from backend.core.gemini_client import ask_gemini

async def evaluation_agent(results):
    prompt = f"""You are a QA Evaluation Agent. Review the agent outputs below briefly.

Provide a SHORT evaluation (3-5 sentences max):
- Overall quality verdict (Good / Needs Improvement)
- Any critical gaps or errors
- One improvement suggestion if applicable

Agent Outputs:
{results}
"""
    return await ask_gemini(prompt, max_output_tokens=300)

