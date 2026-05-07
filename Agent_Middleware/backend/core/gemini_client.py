from google import genai
from backend.config import GEMINI_API_KEY
import contextvars
import asyncio

client = genai.Client(api_key=GEMINI_API_KEY)

call_counter = {"count": 0, "total_tokens": 0}
task_usage = contextvars.ContextVar('task_usage', default=None)

async def ask_gemini(prompt: str, max_retries: int = 5):
    """
    Call Gemini and return the response text.
    Token counts are stored as attributes on the returned string object so
    callers that don't care about tokens keep working unchanged.
    """
    last_error = None
    for attempt in range(max_retries):
        try:
            response = await client.aio.models.generate_content(
                model="gemini-2.5-flash", 
                contents=prompt,
                config={"system_instruction": "You are an intelligent AI agent system."},
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

