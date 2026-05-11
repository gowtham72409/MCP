from backend.core.gemini_client import ask_gemini
import json

async def chat_agent(task: str, memory: dict) -> str:
    mcp_context = ""
    if memory.get("mcp"):
        try:
            mcp_data = json.loads(memory["mcp"]) if isinstance(memory["mcp"], str) else memory["mcp"]
            mcp_context = f"\n\nMCP Tool Result:\n{json.dumps(mcp_data, indent=2)}"
        except Exception:
            mcp_context: str = f"\n\nMCP Result: {memory.get('mcp')}"

    research_ctx = f"\n\nResearch:\n{memory['research']}" if memory.get("research") else ""
    code_ctx     = f"\n\nCode:\n{memory['code']}"         if memory.get("code")     else ""
    pdf_ctx      = f"\n\nPDF Content (indexed):\n{memory['pdf']}" if memory.get("pdf") else ""
    fs_ctx       = f"\n\nFile System Actions:\n{memory['fs']}"    if memory.get("fs")       else ""

    prompt = f"""You are TalkBuddy, a helpful AI assistant. Synthesize the available context below into a clear, direct answer for the user.

Available Context:
{mcp_context}
{research_ctx}
{code_ctx}
{pdf_ctx}
{fs_ctx}

User Request: {task}

Guidelines:
1. Answer directly and concisely. Stop when the question is answered — do not pad.
2. Format with markdown (lists, bold, code blocks) where it improves readability.
3. If MCP or PDF data is present, prioritise it to answer the question.
4. Maintain a helpful, professional tone.
"""

    return await ask_gemini(prompt)