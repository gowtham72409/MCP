import os
import uuid
import json
import asyncio
import datetime
import tempfile
from fastapi import APIRouter, WebSocket, UploadFile, File, WebSocketDisconnect, Form, HTTPException
from pydantic import BaseModel
from typing import List, Optional
from backend.agents.audio import audio_agent
from backend.agents.video import video_agent
from backend.agents.pdf_agent import pdf_agent, answer_question
from backend.agents.pdf_store import store_pdf, delete_pdf, list_pdfs, get_pdf_meta, query_pdfs
from backend.db import AsyncSessionLocal
from backend.models import AiTaskMemory
from backend.process_task import process_task
from backend.core.semantic_cache import redis, INDEX_KEY, CACHE_PREFIX, STATS_KEY, get_cost_savings, get_cache, set_cached, record_cache_hit, record_cache_miss
from backend.core.gemini_client import task_usage
from backend.core.hitl_manager import create_review, await_feedback, submit_feedback
from backend.core.middleware import AgentRunner, LoggingMiddleware, RetryMiddleware, ValidationMiddleware

router = APIRouter(tags=["router"])
agent_runner = AgentRunner([LoggingMiddleware(), RetryMiddleware(retries=3), ValidationMiddleware()])

UPLOAD_DIR = os.path.join(tempfile.gettempdir(), "multi_ai_agent_uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)

@router.websocket("/ws")
async def websocket_text(ws: WebSocket):
    """
    Unified WebSocket for both standard chat and Human-in-the-Loop retrieval.

    Protocol:
      FE → BE: {"type": "query",        "text": "..."}
      BE → FE: {"type": "hitl_review",  "review_id": "...", "question": "...", "sources": [...]}
      FE → BE: {"type": "hitl_feedback","review_id": "...", "approved_ids": [...], "note": ""}
      BE → FE: {"type": "hitl_answer",  "answer": "...", "chat": "...", "sources": [...]}
      (or standard agent responses for non-sensitive queries)
    """
    await ws.accept()
    recv_queue: asyncio.Queue = asyncio.Queue()

    async def _receiver():
        """Continuously read from the WebSocket and push into the queue."""
        try:
            while True:
                raw = await ws.receive_text()
                try:
                    await recv_queue.put(json.loads(raw))
                except json.JSONDecodeError:
                    await recv_queue.put({"type": "query", "text": raw})
        except WebSocketDisconnect:
            await recv_queue.put(None)
        except Exception as e:
            print(f"[WS] Receiver error: {e}")
            await recv_queue.put(None)

    recv_task = asyncio.create_task(_receiver())
    try:
        from backend.core.gemini_client import ask_gemini
        
        while True:
            msg = await recv_queue.get()
            if msg is None:
                break  # client disconnected

            msg_type = msg.get("type", "query")

            if msg_type == "hitl_feedback":
                ok = submit_feedback(msg.get("review_id", ""), msg)
                if not ok:
                    print(f"[HITL] Unknown review_id: {msg.get('review_id')}")
            else:
                text = msg.get("text", "").strip()
                if text:
                    async def _handle_query(ws, text):
                        has_pdfs = msg.get("has_pdfs", False)
                        pdf_ids = msg.get("pdf_ids")

                        cached = await get_cache(text)
                        if cached:
                            if cached.get("type") == "hitl_answer" or not has_pdfs:
                                await record_cache_hit(cached.get("usage", {}))
                                await ws.send_json(cached)
                                return

                        prompt = (
                            f"Is the following question sensitive, dangerous, inappropriate, "
                            f"or does it require human review (e.g. asking for personal info, destructive actions)? "
                            f"Answer ONLY 'YES' or 'NO'.\n\nQuestion: {text}"
                        )
                        is_sensitive_resp = await ask_gemini(prompt)
                        is_sensitive = "YES" in is_sensitive_resp.upper()

                        if is_sensitive:
                            print(f"[HITL] Query flagged as sensitive: {text}")
                            await _run_hitl(ws, text)
                        else:
                            
                            if has_pdfs:
                                result = await answer_question(text, pdf_ids=pdf_ids)
                                if result.get("type") == "not_in_pdf":
                                    if cached:
                                        await record_cache_hit(cached.get("usage", {}))
                                        result = {**cached, "from_cache": True}
                                    else:
                                        async with AsyncSessionLocal() as session:
                                            result = await process_task(text, session, skip_cache=True)
                            else:
                                async with AsyncSessionLocal() as session:
                                    result = await process_task(text, session, skip_cache=True)
                            await ws.send_json(result)

                    asyncio.create_task(_handle_query(ws, text))
    except Exception as e:
        print(f"[WS] Dispatcher error: {e}")
    finally:
        recv_task.cancel()
        try:
            await recv_task
        except asyncio.CancelledError:
            pass
        print("Client disconnected (Unified WS)")


async def _run_hitl(ws: WebSocket, question: str) -> None:
    """
    Full Human-in-the-Loop pipeline for a single question.
    1. Retrieve candidate sources (PDF store → research fallback)
    2. Send hitl_review to frontend and suspend
    3. Receive approved source IDs from human
    4. Generate LLM answer from approved sources only
    5. Send hitl_answer back
    """
    from backend.agents.research import research_agent
    from backend.core.gemini_client import ask_gemini

    review_id = str(uuid.uuid4())
    sources: list = []

  
    try:
        pdfs = await list_pdfs()
        if pdfs:
            hits = await query_pdfs(question, top_k_per_pdf=5, score_threshold=0.40)
            for i, h in enumerate(hits[:10]):
                sources.append({
                    "id":          i,
                    "source_type": "pdf",
                    "pdf_id":      h["pdf_id"],
                    "filename":    h["filename"],
                    "page":        h["page"],
                    "score":       h["score"],
                    "text":        h["text"][:500],
                })
    except Exception as e:
        print(f"[HITL] PDF retrieval error: {e}")

    if not sources:
        try:
            raw = await agent_runner.run(research_agent, question)
            chunks = [c.strip() for c in str(raw).split("\n\n") if len(c.strip()) > 40][:8]
            for i, chunk in enumerate(chunks):
                sources.append({
                    "id":          i,
                    "source_type": "research",
                    "title":       f"Research Result #{i + 1}",
                    "text":        chunk[:500],
                })
        except Exception as e:
            print(f"[HITL] Research retrieval error: {e}")

    if not sources:
        await ws.send_json({
            "type":    "hitl_answer",
            "answer":  "No relevant information could be retrieved for this question.",
            "chat":    "No relevant information could be retrieved for this question.",
            "sources": [],
        })
        return


    context = "\n\n---\n\n".join(
        "[Source {}: {} {}]\n{}".format(
            s["id"] + 1,
            s.get("filename") or s.get("title", "Research"),
            ("• Page " + str(s["page"])) if "page" in s else "",
            s["text"],
        )
        for s in sources
    )

    prompt = (
        f"You are an expert assistant. Answer the question using ONLY the sources below.\n"
        f"IMPORTANT: Do NOT include any citations like [Source 1] or a 'Sources' section at the end. Provide ONLY the answer text.\n\n"
        f"Sources:\n---\n{context}\n---\n\nQuestion: {question}"
    )
    draft_answer = await ask_gemini(prompt)

    
    create_review(review_id, question=question, draft_answer=draft_answer, sources=sources)
    await ws.send_json({
        "type":      "hitl_wait",
        "message":   "⏳ Sensitive topic detected. Waiting for admin approval..."
    })

   
    feedback = await await_feedback(review_id, timeout=3600.0)

    if not feedback:
        await ws.send_json({
            "type":   "hitl_timeout",
            "answer": "⏱ Admin review timed out. Please try again later.",
            "chat":   "⏱ Admin review timed out. Please try again later.",
            "sources": [],
        })
        return

    action = feedback.get("action", "reject")
    edited_answer = feedback.get("edited_answer", "")

    out_sources = [
        {
            "filename": s.get("filename") or s.get("title", "Research"),
            "page":     s.get("page"),
            "score":    s.get("score"),
        }
        for s in sources
    ]

    if action == "approve":
        final_answer = draft_answer
    elif action == "edit":
        final_answer = edited_answer
    else:
        final_answer = " The admin has rejected this sensitive query."
        out_sources = []

    usage = task_usage.get() if task_usage.get() else {"input_tokens": 0, "output_tokens": 0}

    result_dict = {
        "type":    "hitl_answer",
        "answer":  final_answer,
        "chat":    final_answer,
        "sources": out_sources,
        "usage":   usage,
    }

    if action in ("approve", "edit"):
        try:
            await record_cache_miss(usage)         
            await set_cached(question, result_dict) 
        except Exception as e:
            print(f"[HITL Cache] Error storing to cache: {e}")

    await ws.send_json(result_dict)


@router.get("/admin/reviews")
async def get_admin_reviews():
    """Admin endpoint to fetch all pending sensitive reviews."""
    from backend.core.hitl_manager import get_all_pending
    return {"reviews": get_all_pending()}

class AdminFeedbackRequest(BaseModel):
    action: str  
    edited_answer: str = ""

@router.post("/admin/reviews/{review_id}")
async def submit_admin_feedback(review_id: str, req: AdminFeedbackRequest):
    """Admin endpoint to resolve a pending review."""
    from backend.core.hitl_manager import submit_feedback
    ok = submit_feedback(review_id, req.dict())
    if not ok:
        raise HTTPException(status_code=404, detail="Review ID not found or already processed")
    return {"status": "success", "message": f"Review {review_id} resolved with action {req.action}"}

@router.websocket("/admin/ws")
async def admin_ws(ws: WebSocket):
    """WebSocket for Admin Dashboard to push queue updates without polling log spam."""
    await ws.accept()
    from backend.core.hitl_manager import get_all_pending
    try:
        while True:
            await ws.send_json({"reviews": get_all_pending()})
            await asyncio.sleep(3)
    except WebSocketDisconnect:
        pass
    except Exception as e:
        print(f"[Admin WS] Error: {e}")

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
                transcript = await agent_runner.run(audio_agent, tmp_path)
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
        text = await agent_runner.run(audio_agent, path)
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
        text = await agent_runner.run(video_agent, path)
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
        result = await agent_runner.run(pdf_agent, path, question=question, original_filename=file.filename)
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

    return await agent_runner.run(answer_question, req.question, pdf_ids=req.pdf_ids)


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