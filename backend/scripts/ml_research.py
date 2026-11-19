"""Offline research validation for the ACTIVE v2 engine (read-only; never promotes or retrains it).

Reproduces the held-out test predictions from the saved protocol, then runs:
  1. dataset accounting (every exclusion, reconciled to the manifest)
  2. game-clustered paired bootstrap CIs for MAE improvements (B=2000)
  3. an 8-window expanding walk-forward backtest with the *already selected* specs (no re-selection)
  4. predictive interval coverage/width (50/80/90) vs simple baseline intervals, by slice
  5. a controlled v1 comparison (v1 features refit on the same window, with/without the leaky starter flag)
  6. real archived sportsbook line validation (counts, Brier, log loss, ECE, reliability, de-vigged market)

Usage: cd backend && .venv/bin/python scripts/ml_research.py [--boot 2000] [--skip-walk-forward]
Output: artifacts/ml/research/research_results.json (+ test_predictions.csv.gz)
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from sqlalchemy import text  # noqa: E402

from app.db import session_scope  # noqa: E402
from app.ml.engine import artifacts as art  # noqa: E402
from app.ml.engine.data import ALL_CATEGORIES, TARGETS, components, load_raw, validate_and_clean  # noqa: E402
from app.ml.engine.evaluation import (  # noqa: E402
    pct_improvement,
    regression_metrics,
    vectorized_category_quantiles,
)
from app.ml.engine.features import CORE_FEATURES, FULL_FEATURES, build_features  # noqa: E402
from app.ml.engine.models import BASELINES, CANDIDATES, BaselineModel, baseline_predict  # noqa: E402
from app.ml.engine.training import (  # noqa: E402
    MIN_EVAL_APPEARANCES,
    _fit_spec,
    _old_model_predictions,
    load_archived_lines,
    real_line_eval,
    split_by_date,
)

OUT = BACKEND / "artifacts" / "ml" / "research"
SEED = 20261118

WALK_FORWARD = [
    ("W1", "2025-01-15", "2025-02-28", "pre-selection (out-of-time)"),
    ("W2", "2025-03-01", "2025-04-13", "pre-selection (out-of-time)"),
    ("W3", "2025-04-14", "2025-06-30", "pre-selection (out-of-time, 2025 playoffs)"),
    ("W4", "2025-10-21", "2026-01-14", "pre-selection (out-of-time)"),
    ("W5", "2026-01-15", "2026-02-28", "validation period (used for model selection)"),
    ("W6", "2026-03-01", "2026-04-12", "validation period (used for model selection)"),
    ("W7", "2026-04-13", "2026-06-30", "test period (2026 playoffs)"),
    ("W8", "2026-10-01", "2026-11-16", "test period (2026-27 early season)"),
]


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


# ---------------------------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------------------------
def cluster_bootstrap(ae_model: np.ndarray, ae_base: np.ndarray, clusters: np.ndarray, B: int, rng) -> dict:
    """Paired bootstrap resampling whole clusters (games or dates). Returns CI of MAE_base - MAE_model."""
    codes, uniq = pd.factorize(clusters)
    G = len(uniq)
    s_m = np.bincount(codes, weights=ae_model, minlength=G)
    s_b = np.bincount(codes, weights=ae_base, minlength=G)
    n_c = np.bincount(codes, minlength=G).astype(float)
    W = rng.multinomial(G, np.full(G, 1.0 / G), size=B).astype(float)
    n = W @ n_c
    mae_m = (W @ s_m) / n
    mae_b = (W @ s_b) / n
    diff = mae_b - mae_m
    pct = diff / mae_b * 100
    point_diff = float(ae_base.mean() - ae_model.mean())
    return {
        "clusters": int(G),
        "observations": int(len(ae_model)),
        "mae_model": float(ae_model.mean()),
        "mae_baseline": float(ae_base.mean()),
        "mae_improvement": point_diff,
        "pct_improvement": float(point_diff / ae_base.mean() * 100),
        "ci95_improvement": [float(np.percentile(diff, 2.5)), float(np.percentile(diff, 97.5))],
        "ci95_pct_improvement": [float(np.percentile(pct, 2.5)), float(np.percentile(pct, 97.5))],
        "bootstrap_share_not_improved": float(np.mean(diff <= 0)),
        "supports_positive_improvement": bool(np.percentile(diff, 2.5) > 0),
    }


def iid_bootstrap_ci(ae_model: np.ndarray, ae_base: np.ndarray, B: int, rng) -> list[float]:
    d = ae_base - ae_model
    n = len(d)
    idx = rng.integers(0, n, size=(B, n))
    means = d[idx].mean(axis=1)
    return [float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5))]


# ---------------------------------------------------------------------------------------------
def cat_sum(frame: pd.DataFrame, cat: str, prefix: str) -> np.ndarray:
    return sum(frame[f"{prefix}{c}"].to_numpy(dtype=float) for c in components(cat))


def baseline_cat(frame: pd.DataFrame, cat: str, kind: str) -> np.ndarray:
    return sum(np.nan_to_num(baseline_predict(frame, c, kind)) for c in components(cat))


def fit_selected(selected: dict[str, str], rows: pd.DataFrame) -> dict:
    models = {}
    for stat in TARGETS:
        sel = selected[stat]
        if sel.startswith("baseline_"):
            models[stat] = BaselineModel(stat, sel.removeprefix("baseline_"))
        else:
            models[stat] = _fit_spec(next(c for c in CANDIDATES if c.name == sel), stat, rows)
    return models


def tiers(df: pd.DataFrame, train: pd.DataFrame) -> dict[str, pd.Series]:
    mins = df["minutes_l10"].fillna(0)
    vol_q = train["minutes_std10"].quantile([0.25, 0.75]).to_numpy()
    return {
        "minutes_tier_l10": pd.cut(mins, [0, 15, 25, 32, 100], labels=["<15", "15-25", "25-32", "32+"], right=False).astype(str),
        "usage_tier_fga_share_l10": pd.cut(df["fga_share_l10"], [-1, 0.12, 0.2, 2], labels=["low <12%", "mid 12-20%", "high 20%+"], right=False).astype(str),
        "history_appearances": pd.cut(df["appearances"], [0, 10, 30, 80, 10_000], labels=["3-9", "10-29", "30-79", "80+"], right=False).astype(str),
        "minutes_volatility_std10": pd.cut(
            df["minutes_std10"], [-1, vol_q[0], vol_q[1], 1e9], labels=[f"stable <{vol_q[0]:.1f}", "middle", f"volatile >{vol_q[1]:.1f}"]
        ).astype(str),
        "role_change": pd.Series(
            np.where((df["team_changed"] == 1) | (df["minutes_trend"].abs() >= 6), "role_change", "stable_role"), index=df.index
        ),
        "season_phase": pd.Series(
            np.where(df["season_type"] == 3, "playoffs", np.where(df["team_season_games"] < 20, "early (<20 team games)",
                     np.where(df["team_season_games"] < 60, "mid (20-59)", "late (60+)"))), index=df.index
        ),
    }


# ---------------------------------------------------------------------------------------------
def accounting(raw: pd.DataFrame, clean: pd.DataFrame, rep, feats: pd.DataFrame, manifest: dict, val_start, test_start) -> dict:
    played = clean[~clean["did_not_play"]]
    bad = ~played["appeared"] & played["minutes"].fillna(0).gt(0)
    usable = feats[feats["usable_target"]]
    first_app = usable[usable["appearances"] < 1]
    modeled = usable[usable["appearances"] >= 1]
    train, val, test = split_by_date(modeled, val_start, test_start)
    val_low = val[val["appearances"] < MIN_EVAL_APPEARANCES]
    test_low = test[test["appearances"] < MIN_EVAL_APPEARANCES]
    out = {
        "db_rows_final_games": int(len(raw)),
        "duplicates_removed": rep.duplicate_player_game,
        "self_opponent_removed": rep.self_opponent_rows,
        "dnp_rows": rep.rows_dnp,
        "played_rows": rep.rows_played,
        "played_excluded": {
            "missing_minutes": int(played["minutes"].isna().sum()),
            "zero_minutes": int((played["minutes"] == 0).sum()),
            "implausible_or_negative_values": int(bad.sum()),
            "missing_target_stats_with_minutes": int((played["appeared"] & ~played["usable_target"]).sum()),
            "total": rep.excluded_rows,
        },
        "usable_target_rows": int(clean["usable_target"].sum()),
        "first_career_appearance_in_data_excluded": int(len(first_app)),
        "modeled_rows": int(len(modeled)),
        "train_rows": int(len(train)),
        "val_rows_all": int(len(val)),
        "val_rows_excluded_lt3_prior_appearances": int(len(val_low)),
        "val_eval_rows": int(len(val) - len(val_low)),
        "test_rows_all": int(len(test)),
        "test_rows_excluded_lt3_prior_appearances": int(len(test_low)),
        "test_eval_rows": int(len(test) - len(test_low)),
        "deploy_fit_rows": int(len(train) + len(val) + len(test)),
        "manifest_rows": manifest["split"]["rows"],
        "players": int(clean["player_id"].nunique()),
        "teams": int(clean["team_id"].nunique()),
        "games": int(clean["game_id"].nunique()),
        "seasons": sorted(int(s) for s in clean["season"].unique()),
        "feature_columns": {"core": len(CORE_FEATURES), "full": len(FULL_FEATURES), "union_used": len(set(CORE_FEATURES) | set(FULL_FEATURES))},
    }
    eval_sum = out["train_rows"] + out["val_eval_rows"] + out["test_eval_rows"]
    out["reconciliation"] = {
        "train_plus_val_eval_plus_test_eval": eval_sum,
        "deploy_fit_minus_that": out["deploy_fit_rows"] - eval_sum,
        "explained_by_val_test_rows_with_1_or_2_prior_appearances": out["val_rows_excluded_lt3_prior_appearances"] + out["test_rows_excluded_lt3_prior_appearances"],
        "matches_manifest": out["train_rows"] == manifest["split"]["rows"]["train"]
        and out["val_eval_rows"] == manifest["split"]["rows"]["val_eval"]
        and out["test_eval_rows"] == manifest["split"]["rows"]["test_eval"]
        and out["deploy_fit_rows"] == manifest["split"]["rows"]["deploy_fit"],
    }
    out["chain_check"] = {
        "played_minus_excluded_eq_usable": rep.rows_played - rep.excluded_rows == out["usable_target_rows"],
        "usable_minus_first_app_eq_modeled": out["usable_target_rows"] - out["first_career_appearance_in_data_excluded"] == out["modeled_rows"],
        "dnp_plus_played_eq_rows_after_dedupe": rep.rows_dnp + rep.rows_played == rep.rows_total - rep.duplicate_player_game - rep.self_opponent_rows,
    }
    return out


def interval_report(test_e: pd.DataFrame, preds: np.ndarray, dist, val_e: pd.DataFrame, slices: dict) -> dict:
    qs = (0.05, 0.1, 0.25, 0.75, 0.9, 0.95)
    levels = {"50": (2, 3), "80": (1, 4), "90": (0, 5)}
    z = {"50": 0.6745, "80": 1.2816, "90": 1.6449}
    out = {}
    for cat in ALL_CATEGORIES:
        y = cat_sum(test_e, cat, "target_")
        q = vectorized_category_quantiles(dist, preds, cat, qs)
        base = baseline_cat(test_e, cat, "weighted")
        val_res = cat_sum(val_e, cat, "target_") - baseline_cat(val_e, cat, "weighted")
        res_q = np.quantile(val_res, qs)
        sd_hist = np.sqrt(sum(np.nan_to_num(test_e[f"{c}_std10"].to_numpy(dtype=float), nan=0.0) ** 2 for c in components(cat)))
        entry = {"n": int(len(y)), "model": {}, "baseline_global_residual_quantiles": {}, "baseline_player_std10_normal": {}}
        for lvl, (lo, hi) in levels.items():
            cov = (y >= q[:, lo]) & (y <= q[:, hi])
            w = q[:, hi] - q[:, lo]
            entry["model"][lvl] = {"coverage": float(cov.mean()), "mean_width": float(w.mean()), "median_width": float(np.median(w))}
            blo, bhi = np.clip(base + res_q[lo], 0, None), np.clip(base + res_q[hi], 0, None)
            bcov = (y >= blo) & (y <= bhi)
            entry["baseline_global_residual_quantiles"][lvl] = {"coverage": float(bcov.mean()), "mean_width": float((bhi - blo).mean()), "median_width": float(np.median(bhi - blo))}
            plo, phi = np.clip(base - z[lvl] * sd_hist, 0, None), base + z[lvl] * sd_hist
            pcov = (y >= plo) & (y <= phi)
            entry["baseline_player_std10_normal"][lvl] = {"coverage": float(pcov.mean()), "mean_width": float((phi - plo).mean()), "median_width": float(np.median(phi - plo))}
            if lvl == "80":
                entry["by_slice_80"] = {}
                for name, key in slices.items():
                    g = pd.DataFrame({"k": key.values, "cov": cov, "w": w, "bcov": bcov, "bw": bhi - blo, "ae": np.abs(preds_cat(preds, cat) - y)})
                    entry["by_slice_80"][name] = {
                        str(k): {
                            "n": int(len(v)),
                            "model_coverage": float(v["cov"].mean()),
                            "model_mean_width": float(v["w"].mean()),
                            "baseline_global_coverage": float(v["bcov"].mean()),
                            "baseline_global_mean_width": float(v["bw"].mean()),
                            "model_mae": float(v["ae"].mean()),
                        }
                        for k, v in g.groupby("k")
                    }
        out[cat] = entry
    return out


def preds_cat(preds: np.ndarray, cat: str) -> np.ndarray:
    return sum(preds[:, TARGETS.index(c)] for c in components(cat))


def v1_controlled(session, test_e: pd.DataFrame, test_start: date) -> dict:
    """v1 feature set refit on the same pre-test window (HGB, v1's fillna(0)), with and without starter."""
    from app.ml.features import build_training_frame, feature_columns
    from app.ml.regressors import create_regressor

    f = build_training_frame(session)
    f = f[pd.to_datetime(f["start_time"], utc=True) <= test_e["start_time"].max()]
    cols = feature_columns()
    train = f[pd.to_datetime(f["start_time"], utc=True) < pd.Timestamp(test_start, tz="UTC")]
    keys = test_e[["player_id", "game_id"]].copy()
    out = {"v1_feature_columns": len(cols), "train_rows": int(len(train)), "variants": {}}
    for name, use in (("v1_refit_with_actual_starter_flag", cols), ("v1_refit_without_starter_flag", [c for c in cols if c != "starter_int"])):
        preds = f[["player_id", "game_id"]].copy()
        for stat in TARGETS:
            m = create_regressor()
            m.fit(train[use].fillna(0.0), train[f"target_{stat}"].astype(float))
            preds[f"v1_{stat}"] = np.clip(m.predict(f[use].fillna(0.0)), 0, None)
        out["variants"][name] = keys.merge(preds, on=["player_id", "game_id"], how="left")
    return out


def market_bootstrap(lines: pd.DataFrame, test_e: pd.DataFrame, preds: np.ndarray, dist, B: int, rng) -> dict:
    """Game-clustered bootstrap of Brier(market de-vigged) - Brier(model) on two-way priced book lines."""
    from app.ml.engine.evaluation import american_to_prob, vectorized_category_probs

    key = test_e[["player_id", "game_id"]].reset_index(drop=True).assign(_row=np.arange(len(test_e)))
    out = {}
    for cat in ALL_CATEGORIES:
        sub = lines[lines["category_key"] == cat]
        tw = sub.pivot_table(index=["sportsbook_label", "player_id", "game_id", "line"], columns="pick_side", values="american_odds", aggfunc="last").dropna()
        if tw.empty or not {"over", "under"} <= set(tw.columns):
            continue
        tw = tw.reset_index().merge(key, on=["player_id", "game_id"], how="inner")
        r = tw["_row"].to_numpy()
        actual = sum(test_e[f"target_{c}"].to_numpy(dtype=float)[r] for c in components(cat))
        ln = tw["line"].to_numpy(dtype=float)
        po, pu, _, _, _ = vectorized_category_probs(dist, preds[r], cat, ln)
        p_model = po / np.clip(po + pu, 1e-9, None)
        o, u = tw["over"].map(american_to_prob).to_numpy(dtype=float), tw["under"].map(american_to_prob).to_numpy(dtype=float)
        p_mkt = o / (o + u)
        keep = actual != ln
        y = (actual > ln).astype(float)[keep]
        se_model, se_mkt = (p_model[keep] - y) ** 2, (p_mkt[keep] - y) ** 2
        res = cluster_bootstrap(se_model, se_mkt, tw["game_id"].to_numpy()[keep], B, rng)
        out[cat] = {"book_lines": int(keep.sum()), "games": res["clusters"], "brier_model": res["mae_model"], "brier_market": res["mae_baseline"],
                    "market_minus_model": res["mae_improvement"], "ci95_market_minus_model": res["ci95_improvement"],
                    "model_better_ci_excludes_zero": res["supports_positive_improvement"],
                    "market_better_ci_excludes_zero": bool(res["ci95_improvement"][1] < 0)}
    out["note"] = "Brier on overlapping book lines (same player-game across books is correlated; games are the resampling unit). Not a profitability test: no vig, staking, or line selection."
    return out


# ---------------------------------------------------------------------------------------------
def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--boot", type=int, default=2000)
    ap.add_argument("--skip-walk-forward", action="store_true")
    args = ap.parse_args()
    rng = np.random.default_rng(SEED)
    OUT.mkdir(parents=True, exist_ok=True)
    t_start = time.perf_counter()
    results: dict = {"generated_by": "scripts/ml_research.py", "bootstrap_replications": args.boot, "seed": SEED}

    bundle = art.load_bundle(art.active_version())
    manifest, metrics = bundle.manifest, json.loads((art.ROOT / bundle.version / "metrics.json").read_text())
    selected = manifest["selected_models"]
    val_start = date.fromisoformat(manifest["split"]["val_start"])
    test_start = date.fromisoformat(manifest["split"]["test_start"])
    cutoff = pd.Timestamp(manifest["dataset_cutoff"])
    results["model_version"] = bundle.version
    results["selected_models"] = selected

    log("Loading data (restricted to the training dataset cutoff for exact reproduction)")
    with session_scope() as session:
        raw_all = load_raw(session)
        raw = raw_all[raw_all["start_time"] <= cutoff].reset_index(drop=True)
        results["rows_after_cutoff_excluded"] = int(len(raw_all) - len(raw))
        clean, rep = validate_and_clean(raw)
        feats = build_features(clean)
        results["dataset_accounting"] = accounting(raw, clean, rep, feats, manifest, val_start, test_start)
        log(f"Accounting: {results['dataset_accounting']['reconciliation']}")

        modeled = feats[feats["usable_target"] & (feats["appearances"] >= 1)].copy()
        train, val, test = split_by_date(modeled, val_start, test_start)
        val_e = val[val["appearances"] >= MIN_EVAL_APPEARANCES]
        test_e = test[test["appearances"] >= MIN_EVAL_APPEARANCES]

        log("Reproducing fold-2 test predictions (train+val refit of the selected specs)")
        t0 = time.perf_counter()
        fold2 = fit_selected(selected, pd.concat([train, val]))
        preds = np.column_stack([fold2[s].predict(test_e) for s in TARGETS])
        results["fold2_refit_seconds"] = round(time.perf_counter() - t0, 2)
        repro = {}
        for cat in ALL_CATEGORIES:
            mae = regression_metrics(cat_sum(test_e, cat, "target_"), preds_cat(preds, cat))["mae"]
            repro[cat] = {"reproduced_mae": mae, "manifest_mae": metrics["test"][cat]["model"]["mae"], "abs_diff": abs(mae - metrics["test"][cat]["model"]["mae"])}
        results["reproduction"] = repro
        log(f"Reproduction max |diff| = {max(r['abs_diff'] for r in repro.values()):.2e}")

        old = _old_model_predictions(session, test_e)
        log("Controlled v1 refits (same pre-test window)")
        v1c = v1_controlled(session, test_e, test_start)
        archived = load_archived_lines(session)
        line_counts = session.execute(
            text(
                """
                SELECT COUNT(*) AS snapshots,
                       COUNT(*) FILTER (WHERE result IS NOT NULL) AS settled,
                       COUNT(*) FILTER (WHERE result IN ('hit','miss','push')) AS graded,
                       COUNT(DISTINCT game_id) AS games,
                       COUNT(DISTINCT offer_id) AS distinct_offers,
                       COUNT(DISTINCT (player_id, game_id, category_key, line)) AS unique_player_game_cat_line,
                       COUNT(DISTINCT (category_key, line)) AS distinct_thresholds,
                       COUNT(DISTINCT sportsbook_label) AS sportsbooks,
                       MIN(game_start_time) AS first_game, MAX(game_start_time) AS last_game
                FROM prop_offer_snapshots WHERE NOT is_alternate_line
                """
            )
        ).mappings().one()
    results["v1_frame_note"] = "v1 bundle trained on rows before 2026-01-10; uses the target game's actual starter flag"

    # ---- paired, clustered bootstrap on the untouched test period ----------------------------
    log(f"Cluster bootstrap (B={args.boot}) on {len(test_e):,} test rows")
    boot: dict = {}
    clusters_game = test_e["game_id"].to_numpy()
    clusters_date = test_e["game_date"].dt.date.astype(str).to_numpy()
    for cat in ALL_CATEGORIES:
        y = cat_sum(test_e, cat, "target_")
        ae_m = np.abs(preds_cat(preds, cat) - y)
        comps = {k: np.abs(baseline_cat(test_e, cat, k) - y) for k in BASELINES}
        best = min(comps, key=lambda k: comps[k].mean())
        entry = {"best_baseline_on_test (oracle, conservative)": best, "vs": {}}
        for k, ae_b in comps.items():
            e = cluster_bootstrap(ae_m, ae_b, clusters_game, args.boot, rng)
            if k == best:
                e["cluster_by_game_date"] = cluster_bootstrap(ae_m, ae_b, clusters_date, args.boot, rng)
                e["iid_rows_ci95_improvement (for contrast; ignores clustering)"] = iid_bootstrap_ci(ae_m, ae_b, args.boot, rng)
            entry["vs"][k] = e
        if old is not None:
            o = cat_sum(old, cat, "old_")
            ok = np.isfinite(o)
            entry["vs"]["v1_saved_bundle"] = cluster_bootstrap(ae_m[ok], np.abs(o[ok] - y[ok]), clusters_game[ok], args.boot, rng)
        for vname, vp in v1c["variants"].items():
            o = cat_sum(vp, cat, "v1_")
            ok = np.isfinite(o)
            entry["vs"][vname] = cluster_bootstrap(ae_m[ok], np.abs(o[ok] - y[ok]), clusters_game[ok], args.boot, rng)
        boot[cat] = entry
    results["test_bootstrap"] = boot
    results["v1_controlled"] = {k: v for k, v in v1c.items() if k != "variants"}

    # ---- slices on test: model vs every baseline --------------------------------------------
    sl = tiers(test_e, train)
    slices_out = {}
    for cat in ("pts", "reb", "ast", "fg3m", "pts_reb_ast"):
        y = cat_sum(test_e, cat, "target_")
        df = pd.DataFrame({"y": y, "m": preds_cat(preds, cat), **{k: baseline_cat(test_e, cat, k) for k in BASELINES}})
        slices_out[cat] = {}
        for name, key in sl.items():
            slices_out[cat][name] = {}
            for k, g in df.groupby(key.values):
                maes = {b: float(np.mean(np.abs(g[b] - g["y"]))) for b in BASELINES}
                mm = float(np.mean(np.abs(g["m"] - g["y"])))
                best = min(maes, key=maes.get)
                slices_out[cat][name][str(k)] = {"n": int(len(g)), "model_mae": mm, "baseline_mae": maes, "best_baseline": best,
                                                 "pct_vs_best_baseline": pct_improvement(maes[best], mm)}
    results["test_slices"] = slices_out

    # ---- uncertainty ---------------------------------------------------------------------------
    log("Interval coverage and width")
    results["intervals_test"] = interval_report(test_e, preds, bundle.distribution, val_e, sl)
    results["intervals_note"] = (
        "Model intervals: quantiles of round(mean + joint validation residual vector) for the row's projected-PRA bin "
        "(fit on VALIDATION residuals, scored on TEST). Baselines: weighted baseline +/- global validation residual "
        "quantiles, and weighted baseline +/- z * player's 10-game std (normal). Outcomes are integers; bounds are inclusive."
    )
    results["low_frequency_categories"] = "steals/blocks are stored in player_game_stats but are not v2 model targets; no intervals are produced or claimed"

    # ---- real sportsbook lines -----------------------------------------------------------------
    log("Real archived line validation")
    real = real_line_eval(archived, test_e, preds, bundle.distribution)
    results["real_lines"] = {"archive_counts": dict(line_counts), "evaluation": real, "gates": manifest["probability_gates"], "probability_status": manifest["probability_status"],
                             "model_vs_devigged_market_brier_bootstrap": market_bootstrap(archived, test_e, preds, bundle.distribution, args.boot, rng)}

    # ---- walk-forward --------------------------------------------------------------------------
    if not args.skip_walk_forward:
        wf = []
        pooled = []
        for name, a, b, role in WALK_FORWARD:
            a_ts, b_ts = pd.Timestamp(a), pd.Timestamp(b)
            tr = modeled[modeled["game_date"] < a_ts]
            ev = modeled[(modeled["game_date"] >= a_ts) & (modeled["game_date"] <= b_ts) & (modeled["appearances"] >= MIN_EVAL_APPEARANCES)]
            if len(ev) < 500 or len(tr) < 5000:
                continue
            t0 = time.perf_counter()
            models = fit_selected(selected, tr)
            p = np.column_stack([models[s].predict(ev) for s in TARGETS])
            fold = {"fold": name, "eval_dates": [a, b], "role": role, "train_rows": int(len(tr)), "train_end": str(tr["game_date"].max().date()),
                    "eval_rows": int(len(ev)), "eval_games": int(ev["game_id"].nunique()), "fit_seconds": round(time.perf_counter() - t0, 1), "categories": {}}
            for cat in ALL_CATEGORIES:
                y = cat_sum(ev, cat, "target_")
                ae_m = np.abs(preds_cat(p, cat) - y)
                bm = {k: np.abs(baseline_cat(ev, cat, k) - y) for k in BASELINES}
                best = min(bm, key=lambda k: bm[k].mean())
                fold["categories"][cat] = {
                    "model_mae": float(ae_m.mean()),
                    "baseline_mae": {k: float(v.mean()) for k, v in bm.items()},
                    "best_baseline": best,
                    "vs_weighted": cluster_bootstrap(ae_m, bm["weighted"], ev["game_id"].to_numpy(), args.boot, rng),
                    "vs_best": cluster_bootstrap(ae_m, bm[best], ev["game_id"].to_numpy(), args.boot, rng),
                }
            wf.append(fold)
            pooled.append(pd.DataFrame({"fold": name, "game_id": ev["game_id"].to_numpy(), "phase": tiers(ev, tr)["season_phase"].to_numpy(),
                                        **{f"m_{c}": preds_cat(p, c) for c in ALL_CATEGORIES},
                                        **{f"y_{c}": cat_sum(ev, c, "target_") for c in ALL_CATEGORIES},
                                        **{f"b_{c}": baseline_cat(ev, c, "weighted") for c in ALL_CATEGORIES}}))
            log(f"{name} {role}: train {len(tr):,} eval {len(ev):,}  PTS {pct_improvement(fold['categories']['pts']['baseline_mae']['weighted'], fold['categories']['pts']['model_mae']):+.2f}% vs weighted")
        results["walk_forward"] = wf
        pool = pd.concat(pooled)
        phase = {}
        for ph, g in pool.groupby("phase"):
            phase[ph] = {cat: {"n": int(len(g)), "model_mae": float(np.mean(np.abs(g[f"m_{cat}"] - g[f"y_{cat}"]))),
                               "weighted_baseline_mae": float(np.mean(np.abs(g[f"b_{cat}"] - g[f"y_{cat}"])))} for cat in ("pts", "reb", "ast", "pts_reb_ast")}
            for cat in phase[ph]:
                phase[ph][cat]["pct_vs_weighted"] = pct_improvement(phase[ph][cat]["weighted_baseline_mae"], phase[ph][cat]["model_mae"])
        results["walk_forward_pooled_by_season_phase"] = phase
        for label, folds in (("walk_forward_pooled_pre_selection", ["W1", "W2", "W3", "W4"]),
                             ("walk_forward_pooled_pre_selection_regular_season", ["W1", "W2", "W4"]),
                             ("walk_forward_pooled_all_folds", [w[0] for w in WALK_FORWARD])):
            pre = pool[pool["fold"].isin(folds)]
            results[label] = {
                cat: cluster_bootstrap(np.abs(pre[f"m_{cat}"] - pre[f"y_{cat}"]).to_numpy(), np.abs(pre[f"b_{cat}"] - pre[f"y_{cat}"]).to_numpy(),
                                       (pre["fold"] + ":" + pre["game_id"].astype(str)).to_numpy(), args.boot, rng)
                for cat in ALL_CATEGORIES
            }

    pd.DataFrame({"player_id": test_e["player_id"].to_numpy(), "game_id": test_e["game_id"].to_numpy(), "game_date": test_e["game_date"].dt.date.astype(str).to_numpy(),
                  **{f"pred_{s}": preds[:, i] for i, s in enumerate(TARGETS)},
                  **{f"actual_{s}": test_e[f"target_{s}"].to_numpy() for s in TARGETS},
                  **{f"baseline_weighted_{s}": np.nan_to_num(baseline_predict(test_e, s, "weighted")) for s in TARGETS}}).to_csv(OUT / "test_predictions.csv.gz", index=False)
    results["runtime_seconds"] = round(time.perf_counter() - t_start, 1)
    (OUT / "research_results.json").write_text(json.dumps(results, indent=2, default=str))
    log(f"Wrote {OUT / 'research_results.json'} in {results['runtime_seconds']}s")


if __name__ == "__main__":
    main()
