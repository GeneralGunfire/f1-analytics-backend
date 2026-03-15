from pydantic import BaseModel
from typing import Optional


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
