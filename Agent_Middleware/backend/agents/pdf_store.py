import os
import json
import uuid
import shutil
import datetime
import numpy as np
from sentence_transformers import SentenceTransformer
from backend.redis_client import redis
from backend.config import EMBEDDING_MODEL

model=SentenceTransformer(EMBEDDING_MODEL)

PDF_STORE_DIR = os.environ.get("PDF_STORE_DIR", "/tmp/pdf_store")
os.makedirs(PDF_STORE_DIR, exist_ok=True)

REDIS_INDEX_KEY   = "pdf_store:index"
PDF_CACHE_PREFIX  = "pdf_cache:"              
EMBED_BATCH_SIZE  = 5                         

def pdf_dir(pdf_id: str) -> str:
    return os.path.join(PDF_STORE_DIR, pdf_id)

def pages_dir(pdf_id: str) -> str:
    return os.path.join(pdf_dir(pdf_id), "pages")

def meta_path(pdf_id: str) -> str:
    return os.path.join(pdf_dir(pdf_id), "meta.json")

def embed_path(pdf_id: str) -> str:
    return os.path.join(pdf_dir(pdf_id), "embeddings.npy")

def original_path(pdf_id: str) -> str:
    return os.path.join(pdf_dir(pdf_id), "original.pdf")


def embedd(text):
    """
    Encode one string → 1-D vector, or a list of strings → 2-D matrix.
    Using a single function keeps call-sites simple and avoids the bug
    where embedd(list) was wrapping the list in another list and then
    stripping the batch dimension with [0].
    """
    if isinstance(text, list):
        return model.encode(text)          # shape: (N, D)
    return model.encode([text])[0]         # shape: (D,)

def cosine(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """Cosine similarity of query vector b against matrix a (N,D)."""
    norms = np.linalg.norm(a, axis=1) * np.linalg.norm(b) + 1e-9
    return (a @ b) / norms


async def get_index() -> list[str]:
    raw = await redis.get(REDIS_INDEX_KEY)
    return json.loads(raw) if raw else []


async def set_index(index: list[str]):
    await redis.set(REDIS_INDEX_KEY, json.dumps(index))


async def store_pdf(file_bytes: bytes, filename: str) -> dict:
    """
    Persist a PDF, extract pages, embed them, register in index.
    Returns meta dict.
    """
    from pypdf import PdfReader
    import io

    pdf_id = str(uuid.uuid4())
    os.makedirs(pages_dir(pdf_id), exist_ok=True)

    with open(original_path(pdf_id), "wb") as f:
        f.write(file_bytes)

    reader = PdfReader(io.BytesIO(file_bytes))
    pages_text = []
    for i, page in enumerate(reader.pages):
        text = (page.extract_text() or "").strip()
        page_path = os.path.join(pages_dir(pdf_id), f"{i+1}.txt")
        with open(page_path, "w", encoding="utf-8") as f:
            f.write(text)
        pages_text.append(text)

    page_count = len(pages_text)

    non_blank = [(i, t) for i, t in enumerate(pages_text) if t]
    if non_blank:
        idxs, texts = zip(*non_blank)
        vecs = embedd(list(texts))
        embed_matrix = np.zeros((page_count, vecs.shape[1]), dtype=np.float32)
        for rank, orig_idx in enumerate(idxs):
            embed_matrix[orig_idx] = vecs[rank]
    else:
        embed_matrix = np.zeros((page_count, 768), dtype=np.float32)

    np.save(embed_path(pdf_id), embed_matrix)

    meta = {
        "pdf_id":      pdf_id,
        "filename":    filename,
        "page_count":  page_count,
        "uploaded_at": datetime.datetime.utcnow().isoformat(),
    }
    with open(meta_path(pdf_id), "w") as f:
        json.dump(meta, f)

    index = await get_index()
    index.append(pdf_id)
    await set_index(index)

    print(f"[PDFStore] Stored  pdf_id={pdf_id}  pages={page_count}  file={filename}")
    return meta


async def delete_pdf(pdf_id: str) -> dict:
    """
    Remove a PDF folder, evict from Redis index, and invalidate all
    Q&A cache entries that were answered from this PDF.
    """
    folder = pdf_dir(pdf_id)
    if os.path.isdir(folder):
        shutil.rmtree(folder)
        print(f"[PDFStore] Deleted folder  pdf_id={pdf_id}")
    else:
        print(f"[PDFStore] Folder not found  pdf_id={pdf_id}")

    index = await get_index()
    index = [i for i in index if i != pdf_id]
    await set_index(index)

    pattern = f"{PDF_CACHE_PREFIX}{pdf_id}:*"
    keys = await redis.keys(pattern)
    if keys:
        await redis.delete(*keys)
        print(f"[PDFStore] Evicted {len(keys)} cache entries for pdf_id={pdf_id}")

    return {"deleted": pdf_id, "cache_evicted": len(keys) if keys else 0}


async def list_pdfs() -> list[dict]:
    """Return meta for every active PDF."""
    index = await get_index()
    result = []
    for pdf_id in index:
        meta_file = meta_path(pdf_id)
        if os.path.exists(meta_file):
            with open(meta_file) as f:
                result.append(json.load(f))
    return result


async def get_pdf_meta(pdf_id: str) -> dict | None:
    path = meta_path(pdf_id)
    if not os.path.exists(path):
        return None
    with open(path) as f:
        return json.load(f)


def _load_page_text(pdf_id: str, page_num: int) -> str:
    path = os.path.join(pages_dir(pdf_id), f"{page_num}.txt")
    if not os.path.exists(path):
        return ""
    with open(path, encoding="utf-8") as f:
        return f.read()


async def query_pdfs(
    question: str,
    pdf_ids: list[str] | None = None,
    top_k_per_pdf: int = 4,
    score_threshold: float = 0.50,
) -> list[dict]:
    """
    Search across all active (or specified) PDFs.

    Returns a list of hits sorted by score descending:
    [
      {
        "pdf_id":   "...",
        "filename": "...",
        "page":     3,
        "score":    0.87,
        "text":     "..."
      }, ...
    ]
    """
    index = await get_index()
    active = [p for p in (pdf_ids or index) if p in index]

    if not active:
        return []

    q_vec = embedd(question)
    hits = []

    for pdf_id in active:
        embed_file = embed_path(pdf_id)
        meta_file  = meta_path(pdf_id)
        if not os.path.exists(embed_file) or not os.path.exists(meta_file):
            continue

        with open(meta_file) as f:
            meta = json.load(f)

        matrix = np.load(embed_file)          # (page_count, 768)
        scores  = cosine(matrix, q_vec)      # (page_count,)

        top_idx = np.argsort(scores)[::-1][:top_k_per_pdf]
        for idx in top_idx:
            score = float(scores[idx])
            if score < score_threshold:
                continue
            page_num = int(idx) + 1
            text = _load_page_text(pdf_id, page_num)
            if not text:
                continue
            hits.append({
                "pdf_id":   pdf_id,
                "filename": meta["filename"],
                "page":     page_num,
                "score":    round(score, 4),
                "text":     text,
            })

    hits.sort(key=lambda h: h["score"], reverse=True)
    return hits