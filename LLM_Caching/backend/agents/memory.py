"""
Agent that persists task results to the ai_task_memory table
using the SQLAlchemy async ORM session.
"""
import json
import datetime
from sqlalchemy.ext.asyncio import AsyncSession
from backend.models import AiTaskMemory


async def save_task_memory(
    session: AsyncSession,
    task_id: str,
    user_input: str,
    subtasks,
    results: dict,
    evaluation: str,
    chat: str,
):
    record = AiTaskMemory(
        task_id=task_id,
        user_input=user_input,
        planner_output=json.dumps(subtasks) if subtasks else None,
        research_result=results.get("research"),
        code_result=results.get("code"),
        audio_result=results.get("audio"),
        video_result=results.get("video"),
        evaluation_result=evaluation,
        chat_response=chat,
        created_at=datetime.datetime.now(),
        updated_at=datetime.datetime.now(),
        pdf_file=results.get("pdf_file"),
        audio_file=results.get("audio_file"),
        video_file=results.get("video_file"),
    )
    session.add(record)
    await session.commit()
