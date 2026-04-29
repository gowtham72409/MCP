import pytest
from unittest.mock import patch
import numpy as np
from backend.core.semantic_cache import get_cache, set_cached, INDEX_KEY

def _fake_embed(text: str) -> np.ndarray:
    """
    Keyword-overlap fake embedder that mimics semantic similarity.
    Builds a 300-dim bag-of-words style vector from word stems so that
    semantically similar sentences (sharing key words) score >= 0.85,
    while unrelated sentences score low.
    """
    VOCAB_SIZE = 300
    stop = {"what", "is", "the", "a", "an", "of", "and", "to", "in",
            "for", "on", "with", "as", "by", "this", "that", "are",
            "can", "you", "do", "i", "it", "be", "how", "explain", "me"}

    words = [w.lower().rstrip("s?.,!") for w in text.split()]
    keywords = [w for w in words if w not in stop and len(w) > 2]

    vec = np.zeros(VOCAB_SIZE, dtype=np.float32)
    for word in keywords:
        idx = abs(hash(word)) % VOCAB_SIZE
        vec[idx] += 1.0

    norm = np.linalg.norm(vec)
    return vec / (norm + 1e-9)

@pytest.fixture
def mock_redis():
    """In-memory redis mock."""
    with patch("backend.core.semantic_cache.redis") as mock_r:
        memory = {}

        async def fake_get(key):
            return memory.get(key)

        async def fake_setex(key, ttl, value):
            memory[key] = value

        mock_r.get.side_effect = fake_get
        mock_r.setex.side_effect = fake_setex
        yield mock_r


@pytest.fixture(autouse=True)
def mock_gemini_embed():
    """Replace Gemini embed call with deterministic keyword-overlap fake."""
    with patch("backend.core.semantic_cache.embedd", side_effect=_fake_embed):
        yield

@pytest.mark.asyncio
async def test_semantic_cache_flow(mock_redis):
    res1 = await get_cache("what is deep learning?")
    assert res1 is None, "Empty cache should return None"

    fake_result = {"answer": "Deep learning is a subset of machine learning."}
    await set_cached("deep learning neural networks", fake_result)

    # setex called twice: once for the payload, once for the index
    assert mock_redis.setex.call_count == 2

    exact_res = await get_cache("deep learning neural networks")
    assert exact_res == fake_result, "Exact match should hit the cache"

    similar_res = await get_cache("deep learning networks")
    assert similar_res == fake_result, "Semantically similar query should hit the cache"

    dissimilar_res = await get_cache("how do i bake chocolate cake recipe")
    assert dissimilar_res is None, "Dissimilar query should miss the cache"


@pytest.mark.asyncio
async def test_similarity_threshold_boundary(mock_redis):
    """Tests that the SIMILARITY_THRESHOLD boundary is respected."""
    await set_cached("Baseline text", {"answer": "Some baseline answer"})

    with patch("backend.core.semantic_cache.cosine_similarity") as mock_sim:
        mock_sim.return_value = 0.849
        miss_res = await get_cache("Another text")
        assert miss_res is None, "Score of 0.849 should be rejected (below threshold)"

        mock_sim.return_value = 0.851
        hit_res = await get_cache("Another text")
        assert hit_res is not None, "Score of 0.851 should be accepted (above threshold)"
        assert hit_res == {"answer": "Some baseline answer"}