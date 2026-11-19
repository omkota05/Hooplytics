"""Reproducible LOCAL benchmarks for the v2 ML engine (not production traffic).

Each section runs in its own subprocess so peak RSS can be attributed to it (os.wait4 rusage).
Sections:
  features   data extraction, validation, feature engineering throughput, cProfile hot spots
  inference  cold/warm artifact load, scoring 1..5000 real feature rows, batch vs per-row,
             end-to-end service batch (cold / cached), cached single-player projection
  training   one full train_engine run into a temporary artifact root (never promoted)
  api        real uvicorn + PostgreSQL: cold first request, warm sequential, concurrent reads
  database   query latency + archive settlement/insert throughput inside ROLLBACK transactions
Safety: no Unabated calls (API key blanked, schedulers off), no retraining of the active model,
all write benchmarks are rolled back.

Usage: cd backend && .venv/bin/python scripts/ml_benchmark.py [--sections features,inference,api,database,training]
Output: artifacts/ml/research/benchmark_results.json
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import resource
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
OUT = BACKEND / "artifacts" / "ml" / "research"
SAFE_ENV = {"UNABATED_API_KEY": "", "SYNC_ON_STARTUP": "false", "PROP_ODDS_SYNC_ON_STARTUP": "false", "PYTHONPATH": str(BACKEND)}


def pct(values: list[float], p: float) -> float:
    s = sorted(values)
    if not s:
        return float("nan")
    k = (len(s) - 1) * p / 100
    lo, hi = int(k), min(int(k) + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def summarize(ms: list[float]) -> dict:
    return {"n": len(ms), "p50_ms": round(pct(ms, 50), 3), "p95_ms": round(pct(ms, 95), 3), "mean_ms": round(statistics.fmean(ms), 3),
            "min_ms": round(min(ms), 3), "max_ms": round(max(ms), 3)}


def timeit(fn, reps: int, warmup: int = 1) -> list[float]:
    for _ in range(warmup):
        fn()
    out = []
    for _ in range(reps):
        t = time.perf_counter()
        fn()
        out.append((time.perf_counter() - t) * 1000)
    return out


# ---------------------------------------------------------------------------------------------
def section_features() -> dict:
    import cProfile
    import pstats
    import tracemalloc

    from app.db import session_scope
    from app.ml.engine.data import load_raw, validate_and_clean
    from app.ml.engine.features import FEATURE_SETS, build_features

    with session_scope() as s:
        load_ms = timeit(lambda: load_raw(s), 5)
        raw = load_raw(s)
    val_ms = timeit(lambda: validate_and_clean(raw), 5)
    clean, _ = validate_and_clean(raw)
    feat_ms = timeit(lambda: build_features(clean), 5)
    feats = build_features(clean)
    tracemalloc.start()
    build_features(clean)
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    prof = cProfile.Profile()
    prof.enable()
    build_features(clean)
    prof.disable()
    st = pstats.Stats(prof)
    hot = []
    for (file, line, fn), (_cc, _nc, tt, ct, _callers) in st.stats.items():
        if "app/ml/engine/features.py" in file:
            hot.append({"function": f"features.py:{line}:{fn}", "cumulative_s": round(ct, 3), "self_s": round(tt, 3)})
    hot.sort(key=lambda r: -r["cumulative_s"])
    p50 = pct(feat_ms, 50)
    return {
        "rows_loaded": len(raw),
        "extract_load_raw": summarize(load_ms),
        "validate_and_clean": summarize(val_ms),
        "build_features": summarize(feat_ms),
        "feature_rows_per_second_p50": round(len(clean) / (p50 / 1000)),
        "output_columns_total": int(feats.shape[1]),
        "model_feature_columns": {"core": len(FEATURE_SETS["core"]), "full": len(FEATURE_SETS["full"])},
        "build_features_tracemalloc_peak_mb": round(peak / 2**20, 1),
        "feature_frame_memory_mb": round(feats.memory_usage(deep=True).sum() / 2**20, 1),
        "hot_spots_cumulative": hot[:8],
    }


def section_inference() -> dict:
    import numpy as np

    from app.db import session_scope
    from app.ml.engine import artifacts as art
    from app.ml.engine.data import ALL_CATEGORIES, TARGETS, load_raw, validate_and_clean
    from app.ml.engine.evaluation import vectorized_category_quantiles
    from app.ml.engine.features import build_features
    from app.ml.engine.service import EngineService

    version = art.active_version()
    load_ms = timeit(lambda: art.load_bundle(version), 10, warmup=1)
    bundle = art.load_bundle(version)
    size_mb = sum(f.stat().st_size for f in (art.ROOT / version).iterdir()) / 2**20
    with tempfile.TemporaryDirectory() as td:
        ser_ms = []
        for i in range(5):
            t = time.perf_counter()
            art.save_bundle(Path(td) / f"v{i}", manifest=bundle.manifest, metrics={}, models=bundle.models,
                            minutes_model=bundle.minutes_model, distribution=bundle.distribution)
            ser_ms.append((time.perf_counter() - t) * 1000)

    with session_scope() as s:
        clean, _ = validate_and_clean(load_raw(s))
    feats = build_features(clean)
    pool = feats[feats["usable_target"] & (feats["appearances"] >= 3)].tail(5000).reset_index(drop=True)

    def score(rows):
        means = np.column_stack([bundle.models[t].predict(rows) for t in TARGETS])
        bundle.minutes_model.predict(rows)
        for c in ALL_CATEGORIES:
            vectorized_category_quantiles(bundle.distribution, means, c, (0.1, 0.25, 0.5, 0.75, 0.9))
        return means

    scoring = {}
    for n, reps in ((1, 50), (100, 30), (500, 20), (1000, 15), (5000, 5)):
        rows = pool.head(n)
        ms = timeit(lambda rows=rows: score(rows), reps)
        scoring[str(n)] = {**summarize(ms), "predictions_per_second_p50": round(n / (pct(ms, 50) / 1000), 1)}
    rows500 = pool.head(500)
    batch_ms = timeit(lambda: score(rows500), 5)
    loop_ms = timeit(lambda: [score(rows500.iloc[[i]]) for i in range(500)], 1, warmup=0)
    point_only = timeit(lambda: [bundle.models[t].predict(rows500) for t in TARGETS], 10)

    # End-to-end service path used by /api/ml/projections/* (DB load + features + scoring).
    cold = []
    for _ in range(3):
        svc = EngineService()
        t = time.perf_counter()
        with session_scope() as s:
            b = svc.batch(s)
        cold.append((time.perf_counter() - t) * 1000)
    with session_scope() as s:
        cached_batch = timeit(lambda: svc.batch(s), 100)
        pid, gid = next(iter(b))
        cached_player = timeit(lambda: svc.project(s, pid, gid), 200)
    return {
        "model_version": version,
        "artifact_size_mb": round(size_mb, 2),
        "artifact_load_warm_os_cache": summarize(load_ms),
        "artifact_serialize_save_bundle": summarize(ser_ms),
        "scoring_real_feature_rows (4 component models + minutes model + 8-category quantiles)": scoring,
        "batch_vs_per_row_500": {
            "one_batch_call_p50_ms": round(pct(batch_ms, 50), 1),
            "500_single_row_calls_ms": round(loop_ms[0], 1),
            "speedup_x": round(loop_ms[0] / pct(batch_ms, 50), 1),
        },
        "point_predictions_only_500_rows": summarize(point_only),
        "service_batch_cold_incl_bundle_load_db_features (player-games)": {**summarize(cold), "player_games": len(b)},
        "service_batch_cached": summarize(cached_batch),
        "service_project_single_cached": summarize(cached_player),
    }


def section_training() -> dict:
    from app.db import session_scope
    from app.ml.engine import artifacts as art
    from app.ml.engine import training

    with tempfile.TemporaryDirectory() as td:
        art.ROOT = Path(td)
        t = time.perf_counter()
        with session_scope() as s:
            res = training.train_engine(s, promote_if_valid=False)
        wall = time.perf_counter() - t
        size = sum(f.stat().st_size for f in (Path(td) / res["version"]).iterdir()) / 2**20
    m = res["metrics"]["test"]
    return {
        "wall_seconds": round(wall, 1),
        "stage_seconds": res["manifest"]["timings_seconds"],
        "artifact_size_mb": round(size, 2),
        "promoted": res["promoted"],
        "test_mae_matches_active": {c: round(m[c]["model"]["mae"], 6) for c in m},
        "candidate_fit_seconds_fold1": {
            stat: {k: v.get("fit_seconds") for k, v in sel["validation"].items() if "fit_seconds" in v}
            for stat, sel in res["metrics"]["selection"].items()
        },
    }


def section_api() -> dict:
    import concurrent.futures as cf

    import httpx

    port = 8765
    env = {**os.environ, **SAFE_ENV}
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--port", str(port), "--log-level", "warning"],
        cwd=BACKEND, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    base = f"http://127.0.0.1:{port}/api"
    out: dict = {"server": "uvicorn 1 worker, no reload, local PostgreSQL 16 (Docker); schedulers and Unabated disabled"}
    try:
        t0 = time.perf_counter()
        with httpx.Client(timeout=60) as c:
            while True:
                try:
                    if c.get(f"{base}/health").status_code < 500:
                        break
                except httpx.HTTPError:
                    time.sleep(0.2)
            out["startup_seconds"] = round(time.perf_counter() - t0, 2)
            up = c.get(f"{base}/ml/projections/upcoming", params={"limit": 50})
            first_upcoming_ms = up.elapsed.total_seconds() * 1000
            row = next(r for r in up.json()["rows"] if r["appearances"] >= 10)
            eps = {
                "/ml/status": ("/ml/status", None),
                "/ml/metrics": ("/ml/metrics", None),
                "/ml/projections/upcoming": ("/ml/projections/upcoming", {"limit": 100}),
                "/ml/projections/player/{id}": (f"/ml/projections/player/{row['player_id']}", None),
                "/ml/projections/prop": ("/ml/projections/prop", {"player_id": row["player_id"], "game_id": row["game_id"], "category": "pts", "line": 20.5}),
                "/ml/comparison": ("/ml/comparison", {"limit": 150}),
                "/ml/prospective": ("/ml/prospective", None),
            }
            res = {}
            for name, (path, params) in eps.items():
                r0 = c.get(f"{base}{path}", params=params)
                cold_ms = first_upcoming_ms if name == "/ml/projections/upcoming" else r0.elapsed.total_seconds() * 1000
                lat, errs = [], 0
                t = time.perf_counter()
                for _ in range(100):
                    r = c.get(f"{base}{path}", params=params)
                    errs += r.status_code != 200
                    lat.append(r.elapsed.total_seconds() * 1000)
                dur = time.perf_counter() - t
                res[name] = {"first_request_ms": round(cold_ms, 1), "first_status": r0.status_code, "warm_sequential": summarize(lat),
                             "sequential_rps": round(100 / dur, 1), "error_rate": errs / 100, "response_kb": round(len(r0.content) / 1024, 1)}
        out["first_request_note"] = "/ml/projections/upcoming first request includes lazy model load + DB load + feature build + batch scoring"
        pool = httpx.Client(timeout=60, limits=httpx.Limits(max_connections=8, max_keepalive_connections=8))
        try:
            for name, (path, params) in eps.items():
                if name == "/ml/metrics":
                    continue

                def one(_i, path=path, params=params):
                    r = pool.get(f"{base}{path}", params=params)
                    return r.status_code, r.elapsed.total_seconds() * 1000

                t = time.perf_counter()
                with cf.ThreadPoolExecutor(8) as ex:
                    results = list(ex.map(one, range(200)))
                dur = time.perf_counter() - t
                res[name]["concurrent_8_clients_200_requests"] = {
                    **summarize([r[1] for r in results]), "throughput_rps": round(200 / dur, 1),
                    "error_rate": sum(r[0] != 200 for r in results) / 200,
                    "client": "one shared keep-alive pool (8 connections), 8 threads",
                }
        finally:
            pool.close()
        out["endpoints"] = res
    finally:
        proc.terminate()
        _, _, ru = os.wait4(proc.pid, 0)
        out["server_peak_rss_mb"] = round(ru.ru_maxrss / 2**20, 1)
    return out


def section_database() -> dict:
    from sqlalchemy import text

    from app.db import session_scope
    from app.ml.engine.data import data_snapshot_key
    from app.services.forecast_archive_service import record_forecasts, settle_forecasts
    from app.services.ml_engine_service import status as ml_status
    from app.services.odds_archive_service import archive_status, settle_snapshots

    out: dict = {}
    with session_scope() as s:
        out["data_snapshot_key"] = summarize(timeit(lambda: data_snapshot_key(s), 30))
        out["odds_archive_status"] = summarize(timeit(lambda: archive_status(s), 10))
        out["ml_status_service_call"] = summarize(timeit(lambda: ml_status(s), 10))
        n_snap = s.scalar(text("SELECT COUNT(*) FROM prop_offer_snapshots"))
    # Settlement throughput on the real archive: un-settle inside a transaction, settle, ROLLBACK.
    runs = []
    with session_scope() as s:
        for _ in range(3):
            sp = s.begin_nested()
            s.execute(text("UPDATE prop_offer_snapshots SET result = NULL, actual_value = NULL, settled_at = NULL"))
            t = time.perf_counter()
            counts = settle_snapshots(s)
            runs.append((time.perf_counter() - t) * 1000)
            t = time.perf_counter()
            again = settle_snapshots(s)
            noop_ms = (time.perf_counter() - t) * 1000
            sp.rollback()
        s.rollback()
    out["odds_snapshot_settlement_full_archive"] = {"rows": int(n_snap), "settled_rows": int(sum(counts.values())), **summarize(runs),
                                                     "rows_per_second_p50": round(sum(counts.values()) / (pct(runs, 50) / 1000)),
                                                     "idempotent_rerun_ms": round(noop_ms, 1), "idempotent_rerun_changes": int(sum(again.values()))}
    # Forecast insert throughput with real upcoming projections under a throwaway model version, rolled back.
    import copy

    from app.ml.engine.service import get_engine_service

    inner = get_engine_service()

    class _RenamedVersion:
        """Same model and cached batch, recorded under a throwaway version so inserts are not deduplicated."""

        def __init__(self) -> None:
            self.b = copy.copy(inner.bundle())
            self.b.version = "benchmark_rollback"

        def bundle(self):
            return self.b

        def batch(self, s):
            return inner.batch(s)

        def _state_for(self, s):
            return inner._state_for(s)

    with session_scope() as s:
        inner.batch(s)
        svc = _RenamedVersion()
        t = time.perf_counter()
        first = record_forecasts(s, svc=svc)
        first_ms = (time.perf_counter() - t) * 1000
        t = time.perf_counter()
        second = record_forecasts(s, svc=svc)
        second_ms = (time.perf_counter() - t) * 1000
        s.rollback()
    out["forecast_record_real_upcoming_rolled_back"] = {"inserted": first["inserted"], "first_run_ms": round(first_ms, 1),
                                                         "rerun_inserted": second["inserted"], "rerun_ms": round(second_ms, 1),
                                                         "forecasts_per_second": round(first["inserted"] / (first_ms / 1000))}
    # Settlement throughput: SYNTHETIC forecast rows for already-final games, inserted and settled inside a
    # transaction that is always rolled back (never persisted; labelled synthetic).
    with session_scope() as s:
        s.execute(text(
            """
            INSERT INTO ml_forecasts (player_id, game_id, team_id, opponent_team_id, predicted_at, scheduled_tipoff, model_version,
              feature_version, data_snapshot, appearances, season_appearances, projected_minutes, proj_pts, proj_reb, proj_ast, proj_fg3m,
              proj_pts_reb, proj_pts_ast, proj_reb_ast, proj_pts_reb_ast, quantiles, baselines, context, warnings, probability_status)
            SELECT p.player_id, p.game_id, p.team_id, p.opponent_team_id, g.start_time - interval '1 hour', g.start_time, 'benchmark_synthetic',
                   'x', 'x', 10, 5, 20, 10, 4, 2, 1, 14, 12, 6, 16, '{}', '{}', '{}', '[]', '{}'
            FROM player_game_stats p JOIN games g ON g.id = p.game_id
            WHERE g.status = 'final' ORDER BY g.start_time DESC LIMIT 20000
            """
        ))
        t = time.perf_counter()
        counts = settle_forecasts(s)
        ms = (time.perf_counter() - t) * 1000
        t = time.perf_counter()
        again = settle_forecasts(s)
        noop = (time.perf_counter() - t) * 1000
        s.rollback()
    out["forecast_settlement_synthetic_rows_rolled_back"] = {"rows": int(sum(counts.values())), "by_status": counts, "ms": round(ms, 1),
                                                              "rows_per_second": round(sum(counts.values()) / (ms / 1000)),
                                                              "idempotent_rerun_changes": int(sum(again.values())), "idempotent_rerun_ms": round(noop, 1)}
    return out


SECTIONS = {"features": section_features, "inference": section_inference, "training": section_training, "api": section_api, "database": section_database}


def environment() -> dict:
    import numpy
    import pandas
    import sklearn
    import sqlalchemy

    def sh(cmd):
        try:
            return subprocess.check_output(cmd, shell=True, text=True, stderr=subprocess.DEVNULL).strip()
        except Exception:
            return None

    return {
        "label": "LOCAL DEVELOPMENT BENCHMARK (single machine; not production traffic)",
        "cpu": sh("sysctl -n machdep.cpu.brand_string"),
        "cpu_cores": os.cpu_count(),
        "memory_gb": round(int(sh("sysctl -n hw.memsize") or 0) / 2**30, 1),
        "os": platform.platform(),
        "python": platform.python_version(),
        "numpy": numpy.__version__,
        "pandas": pandas.__version__,
        "scikit_learn": sklearn.__version__,
        "sqlalchemy": sqlalchemy.__version__,
        "postgres": sh("docker exec $(docker ps -qf publish=5433 | head -1) postgres --version"),
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sections", default="features,inference,database,api,training")
    ap.add_argument("--child", default=None)
    args = ap.parse_args()
    if args.child:
        os.environ.update(SAFE_ENV)
        res = SECTIONS[args.child]()
        Path(os.environ["BENCH_OUT"]).write_text(json.dumps(res, default=str))
        return
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / "benchmark_results.json"
    results = json.loads(path.read_text()) if path.exists() else {}
    results["environment"] = environment()
    for name in args.sections.split(","):
        print(f"[{time.strftime('%H:%M:%S')}] section {name}", flush=True)
        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tf:
            tmp = tf.name
        t = time.perf_counter()
        proc = subprocess.Popen([sys.executable, __file__, "--child", name], cwd=BACKEND, env={**os.environ, **SAFE_ENV, "BENCH_OUT": tmp})
        _, status, ru = os.wait4(proc.pid, 0)
        if status != 0:
            results[name] = {"error": f"exit status {status}"}
            continue
        res = json.loads(Path(tmp).read_text())
        res["section_wall_seconds"] = round(time.perf_counter() - t, 1)
        res["section_peak_rss_mb"] = round(ru.ru_maxrss / 2**20, 1)  # macOS reports bytes
        results[name] = res
        path.write_text(json.dumps(results, indent=2, default=str))
    print(f"wrote {path}")
    _ = resource


if __name__ == "__main__":
    main()
