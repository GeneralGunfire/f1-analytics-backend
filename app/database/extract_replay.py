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

def _deduplicate_track_points(xs: np.ndarray, ys: np.ndarray, min_dist_m: float = 5.0) -> tuple:
    """
    Remove near-duplicate consecutive points (stationary car, pre-race grid wait).
    Keeps a point only if it is >= min_dist_m from the previously kept point.
    Uses Euclidean distance in FastF1's Cartesian coordinate space (metres).
    Returns filtered (xs, ys) arrays.
    """
    if len(xs) == 0:
        return xs, ys
    keep_x = [xs[0]]
    keep_y = [ys[0]]
    for x, y in zip(xs[1:], ys[1:]):
        dx = x - keep_x[-1]
        dy = y - keep_y[-1]
        if (dx * dx + dy * dy) >= min_dist_m * min_dist_m:
            keep_x.append(x)
            keep_y.append(y)
    return np.array(keep_x), np.array(keep_y)


def extract_track_map(db: Session, circuit_id: str, pos_data: dict, force: bool = False) -> bool:
    """Persist track outline from first driver's position data.

    Uses deduplication to strip stationary pre-race grid rows (the root cause of
    the first ~2500/5000 points being identical in the original extraction).
    """
    existing = db.execute(
        select(TrackMap).where(TrackMap.circuit_id == circuit_id).limit(1)
    ).scalar_one_or_none()
    if existing and not force:
        logger.info(f"  Track map already present for {circuit_id}")
        return True

    if existing and force:
        db.execute(
            TrackMap.__table__.delete().where(TrackMap.circuit_id == circuit_id)
        )
        db.commit()
        logger.info(f"  Deleted existing track map for {circuit_id} (force re-extract)")

    try:
        sample_df = None
        for drv_num, drv_df in pos_data.items():
            if drv_df is None or drv_df.empty:
                continue
            if "X" not in drv_df.columns or "Y" not in drv_df.columns:
                continue
            # Use ALL data (not just head(5000)) so the full lap is captured
            clean = drv_df[["X", "Y"]].dropna()
            if len(clean) >= 100:
                sample_df = clean
                break

        if sample_df is None:
            logger.warning("  No usable position data for track map")
            return False

        xs_raw = sample_df["X"].values.astype(float)
        ys_raw = sample_df["Y"].values.astype(float)

        # Remove near-duplicate points (stationary grid wait, pit lane standing)
        xs, ys = _deduplicate_track_points(xs_raw, ys_raw, min_dist_m=5.0)
        logger.info(f"  Track map: {len(xs_raw)} raw → {len(xs)} after dedup (5m threshold)")

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
    For each driver: merge pos_data (X/Y) with car_data (Speed, nGear, DRS),
    filter by lap window, resample to 250ms, store as RaceFrame rows.
    Also extracts position_in_race from laps data.
    """
    total_frames = 0

    # Load car_data for speed + gear (Speed km/h, nGear 1-8, DRS 0/10/12/14)
    try:
        car_data = sess.car_data  # dict: {driver_num_str: DataFrame}
    except Exception:
        car_data = {}

    # Build lap window lookup: { driver_number_str: { lap_num: (start_td, end_td, code, position) } }
    lap_windows: dict[str, dict[int, tuple]] = {}
    for _, row in sess.laps.iterrows():
        drv_num = str(row.get("DriverNumber", ""))
        drv_code = str(row.get("Driver", ""))[:3]
        lap_num_raw = row.get("LapNumber")
        lap_start = row.get("LapStartTime")
        lap_end = row.get("Time")
        position = row.get("Position", None)
        if pd.isna(lap_num_raw) or pd.isna(lap_start) or pd.isna(lap_end):
            continue
        pos_int = int(position) if position is not None and not pd.isna(position) else None
        if drv_num not in lap_windows:
            lap_windows[drv_num] = {}
        lap_windows[drv_num][int(lap_num_raw)] = (lap_start, lap_end, drv_code, pos_int)

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
                lap_start, lap_end, drv_code, position_in_race = windows[lap_num]

                # SessionTime is nanoseconds — convert to Timedelta for comparison
                session_time_td = pd.to_timedelta(drv_df["SessionTime"].values, unit="ns")
                mask = (session_time_td >= lap_start) & (session_time_td <= lap_end)
                lap_df = drv_df[mask].copy()
                if lap_df.empty:
                    continue

                # Merge car_data (Speed, nGear, DRS) on nearest SessionTime
                drv_car = car_data.get(str(drv_num))
                if drv_car is not None and not drv_car.empty and "SessionTime" in drv_car.columns:
                    try:
                        # Both use nanosecond SessionTime — convert to Timedelta, merge_asof
                        car_td = pd.to_timedelta(drv_car["SessionTime"].values, unit="ns")
                        drv_car_indexed = drv_car.copy()
                        drv_car_indexed.index = car_td
                        lap_df.index = pd.to_timedelta(lap_df["SessionTime"].values, unit="ns")

                        # Keep only useful car_data columns
                        car_cols = [c for c in ["Speed", "nGear", "DRS"] if c in drv_car.columns]
                        car_sub = drv_car_indexed[car_cols].sort_index()
                        lap_df_sorted = lap_df.sort_index()

                        merged = pd.merge_asof(
                            lap_df_sorted,
                            car_sub,
                            left_index=True,
                            right_index=True,
                            tolerance=pd.Timedelta("200ms"),
                            direction="nearest",
                        )
                        lap_df = merged
                    except Exception as merge_err:
                        logger.debug(f"    car_data merge failed for {drv_num} lap {lap_num}: {merge_err}")
                        # Fall back to pos_data only — speed/gear will be None
                        lap_df.index = pd.to_timedelta(lap_df["SessionTime"].values, unit="ns")
                else:
                    lap_df.index = pd.to_timedelta(lap_df["SessionTime"].values, unit="ns")

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

                    # Speed from car_data (km/h)
                    speed_raw = row_pos.get("Speed", None)
                    speed_val = round(float(speed_raw), 1) if speed_raw is not None and not pd.isna(speed_raw) else None

                    # Gear from car_data nGear (1-8)
                    gear_raw = row_pos.get("nGear", None)
                    gear_val = int(gear_raw) if gear_raw is not None and not pd.isna(gear_raw) else None

                    # DRS from car_data (0=closed, 10/12/14=open)
                    drs_raw = row_pos.get("DRS", 0)
                    drs_open = bool(drs_raw is not None and not pd.isna(drs_raw) and int(drs_raw) >= 10)

                    status_val = row_pos.get("Status", "") if has_status else ""
                    lap_batch.append(RaceFrame(
                        replay_session_id=replay_id,
                        lap=lap_num,
                        timestamp_ms=int(ts_td.total_seconds() * 1000),
                        driver_code=drv_code,
                        x=round(float(x_raw) - x_center, 1),
                        y=round(float(y_raw) - y_center, 1),
                        speed=speed_val,
                        gear=gear_val,
                        drs=drs_open,
                        is_in_pit=str(status_val).strip() in ("PitLane", "Pit"),
                        position_in_race=position_in_race,
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
    force: bool = False,
) -> bool:
    logger.info(f"\n{'='*60}")
    logger.info(f"Processing: {year} {race_name} ({session_name})")
    logger.info(f"{'='*60}")

    existing = db.execute(
        select(RaceReplaySession).where(RaceReplaySession.race_id == race_id)
    ).scalar_one_or_none()

    if existing and existing.status == "complete" and not force:
        logger.info("  Already extracted — skipping (use --force to re-extract)")
        return True

    if existing and force:
        logger.info(f"  Force re-extract: deleting existing frames for replay_session {existing.id}")
        db.execute(
            RaceFrame.__table__.delete().where(RaceFrame.replay_session_id == existing.id)
        )
        db.execute(
            RaceEvent.__table__.delete().where(RaceEvent.replay_session_id == existing.id)
        )
        db.commit()
        rs = existing
        rs.status = "pending"
        rs.frame_count = 0
    elif existing:
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

    # Track map — force=True so re-extraction regenerates with fixed dedup logic
    extract_track_map(db, circuit_id, pos_data, force=True)

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
    parser.add_argument("--force", action="store_true", help="Re-extract even if already complete")
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
                    force=args.force,
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
