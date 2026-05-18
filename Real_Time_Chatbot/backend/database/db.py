from sqlalchemy.ext.asyncio import create_async_engine,AsyncSession
from sqlalchemy.orm import declarative_base,sessionmaker
from Real_Time_Chatbot.backend.config import DATABASE_URL

engine=create_async_engine(DATABASE_URL,echo=False)
AsyncSessionLocal=sessionmaker(bind=engine,class_=AsyncSession,expire_on_commit=False)

Base=declarative_base()

async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

async def get_db():
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
 
