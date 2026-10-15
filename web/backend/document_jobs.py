"""Durable bounded PDF jobs, with checkpoints separate from query handling."""
import asyncio
import json
import logging
import os
from pathlib import Path
import time

import httpx

from harness import Budget
from ingestion import parse_pdf, extract_document
from internet import DecisionUnavailable
from knowledge_store import DATA, build_store

LOG = logging.getLogger(__name__)


def save(path, payload):
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    tmp.replace(path)


class DocumentJobs:
    def __init__(self, client, decisions, base_url, api_key, model):
        self.client, self.decisions = client, decisions
        self.base_url, self.api_key, self.model = base_url, api_key, model
        self.semaphore = asyncio.Semaphore(1)
        self.tasks = set()
        self.folder = DATA / "uploads"
        self.folder.mkdir(parents=True, exist_ok=True)
        for path in self.folder.glob("*.json"):
            receipt = json.loads(path.read_text())
            if receipt["status"] in {"queued", "parsing", "extracting", "indexing"}:
                receipt["status"] = "interrupted"
                save(path, receipt)

    def submit(self, data, name, digest):
        path = self.folder / (digest + ".json")
        if path.exists():
            receipt = json.loads(path.read_text())
            return self.public(receipt)
        pdf = self.folder / (digest + ".pdf")
        temp = pdf.with_suffix(".tmp")
        temp.write_bytes(data)
        temp.replace(pdf)
        receipt = {"id": digest, "name": Path(name).name, "status": "queued", "created_at": time.time(),
                   "claims": [], "processed_units": 0, "total_units": 0}
        save(path, receipt)
        self.start(receipt, data)
        return self.public(receipt)

    def start(self, receipt, data):
        task = asyncio.create_task(self.process(receipt, data))
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)

    def get(self, digest):
        path = self.folder / (digest + ".json")
        return json.loads(path.read_text()) if path.exists() else None

    @staticmethod
    def public(receipt):
        return {k: v for k, v in receipt.items() if k != "claims"} | {
            "accepted_claims": sum(c.get("review_status") == "accepted" for c in receipt.get("claims", [])),
            "quarantined_claims": sum(c.get("review_status") != "accepted" for c in receipt.get("claims", []))}

    async def process(self, receipt, data):
        async with self.semaphore:
            path = self.folder / (receipt["id"] + ".json")
            def update(**values):
                receipt.update(values)
                save(path, receipt)
            try:
                update(status="parsing")
                document, units = await asyncio.to_thread(parse_pdf, data, receipt["name"])
                update(document=document, total_units=len(units), status="extracting")
                if self.api_key and os.getenv("TYPESAFE_API_KEY") and units:
                    calls = max(2, min(400, int(os.getenv("INGESTION_MAX_CALLS", "160"))))
                    budget = Budget({"calls": calls, "input_chars": 2000000, "output_tokens": 600000})
                    prior = receipt.get("claims", [])
                    processed = receipt.get("processed_units", 0)
                    def checkpoint(claims, count, errors):
                        update(claims=prior + claims, processed_units=processed + count, errors=errors)
                    async with asyncio.timeout(int(os.getenv("INGESTION_TIMEOUT_SECONDS", "1800"))):
                        result = await extract_document(document, units[processed:], self.client, self.base_url,
                                                        self.api_key, self.model, self.decisions, budget, checkpoint)
                    result["claims"] = prior + result["claims"]
                    result["processed_units"] += processed
                    result["total_units"] = len(units)
                    update(**result)
                else:
                    update(extraction_status="pending_configuration", reason="Configure FPT_API_KEY and TYPESAFE_API_KEY for verified claim extraction")
                update(status="indexing")
                manifest = await asyncio.to_thread(build_store, True)
                status = "needs_ocr" if document["pages_needing_ocr"] else "ready" if receipt.get("extraction_status") == "complete" else "partial"
                update(status=status, snapshot=manifest["snapshot"])
            except asyncio.CancelledError:
                update(status="interrupted")
                raise
            except (TimeoutError, DecisionUnavailable, httpx.HTTPError) as exc:
                update(status="partial", reason=type(exc).__name__, extraction_status="partial")
                try:
                    manifest = await asyncio.to_thread(build_store, True)
                    update(snapshot=manifest["snapshot"])
                except Exception:
                    LOG.exception("Could not index document after extraction interruption")
            except Exception as exc:
                LOG.exception("Document ingestion failed")
                update(status="failed", reason=type(exc).__name__)

    async def close(self):
        for task in self.tasks:
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
