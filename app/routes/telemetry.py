import logging
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query

from app.models.session import TelemetryCompareResponse
from app.services.fastf1_service import get_telemetry_compare

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["telemetry"])

_VALID_SESSIONS = {"R", "Q", "FP1", "FP2", "FP3", "S", "SQ"}


@router.get(
    "/telemetry/compare",
    response_model=TelemetryCompareResponse,
    summary="Compare lap telemetry for up to 5 drivers",
)
async def compare_telemetry(
    year: Annotated[
        int,
        Query(ge=2018, le=2030, description="Championship year"),
    ] = 2024,
    race: Annotated[
        str,
        Query(min_length=1, max_length=100, description="GP name or country, e.g. Monaco"),
    ] = "Monaco",
    session: Annotated[
        str,
        Query(description="Session type: R, Q, FP1, FP2, FP3, S"),
    ] = "Q",
    drivers: Annotated[
        str,
        Query(
            description="Comma-separated driver codes, max 5 (e.g. VER,HAM,NOR)",
            min_length=2,
            max_length=50,
        ),
    ] = "VER,HAM,NOR",
) -> TelemetryCompareResponse:
    """
    Returns telemetry channels (speed, throttle, brake, gear, delta) for each
    driver's fastest lap in the given session, all interpolated to a common
    distance grid.

    The first call for an uncached session may take 15–30 seconds while FastF1
    downloads data.  Subsequent calls with the same parameters are instant.
    """
    # Parse + validate driver list
    driver_codes = [d.strip().upper() for d in drivers.split(",") if d.strip()]
    if not driver_codes:
        raise HTTPException(status_code=422, detail="At least one driver code is required.")
    if len(driver_codes) > 5:
        raise HTTPException(status_code=422, detail="Maximum 5 drivers allowed per request.")

    # Validate session type
    session_upper = session.strip().upper()
    if session_upper not in _VALID_SESSIONS:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid session '{session}'. Valid values: {', '.join(sorted(_VALID_SESSIONS))}",
        )

    # Sort driver codes for a stable cache key
    drivers_key = ",".join(sorted(driver_codes))

    try:
        result = get_telemetry_compare(year, race, session_upper, drivers_key)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception(
            "Telemetry fetch failed year=%d race=%s session=%s drivers=%s",
            year, race, session_upper, drivers_key,
        )
        raise HTTPException(
            status_code=502,
            detail=f"Failed to load telemetry data: {exc}",
        ) from exc

    return TelemetryCompareResponse(**result)
