from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from Real_Time_Chatbot.backend.database.db import get_db
from Real_Time_Chatbot.backend.database.models import Agent, Conversation
from Real_Time_Chatbot.backend.schemas import AgentCreate,AgentUpdate
import json

router = APIRouter(prefix="/agents", tags=["agents"])

@router.get("")
async def list_agents(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Agent).where(Agent.is_active == True))
    agents = result.scalars().all()
    return [
        {
            "id": a.id,
            "name": a.name,
            "description": a.description,
            "system_prompt": a.system_prompt,
            "skills": json.loads(a.skills) if isinstance(a.skills, str) else (a.skills or []),
            "created_at": a.created_at.isoformat(),
        }
        for a in agents
    ]
 
@router.post("")
async def create_agent(data: AgentCreate, db: AsyncSession = Depends(get_db)):
    agent = Agent(
        name=data.name,
        description=data.description,
        system_prompt=data.system_prompt,
        skills=json.dumps(data.skills),
    )
    db.add(agent)
    await db.commit()
    await db.refresh(agent)
    return {"id": agent.id, "name": agent.name, "message": "Agent created successfully"}
 
@router.get("/{agent_id}")
async def get_agent(agent_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Agent).where(Agent.id == agent_id))
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    return {
        "id": agent.id,
        "name": agent.name,
        "description": agent.description,
        "system_prompt": agent.system_prompt,
        "skills": json.loads(agent.skills or "[]"),
        "is_active": agent.is_active,
        "created_at": agent.created_at.isoformat(),
    }
 
@router.put("/{agent_id}")
async def update_agent(agent_id: str, data: AgentUpdate, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Agent).where(Agent.id == agent_id))
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    
    if data.name is not None:
        agent.name = data.name
    if data.description is not None:
        agent.description = data.description
    if data.system_prompt is not None:
        agent.system_prompt = data.system_prompt
    if data.skills is not None:
        agent.skills = json.dumps(data.skills)
    if data.is_active is not None:
        agent.is_active = data.is_active
    
    await db.commit()
    return {"message": "Agent updated successfully"}
 
@router.delete("/{agent_id}")
async def delete_agent(agent_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Agent).where(Agent.id == agent_id))
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    agent.is_active = False
    await db.commit()
    return {"message": "Agent deactivated"}
 
@router.get("/{agent_id}/conversations")
async def get_agent_conversations(agent_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Conversation).where(Conversation.agent_id == agent_id).order_by(Conversation.created_at.desc())
    )
    convs = result.scalars().all()
    return [
        {"id": c.id, "title": c.title, "created_at": c.created_at.isoformat()}
        for c in convs
    ]