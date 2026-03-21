"""
Race endpoints — lap times, positions, circuit info, events, telemetry by round.

All race/historical data is cached for 24 h with Cache-Control headers.
"""

import logging
from functools import lru_cache
from typing import Annotated, Any

import fastf1
import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Path, Query
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.connection import AsyncSessionLocal
from app.database import models
from app.services.fastf1_service import (
    DRIVER_COLORS,
    get_telemetry_compare,
)


async def get_db():
    async with AsyncSessionLocal() as session:
        yield session

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["race"])

_CACHE_1_DAY = "public, max-age=86400"
_VALID_SESSIONS = {"R", "Q", "FP1", "FP2", "FP3", "S", "SQ"}


# ── Helpers ────────────────────────────────────────────────────────────────────

def _cached_response(data: Any) -> JSONResponse:
    return JSONResponse(
        content=data,
        headers={"Cache-Control": _CACHE_1_DAY},
    )


@lru_cache(maxsize=64)
def _load_session_laps(year: int, round_number: int, session_type: str) -> Any:
    session = fastf1.get_session(year, round_number, session_type)
    session.load(laps=True, telemetry=False, weather=False, messages=False)
    return session


# ── GET /api/race/{year}/{round}/laps ─────────────────────────────────────────

@router.get("/race/{year}/{round}/laps", summary="All lap times for a race session")
async def get_laps(
    year:  Annotated[int, Path(ge=2018, le=2030)],
    round: Annotated[int, Path(ge=1,    le=25)],
    session: Annotated[str, Query(description="Session type")] = "R",
) -> JSONResponse:
    if session.upper() not in _VALID_SESSIONS:
        raise HTTPException(status_code=422, detail=f"Invalid session type: {session}")
    try:
        sess = _load_session_laps(year, round, session.upper())
        rows: list[dict] = []
        for _, lap in sess.laps.iterrows():
            lap_time = lap.get("LapTime")
            if not pd.notna(lap_time):
                continue
            lap_time_s = float(lap_time.total_seconds())
            if lap_time_s <= 0:
                continue

            def _safe_sector(col: str) -> float | None:
                v = lap.get(col)
                return round(float(v.total_seconds()), 3) if pd.notna(v) else None

            rows.append({
                "driver":          str(lap["Driver"]),
                "lap":             int(lap["LapNumber"]),
                "time":            round(lap_time_s, 3),
                "sector1":         _safe_sector("Sector1Time"),
                "sector2":         _safe_sector("Sector2Time"),
                "sector3":         _safe_sector("Sector3Time"),
                "compound":        str(lap["Compound"]) if pd.notna(lap.get("Compound")) else None,
                "isPersonalBest":  bool(lap["IsPersonalBest"]) if pd.notna(lap.get("IsPersonalBest")) else False,
            })
        return _cached_response(rows)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to load laps year=%d round=%d session=%s", year, round, session)
        raise HTTPException(status_code=503, detail="FastF1 lap data unavailable") from exc


# ── GET /api/race/{year}/{round}/telemetry ─────────────────────────────────────

@router.get("/race/{year}/{round}/telemetry", summary="Driver telemetry for compare view")
async def get_race_telemetry(
    year:    Annotated[int, Path(ge=2018, le=2030)],
    round:   Annotated[int, Path(ge=1,    le=25)],
    drivers: Annotated[str, Query(description="Comma-separated codes, e.g. VER,LEC")] = "VER,LEC",
    session: Annotated[str, Query()] = "Q",
) -> JSONResponse:
    if session.upper() not in _VALID_SESSIONS:
        raise HTTPException(status_code=422, detail=f"Invalid session type: {session}")

    codes = sorted(c.strip().upper() for c in drivers.split(",") if c.strip())
    if not codes:
        raise HTTPException(status_code=422, detail="No driver codes provided")

    # Load circuit name to pass to existing telemetry service
    try:
        schedule = fastf1.get_event_schedule(year, include_testing=False)
        row = schedule[schedule["RoundNumber"] == round]
        if row.empty:
            raise ValueError(f"Round {round} not found in {year} schedule")
        race_name = str(row.iloc[0]["Location"])
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    try:
        result = get_telemetry_compare(year, race_name, session.upper(), ",".join(codes))
    except Exception as exc:
        logger.exception("Telemetry error year=%d round=%d drivers=%s", year, round, codes)
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    # Re-shape to the frontend's DriverTelemetry[] format
    output: list[dict] = []
    for drv_data in result.get("drivers", []):
        code = drv_data["driver"]
        points: list[dict] = []
        dist   = drv_data.get("distance", [])
        speed  = drv_data.get("speed",    [])
        throt  = drv_data.get("throttle", [])
        brake  = drv_data.get("brake",    [])
        gear   = drv_data.get("gear",     [])
        drs    = drv_data.get("drs",      [])
        delta  = drv_data.get("delta",    [])
        time   = drv_data.get("time",     [])

        for i, d in enumerate(dist):
            points.append({
                "distance": d,
                "speed":    speed[i]  if i < len(speed)  else 0,
                "throttle": throt[i]  if i < len(throt)  else 0,
                "brake":    brake[i]  if i < len(brake)  else 0,
                "gear":     gear[i]   if i < len(gear)   else 0,
                "drs":      drs[i]    if i < len(drs)    else 0,
                "time":     delta[i]  if i < len(delta)  else (time[i] if i < len(time) else 0),
            })

        output.append({
            "driver": code,
            "color":  DRIVER_COLORS.get(code, "#ffffff"),
            "data":   points,
        })

    return _cached_response(output)


# ── GET /api/race/{year}/{round}/positions ─────────────────────────────────────

@router.get("/race/{year}/{round}/positions", summary="Race classification position per lap")
async def get_positions(
    year:  Annotated[int, Path(ge=2018, le=2030)],
    round: Annotated[int, Path(ge=1,    le=25)],
) -> JSONResponse:
    """Returns lap-by-lap race classification positions for all drivers."""
    try:
        sess = _load_session_laps(year, round, "R")
        # Build {driver: [{lap, position}, ...]} from laps DataFrame
        result: dict[str, list[dict]] = {}
        for _, lap in sess.laps.iterrows():
            driver = str(lap["Driver"])
            pos_val = lap.get("Position")
            lap_num = lap.get("LapNumber")
            if not pd.notna(pos_val) or not pd.notna(lap_num):
                continue
            if driver not in result:
                result[driver] = []
            result[driver].append({
                "lap":      int(lap_num),
                "position": int(pos_val),
            })
        # Sort each driver's laps by lap number
        for driver in result:
            result[driver].sort(key=lambda x: x["lap"])
        return _cached_response(result)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Failed to load positions year=%d round=%d", year, round)
        raise HTTPException(status_code=503, detail="FastF1 position data unavailable") from exc


# ── GET /api/circuit/{year}/{round}/info ──────────────────────────────────────

@router.get("/circuit/{year}/{round}/info", summary="Circuit metadata for a round")
async def get_circuit_info(
    year:  Annotated[int, Path(ge=2018, le=2030)],
    round: Annotated[int, Path(ge=1,    le=25)],
    db:    AsyncSession = Depends(get_db),
) -> JSONResponse:
    # Look up race -> circuit from DB (no FastF1 network call needed)
    result = await db.execute(
        select(models.Race, models.Circuit)
        .join(models.Circuit, models.Race.circuit_id == models.Circuit.id)
        .where(models.Race.year == year, models.Race.round == round)
    )
    row = result.first()
    if not row:
        raise HTTPException(status_code=404, detail=f"Round {round} not found in {year}")
    race, circuit = row
    data = {
        "name":        race.name,
        "country":     circuit.country,
        "location":    circuit.city,
        "lat":         float(circuit.lat) if circuit.lat else 0.0,
        "lon":         float(circuit.lon) if circuit.lon else 0.0,
        "trackLength": float(circuit.length_km) if circuit.length_km else 0,
        "turns":       circuit.turns or 0,
        "drsZones":    circuit.drs_zones or 0,
        "lapRecord":   circuit.lap_record_time or "",
        "lapRecordDriver": circuit.lap_record_driver or "",
        "lapRecordYear":   circuit.lap_record_year or 0,
    }
    return _cached_response(data)


# ── GET /api/race/{year}/{round}/events ───────────────────────────────────────

@router.get("/race/{year}/{round}/events", summary="Race events (pitstops, safety cars…)")
async def get_race_events(
    year:  Annotated[int, Path(ge=2018, le=2030)],
    round: Annotated[int, Path(ge=1,    le=25)],
) -> JSONResponse:
    try:
        sess = _load_session_laps(year, round, "R")
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    events: list[dict] = []

    # Pit stops (lap where PitInTime is not null)
    try:
        for _, lap in sess.laps.iterrows():
            if pd.notna(lap.get("PitInTime")):
                events.append({
                    "lap":    int(lap["LapNumber"]),
                    "type":   "pitstop",
                    "driver": str(lap["Driver"]),
                    "detail": f"{lap['Driver']} pit stop",
                })
    except Exception as exc:
        logger.warning("Could not extract pit stops: %s", exc)

    return _cached_response(sorted(events, key=lambda e: e["lap"]))
