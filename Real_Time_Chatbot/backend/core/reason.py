import asyncio
import json
from typing import AsyncGenerator, List, Dict
from Real_Time_Chatbot.backend.services.skill_manager import skill_registry
from Real_Time_Chatbot.backend.core.gemini_client import ask_gemini         


THOUGHT_PROMPT = """You are an AI agent with access to specific tools listed below.

STRICT RULES:
1. If the user's request can be handled by an available tool, you MUST call it using the exact format below.
2. Do NOT invent agent names, routing plans, or JSON structures of your own.
3. Do NOT say you "will use" a tool — actually call it.

To call a tool, use this exact XML format:
<tool_call>
{"name": "exact_skill_name", "args": {"param1": "value1", "param2": "value2"}}
</tool_call>

Format your full response as:
<thinking>
Step 1: [Analyze the request]
Step 2: [Identify which tool matches, or none]
Step 3: [Plan the approach]
Step 4: [Consider edge cases]
</thinking>
<response>
[Your response here. If calling a tool, put the tool_call block here, not in thinking.]
</response>

Only use tools that are listed under "Available Tools". If no tool matches, answer directly.
"""

STEER_MAP = {
    "question":     "Be concise and factual. Use bullet points for clarity.",
    "task":         "Be action-oriented. Provide step-by-step guidance.",
    "creative":     "Be imaginative and expansive. Explore multiple angles.",
    "analysis":     "Be thorough and structured. Use data-driven reasoning.",
    "code":         "Be precise and include examples. Explain your code choices.",
    "conversation": "Be warm and engaging. Match the user's tone.",
}


def _build_prompt(
    system_prompt: str,
    history: List[Dict],
    user_message: str,
    available_skills: List[str],
    intent: dict,
    steer_instructions: str,
) -> str:
    skills_desc = ""
    if available_skills:
        active = [s for s in skill_registry.list_skills() if s["name"] in available_skills]
        if active:
            skills_desc = "\n\nAvailable Tools:\n" + "\n".join(
                f"- {s['name']}: {s['description']} (params: {s['parameters']})"
                for s in active
            )
            skills_desc = "\n\n=== AVAILABLE TOOLS (you may ONLY call these) ===\n"
            for s in active:
                skills_desc += f"\nTool: {s['name']}\n"
                skills_desc += f"Description: {s['description']}\n"
                skills_desc += f"Parameters: {s['parameters']}\n"
                skills_desc += f"Example call:\n<tool_call>\n{{\"name\": \"{s['name']}\", \"args\": {list(s['parameters'].keys())}}}\n</tool_call>\n"
            skills_desc += "=== END TOOLS ===\n"

    intent_tag = (
        f"\n\n[Intent detected: {intent.get('primary_intent', 'general')} "
        f"(confidence: {intent.get('confidence', 0):.2f})]"
    )
    steer_tag = f"\n\n[Prompt Steering: {steer_instructions}]" if steer_instructions else ""

    context = ""
    if history:
        context = "\n\nConversation History:\n"
        for msg in history[-6:]:
            role = "User" if msg["role"] == "user" else "Assistant"
            body = msg["content"]
            context += f"{role}: {body[:300]}…\n" if len(body) > 300 else f"{role}: {body}\n"

    return (
        f"{THOUGHT_PROMPT}\n\n"
        f"System: {system_prompt}{skills_desc}{intent_tag}{steer_tag}{context}\n\n"
        f"User: {user_message}"
    )


async def stream_response(
    system_prompt: str,
    history: List[Dict],
    user_message: str,
    available_skills: List[str],
    intent: dict,
    steer_instructions: str = "",
    model_name: str = "gemini-2.5-flash",
    temperature: float = 0.7,
) -> AsyncGenerator[Dict, None]:
    """Yield SSE-style dicts: thoughts → tool calls → response chunks → complete."""

    full_prompt = _build_prompt(
        system_prompt, history, user_message,
        available_skills, intent, steer_instructions,
    )

    yield {"type": "status", "content": "Initializing reasoning engine..."}

    try:
        yield {"type": "status", "content": "Generating response..."}
        response_text = await ask_gemini(full_prompt, system_instruction=system_prompt)

        thinking = ""
        response = response_text
        tool_calls: List[Dict] = []

        if "<thinking>" in response_text and "</thinking>" in response_text:
            t0 = response_text.index("<thinking>") + len("<thinking>")
            t1 = response_text.index("</thinking>")
            thinking = response_text[t0:t1].strip()
            response = response_text[t1 + len("</thinking>"):].strip()

        if "<response>" in response and "</response>" in response:
            r0 = response.index("<response>") + len("<response>")
            r1 = response.index("</response>")
            response = response[r0:r1].strip()

        if thinking:
            yield {"type": "thinking_start"}
            for step in (s.strip() for s in thinking.split("\n") if s.strip()):
                yield {"type": "thought", "content": step}
                await asyncio.sleep(0.08)
            yield {"type": "thinking_end"}

        remaining = response
        while "<tool_call>" in remaining and "</tool_call>" in remaining:
            tc0 = remaining.index("<tool_call>") + len("<tool_call>")
            tc1 = remaining.index("</tool_call>")
            tool_json = remaining[tc0:tc1].strip()
            remaining = remaining[tc1 + len("</tool_call>"):].strip()

            try:
                tool_data = json.loads(tool_json)
                tool_name = tool_data.get("name", "")
                tool_args = tool_data.get("args", {})

                yield {"type": "tool_call", "tool": tool_name, "args": tool_args}

                if skill_registry.has_skill(tool_name) and tool_name in available_skills:
                    tool_result = await skill_registry.execute_skill(tool_name, **tool_args)
                    yield {"type": "tool_result", "tool": tool_name, "result": tool_result}
                    tool_calls.append({"tool": tool_name, "args": tool_args, "result": tool_result})

                    if not remaining:
                        follow_up = await ask_gemini(
                            f"{full_prompt}\n\nTool '{tool_name}' returned: {tool_result}\n\n"
                            "Now provide a final response based on this result:",
                            system_instruction=system_prompt,
                        )
                        remaining = follow_up.strip()
                        if "<response>" in remaining and "</response>" in remaining:
                            r0 = remaining.index("<response>") + len("<response>")
                            r1 = remaining.index("</response>")
                            remaining = remaining[r0:r1].strip()

            except json.JSONDecodeError:
                pass

        final = remaining or response
        words = final.split(" ")
        for i, word in enumerate(words):
            yield {"type": "response", "content": word + (" " if i < len(words) - 1 else "")}
            await asyncio.sleep(0.02)

        yield {
            "type": "complete",
            "thought_process": thinking,
            "tool_calls": tool_calls,
            "full_response": final,
        }

    except Exception as e:
        yield {"type": "error", "content": f"Generation error: {e}"}


async def generate_title(first_message: str) -> str:
    """Generate a short conversation title from the opening message."""
    try:
        title = await ask_gemini(
            f"Generate a short (3-5 word) title for a conversation that starts with: "
            f"'{first_message[:100]}'. Reply with ONLY the title, no quotes or punctuation.",
            max_output_tokens=32,
        )
        return title.strip()[:50]
    except Exception:
        return first_message[:40] + "..."


def steer_prompt(intent: dict) -> str:
    """Return a prompt-steering instruction based on detected intent."""
    return STEER_MAP.get(intent.get("primary_intent", ""), "")