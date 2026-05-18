import types as builtin_types
import sys
import asyncio
import json
import traceback
from typing import Any, Dict
from pathlib import Path


class SkillRegistry:
    def __init__(self):
        self._skills: Dict[str, Dict] = {}
        self._modules: Dict[str, Any] = {}

    def skill_registry(self):
        self._skills["web_search"] = {
            "name": "web_search",
            "description": "Search the web for information (simulated)",
            "parameters": {"query": "string"},
            "fn": self._web_search,
        }
        self._skills["calculator"] = {
            "name": "calculator",
            "description": "Evaluate mathematical expressions",
            "parameters": {"expression": "string"},
            "fn": self._calculator,
        }
        self._skills["text_summarizer"] = {
            "name": "text_summarizer",
            "description": "Summarize long text into key points",
            "parameters": {"text": "string", "max_points": "int"},
            "fn": self._summarizer,
        }
        self._skills["json_parser"] = {
            "name": "json_parser",
            "description": "Parse and validate JSON data",
            "parameters": {"data": "string"},
            "fn": self._json_parser,
        }
        self._skills["code_runner"] = {
            "name": "code_runner",
            "description": "Execute safe Python expressions",
            "parameters": {"code": "string"},
            "fn": self._code_runner,
        }

    async def _web_search(self, query: str):
        await asyncio.sleep(0.1)
        return (
            f"[Web Search Results for '{query}']\n"
            f"• Result 1: Relevant information about {query}\n"
            f"• Result 2: Additional context and details\n"
            f"• Result 3: Expert opinions and analysis\n"
            f"[Simulated results - connect real search API for production]"
        )

    async def _calculator(self, expression: str):
        try:
            allowed = set("0123456789+-*/().% ")
            if not all(c in allowed for c in expression):
                return "Error: Invalid characters in expression"
            result = eval(expression, {"__builtins__": {}}, {})
            return f"Result: {expression} = {result}"
        except Exception as e:
            return f"Error evaluating expression: {str(e)}"

    async def _summarizer(self, text: str, max_points: int = 5) -> str:
        sentences = [s.strip() for s in text.split(".") if len(s.strip()) > 20]
        points = sentences[:max_points]
        return "Summary:\n" + "\n".join(f"• {p}" for p in points)

    async def _json_parser(self, data: str) -> str:
        try:
            parsed = json.loads(data)
            keys = list(parsed.keys()) if isinstance(parsed, dict) else f"Array with {len(parsed)} items"
            return f"Valid JSON. Keys: {keys}\nFormatted:\n{json.dumps(parsed, indent=2)}"
        except Exception as e:
            return f"Invalid JSON: {str(e)}"

    async def _code_runner(self, code: str) -> str:
        try:
            safe_globals = {
                "__builtins__": {
                    "print": print, "len": len, "range": range,
                    "list": list, "dict": dict, "str": str,
                    "int": int, "float": float,
                }
            }
            output = []
            exec(code, safe_globals, {"output": output})
            return f"Code executed successfully.\nOutput: {output}"
        except Exception as e:
            return f"Execution error: {str(e)}"

    def load_from_code(self, name: str, code: str, description: str, parameters: dict):
        try:
            module_name = f"dynamic_skill_{name}"
            module = builtin_types.ModuleType(module_name)
            exec(code, module.__dict__)

            fn = None
            for attr_name in dir(module):
                attr = getattr(module, attr_name)
                if callable(attr) and attr_name == "execute":
                    fn = attr
                    break

            if fn is None:
                return False, "No 'execute' function found in skill code"

            self._skills[name] = {
                "name": name,
                "description": description,
                "parameters": parameters,
                "fn": fn,
                "code": code,
            }
            self._modules[module_name] = module
            return True, "Skill loaded successfully"
        except Exception:
            return False, f"Error loading skill: {traceback.format_exc()}"

    def unload_skill(self, name: str):
        if name in self._skills:
            del self._skills[name]
            module_name = f"dynamic_skill_{name}"
            if module_name in self._modules:
                del self._modules[module_name]
                if module_name in sys.modules:
                    del sys.modules[module_name]
            return True
        return False

    async def execute_skill(self, name: str, **kwargs):
        if name not in self._skills:
            return f"Error: Skill '{name}' not found"
        try:
            fn = self._skills[name]["fn"]
            if asyncio.iscoroutinefunction(fn):
                result = await fn(**kwargs)
            else:
                result = fn(**kwargs)
            return str(result)
        except Exception:
            return f"Skill execution error: {traceback.format_exc()}"

    def list_skills(self):
        return [
            {"name": s["name"], "description": s["description"], "parameters": s.get("parameters", {})}
            for s in self._skills.values()
        ]

    def get_skill(self, name: str):
        return self._skills.get(name)

    def has_skill(self, name: str):
        return name in self._skills


skill_registry = SkillRegistry()
skill_registry.skill_registry()