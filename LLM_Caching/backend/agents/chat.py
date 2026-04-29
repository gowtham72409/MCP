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

    prompt = f"""You are TalkBuddy, a highly intelligent and helpful AI assistant orchestrating a powerful multi-agent system.
You are the final step in the pipeline. Your job is to synthesize all available context and agent outputs into a clear, natural, and helpful response for the user.

Available System Context:
{mcp_context}
{research_ctx}
{code_ctx}
{pdf_ctx}
{fs_ctx}

User Request: {task}

Guidelines:
1. Carefully synthesize the above context to answer the user's request seamlessly.
2. Do not just blindly paste raw JSON or unformatted text. Reformat data into a conversational, easy-to-read response using markdown (e.g., bolding, lists, code blocks).
3. If MCP data (like HubSpot CRM) or PDF text is present, prioritize answering the user's question using that specific data.
4. Be concise but comprehensive. Maintain a helpful, polite, and professional tone.
"""

    return await ask_gemini(prompt)