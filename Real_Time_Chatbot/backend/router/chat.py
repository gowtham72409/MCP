from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from Real_Time_Chatbot.backend.database.db import get_db
from Real_Time_Chatbot.backend.database.models import Agent,Conversation,Message
from Real_Time_Chatbot.backend.core.gemini import GeminiAgent
from Real_Time_Chatbot.backend.services.embedding_services import embedding_services
from Real_Time_Chatbot.backend.services.workflow import orchestration_pipeline
from Real_Time_Chatbot.backend.core.websocket_manager import ws_manager
from Real_Time_Chatbot.backend.config import GEMINI_API_KEY
from Real_Time_Chatbot.backend.schemas import ChatRequest
import json
import uuid

 
router = APIRouter(prefix="/chat", tags=["chat"])

def get_gemini_agent():
    if not GEMINI_API_KEY:
        raise HTTPException(status_code=400, detail="GEMINI_API_KEY not configured. Set it in Settings.")
    return GeminiAgent(api_key=GEMINI_API_KEY)

@router.post("/send")
async def send_message(request: ChatRequest, db: AsyncSession = Depends(get_db)):
    """Send a message and get streaming response via SSE."""
    
    result = await db.execute(select(Agent).where(Agent.id == request.agent_id))
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
 

    if request.conversation_id:
        conv_result = await db.execute(select(Conversation).where(Conversation.id == request.conversation_id))
        conversation = conv_result.scalar_one_or_none()
        if not conversation:
            raise HTTPException(status_code=404, detail="Conversation not found")
    else:
        conversation = Conversation(agent_id=agent.id, title="New Conversation")
        db.add(conversation)
        await db.commit()
        await db.refresh(conversation)

    msg_result = await db.execute(
        select(Message).where(Message.conversation_id == conversation.id).order_by(Message.created_at)
    )
    history = [{"role": m.role, "content": m.content} for m in msg_result.scalars().all()]
 
 
    user_msg = Message(conversation_id=conversation.id, role="user", content=request.message)
    db.add(user_msg)
    await db.commit()
 
    agent_skills = agent.skills if isinstance(agent.skills, list) else json.loads(agent.skills or "[]")
    gemini = get_gemini_agent()
 
  
    intent = await embedding_services.detect_intent(request.message)
    

    steer = await gemini.steer_prompt(agent.system_prompt, intent, history)
 
    async def event_stream():
        full_response = ""
        thought_process = ""
        tool_calls = []
 
        try:
  
            if request.use_workflow:
                steps = await orchestration_pipeline.plan_workflow(
                    request.message, agent_skills, gemini, intent
                )
                run_id = str(uuid.uuid4())[:8]
                async for event in orchestration_pipeline.execute_workflow(run_id, steps, {}):
                    yield f"data: {json.dumps({'stream_type': 'workflow', **event})}\n\n"
 
          
            async for chunk in gemini.stream_response(
                system_prompt=agent.system_prompt,
                history=history,
                user_message=request.message,
                available_skills=agent_skills,
                intent=intent,
                model_name=getattr(agent, "model", "gemini-2.5-flash"),
                temperature=getattr(agent, "temperature", 0.7),
                steer_instructions=steer,
            ):
                chunk["stream_type"] = "llm"
                yield f"data: {json.dumps(chunk)}\n\n"
 
                if chunk.get("type") == "complete":
                    full_response = chunk.get("full_response", "")
                    thought_process = chunk.get("thought_process", "")
                    tool_calls = chunk.get("tool_calls", [])
 
            embedding = await embedding_services.embed(full_response[:500] if full_response else "")
            asst_msg = Message(
                conversation_id=conversation.id,
                role="assistant",
                content=full_response,
                meta={"thought_process": thought_process, "tool_calls": tool_calls},
                embedding=json.dumps(embedding[:50]), 
            )
            db.add(asst_msg)
 
            if len(history) == 0 and full_response:
                title = await gemini.generate_title(request.message)
                conversation.title = title
 
            await db.commit()
 
            yield f"data: {json.dumps({'stream_type': 'meta', 'conversation_id': conversation.id, 'title': conversation.title})}\n\n"
            yield f"data: [DONE]\n\n"
 
        except Exception as e:
            yield f"data: {json.dumps({'stream_type': 'error', 'content': str(e)})}\n\n"
            yield f"data: [DONE]\n\n"
 
    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        }
    )
 
 
@router.get("/conversations/{conversation_id}")
async def get_conversation(conversation_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Conversation).where(Conversation.id == conversation_id))
    conv = result.scalar_one_or_none()
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    
    msg_result = await db.execute(
        select(Message).where(Message.conversation_id == conversation_id).order_by(Message.created_at)
    )
    messages = msg_result.scalars().all()
    
    return {
        "id": conv.id,
        "title": conv.title,
        "agent_id": conv.agent_id,
        "messages": [
            {
                "id": m.id,
                "role": m.role,
                "content": m.content,
                "thought_process": (m.meta or {}).get("thought_process", ""),
                "tool_calls": (m.meta or {}).get("tool_calls", []),
                "created_at": m.created_at.isoformat(),
            }
            for m in messages
        ],
    }
 
 
@router.delete("/conversations/{conversation_id}")
async def delete_conversation(conversation_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Conversation).where(Conversation.id == conversation_id))
    conv = result.scalar_one_or_none()
    if not conv:
        raise HTTPException(status_code=404, detail="Not found")
    await db.delete(conv)
    await db.commit()
    return {"message": "Deleted"}
 
 
@router.websocket("/ws/{client_id}")
async def websocket_endpoint(websocket: WebSocket, client_id: str):
    await ws_manager.connect(client_id, websocket)
    try:
        while True:
            data = await websocket.receive_json()
            event_type = data.get("type", "")
            
            if event_type == "ping":
                await ws_manager.send_to_client(client_id, {"type": "pong"})
            elif event_type == "join_conversation":
                conv_id = data.get("conversation_id")
                if conv_id:
                    ws_manager.join_room(client_id, conv_id)
                    await ws_manager.send_to_client(client_id, {"type": "joined", "conversation_id": conv_id})
            elif event_type == "stats":
                await ws_manager.send_to_client(client_id, {"type": "stats", **ws_manager.get_stats()})
    except WebSocketDisconnect:
        ws_manager.disconnect(client_id)
