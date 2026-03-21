import asyncio
import sys
sys.path.insert(0, ".")

from app.database.extract_telemetry import (
    extract_session, AsyncSessionLocal
)


async def test_single():
    async with AsyncSessionLocal() as db:
        from sqlalchemy import select, and_
        from app.database.models import Race
        result = await db.execute(
            select(Race).where(
                and_(Race.year == 2024, Race.circuit_id == "bahrain")
            )
        )
        race = result.scalar_one()
        print(f"Testing: 2024 Bahrain Q (race_id={race.id})")

        success = await extract_session(
            db=db,
            race_id=race.id,
            year=2024,
            fastf1_key="Bahrain",
            session_type="Q",
            circuit_name="bahrain"
        )
        print(f"Result: {'SUCCESS' if success else 'FAILED'}")


asyncio.run(test_single())
