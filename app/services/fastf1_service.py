import logging
import os
from functools import lru_cache
from typing import Any

import fastf1

from app.config import get_settings

logger = logging.getLogger(__name__)


def _ensure_cache_dir(cache_dir: str) -> None:
    os.makedirs(cache_dir, exist_ok=True)


def init_fastf1_cache() -> None:
    """Enable FastF1 disk cache. Call once at startup."""
    settings = get_settings()
    cache_dir = settings.ff1_cache_dir
    _ensure_cache_dir(cache_dir)
    fastf1.Cache.enable_cache(cache_dir)
    logger.info("FastF1 cache enabled at %s", cache_dir)


def load_session(year: int, round_number: int, session_type: str = "R") -> Any:
    """
    Load a FastF1 session and return it with laps data.

    Args:
        year: Championship year (e.g. 2024)
        round_number: Round number within the season
        session_type: One of 'R' (Race), 'Q' (Qualifying), 'FP1', 'FP2', 'FP3', 'S' (Sprint)

    Returns:
        fastf1.core.Session with laps loaded
    """
    logger.info("Loading session year=%d round=%d type=%s", year, round_number, session_type)
    session = fastf1.get_session(year, round_number, session_type)
    session.load(laps=True, telemetry=False, weather=False, messages=False)
    return session


@lru_cache(maxsize=32)
def get_event_schedule(year: int) -> list[dict]:
    """
    Return the full event schedule for a given season.
    Results are cached in-memory per year.
    """
    logger.info("Fetching event schedule for %d", year)
    schedule = fastf1.get_event_schedule(year, include_testing=False)

    events: list[dict] = []
    for _, row in schedule.iterrows():
        events.append(
            {
                "round": int(row["RoundNumber"]),
                "country": str(row["Country"]),
                "circuit_name": str(row["OfficialEventName"]),
                "location": str(row["Location"]),
                "date": str(row["EventDate"].date()),
                "session_types": _available_session_types(row),
            }
        )
    return events


def _available_session_types(row: Any) -> list[str]:
    """Extract non-null session type names from a schedule row."""
    types: list[str] = []
    for i in range(1, 6):
        name = row.get(f"Session{i}", None)
        if name and str(name).strip() not in ("", "nan", "None"):
            types.append(str(name))
    return types
