import json
import hashlib
from backend.redis_client import redis
from backend.core.gemini_client import ask_gemini
from backend.agents.pdf_store import store_pdf,list_pdfs,query_pdfs,PDF_CACHE_PREFIX
 
QA_CACHE_TTL = 60 * 60 * 12   
  
def qa_cache_key(pdf_ids: list[str], question: str):
    """
    One cache key per unique (set-of-pdfs, question).
    We also write a per-pdf reverse index so delete_pdf can evict these keys.
    Key format:  pdf_cache:<pdf_id>:<hash>   (one entry per pdf_id in the set)
    We store the actual answer under the canonical hash key.
    """
    sorted_ids = sorted(pdf_ids)
    canonical  = "|".join(sorted_ids) + "||" + question.strip().lower()
    return hashlib.sha3_256(canonical.encode()).hexdigest()[:24]
 
 
async def get_qa_cache(pdf_ids: list[str], question: str):
    key = qa_cache_key(pdf_ids, question)
    raw = await redis.get(f"pdf_qa:{key}")
    if raw:
        print(f"[PDFAgent] Cache HIT  key={key}")
        return json.loads(raw)
    return None
 
async def set_qa_cache(pdf_ids: list[str], question: str, result: dict):
    key = qa_cache_key(pdf_ids, question)
    payload = json.dumps(result)
    await redis.setex(f"pdf_qa:{key}", QA_CACHE_TTL, payload)
    for pdf_id in pdf_ids:
        reverse_key = f"{PDF_CACHE_PREFIX}{pdf_id}:{key}"
        await redis.setex(reverse_key, QA_CACHE_TTL, key)
 
    print(f"[PDFAgent] Cache STORED  key={key}  pdfs={pdf_ids}")
 
async def pdf_agent(file_path: str, question: str = "", original_filename: str = "") -> dict:
    """
    Legacy-compatible entry point used by router /upload-pdf.
    Indexes the PDF into the store; answers question if provided.
    Pass original_filename to avoid storing the UUID-prefixed temp path name.
    """
    with open(file_path, "rb") as f:
        file_bytes = f.read()
 
    import os
    if original_filename:
        filename = original_filename
    else:
        basename = os.path.basename(file_path)
        filename = basename.split("_", 1)[-1] if "_" in basename else basename
 
    meta = await store_pdf(file_bytes, filename)
    pdf_id = meta["pdf_id"]
 
    if not question:
        return {
            "pdf_id":      pdf_id,
            "filename":    filename,
            "page_count":  meta["page_count"],
            "indexed_only": True,
            "text":        "",        
        }
 
    result = await answer_question(question, pdf_ids=[pdf_id])
    return {**result, "pdf_id": pdf_id, "page_count": meta["page_count"]}
   
async def answer_question(
    question: str,
    pdf_ids: list[str] | None = None,
) -> dict:
    """
    Answer a question across all active (or specified) PDFs.
    Returns:
      {
        "type":    "pdf_answer" | "not_in_pdf",
        "answer":  "...",
        "sources": [{"pdf_id":…, "filename":…, "page":…, "score":…}, …],
        "chat":    "..."
      }
    """
    if pdf_ids is None:
        all_meta = await list_pdfs()
        pdf_ids = [m["pdf_id"] for m in all_meta]
 
    if not pdf_ids:
        return {
            "type":    "not_in_pdf",
            "answer":  "No PDFs are currently indexed.",
            "sources": [],
            "chat":    "No PDFs are currently indexed.",
        }
 
    cached = await get_qa_cache(pdf_ids, question)
    if cached:
        return {**cached, "from_cache": True}

    hits = await query_pdfs(question, pdf_ids=pdf_ids, top_k_per_pdf=4)
 
    if not hits:
        return {
            "type":    "not_in_pdf",
            "answer":  "The answer could not be found in the uploaded PDFs.",
            "sources": [],
            "chat":    "The answer could not be found in the uploaded PDFs.",
        }
 
    context_parts = []
    for h in hits[:12]:         
        context_parts.append(
            f"[{h['filename']}  •  Page {h['page']}]\n{h['text']}"
        )
    context = "\n\n---\n\n".join(context_parts)

    relevance_prompt = f"""You are a relevance classifier.
 
Document excerpts:
---
{context}
---
 
Question: {question}
 
Reply with EXACTLY one word:
- RELEVANT   → the excerpts contain enough information to answer
- NOT_RELEVANT → the excerpts do NOT contain the answer"""
 
    relevance = (await ask_gemini(relevance_prompt)).strip().upper()
    if "NOT_RELEVANT" in relevance or "RELEVANT" not in relevance:
        return {
            "type":    "not_in_pdf",
            "answer":  "The answer could not be found in the uploaded PDFs.",
            "sources": [],
            "chat":    "The answer could not be found in the uploaded PDFs.",
        }
 
    source_legend = "\n".join(
        f"- {h['filename']}  Page {h['page']}  (score {h['score']})"
        for h in hits[:12]
    )
    answer_prompt = f"""You are an expert document analysis assistant.
 
Document excerpts (each labeled with filename and page number):
---
{context}
---
 
Question: {question}
 
Instructions:
1. Answer accurately and concisely using ONLY the excerpts above.
2. Cite your sources at the end in this EXACT format:
   Sources: <Filename>, Page <N>; <Filename>, Page <M>
3. Do NOT add outside knowledge.
 
Available source labels:
{source_legend}"""
 
    answer = await ask_gemini(answer_prompt)
 
    sources = [
        {
            "pdf_id":   h["pdf_id"],
            "filename": h["filename"],
            "page":     h["page"],
            "score":    h["score"],
        }
        for h in hits[:12]
    ]
 
    result = {
        "type":    "pdf_answer",
        "answer":  answer,
        "sources": sources,
        "chat":    answer,
    }
 
    await set_qa_cache(pdf_ids, question, result)
    return result









