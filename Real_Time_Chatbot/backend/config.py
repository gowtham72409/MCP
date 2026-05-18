import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(dotenv_path=Path(__file__).parent / ".env")

GEMINI_API_KEY       = os.getenv("GEMINI_API_KEY")
DATABASE_URL         = os.getenv("DATABASE_URL")
EMBEDDING_MODEL      = os.getenv("EMBEDDING_MODEL")
SIMILARITY_THRESHOLD = os.getenv("SIMILARITY_THRESHOLD")
GEMINI_MODEL         = os.getenv("GEMINI_MODEL")
