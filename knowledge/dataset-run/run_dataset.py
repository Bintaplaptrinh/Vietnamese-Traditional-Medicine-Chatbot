"""Run ai-knowledge-graph over the complete corpus within a rolling API budget."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timedelta, timezone
import fcntl
import hashlib
import json
import logging
import math
import os
from pathlib import Path
import re
import sys
import tomllib
import unicodedata

import pymupdf
import requests

RUN_DIR = Path(__file__).resolve().parent
PROJECT = RUN_DIR.parent.parent
REPO = RUN_DIR.parent / "ai-knowledge-graph"
sys.path.insert(0, str(REPO / "src"))

from knowledge_graph.config import load_config, validate_config
from knowledge_graph.entity_standardization import limit_predicate_length, standardize_entities
from knowledge_graph.exports import export_graph
from knowledge_graph.llm import LLMClient, LLMError, extract_json_from_text
from knowledge_graph.main import normalize_triple, save_graph_meta
from knowledge_graph.prompts import system_prompt_for
from knowledge_graph.visualization import render_knowledge_graph


def write_json(path, value):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def read_json(path, default):
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def prepare():
    """Partition all words, preserving document IDs and exact word ranges."""
    documents_path = RUN_DIR / "documents.json"
    inventory = read_json(RUN_DIR / "input-inventory.json", [])
    fingerprints = [
        {"name": p.name, "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
        for p in sorted((PROJECT / "Dataset").glob("*.pdf"))
    ]
    manifest_path = RUN_DIR / "batches.json"
    existing = read_json(manifest_path, {})
    extractor = "pymupdf-control-clean-v1"
    if existing.get("inputs") == fingerprints and existing.get("extractor") == extractor and documents_path.exists():
        return existing, read_json(documents_path, {})
    if (RUN_DIR / "checkpoints").exists() and any((RUN_DIR / "checkpoints").glob("*.json")):
        raise RuntimeError("Dataset changed: existing checkpoints require a separate output folder.")
    documents, inventory = {}, []
    for entry in fingerprints:
        with pymupdf.open(PROJECT / "Dataset" / entry["name"]) as pdf:
            pages = [page.get_text() for page in pdf]
        text = "\n\n".join(pages)
        text = unicodedata.normalize("NFC", text)
        text = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]", " ", text)
        if not text.strip():
            raise RuntimeError(f"No text could be extracted: {entry['name']}")
        documents[entry["name"]] = text
        inventory.append({"file": entry["name"], "pages": len(pages), "words": len(text.split()),
                          "characters": len(text), "empty_pages": sum(not page.strip() for page in pages),
                          "extractor": extractor, "preview": text[:180]})
    write_json(RUN_DIR / "input-inventory.json", inventory)
    total_words = sum(len(text.split()) for text in documents.values())
    batch_words = math.ceil(total_words / 26)
    batches, current, size = [], [], 0
    for name, text in documents.items():
        words = text.split()
        start = 0
        while start < len(words):
            end = min(len(words), start + batch_words - size)
            current.append({"document": name, "start": start, "end": end})
            size += end - start
            start = end
            if size == batch_words:
                batches.append({"id": len(batches) + 1, "words": size, "segments": current})
                current, size = [], 0
    if current:
        batches.append({"id": len(batches) + 1, "words": size, "segments": current})
    ranges = {name: [] for name in documents}
    for batch in batches:
        for segment in batch["segments"]:
            ranges[segment["document"]].append((segment["start"], segment["end"]))
    for name, spans in ranges.items():
        assert spans[0][0] == 0 and spans[-1][1] == len(documents[name].split())
        assert all(left[1] == right[0] for left, right in zip(spans, spans[1:]))
    assert sum(batch["words"] for batch in batches) == total_words
    manifest = {"inputs": fingerprints, "extractor": extractor, "documents": len(documents),
                "pages": sum(row.get("pages", 0) for row in inventory),
                "words": total_words, "batch_count": len(batches), "batches": batches}
    write_json(documents_path, documents)
    write_json(manifest_path, manifest)
    return manifest, documents


class BudgetSession:
    """Record every HTTP POST before sending; no hidden retries or fallback calls."""
    def __init__(self, session, limit):
        self.session = session
        self.limit = min(limit, 30)
        self.ledger_path = RUN_DIR / "api-ledger.json"

    def recent(self):
        threshold = datetime.now(timezone.utc) - timedelta(hours=24)
        return [entry for entry in read_json(self.ledger_path, [])
                if datetime.fromisoformat(entry["started"]) > threshold and entry.get("sent") is not False]

    def post(self, *args, **kwargs):
        entries = read_json(self.ledger_path, [])
        if len(self.recent()) >= self.limit:
            raise LLMError(f"Stopped at {self.limit} API attempts in the last 24 hours. Resume later.")
        entry = {"started": datetime.now(timezone.utc).isoformat(), "status": "pending"}
        entries.append(entry)
        write_json(self.ledger_path, entries)
        print(f"API attempt {len(self.recent())}/{self.limit} (rolling 24h)", flush=True)
        try:
            response = self.session.post(*args, **kwargs)
            entry["status"] = response.status_code
            try:
                entry["usage"] = response.json().get("usage", {})
            except (ValueError, AttributeError):
                pass
            return response
        except Exception as exc:
            entry["status"] = type(exc).__name__
            if isinstance(exc, requests.ConnectionError) and "NameResolutionError" in str(exc):
                entry["sent"] = False
                entry["note"] = "DNS resolution failed before an HTTP request could be sent."
            raise
        finally:
            entry["finished"] = datetime.now(timezone.utc).isoformat()
            write_json(self.ledger_path, entries)


def batch_prompt(batch, documents, config):
    segments = {}
    blocks = []
    for index, segment in enumerate(batch["segments"], 1):
        sid = f"S{index:03d}"
        text = " ".join(documents[segment["document"]].split()[segment["start"]:segment["end"]])
        segments[sid] = (segment, text)
        blocks.append(f"BEGIN DOCUMENT {sid}\nFilename: {segment['document']}\n{text}\nEND DOCUMENT {sid}")
    prompt = system_prompt_for("main_system", config) + "\n"
    prompt += (
        "Return ONLY a complete, compact JSON array. EVERY item MUST have these SEVEN fields: "
        "subject, predicate, object, subject_type, object_type, document, source. "
        'Example: {"subject":"nghiên cứu","predicate":"khảo sát","object":"đau thắt lưng",'
        '"subject_type":"work","object_type":"concept","document":"S001",'
        '"source":"nghiên cứu khảo sát đau thắt lưng"}. '
        "Extract the most informative, explicitly stated medical and research relationships from EVERY "
        "document block. Give balanced coverage across documents and across the whole supplied text. "
        "Prioritize study subjects, diseases, symptoms, diagnoses, treatments, herbs, acupoints, outcomes, "
        "methods, and measured results. ALSO extract computing, decision-support, algorithms, expert "
        "systems, and other nonclinical knowledge when a document discusses them; never skip a document "
        "because it is about technology. Do not infer or generalize treatment findings beyond the study. "
        "Keep quantitative results tied to the study or its participants, and distinguish participants' "
        "opinions from observed clinical outcomes. Use consistent, atomic, lowercase entity names. "
        "Entity types must be person, organization, place, event, technology, product, work, date, concept. "
        "Do not extract the bibliography or repetitive journal headers. Aim for 15-25 distinct triples "
        "per document block, with a hard maximum of 120 triples in the entire array. "
        "Add a document field holding the EXACT block ID (S001, S002, etc.) to EVERY triple. "
        "Add a source field holding a short VERBATIM contiguous quotation from that document "
        "(at most 100 characters); never invent a quotation. Keep entities specific to the study when "
        "necessary. Use Vietnamese entity names and predicates, English JSON keys and entity types. "
        "Keep predicates at most 3 words. Return compact, complete, valid JSON, no markdown or commentary."
    )
    prompt += "\n\nDOCUMENTS TO ANALYZE:\n" + "\n\n".join(blocks)
    prompt += "\n\nReturn the JSON array now. EVERY triple MUST include document (Sxxx) and source."
    return prompt, segments


def validate_response(content, batch, segments):
    # Repair duplicated quote/space tokens before known property names only.
    # The original reply stays on disk, and no subject/predicate/object value changes.
    content = re.sub(
        r'([,{]\s*)"\s+"(?=(?:subject|predicate|object|subject_type|object_type|document|source)"\s*:)',
        r'\1"', content)
    items = extract_json_from_text(content)
    # A stray unclosed quote can confuse the package's balanced-brace salvage.
    # Decode each flat SPO object independently, without altering any values.
    recovered = []
    decoder = json.JSONDecoder()
    for match in re.finditer(r'\{\s*"subject"\s*:', content):
        try:
            item, _ = decoder.raw_decode(content, match.start())
        except json.JSONDecodeError:
            continue
        if isinstance(item, dict):
            recovered.append(item)
    if len(recovered) > len(items or []):
        print(f"Recovered {len(recovered)} individually valid JSON objects", flush=True)
        items = recovered
    if not isinstance(items, list) or not items:
        raise ValueError("Expected a non-empty complete JSON array.")
    triples, rejected = [], []
    for item in items:
        if not isinstance(item, dict) or not all(isinstance(item.get(k), str) and item[k].strip()
                                               for k in ("subject", "predicate", "object", "document")):
            rejected.append(item)
            continue
        sid = item["document"]
        if sid not in segments:
            rejected.append(item)
            continue
        segment, text = segments[sid]
        triple = normalize_triple(item, text)
        triple["predicate"] = limit_predicate_length(triple["predicate"])
        triple.update(document=segment["document"], chunk=batch["id"],
                      document_word_start=segment["start"], document_word_end=segment["end"])
        source = " ".join(str(item.get("source", "")).split())
        if source and source.casefold() in text.casefold():
            triple["source"] = source
            triple["source_verified"] = True
        else:
            triple.pop("source", None)
            triple["source_verified"] = False
        triples.append(triple)
    represented = {t["document"] for t in triples}
    missing = sorted({s["document"] for s, _ in segments.values()} - represented)
    if not triples:
        raise ValueError(f"No valid triples in batch: {missing}")
    if missing:
        print(f"Documents without triples in this block: {missing}; checking overall coverage at the end", flush=True)
    return triples, rejected


def render(manifest, config):
    raw, completed = [], []
    for batch in manifest["batches"]:
        checkpoint = RUN_DIR / "checkpoints" / f"batch-{batch['id']:02d}.json"
        if checkpoint.exists():
            raw.extend(read_json(checkpoint, {})["triples"])
            completed.append(batch["id"])
    for repair_path in (RUN_DIR / "checkpoints").glob("repair*.json"):
        raw.extend(read_json(repair_path, {}).get("triples", []))
    if not raw:
        write_json(RUN_DIR / "run-report.json", {
            "complete": False, "completed_batches": [], "total_batches": manifest["batch_count"],
            "input_documents": manifest["documents"], "input_pages": manifest["pages"],
            "input_words": manifest["words"], "documents_with_triples": 0,
            "api_attempts": read_json(RUN_DIR / "api-ledger.json", []),
            "status": "No batch completed; no graph generated."
        })
        return
    triples = standardize_entities(raw, config)
    seen, unique = set(), []
    for triple in triples:
        key = tuple(triple.get(k) for k in ("subject", "predicate", "object", "document", "source"))
        if key not in seen:
            unique.append(triple)
            seen.add(key)
    write_json(RUN_DIR / "dataset_graph.json", unique)
    stats, graph_data = render_knowledge_graph(unique, str(RUN_DIR / "dataset_graph.html"), config=config)
    save_graph_meta(str(RUN_DIR / "dataset_graph.json"), graph_data, config)
    export_graph(unique, str(RUN_DIR / "dataset_graph.html"), ["csv", "graphml", "cypher"], graph_data)
    coverage = Counter(t["document"] for t in unique)
    missing = sorted(entry["name"] for entry in manifest["inputs"] if entry["name"] not in coverage)
    report = {"complete": len(completed) == manifest["batch_count"] and not missing, "completed_batches": completed,
              "total_batches": manifest["batch_count"], "input_documents": manifest["documents"],
              "input_pages": manifest["pages"], "input_words": manifest["words"],
              "documents_with_triples": len(coverage), "triples_by_document": dict(coverage),
              "missing_documents": missing,
              "verified_source_triples": sum(t.get("source_verified", False) for t in unique),
              "stats": stats, "inference_enabled": False,
              "extraction_scope": "Key relationships, 15-25 per document block; maximum 120 per batch.",
              "api_attempts": read_json(RUN_DIR / "api-ledger.json", [])}
    write_json(RUN_DIR / "run-report.json", report)
    print(json.dumps({k: v for k, v in report.items() if k not in ("triples_by_document", "api_attempts")},
                     ensure_ascii=False, indent=2), flush=True)


def run_pilot(client, documents, config):
    name = min(documents, key=lambda filename: len(documents[filename].split()))
    batch = {"id": 1, "segments": [{"document": name, "start": 0,
                                   "end": len(documents[name].split())}]}
    prompt, segments = batch_prompt(batch, documents, config)
    prompt += "\nDiagnostic extraction: return at most 15 key triples; a complete JSON array is required."
    client.max_tokens = 4096
    client.timeout = 180
    print(f"Diagnostic document: {name}, {len(documents[name].split())} words; one request only.", flush=True)
    try:
        content = client.complete(prompt)
        (RUN_DIR / "pilot-response.txt").write_text(content, encoding="utf-8")
        triples, rejected = validate_response(content, batch, segments)
        triples = standardize_entities(triples, config)
        write_json(RUN_DIR / "pilot_graph.json", triples)
        stats, graph_data = render_knowledge_graph(triples, str(RUN_DIR / "pilot_graph.html"), config=config)
        save_graph_meta(str(RUN_DIR / "pilot_graph.json"), graph_data, config)
        export_graph(triples, str(RUN_DIR / "pilot_graph.html"), ["csv", "graphml"], graph_data)
        write_json(RUN_DIR / "pilot-report.json", {"complete": True, "document": name,
                   "stats": stats, "rejected": len(rejected), "full_corpus_complete": False})
        print(f"Diagnostic extraction succeeded: {stats}", flush=True)
    except (LLMError, ValueError) as exc:
        write_json(RUN_DIR / "pilot-report.json", {"complete": False, "document": name,
                   "error": str(exc), "full_corpus_complete": False})
        print(f"Diagnostic extraction failed: {exc}", file=sys.stderr, flush=True)
        raise SystemExit(1) from None


def repair_coverage(client, manifest, documents, config):
    represented = set()
    for path in (RUN_DIR / "checkpoints").glob("*.json"):
        represented.update(t["document"] for t in read_json(path, {}).get("triples", []))
    missing = sorted(set(documents) - represented)
    if not missing:
        return
    print(f"Coverage repair for {len(missing)} documents: {missing}", flush=True)
    # All input has already been submitted in the main pass. Use a bounded
    # excerpt per missing document to guarantee balanced coverage in one call.
    char_budget = 160000 // len(missing)
    repair_docs = {name: documents[name][:char_budget] for name in missing}
    batch = {"id": manifest["batch_count"] + 1, "segments": [
        {"document": name, "start": 0, "end": len(repair_docs[name].split())} for name in missing]}
    segments = {}
    blocks = []
    for index, segment in enumerate(batch["segments"], 1):
        sid = f"S{index:03d}"
        text = " ".join(repair_docs[segment["document"]].split())
        segments[sid] = (segment, text)
        blocks.append(f"DOCUMENT {sid}: {segment['document']}\n{text}")
    fields = ["subject", "predicate", "object", "subject_type", "object_type", "source"]
    item_schema = {"type": "object", "properties": {field: {"type": "string"} for field in fields},
                   "required": fields, "additionalProperties": False}
    schema = {"type": "object", "properties": {
        sid: {"type": "array", "minItems": 2, "maxItems": 2, "items": item_schema} for sid in segments},
        "required": list(segments), "additionalProperties": False}
    client.extra_body["response_format"] = {
        "type": "json_schema", "json_schema": {"name": "coverage_repair", "schema": schema}}
    prompt = (
        "Extract exactly TWO informative, explicit facts from EVERY document below. Return a JSON OBJECT "
        "with one required key per document ID, holding its two triples. Every triple must have subject, "
        "predicate, object, subject_type, object_type, source. Use Vietnamese entities and predicates; "
        "predicates at most three words. Types: person, organization, place, event, technology, product, "
        "work, date, concept. Include technological and clinical papers. Prefer specific study subjects, "
        "methods, systems or observed outcomes. Keep claims limited to the study. Source must be a "
        "short, VERBATIM quote from the document, at most 100 characters. No inference. "
        "Do not skip ANY document ID.\n\n" + "\n\n".join(blocks))
    digest = hashlib.sha256(json.dumps({"prompt": prompt, "schema": schema},
                                      sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:12]
    response_path = RUN_DIR / "responses" / f"repair-structured-{digest}.txt"
    if response_path.exists():
        content = response_path.read_text(encoding="utf-8")
    else:
        content = client.complete(prompt)
        response_path.write_text(content, encoding="utf-8")
    mapping = extract_json_from_text(content, expect="object")
    if not isinstance(mapping, dict):
        raise ValueError("Coverage repair did not contain a valid JSON object.")
    flattened = []
    for sid, items in mapping.items():
        if sid in segments and isinstance(items, list):
            flattened.extend(dict(item, document=sid) for item in items if isinstance(item, dict))
    triples, rejected = validate_response(json.dumps(flattened, ensure_ascii=False), batch, segments)
    write_json(RUN_DIR / "checkpoints" / f"repair-structured-{digest}.json", {
        "documents": missing, "triples": triples, "rejected": rejected,
        "scope": "Bounded excerpts from documents omitted in the full-input main pass"})
    remaining = set(missing) - {t["document"] for t in triples}
    if remaining:
        raise ValueError(f"Coverage repair still has missing documents: {sorted(remaining)}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prepare-only", action="store_true")
    parser.add_argument("--render-only", action="store_true")
    parser.add_argument("--pilot", action="store_true", help="Diagnose the endpoint on the smallest complete PDF")
    parser.add_argument("--key-file", type=Path)
    parser.add_argument("--max-calls", type=int, default=30)
    args = parser.parse_args()
    os.chdir(REPO)
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    manifest, documents = prepare()
    print(f"Prepared {manifest['documents']} PDFs, {manifest['words']:,} words, "
          f"{manifest['batch_count']} batches; full input coverage verified.", flush=True)
    if args.prepare_only:
        return
    if args.key_file:
        os.environ["NVIDIA_API_KEY"] = args.key_file.read_text().strip()
    if args.render_only:
        with (RUN_DIR / "config-nvidia.toml").open("rb") as handle:
            config = tomllib.load(handle)
        config["llm"]["api_key"] = None
        config = validate_config(config)
    else:
        config = load_config(str(RUN_DIR / "config-nvidia.toml"))
    if not config:
        raise RuntimeError("Invalid NVIDIA configuration.")
    if args.render_only:
        render(manifest, config)
        return
    run_lock = (RUN_DIR / ".run.lock").open("a")
    try:
        fcntl.flock(run_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        raise RuntimeError("Another dataset run is active. Do not run two copies simultaneously.") from None
    client = LLMClient.from_config(config)
    client._session = BudgetSession(client._session, args.max_calls)
    if args.pilot:
        run_pilot(client, documents, config)
        return
    (RUN_DIR / "checkpoints").mkdir(exist_ok=True)
    (RUN_DIR / "responses").mkdir(exist_ok=True)
    failed = False
    try:
        for batch in manifest["batches"]:
            checkpoint = RUN_DIR / "checkpoints" / f"batch-{batch['id']:02d}.json"
            if checkpoint.exists():
                print(f"Batch {batch['id']}: loaded checkpoint", flush=True)
                continue
            prompt, segments = batch_prompt(batch, documents, config)
            print(f"Batch {batch['id']}/{manifest['batch_count']}: {batch['words']:,} words, "
                  f"{len(segments)} document blocks", flush=True)
            response_path = RUN_DIR / "responses" / f"batch-{batch['id']:02d}.txt"
            if response_path.exists():
                content = response_path.read_text(encoding="utf-8")
                print(f"Batch {batch['id']}: validating saved response without an API call", flush=True)
            else:
                content = client.complete(prompt)  # user-only roles supported by NVIDIA Gemma
                response_path.write_text(content, encoding="utf-8")
            try:
                triples, rejected = validate_response(content, batch, segments)
            except ValueError:
                invalid_cache = client._cache_path(prompt, None)
                if invalid_cache and Path(invalid_cache).exists():
                    Path(invalid_cache).unlink()
                raise
            write_json(checkpoint, {"batch": batch["id"], "triples": triples, "rejected": rejected})
            print(f"Batch {batch['id']}: {len(triples)} triples; checkpoint saved", flush=True)
            if batch["id"] == 1:
                render(manifest, config)
        repair_coverage(client, manifest, documents, config)
    except (LLMError, ValueError) as exc:
        failed = True
        print(f"Stopped: {exc}", file=sys.stderr, flush=True)
    finally:
        render(manifest, config)
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
