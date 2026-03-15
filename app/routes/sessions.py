import logging
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query

from app.models.session import Circuit, SessionListResponse
from app.services.fastf1_service import get_event_schedule

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["sessions"])


@router.get(
    "/sessions",
    response_model=SessionListResponse,
    summary="List all rounds for a season",
)
async def list_sessions(
    year: Annotated[int, Query(ge=1950, le=2100, description="Championship year")] = 2024,
) -> SessionListResponse:
    """
    Returns the full race calendar for the requested season.
    Data is sourced from FastF1 and cached in-memory.
    """
    try:
        events = get_event_schedule(year)
    except Exception as exc:
        logger.exception("Failed to fetch schedule for year %d", year)
        raise HTTPException(status_code=502, detail=f"Failed to fetch schedule: {exc}") from exc

    circuits = [Circuit(**event) for event in events]
    return SessionListResponse(season=year, rounds=circuits)
