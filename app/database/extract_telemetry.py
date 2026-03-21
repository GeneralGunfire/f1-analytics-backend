import asyncio
import fastf1
import numpy as np
import json
import logging
import time
from datetime import datetime, date
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlalchemy import select, and_
from app.database.models import (
    Race, TelemetrySession, DriverTelemetry
)
from dotenv import load_dotenv
import os

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# FastF1 cache directory
fastf1.Cache.enable_cache("./cache/fastf1")

DATABASE_URL = os.getenv("DATABASE_URL", "")
if DATABASE_URL.startswith("postgresql://"):
    ASYNC_URL = DATABASE_URL.replace(
        "postgresql://", "postgresql+asyncpg://", 1
    )
elif DATABASE_URL.startswith("postgres://"):
    ASYNC_URL = DATABASE_URL.replace(
        "postgres://", "postgresql+asyncpg://", 1
    )
else:
    ASYNC_URL = DATABASE_URL

engine = create_async_engine(ASYNC_URL, pool_size=2, max_overflow=1)
AsyncSessionLocal = async_sessionmaker(engine, class_=AsyncSession)

SESSIONS_TO_EXTRACT = ["Q", "R"]
# Q = Qualifying (fastest lap per driver)
# R = Race (fastest lap per driver during race)

YEARS_TO_EXTRACT = [2023, 2024, 2025, 2026]
# 2022 added separately at end if time permits

DISTANCE_POINTS = 500


async def extract_session(
    db: AsyncSession,
    race_id: int,
    year: int,
    fastf1_key: str,
    session_type: str,
    circuit_name: str
):
    logger.info(
        f"Processing {year} {circuit_name} {session_type}..."
    )

    # Check if already extracted
    existing = await db.execute(
        select(TelemetrySession).where(
            and_(
                TelemetrySession.race_id == race_id,
                TelemetrySession.session_type == session_type
            )
        )
    )
    existing_session = existing.scalar_one_or_none()
    if existing_session and existing_session.status == "complete":
        logger.info(
            f"  Already extracted — skipping"
        )
        return True

    # Load FastF1 session
    try:
        f1_session = fastf1.get_session(
            year, fastf1_key,
            "Qualifying" if session_type == "Q" else "Race"
        )
        f1_session.load(telemetry=True, laps=True, weather=False)
        logger.info(f"  FastF1 loaded successfully")
    except Exception as e:
        logger.error(f"  FastF1 load failed: {e}")
        return False

    # Create or update telemetry session record
    if existing_session:
        tel_session = existing_session
        tel_session.status = "processing"
    else:
        tel_session = TelemetrySession(
            race_id=race_id,
            session_type=session_type,
            distance_points=DISTANCE_POINTS,
            status="processing"
        )
        db.add(tel_session)

    await db.commit()
    await db.refresh(tel_session)

    # Get all driver codes in this session
    driver_codes = f1_session.laps["Driver"].unique().tolist()
    logger.info(f"  Found {len(driver_codes)} drivers")

    # Find fastest lap time across all drivers for delta calc
    fastest_time = float("inf")
    fastest_driver = None
    driver_lap_data = {}

    for code in driver_codes:
        try:
            laps = f1_session.laps.pick_drivers(code)
            if laps.empty:
                continue
            fastest_lap = laps.pick_fastest()
            if fastest_lap is None or fastest_lap.empty:
                continue
            car_data = fastest_lap.get_car_data().add_distance()
            if car_data.empty or len(car_data) < 10:
                continue
            lap_time_s = fastest_lap["LapTime"].total_seconds()
            if np.isnan(lap_time_s):
                continue
            driver_lap_data[code] = {
                "lap": fastest_lap,
                "car_data": car_data,
                "lap_time_s": lap_time_s
            }
            if lap_time_s < fastest_time:
                fastest_time = lap_time_s
                fastest_driver = code
        except Exception as e:
            logger.warning(f"  Skipping {code}: {e}")
            continue

    if not driver_lap_data:
        logger.error(f"  No valid telemetry found for any driver")
        tel_session.status = "failed"
        await db.commit()
        return False

    logger.info(
        f"  Fastest driver: {fastest_driver} "
        f"({fastest_time:.3f}s)"
    )

    # Build distance grid from fastest driver
    ref_data = driver_lap_data[fastest_driver]["car_data"]
    max_distance = ref_data["Distance"].max()
    distance_grid = np.linspace(0, max_distance, DISTANCE_POINTS)

    # Build reference time array for delta calculation
    ref_time_array = np.interp(
        distance_grid,
        ref_data["Distance"].values,
        ref_data["Time"].dt.total_seconds().values
    )

    # Pre-load any existing driver telemetry rows in one query
    existing_dt_result = await db.execute(
        select(DriverTelemetry).where(
            DriverTelemetry.session_id == tel_session.id
        )
    )
    existing_dt_map = {
        row.driver_code: row
        for row in existing_dt_result.scalars().all()
    }

    # Process each driver — no DB calls inside the loop
    drivers_processed = 0
    for code, data in driver_lap_data.items():
        try:
            car_data = data["car_data"]
            lap_time_s = data["lap_time_s"]

            # Format lap time string
            minutes = int(lap_time_s // 60)
            seconds = lap_time_s % 60
            lap_time_str = f"{minutes}:{seconds:06.3f}"

            # Interpolate all channels to distance grid
            speed = np.interp(
                distance_grid,
                car_data["Distance"].values,
                car_data["Speed"].values
            )
            throttle = np.interp(
                distance_grid,
                car_data["Distance"].values,
                car_data["Throttle"].values
            )
            brake = np.interp(
                distance_grid,
                car_data["Distance"].values,
                car_data["Brake"].astype(float).values
            )
            gear = np.interp(
                distance_grid,
                car_data["Distance"].values,
                car_data["nGear"].values
            )
            time_array = np.interp(
                distance_grid,
                car_data["Distance"].values,
                car_data["Time"].dt.total_seconds().values
            )

            # Calculate delta vs fastest driver
            if code == fastest_driver:
                delta = [0.0] * DISTANCE_POINTS
            else:
                delta = (time_array - ref_time_array).tolist()

            # Calculate summary stats
            top_speed = float(car_data["Speed"].max())
            avg_speed = float(car_data["Speed"].mean())
            throttle_avg = float(car_data["Throttle"].mean())
            brake_events = int(
                (car_data["Brake"].astype(float).diff() > 0.5).sum()
            )

            dt = existing_dt_map.get(code)
            if dt is None:
                dt = DriverTelemetry(
                    session_id=tel_session.id,
                    driver_code=code
                )
                db.add(dt)

            # Store traces as compact JSON
            dt.fastest_lap_time = lap_time_str
            dt.fastest_lap_seconds = round(lap_time_s, 3)
            dt.top_speed_kmh = round(top_speed, 1)
            dt.avg_speed_kmh = round(avg_speed, 1)
            dt.throttle_avg_pct = round(throttle_avg, 1)
            dt.brake_events = brake_events
            dt.speed_trace = json.dumps(
                [round(x, 1) for x in speed.tolist()]
            )
            dt.throttle_trace = json.dumps(
                [round(x, 1) for x in throttle.tolist()]
            )
            dt.brake_trace = json.dumps(
                [round(x, 3) for x in brake.tolist()]
            )
            dt.gear_trace = json.dumps(
                [int(round(x)) for x in gear.tolist()]
            )
            dt.distance_trace = json.dumps(
                [round(x, 1) for x in distance_grid.tolist()]
            )
            dt.delta_trace = json.dumps(
                [round(x, 3) for x in delta]
            )

            drivers_processed += 1
            logger.info(f"    {code}: {lap_time_str} ✓")

        except Exception as e:
            logger.warning(f"    {code} failed: {e}")
            continue

    # Single commit for all drivers
    tel_session.status = "complete"
    tel_session.computed_at = datetime.utcnow()
    await db.commit()

    logger.info(
        f"  Complete: {drivers_processed}/{len(driver_lap_data)} "
        f"drivers processed"
    )
    return True


async def run_extraction():
    logger.info("Starting telemetry extraction...")
    logger.info(
        f"Years: {YEARS_TO_EXTRACT}, "
        f"Sessions: {SESSIONS_TO_EXTRACT}"
    )

    async with AsyncSessionLocal() as db:
        today = date.today()

        total_processed = 0
        total_skipped = 0
        total_failed = 0

        for year in YEARS_TO_EXTRACT:
            logger.info(f"\n{'='*50}")
            logger.info(f"YEAR: {year}")
            logger.info(f"{'='*50}")

            # Get all completed races for this year
            result = await db.execute(
                select(Race).where(
                    and_(
                        Race.year == year,
                        Race.date <= today
                    )
                ).order_by(Race.round)
            )
            races = result.scalars().all()
            logger.info(f"Found {len(races)} completed races")

            for race in races:
                for session_type in SESSIONS_TO_EXTRACT:
                    try:
                        success = await extract_session(
                            db=db,
                            race_id=race.id,
                            year=year,
                            fastf1_key=race.fastf1_key,
                            session_type=session_type,
                            circuit_name=race.circuit_id
                        )
                        if success:
                            total_processed += 1
                        else:
                            total_failed += 1
                    except Exception as e:
                        logger.error(
                            f"Unexpected error {year} "
                            f"{race.circuit_id} {session_type}: {e}"
                        )
                        total_failed += 1

                    # Small delay between sessions to be safe
                    time.sleep(0.5)

        logger.info(f"\n{'='*50}")
        logger.info(f"EXTRACTION COMPLETE")
        logger.info(f"Processed: {total_processed}")
        logger.info(f"Skipped (already done): {total_skipped}")
        logger.info(f"Failed: {total_failed}")
        logger.info(f"{'='*50}")


if __name__ == "__main__":
    asyncio.run(run_extraction())
