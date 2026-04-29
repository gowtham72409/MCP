"""
SQLAlchemy 2.x ORM models for LLM_Caching backend.
Maps to the existing PostgreSQL `ai_task_memory` table.
"""
import datetime
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy import String, Text, DateTime, LargeBinary
from backend.db import Base


class AiTaskMemory(Base):
    __tablename__ = "ai_task_memory"

    task_id: Mapped[str] = mapped_column(String, primary_key=True)
    user_input: Mapped[str | None] = mapped_column(Text, nullable=True)
    planner_output: Mapped[str | None] = mapped_column(Text, nullable=True)
    research_result: Mapped[str | None] = mapped_column(Text, nullable=True)
    code_result: Mapped[str | None] = mapped_column(Text, nullable=True)
    audio_result: Mapped[str | None] = mapped_column(Text, nullable=True)
    video_result: Mapped[str | None] = mapped_column(Text, nullable=True)
    evaluation_result: Mapped[str | None] = mapped_column(Text, nullable=True)
    chat_response: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime.datetime | None] = mapped_column(DateTime, nullable=True)
    updated_at: Mapped[datetime.datetime | None] = mapped_column(DateTime, nullable=True)
    pdf_file: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    audio_file: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    video_file: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
