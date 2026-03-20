"""
F1 Analytics Seed Script
Seeds Supabase database with F1 data for 2022-2026.
Run: python -m app.database.seed
"""

import asyncio
import logging
import os
import time
from datetime import date, datetime
from decimal import Decimal

import httpx
from dotenv import load_dotenv
from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.database.connection import AsyncSessionLocal, engine, test_connection
from app.database import models  # noqa: F401
from app.database.connection import Base

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

JOLPICA_BASE = "https://api.jolpi.ca/ergast/f1"
OPENF1_BASE = "https://api.openf1.org/v1"
SLEEP_BETWEEN_CALLS = 0.5
RETRY_ON_429_WAIT = 65  # seconds to wait when rate limited

# ===========================================================================
# CIRCUITS
# ===========================================================================

CIRCUITS_DATA = [
    {"id": "bahrain", "name": "Bahrain International Circuit", "short_name": "Bahrain",
     "country": "Bahrain", "city": "Sakhir", "country_code": "BH",
     "lap_record_time": "1:31.447", "lap_record_driver": "Pedro de la Rosa", "lap_record_year": 2005,
     "length_km": 5.412, "turns": 15, "drs_zones": 3, "fastf1_key": "Bahrain", "image_key": "bahrain"},
    {"id": "saudi-arabia", "name": "Jeddah Corniche Circuit", "short_name": "Saudi Arabia",
     "country": "Saudi Arabia", "city": "Jeddah", "country_code": "SA",
     "lap_record_time": "1:27.511", "lap_record_driver": "Lewis Hamilton", "lap_record_year": 2021,
     "length_km": 6.174, "turns": 27, "drs_zones": 3, "fastf1_key": "Saudi Arabia", "image_key": "saudi-arabia"},
    {"id": "australia", "name": "Albert Park Circuit", "short_name": "Australia",
     "country": "Australia", "city": "Melbourne", "country_code": "AU",
     "lap_record_time": "1:19.813", "lap_record_driver": "Charles Leclerc", "lap_record_year": 2022,
     "length_km": 5.278, "turns": 16, "drs_zones": 4, "fastf1_key": "Australia", "image_key": "australia"},
    {"id": "japan", "name": "Suzuka International Racing Course", "short_name": "Japan",
     "country": "Japan", "city": "Suzuka", "country_code": "JP",
     "lap_record_time": "1:30.983", "lap_record_driver": "Lewis Hamilton", "lap_record_year": 2019,
     "length_km": 5.807, "turns": 18, "drs_zones": 1, "fastf1_key": "Japan", "image_key": "japan"},
    {"id": "china", "name": "Shanghai International Circuit", "short_name": "China",
     "country": "China", "city": "Shanghai", "country_code": "CN",
     "lap_record_time": "1:32.238", "lap_record_driver": "Michael Schumacher", "lap_record_year": 2004,
     "length_km": 5.451, "turns": 16, "drs_zones": 2, "fastf1_key": "China", "image_key": "china"},
    {"id": "miami", "name": "Miami International Autodrome", "short_name": "Miami",
     "country": "United States", "city": "Miami Gardens", "country_code": "US",
     "lap_record_time": "1:29.708", "lap_record_driver": "Max Verstappen", "lap_record_year": 2023,
     "length_km": 5.412, "turns": 19, "drs_zones": 3, "fastf1_key": "Miami", "image_key": "miami"},
    {"id": "imola", "name": "Autodromo Enzo e Dino Ferrari", "short_name": "Imola",
     "country": "Italy", "city": "Imola", "country_code": "IT",
     "lap_record_time": "1:15.484", "lap_record_driver": "Rubens Barrichello", "lap_record_year": 2004,
     "length_km": 4.909, "turns": 19, "drs_zones": 2, "fastf1_key": "Emilia Romagna", "image_key": "italy"},
    {"id": "monaco", "name": "Circuit de Monaco", "short_name": "Monaco",
     "country": "Monaco", "city": "Monte Carlo", "country_code": "MC",
     "lap_record_time": "1:12.909", "lap_record_driver": "Rubens Barrichello", "lap_record_year": 2004,
     "length_km": 3.337, "turns": 19, "drs_zones": 1, "fastf1_key": "Monaco", "image_key": "monoco"},
    {"id": "spain", "name": "Circuit de Barcelona-Catalunya", "short_name": "Spain",
     "country": "Spain", "city": "Barcelona", "country_code": "ES",
     "lap_record_time": "1:16.330", "lap_record_driver": "Max Verstappen", "lap_record_year": 2021,
     "length_km": 4.657, "turns": 16, "drs_zones": 2, "fastf1_key": "Spain", "image_key": "spain"},
    {"id": "canada", "name": "Circuit Gilles Villeneuve", "short_name": "Canada",
     "country": "Canada", "city": "Montreal", "country_code": "CA",
     "lap_record_time": "1:13.078", "lap_record_driver": "Valtteri Bottas", "lap_record_year": 2019,
     "length_km": 4.361, "turns": 14, "drs_zones": 2, "fastf1_key": "Canada", "image_key": "canada"},
    {"id": "austria", "name": "Red Bull Ring", "short_name": "Austria",
     "country": "Austria", "city": "Spielberg", "country_code": "AT",
     "lap_record_time": "1:05.619", "lap_record_driver": "Carlos Sainz", "lap_record_year": 2020,
     "length_km": 4.318, "turns": 10, "drs_zones": 3, "fastf1_key": "Austria", "image_key": "austria"},
    {"id": "great-britain", "name": "Silverstone Circuit", "short_name": "Great Britain",
     "country": "United Kingdom", "city": "Silverstone", "country_code": "GB",
     "lap_record_time": "1:27.097", "lap_record_driver": "Max Verstappen", "lap_record_year": 2020,
     "length_km": 5.891, "turns": 18, "drs_zones": 2, "fastf1_key": "Great Britain", "image_key": "britain"},
    {"id": "hungary", "name": "Hungaroring", "short_name": "Hungary",
     "country": "Hungary", "city": "Budapest", "country_code": "HU",
     "lap_record_time": "1:16.627", "lap_record_driver": "Lewis Hamilton", "lap_record_year": 2020,
     "length_km": 4.381, "turns": 14, "drs_zones": 1, "fastf1_key": "Hungary", "image_key": "hungary"},
    {"id": "belgium", "name": "Circuit de Spa-Francorchamps", "short_name": "Belgium",
     "country": "Belgium", "city": "Spa", "country_code": "BE",
     "lap_record_time": "1:46.286", "lap_record_driver": "Valtteri Bottas", "lap_record_year": 2018,
     "length_km": 7.004, "turns": 19, "drs_zones": 2, "fastf1_key": "Belgium", "image_key": "belgium"},
    {"id": "netherlands", "name": "Circuit Zandvoort", "short_name": "Netherlands",
     "country": "Netherlands", "city": "Zandvoort", "country_code": "NL",
     "lap_record_time": "1:11.097", "lap_record_driver": "Lewis Hamilton", "lap_record_year": 2021,
     "length_km": 4.259, "turns": 14, "drs_zones": 2, "fastf1_key": "Netherlands", "image_key": "netherlands"},
    {"id": "italy", "name": "Autodromo Nazionale Monza", "short_name": "Italy",
     "country": "Italy", "city": "Monza", "country_code": "IT",
     "lap_record_time": "1:21.046", "lap_record_driver": "Rubens Barrichello", "lap_record_year": 2004,
     "length_km": 5.793, "turns": 11, "drs_zones": 2, "fastf1_key": "Italy", "image_key": "italy"},
    {"id": "singapore", "name": "Marina Bay Street Circuit", "short_name": "Singapore",
     "country": "Singapore", "city": "Singapore", "country_code": "SG",
     "lap_record_time": "1:35.867", "lap_record_driver": "Kevin Magnussen", "lap_record_year": 2018,
     "length_km": 4.940, "turns": 19, "drs_zones": 3, "fastf1_key": "Singapore", "image_key": "singapore"},
    {"id": "azerbaijan", "name": "Baku City Circuit", "short_name": "Azerbaijan",
     "country": "Azerbaijan", "city": "Baku", "country_code": "AZ",
     "lap_record_time": "1:43.009", "lap_record_driver": "Charles Leclerc", "lap_record_year": 2019,
     "length_km": 6.003, "turns": 20, "drs_zones": 2, "fastf1_key": "Azerbaijan", "image_key": "azerbaijan"},
    {"id": "usa", "name": "Circuit of the Americas", "short_name": "United States",
     "country": "United States", "city": "Austin", "country_code": "US",
     "lap_record_time": "1:36.169", "lap_record_driver": "Charles Leclerc", "lap_record_year": 2019,
     "length_km": 5.513, "turns": 20, "drs_zones": 2, "fastf1_key": "United States", "image_key": "usa"},
    {"id": "mexico", "name": "Autodromo Hermanos Rodriguez", "short_name": "Mexico City",
     "country": "Mexico", "city": "Mexico City", "country_code": "MX",
     "lap_record_time": "1:17.774", "lap_record_driver": "Valtteri Bottas", "lap_record_year": 2021,
     "length_km": 4.304, "turns": 17, "drs_zones": 3, "fastf1_key": "Mexico City", "image_key": "mexico"},
    {"id": "brazil", "name": "Autodromo Jose Carlos Pace", "short_name": "Brazil",
     "country": "Brazil", "city": "Sao Paulo", "country_code": "BR",
     "lap_record_time": "1:10.540", "lap_record_driver": "Valtteri Bottas", "lap_record_year": 2018,
     "length_km": 4.309, "turns": 15, "drs_zones": 2, "fastf1_key": "São Paulo", "image_key": "brazil"},
    {"id": "las-vegas", "name": "Las Vegas Strip Circuit", "short_name": "Las Vegas",
     "country": "United States", "city": "Las Vegas", "country_code": "US",
     "lap_record_time": "1:35.490", "lap_record_driver": "Oscar Piastri", "lap_record_year": 2024,
     "length_km": 6.201, "turns": 17, "drs_zones": 2, "fastf1_key": "Las Vegas", "image_key": "las-vegas"},
    {"id": "qatar", "name": "Lusail International Circuit", "short_name": "Qatar",
     "country": "Qatar", "city": "Lusail", "country_code": "QA",
     "lap_record_time": "1:24.319", "lap_record_driver": "Max Verstappen", "lap_record_year": 2023,
     "length_km": 5.380, "turns": 16, "drs_zones": 2, "fastf1_key": "Qatar", "image_key": "qatar"},
    {"id": "abu-dhabi", "name": "Yas Marina Circuit", "short_name": "Abu Dhabi",
     "country": "UAE", "city": "Abu Dhabi", "country_code": "AE",
     "lap_record_time": "1:26.103", "lap_record_driver": "Max Verstappen", "lap_record_year": 2021,
     "length_km": 5.281, "turns": 16, "drs_zones": 2, "fastf1_key": "Abu Dhabi", "image_key": "abu-dhabi"},
    {"id": "france", "name": "Circuit Paul Ricard", "short_name": "France",
     "country": "France", "city": "Le Castellet", "country_code": "FR",
     "lap_record_time": "1:32.740", "lap_record_driver": "Sebastian Vettel", "lap_record_year": 2019,
     "length_km": 5.842, "turns": 15, "drs_zones": 2, "fastf1_key": "France", "image_key": "france"},
]

# ===========================================================================
# TEAMS
# ===========================================================================

TEAMS_DATA = [
    # 2022
    {"year": 2022, "id": "red-bull", "full_name": "Oracle Red Bull Racing", "short_name": "Red Bull", "car_model": "RB18", "engine": "Honda RBPTH001", "color": "#3671C6"},
    {"year": 2022, "id": "ferrari", "full_name": "Scuderia Ferrari", "short_name": "Ferrari", "car_model": "F1-75", "engine": "Ferrari 066/7", "color": "#E8002D"},
    {"year": 2022, "id": "mercedes", "full_name": "Mercedes-AMG Petronas", "short_name": "Mercedes", "car_model": "W13", "engine": "Mercedes M13", "color": "#27F4D2"},
    {"year": 2022, "id": "mclaren", "full_name": "McLaren F1 Team", "short_name": "McLaren", "car_model": "MCL36", "engine": "Mercedes M13", "color": "#FF8000"},
    {"year": 2022, "id": "alpine", "full_name": "BWT Alpine F1 Team", "short_name": "Alpine", "car_model": "A522", "engine": "Renault E-Tech RE22", "color": "#0090FF"},
    {"year": 2022, "id": "alfa-romeo", "full_name": "Alfa Romeo F1 Team ORLEN", "short_name": "Alfa Romeo", "car_model": "C42", "engine": "Ferrari 066/7", "color": "#900000"},
    {"year": 2022, "id": "aston-martin", "full_name": "Aston Martin Aramco", "short_name": "Aston Martin", "car_model": "AMR22", "engine": "Mercedes M13", "color": "#358C75"},
    {"year": 2022, "id": "haas", "full_name": "Haas F1 Team", "short_name": "Haas", "car_model": "VF-22", "engine": "Ferrari 066/7", "color": "#B6BABD"},
    {"year": 2022, "id": "alphatauri", "full_name": "Scuderia AlphaTauri", "short_name": "AlphaTauri", "car_model": "AT03", "engine": "Honda RBPTH001", "color": "#2B4562"},
    {"year": 2022, "id": "williams", "full_name": "Williams Racing", "short_name": "Williams", "car_model": "FW44", "engine": "Mercedes M13", "color": "#37BEDD"},
    # 2023
    {"year": 2023, "id": "red-bull", "full_name": "Oracle Red Bull Racing", "short_name": "Red Bull", "car_model": "RB19", "engine": "Honda RBPTH023", "color": "#3671C6"},
    {"year": 2023, "id": "ferrari", "full_name": "Scuderia Ferrari", "short_name": "Ferrari", "car_model": "SF-23", "engine": "Ferrari 066/10", "color": "#E8002D"},
    {"year": 2023, "id": "mercedes", "full_name": "Mercedes-AMG Petronas", "short_name": "Mercedes", "car_model": "W14", "engine": "Mercedes M14", "color": "#27F4D2"},
    {"year": 2023, "id": "mclaren", "full_name": "McLaren F1 Team", "short_name": "McLaren", "car_model": "MCL60", "engine": "Mercedes M14", "color": "#FF8000"},
    {"year": 2023, "id": "alpine", "full_name": "BWT Alpine F1 Team", "short_name": "Alpine", "car_model": "A523", "engine": "Renault E-Tech RE23", "color": "#0090FF"},
    {"year": 2023, "id": "alfa-romeo", "full_name": "Alfa Romeo F1 Team", "short_name": "Alfa Romeo", "car_model": "C43", "engine": "Ferrari 066/10", "color": "#900000"},
    {"year": 2023, "id": "aston-martin", "full_name": "Aston Martin Aramco", "short_name": "Aston Martin", "car_model": "AMR23", "engine": "Mercedes M14", "color": "#358C75"},
    {"year": 2023, "id": "haas", "full_name": "Haas F1 Team", "short_name": "Haas", "car_model": "VF-23", "engine": "Ferrari 066/10", "color": "#B6BABD"},
    {"year": 2023, "id": "alphatauri", "full_name": "Scuderia AlphaTauri", "short_name": "AlphaTauri", "car_model": "AT04", "engine": "Honda RBPTH023", "color": "#2B4562"},
    {"year": 2023, "id": "williams", "full_name": "Williams Racing", "short_name": "Williams", "car_model": "FW45", "engine": "Mercedes M14", "color": "#37BEDD"},
    # 2024
    {"year": 2024, "id": "red-bull", "full_name": "Oracle Red Bull Racing", "short_name": "Red Bull", "car_model": "RB20", "engine": "Honda RBPTH001", "color": "#3671C6"},
    {"year": 2024, "id": "ferrari", "full_name": "Scuderia Ferrari", "short_name": "Ferrari", "car_model": "SF-24", "engine": "Ferrari 066/12", "color": "#E8002D"},
    {"year": 2024, "id": "mercedes", "full_name": "Mercedes-AMG Petronas", "short_name": "Mercedes", "car_model": "W15", "engine": "Mercedes M15", "color": "#27F4D2"},
    {"year": 2024, "id": "mclaren", "full_name": "McLaren F1 Team", "short_name": "McLaren", "car_model": "MCL38", "engine": "Mercedes M15", "color": "#FF8000"},
    {"year": 2024, "id": "alpine", "full_name": "BWT Alpine F1 Team", "short_name": "Alpine", "car_model": "A524", "engine": "Renault E-Tech RE24", "color": "#0090FF"},
    {"year": 2024, "id": "kick-sauber", "full_name": "Stake F1 Team Kick Sauber", "short_name": "Kick Sauber", "car_model": "C44", "engine": "Ferrari 066/12", "color": "#00CF46"},
    {"year": 2024, "id": "aston-martin", "full_name": "Aston Martin Aramco", "short_name": "Aston Martin", "car_model": "AMR24", "engine": "Mercedes M15", "color": "#358C75"},
    {"year": 2024, "id": "haas", "full_name": "Haas F1 Team", "short_name": "Haas", "car_model": "VF-24", "engine": "Ferrari 066/12", "color": "#B6BABD"},
    {"year": 2024, "id": "rb", "full_name": "Visa Cash App RB", "short_name": "RB", "car_model": "VCARB01", "engine": "Honda RBPTH001", "color": "#6692FF"},
    {"year": 2024, "id": "williams", "full_name": "Williams Racing", "short_name": "Williams", "car_model": "FW46", "engine": "Mercedes M15", "color": "#37BEDD"},
    # 2025
    {"year": 2025, "id": "red-bull", "full_name": "Oracle Red Bull Racing", "short_name": "Red Bull", "car_model": "RB21", "engine": "Honda RBPTH025", "color": "#3671C6"},
    {"year": 2025, "id": "ferrari", "full_name": "Scuderia Ferrari", "short_name": "Ferrari", "car_model": "SF-25", "engine": "Ferrari 066/14", "color": "#E8002D"},
    {"year": 2025, "id": "mercedes", "full_name": "Mercedes-AMG Petronas", "short_name": "Mercedes", "car_model": "W16", "engine": "Mercedes M16", "color": "#27F4D2"},
    {"year": 2025, "id": "mclaren", "full_name": "McLaren F1 Team", "short_name": "McLaren", "car_model": "MCL39", "engine": "Mercedes M16", "color": "#FF8000"},
    {"year": 2025, "id": "alpine", "full_name": "BWT Alpine F1 Team", "short_name": "Alpine", "car_model": "A525", "engine": "Renault E-Tech RE25", "color": "#0090FF"},
    {"year": 2025, "id": "kick-sauber", "full_name": "Stake F1 Team Kick Sauber", "short_name": "Kick Sauber", "car_model": "C45", "engine": "Ferrari 066/14", "color": "#00CF46"},
    {"year": 2025, "id": "aston-martin", "full_name": "Aston Martin Aramco", "short_name": "Aston Martin", "car_model": "AMR25", "engine": "Mercedes M16", "color": "#358C75"},
    {"year": 2025, "id": "haas", "full_name": "Haas F1 Team", "short_name": "Haas", "car_model": "VF-25", "engine": "Ferrari 066/14", "color": "#B6BABD"},
    {"year": 2025, "id": "rb", "full_name": "Visa Cash App RB", "short_name": "RB", "car_model": "VCARB02", "engine": "Honda RBPTH025", "color": "#6692FF"},
    {"year": 2025, "id": "williams", "full_name": "Williams Racing", "short_name": "Williams", "car_model": "FW47", "engine": "Mercedes M16", "color": "#37BEDD"},
    # 2026 (provisional)
    {"year": 2026, "id": "red-bull", "full_name": "Oracle Red Bull Racing", "short_name": "Red Bull", "car_model": "RB22", "engine": "Ford", "color": "#3671C6"},
    {"year": 2026, "id": "ferrari", "full_name": "Scuderia Ferrari", "short_name": "Ferrari", "car_model": "SF-26", "engine": "Ferrari", "color": "#E8002D"},
    {"year": 2026, "id": "mercedes", "full_name": "Mercedes-AMG Petronas", "short_name": "Mercedes", "car_model": "W17", "engine": "Mercedes", "color": "#27F4D2"},
    {"year": 2026, "id": "mclaren", "full_name": "McLaren F1 Team", "short_name": "McLaren", "car_model": "MCL40", "engine": "Mercedes", "color": "#FF8000"},
    {"year": 2026, "id": "alpine", "full_name": "BWT Alpine F1 Team", "short_name": "Alpine", "car_model": "A526", "engine": "Renault", "color": "#0090FF"},
    {"year": 2026, "id": "audi", "full_name": "Audi F1 Team", "short_name": "Audi", "car_model": "C46", "engine": "Audi", "color": "#FF0000"},
    {"year": 2026, "id": "aston-martin", "full_name": "Aston Martin Aramco", "short_name": "Aston Martin", "car_model": "AMR26", "engine": "Honda", "color": "#358C75"},
    {"year": 2026, "id": "haas", "full_name": "Haas F1 Team", "short_name": "Haas", "car_model": "VF-26", "engine": "Ferrari", "color": "#B6BABD"},
    {"year": 2026, "id": "rb", "full_name": "Racing Bulls", "short_name": "Racing Bulls", "car_model": "RB02", "engine": "Honda", "color": "#6692FF"},
    {"year": 2026, "id": "williams", "full_name": "Williams Racing", "short_name": "Williams", "car_model": "FW48", "engine": "Mercedes", "color": "#37BEDD"},
]

# ===========================================================================
# DRIVERS
# ===========================================================================

DRIVERS_DATA = [
    # 2022
    {"code": "VER", "year": 2022, "first_name": "Max", "last_name": "Verstappen", "number": 1, "team_id": "red-bull", "nationality": "Dutch", "color": "#3671C6"},
    {"code": "PER", "year": 2022, "first_name": "Sergio", "last_name": "Perez", "number": 11, "team_id": "red-bull", "nationality": "Mexican", "color": "#3671C6"},
    {"code": "LEC", "year": 2022, "first_name": "Charles", "last_name": "Leclerc", "number": 16, "team_id": "ferrari", "nationality": "Monegasque", "color": "#E8002D"},
    {"code": "SAI", "year": 2022, "first_name": "Carlos", "last_name": "Sainz", "number": 55, "team_id": "ferrari", "nationality": "Spanish", "color": "#E8002D"},
    {"code": "HAM", "year": 2022, "first_name": "Lewis", "last_name": "Hamilton", "number": 44, "team_id": "mercedes", "nationality": "British", "color": "#27F4D2"},
    {"code": "RUS", "year": 2022, "first_name": "George", "last_name": "Russell", "number": 63, "team_id": "mercedes", "nationality": "British", "color": "#27F4D2"},
    {"code": "NOR", "year": 2022, "first_name": "Lando", "last_name": "Norris", "number": 4, "team_id": "mclaren", "nationality": "British", "color": "#FF8000"},
    {"code": "RIC", "year": 2022, "first_name": "Daniel", "last_name": "Ricciardo", "number": 3, "team_id": "mclaren", "nationality": "Australian", "color": "#FF8000"},
    {"code": "ALO", "year": 2022, "first_name": "Fernando", "last_name": "Alonso", "number": 14, "team_id": "alpine", "nationality": "Spanish", "color": "#0090FF"},
    {"code": "OCO", "year": 2022, "first_name": "Esteban", "last_name": "Ocon", "number": 31, "team_id": "alpine", "nationality": "French", "color": "#0090FF"},
    {"code": "BOT", "year": 2022, "first_name": "Valtteri", "last_name": "Bottas", "number": 77, "team_id": "alfa-romeo", "nationality": "Finnish", "color": "#900000"},
    {"code": "ZHO", "year": 2022, "first_name": "Guanyu", "last_name": "Zhou", "number": 24, "team_id": "alfa-romeo", "nationality": "Chinese", "color": "#900000"},
    {"code": "STR", "year": 2022, "first_name": "Lance", "last_name": "Stroll", "number": 18, "team_id": "aston-martin", "nationality": "Canadian", "color": "#358C75"},
    {"code": "VET", "year": 2022, "first_name": "Sebastian", "last_name": "Vettel", "number": 5, "team_id": "aston-martin", "nationality": "German", "color": "#358C75"},
    {"code": "MAG", "year": 2022, "first_name": "Kevin", "last_name": "Magnussen", "number": 20, "team_id": "haas", "nationality": "Danish", "color": "#B6BABD"},
    {"code": "MSC", "year": 2022, "first_name": "Mick", "last_name": "Schumacher", "number": 47, "team_id": "haas", "nationality": "German", "color": "#B6BABD"},
    {"code": "GAS", "year": 2022, "first_name": "Pierre", "last_name": "Gasly", "number": 10, "team_id": "alphatauri", "nationality": "French", "color": "#2B4562"},
    {"code": "TSU", "year": 2022, "first_name": "Yuki", "last_name": "Tsunoda", "number": 22, "team_id": "alphatauri", "nationality": "Japanese", "color": "#2B4562"},
    {"code": "ALB", "year": 2022, "first_name": "Alexander", "last_name": "Albon", "number": 23, "team_id": "williams", "nationality": "Thai", "color": "#37BEDD"},
    {"code": "LAT", "year": 2022, "first_name": "Nicholas", "last_name": "Latifi", "number": 6, "team_id": "williams", "nationality": "Canadian", "color": "#37BEDD"},
    # 2023
    {"code": "VER", "year": 2023, "first_name": "Max", "last_name": "Verstappen", "number": 1, "team_id": "red-bull", "nationality": "Dutch", "color": "#3671C6"},
    {"code": "PER", "year": 2023, "first_name": "Sergio", "last_name": "Perez", "number": 11, "team_id": "red-bull", "nationality": "Mexican", "color": "#3671C6"},
    {"code": "LEC", "year": 2023, "first_name": "Charles", "last_name": "Leclerc", "number": 16, "team_id": "ferrari", "nationality": "Monegasque", "color": "#E8002D"},
    {"code": "SAI", "year": 2023, "first_name": "Carlos", "last_name": "Sainz", "number": 55, "team_id": "ferrari", "nationality": "Spanish", "color": "#E8002D"},
    {"code": "HAM", "year": 2023, "first_name": "Lewis", "last_name": "Hamilton", "number": 44, "team_id": "mercedes", "nationality": "British", "color": "#27F4D2"},
    {"code": "RUS", "year": 2023, "first_name": "George", "last_name": "Russell", "number": 63, "team_id": "mercedes", "nationality": "British", "color": "#27F4D2"},
    {"code": "NOR", "year": 2023, "first_name": "Lando", "last_name": "Norris", "number": 4, "team_id": "mclaren", "nationality": "British", "color": "#FF8000"},
    {"code": "PIA", "year": 2023, "first_name": "Oscar", "last_name": "Piastri", "number": 81, "team_id": "mclaren", "nationality": "Australian", "color": "#FF8000"},
    {"code": "ALO", "year": 2023, "first_name": "Fernando", "last_name": "Alonso", "number": 14, "team_id": "aston-martin", "nationality": "Spanish", "color": "#358C75"},
    {"code": "STR", "year": 2023, "first_name": "Lance", "last_name": "Stroll", "number": 18, "team_id": "aston-martin", "nationality": "Canadian", "color": "#358C75"},
    {"code": "OCO", "year": 2023, "first_name": "Esteban", "last_name": "Ocon", "number": 31, "team_id": "alpine", "nationality": "French", "color": "#0090FF"},
    {"code": "GAS", "year": 2023, "first_name": "Pierre", "last_name": "Gasly", "number": 10, "team_id": "alpine", "nationality": "French", "color": "#0090FF"},
    {"code": "BOT", "year": 2023, "first_name": "Valtteri", "last_name": "Bottas", "number": 77, "team_id": "alfa-romeo", "nationality": "Finnish", "color": "#900000"},
    {"code": "ZHO", "year": 2023, "first_name": "Guanyu", "last_name": "Zhou", "number": 24, "team_id": "alfa-romeo", "nationality": "Chinese", "color": "#900000"},
    {"code": "MAG", "year": 2023, "first_name": "Kevin", "last_name": "Magnussen", "number": 20, "team_id": "haas", "nationality": "Danish", "color": "#B6BABD"},
    {"code": "HUL", "year": 2023, "first_name": "Nico", "last_name": "Hulkenberg", "number": 27, "team_id": "haas", "nationality": "German", "color": "#B6BABD"},
    {"code": "TSU", "year": 2023, "first_name": "Yuki", "last_name": "Tsunoda", "number": 22, "team_id": "alphatauri", "nationality": "Japanese", "color": "#2B4562"},
    {"code": "DEV", "year": 2023, "first_name": "Nyck", "last_name": "de Vries", "number": 21, "team_id": "alphatauri", "nationality": "Dutch", "color": "#2B4562"},
    {"code": "ALB", "year": 2023, "first_name": "Alexander", "last_name": "Albon", "number": 23, "team_id": "williams", "nationality": "Thai", "color": "#37BEDD"},
    {"code": "SAR", "year": 2023, "first_name": "Logan", "last_name": "Sargeant", "number": 2, "team_id": "williams", "nationality": "American", "color": "#37BEDD"},
    # 2024
    {"code": "VER", "year": 2024, "first_name": "Max", "last_name": "Verstappen", "number": 1, "team_id": "red-bull", "nationality": "Dutch", "color": "#3671C6"},
    {"code": "PER", "year": 2024, "first_name": "Sergio", "last_name": "Perez", "number": 11, "team_id": "red-bull", "nationality": "Mexican", "color": "#3671C6"},
    {"code": "LEC", "year": 2024, "first_name": "Charles", "last_name": "Leclerc", "number": 16, "team_id": "ferrari", "nationality": "Monegasque", "color": "#E8002D"},
    {"code": "SAI", "year": 2024, "first_name": "Carlos", "last_name": "Sainz", "number": 55, "team_id": "ferrari", "nationality": "Spanish", "color": "#E8002D"},
    {"code": "HAM", "year": 2024, "first_name": "Lewis", "last_name": "Hamilton", "number": 44, "team_id": "mercedes", "nationality": "British", "color": "#27F4D2"},
    {"code": "RUS", "year": 2024, "first_name": "George", "last_name": "Russell", "number": 63, "team_id": "mercedes", "nationality": "British", "color": "#27F4D2"},
    {"code": "NOR", "year": 2024, "first_name": "Lando", "last_name": "Norris", "number": 4, "team_id": "mclaren", "nationality": "British", "color": "#FF8000"},
    {"code": "PIA", "year": 2024, "first_name": "Oscar", "last_name": "Piastri", "number": 81, "team_id": "mclaren", "nationality": "Australian", "color": "#FF8000"},
    {"code": "ALO", "year": 2024, "first_name": "Fernando", "last_name": "Alonso", "number": 14, "team_id": "aston-martin", "nationality": "Spanish", "color": "#358C75"},
    {"code": "STR", "year": 2024, "first_name": "Lance", "last_name": "Stroll", "number": 18, "team_id": "aston-martin", "nationality": "Canadian", "color": "#358C75"},
    {"code": "OCO", "year": 2024, "first_name": "Esteban", "last_name": "Ocon", "number": 31, "team_id": "alpine", "nationality": "French", "color": "#0090FF"},
    {"code": "GAS", "year": 2024, "first_name": "Pierre", "last_name": "Gasly", "number": 10, "team_id": "alpine", "nationality": "French", "color": "#0090FF"},
    {"code": "BOT", "year": 2024, "first_name": "Valtteri", "last_name": "Bottas", "number": 77, "team_id": "kick-sauber", "nationality": "Finnish", "color": "#00CF46"},
    {"code": "ZHO", "year": 2024, "first_name": "Guanyu", "last_name": "Zhou", "number": 24, "team_id": "kick-sauber", "nationality": "Chinese", "color": "#00CF46"},
    {"code": "MAG", "year": 2024, "first_name": "Kevin", "last_name": "Magnussen", "number": 20, "team_id": "haas", "nationality": "Danish", "color": "#B6BABD"},
    {"code": "HUL", "year": 2024, "first_name": "Nico", "last_name": "Hulkenberg", "number": 27, "team_id": "haas", "nationality": "German", "color": "#B6BABD"},
    {"code": "TSU", "year": 2024, "first_name": "Yuki", "last_name": "Tsunoda", "number": 22, "team_id": "rb", "nationality": "Japanese", "color": "#6692FF"},
    {"code": "RIC", "year": 2024, "first_name": "Daniel", "last_name": "Ricciardo", "number": 3, "team_id": "rb", "nationality": "Australian", "color": "#6692FF"},
    {"code": "ALB", "year": 2024, "first_name": "Alexander", "last_name": "Albon", "number": 23, "team_id": "williams", "nationality": "Thai", "color": "#37BEDD"},
    {"code": "SAR", "year": 2024, "first_name": "Logan", "last_name": "Sargeant", "number": 2, "team_id": "williams", "nationality": "American", "color": "#37BEDD"},
    # 2025
    {"code": "VER", "year": 2025, "first_name": "Max", "last_name": "Verstappen", "number": 1, "team_id": "red-bull", "nationality": "Dutch", "color": "#3671C6"},
    {"code": "LAW", "year": 2025, "first_name": "Liam", "last_name": "Lawson", "number": 30, "team_id": "red-bull", "nationality": "New Zealander", "color": "#3671C6"},
    {"code": "LEC", "year": 2025, "first_name": "Charles", "last_name": "Leclerc", "number": 16, "team_id": "ferrari", "nationality": "Monegasque", "color": "#E8002D"},
    {"code": "HAM", "year": 2025, "first_name": "Lewis", "last_name": "Hamilton", "number": 44, "team_id": "ferrari", "nationality": "British", "color": "#E8002D"},
    {"code": "RUS", "year": 2025, "first_name": "George", "last_name": "Russell", "number": 63, "team_id": "mercedes", "nationality": "British", "color": "#27F4D2"},
    {"code": "ANT", "year": 2025, "first_name": "Andrea Kimi", "last_name": "Antonelli", "number": 12, "team_id": "mercedes", "nationality": "Italian", "color": "#27F4D2"},
    {"code": "NOR", "year": 2025, "first_name": "Lando", "last_name": "Norris", "number": 4, "team_id": "mclaren", "nationality": "British", "color": "#FF8000"},
    {"code": "PIA", "year": 2025, "first_name": "Oscar", "last_name": "Piastri", "number": 81, "team_id": "mclaren", "nationality": "Australian", "color": "#FF8000"},
    {"code": "ALO", "year": 2025, "first_name": "Fernando", "last_name": "Alonso", "number": 14, "team_id": "aston-martin", "nationality": "Spanish", "color": "#358C75"},
    {"code": "STR", "year": 2025, "first_name": "Lance", "last_name": "Stroll", "number": 18, "team_id": "aston-martin", "nationality": "Canadian", "color": "#358C75"},
    {"code": "OCO", "year": 2025, "first_name": "Esteban", "last_name": "Ocon", "number": 31, "team_id": "haas", "nationality": "French", "color": "#B6BABD"},
    {"code": "BOR", "year": 2025, "first_name": "Gabriel", "last_name": "Bortoleto", "number": 5, "team_id": "kick-sauber", "nationality": "Brazilian", "color": "#00CF46"},
    {"code": "HUL", "year": 2025, "first_name": "Nico", "last_name": "Hulkenberg", "number": 27, "team_id": "kick-sauber", "nationality": "German", "color": "#00CF46"},
    {"code": "MAG", "year": 2025, "first_name": "Kevin", "last_name": "Magnussen", "number": 20, "team_id": "haas", "nationality": "Danish", "color": "#B6BABD"},
    {"code": "GAS", "year": 2025, "first_name": "Pierre", "last_name": "Gasly", "number": 10, "team_id": "alpine", "nationality": "French", "color": "#0090FF"},
    {"code": "DOO", "year": 2025, "first_name": "Jack", "last_name": "Doohan", "number": 7, "team_id": "alpine", "nationality": "Australian", "color": "#0090FF"},
    {"code": "TSU", "year": 2025, "first_name": "Yuki", "last_name": "Tsunoda", "number": 22, "team_id": "rb", "nationality": "Japanese", "color": "#6692FF"},
    {"code": "HAD", "year": 2025, "first_name": "Isack", "last_name": "Hadjar", "number": 6, "team_id": "rb", "nationality": "French", "color": "#6692FF"},
    {"code": "ALB", "year": 2025, "first_name": "Alexander", "last_name": "Albon", "number": 23, "team_id": "williams", "nationality": "Thai", "color": "#37BEDD"},
    {"code": "SAI", "year": 2025, "first_name": "Carlos", "last_name": "Sainz", "number": 55, "team_id": "williams", "nationality": "Spanish", "color": "#37BEDD"},
    # 2026 (provisional)
    {"code": "VER", "year": 2026, "first_name": "Max", "last_name": "Verstappen", "number": 1, "team_id": "red-bull", "nationality": "Dutch", "color": "#3671C6"},
    {"code": "LAW", "year": 2026, "first_name": "Liam", "last_name": "Lawson", "number": 30, "team_id": "red-bull", "nationality": "New Zealander", "color": "#3671C6"},
    {"code": "LEC", "year": 2026, "first_name": "Charles", "last_name": "Leclerc", "number": 16, "team_id": "ferrari", "nationality": "Monegasque", "color": "#E8002D"},
    {"code": "HAM", "year": 2026, "first_name": "Lewis", "last_name": "Hamilton", "number": 44, "team_id": "ferrari", "nationality": "British", "color": "#E8002D"},
    {"code": "RUS", "year": 2026, "first_name": "George", "last_name": "Russell", "number": 63, "team_id": "mercedes", "nationality": "British", "color": "#27F4D2"},
    {"code": "ANT", "year": 2026, "first_name": "Andrea Kimi", "last_name": "Antonelli", "number": 12, "team_id": "mercedes", "nationality": "Italian", "color": "#27F4D2"},
    {"code": "NOR", "year": 2026, "first_name": "Lando", "last_name": "Norris", "number": 4, "team_id": "mclaren", "nationality": "British", "color": "#FF8000"},
    {"code": "PIA", "year": 2026, "first_name": "Oscar", "last_name": "Piastri", "number": 81, "team_id": "mclaren", "nationality": "Australian", "color": "#FF8000"},
    {"code": "ALO", "year": 2026, "first_name": "Fernando", "last_name": "Alonso", "number": 14, "team_id": "aston-martin", "nationality": "Spanish", "color": "#358C75"},
    {"code": "STR", "year": 2026, "first_name": "Lance", "last_name": "Stroll", "number": 18, "team_id": "aston-martin", "nationality": "Canadian", "color": "#358C75"},
    {"code": "GAS", "year": 2026, "first_name": "Pierre", "last_name": "Gasly", "number": 10, "team_id": "alpine", "nationality": "French", "color": "#0090FF"},
    {"code": "DOO", "year": 2026, "first_name": "Jack", "last_name": "Doohan", "number": 7, "team_id": "alpine", "nationality": "Australian", "color": "#0090FF"},
    {"code": "BOR", "year": 2026, "first_name": "Gabriel", "last_name": "Bortoleto", "number": 5, "team_id": "audi", "nationality": "Brazilian", "color": "#FF0000"},
    {"code": "HUL", "year": 2026, "first_name": "Nico", "last_name": "Hulkenberg", "number": 27, "team_id": "audi", "nationality": "German", "color": "#FF0000"},
    {"code": "OCO", "year": 2026, "first_name": "Esteban", "last_name": "Ocon", "number": 31, "team_id": "haas", "nationality": "French", "color": "#B6BABD"},
    {"code": "MAG", "year": 2026, "first_name": "Kevin", "last_name": "Magnussen", "number": 20, "team_id": "haas", "nationality": "Danish", "color": "#B6BABD"},
    {"code": "TSU", "year": 2026, "first_name": "Yuki", "last_name": "Tsunoda", "number": 22, "team_id": "rb", "nationality": "Japanese", "color": "#6692FF"},
    {"code": "HAD", "year": 2026, "first_name": "Isack", "last_name": "Hadjar", "number": 6, "team_id": "rb", "nationality": "French", "color": "#6692FF"},
    {"code": "ALB", "year": 2026, "first_name": "Alexander", "last_name": "Albon", "number": 23, "team_id": "williams", "nationality": "Thai", "color": "#37BEDD"},
    {"code": "SAI", "year": 2026, "first_name": "Carlos", "last_name": "Sainz", "number": 55, "team_id": "williams", "nationality": "Spanish", "color": "#37BEDD"},
]

# ===========================================================================
# CIRCUIT ID MAPPING (Jolpica circuitId → our id)
# ===========================================================================

CIRCUIT_ID_MAP = {
    "bahrain": "bahrain",
    "jeddah": "saudi-arabia",
    "albert_park": "australia",
    "suzuka": "japan",
    "shanghai": "china",
    "miami": "miami",
    "imola": "imola",
    "monaco": "monaco",
    "catalunya": "spain",
    "villeneuve": "canada",
    "red_bull_ring": "austria",
    "silverstone": "great-britain",
    "hungaroring": "hungary",
    "spa": "belgium",
    "zandvoort": "netherlands",
    "monza": "italy",
    "marina_bay": "singapore",
    "baku": "azerbaijan",
    "americas": "usa",
    "rodriguez": "mexico",
    "interlagos": "brazil",
    "las_vegas": "las-vegas",
    "vegas": "las-vegas",
    "losail": "qatar",
    "yas_marina": "abu-dhabi",
    "paul_ricard": "france",
    "ricard": "france",
}

# Sprint weekends per year
SPRINT_WEEKENDS = {
    2022: {"austria", "brazil"},
    2023: {"azerbaijan", "austria", "belgium", "usa", "brazil"},
    2024: {"china", "miami", "austria", "usa", "brazil", "qatar"},
    2025: {"china", "miami", "belgium", "usa", "brazil", "qatar"},
    2026: set(),
}

# ===========================================================================
# 2026 CALENDAR (hardcoded)
# ===========================================================================

RACES_2026 = [
    {"round": 1, "circuit_id": "australia", "date": "2026-03-08", "provisional": False},
    {"round": 2, "circuit_id": "china", "date": "2026-03-15", "provisional": False},
    {"round": 3, "circuit_id": "japan", "date": "2026-03-29", "provisional": True},
    {"round": 4, "circuit_id": "bahrain", "date": "2026-04-12", "provisional": True},
    {"round": 5, "circuit_id": "saudi-arabia", "date": "2026-04-19", "provisional": True},
    {"round": 6, "circuit_id": "miami", "date": "2026-05-03", "provisional": True},
    {"round": 7, "circuit_id": "monaco", "date": "2026-05-24", "provisional": True},
    {"round": 8, "circuit_id": "spain", "date": "2026-06-07", "provisional": True},
    {"round": 9, "circuit_id": "canada", "date": "2026-06-21", "provisional": True},
    {"round": 10, "circuit_id": "austria", "date": "2026-07-05", "provisional": True},
    {"round": 11, "circuit_id": "great-britain", "date": "2026-07-12", "provisional": True},
    {"round": 12, "circuit_id": "belgium", "date": "2026-07-26", "provisional": True},
    {"round": 13, "circuit_id": "hungary", "date": "2026-08-02", "provisional": True},
    {"round": 14, "circuit_id": "netherlands", "date": "2026-08-30", "provisional": True},
    {"round": 15, "circuit_id": "italy", "date": "2026-09-06", "provisional": True},
    {"round": 16, "circuit_id": "azerbaijan", "date": "2026-09-20", "provisional": True},
    {"round": 17, "circuit_id": "singapore", "date": "2026-10-04", "provisional": True},
    {"round": 18, "circuit_id": "japan", "date": "2026-10-11", "provisional": True},
    {"round": 19, "circuit_id": "usa", "date": "2026-10-18", "provisional": True},
    {"round": 20, "circuit_id": "mexico", "date": "2026-10-25", "provisional": True},
    {"round": 21, "circuit_id": "brazil", "date": "2026-11-08", "provisional": True},
    {"round": 22, "circuit_id": "las-vegas", "date": "2026-11-21", "provisional": True},
    {"round": 23, "circuit_id": "qatar", "date": "2026-11-29", "provisional": True},
    {"round": 24, "circuit_id": "abu-dhabi", "date": "2026-12-06", "provisional": True},
]

# ===========================================================================
# SEED FUNCTIONS
# ===========================================================================

async def seed_circuits(session):
    logger.info("=== Seeding circuits ===")
    count = 0
    for c in CIRCUITS_DATA:
        stmt = pg_insert(models.Circuit).values(
            id=c["id"],
            name=c["name"],
            short_name=c["short_name"],
            country=c["country"],
            city=c["city"],
            country_code=c["country_code"],
            lap_record_time=c.get("lap_record_time"),
            lap_record_driver=c.get("lap_record_driver"),
            lap_record_year=c.get("lap_record_year"),
            length_km=c.get("length_km"),
            turns=c.get("turns"),
            drs_zones=c.get("drs_zones"),
            fastf1_key=c["fastf1_key"],
            image_key=c.get("image_key"),
        ).on_conflict_do_update(
            index_elements=["id"],
            set_={
                "name": c["name"],
                "short_name": c["short_name"],
                "country": c["country"],
                "city": c["city"],
                "country_code": c["country_code"],
                "lap_record_time": c.get("lap_record_time"),
                "lap_record_driver": c.get("lap_record_driver"),
                "lap_record_year": c.get("lap_record_year"),
                "length_km": c.get("length_km"),
                "turns": c.get("turns"),
                "drs_zones": c.get("drs_zones"),
                "fastf1_key": c["fastf1_key"],
                "image_key": c.get("image_key"),
            }
        )
        await session.execute(stmt)
        count += 1
    await session.commit()
    logger.info(f"Circuits: {count} upserted")
    return count


async def seed_teams(session):
    logger.info("=== Seeding teams ===")
    count = 0
    for t in TEAMS_DATA:
        stmt = pg_insert(models.Team).values(
            id=t["id"],
            year=t["year"],
            full_name=t["full_name"],
            short_name=t["short_name"],
            car_model=t.get("car_model"),
            engine=t.get("engine"),
            color=t["color"],
        ).on_conflict_do_update(
            index_elements=["id", "year"],
            set_={
                "full_name": t["full_name"],
                "short_name": t["short_name"],
                "car_model": t.get("car_model"),
                "engine": t.get("engine"),
                "color": t["color"],
            }
        )
        await session.execute(stmt)
        count += 1
    await session.commit()
    logger.info(f"Teams: {count} upserted")
    return count


async def seed_drivers(session):
    logger.info("=== Seeding drivers ===")
    count = 0
    for d in DRIVERS_DATA:
        stmt = pg_insert(models.Driver).values(
            code=d["code"],
            year=d["year"],
            first_name=d["first_name"],
            last_name=d["last_name"],
            number=d.get("number"),
            team_id=d["team_id"],
            nationality=d.get("nationality"),
            color=d.get("color"),
        ).on_conflict_do_update(
            index_elements=["code", "year"],
            set_={
                "first_name": d["first_name"],
                "last_name": d["last_name"],
                "number": d.get("number"),
                "team_id": d["team_id"],
                "nationality": d.get("nationality"),
                "color": d.get("color"),
            }
        )
        await session.execute(stmt)
        count += 1
    await session.commit()
    logger.info(f"Drivers: {count} upserted")
    return count


async def fetch_json(client, url, _retries=3):
    await asyncio.sleep(SLEEP_BETWEEN_CALLS)
    for attempt in range(_retries):
        try:
            resp = await client.get(url, timeout=30)
            if resp.status_code == 429:
                logger.warning(f"Rate limited (429) on {url} — waiting {RETRY_ON_429_WAIT}s (attempt {attempt + 1}/{_retries})")
                await asyncio.sleep(RETRY_ON_429_WAIT)
                continue
            if resp.status_code == 404:
                # Not found — no point retrying
                return None
            resp.raise_for_status()
            return resp.json()
        except Exception as e:
            if attempt < _retries - 1:
                logger.warning(f"API error fetching {url}: {e} — retrying in 5s")
                await asyncio.sleep(5)
            else:
                logger.warning(f"API error fetching {url}: {e}")
                return None
    return None


def get_fastf1_key_for_circuit(circuit_id):
    for c in CIRCUITS_DATA:
        if c["id"] == circuit_id:
            return c["fastf1_key"]
    return circuit_id


async def seed_races(session, client):
    logger.info("=== Seeding races (2022-2025 from Jolpica) ===")
    total = 0
    for year in [2022, 2023, 2024, 2025]:
        url = f"{JOLPICA_BASE}/{year}/races.json?limit=100"
        data = await fetch_json(client, url)
        if not data:
            logger.warning(f"No race data for {year}")
            continue
        races = data.get("MRData", {}).get("RaceTable", {}).get("Races", [])
        sprint_circuits = SPRINT_WEEKENDS.get(year, set())
        for r in races:
            jolpica_circuit_id = r.get("Circuit", {}).get("circuitId", "")
            circuit_id = CIRCUIT_ID_MAP.get(jolpica_circuit_id)
            if not circuit_id:
                logger.warning(f"Unknown circuit id: {jolpica_circuit_id} for {year} R{r.get('round')}")
                continue
            is_sprint = circuit_id in sprint_circuits
            race_date = date.fromisoformat(r["date"])
            fastf1_key = get_fastf1_key_for_circuit(circuit_id)
            stmt = pg_insert(models.Race).values(
                year=year,
                round=int(r["round"]),
                circuit_id=circuit_id,
                official_name=r.get("raceName"),
                date=race_date,
                race_date=race_date,
                fastf1_key=fastf1_key,
                is_sprint_weekend=is_sprint,
                is_provisional=False,
            ).on_conflict_do_update(
                index_elements=["year", "round"],
                set_={
                    "circuit_id": circuit_id,
                    "official_name": r.get("raceName"),
                    "date": race_date,
                    "race_date": race_date,
                    "fastf1_key": fastf1_key,
                    "is_sprint_weekend": is_sprint,
                    "is_provisional": False,
                }
            )
            await session.execute(stmt)
            total += 1
        await session.commit()
        logger.info(f"  {year}: {len(races)} races seeded")

    logger.info("=== Seeding races (2026 hardcoded) ===")
    for r in RACES_2026:
        fastf1_key = get_fastf1_key_for_circuit(r["circuit_id"])
        race_date = date.fromisoformat(r["date"])
        stmt = pg_insert(models.Race).values(
            year=2026,
            round=r["round"],
            circuit_id=r["circuit_id"],
            official_name=None,
            date=race_date,
            race_date=race_date,
            fastf1_key=fastf1_key,
            is_sprint_weekend=False,
            is_provisional=r["provisional"],
        ).on_conflict_do_update(
            index_elements=["year", "round"],
            set_={
                "circuit_id": r["circuit_id"],
                "date": race_date,
                "race_date": race_date,
                "fastf1_key": fastf1_key,
                "is_sprint_weekend": False,
                "is_provisional": r["provisional"],
            }
        )
        await session.execute(stmt)
        total += 1
    await session.commit()
    logger.info(f"2026: {len(RACES_2026)} races seeded")
    logger.info(f"Total races seeded: {total}")
    return total


async def get_race_id(session, year, round_num):
    result = await session.execute(
        select(models.Race).where(
            models.Race.year == year,
            models.Race.round == round_num,
        )
    )
    race = result.scalar_one_or_none()
    return race.id if race else None


async def seed_race_results(session, client):
    logger.info("=== Seeding race results (2022-2025) ===")
    total = 0
    failures = 0
    for year in [2022, 2023, 2024, 2025]:
        races_result = await session.execute(
            select(models.Race).where(models.Race.year == year).order_by(models.Race.round)
        )
        races = races_result.scalars().all()
        for race in races:
            logger.info(f"  Results: {year} R{race.round} ({race.circuit_id})")
            results_url = f"{JOLPICA_BASE}/{year}/{race.round}/results.json"
            results_data = await fetch_json(client, results_url)
            if not results_data:
                logger.warning(f"  No results for {year} R{race.round}")
                failures += 1
                continue
            results = results_data.get("MRData", {}).get("RaceTable", {}).get("Races", [])
            if not results:
                logger.warning(f"  Empty results for {year} R{race.round}")
                failures += 1
                continue
            race_results = results[0].get("Results", [])
            if len(race_results) < 3:
                logger.warning(f"  Too few results for {year} R{race.round}")
                failures += 1
                continue

            winner = race_results[0].get("Driver", {}).get("code")
            p2 = race_results[1].get("Driver", {}).get("code") if len(race_results) > 1 else None
            p3 = race_results[2].get("Driver", {}).get("code") if len(race_results) > 2 else None
            total_laps = race_results[0].get("laps")

            fastest_lap_driver = None
            fastest_lap_time = None
            for rr in race_results:
                fl = rr.get("FastestLap", {})
                if fl.get("rank") == "1":
                    fastest_lap_driver = rr.get("Driver", {}).get("code")
                    fastest_lap_time = fl.get("Time", {}).get("time")
                    break

            # Qualifying
            qual_url = f"{JOLPICA_BASE}/{year}/{race.round}/qualifying.json"
            qual_data = await fetch_json(client, qual_url)
            pole_driver = None
            pole_time = None
            if qual_data:
                qual_races = qual_data.get("MRData", {}).get("RaceTable", {}).get("Races", [])
                if qual_races:
                    qual_results = qual_races[0].get("QualifyingResults", [])
                    if qual_results:
                        pole = qual_results[0]
                        pole_driver = pole.get("Driver", {}).get("code")
                        pole_time = pole.get("Q3") or pole.get("Q2") or pole.get("Q1")

            stmt = pg_insert(models.RaceResult).values(
                race_id=race.id,
                winner_code=winner,
                p2_code=p2,
                p3_code=p3,
                pole_driver_code=pole_driver,
                pole_time=pole_time,
                fastest_lap_driver_code=fastest_lap_driver,
                fastest_lap_time=fastest_lap_time,
                total_laps=int(total_laps) if total_laps else None,
                safety_car_deployments=0,
            ).on_conflict_do_update(
                index_elements=["race_id"],
                set_={
                    "winner_code": winner,
                    "p2_code": p2,
                    "p3_code": p3,
                    "pole_driver_code": pole_driver,
                    "pole_time": pole_time,
                    "fastest_lap_driver_code": fastest_lap_driver,
                    "fastest_lap_time": fastest_lap_time,
                    "total_laps": int(total_laps) if total_laps else None,
                }
            )
            await session.execute(stmt)
            await session.commit()
            total += 1

    # 2026: seed Australia and China if available
    logger.info("=== Seeding race results (2026) ===")
    for round_num in [1, 2]:  # Australia, China
        race_result = await session.execute(
            select(models.Race).where(models.Race.year == 2026, models.Race.round == round_num)
        )
        race = race_result.scalar_one_or_none()
        if not race:
            continue
        results_url = f"{JOLPICA_BASE}/2026/{round_num}/results.json"
        results_data = await fetch_json(client, results_url)
        if not results_data:
            logger.info(f"  2026 R{round_num}: no Jolpica data yet, skipping")
            continue
        results = results_data.get("MRData", {}).get("RaceTable", {}).get("Races", [])
        if not results:
            continue
        race_results_list = results[0].get("Results", [])
        if len(race_results_list) < 3:
            continue
        winner = race_results_list[0].get("Driver", {}).get("code")
        p2 = race_results_list[1].get("Driver", {}).get("code")
        p3 = race_results_list[2].get("Driver", {}).get("code")
        total_laps = race_results_list[0].get("laps")
        fastest_lap_driver = None
        fastest_lap_time = None
        for rr in race_results_list:
            fl = rr.get("FastestLap", {})
            if fl.get("rank") == "1":
                fastest_lap_driver = rr.get("Driver", {}).get("code")
                fastest_lap_time = fl.get("Time", {}).get("time")
                break
        qual_url = f"{JOLPICA_BASE}/2026/{round_num}/qualifying.json"
        qual_data = await fetch_json(client, qual_url)
        pole_driver = None
        pole_time = None
        if qual_data:
            qual_races = qual_data.get("MRData", {}).get("RaceTable", {}).get("Races", [])
            if qual_races:
                qr = qual_races[0].get("QualifyingResults", [])
                if qr:
                    pole_driver = qr[0].get("Driver", {}).get("code")
                    pole_time = qr[0].get("Q3") or qr[0].get("Q2") or qr[0].get("Q1")
        stmt = pg_insert(models.RaceResult).values(
            race_id=race.id,
            winner_code=winner, p2_code=p2, p3_code=p3,
            pole_driver_code=pole_driver, pole_time=pole_time,
            fastest_lap_driver_code=fastest_lap_driver, fastest_lap_time=fastest_lap_time,
            total_laps=int(total_laps) if total_laps else None,
            safety_car_deployments=0,
        ).on_conflict_do_update(
            index_elements=["race_id"],
            set_={
                "winner_code": winner, "p2_code": p2, "p3_code": p3,
                "pole_driver_code": pole_driver, "pole_time": pole_time,
                "fastest_lap_driver_code": fastest_lap_driver,
                "fastest_lap_time": fastest_lap_time,
                "total_laps": int(total_laps) if total_laps else None,
            }
        )
        await session.execute(stmt)
        await session.commit()
        total += 1
        logger.info(f"  2026 R{round_num}: winner={winner}")

    logger.info(f"Race results total: {total} (failures: {failures})")
    return total


async def seed_weather(session, client):
    logger.info("=== Seeding weather (2023, 2024, 2026) ===")
    total = 0
    for year in [2023, 2024, 2026]:
        sessions_url = f"{OPENF1_BASE}/sessions?year={year}&session_name=Race"
        sessions_data = await fetch_json(client, sessions_url)
        if not sessions_data:
            logger.warning(f"No OpenF1 sessions for {year}")
            continue

        # Build mapping: country_name/location -> session_key
        openf1_sessions = {}
        for s in sessions_data:
            key = (s.get("country_name", "").lower(), s.get("location", "").lower())
            openf1_sessions[key] = s.get("session_key")

        races_result = await session.execute(
            select(models.Race, models.Circuit)
            .join(models.Circuit, models.Race.circuit_id == models.Circuit.id)
            .where(models.Race.year == year)
            .order_by(models.Race.round)
        )
        rows = races_result.all()
        for race, circuit in rows:
            # Find matching session
            session_key = None
            country_lower = circuit.country.lower()
            city_lower = circuit.city.lower()
            for (cn, loc), sk in openf1_sessions.items():
                if country_lower in cn or cn in country_lower or city_lower in loc or loc in city_lower:
                    session_key = sk
                    break
            if not session_key:
                logger.warning(f"  No OpenF1 session for {year} {circuit.short_name}")
                continue

            weather_url = f"{OPENF1_BASE}/weather?session_key={session_key}"
            weather_data = await fetch_json(client, weather_url)
            if not weather_data:
                logger.warning(f"  No weather for {year} {circuit.short_name}")
                continue
            if not weather_data:
                continue

            air_temps = [w["air_temperature"] for w in weather_data if w.get("air_temperature") is not None]
            track_temps = [w["track_temperature"] for w in weather_data if w.get("track_temperature") is not None]
            humidities = [w["humidity"] for w in weather_data if w.get("humidity") is not None]
            wind_speeds = [w["wind_speed"] for w in weather_data if w.get("wind_speed") is not None]
            rainfalls = [w.get("rainfall", 0) for w in weather_data]

            condition = "Wet" if any(r and r > 0 for r in rainfalls) else "Clear"

            stmt = pg_insert(models.Weather).values(
                race_id=race.id,
                session="Race",
                air_temp_celsius=round(sum(air_temps) / len(air_temps), 1) if air_temps else None,
                track_temp_celsius=round(sum(track_temps) / len(track_temps), 1) if track_temps else None,
                humidity_percent=int(sum(humidities) / len(humidities)) if humidities else None,
                wind_speed_kmh=round(sum(wind_speeds) / len(wind_speeds), 1) if wind_speeds else None,
                condition=condition,
            ).on_conflict_do_update(
                index_elements=["race_id", "session"],
                set_={
                    "air_temp_celsius": round(sum(air_temps) / len(air_temps), 1) if air_temps else None,
                    "track_temp_celsius": round(sum(track_temps) / len(track_temps), 1) if track_temps else None,
                    "humidity_percent": int(sum(humidities) / len(humidities)) if humidities else None,
                    "wind_speed_kmh": round(sum(wind_speeds) / len(wind_speeds), 1) if wind_speeds else None,
                    "condition": condition,
                }
            )
            await session.execute(stmt)
            await session.commit()
            total += 1
            logger.info(f"  Weather: {year} {circuit.short_name} ({condition})")

    logger.info(f"Weather total: {total}")
    return total


async def seed_tyre_strategies(session, client):
    logger.info("=== Seeding tyre strategies (2023, 2024, 2026) ===")
    total = 0
    for year in [2023, 2024, 2026]:
        sessions_url = f"{OPENF1_BASE}/sessions?year={year}&session_name=Race"
        sessions_data = await fetch_json(client, sessions_url)
        if not sessions_data:
            logger.warning(f"No OpenF1 sessions for {year}")
            continue

        openf1_sessions = {}
        for s in sessions_data:
            key = (s.get("country_name", "").lower(), s.get("location", "").lower())
            openf1_sessions[key] = s.get("session_key")

        races_result = await session.execute(
            select(models.Race, models.Circuit)
            .join(models.Circuit, models.Race.circuit_id == models.Circuit.id)
            .where(models.Race.year == year)
            .order_by(models.Race.round)
        )
        rows = races_result.all()
        for race, circuit in rows:
            session_key = None
            country_lower = circuit.country.lower()
            city_lower = circuit.city.lower()
            for (cn, loc), sk in openf1_sessions.items():
                if country_lower in cn or cn in country_lower or city_lower in loc or loc in city_lower:
                    session_key = sk
                    break
            if not session_key:
                logger.warning(f"  No OpenF1 session for {year} {circuit.short_name}")
                continue

            # Get drivers to map number -> code
            drivers_url = f"{OPENF1_BASE}/drivers?session_key={session_key}"
            drivers_data = await fetch_json(client, drivers_url)
            driver_map = {}
            if drivers_data:
                for d in drivers_data:
                    num = d.get("driver_number")
                    code = d.get("name_acronym")
                    if num and code:
                        driver_map[num] = code

            stints_url = f"{OPENF1_BASE}/stints?session_key={session_key}"
            stints_data = await fetch_json(client, stints_url)
            if not stints_data:
                logger.warning(f"  No stints for {year} {circuit.short_name}")
                continue

            race_stints = 0
            for stint in stints_data:
                driver_num = stint.get("driver_number")
                driver_code = driver_map.get(driver_num)
                if not driver_code:
                    continue
                compound = stint.get("compound", "UNKNOWN")
                if compound:
                    compound = compound.upper()
                lap_start = stint.get("lap_start") or 1
                lap_end = stint.get("lap_end") or lap_start
                laps = max(1, lap_end - lap_start + 1)
                stint_num = stint.get("stint_number", 1)
                stmt = pg_insert(models.TyreStrategy).values(
                    race_id=race.id,
                    driver_code=driver_code,
                    stint_number=stint_num,
                    compound=compound,
                    laps=laps,
                ).on_conflict_do_update(
                    index_elements=["race_id", "driver_code", "stint_number"],
                    set_={"compound": compound, "laps": laps}
                )
                await session.execute(stmt)
                race_stints += 1
            await session.commit()
            total += race_stints
            logger.info(f"  Tyres: {year} {circuit.short_name}: {race_stints} stints")

    logger.info(f"Tyre strategy total: {total} stints")
    return total


async def seed_tyre_strategies_2022(session):
    """Seed 2022 tyre strategies using FastF1 locally."""
    logger.info("=== Seeding tyre strategies (2022 via FastF1) ===")
    try:
        import fastf1
        fastf1.Cache.enable_cache("./cache/fastf1")
    except Exception as e:
        logger.warning(f"FastF1 not available for 2022 tyres: {e}")
        return 0

    races_result = await session.execute(
        select(models.Race, models.Circuit)
        .join(models.Circuit, models.Race.circuit_id == models.Circuit.id)
        .where(models.Race.year == 2022)
        .order_by(models.Race.round)
    )
    rows = races_result.all()
    total = 0
    for race, circuit in rows:
        try:
            logger.info(f"  FastF1 loading 2022 {circuit.short_name}...")
            f1_session = fastf1.get_session(2022, circuit.fastf1_key, "R")
            f1_session.load(laps=True, telemetry=False, weather=False, messages=False)
            laps = f1_session.laps
            if laps is None or laps.empty:
                continue

            race_stints = 0
            for driver_code in laps["Driver"].unique():
                driver_laps = laps[laps["Driver"] == driver_code]
                for stint_num in driver_laps["Stint"].unique():
                    stint_laps = driver_laps[driver_laps["Stint"] == stint_num]
                    if stint_laps.empty:
                        continue
                    compound = stint_laps.iloc[0].get("Compound", "UNKNOWN")
                    if compound and hasattr(compound, "upper"):
                        compound = compound.upper()
                    elif not compound:
                        compound = "UNKNOWN"
                    lap_count = len(stint_laps)
                    stmt = pg_insert(models.TyreStrategy).values(
                        race_id=race.id,
                        driver_code=str(driver_code)[:3],
                        stint_number=int(stint_num),
                        compound=str(compound)[:20],
                        laps=lap_count,
                    ).on_conflict_do_update(
                        index_elements=["race_id", "driver_code", "stint_number"],
                        set_={"compound": str(compound)[:20], "laps": lap_count}
                    )
                    await session.execute(stmt)
                    race_stints += 1
            await session.commit()
            total += race_stints
            logger.info(f"  2022 {circuit.short_name}: {race_stints} stints")
        except Exception as e:
            logger.warning(f"  FastF1 2022 {circuit.short_name} failed: {e}")
            continue

    logger.info(f"2022 tyre strategies total: {total} stints")
    return total


# ===========================================================================
# MAIN
# ===========================================================================

async def main():
    logger.info("Starting F1 seed script")
    ok = await test_connection()
    if not ok:
        logger.error("Database connection failed. Check DATABASE_URL in .env")
        return

    async with AsyncSessionLocal() as session:
        async with httpx.AsyncClient(verify=False) as client:
            circuits = await seed_circuits(session)
            teams = await seed_teams(session)
            drivers = await seed_drivers(session)
            races = await seed_races(session, client)
            race_results = await seed_race_results(session, client)
            weather = await seed_weather(session, client)
            tyres = await seed_tyre_strategies(session, client)
            tyres_2022 = await seed_tyre_strategies_2022(session)

    logger.info("=" * 60)
    logger.info("SEED COMPLETE")
    logger.info(f"  Circuits:       {circuits}")
    logger.info(f"  Teams:          {teams}")
    logger.info(f"  Drivers:        {drivers}")
    logger.info(f"  Races:          {races}")
    logger.info(f"  Race results:   {race_results}")
    logger.info(f"  Weather:        {weather}")
    logger.info(f"  Tyre stints:    {tyres + tyres_2022}")
    logger.info("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
