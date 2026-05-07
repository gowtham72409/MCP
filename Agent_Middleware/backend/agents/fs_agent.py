import os
import shutil
import json
from pathlib import Path
from backend.core.gemini_client import ask_gemini

BASE_DIR = Path(os.environ.get("FS_AGENT_BASE_DIR", os.getcwd())).resolve()


def resolve_path(raw: str) -> Path:
    """Resolve a path string against BASE_DIR if it is relative."""
    p = Path(raw)
    if p.is_absolute():
        return p
    return (BASE_DIR / p).resolve()


def build_system_prompt() -> str:
    return f"""You are a helpful File System Automator agent.
Your goal is to parse the user's natural language command into a structured list of file system operations to execute.
Return ONLY valid JSON. No explanation. No markdown prose outside code fences.

Current working environment (base directory): {BASE_DIR}
All relative paths will be resolved under this base directory unless the user provides an absolute path.

Supported actions:
1. create
   Format: {{"action": "create", "type": "folder" | "file", "path": "<absolute or relative path>"}}
   Required fields: path, type

2. search
   Format: {{"action": "search", "query": "<file name or extension pattern>", "directory": "<directory to search in>"}}
   Note: if no directory is specified by the user, use "." (base directory).
   Required fields: query

3. move
   Format: {{"action": "move", "source": "<source file or folder path>", "destination": "<target folder path>"}}
   Required fields: source AND destination  ← BOTH must be present. If destination is missing, use clarify.

4. organize
   Format: {{"action": "organize", "directory": "<directory to organize>"}}
   Note: groups files by extension into sub-folders.
   Required fields: directory (use "." if not specified)

5. delete
   Format: {{"action": "delete", "target": "<file or folder path>"}}
   Required fields: target

6. clarify  ← Use this when required information is missing (e.g. move destination)
   Format: {{"action": "clarify", "message": "<Ask the user for the missing information in plain English>"}}

IMPORTANT RULES:
- For move: if the user does not specify WHERE to move (no destination), output a clarify action asking where to move it.
- Never invent/guess missing paths.
- If the action is completely unsupported, use: {{"error": "The requested action is not supported."}}

Example – complete move:
```json
{{
    "operations": [
        {{"action": "move", "source": "D:\\\\some\\\\folder", "destination": "D:\\\\target\\\\folder"}}
    ]
}}
```

Example – move with missing destination (trigger clarify):
```json
{{
    "operations": [
        {{"action": "clarify", "message": "Where would you like to move the folder 'file'? Please provide the destination path."}}
    ]
}}
```

Example – unsupported:
```json
{{
    "error": "The requested action is not supported."
}}
```
"""


REQUIRED_FIELDS: dict[str, list[str]] = {
    "create":   ["path", "type"],
    "search":   ["query"],
    "move":     ["source", "destination"],
    "organize": ["directory"],
    "delete":   ["target"],
    "clarify":  ["message"],
}


def validate_operation(op: dict) -> str | None:
    """Return an error string if required fields are missing, else None."""
    action = op.get("action", "")
    required = REQUIRED_FIELDS.get(action, [])
    missing = [f for f in required if not op.get(f, "").strip()]
    if missing:
        return f"Missing required field(s) for '{action}': {', '.join(missing)}"
    return None

async def fs_agent(user_input: str) -> str:
    system_prompt = build_system_prompt()
    prompt = f"{system_prompt}\n\nUser natural language command:\n{user_input}"
    response_text = await ask_gemini(prompt)

    clean_text = response_text.replace("```json", "").replace("```", "").strip()

    output: list[str] = []

    try:
        data = json.loads(clean_text)
    except json.JSONDecodeError:
        return (
            f"Could not parse the agent's response as JSON.\n"
            f"Raw response:\n{response_text}"
        )
        
    if "error" in data:
        return f" {data['error']}"

    operations = data.get("operations", [])
    if not operations:
        return "No valid file system operations were extracted from your input."

    for op in operations:
        action = op.get("action", "").lower()

        if action == "clarify":
            return f" {op.get('message', 'Please provide more details.')}"

        err = validate_operation(op)
        if err:
            return f" {err}"

        res_str = f"[Executing] {action.upper()}: {json.dumps(op)}\n"

        try:
            if action == "create":
                target = resolve_path(op["path"])
                op_type = op.get("type", "folder").lower()
                if op_type == "folder":
                    target.mkdir(parents=True, exist_ok=True)
                    res_str += f"Created folder at {target}"
                elif op_type == "file":
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.touch(exist_ok=True)
                    res_str += f"Created file at {target}"
                else:
                    res_str += f"Unknown type '{op_type}'. Use 'folder' or 'file'."

            elif action == "search":
                raw_dir = op.get("directory", ".")
                directory = resolve_path(raw_dir)
                query = op["query"]
                res_str += f"Searching for '{query}' in {directory}...\n"
                if not directory.exists() or not directory.is_dir():
                    res_str += f"Directory {directory} does not exist."
                else:
                    found = False
                    for path in directory.rglob(f"*{query}*"):
                        res_str += f"     Found: {path}\n"
                        found = True
                    if not found:
                        res_str += "     No matching files or folders found."

            elif action == "move":
                source = resolve_path(op["source"])
                destination = resolve_path(op["destination"])
                if not source.exists():
                    res_str += f"Source '{source}' does not exist."
                else:
                    destination.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(source), str(destination / source.name))
                    res_str += f"Moved '{source.name}' → {destination}"

            elif action == "organize":
                directory = resolve_path(op.get("directory", "."))
                if not directory.exists() or not directory.is_dir():
                    res_str += f"Directory '{directory}' is invalid or does not exist."
                else:
                    res_str += f"Organizing {directory}...\n"
                    moved_count = 0
                    for item in directory.iterdir():
                        if item.is_file():
                            ext = item.suffix.strip(".").lower() or "others"
                            target_folder = directory / ext.capitalize()
                            target_folder.mkdir(exist_ok=True)
                            shutil.move(str(item), str(target_folder / item.name))
                            moved_count += 1
                    res_str += f"Organized {moved_count} file(s)."

            elif action == "delete":
                target = resolve_path(op["target"])
                if not target.exists():
                    res_str += f"Target '{target}' does not exist."
                else:
                    if target.is_dir():
                        shutil.rmtree(target)
                        res_str += f"Deleted folder '{target}'"
                    else:
                        target.unlink()
                        res_str += f"Deleted file '{target}'"

            else:
                res_str += f"Unknown action: '{action}'"

        except Exception as e:
            res_str += f"Error executing '{action}': {e}"

        output.append(res_str)

    return "\n".join(output)
