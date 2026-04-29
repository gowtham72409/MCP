from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import declarative_base
from backend.config import DATABASE_URL

DATABASE_URL = DATABASE_URL

engine = create_async_engine(DATABASE_URL,
    echo=False,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

Base=declarative_base()

async def get_session():
    """Dependency / context manager that yields an AsyncSession."""
    async with AsyncSessionLocal() as session:
        yield session