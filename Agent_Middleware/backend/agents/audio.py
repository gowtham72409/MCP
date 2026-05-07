import asyncio
from faster_whisper import WhisperModel

model = WhisperModel("base", compute_type="int8")

async def audio_agent(file_path: str):
    def transcribe():
        segments, _ = model.transcribe(file_path)
        return " ".join([seg.text for seg in segments]).strip()
    return await asyncio.to_thread(transcribe)