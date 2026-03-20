from sqlalchemy import (
    Column, Integer, String, Date, Numeric,
    Boolean, ForeignKey, UniqueConstraint, Text
)
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
