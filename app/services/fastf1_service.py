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

    # Load session with telemetry and weather
    session = fastf1.get_session(year, race, session_type)
    session.load(laps=True, telemetry=True, weather=True, messages=False)

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

    # Delta vs fastest driver (grid-interpolated; used only for delta curves)
    deltas, _fastest_interp = _calculate_deltas(time_at_grid)

    # Determine fastest_driver from actual lap_times_s (source of truth)
    fastest_driver = min(
        (d for d in lap_times_s if d in raw_data),
        key=lambda d: lap_times_s[d],
    )

    def fmt_lap(s: float | None) -> str:
        if s is None:
            return "N/A"
        m = int(s // 60)
        sec = s % 60
        return f"{m}:{sec:06.3f}"

    # Extract weather averages
    air_temp = track_temp = humidity = wind_speed = None
    rainfall = False
    try:
        weather = session.weather_data
        if weather is not None and not weather.empty:
            if "AirTemp" in weather.columns:
                air_temp = round(float(weather["AirTemp"].mean()), 1)
            if "TrackTemp" in weather.columns:
                track_temp = round(float(weather["TrackTemp"].mean()), 1)
            if "Humidity" in weather.columns:
                humidity = round(float(weather["Humidity"].mean()), 1)
            if "WindSpeed" in weather.columns:
                wind_speed = round(float(weather["WindSpeed"].mean()), 1)
            if "Rainfall" in weather.columns:
                rainfall = bool(weather["Rainfall"].any())
    except Exception as exc:
        logger.warning("Weather extraction failed: %s", exc)

    # Extract tire stints per driver (full race strategy)
    tire_stints: dict[str, list] = {}
    try:
        for driver in driver_codes:
            driver_laps = session.laps.pick_drivers(driver)
            stints: list[dict] = []
            if not driver_laps.empty and "Stint" in driver_laps.columns:
                for stint_num, stint_laps in driver_laps.groupby("Stint"):
                    compound = None
                    if "Compound" in stint_laps.columns:
                        vals = [
                            v for v in stint_laps["Compound"].tolist()
                            if str(v).strip() not in ("nan", "None", "", "UNKNOWN")
                        ]
                        compound = str(vals[0]).upper() if vals else None
                    stints.append({
                        "stint": int(stint_num),
                        "compound": compound,
                        "first_lap": int(stint_laps["LapNumber"].min()),
                        "last_lap": int(stint_laps["LapNumber"].max()),
                        "laps_count": len(stint_laps),
                    })
            tire_stints[driver] = stints
    except Exception as exc:
        logger.warning("Tire stints extraction failed: %s", exc)

    # Build output telemetry dict
    telemetry_out: dict[str, dict] = {}
    for driver in raw_data:
        ch = interp[driver]

        # team_name from session results
        team_name = ""
        try:
            if hasattr(session, "results") and session.results is not None and len(session.results) > 0:
                if driver in session.results["Abbreviation"].values:
                    row = session.results[session.results["Abbreviation"] == driver].iloc[0]
                    team_name = str(row.get("TeamName", ""))
        except Exception:
            pass

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
            "compound": raw_data[driver].get("compound"),
            "sector1": raw_data[driver].get("sector1"),
            "sector2": raw_data[driver].get("sector2"),
            "sector3": raw_data[driver].get("sector3"),
            "team_name": team_name,
            "tire_stints": tire_stints.get(driver, []),
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
            "air_temp": air_temp,
            "track_temp": track_temp,
            "humidity": humidity,
            "wind_speed": wind_speed,
            "rainfall": rainfall,
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

def _fmt_sector(td) -> str | None:
    """Format a timedelta sector time as a seconds string, e.g. '27.543'."""
    try:
        if not pd.notna(td):
            return None
        s = td.total_seconds()
        return f"{s:.3f}" if s > 0 else None
    except Exception:
        return None


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

    # Compound — normalise invalid values to None
    compound: str | None = None
    try:
        raw_compound = fastest.get("Compound", None)
        c_str = str(raw_compound) if raw_compound is not None else ""
        if c_str not in ("nan", "None", "", "UNKNOWN"):
            compound = c_str
    except Exception:
        pass

    # Sector times
    sector1 = _fmt_sector(fastest.get("Sector1Time"))
    sector2 = _fmt_sector(fastest.get("Sector2Time"))
    sector3 = _fmt_sector(fastest.get("Sector3Time"))

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
        "compound":     compound,
        "sector1":      sector1,
        "sector2":      sector2,
        "sector3":      sector3,
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


@lru_cache(maxsize=20)
def get_all_laps(year: int, race: str, session_type: str) -> list[dict]:
    """
    Return all valid personal-best or race laps for all drivers in a session.

    Loads laps only (no telemetry) for speed. Cached by (year, race, session_type).
    """
    logger.info("Loading all laps year=%d race=%s session=%s", year, race, session_type)
    session = fastf1.get_session(year, race, session_type)
    session.load(laps=True, telemetry=False, weather=False, messages=False)

    rows: list[dict] = []
    for _, lap in session.laps.iterrows():
        lap_time = lap.get("LapTime")
        if not pd.notna(lap_time):
            continue
        lap_time_s = float(lap_time.total_seconds())
        if lap_time_s <= 0:
            continue

        compound = None
        if "Compound" in lap.index and pd.notna(lap.get("Compound")):
            compound = str(lap["Compound"])

        stint = None
        if "Stint" in lap.index and pd.notna(lap.get("Stint")):
            stint = int(lap["Stint"])

        is_pb = False
        if "IsPersonalBest" in lap.index and pd.notna(lap.get("IsPersonalBest")):
            is_pb = bool(lap["IsPersonalBest"])

        rows.append({
            "driver":          str(lap["Driver"]),
            "lap_number":      int(lap["LapNumber"]),
            "lap_time_s":      round(lap_time_s, 3),
            "compound":        compound,
            "stint":           stint,
            "is_personal_best": is_pb,
        })

    return rows


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


# ── Race positions ──────────────────────────────────────────────────────────

@lru_cache(maxsize=10)
def get_race_positions(year: int, race: str) -> dict:
    """
    Load lap-by-lap race data for all drivers.
    Returns driver info and all lap records for race replay visualization.
    """
    logger.info("Loading race positions year=%d race=%s", year, race)

    session = fastf1.get_session(year, race, "R")
    session.load(laps=True, telemetry=False, weather=False, messages=False)

    laps_df = session.laps

    # Get race results for grid positions and driver info
    results = (
        session.results
        if hasattr(session, "results") and session.results is not None
        else pd.DataFrame()
    )

    drivers_info: dict[str, dict] = {}
    laps_data: dict[str, list] = {}

    all_drivers = laps_df["Driver"].unique() if len(laps_df) > 0 else []

    for driver_code in all_drivers:
        driver_laps = laps_df[laps_df["Driver"] == driver_code].copy()
        driver_laps = driver_laps.sort_values("LapNumber")

        # Get driver info from results or fall back to safe defaults
        try:
            if len(results) > 0 and driver_code in results["Abbreviation"].values:
                result_row = results[results["Abbreviation"] == driver_code].iloc[0]
                grid_raw = result_row.get("GridPosition", None)
                grid_pos = int(grid_raw) if pd.notna(grid_raw) else 20
                full_name = str(result_row.get("FullName", driver_code))
                team_name = str(result_row.get("TeamName", "Unknown"))
            else:
                grid_pos = 20
                full_name = driver_code
                team_name = "Unknown"
        except Exception:
            grid_pos = 20
            full_name = driver_code
            team_name = "Unknown"

        color = DRIVER_COLORS.get(driver_code, "#888888")

        try:
            driver_number = int(session.get_driver(driver_code)["DriverNumber"])
        except Exception:
            driver_number = 0

        drivers_info[driver_code] = {
            "code": driver_code,
            "number": driver_number,
            "name": full_name,
            "team": team_name,
            "color": color,
            "grid_position": grid_pos,
        }

        laps_list: list[dict] = []
        max_lap = int(driver_laps["LapNumber"].max()) if len(driver_laps) > 0 else 0

        for _, lap_row in driver_laps.iterrows():
            try:
                raw_lap_time = lap_row["LapTime"]
                lap_time_s = (
                    raw_lap_time.total_seconds() if pd.notna(raw_lap_time) else None
                )
                if lap_time_s is None or lap_time_s <= 0:
                    continue

                compound = (
                    str(lap_row.get("Compound", "UNKNOWN"))
                    if pd.notna(lap_row.get("Compound"))
                    else "UNKNOWN"
                )
                stint = (
                    int(lap_row.get("Stint", 1))
                    if pd.notna(lap_row.get("Stint"))
                    else 1
                )
                lap_num = int(lap_row["LapNumber"])

                # Detect pit stop from PitInTime / PitOutTime
                pit_time: float | None = None
                in_pit = False
                try:
                    pit_in = lap_row.get("PitInTime")
                    pit_out = lap_row.get("PitOutTime")
                    if pd.notna(pit_in) and pd.notna(pit_out):
                        in_pit = True
                        diff = pit_out - pit_in
                        if hasattr(diff, "total_seconds"):
                            pit_time = diff.total_seconds()
                except Exception:
                    pass

                # Retirement heuristic: last lap significantly shorter than race distance
                is_last_lap = lap_num == max_lap
                retired = False
                try:
                    if is_last_lap and lap_time_s > 200:
                        # Only flag as retired if driver clearly didn't complete the lap
                        total_laps_in_race = int(laps_df["LapNumber"].max())
                        if lap_num < total_laps_in_race:
                            retired = True
                except Exception:
                    pass

                laps_list.append({
                    "lap": lap_num,
                    "lap_time_s": round(lap_time_s, 3),
                    "compound": compound,
                    "stint": stint,
                    "in_pit": in_pit,
                    "pit_time_s": round(pit_time, 1) if pit_time is not None else None,
                    "retired": retired,
                    "position": None,
                })
            except Exception:
                continue

        if laps_list:
            laps_data[driver_code] = laps_list

    total_laps = int(laps_df["LapNumber"].max()) if len(laps_df) > 0 else 0

    return {
        "year": year,
        "race": race,
        "total_laps": total_laps,
        "drivers": drivers_info,
        "laps": laps_data,
    }
