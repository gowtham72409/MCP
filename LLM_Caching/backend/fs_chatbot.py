import os
import shutil
import json
import asyncio
from pathlib import Path
import sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from backend.core.gemini_client import ask_gemini

SYSTEM_PROMPT = """You are a helpful File System Automator agent.
Your goal is to parse the user's natural language command into a structured list of file system operations to execute.
Return ONLY valid JSON. The JSON should be a dictionary with a key "operations", mapped to a list of operation objects.

Supported actions:
1. create
   Format: {"action": "create", "type": "folder" | "file", "path": "<absolute or relative path>"}
2. search
   Format: {"action": "search", "query": "<file name or extension pattern>", "directory": "<directory to search in>"}
   Note: if no directory is specified by the user, use "." (current directory).
3. move
   Format: {"action": "move", "source": "<file or folder path>", "destination": "<target folder path>"}
4. organize
   Format: {"action": "organize", "directory": "<directory to organize>"}
   Note: this will automatically group files by extension in the target directory.
5. delete
   Format: {"action": "delete", "target": "<file or folder path>"}
   Note: will permanently delete the specified file or folder. Use with caution.

Example Output:
```json
{
    "operations": [
        {"action": "create", "type": "folder", "path": "./my_folder"}
    ]
}
```

If the user requests an action that is NOT supported (like 'select' or 'hack'), or you don't have enough context, you MUST still return valid JSON indicating an error:
```json
{
    "error": "The requested action is not supported or lacks context."
}
```
"""

async def execute_operation(op: dict):
    action = op.get("action")
    print(f"\n[Executing] {action.upper()}: {op}")
    
    if action == "create":
        target = Path(op.get("path"))
        op_type = op.get("type", "folder")
        if op_type == "folder":
            target.mkdir(parents=True, exist_ok=True)
            print(f"  -> Created folder at {target.resolve()}")
        elif op_type == "file":
            target.parent.mkdir(parents=True, exist_ok=True)
            target.touch(exist_ok=True)
            print(f"  -> Created file at {target.resolve()}")
            
    elif action == "search":
        directory = Path(op.get("directory", "."))
        query = op.get("query", "")
        print(f"  -> Searching for '{query}' in {directory.resolve()}...")
        found = False
        for path in directory.rglob(f"*{query}*"):
            print(f"     Found: {path.resolve()}")
            found = True
        if not found:
            print("     No matching files found.")
            
    elif action == "move":
        source = Path(op.get("source"))
        destination = Path(op.get("destination"))
        if not source.exists():
            print(f"  -> [Error] Source {source.resolve()} does not exist.")
            return
        destination.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source), str(destination / source.name))
        print(f"  -> Moved {source.name} to {destination.resolve()}")
        
    elif action == "organize":
        directory = Path(op.get("directory", "."))
        if not directory.exists() or not directory.is_dir():
            print(f"  -> [Error] Directory {directory.resolve()} is invalid.")
            return
        print(f"  -> Organizing directory {directory.resolve()}...")
        moved_count = 0
        for item in directory.iterdir():
            if item.is_file():
                ext = item.suffix.strip('.').lower()
                if not ext:
                    ext = "others"
                target_folder = directory / ext.capitalize()
                target_folder.mkdir(exist_ok=True)
                shutil.move(str(item), str(target_folder / item.name))
                moved_count += 1
        print(f"  -> Organized {moved_count} files.")
    
    elif action == "delete":
        target = Path(op.get("target"))
        if not target.exists():
            print(f"  -> [Error] Target {target.resolve()} does not exist.")
            return
        
        try:
            if target.is_dir():
                shutil.rmtree(target)
                print(f"  -> Deleted folder {target.resolve()}")
            else:
                target.unlink()
                print(f"  -> Deleted file {target.resolve()}")
        except Exception as e:
            print(f"  -> [Error] Failed to delete {target.resolve()}: {e}")
            
    else:
        print(f"  -> [Error] Unknown action: {action}")

async def run_chat():
    print("=====================================================")
    print(" File System Automator Chatbot (Type 'quit' to exit)")
    print("=====================================================\n")
    
    while True:
        try:
            user_input = input("You: ")
        except (EOFError, KeyboardInterrupt):
            break
            
        if user_input.strip().lower() in ["quit", "exit"]:
            break
        if not user_input.strip():
            continue
            
        prompt = f"{SYSTEM_PROMPT}\n\nUser natural language command:\n{user_input}"
        print("Bot: Thinking...")
        
        response_text = await ask_gemini(prompt)
        
        clean_text = response_text.replace("```json", "").replace("```", "").strip()
        
        try:
            data = json.loads(clean_text)
            
            if "error" in data:
                print(f"Bot: [Error] {data['error']}")
                continue
                
            operations = data.get("operations", [])
            if not operations:
                print("Bot: Could not extract any valid file system operations from your input.")
                continue
            
            for op in operations:
                try:
                    await execute_operation(op)
                except Exception as e:
                    print(f"  -> [Error] Failed to execute {op.get('action')}: {e}")
                    
            print("\nBot: Done! What's next?")
        except json.JSONDecodeError:
            print("\nBot: Error understanding the command.")
            print(f"[Debug] Raw Response: {response_text}")

if __name__ == "__main__":
    asyncio.run(run_chat())
