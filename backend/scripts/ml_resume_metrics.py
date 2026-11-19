"""Build artifacts/ml/research/resume_metrics.json from the saved research + benchmark results.

Every number is read from research_results.json / benchmark_results.json (or the live forecast
archive counts) and carries the JSON path it came from. Nothing is recomputed or estimated here.

Usage:  cd backend && PYTHONPATH=. .venv/bin/python scripts/ml_resume_metrics.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

OUT = BACKEND / "artifacts" / "ml" / "research"
CATS = ["pts", "reb", "ast", "fg3m", "pts_reb", "pts_ast", "reb_ast", "pts_reb_ast"]


def get(d: dict, path: str):
    cur = d
    for part in path.split("|"):
        cur = cur[part]
    return cur


def metric(src_name: str, src: dict, path: str, nd: int = 2):
    v = get(src, path)
    if isinstance(v, float):
        v = round(v, nd)
    elif isinstance(v, list):
        v = [round(x, nd) if isinstance(x, float) else x for x in v]
    return {"value": v, "source": f"{src_name}:{path}"}


def main() -> None:
    r = json.loads((OUT / "research_results.json").read_text())
    b = json.loads((OUT / "benchmark_results.json").read_text())
    R = lambda p, nd=2: metric("research_results.json", r, p, nd)  # noqa: E731
    B = lambda p, nd=2: metric("benchmark_results.json", b, p, nd)  # noqa: E731

    test = {}
    for c in CATS:
        best = r["test_bootstrap"][c]["best_baseline_on_test (oracle, conservative)"]
        base = f"test_bootstrap|{c}|vs"
        test[c] = {
            "best_baseline": best,
            "pct_vs_best_baseline": R(f"{base}|{best}|pct_improvement"),
            "ci95_pct_vs_best_baseline_game_clustered": R(f"{base}|{best}|ci95_pct_improvement"),
            "pct_vs_last_10": R(f"{base}|last_10|pct_improvement"),
            "pct_vs_season_avg": R(f"{base}|season_avg|pct_improvement"),
            "pct_vs_v1_saved_bundle": R(f"{base}|v1_saved_bundle|pct_improvement"),
            "ci95_pct_vs_v1_saved_bundle": R(f"{base}|v1_saved_bundle|ci95_pct_improvement"),
            "pct_vs_v1_refit_without_starter_flag": R(f"{base}|v1_refit_without_starter_flag|pct_improvement"),
            "ci95_pct_vs_v1_refit_without_starter_flag": R(f"{base}|v1_refit_without_starter_flag|ci95_pct_improvement"),
            "model_mae": R(f"{base}|{best}|mae_model", 3),
        }

    pooled = {}
    for key in ("walk_forward_pooled_pre_selection", "walk_forward_pooled_pre_selection_regular_season", "walk_forward_pooled_all_folds"):
        pooled[key] = {c: {"pct_vs_weighted": R(f"{key}|{c}|pct_improvement"), "ci95": R(f"{key}|{c}|ci95_pct_improvement"),
                           "observations": R(f"{key}|{c}|observations"), "game_clusters": R(f"{key}|{c}|clusters")} for c in ("pts", "reb", "ast", "pts_reb_ast")}

    folds = [{"fold": f["fold"], "role": f["role"], "eval_dates": f["eval_dates"], "eval_rows": f["eval_rows"],
              "pts_pct_vs_weighted": round(f["categories"]["pts"]["vs_weighted"]["pct_improvement"], 2),
              "pts_ci95": [round(x, 2) for x in f["categories"]["pts"]["vs_weighted"]["ci95_pct_improvement"]]}
             for f in r["walk_forward"]]

    intervals = {c: {lvl: {"model_coverage": R(f"intervals_test|{c}|model|{lvl}|coverage", 3),
                           "model_mean_width": R(f"intervals_test|{c}|model|{lvl}|mean_width"),
                           "global_residual_baseline_coverage": R(f"intervals_test|{c}|baseline_global_residual_quantiles|{lvl}|coverage", 3),
                           "player_std_normal_baseline_coverage": R(f"intervals_test|{c}|baseline_player_std10_normal|{lvl}|coverage", 3)}
                     for lvl in ("50", "80", "90")} for c in ("pts", "pts_reb_ast")}

    market = {c: {"book_lines": R(f"real_lines|model_vs_devigged_market_brier_bootstrap|{c}|book_lines"),
                  "games": R(f"real_lines|model_vs_devigged_market_brier_bootstrap|{c}|games"),
                  "brier_model": R(f"real_lines|model_vs_devigged_market_brier_bootstrap|{c}|brier_model", 4),
                  "brier_market_devigged": R(f"real_lines|model_vs_devigged_market_brier_bootstrap|{c}|brier_market", 4),
                  "ci95_market_minus_model": R(f"real_lines|model_vs_devigged_market_brier_bootstrap|{c}|ci95_market_minus_model", 4),
                  "model_ece_unique_lines": R(f"real_lines|evaluation|categories|{c}|model|ece", 3)} for c in CATS}

    inf = "inference|scoring_real_feature_rows (4 component models + minutes model + 8-category quantiles)"
    api = {name: {"warm_p50_ms": B(f"api|endpoints|{name}|warm_sequential|p50_ms", 1),
                  "warm_p95_ms": B(f"api|endpoints|{name}|warm_sequential|p95_ms", 1),
                  "first_request_ms": B(f"api|endpoints|{name}|first_request_ms", 1),
                  "error_rate": B(f"api|endpoints|{name}|error_rate")}
           for name in b["api"]["endpoints"]}
    for name, v in b["api"]["endpoints"].items():
        if "concurrent_8_clients_200_requests" in v:
            api[name]["throughput_rps_8_concurrent"] = B(f"api|endpoints|{name}|concurrent_8_clients_200_requests|throughput_rps", 1)

    try:
        from sqlalchemy import text

        from app.db import session_scope
        with session_scope() as s:
            rows = s.execute(text("SELECT status, count(*), count(DISTINCT game_id) FROM ml_forecasts GROUP BY status")).all()
            lines = s.execute(text("SELECT count(*) FROM ml_forecast_lines")).scalar_one()
        prospective = {"by_status": {st: {"forecasts": n, "games": g} for st, n, g in rows}, "lines": lines, "source": "live query of ml_forecasts"}
    except Exception as exc:  # noqa: BLE001
        prospective = {"error": f"database unavailable: {exc}"}

    out = {
        "generated_by": "scripts/ml_resume_metrics.py",
        "environment": b["environment"],
        "model_version": r["model_version"],
        "bootstrap": {"replications": r["bootstrap_replications"], "seed": r["seed"], "cluster": "game (primary); game-date and iid also reported in research_results.json"},
        "dataset": {k: R(f"dataset_accounting|{k}") for k in ("db_rows_final_games", "dnp_rows", "played_rows", "usable_target_rows", "modeled_rows", "train_rows", "val_eval_rows", "test_eval_rows")
                    if k in r["dataset_accounting"]},
        "reproduction_max_abs_mae_diff": max(v["abs_diff"] for v in r["reproduction"].values()),
        "test_period_accuracy": test,
        "walk_forward_folds": folds,
        "walk_forward_pooled": pooled,
        "intervals_test": intervals,
        "real_lines_model_vs_market": market,
        "real_lines_archive": R("real_lines|archive_counts"),
        "probability_status": R("real_lines|probability_status"),
        "engineering": {
            "training_wall_seconds": B("training|wall_seconds", 1),
            "training_peak_rss_mb": B("training|section_peak_rss_mb", 1),
            "artifact_size_mb": B("inference|artifact_size_mb"),
            "artifact_load_p50_ms": B("inference|artifact_load_warm_os_cache|p50_ms", 1),
            "feature_build_p50_ms": B("features|build_features|p50_ms", 1),
            "feature_rows_per_second_p50": B("features|feature_rows_per_second_p50", 0),
            "scoring": {n: {"p50_ms": B(f"{inf}|{n}|p50_ms", 1), "predictions_per_second": B(f"{inf}|{n}|predictions_per_second_p50", 0)} for n in ("1", "100", "500", "1000")},
            "batch_vs_per_row_500_speedup_x": B("inference|batch_vs_per_row_500|speedup_x", 1),
            "cached_single_projection_p50_ms": B("inference|service_project_single_cached|p50_ms", 2),
            "odds_settlement_rows_per_second": B("database|odds_snapshot_settlement_full_archive|rows_per_second_p50", 0),
            "forecast_settlement_rows_per_second_synthetic": B("database|forecast_settlement_synthetic_rows_rolled_back|rows_per_second", 0),
            "forecast_record_per_second": B("database|forecast_record_real_upcoming_rolled_back|forecasts_per_second", 0),
            "api": api,
            "api_server_peak_rss_mb": B("api|server_peak_rss_mb", 1),
        },
        "prospective_archive": prospective,
    }
    path = OUT / "resume_metrics.json"
    path.write_text(json.dumps(out, indent=2, default=str))
    print(f"wrote {path}")


if __name__ == "__main__":
    main()
