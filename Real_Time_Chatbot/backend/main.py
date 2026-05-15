from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from Real_Time_Chatbot.backend.router import agents, chat, skill
from Real_Time_Chatbot.backend.router import system
from Real_Time_Chatbot.backend.database.db import init_db

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(agents.router, prefix="/api")
app.include_router(chat.router, prefix="/api")
app.include_router(skill.router, prefix="/api")
app.include_router(system.router, prefix="/api")

@app.on_event("startup")
async def on_startup():
    await init_db()