from pydantic import BaseModel
from typing import Optional, List

class AgentCreate(BaseModel):
    name: str
    description: str = ""
    system_prompt: str = "You are a helpful AI assistant."
    model: str = "gemini-2.5-flash"
    temperature: float = 0.7
    skills: List[str] = []
 
class AgentUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    system_prompt: Optional[str] = None
    model: Optional[str] = None
    temperature: Optional[float] = None
    skills: Optional[List[str]] = None
    is_active: Optional[bool] = None

class ChatRequest(BaseModel):
    agent_id: str
    conversation_id: Optional[int] = None
    message: str
    use_workflow: bool = False

class SkillCreate(BaseModel):
    name: str
    description: str
    code: str
    parameters: dict = {}
 
 
class SkillUpdate(BaseModel):
    description: Optional[str] = None
    code: Optional[str] = None
    parameters: Optional[dict] = None
    is_active: Optional[bool] = None

class SettingsUpdate(BaseModel):
    gemini_api_key: Optional[str] = None
    default_model: Optional[str] = None
    max_history_length: Optional[int] = None
    enable_thought_streaming: Optional[bool] = None
    enable_workflow: Optional[bool] = None