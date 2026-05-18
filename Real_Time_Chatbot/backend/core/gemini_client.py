from google import genai
from google.genai import types
import asyncio
from Real_Time_Chatbot.backend.config import GEMINI_API_KEY, GEMINI_MODEL

client = genai.Client(api_key=GEMINI_API_KEY)


async def ask_gemini(
    prompt: str,
    system_instruction: str = "You are an intelligent AI agent system.",
    max_output_tokens: int = 2000,
) -> str:
    """Send *prompt* to Gemini and return the response text."""

    config = types.GenerateContentConfig(
        system_instruction=system_instruction,
        max_output_tokens=max_output_tokens,
        thinking_config=types.ThinkingConfig(thinking_budget=0),
    )

    MAX_RETRIES = 3
    last_error = None

    for attempt in range(MAX_RETRIES):
        try:
            response = await client.aio.models.generate_content(
                model=GEMINI_MODEL,
                contents=prompt,
                config=config,
            )
            return response.text or ""

        except Exception as e:
            last_error = e
            if attempt < MAX_RETRIES - 1:
                wait = 2 ** (attempt + 1)
                print(f"[Gemini] Error: {e}. Retry {attempt + 1}/{MAX_RETRIES} in {wait}s…")
                await asyncio.sleep(wait)

    return f"Gemini API Error: {last_error}"