from fastapi import APIRouter
from Real_Time_Chatbot.backend.schemas import SettingsUpdate
from Real_Time_Chatbot.backend.config import GEMINI_API_KEY,EMBEDDING_MODEL,GEMINI_MODEL
import os
 
router = APIRouter(prefix="/system", tags=["system"])
 
_settings = {
    "gemini_api_key":GEMINI_API_KEY,
    "default_model": GEMINI_MODEL,
    "max_history_length": 20,
    "enable_thought_streaming": True,
    "enable_workflow": True,
    "embedding_model": EMBEDDING_MODEL,
}

@router.get("/settings")
async def get_settings():
    safe = {k: v for k, v in _settings.items() if k != "gemini_api_key"}
    safe["api_key_configured"] = bool(_settings.get("gemini_api_key"))
    return safe
 
 
@router.put("/settings")
async def update_settings(data: SettingsUpdate):
    global _settings
    if data.gemini_api_key is not None:
        _settings["gemini_api_key"] = data.gemini_api_key
        os.environ["GEMINI_API_KEY"] = data.gemini_api_key
  
        import Real_Time_Chatbot.backend.router.chat as chat_module
        chat_module.GEMINI_API_KEY = data.gemini_api_key
    if data.default_model is not None:
        _settings["default_model"] = data.default_model
    if data.max_history_length is not None:
        _settings["max_history_length"] = data.max_history_length
    if data.enable_thought_streaming is not None:
        _settings["enable_thought_streaming"] = data.enable_thought_streaming
    if data.enable_workflow is not None:
        _settings["enable_workflow"] = data.enable_workflow
    return {"message": "Settings updated"}
 
 
@router.get("/health")
async def health():
    from Real_Time_Chatbot.backend.services.skill_manager import skill_registry
    from Real_Time_Chatbot.backend.core.websocket_manager import ws_manager
    return {
        "status": "healthy",
        "skills_loaded": len(skill_registry.list_skills()),
        "ws_connections": ws_manager.get_connection_count(),
        "api_key_configured": bool(_settings.get("gemini_api_key")),
    }
 
 
@router.get("/models")
async def list_models():
    return {
        "models": [
            {"id": "gemini-2.5-flash", "name": "Gemini 2.5 Flash", "description": "Fast, efficient"},
            {"id": "gemini-2.0-flash", "name": "Gemini 2.0 Flash", "description": "Most capable"},
            {"id": "gemini-1.5-pro", "name": "Gemini 1.5 pro", "description": "Balanced speed/quality"},
        ]
    }