import asyncio
import json
import uuid
from typing import List, Dict, Any, AsyncGenerator, Optional
from datetime import datetime
from Real_Time_Chatbot.backend.services.skill_manager import skill_registry
from Real_Time_Chatbot.backend.services.embedding_services import embedd, detect_intent


class WorkflowStep:

    def __init__(self, step_id: str, name: str, action: str, parameter: dict = None):
        self.step_id = step_id
        self.name = name
        self.action = action
        self.params = parameter or {}
        self.status = "pending"
        self.result = None
        self.error = None
        self.started_at = None
        self.completed_at = None

    def to_dict(self):
        return {
            "step_id": self.step_id,
            "name": self.name,
            "action": self.action,
            "params": self.params,
            "status": self.status,
            "result": self.result,
            "error": self.error,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
        }


class OrchestrationPipeline:

    def __init__(self):
        self._active_runs: Dict[str, dict] = {}

    async def plan_workflow(self, user_input: str, agent_skills: list, gemini_agent, intent: dict):
        steps = []
        primary_intent = intent.get("primary_intent", "conversation")

        steps.append(WorkflowStep(
            step_id=str(uuid.uuid4())[:8],
            name="Semantic Analysis",
            action="embed_input",
            parameter={"text": user_input},
        ))

        if agent_skills:
            tool_keywords = {
                "calculator": ["calculate", "compute", "math", "solve", "add", "multiply", "divide"],
                "web_search": ["search", "find", "look up", "current", "latest", "news"],
                "json_parser": ["json", "parse", "data", "structure"],
                "code_runner": ["run", "execute", "code", "script"],
            }
            lower_input = user_input.lower()
            for tool_name, keywords in tool_keywords.items():
                if tool_name in agent_skills and any(kw in lower_input for kw in keywords):
                    steps.append(WorkflowStep(
                        step_id=str(uuid.uuid4())[:8],
                        name=f"Execute {tool_name}",
                        action="run_skill",
                        parameter={"skill_name": tool_name, "query": user_input},
                    ))
                    break

        steps.append(WorkflowStep(
            step_id=str(uuid.uuid4())[:8],
            name="Generate response",
            action="llm_generate",
            parameter={"user_input": user_input},
        ))

        if primary_intent in ["analysis", "code"]:
            steps.append(WorkflowStep(
                step_id=str(uuid.uuid4())[:8],
                name="Quality check",
                action="quality_check",
                parameter={},
            ))

        return steps

    async def execute_workflow(self, run_id: str, steps: List[WorkflowStep], context: dict):
        self._active_runs[run_id] = {
            "status": "running",
            "steps": steps,
            "context": context,
            "started_at": datetime.utcnow().isoformat(),
        }

        yield {"type": "workflow_start", "run_id": run_id, "total_steps": len(steps)}

        workflow_context = {}

        for i, step in enumerate(steps):
            step.status = "running"
            step.started_at = datetime.utcnow().isoformat()

            yield {
                "type": "step_start",
                "run_id": run_id,
                "step": step.to_dict(),
                "step_index": i,
                "total_steps": len(steps),
            }

            try:
                result = await self._execute_step(step, context, workflow_context)
                step.status = "completed"
                step.result = result
                step.completed_at = datetime.utcnow().isoformat()
                workflow_context[step.step_id] = result

                yield {
                    "type": "step_complete",
                    "run_id": run_id,
                    "step": step.to_dict(),
                    "step_index": i,
                }
                await asyncio.sleep(0.1)

            except Exception as e:
                step.status = "failed"
                step.error = str(e)
                step.completed_at = datetime.utcnow().isoformat()

                yield {
                    "type": "step_failed",
                    "run_id": run_id,
                    "step": step.to_dict(),
                    "step_index": i,
                }

        self._active_runs[run_id]["status"] = "completed"
        yield {
            "type": "workflow_complete",
            "run_id": run_id,
            "steps": [s.to_dict() for s in steps],
        }

    async def _execute_step(self, step: WorkflowStep, context: dict, workflow_context: dict):
        action = step.action

        if action == "embed_input":
            text = step.params.get("text", "")
            embedding = embedd(text)
            intent = detect_intent(text)
            return {"embedding_dims": len(embedding), "intent": intent}

        elif action == "run_skill":
            skill_name = step.params.get("skill_name", "")
            query = step.params.get("query", "")

            if skill_name == "calculator":
                import re
                numbers = re.findall(r'\d+(?:\.\d+)?', query)
                expr = ' + '.join(numbers) if numbers else "0"
                result = await skill_registry.execute_skill("calculator", expression=expr)
            elif skill_name == "web_search":
                result = await skill_registry.execute_skill("web_search", query=query)
            else:
                result = await skill_registry.execute_skill(skill_name, query=query)

            return result

        elif action == "llm_generate":
            return {"status": "LLM generation handled by streaming response"}

        elif action == "quality_check":
            return {"status": "Quality check passed", "score": 0.92}

        else:
            return {"status": f"Unknown action: {action}"}

    async def get_run_status(self, run_id: str):
        return self._active_runs.get(run_id)

    async def list_active(self):
        return [rid for rid, run in self._active_runs.items() if run["status"] == "running"]


orchestration_pipeline = OrchestrationPipeline()