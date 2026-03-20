"""
Analytics routes: all-laps data and CSV export.
"""
import logging
from typing import Annotated, AsyncIterator

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import StreamingResponse

from app.services.fastf1_service import get_all_laps, get_race_positions, get_telemetry_compare

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["analytics"])

_VALID_SESSIONS = {"R", "Q", "FP1", "FP2", "FP3", "S", "SQ"}


# ── GET /api/laps ─────────────────────────────────────────────────────────────

@router.get(
    "/laps",
    summary="All lap times for every driver in a session",
)
async def get_laps(
    year: Annotated[int, Query(ge=2018, le=2030)] = 2024,
    race: Annotated[str, Query(min_length=1, max_length=100)] = "Monaco",
    session: Annotated[str, Query(description="R, Q, FP1, FP2, FP3, S")] = "R",
) -> dict:
    """
    Returns every valid lap time for all drivers in a session.
    Loads only lap data (no telemetry), so first call is ~5–10 s.

    Useful for race-pace charts, stint analysis, and per-driver lap progression.
    """
    session_upper = session.strip().upper()
    if session_upper not in _VALID_SESSIONS:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid session '{session}'. Valid: {', '.join(sorted(_VALID_SESSIONS))}",
        )
    try:
        laps = get_all_laps(year, race, session_upper)
    except Exception as exc:
        logger.exception("get_all_laps failed year=%d race=%s session=%s", year, race, session_upper)
        raise HTTPException(status_code=502, detail=f"Failed to load laps: {exc}") from exc

    return {
        "year": year,
        "race": race,
        "session": session_upper,
        "laps": laps,
    }


# ── GET /api/export/csv ───────────────────────────────────────────────────────

@router.get(
    "/export/csv",
    summary="Download telemetry comparison as CSV",
    response_class=StreamingResponse,
)
async def export_csv(
    year: Annotated[int, Query(ge=2018, le=2030)] = 2024,
    race: Annotated[str, Query(min_length=1, max_length=100)] = "Monaco",
    session: Annotated[str, Query()] = "Q",
    drivers: Annotated[str, Query(min_length=2, max_length=50)] = "VER,HAM,NOR",
) -> StreamingResponse:
    """
    Streams the telemetry comparison as a CSV file download.

    Reuses the cached telemetry from /api/telemetry/compare, so if that
    endpoint has been called already this responds instantly.
    """
    session_upper = session.strip().upper()
    if session_upper not in _VALID_SESSIONS:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid session '{session}'. Valid: {', '.join(sorted(_VALID_SESSIONS))}",
        )

    driver_codes = [d.strip().upper() for d in drivers.split(",") if d.strip()]
    if not driver_codes:
        raise HTTPException(status_code=422, detail="At least one driver code required.")
    if len(driver_codes) > 5:
        raise HTTPException(status_code=422, detail="Maximum 5 drivers.")

    drivers_key = ",".join(sorted(driver_codes))

    try:
        result = get_telemetry_compare(year, race, session_upper, drivers_key)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("CSV export failed year=%d race=%s session=%s", year, race, session_upper)
        raise HTTPException(status_code=502, detail=f"Failed to load telemetry: {exc}") from exc

    async def _generate() -> AsyncIterator[str]:
        yield "Driver,LapNumber,LapTime,Distance_m,Speed_kmh,Throttle_pct,Brake_pct,Gear,Delta_s\n"
        for driver, tel in result["telemetry"].items():
            lap_num = tel.get("lap_number", 0)
            lap_time = tel.get("lap_time", "")
            dist = tel["distance"]
            speed = tel["speed"]
            throttle = tel["throttle"]
            brake = tel["brake"]
            gear = tel["gear"]
            delta = tel["delta"]
            n = len(dist)
            for i in range(n):
                yield (
                    f"{driver},{lap_num},{lap_time},"
                    f"{dist[i]},{speed[i]},{throttle[i]},"
                    f"{brake[i]},{gear[i]},{delta[i]}\n"
                )

    safe_race = race.replace(" ", "_").replace("/", "-")
    filename = f"f1-telemetry-{year}-{safe_race}-{session_upper}.csv"

    return StreamingResponse(
        _generate(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ── GET /api/race/positions ───────────────────────────────────────────────────

@router.get(
    "/race/positions",
    summary="Lap-by-lap timing data for all drivers in a race",
)
async def get_race_positions_endpoint(
    year: Annotated[int, Query(ge=2018, le=2030, description="Championship year")] = 2024,
    race: Annotated[str, Query(min_length=1, max_length=100, description="Race/GP name")] = "Monaco",
) -> dict:
    """
    Returns lap-by-lap timing data for all drivers in a race.
    Used for race replay visualization.
    First call takes 15–30 s (loading from FastF1), subsequent calls instant (cached).
    """
    try:
        data = get_race_positions(year, race)
        return data
    except Exception as exc:
        logger.exception("Race positions error year=%d race=%s", year, race)
        raise HTTPException(
            status_code=502,
            detail=f"Failed to load race data: {exc}",
        ) from exc
