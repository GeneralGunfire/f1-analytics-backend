import logging
import os
from functools import lru_cache
from typing import Any

import fastf1
import numpy as np
import pandas as pd

from app.config import get_settings

logger = logging.getLogger(__name__)

# ── Driver colour palette (2024 season) ───────────────────────────────────

DRIVER_COLORS: dict[str, str] = {
    "VER": "#3671C6", "PER": "#3671C6",
    "HAM": "#27F4D2", "RUS": "#27F4D2",
    "LEC": "#E8002D", "SAI": "#E8002D",
    "NOR": "#FF8000", "PIA": "#FF8000",
    "ALO": "#358C75", "STR": "#358C75",
    "GAS": "#0090FF", "OCO": "#0090FF",
    "TSU": "#356CAC", "RIC": "#356CAC",
    "ZHO": "#900000", "BOT": "#900000",
    "MAG": "#B6BABD", "HUL": "#B6BABD",
    "ALB": "#64C4FF", "SAR": "#64C4FF",
    "LAW": "#356CAC", "BEA": "#B6BABD",
    "ANT": "#27F4D2", "DOO": "#FF8000",
    "HAD": "#64C4FF",
}


# ── Cache initialisation ───────────────────────────────────────────────────

def _ensure_cache_dir(cache_dir: str) -> None:
    os.makedirs(cache_dir, exist_ok=True)


def init_fastf1_cache() -> None:
    """Enable FastF1 disk cache. Called once at startup."""
    settings = get_settings()
    cache_dir = settings.ff1_cache_dir
    _ensure_cache_dir(cache_dir)
    fastf1.Cache.enable_cache(cache_dir)
    logger.info("FastF1 cache enabled at %s", cache_dir)


# ── Session schedule ───────────────────────────────────────────────────────

def load_session(year: int, round_number: int, session_type: str = "R") -> Any:
    """Load a FastF1 session with laps only (no telemetry)."""
    logger.info("Loading session year=%d round=%d type=%s", year, round_number, session_type)
    session = fastf1.get_session(year, round_number, session_type)
    session.load(laps=True, telemetry=False, weather=False, messages=False)
    return session


@lru_cache(maxsize=32)
def get_event_schedule(year: int) -> list[dict]:
    """Return the full event schedule for a given season (in-memory cached)."""
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
    types: list[str] = []
    for i in range(1, 6):
        name = row.get(f"Session{i}", None)
        if name and str(name).strip() not in ("", "nan", "None"):
            types.append(str(name))
    return types


# ── Telemetry comparison ───────────────────────────────────────────────────

@lru_cache(maxsize=20)
def get_telemetry_compare(
    year: int,
    race: str,
    session_type: str,
    drivers_key: str,  # sorted comma-separated driver codes — used as cache key
) -> dict:
    """
    Load and compare telemetry for multiple drivers.

    Args:
        year: Championship year
        race: GP name or country (e.g. "Monaco")
        session_type: "R", "Q", "FP1", "FP2", "FP3", "S"
        drivers_key: Sorted comma-separated driver codes (e.g. "HAM,NOR,VER")

    Returns:
        Dict matching TelemetryCompareResponse schema
    """
    driver_codes = [d.strip().upper() for d in drivers_key.split(",")]
    logger.info(
        "Fetching telemetry year=%d race=%s session=%s drivers=%s",
        year, race, session_type, driver_codes,
    )

    # Load session with telemetry
    session = fastf1.get_session(year, race, session_type)
    session.load(laps=True, telemetry=True, weather=False, messages=False)

    # Event metadata
    event = session.event
    track_name = str(event.get("OfficialEventName", race))
    try:
        session_date = str(event["EventDate"].date())
    except Exception:
        session_date = ""

    # Extract raw telemetry per driver
    raw_data: dict[str, dict] = {}
    lap_times_s: dict[str, float] = {}

    for driver in driver_codes:
        try:
            raw, lap_s = _extract_driver_telemetry(session, driver)
            if raw is not None:
                raw_data[driver] = raw
                lap_times_s[driver] = lap_s
        except Exception as exc:
            logger.warning("Skipping driver %s: %s", driver, exc)

    if not raw_data:
        raise ValueError(f"No valid telemetry found for any of: {driver_codes}")

    # Build common distance grid (10 m intervals up to shortest lap)
    max_dist = min(d["max_distance"] for d in raw_data.values())
    grid = np.arange(0.0, max_dist, 10.0)

    # Interpolate all channels to common grid
    interp: dict[str, dict[str, np.ndarray]] = {}
    time_at_grid: dict[str, np.ndarray] = {}

    for driver, raw in raw_data.items():
        ch = _interpolate_to_grid(raw, grid)
        interp[driver] = ch
        time_at_grid[driver] = ch["time_seconds"]

    # Delta vs fastest driver
    deltas, fastest_driver = _calculate_deltas(time_at_grid)

    def fmt_lap(s: float | None) -> str:
        if s is None:
            return "N/A"
        m = int(s // 60)
        sec = s % 60
        return f"{m}:{sec:06.3f}"

    # Build output telemetry dict
    telemetry_out: dict[str, dict] = {}
    for driver in raw_data:
        ch = interp[driver]
        telemetry_out[driver] = {
            "color": DRIVER_COLORS.get(driver, "#FFFFFF"),
            "lap_number": int(raw_data[driver]["lap_number"]),
            "lap_time": fmt_lap(lap_times_s.get(driver)),
            "top_speed": round(float(np.max(ch["speed"])), 1),
            "distance": grid.tolist(),
            "speed": np.round(ch["speed"], 1).tolist(),
            "throttle": np.round(ch["throttle"], 1).tolist(),
            "brake": np.round(ch["brake"], 1).tolist(),
            "gear": ch["gear"].astype(int).tolist(),
            "delta": np.round(deltas[driver], 3).tolist(),
            "x": np.round(ch.get("x", np.array([])), 1).tolist(),
            "y": np.round(ch.get("y", np.array([])), 1).tolist(),
        }

    # Summary & insights
    summary = _generate_summary(list(raw_data.keys()), lap_times_s, fastest_driver, race, session_type)

    sorted_drivers = sorted(
        [(d, t) for d, t in lap_times_s.items() if d in telemetry_out],
        key=lambda x: x[1],
    )
    performance_gaps: dict[str, str] = {}
    if sorted_drivers:
        best = sorted_drivers[0][1]
        for d, t in sorted_drivers:
            performance_gaps[d] = "fastest" if d == fastest_driver else f"+{t - best:.3f}s"

    avg_speeds = [float(np.mean(interp[d]["speed"])) for d in telemetry_out]

    return {
        "metadata": {
            "year": year,
            "race": race,
            "session": session_type,
            "drivers": list(telemetry_out.keys()),
            "track_name": track_name,
            "date": session_date,
        },
        "telemetry": telemetry_out,
        "summary": summary,
        "insights": {
            "fastest_driver": fastest_driver,
            "fastest_time": fmt_lap(lap_times_s.get(fastest_driver)),
            "average_speed": round(float(np.mean(avg_speeds)), 1) if avg_speeds else 0.0,
            "performance_gaps": performance_gaps,
        },
    }


# ── Private helpers ────────────────────────────────────────────────────────

def _extract_driver_telemetry(session: Any, driver: str) -> tuple[dict | None, float]:
    """Return (raw_telemetry_dict, lap_time_seconds) for the driver's fastest lap."""
    laps = session.laps.pick_drivers(driver)
    if laps.empty:
        raise ValueError(f"No laps for driver {driver}")

    fastest = laps.pick_fastest()
    if fastest is None or (hasattr(fastest, "empty") and fastest.empty):
        raise ValueError(f"No fastest lap for driver {driver}")

    lap_time = fastest["LapTime"]
    lap_time_s = float(lap_time.total_seconds()) if pd.notna(lap_time) else 0.0

    tel = fastest.get_telemetry()
    if tel is None or tel.empty:
        raise ValueError(f"No telemetry for driver {driver}")

    tel = tel.dropna(subset=["Distance"])
    if tel.empty:
        raise ValueError(f"Empty telemetry after cleaning for driver {driver}")

    # Brake: handle bool or float
    if "Brake" in tel.columns:
        brake = tel["Brake"].values
        if brake.dtype == bool or brake.dtype == np.bool_:
            brake = brake.astype(float) * 100.0
        else:
            brake = brake.astype(float)
            if brake.max() <= 1.0:
                brake = brake * 100.0
    else:
        brake = np.zeros(len(tel))

    time_s = tel["Time"].dt.total_seconds().values

    lap_number = 0
    if "LapNumber" in fastest.index or hasattr(fastest, "get"):
        ln = fastest.get("LapNumber", 0)
        if pd.notna(ln):
            lap_number = int(ln)

    raw: dict = {
        "distances":    tel["Distance"].values.astype(float),
        "speeds":       tel["Speed"].values.astype(float) if "Speed" in tel.columns else np.zeros(len(tel)),
        "throttle":     tel["Throttle"].values.astype(float) if "Throttle" in tel.columns else np.zeros(len(tel)),
        "brake":        brake,
        "gear":         tel["nGear"].values.astype(float) if "nGear" in tel.columns else np.ones(len(tel)),
        "time_seconds": time_s,
        "x":            tel["X"].values.astype(float) if "X" in tel.columns else np.array([]),
        "y":            tel["Y"].values.astype(float) if "Y" in tel.columns else np.array([]),
        "max_distance": float(tel["Distance"].max()),
        "lap_number":   lap_number,
    }
    return raw, lap_time_s


def _interpolate_to_grid(raw: dict, grid: np.ndarray) -> dict[str, np.ndarray]:
    """Interpolate all telemetry channels onto a uniform distance grid."""
    distances = raw["distances"]

    # Sort by distance and remove duplicates
    sort_idx = np.argsort(distances)
    distances = distances[sort_idx]
    _, uniq = np.unique(distances, return_index=True)
    distances = distances[uniq]

    def interp(values: np.ndarray) -> np.ndarray:
        v = values[sort_idx][uniq]
        clipped = np.clip(grid, distances[0], distances[-1])
        return np.interp(clipped, distances, v)

    result: dict[str, np.ndarray] = {
        "speed":        np.clip(interp(raw["speeds"]), 0, 400),
        "throttle":     np.clip(interp(raw["throttle"]), 0, 100),
        "brake":        np.clip(interp(raw["brake"]), 0, 100),
        "gear":         np.round(np.clip(interp(raw["gear"]), 0, 9)),
        "time_seconds": interp(raw["time_seconds"]),
    }

    # X / Y coordinates (optional)
    if len(raw.get("x", [])) == len(raw["distances"]):
        result["x"] = interp(raw["x"])
        result["y"] = interp(raw["y"])

    return result


def _calculate_deltas(
    time_at_grid: dict[str, np.ndarray],
) -> tuple[dict[str, np.ndarray], str]:
    """Return (delta_dict, fastest_driver_code) where delta = driver_time - fastest_time."""
    total_times = {d: float(t[-1]) for d, t in time_at_grid.items()}
    fastest = min(total_times, key=total_times.get)  # type: ignore[arg-type]
    ref = time_at_grid[fastest]
    deltas = {d: t - ref for d, t in time_at_grid.items()}
    return deltas, fastest


def _generate_summary(
    drivers: list[str],
    lap_times: dict[str, float],
    fastest_driver: str,
    race: str,
    session_type: str,
) -> str:
    """Produce a plain-English summary without AI."""
    session_name = {
        "Q": "qualifying", "R": "the race",
        "FP1": "FP1", "FP2": "FP2", "FP3": "FP3",
        "S": "the sprint race", "SQ": "sprint qualifying",
    }.get(session_type.upper(), session_type)

    sorted_drivers = sorted(
        [(d, t) for d, t in lap_times.items() if d in drivers],
        key=lambda x: x[1],
    )
    if not sorted_drivers:
        return "Telemetry comparison loaded."

    def fmt(s: float) -> str:
        m = int(s // 60)
        sec = s % 60
        return f"{m}:{sec:06.3f}"

    best_time = sorted_drivers[0][1]
    parts = [
        f"{fastest_driver} set the fastest lap in {session_name} at {race} ({fmt(best_time)})"
    ]
    for d, t in sorted_drivers[1:]:
        gap = t - best_time
        parts.append(f"{d} was +{gap:.3f}s behind")

    return ". ".join(parts) + "."
