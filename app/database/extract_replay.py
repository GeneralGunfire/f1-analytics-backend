"""
Race Replay Extraction Script
------------------------------
Extracts position data, events, and track maps from FastF1 sessions
and stores them in Supabase for the replay API.

Usage:
    python app/database/extract_replay.py                        # all races
    python app/database/extract_replay.py --year 2024            # one year
    python app/database/extract_replay.py --year 2024 --race bahrain --session R

FastF1 pos_data structure (v3.x):
  - pos_data is a plain dict: { driver_number_str: Telemetry DataFrame }
  - Keys: driver number strings e.g. '1', '44', '63'
  - DataFrame index: RangeIndex (NOT a time index)
  - DataFrame columns: Date, Status, X, Y, Z, Source, Time, SessionTime
  - SessionTime: nanosecond integers (time from session start)
  - Laps DataFrame: LapStartTime, Time columns are pandas Timedelta objects
"""

import argparse
import logging
import os
import time
from datetime import datetime, date

import fastf1
import numpy as np
import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker, Session

from app.database.models import (
    Race, TrackMap, RaceReplaySession, RaceFrame, RaceEvent
)

load_dotenv()
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)

fastf1.Cache.enable_cache("./cache/fastf1")

# ---------------------------------------------------------------------------
# Database connection (sync — psycopg2)
# ---------------------------------------------------------------------------

DATABASE_URL = os.getenv("DATABASE_URL", "")
if DATABASE_URL.startswith("postgresql+asyncpg://"):
    SYNC_URL = DATABASE_URL.replace("postgresql+asyncpg://", "postgresql://", 1)
elif DATABASE_URL.startswith("postgres://"):
    SYNC_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)
else:
    SYNC_URL = DATABASE_URL

engine = create_engine(SYNC_URL, pool_size=2, max_overflow=1)
SessionLocal = sessionmaker(bind=engine)

RATE_LIMIT_WAIT = 65
BATCH_SIZE = 5000
RESAMPLE_INTERVAL = "250ms"


# ---------------------------------------------------------------------------
# FastF1 session loader with rate-limit retry
# ---------------------------------------------------------------------------

def _load_f1_session(year: int, fastf1_key: str, session_name: str):
    """Load FastF1 session with telemetry=True (required for pos_data)."""
    for attempt in range(2):
        try:
            sess = fastf1.get_session(year, fastf1_key, session_name)
            sess.load(telemetry=True, laps=True, weather=False, messages=True)
            return sess
        except Exception as e:
            err_str = str(e).lower()
            if ("rate limit" in err_str or "429" in err_str or "too many" in err_str):
                if attempt == 0:
                    logger.warning(f"Rate limit — retrying in {RATE_LIMIT_WAIT}s")
                    time.sleep(RATE_LIMIT_WAIT)
                    continue
            raise
    return None


# ---------------------------------------------------------------------------
# Track map
# ---------------------------------------------------------------------------

def extract_track_map(db: Session, circuit_id: str, pos_data: dict) -> bool:
    """Persist track outline from first driver's position data."""
    if db.execute(
        select(TrackMap).where(TrackMap.circuit_id == circuit_id).limit(1)
    ).scalar_one_or_none():
        logger.info(f"  Track map already present for {circuit_id}")
        return True

    try:
        sample_df = None
        for drv_num, drv_df in pos_data.items():
            if drv_df is None or drv_df.empty:
                continue
            if "X" not in drv_df.columns or "Y" not in drv_df.columns:
                continue
            clean = drv_df[["X", "Y"]].head(5000).dropna()
            if len(clean) >= 100:
                sample_df = clean
                break

        if sample_df is None:
            logger.warning("  No usable position data for track map")
            return False

        xs = sample_df["X"].values.astype(float)
        ys = sample_df["Y"].values.astype(float)
        x_c, y_c = xs.mean(), ys.mean()

        rows = [
            TrackMap(
                circuit_id=circuit_id,
                x=float(round(float(x) - x_c, 1)),
                y=float(round(float(y) - y_c, 1)),
                point_order=int(i),
                is_pit_lane=False,
                sector=None,
                is_drs_zone=False,
            )
            for i, (x, y) in enumerate(zip(xs, ys))
        ]
        db.bulk_save_objects(rows)
        db.commit()
        logger.info(f"  Track map: {len(rows)} points stored for {circuit_id}")
        return True

    except Exception as e:
        logger.error(f"  Track map failed: {e}")
        db.rollback()
        return False


# ---------------------------------------------------------------------------
# Event extraction
# ---------------------------------------------------------------------------

def _extract_events(db: Session, replay_id: int, sess) -> int:
    events: list[RaceEvent] = []

    # Race control messages
    try:
        msgs = sess.race_control_messages
        if msgs is not None and not msgs.empty:
            for _, msg in msgs.iterrows():
                try:
                    category = str(msg.get("Category", "")).strip()
                    flag = str(msg.get("Flag", "")).strip()
                    driver_code = None
                    racing_num = msg.get("RacingNumber", None)
                    if racing_num and not pd.isna(racing_num):
                        try:
                            info = sess.get_driver(int(racing_num))
                            if info:
                                driver_code = info.get("Abbreviation")
                        except Exception:
                            pass

                    ts_ms = None
                    try:
                        ts_ms = int(msg["Time"].total_seconds() * 1000)
                    except Exception:
                        pass

                    lap_num = None
                    try:
                        lap_num = int(msg["Lap"])
                    except Exception:
                        pass

                    if category == "SafetyCar":
                        etype, desc = "safety_car", str(msg.get("Message", "Safety car"))
                    elif category == "VirtualSafetyCar":
                        etype, desc = "vsc", str(msg.get("Message", "Virtual safety car"))
                    elif flag and flag not in ("", "None", "nan"):
                        etype, desc = "flag", f"{flag} flag"
                    elif category == "Drs":
                        etype, desc = "drs", str(msg.get("Message", "DRS"))
                    else:
                        etype, desc = "race_control", str(msg.get("Message", category))

                    events.append(RaceEvent(
                        replay_session_id=replay_id,
                        lap=lap_num, timestamp_ms=ts_ms,
                        event_type=etype, driver_code=driver_code,
                        description=desc[:500], x=None, y=None,
                    ))
                except Exception:
                    continue
    except Exception as e:
        logger.warning(f"  Race control messages failed: {e}")

    # Pit stops + personal bests
    try:
        laps = sess.laps
        if laps is not None and not laps.empty:
            for _, lap in laps[laps["PitInTime"].notna()].iterrows():
                try:
                    code = str(lap.get("Driver", ""))[:3]
                    lnum = int(lap["LapNumber"]) if not pd.isna(lap.get("LapNumber")) else None
                    ts = int(lap["PitInTime"].total_seconds() * 1000)
                    events.append(RaceEvent(
                        replay_session_id=replay_id, lap=lnum, timestamp_ms=ts,
                        event_type="pit_in", driver_code=code,
                        description=f"{code} pits in (lap {lnum})", x=None, y=None,
                    ))
                except Exception:
                    continue

            for _, lap in laps[laps["PitOutTime"].notna()].iterrows():
                try:
                    code = str(lap.get("Driver", ""))[:3]
                    lnum = int(lap["LapNumber"]) if not pd.isna(lap.get("LapNumber")) else None
                    ts = int(lap["PitOutTime"].total_seconds() * 1000)
                    events.append(RaceEvent(
                        replay_session_id=replay_id, lap=lnum, timestamp_ms=ts,
                        event_type="pit_out", driver_code=code,
                        description=f"{code} exits pits (lap {lnum})", x=None, y=None,
                    ))
                except Exception:
                    continue

            pb = laps[laps.get("IsPersonalBest", pd.Series(False, index=laps.index)) == True]  # noqa
            for _, lap in pb.iterrows():
                try:
                    code = str(lap.get("Driver", ""))[:3]
                    lnum = int(lap["LapNumber"]) if not pd.isna(lap.get("LapNumber")) else None
                    lap_time = str(lap.get("LapTime", "")) if not pd.isna(lap.get("LapTime")) else ""
                    ts = None
                    if not pd.isna(lap.get("LapStartTime")):
                        ts = int(lap["LapStartTime"].total_seconds() * 1000)
                    events.append(RaceEvent(
                        replay_session_id=replay_id, lap=lnum, timestamp_ms=ts,
                        event_type="fastest_lap", driver_code=code,
                        description=f"{code} personal best: {lap_time} (lap {lnum})",
                        x=None, y=None,
                    ))
                except Exception:
                    continue
    except Exception as e:
        logger.warning(f"  Lap event extraction failed: {e}")

    if events:
        db.bulk_save_objects(events)
        db.commit()
    return len(events)


# ---------------------------------------------------------------------------
# Position frame extraction (per-driver, vectorised)
# ---------------------------------------------------------------------------

def _extract_frames(
    db: Session,
    replay_id: int,
    sess,
    pos_data: dict,
    total_laps: int,
    x_center: float,
    y_center: float,
) -> int:
    """
    For each driver: convert SessionTime (ns) → Timedelta, filter by lap window,
    resample to 250ms, store as RaceFrame rows.
    """
    total_frames = 0

    # Build lap window lookup: { driver_number_str: { lap_num: (start_td, end_td, code) } }
    lap_windows: dict[str, dict[int, tuple]] = {}
    for _, row in sess.laps.iterrows():
        drv_num = str(row.get("DriverNumber", ""))
        drv_code = str(row.get("Driver", ""))[:3]
        lap_num_raw = row.get("LapNumber")
        lap_start = row.get("LapStartTime")
        lap_end = row.get("Time")
        if pd.isna(lap_num_raw) or pd.isna(lap_start) or pd.isna(lap_end):
            continue
        if drv_num not in lap_windows:
            lap_windows[drv_num] = {}
        lap_windows[drv_num][int(lap_num_raw)] = (lap_start, lap_end, drv_code)

    for lap_num in range(1, total_laps + 1):
        lap_batch: list[RaceFrame] = []

        for drv_num, drv_df in pos_data.items():
            try:
                if drv_df is None or drv_df.empty:
                    continue
                if "X" not in drv_df.columns or "Y" not in drv_df.columns:
                    continue

                windows = lap_windows.get(str(drv_num), {})
                if lap_num not in windows:
                    continue
                lap_start, lap_end, drv_code = windows[lap_num]

                # SessionTime is nanoseconds — convert to Timedelta for comparison
                session_time_td = pd.to_timedelta(drv_df["SessionTime"].values, unit="ns")
                mask = (session_time_td >= lap_start) & (session_time_td <= lap_end)
                lap_df = drv_df[mask].copy()
                if lap_df.empty:
                    continue

                # Set Timedelta index for resample
                lap_df.index = pd.to_timedelta(drv_df["SessionTime"].values[mask], unit="ns")
                lap_resampled = lap_df.resample(RESAMPLE_INTERVAL).last()
                lap_resampled = lap_resampled.dropna(subset=["X", "Y"])
                if lap_resampled.empty:
                    continue

                has_status = "Status" in lap_resampled.columns

                for ts_td, row_pos in lap_resampled.iterrows():
                    x_raw = row_pos["X"]
                    y_raw = row_pos["Y"]
                    if pd.isna(x_raw) or pd.isna(y_raw):
                        continue
                    speed_raw = row_pos.get("Speed", None)
                    status_val = row_pos.get("Status", "") if has_status else ""
                    lap_batch.append(RaceFrame(
                        replay_session_id=replay_id,
                        lap=lap_num,
                        timestamp_ms=int(ts_td.total_seconds() * 1000),
                        driver_code=drv_code,
                        x=round(float(x_raw) - x_center, 1),
                        y=round(float(y_raw) - y_center, 1),
                        speed=round(float(speed_raw), 1) if speed_raw is not None and not pd.isna(speed_raw) else None,
                        gear=None,
                        drs=False,
                        is_in_pit=str(status_val).strip() in ("PitLane", "Pit"),
                        position_in_race=None,
                    ))

            except Exception as e:
                logger.warning(f"    Driver {drv_num} lap {lap_num}: {e}")
                continue

        # Flush batch
        for i in range(0, len(lap_batch), BATCH_SIZE):
            db.bulk_save_objects(lap_batch[i:i + BATCH_SIZE])
        if lap_batch:
            db.commit()
        total_frames += len(lap_batch)
        pct = round(lap_num / total_laps * 100)
        logger.info(f"  Processing lap {lap_num}/{total_laps} — {total_frames} frames stored [{pct}%]")

    return total_frames


# ---------------------------------------------------------------------------
# Main race extraction
# ---------------------------------------------------------------------------

def extract_race(
    db: Session,
    race_id: int,
    year: int,
    fastf1_key: str,
    circuit_id: str,
    race_name: str,
    session_name: str = "Race",
) -> bool:
    logger.info(f"\n{'='*60}")
    logger.info(f"Processing: {year} {race_name} ({session_name})")
    logger.info(f"{'='*60}")

    # Skip if already done
    existing = db.execute(
        select(RaceReplaySession).where(RaceReplaySession.race_id == race_id)
    ).scalar_one_or_none()
    if existing and existing.status == "complete":
        logger.info("  Already extracted — skipping")
        return True

    if existing:
        rs = existing
        rs.status = "pending"
        rs.frame_count = 0
    else:
        rs = RaceReplaySession(race_id=race_id, status="pending", frame_count=0)
        db.add(rs)
    db.commit()
    db.refresh(rs)

    # Load FastF1
    try:
        sess = _load_f1_session(year, fastf1_key, session_name)
        if sess is None:
            raise RuntimeError("Session returned None")
        logger.info("  FastF1 session loaded")
    except Exception as e:
        logger.error(f"  Load failed: {e}")
        rs.status = "failed"
        db.commit()
        return False

    # Get pos_data
    try:
        pos_data = sess.pos_data
        if not pos_data:
            raise ValueError("pos_data is empty")
    except Exception as e:
        logger.error(f"  pos_data unavailable: {e}")
        rs.status = "failed"
        db.commit()
        return False

    # Total laps
    total_laps = 0
    try:
        total_laps = int(sess.laps["LapNumber"].max())
    except Exception:
        pass
    rs.total_laps = total_laps
    db.commit()

    logger.info(f"  Drivers: {len(pos_data)}  |  Laps: {total_laps}")

    # Global coordinate center
    all_x, all_y = [], []
    for drv_df in pos_data.values():
        if drv_df is not None and not drv_df.empty:
            if "X" in drv_df.columns:
                all_x.extend(drv_df["X"].dropna().values.tolist())
            if "Y" in drv_df.columns:
                all_y.extend(drv_df["Y"].dropna().values.tolist())

    if not all_x:
        logger.error("  No X/Y data found")
        rs.status = "failed"
        db.commit()
        return False

    x_center = float(np.mean(all_x))
    y_center = float(np.mean(all_y))

    # Track map
    extract_track_map(db, circuit_id, pos_data)

    # Position frames
    logger.info("  Extracting position frames...")
    total_frames = _extract_frames(db, rs.id, sess, pos_data, total_laps, x_center, y_center)

    # Events
    logger.info("  Extracting events...")
    event_count = _extract_events(db, rs.id, sess)
    logger.info(f"  Events stored: {event_count}")

    # Finalise
    rs.status = "complete"
    rs.frame_count = total_frames
    rs.extracted_at = datetime.utcnow()
    db.commit()

    logger.info(f"\n  DONE — {total_frames} frames | {event_count} events | {total_laps} laps")
    return True


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--year", type=int)
    parser.add_argument("--race", type=str)
    parser.add_argument("--session", type=str, default="R")
    args = parser.parse_args()

    session_map = {
        "R": "Race", "Q": "Qualifying",
        "FP1": "Practice 1", "FP2": "Practice 2", "FP3": "Practice 3", "S": "Sprint",
    }
    session_name = session_map.get(args.session.upper(), "Race")

    with SessionLocal() as db:
        today = date.today()
        query = select(Race).where(Race.date <= today)
        if args.year:
            query = query.where(Race.year == args.year)
        if args.race:
            query = query.where(Race.fastf1_key.ilike(f"%{args.race}%"))
        query = query.order_by(Race.year, Race.round)

        races = db.execute(query).scalars().all()
        if not races:
            logger.error("No races found")
            return

        logger.info(f"Found {len(races)} race(s)")
        success = failed = 0
        for race in races:
            try:
                ok = extract_race(
                    db=db, race_id=race.id, year=race.year,
                    fastf1_key=race.fastf1_key, circuit_id=race.circuit_id,
                    race_name=race.circuit_id, session_name=session_name,
                )
                if ok:
                    success += 1
                else:
                    failed += 1
            except Exception as e:
                logger.error(f"Race {race.id} error: {e}")
                failed += 1
            time.sleep(1)

        logger.info(f"\n{'='*60}")
        logger.info(f"DONE — Success: {success}  Failed: {failed}")
        logger.info(f"{'='*60}")


if __name__ == "__main__":
    main()
