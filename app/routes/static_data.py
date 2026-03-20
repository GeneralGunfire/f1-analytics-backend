from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_
from app.database.connection import get_db
from app.database import models
from datetime import date

router = APIRouter(prefix="/api/static", tags=["static"])


@router.get("/drivers")
async def get_drivers(year: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(models.Driver).where(models.Driver.year == year)
    )
    drivers = result.scalars().all()
    if not drivers:
        raise HTTPException(404, f"No drivers for {year}")
    return {
        "year": year,
        "drivers": [
            {
                "code": d.code,
                "firstName": d.first_name,
                "lastName": d.last_name,
                "number": d.number,
                "team": d.team_id,
                "color": d.color,
                "nationality": d.nationality,
            }
            for d in drivers
        ],
    }


@router.get("/teams")
async def get_teams(year: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(models.Team).where(models.Team.year == year)
    )
    teams = result.scalars().all()
    if not teams:
        raise HTTPException(404, f"No teams for {year}")
    return {
        "year": year,
        "teams": [
            {
                "id": t.id,
                "fullName": t.full_name,
                "shortName": t.short_name,
                "carModel": t.car_model,
                "engine": t.engine,
                "color": t.color,
            }
            for t in teams
        ],
    }


@router.get("/races")
async def get_races(year: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(models.Race, models.Circuit)
        .join(models.Circuit, models.Race.circuit_id == models.Circuit.id)
        .where(models.Race.year == year)
        .order_by(models.Race.round)
    )
    rows = result.all()
    if not rows:
        raise HTTPException(404, f"No races for {year}")

    today = date.today()
    races = []
    for race, circuit in rows:
        races.append(
            {
                "round": race.round,
                "circuitId": race.circuit_id,
                "name": race.official_name,
                "shortName": circuit.short_name,
                "country": circuit.country,
                "countryCode": circuit.country_code,
                "date": race.date.isoformat(),
                "fastf1Key": race.fastf1_key,
                "imageKey": circuit.image_key,
                "completed": race.date <= today,
                "isSprintWeekend": race.is_sprint_weekend,
                "isProvisional": race.is_provisional,
                "lengthKm": float(circuit.length_km) if circuit.length_km else None,
                "turns": circuit.turns,
            }
        )
    return {"year": year, "races": races}


@router.get("/race-result")
async def get_race_result(
    year: int, circuit: str, db: AsyncSession = Depends(get_db)
):
    race_result = await db.execute(
        select(models.Race).where(
            and_(models.Race.year == year, models.Race.circuit_id == circuit)
        )
    )
    race = race_result.scalar_one_or_none()
    if not race:
        raise HTTPException(404, "Race not found")

    rr_result = await db.execute(
        select(models.RaceResult).where(models.RaceResult.race_id == race.id)
    )
    rr = rr_result.scalar_one_or_none()
    if not rr:
        return {"year": year, "circuit": circuit, "result": None}

    return {
        "year": year,
        "circuit": circuit,
        "result": {
            "winner": rr.winner_code,
            "podium": [rr.winner_code, rr.p2_code, rr.p3_code],
            "pole": {"driver": rr.pole_driver_code, "time": rr.pole_time},
            "fastestLap": {
                "driver": rr.fastest_lap_driver_code,
                "time": rr.fastest_lap_time,
            },
            "totalLaps": rr.total_laps,
            "safetyCarDeployments": rr.safety_car_deployments,
        },
    }


@router.get("/weather")
async def get_weather(
    year: int,
    circuit: str,
    session: str = "Race",
    db: AsyncSession = Depends(get_db),
):
    race_result = await db.execute(
        select(models.Race).where(
            and_(models.Race.year == year, models.Race.circuit_id == circuit)
        )
    )
    race = race_result.scalar_one_or_none()
    if not race:
        raise HTTPException(404, "Race not found")

    w_result = await db.execute(
        select(models.Weather).where(
            and_(
                models.Weather.race_id == race.id,
                models.Weather.session == session,
            )
        )
    )
    w = w_result.scalar_one_or_none()
    if not w:
        return {"year": year, "circuit": circuit, "session": session, "weather": None}

    return {
        "year": year,
        "circuit": circuit,
        "session": session,
        "weather": {
            "airTempCelsius": float(w.air_temp_celsius) if w.air_temp_celsius else None,
            "trackTempCelsius": float(w.track_temp_celsius) if w.track_temp_celsius else None,
            "humidityPercent": w.humidity_percent,
            "windSpeedKmh": float(w.wind_speed_kmh) if w.wind_speed_kmh else None,
            "condition": w.condition,
        },
    }


@router.get("/tyre-strategy")
async def get_tyre_strategy(
    year: int, circuit: str, db: AsyncSession = Depends(get_db)
):
    race_result = await db.execute(
        select(models.Race).where(
            and_(models.Race.year == year, models.Race.circuit_id == circuit)
        )
    )
    race = race_result.scalar_one_or_none()
    if not race:
        raise HTTPException(404, "Race not found")

    ts_result = await db.execute(
        select(models.TyreStrategy)
        .where(models.TyreStrategy.race_id == race.id)
        .order_by(
            models.TyreStrategy.driver_code, models.TyreStrategy.stint_number
        )
    )
    stints = ts_result.scalars().all()

    strategies = {}
    for s in stints:
        if s.driver_code not in strategies:
            strategies[s.driver_code] = []
        strategies[s.driver_code].append(
            {"stint": s.stint_number, "compound": s.compound, "laps": s.laps}
        )

    return {"year": year, "circuit": circuit, "strategies": strategies}


@router.get("/circuits")
async def get_all_circuits(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(models.Circuit))
    circuits = result.scalars().all()
    return {
        "circuits": [
            {
                "id": c.id,
                "name": c.name,
                "shortName": c.short_name,
                "country": c.country,
                "countryCode": c.country_code,
                "lengthKm": float(c.length_km) if c.length_km else None,
                "turns": c.turns,
                "drsZones": c.drs_zones,
                "lapRecord": {
                    "time": c.lap_record_time,
                    "driver": c.lap_record_driver,
                    "year": c.lap_record_year,
                },
                "fastf1Key": c.fastf1_key,
                "imageKey": c.image_key,
            }
            for c in circuits
        ]
    }
