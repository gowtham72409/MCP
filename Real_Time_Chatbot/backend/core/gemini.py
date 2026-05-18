from google import genai
from Real_Time_Chatbot.backend.core.gemini_client import ask_gemini          
from Real_Time_Chatbot.backend.core.reason import stream_response, generate_title, steer_prompt


class GeminiAgent:

    def __init__(self, api_key: str = ""):
        if api_key:
            import Real_Time_Chatbot.backend.core.gemini_client as _gc
            _gc.client = genai.Client(api_key=api_key)

    async def stream_response(self, **kwargs):
        async for chunk in stream_response(**kwargs):
            yield chunk

    async def generate_title(self, first_message: str) -> str:
        return await generate_title(first_message)

    async def steer_prompt(self, original_prompt: str, intent: dict, history: list) -> str:
        return steer_prompt(intent)