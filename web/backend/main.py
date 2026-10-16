"""Run with: conda activate bqp && python web/backend/main.py."""

import json
import asyncio
import hashlib
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

import httpx
import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, UploadFile, File, Query
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from graph_chat import GraphKnowledge, language_hint
from harness import Harness
from internet import Internet
from reranking import QwenReranker, RerankerUnavailable, MODEL_ID as RERANKER_MODEL_ID
from knowledge_store import build_store
from document_jobs import DocumentJobs
from ingestion import parse_pdf
from medical_skills import get_medical_skills

HERE = Path(__file__).resolve().parent
load_dotenv(HERE / ".env")
os.environ.setdefault("HF_HOME", str(HERE / ".model-cache"))
os.environ.setdefault("USE_TF", "0")
MODEL = os.getenv("FPT_MODEL", "gemma-4-31B-it")
BASE_URL = os.getenv("FPT_BASE_URL", "https://mkp-api.fptcloud.com").rstrip("/")


@asynccontextmanager
async def lifespan(app):
    app.state.skills = get_medical_skills()
    app.state.knowledge = GraphKnowledge()
    async with httpx.AsyncClient(timeout=httpx.Timeout(60, connect=15)) as client:
        app.state.client = client
        app.state.internet = Internet(client)
        app.state.reranker = QwenReranker()
        app.state.jobs = DocumentJobs(client, app.state.internet.decisions, BASE_URL, os.getenv("FPT_API_KEY"), MODEL)
        app.state.index_status = "indexing"
        async def initialize():
            try:
                await asyncio.to_thread(build_store)
                app.state.knowledge.store.refresh()
                app.state.index_status = "ready"
            except Exception:
                logging.exception("Shared knowledge indexing failed")
                app.state.index_status = "failed"
        app.state.index_task = asyncio.create_task(initialize())
        async def warm_reranker():
            try:
                await app.state.reranker.warmup()
                logging.info("Local Qwen reranker ready")
            except RerankerUnavailable:
                # Preserve the existing retrieval fallback when Qwen is unavailable.
                logging.exception("Local Qwen warmup failed; using retrieval ranking")

        async def warm_knowledge():
            await app.state.index_task
            await asyncio.to_thread(app.state.knowledge.store.warmup)
            logging.info("Local knowledge search ready")

        try:
            # Finish model loading and first inference before ASGI startup completes.
            await asyncio.gather(warm_knowledge(), warm_reranker())
            yield
        finally:
            await app.state.jobs.close()
            await app.state.index_task
            app.state.knowledge.store.close()


app = FastAPI(title="Bloop Agent Chat", lifespan=lifespan)


class Message(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=12000)


class ChatRequest(BaseModel):
    messages: list[Message] = Field(min_length=1, max_length=40)
    effort: Literal["low", "medium", "high"] = "low"
    route: Literal["auto", "graph", "web", "hybrid"] = "auto"
    ask_user: bool = True
    branches: list[Literal["graph", "mesh", "vietherbs", "web"]] = Field(default_factory=list, max_length=4)
    documents: list[str] = Field(default_factory=list, max_length=100)


def event(kind, **values):
    return f"data: {json.dumps({'type': kind, **values}, ensure_ascii=False)}\n\n"


@app.get("/api/health")
async def health():
    app.state.knowledge.store.refresh()
    if app.state.knowledge.store.manifest:
        app.state.index_status = "ready"
    return {
        "status": "ok", "model": MODEL, "configured": bool(os.getenv("FPT_API_KEY")),
        "knowledge_graph": app.state.knowledge.path.name,
        "graph_facts": len(app.state.knowledge.index.triples),
        "graph_entities": len(app.state.knowledge.index.names),
        "decision_model": os.getenv("TYPESAFE_MODEL", "jev-latest"),
        "decision_configured": bool(os.getenv("TYPESAFE_API_KEY")),
        "skill_profile": app.state.skills.info(),
        "shared_knowledge": app.state.knowledge.store.manifest,
        "index_status": app.state.index_status,
        "reranker_model": RERANKER_MODEL_ID,
        "reranker_local_ready": app.state.reranker.ready and not app.state.reranker.failed,
        "bm25_local_ready": app.state.knowledge.store.client is not None,
        "search_provider": "searxng" if os.getenv("SEARXNG_URL") else "brave" if os.getenv("BRAVE_SEARCH_API_KEY") else "ddgs",
        "crawler": "crawl4ai" if os.getenv("CRAWL4AI_URL") else "jina",
    }


@app.get("/api/graph")
async def graph(branch: Literal["graph", "mesh", "vietherbs"] = "graph", q: str = Query(default="", max_length=500), limit: int = Query(default=80, ge=1, le=150)):
    result = await asyncio.to_thread(app.state.knowledge.store.graph, branch, q, limit)
    if result["status"] == "indexing" and app.state.index_status == "failed":
        result["status"] = "failed"
    return result


@app.get("/api/documents")
async def documents():
    rows = await asyncio.to_thread(app.state.knowledge.store.documents)
    jobs = [app.state.jobs.public(json.loads(p.read_text())) for p in app.state.jobs.folder.glob("*.json")]
    return {"documents": rows, "jobs": jobs, "index_status": app.state.index_status}


@app.post("/api/documents", status_code=202)
async def upload_document(file: UploadFile = File(...)):
    maximum = max(1, min(100, int(os.getenv("PDF_UPLOAD_MAX_MB", "40")))) * 1024 * 1024
    try:
        data = await file.read(maximum + 1)
        if len(data) > maximum:
            raise HTTPException(413, "PDF vượt giới hạn dung lượng tải lên.")
        if not data.startswith(b"%PDF-") or not (file.filename or "").lower().endswith(".pdf"):
            raise HTTPException(415, "Hãy chọn một tài liệu PDF.")
        try:
            await asyncio.to_thread(parse_pdf, data, file.filename)
        except (ValueError, RuntimeError) as exc:
            raise HTTPException(422, "Không thể đọc PDF hoặc PDF bị khóa/vượt giới hạn trang.") from exc
        digest = hashlib.sha256(data).hexdigest()
        existing = next((d for d in await asyncio.to_thread(app.state.knowledge.store.documents) if d["sha256"] == digest), None)
        if existing:
            return {"id": digest, "status": "already_indexed", "document": existing, "name": existing["name"]}
        return app.state.jobs.submit(data, file.filename, digest)
    finally:
        await file.close()


@app.get("/api/documents/{job_id}")
async def document_job(job_id: str):
    if len(job_id) != 64 or any(c not in "0123456789abcdef" for c in job_id):
        raise HTTPException(404, "Không tìm thấy tài liệu.")
    receipt = app.state.jobs.get(job_id)
    if not receipt:
        raise HTTPException(404, "Không tìm thấy tài liệu.")
    return app.state.jobs.public(receipt)


@app.post("/api/documents/{job_id}/retry", status_code=202)
async def retry_document(job_id: str):
    await document_job(job_id)
    receipt = app.state.jobs.get(job_id)
    if receipt["status"] not in {"failed", "partial", "interrupted"}:
        raise HTTPException(409, "Tài liệu chưa cần xử lý lại.")
    from document_jobs import save
    receipt["status"] = "queued"
    save(app.state.jobs.folder / (job_id + ".json"), receipt)
    app.state.jobs.start(receipt, (app.state.jobs.folder / (job_id + ".pdf")).read_bytes())
    return app.state.jobs.public(receipt)


@app.post("/api/chat")
async def chat(request: ChatRequest):
    api_key = os.getenv("FPT_API_KEY")
    if not api_key:
        raise HTTPException(503, "Set FPT_API_KEY in backend/.env first.")
    if request.messages[-1].role != "user":
        raise HTTPException(422, "The last message must be from the user.")

    async def stream():
        vietnamese = language_hint(request.messages[-1].content) == "vi"
        try:
            result = await Harness(app.state.knowledge, app.state.client, BASE_URL, api_key, MODEL,
                                   app.state.internet, app.state.reranker, skills=app.state.skills).run(request)
            yield event("result", **result)
            answer = result["answer"]
            # Validate grounding before exposing any answer text to the browser.
            yield event("token", content=answer)
            yield event("done")
        except httpx.HTTPStatusError as error:
            code = error.response.status_code
            english = {
                401: "FPT rejected the API key. Check backend/.env.",
                403: "This API key does not have access to the model.",
                404: "FPT could not find the configured model or endpoint.",
                429: "FPT is busy or your quota is exhausted. Try again shortly.",
            }
            vietnamese_errors = {
                401: "FPT từ chối khóa API. Hãy kiểm tra backend/.env.",
                403: "Khóa API này không có quyền truy cập mô hình.",
                404: "FPT không tìm thấy mô hình hoặc địa chỉ API đã cấu hình.",
                429: "FPT đang bận hoặc bạn đã hết hạn mức. Vui lòng thử lại sau.",
            }
            message = vietnamese_errors.get(code, f"FPT trả về lỗi HTTP {code}. Vui lòng thử lại.") if vietnamese else english.get(code, f"FPT returned HTTP {code}. Please try again.")
            yield event("error", message=message)
        except httpx.TimeoutException:
            yield event("error", message="Phản hồi mất quá nhiều thời gian. Vui lòng thử lại." if vietnamese else "The response took too long. Please try again.")
        except httpx.RequestError:
            yield event("error", message="Không thể kết nối tới FPT. Hãy kiểm tra kết nối và thử lại." if vietnamese else "Could not reach FPT. Check your connection and try again.")
        except OSError:
            yield event("error", message="Không thể đọc đồ thị tri thức. Vui lòng kiểm tra cấu hình." if vietnamese else "Could not read the knowledge graph. Please check its configuration.")
        except (ValueError, TypeError, KeyError, AttributeError):
            yield event("error", message="Không thể xử lý dữ liệu phản hồi hoặc đồ thị tri thức. Vui lòng thử lại." if vietnamese else "Could not process the response or knowledge graph data. Please try again.")

    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# Mount only the frontend; backend settings never become public files.
app.mount("/", StaticFiles(directory=HERE.parent / "frontend", html=True), name="frontend")

if __name__ == "__main__":
    uvicorn.run(app, host=os.getenv("HOST", "127.0.0.1"), port=int(os.getenv("PORT", "8000")))
