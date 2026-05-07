from backend.core.gemini_client import ask_gemini
import json

async def planner_agent(user_input: str):
    prompt = f"""You are an advanced planner AI orchestrating a powerful multi-agent system.
Your goal is to thoughtfully analyze the user's request and determine the most appropriate set of specialized agents to execute the task.

Available agents:
- research   → For gathering information, answering complex factual questions, deep analysis, and conceptual explanations.
- code       → For generating, reviewing, debugging, or explaining programming tasks, scripts, and software logic.
- audio      → For audio transcription or audio-processing tasks.
- video      → For video analysis and video-processing tasks.
- pdf        → For extracting information from loaded PDF documents, and summarizing text.
- fs         → For file system operations, like creating, searching, moving, organizing, or deleting files and folders.
- mcp        → For integrating with external tools (e.g., HubSpot CRM for contacts/deals, Slack messaging, Notion pages, GitHub issues).
- chat       → For general, casual conversation, greetings, simple unstructured questions, and synthesizing results into a final user-friendly response.

CRITICAL REQUIREMENT:
You must output ONLY valid JSON format containing a list of chosen agent strings. Do absolutely nothing else.
Example: {{"agents": ["research", "chat"]}}

User Task:
{user_input}
"""

    response = await ask_gemini(prompt)

    try:
        response = response.replace("```json", "").replace("```", "").strip()
        data = json.loads(response)
        return data["agents"]
    except Exception:
        return ["chat"]