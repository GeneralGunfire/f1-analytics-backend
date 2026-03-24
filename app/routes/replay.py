"""
Race Replay API routes
-----------------------
GET /api/replay/available          — list races with complete replay data
GET /api/replay/meta?race_id=X    — metadata for one race replay
GET /api/replay/frames?race_id=X&lap_start=1&lap_end=3  — position frames
GET /api/replay/events?race_id=X  — all events sorted by timestamp_ms
GET /api/replay/track?circuit_id=bahrain  — track map points
"""

from functools import lru_cache
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_

from app.database.connection import get_db
from app.database.models import (
    Race, Circuit, Driver,
    RaceReplaySession, RaceFrame, RaceEvent, TrackMap,
)

router = APIRouter(tags=["replay"])


# ---------------------------------------------------------------------------
# GET /api/replay/available
# ---------------------------------------------------------------------------

@router.get("/api/replay/available")
async def get_available_replays(db: AsyncSession = Depends(get_db)):
    """Return all races that have complete replay data."""
    result = await db.execute(
        select(RaceReplaySession, Race, Circuit)
        .join(Race, RaceReplaySession.race_id == Race.id)
        .join(Circuit, Race.circuit_id == Circuit.id)
        .where(RaceReplaySession.status == "complete")
        .order_by(Race.year.desc(), Race.round)
    )
    rows = result.all()

    return [
        {
            "race_id": race.id,
            "year": race.year,
            "round": race.round,
            "circuit_id": race.circuit_id,
            "name": circuit.name,
            "total_laps": rs.total_laps,
            "frame_count": rs.frame_count,
            "duration_seconds": rs.duration_seconds,
            "extracted_at": rs.extracted_at.isoformat() if rs.extracted_at else None,
        }
        for rs, race, circuit in rows
    ]


# ---------------------------------------------------------------------------
# GET /api/replay/meta
# ---------------------------------------------------------------------------

@router.get("/api/replay/meta")
async def get_replay_meta(
    race_id: int = Query(...),
    db: AsyncSession = Depends(get_db),
):
    """Metadata for a single race replay."""
    # Fetch replay session
    rs_result = await db.execute(
        select(RaceReplaySession).where(RaceReplaySession.race_id == race_id)
    )
    rs = rs_result.scalar_one_or_none()
    if not rs or rs.status != "complete":
        raise HTTPException(404, "Replay not available for this race")

    # Fetch race + circuit
    race_result = await db.execute(
        select(Race, Circuit)
        .join(Circuit, Race.circuit_id == Circuit.id)
        .where(Race.id == race_id)
    )
    row = race_result.first()
    if not row:
        raise HTTPException(404, "Race not found")
    race, circuit = row

    # Fetch drivers for this season
    drv_result = await db.execute(
        select(Driver).where(Driver.year == race.year).order_by(Driver.code)
    )
    drivers = drv_result.scalars().all()

    # Determine which driver codes actually appear in frames for this replay
    from sqlalchemy import distinct, func
    codes_result = await db.execute(
        select(distinct(RaceFrame.driver_code)).where(
            RaceFrame.replay_session_id == rs.id
        )
    )
    active_codes = set(r[0] for r in codes_result.all())

    driver_list = [
        {
            "code": d.code,
            "name": f"{d.first_name} {d.last_name}",
            "team": d.team_id,
            "color": d.color or "#FFFFFF",
        }
        for d in drivers
        if d.code in active_codes
    ]

    return {
        "race_id": race_id,
        "year": race.year,
        "round": race.round,
        "circuit_id": circuit.id,
        "circuit_name": circuit.name,
        "total_laps": rs.total_laps,
        "frame_count": rs.frame_count,
        "duration_seconds": rs.duration_seconds,
        "drivers": driver_list,
        "grid_order": [],  # could populate from race results if needed
    }


# ---------------------------------------------------------------------------
# GET /api/replay/frames
# ---------------------------------------------------------------------------

@router.get("/api/replay/frames")
async def get_replay_frames(
    race_id: int = Query(...),
    lap_start: int = Query(1, ge=1),
    lap_end: int = Query(1, ge=1),
    db: AsyncSession = Depends(get_db),
):
    """
    Returns position frames for laps [lap_start, lap_end] (inclusive).
    Max range = 5 laps.
    Response shape: { lap: { timestamp_ms: { driver_code: {x,y,speed,...} } } }
    """
    if lap_end < lap_start:
        raise HTTPException(400, "lap_end must be >= lap_start")
    if (lap_end - lap_start) > 4:
        raise HTTPException(400, "Maximum 5 laps per request (lap_end - lap_start <= 4)")

    # Resolve replay session id
    rs_result = await db.execute(
        select(RaceReplaySession.id).where(
            and_(
                RaceReplaySession.race_id == race_id,
                RaceReplaySession.status == "complete",
            )
        )
    )
    rs_id = rs_result.scalar_one_or_none()
    if not rs_id:
        raise HTTPException(404, "Replay not available for this race")

    # Fetch frames
    frames_result = await db.execute(
        select(RaceFrame).where(
            and_(
                RaceFrame.replay_session_id == rs_id,
                RaceFrame.lap >= lap_start,
                RaceFrame.lap <= lap_end,
            )
        ).order_by(RaceFrame.lap, RaceFrame.timestamp_ms)
    )
    frames = frames_result.scalars().all()

    # Nest: lap → timestamp_ms → driver_code → data
    out: dict[str, dict[str, dict[str, Any]]] = {}
    for f in frames:
        lap_key = str(f.lap)
        ts_key = str(f.timestamp_ms)
        if lap_key not in out:
            out[lap_key] = {}
        if ts_key not in out[lap_key]:
            out[lap_key][ts_key] = {}
        out[lap_key][ts_key][f.driver_code] = {
            "x": f.x,
            "y": f.y,
            "speed": f.speed,
            "gear": f.gear,
            "drs": f.drs,
            "is_in_pit": f.is_in_pit,
            "position": f.position_in_race,
        }

    return out


# ---------------------------------------------------------------------------
# GET /api/replay/events
# ---------------------------------------------------------------------------

@router.get("/api/replay/events")
async def get_replay_events(
    race_id: int = Query(...),
    db: AsyncSession = Depends(get_db),
):
    """Return all race events sorted by timestamp_ms."""
    rs_result = await db.execute(
        select(RaceReplaySession.id).where(
            and_(
                RaceReplaySession.race_id == race_id,
                RaceReplaySession.status == "complete",
            )
        )
    )
    rs_id = rs_result.scalar_one_or_none()
    if not rs_id:
        raise HTTPException(404, "Replay not available for this race")

    events_result = await db.execute(
        select(RaceEvent)
        .where(RaceEvent.replay_session_id == rs_id)
        .order_by(RaceEvent.timestamp_ms)
    )
    events = events_result.scalars().all()

    return [
        {
            "id": e.id,
            "lap": e.lap,
            "timestamp_ms": e.timestamp_ms,
            "event_type": e.event_type,
            "driver_code": e.driver_code,
            "description": e.description,
            "x": e.x,
            "y": e.y,
        }
        for e in events
    ]


# ---------------------------------------------------------------------------
# GET /api/replay/track
# ---------------------------------------------------------------------------

@lru_cache(maxsize=50)
def _track_cache_key(circuit_id: str) -> str:
    return circuit_id


@router.get("/api/replay/track")
async def get_track_map(
    circuit_id: str = Query(...),
    db: AsyncSession = Depends(get_db),
):
    """Return track map points for a circuit, sorted by point_order."""
    result = await db.execute(
        select(TrackMap)
        .where(TrackMap.circuit_id == circuit_id)
        .order_by(TrackMap.point_order)
    )
    points = result.scalars().all()

    if not points:
        raise HTTPException(404, f"No track map found for circuit: {circuit_id}")

    return [
        {
            "id": p.id,
            "point_order": p.point_order,
            "x": p.x,
            "y": p.y,
            "is_pit_lane": p.is_pit_lane,
            "sector": p.sector,
            "is_drs_zone": p.is_drs_zone,
        }
        for p in points
    ]
