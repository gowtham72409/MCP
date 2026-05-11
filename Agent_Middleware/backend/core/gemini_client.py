from google import genai
from backend.config import GEMINI_API_KEY
import contextvars
import asyncio

client = genai.Client(api_key=GEMINI_API_KEY)

call_counter = {"count": 0, "total_tokens": 0}
task_usage = contextvars.ContextVar('task_usage', default=None)
# Pre-computed once per request; read by HITLMiddleware to avoid per-agent LLM calls
hitl_is_sensitive = contextvars.ContextVar('hitl_is_sensitive', default=None)

async def ask_gemini(prompt: str, max_retries: int = 5, max_output_tokens: int = None):
    """
    Call Gemini and return the response text.
    - max_output_tokens: cap response length (use small values for YES/NO checks).
    - thinking_budget=0: disables Gemini 2.5 Flash extended thinking to remove
      hidden latency and billed thinking tokens on every call.
    """
    last_error = None
    config = {
        "system_instruction": "You are an intelligent AI agent system.",
        "thinking_config": {"thinking_budget": 0},
    }
    if max_output_tokens is not None:
        config["max_output_tokens"] = max_output_tokens

    for attempt in range(max_retries):
        try:
            response = await client.aio.models.generate_content(
                model="gemini-2.5-flash",
                contents=prompt,
                config=config,
            )

            usage = getattr(response, 'usage_metadata', None)
            call_counter["count"] += 1
            tokens_this_call = usage.total_token_count if usage else 0
            call_counter["total_tokens"] += tokens_this_call
            
            print(f"[Gemini] Call #{call_counter['count']} | "
                  f"Tokens this call: {tokens_this_call} | "
                  f"Total so far: {call_counter['total_tokens']}")

            t_usage = task_usage.get()
            if t_usage is not None and usage is not None:
                t_usage["input_tokens"] += usage.prompt_token_count or 0
                t_usage["output_tokens"] += usage.candidates_token_count or 0

            text = response.text or ""  
            return text

        except Exception as e:
            last_error = e
            if attempt < max_retries - 1:
                wait_time = (2 ** (attempt + 1))
                print(f"[Gemini] API Error: {str(e)}. Retrying in {wait_time}s... (Attempt {attempt+1}/{max_retries})")
                await asyncio.sleep(wait_time)

    return f"Gemini API Error: {str(last_error)}"

