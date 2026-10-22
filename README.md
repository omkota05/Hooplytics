# Hooplytics

A local NBA analytics app with real NBA data. It lets you search any player, chart their game-by-game
stats against a custom line, check head-to-head history against any opponent, and look at upcoming
games. Data comes from ESPN's public JSON API, is stored in PostgreSQL by a FastAPI sync service, and
is served to a Next.js frontend.

> Hooplytics only shows **historical results**. It does not make predictions, offer betting lines or
> injury reports, or give betting advice. The Picks page is a historical trend explorer until a real,
> validated ML model exists (see [ML roadmap](#ml-roadmap)).

## Quick start (macOS)

Prerequisites:

| Tool | Version | Install |
| --- | --- | --- |
| Python | 3.11+ | `brew install python@3.12` |
| Node.js | 20+ | `brew install node` |
| Docker Desktop | any recent | <https://www.docker.com/products/docker-desktop/> |

```bash
make setup   # checks prerequisites, generates .env files with a random DB password, installs deps
make dev     # starts PostgreSQL, runs migrations, starts API + frontend
```

Then open <http://localhost:3000>. API docs are at <http://localhost:8000/docs>.

On the first start with an empty database, the API runs its first sync in the background. The current
season becomes usable within a few minutes. After that, historical seasons download in resumable
chunks; three seasons take about 20 minutes and about 3,000 requests. Watch progress in the sidebar
indicator, or run `make status`. To run the history download in the foreground instead:

```bash
make db && make migrate && make backfill
```

If a prerequisite is missing, the scripts stop with an install hint. If Docker Desktop is installed but
not running, `make dev` launches it and waits.

## Commands

| Command | What it does |
| --- | --- |
| `make setup` | One-time setup (env files, `backend/.venv`, `npm install`) |
| `make dev` | Start everything; Ctrl-C stops the API and frontend |
| `make db` / `make db-stop` | Start or stop only PostgreSQL (data persists in a Docker volume) |
| `make migrate` | Apply Alembic migrations |
| `make migration m="..."` | Autogenerate a new migration |
| `make sync` | Incremental sync now (new games, box scores, schedule, rosters) |
| `make backfill` | Download historical seasons (safe to interrupt and re-run) |
| `make status` | Data freshness and per-season coverage |
| `make test` | Backend tests (needs `make db`; uses a separate `hooplytics_test` database) |
| `make lint` / `make typecheck` / `make build` | Ruff + ESLint, TypeScript, Next.js production build |
| `make check` | Lint, type check, and test |
| `make export-dataset out=x.csv` | Export the point-in-time ML feature table |
| `make db-reset` | Delete all local data (asks for confirmation) |

The backend CLI has more options: `cd backend && .venv/bin/python -m app.cli --help`
(for example `backfill --season 2024 --max-games 100` or `backfill --retry-failed`).

## Configuration

`make setup` writes three git-ignored files from the committed `*.example` templates:

* `.env`: Postgres credentials for Docker Compose (random password, generated locally).
* `backend/.env`: `DATABASE_URL` and sync settings.
* `frontend/.env.local`: `NEXT_PUBLIC_API_URL` (default `http://localhost:8000`).

No API keys are needed. The ESPN endpoints are public.

| `backend/.env` | Default | Meaning |
| --- | --- | --- |
| `HISTORY_SEASONS` | `2` | Previous seasons to backfill, in addition to the current one |
| `SYNC_ON_STARTUP` | `true` | Run the background scheduler inside the API process |
| `SYNC_STALE_MINUTES` | `30` | On startup, sync right away if the last success is older than this |
| `SYNC_INTERVAL_MINUTES` | `30` | Incremental sync interval while the API runs |
| `AUTO_BACKFILL` | `true` | Download missing history between incremental syncs |
| `UPCOMING_DAYS` | `14` | How far ahead to keep the schedule fresh |
| `PROVIDER_MIN_REQUEST_INTERVAL_SECONDS` | `0.35` | Minimum delay between provider requests |
| `PROVIDER_TIMEOUT_SECONDS` / `PROVIDER_MAX_RETRIES` | `20` / `4` | HTTP timeout and retries (backoff, honors `Retry-After`) |

Postgres listens on host port **5433** (`POSTGRES_PORT` in `.env`) to avoid clashing with a local
Postgres on 5432.

## Data source

**Provider: ESPN public site API** (`site.api.espn.com/apis/site/v2/sports/basketball/nba`). It is
unofficial and undocumented, and it needs no key. Endpoints used: `/teams`, `/teams/{id}/roster`,
`/teams/{id}/schedule`, `/scoreboard?dates=YYYYMMDD`, and `/summary?event={id}` (box scores).

Why not NBA.com / `nba_api`? `stats.nba.com` and `cdn.nba.com` refused or timed out every request from
the development network (Akamai bot protection blocked even plain browser-like requests), and they are
also unofficial. The provider sits behind a `DataProvider` protocol
(`backend/app/ingestion/providers/base.py`), so another source can be added without touching storage,
analytics, or the UI.

Important caveats:

* **Terms of use.** ESPN data is for personal, non-commercial use. Check ESPN's terms before deploying
  or sharing this app publicly. The API can change or rate-limit without notice; Hooplytics throttles
  itself to about 3 requests per second.
* **Stable IDs.** ESPN player, team, and game IDs are the primary keys, so re-syncs never create
  duplicates.
* **Known gaps, verified.** 8 completed 2025-26 playoff games (for example ESPN event `401869391`, NY @
  ATL on 2026-04-25) are listed as final on ESPN's scoreboard, but their box-score endpoint returns HTTP
  404 on both ESPN hosts. Those games have no player stats in Hooplytics. They are retried with backoff
  (15 minutes, doubling each time, 8 attempts), and `make status` shows them as `boxscores_pending`.
  Retry manually with `backfill --retry-failed`.
* **Not available for free, so not included:** injury reports, betting odds and lines, and advanced or
  tracking stats (defensive matchups and similar). The matchup page says so instead of guessing.
* Live scores update on each incremental sync (every 30 minutes by default, or press **Sync now**). The
  app is not a live play-by-play tracker.
* Season labels use the ending year internally: `season=2027` means 2026-27. Regular season, play-in,
  and playoffs are stored. Preseason and All-Star games are ignored.

## How sync works

```
ESPN API → ingestion/providers/espn (HTTP + normalization)
        → sync/service (orchestration) → sync/writer (idempotent upserts)
        → PostgreSQL → repositories → services/analytics → FastAPI routes → Next.js
```

* **Incremental** (`make sync`, the scheduler, or the **Sync now** button) covers:
  * Scoreboard days since the last successful sync, plus one day of overlap, up to 21 days back. This
    catches up automatically after the Mac was off.
  * Days that still have unfinished games more than 4 hours after tip-off.
  * The upcoming window every 3 hours, and full current-season team schedules every 3 days, which
    catches reschedules and postponements.
  * Rosters every 12 hours and teams weekly.
  * Box scores for any completed game that doesn't have one yet.
* **Backfill** downloads each season's schedule once, then box scores newest-first. Each box score
  commits on its own, so an interrupted run resumes where it stopped.
* **Correctness.** Every write is an `INSERT … ON CONFLICT` upsert. `player_game_stats` has a unique
  `(player_id, game_id)` constraint. Box-score corrections replace the old rows. A score change on a
  final game queues its box score for a re-fetch. Postponed and canceled games are stored with their
  status and never counted. Incomplete box scores are not marked as synced.
* **Safety.** A PostgreSQL advisory lock allows only one sync at a time across the API and CLI. Each
  run is recorded in `sync_runs`, and the frontend shows the last successful sync.
* **Bad responses.** If the provider returns fewer than 30 teams or a near-empty roster set, the
  previous data is kept. If the provider is down (repeated 5xx or timeouts), the scheduler pauses for
  10 minutes.

## Analytics rules

* Stat categories: PTS, REB, AST, 3PM, STL, BLK, TOV, P+R, P+A, R+A, PRA, and S+B. Combined
  categories are computed from per-game components in one place (`app/analytics/categories.py`).
* Windows: last N games, a whole season, a date range, or all synced games. Filters can add an
  opponent and a season type (all, regular season, postseason).
* **Did-not-play (DNP) games are excluded.** A game counts only if the player logged minutes.
* **Over, under, and push are counted separately.** Over% + Under% + Push% = 100%, and all three use
  the same denominator: the number of games shown. The over rate excluding pushes is reported
  separately.
* Distribution stats include mean, median, sample standard deviation, min, max, and count.
* Samples under 5 games are labeled as small. Head-to-head views show the count next to every rate.

## Project layout

```
backend/
  app/
    api/routes/      FastAPI routers (players, games, stats, sync)
    services/        Use cases that assemble API responses
    repositories/    SQL queries
    analytics/       Pure functions: categories, windows, line evaluation
    ingestion/       HTTP client + provider adapters (ESPN)
    sync/            Orchestration, idempotent writer, scheduler
    models/          SQLAlchemy models
    schemas/         Pydantic API contracts
    ml/              Point-in-time dataset builder + predictor interface (no model yet)
    cli.py           Typer CLI
  alembic/           Migrations
  tests/             pytest (synthetic fixtures only)
frontend/src/
  app/               Next.js App Router pages (dashboard, players, matchups, picks)
  components/        Charts, analysis panels, search, layout, shadcn/ui primitives
  lib/               API client, types, hooks, formatters
scripts/             setup.sh, dev.sh, shared shell helpers
```

Main API endpoints (all under `/api`; full schema at `/docs`):
`GET /players/search?q=`, `GET /players`, `GET /players/{id}`, `/players/{id}/season-averages`,
`/players/{id}/game-logs`, `/players/{id}/stat-analysis`, `/players/{id}/matchup-comparison`,
`GET /games/upcoming`, `/games/recent`, `/games/top-performers`, `/games/{id}`, `GET /teams`,
`GET /stats/categories`, `GET /explorer/trends`, `GET /sync/status`, `POST /sync/run`.

## Tests

```bash
make db && make test
```

The tests cover:

* Combined-stat math, over/under/push classification, and window and opponent filtering.
* DNP exclusion and ESPN payload normalization.
* Idempotent upserts, duplicate and corrected box scores, status transitions, skipped preseason games,
  and backfill resume and retry backoff.
* API endpoints and the leakage-safe ML features.

All fixtures are **synthetic**: fictional teams like "Testville Testers", fictional players, season
2099. They are never real NBA data. The DB tests run against `hooplytics_test`, which the Postgres
container creates on first start, and refuse to run against your main database.

## ML roadmap

The groundwork is in place, but there is deliberately no model yet:

* `app/ml/dataset.py` builds one row per player-game with **point-in-time** features. Rolling averages
  and rest days use only games before tip-off. Targets cover every stat category.
  `make export-dataset out=games.csv` writes the table; Parquet needs
  `pip install -r backend/requirements-ml.txt`.
* `app/ml/prediction.py` defines the `StatPredictor` protocol (projection plus line probability) that a
  scikit-learn or XGBoost model would implement.
* The Picks page shows historical hit rates only. It says "ML predictions coming later" rather than
  showing invented picks.

Next steps for ML: train/validation splits by date (never random), a calibrated per-category model,
backtests against the stored history, and a prediction API that reports its own validation metrics.

## Unfinished / possible next work

- [ ] ESPN box scores for the 8 completed playoff games listed above (provider-side gap; retry with
      `backfill --retry-failed`).
- [ ] Live in-game scores between syncs (would need a faster polling mode while games are in progress).
- [ ] A second data provider for redundancy (the `DataProvider` protocol is ready for one).
- [ ] Frontend unit or end-to-end tests. The UI has been checked by hand in the browser, and the
      TypeScript type check and production build pass, but there are no automated UI tests.
- [ ] ML models (see roadmap). Odds and injury data would need a paid or licensed source.
