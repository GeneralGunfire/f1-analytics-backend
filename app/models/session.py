from pydantic import BaseModel
from typing import Optional


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


class TelemetryMetadata(BaseModel):
    year: int
    race: str
    session: str
    drivers: list[str]
    track_name: str
    date: str


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
