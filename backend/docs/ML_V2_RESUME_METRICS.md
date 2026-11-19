# Hooplytics ML v2 — validation, benchmarks and resume metrics

Model `v2_20261118T093017Z` (rollback `v2_20261118T092450Z`). All numbers below are read from
`artifacts/ml/research/{research_results,benchmark_results,resume_metrics}.json`, each regenerable:

```
cd backend
PYTHONPATH=. .venv/bin/python scripts/ml_research.py --boot 2000      # ~4 min, research_results.json
PYTHONPATH=. .venv/bin/python scripts/ml_benchmark.py                 # ~8 min, benchmark_results.json
PYTHONPATH=. .venv/bin/python scripts/ml_resume_metrics.py            # resume_metrics.json (with source paths)
```

Benchmarks are **local development measurements** (Apple M2 Pro, 10 cores, 16 GB, macOS 15.6, Python 3.13.1,
scikit-learn 1.6.0, PostgreSQL 16.15 in Docker). They are not production-traffic results.
Bootstrap: B = 2000, seed 20261118, resampling **games** (288 test games); date-clustered and iid CIs are also
saved and are nearly identical.

## 1. Research results

**Integrity.** The research script reloads data restricted to the manifest's dataset cutoff and refits the
fold-2 specs; reproduced test MAE matches the manifest exactly (max |diff| = 0.0) for all 8 categories.
Dataset accounting: 75,216 final-game rows → 13,705 DNP + 61,511 played → 336 excluded (108 missing minutes,
228 zero minutes) → 61,175 usable → 745 first-in-data appearances excluded → **60,430 modeled**
(train 40,566 / val 13,372 / test 6,300). The 192-row gap = 87 val + 105 test rows with < 3 prior appearances.

**Held-out test period (6,300 player-games, 288 games), MAE improvement, game-clustered 95% CI:**

| Category | vs best baseline | vs last-10 avg | vs v1 refit (no starter flag) |
|---|---|---|---|
| PTS | +4.72% [3.87, 5.59] | +6.58% | +2.62% [2.01, 3.24] |
| REB | +3.81% [3.03, 4.61] | +5.32% | +2.37% [1.79, 2.93] |
| AST | +3.38% [2.47, 4.26] (vs EWM) | +5.03% | +2.69% [1.82, 3.51] |
| 3PM | 0.00% (model = weighted baseline) | +0.98% | +0.36% [−0.41, 1.08] |
| PTS+REB | +5.24% [4.43, 6.08] | +7.29% | +3.12% |
| PTS+AST | +5.04% [4.14, 5.92] | +7.40% | +3.31% |
| REB+AST | +4.45% [3.64, 5.34] | +6.44% | +2.84% |
| PRA | +5.46% [4.56, 6.34] | +8.01% | +3.52% [2.89, 4.16] |

"Best baseline" is chosen on the test set itself (most conservative comparison). vs the saved v1 bundle
(which used the leaky same-game starter flag): PTS +1.28% [0.59, 2.00], PRA +1.52% [0.68, 2.34].

**Walk-forward (8 out-of-time windows, no tuning on any window), PTS vs weighted baseline:**

| Window | Period | Role | PTS | PRA |
|---|---|---|---|---|
| W1 | 2025-01-15 → 02-28 | pre-selection | −0.33% [−1.09, 0.40] | +0.58% |
| W2 | 2025-03-01 → 04-13 | pre-selection | +0.59% [−0.11, 1.31] | +1.25% |
| W3 | 2025 playoffs | pre-selection | **−17.48%** [−20.43, −14.64] | −17.25% |
| W4 | 2025-10-21 → 2026-01-14 | pre-selection | −0.40% [−0.96, 0.16] | +0.19% |
| W5 | 2026-01-15 → 02-28 | validation (selection) | +0.80% | +1.87% |
| W6 | 2026-03-01 → 04-12 | validation (selection) | +1.57% | +2.49% |
| W7 | 2026 playoffs | test | +7.20% [5.62, 8.78] | +8.73% |
| W8 | 2026-10-01 → 11-16 | test | +3.62% [2.71, 4.57] | +3.99% |

Pooled, game-clustered:
- Pre-selection W1–W4: PTS −1.34% [−1.83, −0.87]; PRA −0.68% [−1.18, −0.22] (driven by W3).
- Pre-selection regular season W1, W2, W4: PTS −0.11% [−0.47, 0.28] (not significant); REB +0.85% [0.52, 1.18];
  PRA +0.58% [0.22, 0.94].
- All 8 windows: PTS +0.16% [−0.20, 0.53] (not significant); REB +0.79%; AST +0.98%; PRA +0.92% [0.57, 1.25].

Interpretation: gains grow with training history (12k → 56k rows) and are not uniform. W3 is a diagnosed
feature-design weakness, not leakage: with no playoff rows in training, `season_progress` makes playoff games
look like late regular season, where bench minutes rise (+3.3 vs L10); in the playoffs they fall (−2.5).
Fixing season-progress for playoff rows alone cut W3 PTS MAE 5.72 → 4.81 (baseline 4.87) in a diagnostic.
The deployed model trains on two playoff runs (W7 is +7.2%). Recommended for feature version 2.2; not retrained here.

**Intervals (test, fit on validation residuals):**

| | 50% cov / width | 80% cov / width | 90% cov / width |
|---|---|---|---|
| PTS model | 0.569 / 7.39 | 0.842 / 14.04 | 0.922 / 18.13 |
| PTS global-residual baseline | 0.485 / 7.26 | 0.797 / 13.79 | 0.897 / 18.10 |
| PTS player-std normal baseline | 0.449 / 7.36 | 0.770 / 13.52 | 0.863 / 16.79 |
| PRA model | 0.538 / 9.65 | 0.811 / 18.32 | 0.894 / 23.54 |
| PRA player-std normal baseline | 0.397 / 8.45 | 0.690 / 15.90 | 0.810 / 20.13 |

Model intervals are slightly conservative in aggregate but hold conditional coverage across minutes tiers
(PTS 80%: 0.81–0.84 for 15+ min tiers vs the global baseline's 0.68–0.82), because widths scale with projected
volume. Limitations: AST/3PM over-cover (50% intervals ≈ 0.71); widths do not widen for volatile-minutes or
short-history players; steals/blocks are not modeled.

## 2. Sportsbook validation (no edge claim)

Archive: 94,290 settled pregame snapshots, 11,512 unique player/game/category/line combinations, 326 thresholds,
14 books, 63 games (60 overlap the test period). No historical lines were fetched or fabricated.

Model vs de-vigged market Brier (lower is better), game-clustered CI of market − model:

| Category | Book lines | Model | Market | Market − model, 95% CI | Model ECE |
|---|---|---|---|---|---|
| PTS | 7,559 | 0.2388 | 0.2478 | +0.0090 [+0.0009, +0.0167] | 0.053 |
| REB | 6,439 | 0.2489 | 0.2471 | −0.0018 [−0.0113, +0.0075] | 0.042 |
| AST | 4,784 | 0.2555 | 0.2429 | −0.0126 [−0.0217, −0.0031] | 0.052 |
| 3PM | 5,556 | 0.2760 | 0.2452 | −0.0308 [−0.0428, −0.0177] | 0.114 |
| PTS+REB | 4,500 | 0.2598 | 0.2496 | −0.0102 [−0.0204, −0.0004] | 0.078 |
| PTS+AST | 3,492 | 0.2686 | 0.2489 | −0.0197 [−0.0303, −0.0095] | 0.074 |
| REB+AST | 3,288 | 0.2554 | 0.2468 | −0.0085 [−0.0199, +0.0025] | 0.064 |
| PRA | 5,356 | 0.2619 | 0.2497 | −0.0121 [−0.0226, −0.0014] | 0.081 |

The market is significantly better on 5 of 8 categories. PTS is marginally better than the market on 58 games,
but it is one of 8 comparisons, the CI lower bound is near zero, and PTS fails the ECE ≤ 0.04 gate.
**No category passes the real-line gate; probabilities and ML recommendations stay disabled.**

## 3. Prospective forecast archive

Immutable `ml_forecasts` / `ml_forecast_lines` tables (migration 0010). A Postgres trigger blocks UPDATE of
prediction columns and all DELETEs; CHECK constraints enforce `predicted_at < tipoff` and pregame line timestamps;
a unique key makes recording idempotent. Settlement is a single idempotent SQL statement
(settled / void_dnp / void_game / unresolved). Runs after each successful ESPN sync and odds import; served
read-only at `GET /api/ml/prospective` and in the ML Lab "Prospective" tab.

Current state: **484 forecasts for 15 games, all pending**, 0 attached lines (no odds import since Nov 17).
No prospective accuracy is claimed until ≥ 1,000 settled forecasts across ≥ 50 games (enforced in the summary).

## 4. Engineering benchmarks (local)

| Measurement | Result |
|---|---|
| Full training pipeline (load → selection → test → refit → save) | 157 s wall, 903 MB peak RSS, 1.79 MB artifact |
| Fold-1 candidate fit (PTS): ridge / HGB / two-stage | 0.16 s / 1.3–2.0 s / 10.4 s |
| Raw load 75,342 rows / feature build (120 columns) | 681 ms / 1,278 ms p50 (≈ 59k rows/s) |
| Artifact load | 47 ms p50 |
| Batch scoring (5 models + 8-category quantiles), 1 / 100 / 500 / 1000 rows | 31 / 74 / 270 / 484 ms p50 (up to ≈ 2,065 rows/s) |
| One batch call vs 500 single-row calls | 277 ms vs 16.0 s (**57.9×**) |
| Cold upcoming slate (bundle + DB + features + scoring, 514 player-games) | 2.45 s p50; cached 9 ms |
| Odds archive settlement (94,290 rows, rolled back) | 5.7 s p50 ≈ 16.5k rows/s; idempotent rerun 87 ms, 0 changes |
| Forecast settlement (20,000 synthetic rows, rolled back) | 610 ms ≈ 32.8k rows/s; rerun 0 changes |
| Forecast recording (484 real forecasts, rolled back) | ≈ 900/s; rerun inserts 0 |

API (uvicorn, 1 worker, local PostgreSQL; schedulers and Unabated disabled; 100 sequential + 200 requests from
8 threads over a shared keep-alive pool; **0 errors on every endpoint**):

| Endpoint | First request | Warm p50 / p95 | 8-thread throughput |
|---|---|---|---|
| `/ml/projections/upcoming` | 2,776 ms (lazy model + feature build) | 20.1 / 22.0 ms | 100 rps |
| `/ml/projections/player/{id}` | 19.6 ms | 14.0 / 16.5 ms | 243 rps |
| `/ml/projections/prop` | 13.1 ms | 11.6 / 13.1 ms | 472 rps |
| `/ml/comparison` | 32.3 ms | 7.1 / 8.7 ms | 540 rps |
| `/ml/prospective` | 25.3 ms | 3.1 / 3.5 ms | 708 rps |
| `/ml/status` | 270 ms | 72.2 / 83.5 ms | 84 rps |

Server peak RSS 574 MB. `/ml/status` is dominated by two ~70 ms aggregate queries (odds-archive status);
at a page-load endpoint that is acceptable, so no optimization was applied.

The first-request column for `upcoming` comes from the earlier server start within the same run. The training-benchmark refit uses the *current* DB
(126 rows past the dataset cutoff), so its test MAE differs from the manifest in the 4th decimal
(PTS 4.4567 vs 4.4562); the cutoff-restricted research reproduction is exact.

## 5. Top 10 achievements (ranked by strength of evidence)

1. Beat the strongest simple baseline on 7/8 prop categories on a held-out period with game-clustered
   bootstrap CIs excluding zero (PTS +4.7%, PRA +5.5%; up to +8.0% vs last-10 averages).
2. Exact end-to-end reproducibility: refit from raw data reproduces held-out MAE to 0.0 difference; full
   accounting of 75,216 → 60,430 modeled rows including a 192-row discrepancy explained to the row.
3. Found and removed a same-game leakage feature (starter flag) in v1; controlled same-window refits show v2
   beats leakage-free v1 by +2.4–3.5% across 7 categories.
4. Honest 8-window walk-forward evaluation that surfaced a −17% playoff failure mode and diagnosed its cause
   (season-progress feature), with a measured fix (5.72 → 4.81 MAE).
5. Calibrated predictive intervals with conditional coverage held across minutes tiers, where the
   homoscedastic baseline drops to 0.68 coverage for high-minute players.
6. Probability-gating system validated against 11,512 real archived sportsbook lines from 14 books, with the
   model-vs-market Brier test that correctly keeps probabilities disabled.
7. Tamper-evident prospective forecast archive (DB trigger + check constraints) with idempotent settlement,
   making future out-of-sample claims auditable.
8. Vectorized batch inference 57.9× faster than per-row scoring; ~2,000 multi-model predictions/s; 9–14 ms cached
   projections.
9. Read-only ML API: sub-25 ms warm p50 on 5 of 6 endpoints, 100–708 rps on one local worker, 0% errors.
10. 213 backend tests (212 pass, 1 skipped) + 10 frontend tests; reproducible research and benchmark scripts.

**Software Engineering picks:** #7, #8, #9 — e.g. "Built a tamper-evident forecast archive in PostgreSQL
(trigger-enforced immutability, idempotent settlement at ~33k rows/s)"; "Vectorized multi-model inference
57.9× faster than per-row scoring; ~2,000 predictions/s locally".

**ML Engineering picks:** #1, #2, #4 — e.g. "Cut player-prop MAE 4.7–5.5% vs the strongest baseline on a held-out
season segment (game-clustered bootstrap, B=2000), with exact reproducibility and an 8-fold walk-forward audit".

**Applied AI / Data Science picks:** #3, #5, #6 — e.g. "Detected same-game leakage in v1 and quantified the honest
gain (+2.6% PTS) via controlled refits"; "Validated probability calibration against 11.5k real sportsbook lines
and kept the feature gated when it failed (no category met ECE ≤ 0.04)".

Do not claim: a betting edge, production traffic numbers, prospective accuracy (none settled yet), or
uniform gains across all periods (pooled pre-selection PTS is −1.3%).

## 6. Status and remaining opportunities

Flags unchanged: inference on, experimental UI on, recommendations off, probabilities off. Active and rollback
artifacts untouched. HCS/PCS, Prop Finder and Parlay Builder unchanged. Nothing committed.

Verification run on 2026-11-18: backend pytest 212 passed / 1 skipped; frontend 10/10 tests, `tsc` clean,
`next build` succeeds; ESLint 0 errors (1 pre-existing warning in `prop-finder-view.tsx`, untouched); ruff clean
on new/changed files.

Opportunities, in order of value:
1. Settle the 484 pending forecasts after games finish (`make ml-forecast` or the scheduler) and keep
   accumulating to the 1,000-forecast / 50-game threshold.
2. Feature version 2.2: reset season-progress features for playoff rows (fixes the W3 failure mode); validate
   with the same walk-forward script before promoting.
3. Volatility-aware interval widths (minutes std, history length) and a dedicated 3PM model (currently equal to
   the weighted baseline).
4. Keep importing odds to grow the real-line archive; re-run the market comparison once more games exist.
