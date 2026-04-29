import os
import uuid
import datetime
import tempfile
from fastapi import APIRouter, WebSocket, UploadFile, File, WebSocketDisconnect, Form, HTTPException
from pydantic import BaseModel
from typing import List, Optional
from backend.agents.audio import audio_agent
from backend.agents.video import video_agent
from backend.agents.pdf_agent import pdf_agent, answer_question
from backend.agents.pdf_store import store_pdf, delete_pdf, list_pdfs, get_pdf_meta
from backend.db import AsyncSessionLocal
from backend.models import AiTaskMemory
from backend.process_task import process_task
from backend.core.semantic_cache import redis, INDEX_KEY, CACHE_PREFIX, STATS_KEY, get_cost_savings

router = APIRouter(tags=["router"])

UPLOAD_DIR = os.path.join(tempfile.gettempdir(), "multi_ai_agent_uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

@router.websocket("/ws")
async def websocket_text(ws: WebSocket):
    await ws.accept()
    try:
        while True:
            text = await ws.receive_text()
            async with AsyncSessionLocal() as session:
                result = await process_task(text, session)
            await ws.send_json(result)
    except WebSocketDisconnect:
        print("Client disconnected (text WS)")
    except Exception as e:
        print(f"WebSocket error: {e}")


@router.websocket("/ws/mic")
async def websocket_mic(ws: WebSocket):
    await ws.accept()
    tmp_path = None
    try:
        while True:
            data     = await ws.receive_bytes()
            tmp_path = f"{UPLOAD_DIR}/mic_{uuid.uuid4()}.webm"
            with open(tmp_path, "wb") as f:
                f.write(data)
            try:
                transcript = await audio_agent(tmp_path)
                with open(tmp_path, "rb") as f:
                    file_bytes = f.read()
                await ws.send_json({"type": "transcript", "text": transcript})
                async with AsyncSessionLocal() as session:
                    result = await process_task(
                        transcript, session, media_type="audio", file_bytes=file_bytes
                    )
                await ws.send_json({**result, "type": "agent_result"})
            finally:
                _delete(tmp_path); tmp_path = None
    except WebSocketDisconnect:
        print("Client disconnected (mic WS)")
    except Exception as e:
        print(f"Mic WebSocket error: {e}")
    finally:
        if tmp_path:
            _delete(tmp_path)


@router.delete("/cache/clear")
async def clear_semantic_cache():
    keys = await redis.keys(f"{CACHE_PREFIX}*")
    if keys:
        await redis.delete(*keys)
    await redis.delete(INDEX_KEY)
    return {"cleared": len(keys) + 1}


@router.get("/stats/cost-savings")
async def cost_savings_endpoint():
    return await get_cost_savings()


@router.post("/cache/clear-all")
async def clear_all_cache():
    """Clear all semantic cache entries AND reset stats metrics."""
    keys = await redis.keys(f"{CACHE_PREFIX}*")
    if keys:
        await redis.delete(*keys)
    await redis.delete(INDEX_KEY)
    await redis.delete(STATS_KEY)
    return {"status": "cleared", "cache_keys_deleted": len(keys)}


@router.post("/upload-audio")
async def upload_audio(file: UploadFile = File(...)):
    path = _tmp_path(file.filename)
    await _save_upload(file, path)
    try:
        text = await audio_agent(path)
        with open(path, "rb") as f:
            file_bytes = f.read()
        async with AsyncSessionLocal() as session:
            result = await process_task(text, session, media_type="audio", file_bytes=file_bytes)
        return {"type": "audio", "transcript": text, **result}
    finally:
        _delete(path)


@router.post("/upload-video")
async def upload_video(file: UploadFile = File(...)):
    path = _tmp_path(file.filename)
    await _save_upload(file, path)
    try:
        text = await video_agent(path)
        with open(path, "rb") as f:
            file_bytes = f.read()
        async with AsyncSessionLocal() as session:
            result = await process_task(text, session, media_type="video", file_bytes=file_bytes)
        return {"type": "video", "transcript": text, **result}
    finally:
        _delete(path)


@router.post("/upload-pdf")
async def upload_pdf(
    file: UploadFile = File(...),
    question: str    = Form(default=""),
):
    """
    Upload a single PDF.  The file is indexed into the PDF store folder.
    Optionally answer a question immediately after indexing.
    """
    path = _tmp_path(file.filename)
    await _save_upload(file, path)
    try:
        result = await pdf_agent(path, question=question, original_filename=file.filename)
        with open(path, "rb") as f:
            pdf_bytes = f.read()

        task_id = result.get("pdf_id", str(uuid.uuid4()))
        async with AsyncSessionLocal() as session:
            record = AiTaskMemory(
                task_id=task_id,
                user_input=f"Uploaded PDF: {file.filename}",
                created_at=datetime.datetime.now(),
                updated_at=datetime.datetime.now(),
                pdf_file=pdf_bytes,
            )
            session.add(record)
            await session.commit()

        return {"type": "pdf", **result}
    finally:
        _delete(path)


@router.post("/upload-pdfs")
async def upload_pdfs(files: List[UploadFile] = File(...)):
    """
    Upload multiple PDFs at once.
    Returns a list of meta objects, one per file.
    All uploaded PDFs become immediately searchable via /ask-pdfs.
    """
    results = []
    for file in files:
        path = _tmp_path(file.filename)
        await _save_upload(file, path)
        try:
            file_bytes = open(path, "rb").read()
            meta = await store_pdf(file_bytes, file.filename)

            async with AsyncSessionLocal() as session:
                record = AiTaskMemory(
                    task_id=meta["pdf_id"],
                    user_input=f"Uploaded PDF: {file.filename}",
                    created_at=datetime.datetime.now(),
                    updated_at=datetime.datetime.now(),
                    pdf_file=file_bytes,
                )
                session.add(record)
                await session.commit()

            results.append({"type": "pdf", **meta})
        except Exception as e:
            results.append({"type": "error", "filename": file.filename, "error": str(e)})
        finally:
            _delete(path)

    return {"uploaded": len(results), "pdfs": results}


@router.get("/pdfs")
async def get_pdfs():
    """List all currently stored PDFs with their meta info."""
    pdfs = await list_pdfs()
    return {"pdfs": pdfs, "count": len(pdfs)}


@router.delete("/pdfs/{pdf_id}")
async def remove_pdf(pdf_id: str):
    """
    Delete a PDF by its pdf_id.
    - Removes the folder from disk.
    - Evicts it from the Redis store index.
    - Invalidates ALL cached Q&A answers that referenced this PDF.
    After deletion, asking the same question will go to the LLM fresh
    (no stale cache hit).
    """
    meta = await get_pdf_meta(pdf_id)
    if not meta:
        raise HTTPException(status_code=404, detail=f"PDF {pdf_id} not found")

    result = await delete_pdf(pdf_id)
    return {
        "deleted":        pdf_id,
        "filename":       meta.get("filename"),
        "cache_evicted":  result.get("cache_evicted", 0),
        "message":        "PDF deleted and all related cache entries invalidated.",
    }


class AskPdfsRequest(BaseModel):
    question: str
    pdf_ids:  Optional[List[str]] = None   # None = search ALL stored PDFs


@router.post("/ask-pdfs")
async def ask_pdfs(req: AskPdfsRequest):
    """
    Answer a question across one, several, or ALL stored PDFs.

    - Uses Gemini text-embedding-004 for semantic page retrieval.
    - Results are cached in Redis per (pdf_id set + question).
    - If any PDF in the set is deleted, its cache entries are auto-evicted,
      so the next identical question goes back to the LLM.

    Response:
      {
        "type":       "pdf_answer" | "not_in_pdf",
        "answer":     "...",
        "sources":    [{"pdf_id", "filename", "page", "score"}, ...],
        "from_cache": true | false   (only present on cache hits)
      }
    """
    if not req.question.strip():
        raise HTTPException(status_code=400, detail="question must not be empty")

    return await answer_question(req.question, pdf_ids=req.pdf_ids)


class AskPdfRequest(BaseModel):
    question: str
    pdf_text: str


@router.post("/ask-pdf")
async def ask_pdf(req: AskPdfRequest):
    """
    Legacy endpoint: front-end sends raw PDF text.
    Delegates to the new multi-PDF answer pipeline using in-memory text
    (not persisted to the store).
    """
    from backend.core.gemini_client import ask_gemini
    import re

    def get_relevant_pages(full_text: str, question: str, top_k: int = 15) -> str:
        pages = re.split(r'(?=\[Page \d+\]\n)', full_text)
        pages = [p.strip() for p in pages if p.strip()]
        if len(pages) <= top_k:
            return full_text
        stop_words = {
            "what","is","the","in","of","and","a","to","for","on","with",
            "as","by","an","this","that","are","from","how","why","can",
            "you","tell","explain","about","details","mention",
        }
        q_words = [
            w.lower() for w in re.findall(r'\w+', question)
            if w.lower() not in stop_words and len(w) > 2
        ]
        selected = {0, 1, 2} if len(pages) > 2 else set(range(len(pages)))
        if q_words:
            scores = sorted(
                [(sum(p.lower().count(qw) for qw in q_words), i) for i, p in enumerate(pages)],
                reverse=True,
            )
            for score, i in scores:
                if len(selected) >= top_k:
                    break
                if score > 0:
                    selected.add(i)
        for i in range(len(pages)):
            if len(selected) >= top_k:
                break
            selected.add(i)
        return "\n\n".join(pages[i] for i in sorted(selected))

    context = get_relevant_pages(req.pdf_text, req.question)

    relevance = (await ask_gemini(
        f"Does this document contain enough information to answer '{req.question}'?\n"
        f"Reply ONLY with RELEVANT or NOT_RELEVANT.\n\n{context}"
    )).strip().upper()

    if "NOT_RELEVANT" in relevance or "RELEVANT" not in relevance:
        return {"type": "not_in_pdf", "redirect": True, "question": req.question}

    answer = await ask_gemini(
        f"Answer using ONLY the document below.\n"
        f"End with: Sources: Page X, Page Y\n\n"
        f"Document:\n{context}\n\nQuestion: {req.question}"
    )

    src_match = re.search(r'Sources\s*:\s*(.+)', answer, re.IGNORECASE)
    if not src_match or src_match.group(1).strip().lower() in ("none", "", "n/a"):
        return {"type": "not_in_pdf", "redirect": True, "question": req.question}

    return {"type": "pdf_answer", "answer": answer, "chat": answer}


def _tmp_path(filename: str) -> str:
    return os.path.join(UPLOAD_DIR, f"{uuid.uuid4()}_{filename}")


async def _save_upload(file: UploadFile, path: str):
    content = await file.read()
    with open(path, "wb") as f:
        f.write(content)


def _delete(path: str):
    try:
        if path and os.path.exists(path):
            os.remove(path)
    except Exception as e:
        print(f"Could not delete {path}: {e}")