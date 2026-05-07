import json 
import hashlib
import numpy as np
from sentence_transformers import SentenceTransformer
from backend.redis_client import redis
from backend.config import EMBEDDING_MODEL

model=SentenceTransformer(EMBEDDING_MODEL)

CACHE_PREFIX = "sem_cache:"
INDEX_KEY="sem_cache:index"
SIMILARITY_THRESHOLD = 0.85
CACHE_TTL=60 * 60 * 24

COST_INPUT_PER_1K  = 0.00005   # $0.05 / 1M input tokens
COST_OUTPUT_PER_1K = 0.00008 

def embedd(text:str):
    return model.encode([text])[0]

def cosine_similarity(vec1,vec2):
    a=np.array(vec1)
    b=np.array(vec2)
    return float(np.dot(a,b)/(np.linalg.norm(a) * np.linalg.norm(b)+1e-9))

async def get_cache(query:str):
    """Return cached result if a semantically similar query exists."""
    query_vec=embedd(query)

    raw_index=await redis.get(INDEX_KEY)

    if not raw_index:
        return None
    
    index=json.loads(raw_index)
    best_score, best_key=0.0,None

    for entry in index:
        stored_vec = np.array(entry["vector"], dtype=np.float32)

        if query_vec.shape != stored_vec.shape:
            continue
        score = cosine_similarity(query_vec, stored_vec)
        if score > best_score:
            best_score, best_key = score, entry["key"]

    if best_score >= SIMILARITY_THRESHOLD and best_key:
        raw = await redis.get(best_key)
        if raw:
            print(f"[SemanticCache] HIT  score={best_score:.3f}  key={best_key}")
            return json.loads(raw)

    print(f"[SemanticCache] MISS  best_score={best_score:.3f}")
    return None
    
async def set_cached(query: str, result: dict):
    """Store result and update the embedding index."""
    query_vec=embedd(query)
    cache_key=CACHE_PREFIX+hashlib.sha3_256(query.encode()).hexdigest()[:16]

    await redis.setex(cache_key,CACHE_TTL,json.dumps(result))


    raw_index=await redis.get(INDEX_KEY)
    index=json.loads(raw_index) if raw_index else []                           

    index.append({
        "key":    cache_key,
        "query":  query,
        "vector": query_vec.tolist(),
    })

    if len(index) > 1000:
        index = index[-1000:]

    await redis.setex(INDEX_KEY, CACHE_TTL * 7, json.dumps(index))
    print(f"[SemanticCache] STORED  key={cache_key}")

STATS_KEY = "sem_cache:metrics_json"

async def record_cache_miss(usage_dict: dict):
    stats = await redis.get(STATS_KEY)
    stats = json.loads(stats) if stats else {}
    stats["total_queries"] = stats.get("total_queries", 0) + 1
    stats["cache_misses"] = stats.get("cache_misses", 0) + 1
    
    in_tok = usage_dict.get("input_tokens", 0)
    out_tok = usage_dict.get("output_tokens", 0)
    
    stats["used_input_tokens"] = stats.get("used_input_tokens", 0) + in_tok
    stats["used_output_tokens"] = stats.get("used_output_tokens", 0) + out_tok
    
    cost_used = (in_tok / 1000 * COST_INPUT_PER_1K) + (out_tok / 1000 * COST_OUTPUT_PER_1K)
    stats["used_cost_usd"] = stats.get("used_cost_usd", 0.0) + cost_used
    
    await redis.set(STATS_KEY, json.dumps(stats))

async def record_cache_hit(usage_dict: dict):
    stats = await redis.get(STATS_KEY)
    stats = json.loads(stats) if stats else {}
    stats["total_queries"] = stats.get("total_queries", 0) + 1
    stats["cache_hits"] = stats.get("cache_hits", 0) + 1
    
    in_tok = usage_dict.get("input_tokens", 0)
    out_tok = usage_dict.get("output_tokens", 0)
    
    stats["saved_input_tokens"] = stats.get("saved_input_tokens", 0) + in_tok
    stats["saved_output_tokens"] = stats.get("saved_output_tokens", 0) + out_tok
    
    cost_saved = (in_tok / 1000 * COST_INPUT_PER_1K) + (out_tok / 1000 * COST_OUTPUT_PER_1K)
    stats["cost_saved_usd"] = stats.get("cost_saved_usd", 0.0) + cost_saved
    
    await redis.set(STATS_KEY, json.dumps(stats))

async def get_cost_savings():
    stats = await redis.get(STATS_KEY)
    if not stats:
        return {"total_queries": 0, "cache_hits": 0, "cache_misses": 0, "saved_input_tokens": 0, "saved_output_tokens": 0, "cost_saved_usd": 0.0, "used_input_tokens": 0, "used_output_tokens": 0, "used_cost_usd": 0.0}
    return json.loads(stats)
