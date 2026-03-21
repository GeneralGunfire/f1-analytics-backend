from sqlalchemy import (
    Column, Integer, String, Date, DateTime, Numeric, Float,
    Boolean, ForeignKey, UniqueConstraint, Text
)
from datetime import datetime
from app.database.connection import Base


class Circuit(Base):
    __tablename__ = "circuits"
    id = Column(String(50), primary_key=True)
    name = Column(String(200), nullable=False)
    short_name = Column(String(100), nullable=False)
    country = Column(String(100), nullable=False)
    city = Column(String(100), nullable=False)
    country_code = Column(String(2), nullable=False)
    lap_record_time = Column(String(20))
    lap_record_driver = Column(String(100))
    lap_record_year = Column(Integer)
    length_km = Column(Numeric(5, 3))
    turns = Column(Integer)
    drs_zones = Column(Integer)
    lat = Column(Float)
    lon = Column(Float)
    fastf1_key = Column(String(100), nullable=False)
    image_key = Column(String(100))


class Team(Base):
    __tablename__ = "teams"
    __table_args__ = (UniqueConstraint("id", "year"),)
    pk = Column(Integer, primary_key=True, autoincrement=True)
    id = Column(String(50), nullable=False)
    year = Column(Integer, nullable=False)
    full_name = Column(String(200), nullable=False)
    short_name = Column(String(100), nullable=False)
    car_model = Column(String(50))
    engine = Column(String(100))
    color = Column(String(7), nullable=False)


class Driver(Base):
    __tablename__ = "drivers"
    __table_args__ = (UniqueConstraint("code", "year"),)
    pk = Column(Integer, primary_key=True, autoincrement=True)
    code = Column(String(3), nullable=False)
    year = Column(Integer, nullable=False)
    first_name = Column(String(100), nullable=False)
    last_name = Column(String(100), nullable=False)
    number = Column(Integer)
    team_id = Column(String(50), nullable=False)
    nationality = Column(String(100))
    color = Column(String(7))


class Race(Base):
    __tablename__ = "races"
    __table_args__ = (UniqueConstraint("year", "round"),)
    id = Column(Integer, primary_key=True, autoincrement=True)
    year = Column(Integer, nullable=False)
    round = Column(Integer, nullable=False)
    circuit_id = Column(String(50), ForeignKey("circuits.id"), nullable=False)
    official_name = Column(String(300))
    date = Column(Date, nullable=False)
    fp1_date = Column(Date)
    fp2_date = Column(Date)
    fp3_date = Column(Date)
    qualifying_date = Column(Date)
    sprint_date = Column(Date)
    race_date = Column(Date)
    fastf1_key = Column(String(100), nullable=False)
    is_sprint_weekend = Column(Boolean, default=False)
    is_provisional = Column(Boolean, default=False)


class RaceResult(Base):
    __tablename__ = "race_results"
    __table_args__ = (UniqueConstraint("race_id"),)
    id = Column(Integer, primary_key=True, autoincrement=True)
    race_id = Column(Integer, ForeignKey("races.id"), nullable=False)
    winner_code = Column(String(3))
    p2_code = Column(String(3))
    p3_code = Column(String(3))
    pole_driver_code = Column(String(3))
    pole_time = Column(String(20))
    fastest_lap_driver_code = Column(String(3))
    fastest_lap_time = Column(String(20))
    safety_car_deployments = Column(Integer, default=0)
    total_laps = Column(Integer)


class Weather(Base):
    __tablename__ = "weather"
    __table_args__ = (UniqueConstraint("race_id", "session"),)
    id = Column(Integer, primary_key=True, autoincrement=True)
    race_id = Column(Integer, ForeignKey("races.id"), nullable=False)
    session = Column(String(20), nullable=False)
    air_temp_celsius = Column(Numeric(4, 1))
    track_temp_celsius = Column(Numeric(4, 1))
    humidity_percent = Column(Integer)
    wind_speed_kmh = Column(Numeric(5, 1))
    condition = Column(String(50))


class TyreStrategy(Base):
    __tablename__ = "tyre_strategy"
    __table_args__ = (
        UniqueConstraint("race_id", "driver_code", "stint_number"),
    )
    id = Column(Integer, primary_key=True, autoincrement=True)
    race_id = Column(Integer, ForeignKey("races.id"), nullable=False)
    driver_code = Column(String(3), nullable=False)
    stint_number = Column(Integer, nullable=False)
    compound = Column(String(20), nullable=False)
    laps = Column(Integer, nullable=False)


class TelemetrySession(Base):
    __tablename__ = "telemetry_sessions"
    __table_args__ = (UniqueConstraint("race_id", "session_type"),)
    id = Column(Integer, primary_key=True, autoincrement=True)
    race_id = Column(Integer, ForeignKey("races.id"), nullable=False)
    session_type = Column(String(10), nullable=False)
    # Q = Qualifying, R = Race, FP1/FP2/FP3 = Practice
    distance_points = Column(Integer, default=500)
    computed_at = Column(DateTime, default=datetime.utcnow)
    status = Column(String(20), default="complete")
    # complete, partial, failed


class DriverTelemetry(Base):
    __tablename__ = "driver_telemetry"
    __table_args__ = (
        UniqueConstraint("session_id", "driver_code"),
    )
    id = Column(Integer, primary_key=True, autoincrement=True)
    session_id = Column(
        Integer, ForeignKey("telemetry_sessions.id"), nullable=False
    )
    driver_code = Column(String(3), nullable=False)
    fastest_lap_time = Column(String(20))
    fastest_lap_seconds = Column(Numeric(8, 3))
    top_speed_kmh = Column(Numeric(6, 1))
    avg_speed_kmh = Column(Numeric(6, 1))
    throttle_avg_pct = Column(Numeric(5, 1))
    brake_events = Column(Integer)
    # Telemetry arrays stored as JSON text
    # Format: [val1, val2, ...] — 500 points each
    speed_trace = Column(Text)
    throttle_trace = Column(Text)
    brake_trace = Column(Text)
    gear_trace = Column(Text)
    distance_trace = Column(Text)
    delta_trace = Column(Text)
    # Delta vs fastest driver in session, 0.0 for fastest driver
