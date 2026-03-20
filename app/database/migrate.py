import asyncio
import logging
from app.database.connection import Base, engine, test_connection
from app.database import models  # noqa: F401 — import triggers registration

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def run_migration():
    logger.info("Testing database connection...")
    ok = await test_connection()
    if not ok:
        logger.error("Cannot connect. Check DATABASE_URL in .env")
        return False

    logger.info("Creating tables...")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("All tables created successfully")
    return True


if __name__ == "__main__":
    asyncio.run(run_migration())
