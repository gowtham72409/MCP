from backend.core.gemini_client import ask_gemini

async def research_agent(task):
    prompt = f"""You are an expert Research AI Agent in a multi-agent system.
Provide an accurate, concise, and well-structured answer to the user's query.

Guidelines:
1. Be factual and objective.
2. Use clear structure (bullet points or short paragraphs). Avoid padding.
3. Cover all key points but omit unnecessary elaboration.

User Query:
{task}
"""
    return await ask_gemini(prompt)

