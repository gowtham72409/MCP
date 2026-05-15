from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from Real_Time_Chatbot.backend.database.db import get_db
from Real_Time_Chatbot.backend.database.models import Skill
from Real_Time_Chatbot.backend.services.skill_manager import skill_registry
from Real_Time_Chatbot.backend.schemas import SkillCreate
import json
 
router = APIRouter(prefix="/skills", tags=["skills"])

@router.get("")
async def list_skills(db: AsyncSession = Depends(get_db)):
    """List all skills (builtin + database-stored custom skills)."""
    registry_skills = skill_registry.list_skills()
 
    result = await db.execute(select(Skill).where(Skill.is_active == True))
    db_skills = result.scalars().all()
    db_skill_names = {s.name for s in db_skills}
    
    combined = {s["name"]: {**s, "source": "builtin"} for s in registry_skills}
    for s in db_skills:
        combined[s.name] = {
            "name": s.name,
            "description": s.description,
            "parameters": json.loads(s.parameters or "{}"),
            "source": "custom",
            "id": s.id,
            "created_at": s.created_at.isoformat(),
        }
    
    return list(combined.values())
 
 
@router.post("")
async def create_skill(data: SkillCreate, db: AsyncSession = Depends(get_db)):
    """Create and dynamically load a new skill."""

    if "def execute" not in data.code and "async def execute" not in data.code:
        raise HTTPException(status_code=400, detail="Skill code must contain an 'execute' function")
  
    success, message = skill_registry.load_from_code(
        name=data.name,
        code=data.code,
        description=data.description,
        parameters=data.parameters,
    )
    
    if not success:
        raise HTTPException(status_code=400, detail=message)
    
    
    skill = Skill(
        name=data.name,
        description=data.description,
        code=data.code,
        parameters=json.dumps(data.parameters),
    )
    db.add(skill)
    await db.commit()
    await db.refresh(skill)
    
    return {"id": skill.id, "name": skill.name, "message": "Skill loaded and registered successfully"}
 
 
@router.post("/upload")
async def upload_skill(file: UploadFile = File(...), db: AsyncSession = Depends(get_db)):
    """Upload a Python skill file."""
    if not file.filename.endswith(".py"):
        raise HTTPException(status_code=400, detail="Only .py files accepted")
    
    content = await file.read()
    code = content.decode("utf-8")
    
    skill_name = file.filename.replace(".py", "").replace("-", "_")
    
    # Extract docstring as description
    description = f"Uploaded skill from {file.filename}"
    if '"""' in code:
        start = code.index('"""') + 3
        end = code.index('"""', start)
        description = code[start:end].strip()
    
    success, message = skill_registry.load_from_code(
        name=skill_name,
        code=code,
        description=description,
        parameters={},
    )
    
    if not success:
        raise HTTPException(status_code=400, detail=message)
    
    skill = Skill(name=skill_name, description=description, code=code, parameters="{}")
    db.add(skill)
    await db.commit()
    
    return {"name": skill_name, "message": f"Skill '{skill_name}' uploaded and activated"}
 
 
@router.post("/{skill_name}/execute")
async def execute_skill(skill_name: str, params: dict = {}):
    """Execute a skill directly."""
    if not skill_registry.has_skill(skill_name):
        raise HTTPException(status_code=404, detail=f"Skill '{skill_name}' not found")
    
    result = await skill_registry.execute_skill(skill_name, **params)
    return {"skill": skill_name, "result": result}
 
 
@router.delete("/{skill_name}")
async def delete_skill(skill_name: str, db: AsyncSession = Depends(get_db)):
    """Unload and delete a skill."""
    skill_registry.unload_skill(skill_name)
    
    result = await db.execute(select(Skill).where(Skill.name == skill_name))
    skill = result.scalar_one_or_none()
    if skill:
        skill.is_active = False
        await db.commit()
    
    return {"message": f"Skill '{skill_name}' unloaded"}
 
 
@router.post("/reload-all")
async def reload_all_skills(db: AsyncSession = Depends(get_db)):
    """Reload all custom skills from database."""
    result = await db.execute(select(Skill).where(Skill.is_active == True))
    skills = result.scalars().all()
    
    loaded = []
    failed = []
    for skill in skills:
        success, msg = skill_registry.load_from_code(
            name=skill.name,
            code=skill.code,
            description=skill.description,
            parameters=json.loads(skill.parameters or "{}"),
        )
        if success:
            loaded.append(skill.name)
        else:
            failed.append({"name": skill.name, "error": msg})
    
    return {"loaded": loaded, "failed": failed}
 