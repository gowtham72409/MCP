import uuid
import json
import asyncio
from sqlalchemy.ext.asyncio import AsyncSession
from backend.mcp.mcp_client import resolve_tool, call_mcp_tool
from backend.agents.planner import planner_agent
from backend.agents.research import research_agent
from backend.agents.code import code_agent
from backend.agents.evaluation import evaluation_agent
from backend.agents.chat import chat_agent
from backend.agents.memory import save_task_memory
from backend.agents.fs_agent import fs_agent
from backend.core.semantic_cache import get_cache, set_cached, record_cache_hit, record_cache_miss
from backend.core.gemini_client import task_usage


async def process_task(
    user_input: str,
    session: AsyncSession,
    pdf_context: str = "",
    media_type: str = None,
    file_bytes: bytes = None,
) -> dict:
    task_id = str(uuid.uuid4())
    task_usage.set({"input_tokens": 0, "output_tokens": 0})

    if not media_type and not pdf_context:
        cached = await get_cache(user_input)
        if cached:
            await record_cache_hit(cached.get("usage", {}))
            return {**cached, "task_id": task_id, "from_cache": True}

    mcp_tool   = await resolve_tool(user_input)
    mcp_result = None
    if mcp_tool:
        mcp_result = await call_mcp_tool(mcp_tool["tool"], mcp_tool["params"])

    agents  = await planner_agent(user_input)
    results = {}

    tasks = []
    if "research" in agents:
        tasks.append(("research", research_agent(user_input)))
    if "code" in agents:
        tasks.append(("code", code_agent(user_input)))
    if "fs" in agents:
        tasks.append(("fs", fs_agent(user_input)))

    if tasks:
        responses = await asyncio.gather(*[t[1] for t in tasks], return_exceptions=True)
        for i, (name, _) in enumerate(tasks):
            results[name] = str(responses[i])

    if mcp_result:
        results["mcp"] = json.dumps(mcp_result)

    if pdf_context:
        results["pdf"] = pdf_context

    if media_type:
        results[media_type] = user_input

    evaluation    = await evaluation_agent(results)
    chat_response = await chat_agent(user_input, results)

    if media_type and file_bytes:
        results[f"{media_type}_file"] = file_bytes

    await save_task_memory(session, task_id, user_input, agents, results, evaluation, chat_response)

    if media_type and file_bytes:
        results.pop(f"{media_type}_file", None)

    response = {
        "task_id":    task_id,
        "results":    results,
        "evaluation": evaluation,
        "chat":       chat_response,
        "mcp":        mcp_result,
        "usage":      task_usage.get(),
    }

    if not media_type and not pdf_context:
        await record_cache_miss(response.get("usage", {}))
        await set_cached(user_input, response)
    return response
