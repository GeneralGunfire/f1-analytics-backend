from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy import text
import logging
import os
from dotenv import load_dotenv

load_dotenv()
logger = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL", "")

# Convert postgresql:// to postgresql+asyncpg:// if needed
if DATABASE_URL.startswith("postgresql://"):
    ASYNC_DATABASE_URL = DATABASE_URL.replace(
        "postgresql://", "postgresql+asyncpg://", 1
    )
elif DATABASE_URL.startswith("postgres://"):
    ASYNC_DATABASE_URL = DATABASE_URL.replace(
        "postgres://", "postgresql+asyncpg://", 1
    )
else:
    ASYNC_DATABASE_URL = DATABASE_URL

engine = create_async_engine(
    ASYNC_DATABASE_URL or "postgresql+asyncpg://localhost/placeholder",
    pool_size=2,
    max_overflow=1,
    pool_pre_ping=True,
    pool_recycle=1800,
    echo=False
)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False
)


class Base(DeclarativeBase):
    pass


async def get_db():
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()


async def test_connection():
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        logger.info("Database connection successful")
        return True
    except Exception as e:
        logger.error(f"Database connection failed: {e}")
        return False
