import os
import asyncio
import subprocess
from backend.agents.audio import audio_agent

async def extract_audio(video_path, audio_path):
    def run_ffmpeg():
        subprocess.run([
            "ffmpeg", "-i", video_path, "-vn",
            "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1",
            audio_path, "-y"
        ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        
    await asyncio.to_thread(run_ffmpeg)

async def video_agent(video_path: str):
    audio_path = video_path.rsplit(".", 1)[0] + ".wav"

    await extract_audio(video_path, audio_path)
    text = await audio_agent(audio_path)

    if os.path.exists(audio_path):
        os.remove(audio_path)

    return text