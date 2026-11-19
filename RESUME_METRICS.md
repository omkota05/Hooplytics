# HoopsIQ (Hooplytics) — Resume Engineering & ML Metrics

**Generated:** 2026-11-18 (local)  
**Repository:** `Hooplytics` (NBA analytics platform; branded **HoopsIQ** in product/resume copy)  
**Measurement environment:** macOS, **Apple M2 Pro**, **16 GB RAM**, **arm64**, Python **3.13.1**, PostgreSQL **16-alpine** in Docker (`localhost:5433`), FastAPI via `TestClient` (in-process; no separate Uvicorn worker).

Temporary read-only benchmark scripts used for this report (safe to delete after review):

- `backend/scripts/_resume_metrics_data_scale.py`
- `backend/scripts/_resume_metrics_db_bench.py`
- `backend/scripts/_resume_metrics_api_bench.py`

---

## Executive summary

| Area | Verified headline |
|------|-------------------|
| **Data** | **75,216** player-game stat rows, **~2,840** final games with box scores across **3** seasons, **328k** prop-offer rows ingested (**56** import runs) |
| **Backend** | Player read APIs **~9–14 ms** p50 (30 runs); ML stat prediction **~743–760 ms** p50 (feature build + inference); recommendation feed **~36 s** cold → **&lt;1 ms** p50 warm with identical output |
| **ML (holdout)** | Chronological test split **8,197** player-games; ML beats composite rolling baselines on **pts/reb/ast** (e.g. pts MAE **4.62** vs **4.77**, **~3.0%** MAE reduction) |
| **Game winner** | Held-out test **373** games; production **logistic** Brier **0.192** vs home baseline **0.243** on same test set |
| **Calibration (honest)** | **No** archived historical *pregame* sportsbook lines → **real-market prop calibration not claimable** (see §5) |
| **Tests** | **177** backend pytest cases collected; **175 passed**, **1 skipped**, **0 failed** (excluding slow perf test); **10** frontend Vitest cases, all pass |

---

## 1. Data scale

**Method:** `SELECT COUNT(*)` / `COUNT(DISTINCT …)` on live DB (`make status` + `scripts/_resume_metrics_data_scale.py`). No writes.

| Metric | Measured value | Baseline / note | Method | Sample size | Confidence / limitations |
|--------|----------------|-----------------|--------|-------------|--------------------------|
| NBA teams | **30** (30 active) | — | `teams` table | 30 | **Verified** |
| Players in DB | **777** total; **764** with ≥1 box-score row; **525** `is_active` | Not full historical NBA universe—roster/backfill scope | `players`, `player_game_stats` | 777 | **Verified**; ESPN sync scope only |
| Seasons (games table) | **3** season keys (**2025–2027** ending years) | README default `HISTORY_SEASONS=2` + current | `games.season` | 3 | **Verified** |
| Games (all statuses) | **3,852** scheduled rows | — | `games` | 3,852 | **Verified** |
| Final games | **2,848** | — | `games.status='final'` | 2,848 | **Verified** |
| Final games w/ box score synced | **2,840** by season: **2024–25:** 1,321 · **2025–26:** 1,314 · **2026–27:** 205 | README ~3 seasons in ~20 min | `boxscore_synced_at IS NOT NULL` | 2,840 | **Verified** |
| Player-game stat rows | **75,216** (**61,511** played, not DNP) | — | `player_game_stats` | 75,216 | **Verified**; unique on `(player_id, game_id)` |
| Prop offer rows (current table) | **328,283** total; **11,792** active; **11,433** active+matched | Upserts ≠ unique logical props over time | `prop_offers` | 328,283 | **Verified** |
| Prop line hit cache rows | **22,749** | Descriptive vs *current* line | `prop_line_hit_cache` | 22,749 | **Verified**; not pregame archive |
| Prop import runs | **56** runs | — | `prop_import_runs` | 56 | **Verified** |
| Lifetime prop import volume | **3,981,527** offers seen; **965,125** upserted; **504,653** matched (summed run counters) | Can exceed current row count due to updates/deactivation | Sum over `prop_import_runs` | 56 runs | **Verified**; cumulative counters |
| Eligible Prop Finder rows *now* | **0** | **11,433** matched active rows exist but **0** pass upcoming-game filter at measurement time | `_eligible_prop_clauses()` + join `games` | 0 eligible | **Verified**; stale odds vs schedule—not missing DB scale |

**Ingestion / sync throughput (from `sync_runs`):**

| Kind | Runs | Box scores synced | Total wall time (sum) | Implied throughput |
|------|------|-------------------|----------------------|---------------------|
| `backfill` | 8 | 2,637 | **1,247 s** (~21 min) | **~2.1** box scores/s (aggregate) |
| `incremental` | 38 | 203 | **857 s** | Mixed schedule/box-score work; not a pure box-score benchmark |

Provider requests (successful/partial runs): **3,514** backfill + **1,773** incremental = **5,287** total (aligns with README order-of-magnitude **~3,000** for initial 3-season download).

**Prop import (successful runs, n=46):** avg **135 s** / run, avg **~20,981** upserts/run, avg **~82,189** offers seen/run.

---

## 2. Backend performance

**Method:** `fastapi.testclient.TestClient` against `app.main:app`, **30** timed requests after **1** warm-up (except recommendations—see below). Latency = client-side wall clock including DB + Python (single worker, local Postgres).

**Representative IDs:** `player_id=3147657` (213 game logs), `game_id=401910002` (scheduled).

| Endpoint / operation | Condition | avg (ms) | p50 (ms) | p95 (ms) | Baseline | Method | n | Limitations |
|---------------------|-----------|---------:|---------:|---------:|----------|--------|---|-------------|
| `GET /api/players/{id}` | Warm | 9.0 | 8.6 | 10.2 | — | HTTP 30× | 30 | In-process TestClient |
| `GET /api/players/{id}/game-logs?limit=82` | Warm | 9.4 | 9.2 | 11.6 | — | HTTP 30× | 30 | Returns 82 rows |
| `GET /api/players/{id}/stat-analysis?…&window=last_n&n=82` | Warm | 13.6 | 11.7 | 15.2 | — | HTTP 30× | 30 | One outlier **62 ms** |
| `GET /api/predictions/player-stat` (pts) | Warm | 760.2 | 742.9 | 801.8 | — | HTTP 30× | 30 | Dominated by per-player feature build |
| `GET /api/predictions/metrics` | Warm | 26.0 | 26.0 | 27.0 | — | HTTP 30× | 30 | Reads artifact JSON from disk |
| `predict_player_stat` (service) | Same session, 30× | 776.3 | 755.6 | 819.2 | — | Direct call | 30 | Confirms HTTP ≈ service |
| `generate_recommendations(days=3)` | **Cold** (cache cleared) | **36,392** | — | — | — | Service 1× | 1 | **596** props generated |
| `generate_recommendations(days=3)` | **Warm** (in-memory cache) | **1.38** | **0.87** | **2.97** | Cold path | Service 5× | 5 | `cache_output_equivalent: true` |
| `GET /api/prop-finder?limit=50` | Warm | **17.3** | **16.7** | **18.6** | — | HTTP 30× | 30 | **0 rows** (no eligible upcoming props) |

**Cache behavior (`recommendation_service`):** TTL **3600 s**; key includes model versions + last incremental sync time. Warm path speedup **~26,000×** vs cold in this run (36.4 s → 0.87 ms p50). Documented budget test: uncached 3-day feed **&lt;120 s** with **&gt;100** props (`tests/test_recommendation_performance.py`, marked `@pytest.mark.slow`).

**Equivalence:** Warm recommendation calls returned identical `player_props_generated` and `upcoming_games_scanned` vs first cold call.

**Not measured:** Separate Uvicorn multi-worker deployment, production TLS, geographic latency, or `/api/recommendations` HTTP (disabled when `enable_ml_recommendations=false`, default in `config.py`).

---

## 3. Database performance

**Method:** `EXPLAIN (ANALYZE, BUFFERS)` + 30× ORM timing for full player history (`scripts/_resume_metrics_db_bench.py`).

| Query pattern | Execution time (EXPLAIN) | Index usage | ORM p50 (30×) | Limitations |
|---------------|-------------------------|-------------|---------------|-------------|
| Player game log by `player_id`, `ORDER BY game_date DESC` | **0.233 ms** | **`ix_pgs_player_date`** bitmap index scan | **6.25 ms** (213 rows + joinedload game/opponent) | ORM includes ORM/join overhead |
| Season aggregate for one player | **0.139 ms** | Same index + filter on `season`, `did_not_play` | — | Cheap |
| Active player directory sort by season pts avg (LIMIT 50) | **49.6 ms** | Seq scan on **61,511** played rows + hash aggregate | — | Heavy; no materialized leaderboard |

**Before/after index improvements:** Not re-measured here (no second configuration on this machine). Schema includes intentional indexes on `player_game_stats` (`ix_pgs_player_date`, `ix_pgs_player_opponent_date`, etc.) from migrations `0001`–`0008`.

---

## 4. ML performance (player props & game winner)

### 4.1 Split protocol (leakage safety)

| Item | Value | Source |
|------|-------|--------|
| Split method | **Chronological by UTC kickoff** (all rows sharing a tip share the same fold) | `app/ml/features.py::split_chronological` |
| Train / val / test fractions | **70% / 15% / 15%** of distinct kickoffs | `TRAIN_FRAC`, `VAL_FRAC` |
| Features | Point-in-time rolling stats (`shift(1)`), season-to-date means, opponent defense, rest, etc. | `enrich_player_game_frame` |
| Active model version | **`20261022T172639Z`** | `backend/artifacts/ml/active_version.txt` |

### 4.2 Player stat models — held-out **test** set (n = **8,197** player-games each category)

Test date range: **2026-03-08 .. 2026-10-21**. Baselines are **not** a single fixed “last-10” line: for each component stat, validation picks the best of **`season_avg` | `last_10` | `ewm(10)`**, then composes category totals (see `baseline_kind` in `metrics.json`: e.g. `pts:ewm, reb/ast/fg3m: season_avg`).

| Category | MAE baseline | MAE ML | Δ MAE | RMSE baseline | RMSE ML | Δ RMSE | Selected |
|----------|-------------:|-------:|------:|--------------:|--------:|-------:|----------|
| **pts** | 4.765 | **4.623** | **−3.0%** | 6.272 | **6.049** | **−3.6%** | ml |
| **reb** | 1.936 | **1.844** | **−4.7%** | 2.572 | **2.431** | **−5.5%** | ml |
| **ast** | 1.408 | **1.343** | **−4.6%** | 1.927 | **1.825** | **−5.3%** | ml |
| **fg3m** | 0.901 | **0.896** | **−0.5%** | 1.268 | **1.236** | **−2.5%** | ml |
| **pts_reb_ast** | 6.342 | **6.032** | **−4.9%** | 8.208 | **7.763** | **−5.4%** | ml |

**Method:** Frozen artifact `metrics.json` from training pipeline (`make ml-metrics` / `app/cli ml-metrics`). **Confidence:** High for reproducibility on this DB snapshot; models not in git (regenerate via `make ml-train`).

**Training row counts (played games frame):** train **40,745** / val **8,272** / test **8,197** (total **57,214** labeled rows in split).

### 4.3 Game winner model

Active version: **`20261022T173538Z`** (`backend/artifacts/ml/game_winner/`). **373** held-out test games (chronological).

| Model (test set) | Accuracy | Log loss | Brier | Notes |
|------------------|---------:|---------:|------:|-------|
| Home baseline | 0.592 | 0.680 | 0.243 | Always-home prior |
| Elo (raw) | **0.743** | **0.542** | **0.181** | Strong discrimination |
| Logistic (production) | 0.684 | 0.562 | **0.191** | **Selected** + isotonic calibration enabled |
| Gradient boosting “ml” | 0.713 | 0.571 | 0.194 | Not selected |

**Documented internal A/B (same test games, pipeline fix):** prior bundle `20261022T173119Z` vs current—calibrated logistic test Brier **0.185 → 0.191** (metrics `prior_model_baseline_report`); treat as engineering regression audit, not independent dataset.

---

## 5. Calibration (props & probabilities)

| Claim | Status | Evidence |
|-------|--------|----------|
| Real sportsbook **pregame** prop calibration (Brier / log-loss vs closing lines) | **Not available** | `backend/docs/PROBABILITY_CALIBRATION.md` — no timestamped pregame line archive |
| Prop **hit-rate vs today’s posted line** on past games | Implemented | `prop_line_hit_cache`; descriptive only |
| Player prop **Brier** in `metrics.json` | **Synthetic only** | Scheme **`pregame_model_half`**: floor(model mean)+0.5, normal-over-under prob; isotonic fit on val, scored on test |
| Example pts test Brier (synthetic line) | **0.2497** raw normal → **0.2460** isotonic | n ≈ category test rows with ≥8 prior games | **Do not cite as market calibration** |
| Production `enable_probability_calibration` | **false** default | `app/config.py` |
| Game winner reliability bins | Available on **held-out test** | See `ml-metrics-games` JSON (`reliability_raw` for Elo/logistic/ml) |

---

## 6. Engineering & quality

| Metric | Value | Method | Limitations |
|--------|-------|--------|---------------|
| Backend tests collected | **177** | `pytest --collect-only` | |
| Backend tests executed (excl. slow perf) | **175 passed**, **1 skipped**, **0 failed** | `pytest -q --ignore=tests/test_recommendation_performance.py` | DB-backed tests need `make db` |
| Slow integration budget test | 1 test (`<120 s` generation) | `@pytest.mark.slow` | Not run for pass-rate above |
| Frontend unit tests | **10** passed | `npm test` (Vitest) | `frontend/src/lib/format.test.ts` |
| DB migrations | **8** Alembic revisions | `backend/alembic/versions/` | |
| API surface | **9** route modules (`players`, `games`, `stats`, `predictions`, `recommendations`, `prop_finder`, `hit_streaks`, `parlay_builder`, `sync`) | `app/main.py` | |
| Stack | FastAPI, SQLAlchemy 2, PostgreSQL 16, Next.js, scikit-learn/XGBoost regressors | repo | |
| ML inference batching | Prepared-path parity test | `tests/test_recommendation_inference_batch.py` | Numerical equivalence direct vs batched |
| Recommendation batching | Uncached budget **&lt;120 s** for 3-day feed | `test_recommendation_generation_under_budget` | Slow mark |

---

## Master metrics table (resume-ready)

| Metric | Measured value | Baseline | Measurement method | Sample size | Confidence / limitations |
|--------|----------------|----------|-------------------|-------------|--------------------------|
| Player-game data warehouse rows | 75,216 (61,511 played) | — | SQL count | 75,216 | Local ESPN sync |
| Historical box scores | 2,840 final games / 3 seasons | — | SQL | 2,840 | Current season partial (205 games) |
| Sportsbook prop rows stored | 328,283 (11.8k active) | — | SQL | 328k | Lifetime import 965k upserts |
| Player profile API latency p50 | 8.6 ms | — | TestClient 30× | 30 | Local M2 Pro |
| Game logs API p50 (82 games) | 9.2 ms | — | TestClient 30× | 30 | |
| ML player-stat prediction p50 | 743 ms | — | TestClient 30× | 30 | Per-request feature build |
| Recommendations cache warm p50 | 0.87 ms | 36.4 s cold | Service timing | 5 warm | In-proc cache; 596 props |
| Player-game log SQL (index) | 0.23 ms | — | EXPLAIN ANALYZE | 213 rows | Planner only |
| pts MAE (chronological test) | 4.623 | 4.765 composite baseline | `metrics.json` holdout | 8,197 | Auto-picked baseline components |
| pts_reb_ast MAE test | 6.032 | 6.342 | same | 8,197 | |
| Game winner Brier (test, prod logistic) | 0.192 | 0.243 home | `ml-metrics-games` | 373 games | Not betting ROI |
| Automated tests | 175 pass / 1 skip | — | pytest + vitest | 187 total | Excludes 1 slow test from run |

---

## Strongest resume bullets (pick 3 per track)

### Software engineering (measurable)

1. **Built a synced NBA data platform** ingesting **75k+** player-game rows and **2,840** box-scored games across **3** seasons with resumable backfill (**~2.1** box scores/s aggregate) and **5.3k** documented provider HTTP requests.
2. **Delivered sub-10 ms p50 REST reads** for player profiles and game logs (30-run local benchmark) on PostgreSQL 16 with index-backed player history (**0.23 ms** planner time on `ix_pgs_player_date`).
3. **Optimized recommendation aggregation** with versioned in-memory caching: **~36 s → &lt;1 ms p50** warm latency for a **596-prop / 3-day** feed with verified output equivalence; batch inference parity covered by automated tests (**177** backend tests).

### Machine learning (measurable)

1. **Chronological leak-safe training pipeline** (UTC kickoff splits) on **57k+** player-game examples; holdout **8,197** games; ML reduces **pts** MAE **4.765 → 4.623** (~**3%**) vs strong rolling baselines on untouched test data.
2. **Multi-target player prop models** (pts/reb/ast/fg3m + composites) with unified component covariance for line probabilities; **pts_reb_ast** RMSE **7.76** vs baseline **8.21** (~**5.4%**).
3. **Game outcome modeling** on **373** held-out games: production **logistic** achieves Brier **0.191** vs **0.243** home baseline; **Elo** reaches **74.3%** accuracy on the same test split (reported with calibration/reliability artifacts).

---

## What not to claim

- Betting win rates, ROI, or “beat the sportsbook” using Prop Finder hit rates or synthetic half-point lines.
- Market-calibrated prop probabilities (`PROBABILITY_CALIBRATION.md`).
- Production API latency under load without load tests on deployed infrastructure.
- Before/after database migration performance without paired measurements on both schemas.

---

## Reproduction checklist

```bash
make db && make status
make ml-metrics
make ml-metrics-games
cd backend && .venv/bin/pytest -q --ignore=tests/test_recommendation_performance.py
PYTHONPATH=. .venv/bin/python scripts/_resume_metrics_data_scale.py
PYTHONPATH=. .venv/bin/python scripts/_resume_metrics_api_bench.py   # ~90s (cold ML)
PYTHONPATH=. .venv/bin/python scripts/_resume_metrics_db_bench.py
```