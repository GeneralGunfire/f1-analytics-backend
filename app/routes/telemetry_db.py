from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from app.database.connection import get_db
from app.database.models import Race, Circuit, TelemetrySession, DriverTelemetry, Weather, Driver
import json
from datetime import date

router = APIRouter(prefix="/api/telemetry", tags=["telemetry"])

# Driver colours — kept in sync with fastf1_service.py
_DRIVER_COLORS: dict[str, str] = {
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
    "LAW": "#3671C6", "BEA": "#B6BABD",
    "ANT": "#27F4D2", "DOO": "#0090FF",
    "HAD": "#356CAC", "BOR": "#00CF46",
}

_SESSION_TO_WEATHER_NAME: dict[str, str] = {
    "Q": "Qualifying", "R": "Race",
    "FP1": "Practice 1", "FP2": "Practice 2", "FP3": "Practice 3",
    "S": "Sprint",
}


@router.get("/compare")
async def compare_telemetry(
    year: int,
    race: str = Query(..., description="FastF1 race key e.g. Monaco"),
    session: str = Query(..., description="Q, R, FP1, FP2, FP3"),
    drivers: str = Query(..., description="Comma-separated driver codes, max 5"),
    db: AsyncSession = Depends(get_db)
):
    driver_list = [d.strip().upper() for d in drivers.split(",")]

    if len(driver_list) < 1 or len(driver_list) > 5:
        raise HTTPException(400, "Provide 1-5 driver codes")

    valid_sessions = ["Q", "R", "FP1", "FP2", "FP3", "S"]
    if session not in valid_sessions:
        raise HTTPException(400, f"Session must be one of: {valid_sessions}")

    # Find the race in database (join with Circuit for track name)
    race_result = await db.execute(
        select(Race, Circuit)
        .join(Circuit, Race.circuit_id == Circuit.id)
        .where(and_(Race.year == year, Race.fastf1_key == race))
    )
    row = race_result.first()
    if not row:
        raise HTTPException(404, f"Race not found: {year} {race}")
    race_row, circuit_row = row

    if race_row.date > date.today():
        raise HTTPException(400, "Race has not happened yet")

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
                "message": f"Telemetry for {year} {race} {session} has not been computed yet.",
                "race": race, "year": year, "session": session
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

    # Fetch driver telemetry rows
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
        raise HTTPException(404, f"No telemetry found for drivers: {driver_list}")

    # Fetch driver colors from DB for this year (override hardcoded where available)
    driver_colors: dict[str, str] = dict(_DRIVER_COLORS)
    try:
        dr_result = await db.execute(
            select(Driver).where(
                and_(Driver.year == year, Driver.code.in_(driver_list))
            )
        )
        for drv in dr_result.scalars().all():
            if drv.color:
                driver_colors[drv.code] = drv.color
    except Exception:
        pass

    # Ensure distinct colors for same-team pairs
    seen_colors: set[str] = set()
    fallback_palette = [
        "#00D2BE", "#FF8000", "#0600EF", "#FFB800", "#9B59B6",
        "#00A0DD", "#FF69B4", "#7A7A7A", "#39B54A", "#E67E22",
    ]
    fb_idx = 0
    final_colors: dict[str, str] = {}
    for dt in sorted(driver_telemetry_rows, key=lambda x: float(x.fastest_lap_seconds or 999)):
        c = driver_colors.get(dt.driver_code, "#FFFFFF")
        if c not in seen_colors:
            seen_colors.add(c)
            final_colors[dt.driver_code] = c
        else:
            while fb_idx < len(fallback_palette) and fallback_palette[fb_idx] in seen_colors:
                fb_idx += 1
            alt = fallback_palette[fb_idx] if fb_idx < len(fallback_palette) else "#FFFFFF"
            if fb_idx < len(fallback_palette):
                fb_idx += 1
            seen_colors.add(alt)
            final_colors[dt.driver_code] = alt

    # Fastest driver
    fastest_row = min(driver_telemetry_rows, key=lambda x: float(x.fastest_lap_seconds or 999))
    fastest_driver = fastest_row.driver_code
    fastest_time_s = float(fastest_row.fastest_lap_seconds or 0)

    def fmt_lap(s: float) -> str:
        m = int(s // 60)
        sec = s % 60
        return f"{m}:{sec:06.3f}"

    # Weather lookup
    air_temp = track_temp = humidity = wind_speed = None
    rainfall = False
    try:
        weather_session_name = _SESSION_TO_WEATHER_NAME.get(session, session)
        w_result = await db.execute(
            select(Weather).where(
                and_(Weather.race_id == race_row.id, Weather.session == weather_session_name)
            )
        )
        w = w_result.scalar_one_or_none()
        if w:
            air_temp   = float(w.air_temp_celsius)   if w.air_temp_celsius   else None
            track_temp = float(w.track_temp_celsius) if w.track_temp_celsius else None
            humidity   = float(w.humidity_percent)   if w.humidity_percent   else None
            wind_speed = float(w.wind_speed_kmh)     if w.wind_speed_kmh     else None
            rainfall   = w.condition in ("Wet", "Rain") if w.condition else False
    except Exception:
        pass

    # Build telemetry dict in the format CompareResults expects
    telemetry_out: dict[str, dict] = {}
    performance_gaps: dict[str, str] = {}
    avg_speeds: list[float] = []

    for dt in driver_telemetry_rows:
        code = dt.driver_code
        lap_s = float(dt.fastest_lap_seconds or 0)
        performance_gaps[code] = "fastest" if code == fastest_driver else f"+{lap_s - fastest_time_s:.3f}s"
        avg_speed = float(dt.avg_speed_kmh or 0)
        avg_speeds.append(avg_speed)

        telemetry_out[code] = {
            "color":      final_colors.get(code, "#FFFFFF"),
            "lap_number": 0,
            "lap_time":   dt.fastest_lap_time,
            "top_speed":  float(dt.top_speed_kmh) if dt.top_speed_kmh else None,
            "distance":   json.loads(dt.distance_trace) if dt.distance_trace else [],
            "speed":      json.loads(dt.speed_trace)    if dt.speed_trace    else [],
            "throttle":   json.loads(dt.throttle_trace) if dt.throttle_trace else [],
            "brake":      json.loads(dt.brake_trace)    if dt.brake_trace    else [],
            "gear":       json.loads(dt.gear_trace)     if dt.gear_trace     else [],
            "delta":      json.loads(dt.delta_trace)    if dt.delta_trace    else [],
            "x":          [],
            "y":          [],
            "compound":   None,
            "sector1":    None,
            "sector2":    None,
            "sector3":    None,
            "team_name":  "",
            "tire_stints": [],
        }

    track_name = circuit_row.name if circuit_row else race
    race_date  = race_row.date.isoformat() if race_row.date else ""
    overall_avg = round(sum(avg_speeds) / len(avg_speeds), 1) if avg_speeds else 0.0

    return {
        "metadata": {
            "year":       year,
            "race":       race,
            "session":    session,
            "drivers":    list(telemetry_out.keys()),
            "track_name": track_name,
            "date":       race_date,
            "air_temp":   air_temp,
            "track_temp": track_temp,
            "humidity":   humidity,
            "wind_speed": wind_speed,
            "rainfall":   rainfall,
        },
        "telemetry": telemetry_out,
        "summary":   f"Fastest lap telemetry — {race} {year} {session}",
        "insights": {
            "fastest_driver":   fastest_driver,
            "fastest_time":     fmt_lap(fastest_time_s),
            "average_speed":    overall_avg,
            "performance_gaps": performance_gaps,
        },
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
            and_(Race.year == year, TelemetrySession.status == "complete")
        ).order_by(Race.round)
    )
    rows = result.all()

    return {
        "year": year,
        "available": [
            {
                "circuitId":   race.circuit_id,
                "fastf1Key":   race.fastf1_key,
                "round":       race.round,
                "session":     ts.session_type,
                "computedAt":  ts.computed_at.isoformat() if ts.computed_at else None
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
        select(Race).where(and_(Race.year == year, Race.fastf1_key == race))
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
        select(
            DriverTelemetry.driver_code,
            DriverTelemetry.fastest_lap_time,
            DriverTelemetry.fastest_lap_seconds
        ).where(
            DriverTelemetry.session_id == tel_session.id
        ).order_by(DriverTelemetry.fastest_lap_seconds)
    )
    rows = dt_result.all()

    return {
        "year":      year,
        "race":      race,
        "session":   session,
        "available": True,
        "drivers": [
            {
                "code":             r.driver_code,
                "fastestLapTime":   r.fastest_lap_time,
                "fastestLapSeconds": float(r.fastest_lap_seconds)
            } for r in rows
        ]
    }
