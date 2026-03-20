from pydantic import BaseModel
from typing import Dict, List, Optional


# ── Session list models ────────────────────────────────────────────────────

class Circuit(BaseModel):
    round: int
    country: str
    circuit_name: str
    location: str
    date: str
    session_types: list[str]


class SessionListResponse(BaseModel):
    season: int
    rounds: list[Circuit]


class ErrorResponse(BaseModel):
    detail: str
    code: Optional[str] = None


# ── Telemetry models ───────────────────────────────────────────────────────

class TireStint(BaseModel):
    stint: int
    compound: Optional[str] = None
    first_lap: int
    last_lap: int
    laps_count: int


class DriverTelemetry(BaseModel):
    color: str
    lap_number: int
    lap_time: Optional[str] = None
    top_speed: Optional[float] = None
    distance: list[float]
    speed: list[float]
    throttle: list[float]
    brake: list[float]
    gear: list[float]
    delta: list[float]
    x: list[float] = []
    y: list[float] = []
    compound: Optional[str] = None
    sector1: Optional[str] = None
    sector2: Optional[str] = None
    sector3: Optional[str] = None
    team_name: str = ""
    tire_stints: list[TireStint] = []


class TelemetryMetadata(BaseModel):
    year: int
    race: str
    session: str
    drivers: list[str]
    track_name: str
    date: str
    air_temp: Optional[float] = None
    track_temp: Optional[float] = None
    humidity: Optional[float] = None
    wind_speed: Optional[float] = None
    rainfall: bool = False


class TelemetryInsights(BaseModel):
    fastest_driver: str
    fastest_time: Optional[str] = None
    average_speed: float
    performance_gaps: dict[str, str]


class TelemetryCompareResponse(BaseModel):
    metadata: TelemetryMetadata
    telemetry: dict[str, DriverTelemetry]
    summary: str
    insights: TelemetryInsights


# ── Race positions models ───────────────────────────────────────────────────

class DriverLap(BaseModel):
    lap: int
    lap_time_s: float
    compound: str = "UNKNOWN"
    stint: int = 1
    in_pit: bool = False
    pit_time_s: Optional[float] = None
    retired: bool = False
    position: Optional[int] = None


class DriverRaceInfo(BaseModel):
    code: str
    number: int
    name: str
    team: str
    color: str
    grid_position: int


class RacePositionsResponse(BaseModel):
    year: int
    race: str
    total_laps: int
    drivers: Dict[str, DriverRaceInfo]
    laps: Dict[str, List[DriverLap]]
    # Dict[str, List[DriverLap]] — key is driver code, value is list of lap records
