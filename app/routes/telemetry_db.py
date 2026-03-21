from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from app.database.connection import get_db
from app.database.models import Race, TelemetrySession, DriverTelemetry
import json
from datetime import date

router = APIRouter(prefix="/api/telemetry", tags=["telemetry"])


@router.get("/compare")
async def compare_telemetry(
    year: int,
    race: str = Query(..., description="FastF1 race key e.g. Monaco"),
    session: str = Query(
        ..., description="Q, R, FP1, FP2, FP3"
    ),
    drivers: str = Query(
        ..., description="Comma-separated driver codes, max 5"
    ),
    db: AsyncSession = Depends(get_db)
):
    driver_list = [d.strip().upper() for d in drivers.split(",")]

    if len(driver_list) < 1 or len(driver_list) > 5:
        raise HTTPException(400, "Provide 1-5 driver codes")

    valid_sessions = ["Q", "R", "FP1", "FP2", "FP3", "S"]
    if session not in valid_sessions:
        raise HTTPException(
            400, f"Session must be one of: {valid_sessions}"
        )

    # Find the race in database
    race_result = await db.execute(
        select(Race).where(
            and_(
                Race.year == year,
                Race.fastf1_key == race
            )
        )
    )
    race_row = race_result.scalar_one_or_none()
    if not race_row:
        raise HTTPException(
            404, f"Race not found: {year} {race}"
        )

    if race_row.date > date.today():
        raise HTTPException(
            400, "Race has not happened yet"
        )

    # Find the telemetry session
    ts_result = await db.execute(
        select(TelemetrySession).where(
            and_(
                TelemetrySession.race_id == race_row.id,
                TelemetrySession.session_type == session
            )
        )
    )
    tel_session = ts_result.scalar_one_or_none()

    if not tel_session:
        raise HTTPException(
            404,
            detail={
                "error": "telemetry_not_computed",
                "message": (
                    f"Telemetry for {year} {race} {session} "
                    f"has not been computed yet."
                ),
                "race": race,
                "year": year,
                "session": session
            }
        )

    if tel_session.status != "complete":
        raise HTTPException(
            503,
            detail={
                "error": "telemetry_processing",
                "message": "Telemetry is still being computed.",
                "status": tel_session.status
            }
        )

    # Fetch telemetry for requested drivers
    dt_result = await db.execute(
        select(DriverTelemetry).where(
            and_(
                DriverTelemetry.session_id == tel_session.id,
                DriverTelemetry.driver_code.in_(driver_list)
            )
        )
    )
    driver_telemetry_rows = dt_result.scalars().all()

    if not driver_telemetry_rows:
        raise HTTPException(
            404,
            f"No telemetry found for drivers: {driver_list}"
        )

    # Find fastest driver
    fastest_driver = min(
        driver_telemetry_rows,
        key=lambda x: float(x.fastest_lap_seconds or 999)
    ).driver_code

    # Build response
    drivers_response = {}
    for dt in driver_telemetry_rows:
        drivers_response[dt.driver_code] = {
            "fastestLapTime": dt.fastest_lap_time,
            "fastestLapSeconds": float(dt.fastest_lap_seconds),
            "topSpeedKmh": float(dt.top_speed_kmh),
            "avgSpeedKmh": float(dt.avg_speed_kmh),
            "throttleAvgPct": float(dt.throttle_avg_pct or 0),
            "brakeEvents": dt.brake_events,
            "telemetry": {
                "distance": json.loads(dt.distance_trace),
                "speed": json.loads(dt.speed_trace),
                "throttle": json.loads(dt.throttle_trace),
                "brake": json.loads(dt.brake_trace),
                "gear": json.loads(dt.gear_trace)
            },
            "delta": json.loads(dt.delta_trace)
        }

    return {
        "race": race,
        "year": year,
        "session": session,
        "sessionDisplay": {
            "Q": "Qualifying", "R": "Race",
            "FP1": "Practice 1", "FP2": "Practice 2",
            "FP3": "Practice 3", "S": "Sprint"
        }.get(session, session),
        "fastestDriver": fastest_driver,
        "distancePoints": tel_session.distance_points,
        "driversFound": [dt.driver_code for dt in driver_telemetry_rows],
        "driversRequested": driver_list,
        "drivers": drivers_response
    }


@router.get("/available")
async def get_available_sessions(
    year: int,
    db: AsyncSession = Depends(get_db)
):
    result = await db.execute(
        select(TelemetrySession, Race).join(
            Race, TelemetrySession.race_id == Race.id
        ).where(
            and_(
                Race.year == year,
                TelemetrySession.status == "complete"
            )
        ).order_by(Race.round)
    )
    rows = result.all()

    return {
        "year": year,
        "available": [
            {
                "circuitId": race.circuit_id,
                "fastf1Key": race.fastf1_key,
                "round": race.round,
                "session": ts.session_type,
                "computedAt": ts.computed_at.isoformat()
                    if ts.computed_at else None
            }
            for ts, race in rows
        ]
    }


@router.get("/drivers")
async def get_available_drivers(
    year: int,
    race: str,
    session: str = "Q",
    db: AsyncSession = Depends(get_db)
):
    race_result = await db.execute(
        select(Race).where(
            and_(Race.year == year, Race.fastf1_key == race)
        )
    )
    race_row = race_result.scalar_one_or_none()
    if not race_row:
        raise HTTPException(404, "Race not found")

    ts_result = await db.execute(
        select(TelemetrySession).where(
            and_(
                TelemetrySession.race_id == race_row.id,
                TelemetrySession.session_type == session
            )
        )
    )
    tel_session = ts_result.scalar_one_or_none()
    if not tel_session or tel_session.status != "complete":
        return {"drivers": [], "available": False}

    dt_result = await db.execute(
        select(DriverTelemetry.driver_code,
               DriverTelemetry.fastest_lap_time,
               DriverTelemetry.fastest_lap_seconds).where(
            DriverTelemetry.session_id == tel_session.id
        ).order_by(DriverTelemetry.fastest_lap_seconds)
    )
    rows = dt_result.all()

    return {
        "year": year,
        "race": race,
        "session": session,
        "available": True,
        "drivers": [
            {
                "code": r.driver_code,
                "fastestLapTime": r.fastest_lap_time,
                "fastestLapSeconds": float(r.fastest_lap_seconds)
            } for r in rows
        ]
    }
