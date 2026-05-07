import logging
import asyncio

logger = logging.getLogger(__name__)

class AgentMiddleware:
    async def __call__(self, call_next, *args, **kwargs):
        return await call_next(*args, **kwargs)

class LoggingMiddleware(AgentMiddleware):
    async def __call__(self, call_next, *args, **kwargs):
        agent_name = getattr(call_next, '__name__', 'unknown_agent')
        logger.info(f"[Agent Execution] Starting {agent_name}")
        try:
            result = await call_next(*args, **kwargs)
            logger.info(f"[Agent Execution] Finished {agent_name} successfully")
            return result
        except Exception as e:
            logger.error(f"[Agent Execution] Failed {agent_name}: {e}")
            raise

class RetryMiddleware(AgentMiddleware):
    def __init__(self, retries=3, delay=1.0):
        self.retries = retries
        self.delay = delay

    async def __call__(self, call_next, *args, **kwargs):
        agent_name = getattr(call_next, '__name__', 'unknown_agent')
        for attempt in range(self.retries):
            try:
                return await call_next(*args, **kwargs)
            except Exception as e:
                if attempt == self.retries - 1:
                    raise
                logger.warning(f"[Retry] {agent_name} attempt {attempt+1}/{self.retries} failed: {e}. Retrying in {self.delay}s...")
                await asyncio.sleep(self.delay)

class ValidationMiddleware(AgentMiddleware):
    async def __call__(self, call_next, *args, **kwargs):
        # Validate that the first argument is a non-empty string, assuming the task is the first arg
        if args and isinstance(args[0], str) and not args[0].strip():
            agent_name = getattr(call_next, '__name__', 'unknown_agent')
            raise ValueError(f"Agent {agent_name} received empty task input")
        return await call_next(*args, **kwargs)

class HITLMiddleware(AgentMiddleware):
    async def __call__(self, call_next, *args, **kwargs):
        from backend.core.gemini_client import ask_gemini
        from backend.core.hitl_manager import create_review, await_feedback
        import uuid
        import os

        agent_name = getattr(call_next, '__name__', 'unknown_agent')

        task = ""
        if agent_name == "pdf_agent":
            task = kwargs.get("question", "")
        elif agent_name in ("audio_agent", "video_agent", "answer_question"):
            # These agents just transcribe or retrieve answers, no dangerous actions
            return await call_next(*args, **kwargs)
        else:
            task = args[0] if args and isinstance(args[0], str) else kwargs.get("task", "")

        if not task or (isinstance(task, str) and os.path.exists(task)):
            return await call_next(*args, **kwargs)

        prompt = (
            f"Is the following task sensitive, dangerous, inappropriate, "
            f"or does it require human review (e.g. asking for personal info, destructive actions)? "
            f"Answer ONLY 'YES' or 'NO'.\n\nTask: {task}"
        )
        is_sensitive_resp = await ask_gemini(prompt)
        is_sensitive = "YES" in is_sensitive_resp.upper()

        if not is_sensitive:
            return await call_next(*args, **kwargs)

        logger.info(f"[HITL] Agent '{agent_name}' intercepted sensitive task: {task}")

        draft_prompt = f"Provide a brief draft response or outline the intended action for this sensitive task handled by {agent_name}:\nTask: {task}"
        draft_answer = await ask_gemini(draft_prompt)

        review_id = str(uuid.uuid4())
        create_review(review_id, question=task, draft_answer=draft_answer, sources=[])

        logger.info(f"[HITL] Waiting for admin review on review_id: {review_id}")
        feedback = await await_feedback(review_id, timeout=3600.0)

        if not feedback:
            logger.warning(f"[HITL] Admin review timed out for {review_id}")
            return f"Admin review timed out for sensitive task in {agent_name}."

        action = feedback.get("action", "reject")

        if action == "approve":
            logger.info(f"[HITL] Admin approved action for {review_id}")
            return await call_next(*args, **kwargs)
        elif action == "edit":
            logger.info(f"[HITL] Admin edited action for {review_id}. Bypassing execution and returning edited answer.")
            return feedback.get("edited_answer", "")
        else:
            logger.info(f"[HITL] Admin rejected action for {review_id}")
            return f"The admin has rejected this sensitive action in {agent_name}."

class AgentRunner:
    def __init__(self, middlewares=None):
        self.middlewares = middlewares or []

    async def run(self, agent_func, *args, **kwargs):
        current_call = agent_func
        for mw in reversed(self.middlewares):
            def make_call(middleware, next_call):
                async def chained_call(*a, **kw):
                    return await middleware(next_call, *a, **kw)
                chained_call.__name__ = getattr(next_call, '__name__', 'chained_call')
                return chained_call
            current_call = make_call(mw, current_call)
        return await current_call(*args, **kwargs)
