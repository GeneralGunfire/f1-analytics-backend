# F1 Analytics Platform — Data Architecture

**Document date:** 2026-03-20
**Scope:** Data population, connection, and serving strategy for seasons 2022–2026
**Status:** Reference document — verified against live APIs

---

## Executive Summary

Jolpica (the Ergast replacement, confirmed operational) covers all structured race data from 2022 to present day including results, qualifying, standings, and calendar. OpenF1 covers granular telemetry data (weather per minute, tyre stints, lap timing) but only from 2023 onward. The correct approach is to seed the Supabase database using a one-time Python script that calls Jolpica for structural data and OpenF1 for granular data, then run a lightweight post-race script after each 2026 race weekend. FastAPI on Render free tier must use the Supabase session-mode pooler (port 5432) with a pool of 2–3 connections maximum to stay within the 60-connection hard limit on the free tier.

---

## API Research Results

### Test 1: OpenF1 Sessions — `GET https://api.openf1.org/v1/sessions?year=2024`

**HTTP Status:** 200 OK (SSL certificate requires `-k` flag in curl; works normally in Python requests)

**Response summary:**
- 123 sessions total for 2024
- Session types: `Practice` (63), `Qualifying` (30), `Race` (30)
- Includes Sprint Qualifying and Sprint Race in the "Qualifying" and "Race" counts respectively

**Fields per session object:**
```json
{
  "session_key": 9472,
  "session_type": "Race",
  "session_name": "Race",
  "date_start": "2024-03-02T15:00:00+00:00",
  "date_end": "2024-03-02T17:00:00+00:00",
  "meeting_key": 1229,
  "circuit_key": 63,
  "circuit_short_name": "Sakhir",
  "country_key": 36,
  "country_code": "BRN",
  "country_name": "Bahrain",
  "location": "Sakhir",
  "gmt_offset": "03:00:00",
  "year": 2024
}
```

**Critical finding:** OpenF1 sessions endpoint is metadata only. It does NOT contain race results or finishing positions. Race results must come from Jolpica.

**Year coverage:**
- 2022: 0 sessions (404 Not Found)
- 2023: 118 sessions (first session: 2023-02-23 pre-season test)
- 2024: 123 sessions
- 2026: 126 sessions (already populated through end of calendar)

---

### Test 2: OpenF1 Drivers — `GET https://api.openf1.org/v1/drivers?session_key=latest`

**HTTP Status:** 200 OK

**Session key resolved to:** 11245 (2026 season — confirmed by Gabriel Bortoleto/Audi and Isack Hadjar/Red Bull in response)

**Fields per driver object:**
```json
{
  "meeting_key": 1280,
  "session_key": 11245,
  "driver_number": 1,
  "broadcast_name": "L NORRIS",
  "full_name": "Lando NORRIS",
  "name_acronym": "NOR",
  "team_name": "McLaren",
  "team_colour": "F47600",
  "first_name": "Lando",
  "last_name": "Norris",
  "headshot_url": "https://media.formula1.com/...",
  "country_code": null
}
```

**Note:** `country_code` returns null for all drivers in this response. Use Jolpica for nationality data. Headshot URLs link to formula1.com CDN — not guaranteed stable. Team colour hex codes are accurate and useful for UI.

---

### Test 3: Jolpica Full-Season Results — `GET https://api.jolpi.ca/ergast/f1/2024/results/?limit=5`

**HTTP Status:** 200 OK

**Response structure:**
- `MRData.total`: 479 (total individual driver-race result rows across all 24 races)
- Default limit is 30, maximum is 100
- Data is paginated — need `?limit=100&offset=0`, `?limit=100&offset=100`, etc. to get all results
- To get a complete season: 479 results ÷ 100 per page = 5 requests minimum

**Key insight:** When fetching full-season results, the response groups by race. With `limit=5`, you get 1 race with 5 driver results. To efficiently seed a season, fetch per-race: `/ergast/f1/2024/{round}/results/` (24 requests for 2024) or use large limit on the season endpoint.

---

### Test 4: Jolpica 2026 Race Calendar — `GET https://api.jolpi.ca/ergast/f1/2026/races/`

**HTTP Status:** 200 OK

**22 races confirmed in calendar:**

| Round | Race Name | Date |
|-------|-----------|------|
| 1 | Australian Grand Prix | 2026-03-08 |
| 2 | Chinese Grand Prix | 2026-03-15 |
| 3 | Japanese Grand Prix | 2026-03-29 |
| 4 | Miami Grand Prix | 2026-05-03 |
| 5 | Canadian Grand Prix | 2026-05-24 |
| 6 | Monaco Grand Prix | 2026-06-07 |
| 7 | Barcelona Grand Prix | 2026-06-14 |
| 8 | Austrian Grand Prix | 2026-06-28 |
| 9 | British Grand Prix | 2026-07-05 |
| 10 | Belgian Grand Prix | 2026-07-19 |
| 11 | Hungarian Grand Prix | 2026-07-26 |
| 12 | Dutch Grand Prix | 2026-08-23 |
| 13 | Italian Grand Prix | 2026-09-06 |
| 14 | Spanish Grand Prix | 2026-09-13 |
| 15 | Azerbaijan Grand Prix | 2026-09-26 |
| 16 | Singapore Grand Prix | 2026-10-11 |
| 17 | United States Grand Prix | 2026-10-25 |
| 18 | Mexico City Grand Prix | 2026-11-01 |
| 19 | Brazilian Grand Prix | 2026-11-08 |
| 20 | Las Vegas Grand Prix | 2026-11-22 |
| 21 | Qatar Grand Prix | 2026-11-29 |
| 22 | Abu Dhabi Grand Prix | 2026-12-06 |

**Completed as of 2026-03-20:** Rounds 1 (Australia) and 2 (China).

**Circuit fields available:** `circuitId`, `circuitName`, `url`, `Location.lat`, `Location.long`, `Location.locality`, `Location.country`

---

### Test 5: Jolpica Qualifying — `GET https://api.jolpi.ca/ergast/f1/2024/qualifying/`

**HTTP Status:** 200 OK

**Qualifying fields per driver:**
```json
{
  "position": "1",
  "number": "1",
  "Q1": "1:30.031",
  "Q2": "1:29.374",
  "Q3": "1:29.179",
  "Driver": { "code": "VER", "givenName": "Max", ... },
  "Constructor": { "name": "Red Bull Racing", ... }
}
```

**Total:** 479 qualifying result rows for 2024. Drivers eliminated in Q1 have empty Q2/Q3. Drivers eliminated in Q2 have empty Q3. This is complete qualifying data.

---

### Test 6: Original Ergast — `GET http://ergast.com/api/f1/2024/results.json`

**HTTP Status:** 301 redirect → 404

**Result: ERGAST IS DOWN.** The domain redirects but returns 404. The root domain `http://ergast.com/` also returns 404 after redirect. Ergast shut down as planned at the end of 2024/start of 2025. Do not use it. Use Jolpica exclusively.

---

### Test 7: OpenF1 Weather — `GET https://api.openf1.org/v1/weather?session_key=9472`

Note: session_key 9472 = 2024 Bahrain Race (tested against this; 9158 = 2023 Singapore Race)

**HTTP Status:** 200 OK

**Response:** 157 weather records for one race session (one record per minute approximately)

**Fields per record:**
```json
{
  "date": "2024-03-02T14:03:56",
  "session_key": 9472,
  "meeting_key": 1229,
  "wind_direction": 187,
  "air_temperature": 18.9,
  "humidity": 46.0,
  "pressure": 1007.7,
  "rainfall": 0,
  "wind_speed": 0.9,
  "track_temperature": 26.5
}
```

**Date range:** 2024-03-02T14:03 to 2024-03-02T16:39 (covers full race duration)

**Rainfall note:** Integer 0 or 1 (binary, not mm). For "did it rain?" this works; for intensity you need external sources.

**Aggregation strategy for storage:** Store MIN/MAX/AVG of air_temperature, track_temperature, humidity, wind_speed per session. Also store `max(rainfall)` to flag "wet race". Do not store all 157 rows per session in Supabase — aggregate to 1 row per session.

---

### Test 8: OpenF1 Stints — `GET https://api.openf1.org/v1/stints?session_key=9472`

**HTTP Status:** 200 OK

**Response:** 63 stint records for 2024 Bahrain Race (20 drivers × ~3 stints average)

**Fields per record:**
```json
{
  "meeting_key": 1229,
  "session_key": 9472,
  "stint_number": 1,
  "driver_number": 1,
  "lap_start": 1,
  "lap_end": 17,
  "compound": "SOFT",
  "tyre_age_at_start": 3
}
```

**Compound values observed:** `SOFT`, `MEDIUM`, `HARD`, `INTERMEDIATE`, `WET`

**This is exactly what's needed for tyre strategy visualization.** Each row = one stint for one driver. Joining with driver table gives the full picture.

---

## Recommended Data Population Strategy

### Source Assignment by Data Type

| Data Type | Primary Source | Notes |
|-----------|---------------|-------|
| Race calendar (all seasons) | Jolpica `/ergast/f1/{year}/races/` | Circuit info included |
| Race results (finishing positions, points, times) | Jolpica `/ergast/f1/{year}/{round}/results/` | Full grid |
| Qualifying results (Q1/Q2/Q3 times) | Jolpica `/ergast/f1/{year}/{round}/qualifying/` | All 20 drivers |
| Driver list + nationality | Jolpica `/ergast/f1/{year}/drivers/` | Stable reference data |
| Constructor list | Jolpica `/ergast/f1/{year}/constructors/` | 10 per season |
| Driver standings (end of season) | Jolpica `/ergast/f1/{year}/driverStandings/` | Snapshot per round |
| Constructor standings | Jolpica `/ergast/f1/{year}/constructorStandings/` | Snapshot per round |
| Pit stop data | Jolpica `/ergast/f1/{year}/{round}/pitstops/` | Lap + duration |
| Tyre stints (compound per stint) | OpenF1 `/v1/stints?session_key={key}` | 2023+ only |
| Weather per session | OpenF1 `/v1/weather?session_key={key}` | 2023+ only; aggregate to 1 row |
| Lap telemetry (speed/throttle/brake) | FastF1 `session.laps` | Serve on-demand, never store |
| Driver headshots | OpenF1 `/v1/drivers?session_key=latest` or F1 CDN | Fragile — store URL not image |
| Team colours | OpenF1 `/v1/drivers` | `team_colour` hex field |

### Historical Seed Script (2022–2025)

Run once, locally, before deploying. Not on Render — Render's ephemeral disk and 512MB RAM make this unsuitable for FastF1's memory footprint.

**Execution order:**

**Step 1: Seed reference tables** (circuits, drivers, constructors)
```
for year in 2022 2023 2024 2025:
    GET /ergast/f1/{year}/circuits/
    GET /ergast/f1/{year}/drivers/
    GET /ergast/f1/{year}/constructors/
    Upsert to Supabase (circuits, drivers, constructors tables)
```
Rate: 3 requests × 4 years = 12 requests. Well within 500/hour limit.

**Step 2: Seed race calendars**
```
for year in 2022 2023 2024 2025:
    GET /ergast/f1/{year}/races/
    Insert to races table with circuit_id foreign key
```
Rate: 4 requests total.

**Step 3: Seed race results** (largest operation)
```
for year in 2022 2023 2024 2025:
    for round in 1..N:
        GET /ergast/f1/{year}/{round}/results/
        GET /ergast/f1/{year}/{round}/qualifying/
        GET /ergast/f1/{year}/{round}/pitstops/
        sleep(0.25)  # stay under 4 req/sec burst limit
```
Rate: 2022(22) + 2023(22) + 2024(24) + 2025(24) = 92 rounds × 3 endpoints = 276 requests.
At 0.25s between requests: ~70 seconds total. Well within 500/hour limit.

**Step 4: Seed OpenF1 data (2023–2025 only)**
```
for year in 2023 2024 2025:
    sessions = GET /v1/sessions?year={year}  # filter to Race sessions only
    for each race_session:
        weather_records = GET /v1/weather?session_key={session_key}
        aggregate to: min_air_temp, max_air_temp, avg_air_temp,
                      min_track_temp, max_track_temp, avg_humidity,
                      max_rainfall (0 or 1), avg_wind_speed
        stints = GET /v1/stints?session_key={session_key}
        Upsert weather_summary and stints to Supabase
        sleep(0.3)
```
Rate: ~70 race sessions × 2 = 140 requests. Safe.

**Step 5: No FastF1 in seeding script**
FastF1 is for on-demand telemetry serving only. It is not used in the seed script. Historical results come from Jolpica; stints come from OpenF1.

### 2022 Tyre Data Gap

OpenF1 does not have 2022 data. For 2022 tyre stints, use FastF1:
```python
session = fastf1.get_session(2022, round_number, 'R')
session.load(laps=True, telemetry=False, weather=False)
stints = session.laps[['Driver','Stint','Compound','TyreLife']].drop_duplicates(subset=['Driver','Stint'])
```
This works but requires FastF1's local disk cache (run locally, not on Render). Extract and insert to Supabase during the initial seed. 22 sessions × ~5 seconds per session = ~110 seconds total.

### 2026 Season (Ongoing)

As of 2026-03-20, Rounds 1 (Australia) and 2 (China) have results in both Jolpica and OpenF1.

The calendar (all 22 races) is already in Jolpica. Insert all 22 race rows to the `races` table at season start with `status = 'scheduled'`. After each race weekend, run the post-race update script (see Update Workflow section).

---

## Recommended Connection Strategy

### Decision: Supabase Session Pooler, Port 5432

**Connection string format:**
```
postgresql+asyncpg://postgres.xhnxuupzbzvehxuchvau:{PASSWORD}@aws-0-eu-north-1.pooler.supabase.com:5432/postgres
```

**Why session pooler (not direct, not transaction mode):**

| Option | Port | Verdict | Reason |
|--------|------|---------|--------|
| Direct connection | 5432 on `db.xhnxuupzbzvehxuchvau.supabase.co` | Avoid | Each server restart creates new connection; fine for persistent servers but wastes connections when Render spins down |
| Transaction pooler | 6543 on pooler host | Avoid | Does not support prepared statements; SQLAlchemy async uses prepared statements by default |
| Session pooler | 5432 on pooler host | **Use this** | Supports prepared statements, designed for IPv4 networks, Supavisor manages connection lifecycle |

**Why not transaction mode:** SQLAlchemy 2.0 async with asyncpg uses prepared statements by default. Disabling them globally (`statement_cache_size=0` in asyncpg connect args) is possible but degrades performance and adds complexity.

**Supabase free tier connection limits:**
- Direct PostgreSQL: 60 max connections
- Supavisor pooler clients: 200 max clients
- The pooler multiplexes those 200 client connections into the 60 direct connections

**Pool configuration for Render free tier + Supabase free tier:**

```python
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker

DATABASE_URL = (
    "postgresql+asyncpg://"
    "postgres.xhnxuupzbzvehxuchvau:{PASSWORD}"
    "@aws-0-eu-north-1.pooler.supabase.com:5432/postgres"
)

engine = create_async_engine(
    DATABASE_URL,
    pool_size=3,          # Max connections this instance holds open
    max_overflow=2,       # Burst allowance (total max = 5)
    pool_timeout=10,      # Seconds to wait for a connection before error
    pool_recycle=1800,    # Recycle connections after 30 minutes
    pool_pre_ping=True,   # Verify connection alive before using it
)

AsyncSessionLocal = sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)
```

**Why pool_size=3:** Render free tier spins down after 15 minutes of inactivity, killing all connections anyway. When it wakes, it opens fresh connections. The Supabase free limit is 60 direct connections but the pooler handles multiplexing. 3 is safe for a single Render instance and leaves room for local dev, migrations, and Supabase Studio to connect simultaneously.

**Dependency injection pattern:**
```python
from contextlib import asynccontextmanager
from typing import AsyncGenerator

async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
```

**Required packages:**
```
asyncpg==0.31.0
SQLAlchemy==2.0.48
```

---

## Data Responsibility Map

| Data Type | Source | When to Fetch | Cache Strategy (React Query) |
|-----------|--------|---------------|------------------------------|
| Circuits (static reference) | Jolpica → Supabase (seed) | Seed once; never re-fetch | `staleTime: Infinity, gcTime: Infinity` — prefetch on app load |
| Drivers (per season) | Jolpica → Supabase (seed) | Seed once per season | `staleTime: 24h` — refresh if driver transfer occurs |
| Constructors (per season) | Jolpica → Supabase (seed) | Seed once per season | `staleTime: 24h` |
| Race calendar | Jolpica → Supabase (seed) | Seed at season start | `staleTime: 7 days` — race dates rarely change |
| Race results (completed) | Jolpica → Supabase (seed + post-race update) | Read from DB; never call Jolpica from API | `staleTime: Infinity` once race is marked completed |
| Race results (upcoming) | N/A | N/A | `staleTime: 0` — poll after expected race end time |
| Qualifying results | Jolpica → Supabase (seed + post-race update) | Read from DB | `staleTime: Infinity` once qualifying is done |
| Driver standings | Jolpica → Supabase (post-race update) | Re-fetch after each race | `staleTime: 1h` during active race weekend |
| Constructor standings | Jolpica → Supabase (post-race update) | Re-fetch after each race | `staleTime: 1h` during active race weekend |
| Pit stops | Jolpica → Supabase (seed + post-race update) | Read from DB | `staleTime: Infinity` once race is complete |
| Tyre stints (2023+) | OpenF1 → Supabase (seed + post-race update) | Read from DB | `staleTime: Infinity` once race is complete |
| Tyre stints (2022) | FastF1 → Supabase (seed, local only) | Read from DB | `staleTime: Infinity` |
| Weather summary | OpenF1 → Supabase (aggregated, seed + post-race) | Read from DB | `staleTime: Infinity` once race is complete |
| Lap telemetry (speed/brake/throttle) | FastF1 → FastAPI (on-demand) | Never stored; served from FastF1 cache | `staleTime: 5min, gcTime: 10min` — expensive to refetch |
| Fastest lap per session | FastF1 → FastAPI (on-demand) or Jolpica | On-demand or seed from Jolpica results | `staleTime: Infinity` once race complete |
| Driver headshot URLs | OpenF1 `/v1/drivers` → Supabase | Seed per season; update if URL breaks | `staleTime: 24h` |
| Team colour hex codes | OpenF1 `/v1/drivers` → Supabase | Seed per season | `staleTime: 24h` |

---

## Update Workflow for 2026 Season

After each race weekend (Sunday evening or Monday morning), run the following. Total time: under 5 minutes.

### Step 1: Run the post-race update script

```bash
python scripts/update_race.py --year 2026 --round <N>
```

This script does the following in order:

1. **Fetch race results from Jolpica**
   `GET /ergast/f1/2026/{N}/results/`
   Insert/upsert to `race_results` table.

2. **Fetch qualifying results from Jolpica**
   `GET /ergast/f1/2026/{N}/qualifying/`
   Insert/upsert to `qualifying_results` table.

3. **Fetch pit stops from Jolpica**
   `GET /ergast/f1/2026/{N}/pitstops/`
   Insert/upsert to `pit_stops` table.

4. **Find the race session_key from OpenF1**
   `GET /v1/sessions?year=2026` → filter `session_type=Race` for the correct circuit.

5. **Fetch and aggregate weather from OpenF1**
   `GET /v1/weather?session_key={key}`
   Aggregate to 1 row: min/max/avg of each metric.
   Upsert to `session_weather` table.

6. **Fetch tyre stints from OpenF1**
   `GET /v1/stints?session_key={key}`
   Upsert to `tyre_stints` table.

7. **Update race status in calendar**
   `UPDATE races SET status = 'completed' WHERE year = 2026 AND round = {N}`

8. **Fetch updated driver standings from Jolpica**
   `GET /ergast/f1/2026/{N}/driverStandings/`
   Upsert to `driver_standings` table.

9. **Fetch updated constructor standings from Jolpica**
   `GET /ergast/f1/2026/{N}/constructorStandings/`
   Upsert to `constructor_standings` table.

**Total API calls:** ~9 requests per race weekend. Zero risk of hitting rate limits.

### What does NOT need manual action

- FastAPI on Render automatically serves the updated data — no redeploy needed.
- React frontend automatically invalidates queries when race status changes to "completed".
- FastF1 cache on Render is ephemeral — the service will re-fetch telemetry from F1 live timing on next request (uses FastF1's built-in caching, but this cache is lost on spin-down).

### What needs manual action (edge cases)

- **Driver transfer mid-season** (rare): Update `drivers` table manually or re-run the driver seed for that season.
- **Race cancellation**: Update `races SET status = 'cancelled'` manually.
- **Sprint race weekend**: Add an additional step to fetch sprint results from `/ergast/f1/2026/{N}/sprint/`.

### How long it takes

- Script runtime: 15–30 seconds (9 API calls with 0.25s sleep between)
- Verification: 2 minutes (spot-check one race result in the UI)
- Total effort per race weekend: under 5 minutes

---

## Implementation Order

### Phase 1: Database schema and connectivity (build first)

1. Create Supabase schema: `circuits`, `drivers`, `constructors`, `races`, `race_results`, `qualifying_results`, `pit_stops`, `tyre_stints`, `session_weather`, `driver_standings`, `constructor_standings`
2. Add `asyncpg` and `SQLAlchemy==2.0.x` to `requirements.txt` (they are not in the current requirements)
3. Create `app/database.py` with the async engine and session factory described in the Connection Strategy section
4. Add `DATABASE_URL` to environment variables (Render env vars + local `.env`)
5. Write and run Alembic migrations to create tables

**Rationale:** Nothing else works until the DB is connected.

### Phase 2: Historical seed script (run locally)

6. Write `scripts/seed_historical.py` — calls Jolpica for 2022–2025 calendar, drivers, constructors, results, qualifying, pit stops
7. Run the script locally with a `.env` pointing at the production Supabase project
8. Write `scripts/seed_openf1.py` — calls OpenF1 for 2023–2025 tyre stints and weather summaries
9. Write `scripts/seed_fastf1_2022.py` — uses FastF1 locally to extract 2022 tyre stints
10. Run all three scripts. Verify row counts match expected totals (92 race weekends × 20 drivers = ~1840 result rows for 2022–2025)

**Rationale:** Seed before writing any API routes so you can test real data immediately.

### Phase 3: FastAPI read routes

11. Implement `/api/calendar/{year}` — returns races for a season with status (scheduled/completed)
12. Implement `/api/race/{year}/{round}/results` — joins race_results with drivers and constructors
13. Implement `/api/race/{year}/{round}/qualifying` — qualifying results
14. Implement `/api/race/{year}/{round}/stints` — tyre strategy data
15. Implement `/api/race/{year}/{round}/weather` — aggregated weather
16. Implement `/api/standings/{year}/drivers` and `/api/standings/{year}/constructors`

**Rationale:** All data is already in Supabase; routes are thin DB queries.

### Phase 4: FastF1 telemetry routes (on-demand, existing backend)

17. Keep existing FastF1 routes for lap telemetry (`/telemetry`, `/sessions`)
18. Ensure `fastf1.Cache.enable_cache('./cache/fastf1')` points to local disk path (acceptable for development; ephemeral on Render but acceptable since telemetry re-fetches are just slow, not broken)
19. Consider adding a `/api/session/{year}/{round}/fastest-lap` route that uses FastF1

**Rationale:** These are separate from the DB-backed routes and require no schema changes.

### Phase 5: Post-race update tooling

20. Write `scripts/update_race.py --year {Y} --round {N}` using the workflow above
21. Test on Round 3 (Japan, 2026-03-29) after it completes

### Phase 6: React frontend caching

22. Add `@tanstack/react-query@5.x` to the frontend
23. Configure `QueryClient` default options:
    ```typescript
    const queryClient = new QueryClient({
      defaultOptions: {
        queries: {
          staleTime: 5 * 60 * 1000,   // 5 minutes default
          gcTime: 10 * 60 * 1000,      // 10 minutes garbage collection
          retry: 2,
        },
      },
    });
    ```
24. Override `staleTime: Infinity` for static queries (circuits, completed race results, historical seasons)
25. Prefetch current season calendar on app mount

---

## Appendix: Raw API Responses

### A1: OpenF1 Sessions 2024 (first 2 records)

```json
[
  {
    "session_key": 9462,
    "session_type": "Practice",
    "session_name": "Day 1",
    "date_start": "2024-02-21T07:00:00+00:00",
    "date_end": "2024-02-21T16:00:00+00:00",
    "meeting_key": 1228,
    "circuit_key": 63,
    "circuit_short_name": "Sakhir",
    "country_key": 36,
    "country_code": "BRN",
    "country_name": "Bahrain",
    "location": "Sakhir",
    "gmt_offset": "03:00:00",
    "year": 2024
  },
  {
    "session_key": 9472,
    "session_type": "Race",
    "session_name": "Race",
    "date_start": "2024-03-02T15:00:00+00:00",
    "date_end": "2024-03-02T17:00:00+00:00",
    "meeting_key": 1229,
    "circuit_key": 63,
    "circuit_short_name": "Sakhir",
    "country_key": 36,
    "country_code": "BRN",
    "country_name": "Bahrain",
    "location": "Sakhir",
    "gmt_offset": "03:00:00",
    "year": 2024
  }
]
```

Session count breakdown: Practice 63, Qualifying 30, Race 30 = 123 total for 2024.

---

### A2: OpenF1 Drivers (latest session = 11245, 2026)

```json
{
  "meeting_key": 1280,
  "session_key": 11245,
  "driver_number": 1,
  "broadcast_name": "L NORRIS",
  "full_name": "Lando NORRIS",
  "name_acronym": "NOR",
  "team_name": "McLaren",
  "team_colour": "F47600",
  "first_name": "Lando",
  "last_name": "Norris",
  "headshot_url": "https://media.formula1.com/d_driver_fallback_image.png/content/dam/fom-website/drivers/L/LANNOR01_Lando_Norris/lannor01.png.transform/1col/image.png",
  "country_code": null
}
```

Notable 2026 driver lineup confirmed: Bortoleto (Audi #5), Hadjar (Red Bull #6), Antonelli (Mercedes #12), Norris (McLaren #1), Verstappen (Red Bull #3), Perez (Cadillac #11).

---

### A3: Jolpica Full-Season Results 2024 (limit=5)

```
MRData.total: 479
MRData.limit: 5
MRData.offset: 0
Races in page: 1 (Bahrain Grand Prix, Round 1)
Results in page: 5 drivers
```

---

### A4: Jolpica 2026 Race Calendar (full)

22 races confirmed. First 3:
```json
[
  {"round": "1", "raceName": "Australian Grand Prix", "date": "2026-03-08",
   "Circuit": {"circuitName": "Albert Park Grand Prix Circuit", "Location": {"locality": "Melbourne", "country": "Australia"}}},
  {"round": "2", "raceName": "Chinese Grand Prix", "date": "2026-03-15",
   "Circuit": {"circuitName": "Shanghai International Circuit"}},
  {"round": "3", "raceName": "Japanese Grand Prix", "date": "2026-03-29",
   "Circuit": {"circuitName": "Suzuka Circuit"}}
]
```

---

### A5: Jolpica Qualifying 2024 Round 1

```json
{
  "position": "1",
  "number": "1",
  "Q1": "1:30.031",
  "Q2": "1:29.374",
  "Q3": "1:29.179",
  "Driver": {"driverId": "max_verstappen", "code": "VER"},
  "Constructor": {"constructorId": "red_bull", "name": "Red Bull Racing"}
}
```

Total: 479 qualifying rows for 2024 (20 drivers × 24 rounds, minus cancelled sessions).

---

### A6: Ergast Status

```
GET http://ergast.com/api/f1/2024/results.json
HTTP 301 -> HTTP 404

GET http://ergast.com/
HTTP 301 -> HTTP 404
```

Ergast is confirmed dead. Do not reference it in any code.

---

### A7: OpenF1 Weather (session_key=9472, 2024 Bahrain Race)

```json
{
  "date": "2024-03-02T14:03:56",
  "session_key": 9472,
  "meeting_key": 1229,
  "wind_direction": 187,
  "air_temperature": 18.9,
  "humidity": 46.0,
  "pressure": 1007.7,
  "rainfall": 0,
  "wind_speed": 0.9,
  "track_temperature": 26.5
}
```

157 records for this session (one per minute, ~2.5 hours). Store aggregated, not raw.

---

### A8: OpenF1 Stints (session_key=9472, 2024 Bahrain Race)

```json
{
  "meeting_key": 1229,
  "session_key": 9472,
  "stint_number": 1,
  "driver_number": 1,
  "lap_start": 1,
  "lap_end": 17,
  "compound": "SOFT",
  "tyre_age_at_start": 3
}
```

63 stints total for the race (20 drivers). This is the complete tyre strategy picture — every compound change, every stint length.

---

## FastF1 Capabilities Reference

**Version tested:** 3.8.1 (current as of 2026-03-20)

**What FastF1 provides:**
- `fastf1.get_event_schedule(year)` — returns DataFrame of all rounds with circuit, date, event format
- `fastf1.get_session(year, round, 'R'/'Q'/'FP1'/'FP2'/'FP3'/'S'/'SQ')` — session object
- `session.load(laps=True, telemetry=True, weather=True)` — loads data from F1 live timing or cache
- `session.results` — DataFrame: position, driver, team, time, status (DNF etc), fastest lap
- `session.laps` — DataFrame: every lap for every driver including `Compound`, `TyreLife`, `Stint`, sector times, `PitInTime`, `PitOutTime`
- `session.weather_data` — same minute-by-minute data as OpenF1 weather endpoint
- `lap.get_telemetry()` — returns speed, throttle, brake, DRS, RPM per data point (~10Hz)

**What FastF1 does NOT provide:**
- Historical standings or championship points
- Qualifying session times (available from `session.results` for qualifying session type)
- Jolpica-style structured endpoints — it's a data analysis library, not an API wrapper

**Data sources FastF1 uses internally:**
- F1 live timing (signalr stream for live data, historical replay for past sessions)
- Jolpica for structural data (replaces Ergast since early 2025)

**Bulk loading suitability:**
FastF1 is NOT suitable for bulk historical seeding in a production deployment:
- Each session load with telemetry: ~200–500MB peak memory (512MB Render limit = OOM)
- First load of a session (no cache): 30–120 seconds network time
- Cache files are large (~50–200MB per session with telemetry) — Render's ephemeral disk loses them on spin-down

**Correct use pattern:** Use FastF1 only for on-demand telemetry requests. Enable local disk cache during development. Accept that the Render deployment will re-fetch from F1 live timing on first request after spin-down (slow first load, fine thereafter during a session).

---

## Supabase Free Tier Limits (Verified 2026)

| Limit | Value |
|-------|-------|
| Database size | 500 MB |
| Direct PostgreSQL connections | 60 |
| Supavisor pooler clients | 200 |
| Project auto-pause | After 1 week of inactivity (manually unpause) |
| Storage | 1 GB |
| Egress | 5 GB/month |

**Auto-pause warning:** Supabase pauses free projects after 1 week of inactivity. During active development this is unlikely to trigger, but if you take a break, unpause the project from the Supabase dashboard before running the backend.

---

## Ergast Shutdown Timeline (Confirmed)

- **End of 2024:** Ergast stopped updating. Final data: 2024 season.
- **Early 2025:** ergast.com domain went offline. Returns 404 after redirect.
- **Replacement:** Jolpica (`api.jolpi.ca/ergast/f1/`) — drop-in compatible, same URL structure, maintained by volunteers, ~$45/month hosting costs funded by donations.
- **Jolpica rate limits:** 4 requests/second burst, 500 requests/hour sustained. Limits will decrease in the future as token auth is implemented.
- **Jolpica data coverage:** 1950 to present (same as Ergast historical coverage).
- **OpenF1 data coverage:** 2023 pre-season testing onward. No data for 2022 or earlier.

---

## Sources

- Jolpica F1 API GitHub: https://github.com/jolpica/jolpica-f1
- Jolpica rate limits doc: https://github.com/jolpica/jolpica-f1/blob/main/docs/rate_limits.md
- FastF1 documentation: https://docs.fastf1.dev/
- FastF1 Jolpica integration: https://docs.fastf1.dev/api_reference/jolpica.html
- Ergast deprecation discussion: https://github.com/theOehrly/Fast-F1/discussions/445
- OpenF1 API: https://openf1.org/
- OpenF1 docs: https://openf1.org/docs/
- Supabase compute and connection limits: https://supabase.com/docs/guides/platform/compute-and-disk
- Supabase connection guide: https://supabase.com/docs/guides/database/connecting-to-postgres
- Render free tier docs: https://render.com/docs/free
- TanStack Query v5 prefetching: https://tanstack.com/query/v5/docs/framework/react/guides/prefetching
- SQLAlchemy async docs: https://docs.sqlalchemy.org/en/20/orm/extensions/asyncio.html
