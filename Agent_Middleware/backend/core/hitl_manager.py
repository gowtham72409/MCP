import asyncio
import time
from typing import Dict, Optional, List


class _Review:
    __slots__ = ("_event", "feedback", "question", "draft_answer", "created_at", "sources")

    def __init__(self, question: str = "", draft_answer: str = "", sources: list = None):
        self._event  = asyncio.Event()
        self.feedback: Optional[dict] = None
        self.question = question
        self.draft_answer = draft_answer
        self.sources = sources or []
        self.created_at = time.time()
        

_pending: Dict[str, _Review] = {}


def create_review(review_id: str, question: str = "", draft_answer: str = "", sources: list = None) -> None:
    """Register a new pending review slot."""
    _pending[review_id] = _Review(question, draft_answer, sources)


async def await_feedback(review_id: str, timeout: float = 3600.0) -> Optional[dict]:
    """
    Suspend the calling coroutine until the admin submits feedback
    or the timeout expires (default 1 hour for admin queue).
    Returns the feedback dict or None on timeout.
    """
    rev = _pending.get(review_id)
    if not rev:
        return None
    try:
        await asyncio.wait_for(rev._event.wait(), timeout=timeout)
        return rev.feedback
    except asyncio.TimeoutError:
        return None
    finally:
        _pending.pop(review_id, None)


def submit_feedback(review_id: str, feedback: dict) -> bool:
    """
    Called when the Admin sends their approval/edit/reject payload.
    Wakes up the suspended coroutine in await_feedback().
    Returns True if the review_id was found, False otherwise.
    """
    rev = _pending.get(review_id)
    if not rev:
        return False
    rev.feedback = feedback
    rev._event.set()
    return True

def get_all_pending() -> List[dict]:
    """
    Returns a list of all pending reviews for the Admin Dashboard.
    """
    reviews = []
    for rid, rev in _pending.items():
        reviews.append({
            "review_id": rid,
            "question": rev.question,
            "draft_answer": rev.draft_answer,
            "sources": rev.sources,
            "created_at": rev.created_at
        })
    # Sort by oldest first
    return sorted(reviews, key=lambda x: x["created_at"])
