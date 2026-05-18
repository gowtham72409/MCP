from sqlalchemy import Column, String, Text, DateTime, JSON, Boolean
from Real_Time_Chatbot.backend.database.db import Base
from datetime import datetime
import uuid


class Agent(Base):
    __tablename__ = "agents"

    id            = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name          = Column(String, nullable=False)
    description   = Column(Text, default="")
    system_prompt = Column(Text, default="")
    skills        = Column(JSON, default=list)
    created_at    = Column(DateTime, default=datetime.utcnow)
    is_active     = Column(Boolean, default=True)


class Conversation(Base):
    __tablename__ = "conversations"

    id         = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    agent_id   = Column(String, nullable=False)
    title      = Column(String, default="New Conversation")
    context    = Column(JSON, default=dict)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow)


class Message(Base):
    __tablename__ = "messages"

    id              = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    conversation_id = Column(String, nullable=False)
    role            = Column(String, nullable=False)  # "user" | "assistant" | "system"
    content         = Column(Text, default="")
    meta            = Column(JSON, default=dict)
    embedding       = Column(JSON, default=list)      # List[float] from SentenceTransformer
    created_at      = Column(DateTime, default=datetime.utcnow)


class Skill(Base):
    __tablename__ = "skills"

    id          = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name        = Column(String, nullable=False, unique=True)
    description = Column(Text, default="")
    code        = Column(Text, nullable=False)
    parameters  = Column(JSON, default=dict)
    is_active   = Column(Boolean, default=True)
    created_at  = Column(DateTime, default=datetime.utcnow)


class WorkflowRun(Base):
    __tablename__ = "workflow_runs"

    id              = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    conversation_id = Column(String, nullable=False)
    graph_name      = Column(String, default="agent_graph")
    steps           = Column(JSON, default=list)   # List of step dicts logged at runtime
    status          = Column(String, default="pending")  # pending|running|completed|failed
    result          = Column(Text, default="")
    created_at      = Column(DateTime, default=datetime.utcnow)