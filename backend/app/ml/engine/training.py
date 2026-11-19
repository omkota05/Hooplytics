"""Offline training + walk-forward evaluation for the v2 player-stat engine.

Protocol (all splits by game date; every row of a game lands in one partition):
  fold 1: fit on TRAIN, score on VALIDATION -> model selection, residual distribution, gates
  fold 2: refit the selected specs on TRAIN+VALIDATION, score once on TEST (untouched)
  deploy: refit the selected specs on all usable rows; distribution stays the fold-1
          out-of-sample residuals (never fit on the rows it is evaluated on).
"""

from __future__ import annotations

import logging
import time
from datetime import UTC, date, datetime
from typing import Any

import numpy as np
import pandas as pd
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.ml.engine import artifacts as art
from app.ml.engine.data import ALL_CATEGORIES, TARGETS, components, load_raw, validate_and_clean
from app.ml.engine.distribution import JointResidualDistribution
from app.ml.engine.evaluation import (
    american_to_prob,
    pct_improvement,
    prob_metrics,
    regression_metrics,
    slice_report,
    synthetic_threshold_eval,
    vectorized_category_probs,
)
from app.ml.engine.features import FEATURE_SETS, FEATURE_VERSION, build_features
from app.ml.engine.models import (
    BASELINES,
    CANDIDATES,
    BaselineModel,
    ComponentModel,
    baseline_predict,
    minutes_model,
)

logger = logging.getLogger("hooplytics.ml")

DEFAULT_VAL_START = date(2026, 1, 15)
DEFAULT_TEST_START = date(2026, 4, 13)
MIN_EVAL_APPEARANCES = 3
# Probability gates.
SYNTHETIC_MAX_ECE = 0.03
REAL_MIN_LINES = 300
REAL_MAX_ECE = 0.04


class Timer:
    def __init__(self) -> None:
        self.stages: dict[str, float] = {}
        self._t = time.perf_counter()

    def mark(self, name: str) -> float:
        now = time.perf_counter()
        self.stages[name] = round(now - self._t, 3)
        self._t = now
        return self.stages[name]


def _log(progress, msg: str) -> None:
    logger.info(msg)
    if progress:
        progress(msg)


def split_by_date(frame: pd.DataFrame, val_start: date, test_start: date):
    d = frame["game_date"].dt.date
    train = frame[d < val_start]
    val = frame[(d >= val_start) & (d < test_start)]
    test = frame[d >= test_start]
    for a, b in ((train, val), (val, test), (train, test)):
        if set(a["game_id"]) & set(b["game_id"]):
            raise AssertionError("A game appears in two partitions")
    if len(train) and len(val) and train["start_time"].max() >= val["start_time"].min():
        raise AssertionError("Train overlaps validation in time")
    if len(val) and len(test) and val["start_time"].max() >= test["start_time"].min():
        raise AssertionError("Validation overlaps test in time")
    return train, val, test


def _date_range(df: pd.DataFrame) -> list[str]:
    return [str(df["game_date"].min().date()), str(df["game_date"].max().date())] if len(df) else [None, None]


def _fit_spec(spec, stat: str, rows: pd.DataFrame) -> ComponentModel:
    y = rows[f"target_{stat}"].to_numpy(dtype=float)
    mins = rows["target_minutes"].to_numpy(dtype=float)
    return ComponentModel(spec, stat).fit(rows, y, minutes=mins)


def _permutation_importance(model: ComponentModel, rows: pd.DataFrame, stat: str, n: int = 4000, top: int = 15) -> list[dict]:
    rng = np.random.default_rng(42)
    sample = rows.sample(min(n, len(rows)), random_state=42)
    y = sample[f"target_{stat}"].to_numpy(dtype=float)
    base = float(np.mean(np.abs(model.predict(sample) - y)))
    out = []
    for col in model.features:
        deltas = []
        for _ in range(2):
            shuffled = sample.copy()
            shuffled[col] = rng.permutation(shuffled[col].to_numpy())
            deltas.append(float(np.mean(np.abs(model.predict(shuffled) - y))) - base)
        out.append({"feature": col, "mae_increase": float(np.mean(deltas))})
    out.sort(key=lambda r: -r["mae_increase"])
    return out[:top]


def _old_model_predictions(session: Session, keys: pd.DataFrame) -> pd.DataFrame | None:
    """Predictions of the previous (v1) bundle on the same rows, if its artifacts load."""
    try:
        from app.ml.artifacts import load_bundle as load_v1
        from app.ml.baselines import predict_baseline as v1_baseline
        from app.ml.features import build_training_frame as v1_frame

        b = load_v1()
        f = v1_frame(session)
        x = f[b.feature_columns].fillna(0.0)
        out = f[["player_id", "game_id"]].copy()
        for stat in ("pts", "reb", "ast", "fg3m"):
            if b.component_selected_model[stat] == "ml":
                out[f"old_{stat}"] = b.ml_models[stat].predict(x)
            else:
                out[f"old_{stat}"] = v1_baseline(f, stat, b.component_baseline_kind[stat])
        out = keys[["player_id", "game_id"]].merge(out, on=["player_id", "game_id"], how="left")
        out.attrs["version"] = b.version
        return out
    except Exception as exc:  # old artifacts are optional
        logger.warning("Old model comparison unavailable: %s", exc)
        return None


def load_archived_lines(session: Session) -> pd.DataFrame:
    rows = session.execute(
        text(
            """
            SELECT player_id, game_id, category_key, line, pick_side, sportsbook_label, american_odds,
                   result, last_observed_at, game_start_time
            FROM prop_offer_snapshots
            WHERE result IN ('hit','miss','push') AND is_alternate_line = false
              AND last_observed_at < game_start_time AND player_id IS NOT NULL
            """
        )
    ).mappings().all()
    return pd.DataFrame(rows)


def real_line_eval(lines: pd.DataFrame, test: pd.DataFrame, means: np.ndarray, dist: JointResidualDistribution) -> dict:
    """Score probabilities against genuine archived pregame lines (prospective, small sample)."""
    if lines.empty:
        return {"available": False, "reason": "no archived pregame lines"}
    key = test[["player_id", "game_id"]].reset_index(drop=True).assign(_row=np.arange(len(test)))
    out: dict[str, Any] = {"available": True, "categories": {}}
    lines = lines[lines["category_key"].isin(ALL_CATEGORIES)]
    merged = lines.merge(key, on=["player_id", "game_id"], how="inner")
    out["offers_matched_to_test_rows"] = int(len(merged))
    out["offers_total_graded"] = int(len(lines))
    if merged.empty:
        out["available"] = False
        out["reason"] = "archived lines do not overlap test rows"
        return out
    out["date_range"] = [str(merged["game_start_time"].min()), str(merged["game_start_time"].max())]
    out["games"] = int(merged["game_id"].nunique())
    for cat in ALL_CATEGORIES:
        sub = merged[merged["category_key"] == cat]
        if sub.empty:
            continue
        uniq = sub.drop_duplicates(["player_id", "game_id", "line"])[["player_id", "game_id", "line", "_row"]]
        r = uniq["_row"].to_numpy()
        po, pu, pp, _, _ = vectorized_category_probs(dist, means[r], cat, uniq["line"].to_numpy(dtype=float))
        actual = sum(test[f"target_{c}"].to_numpy(dtype=float)[r] for c in components(cat))
        line = uniq["line"].to_numpy(dtype=float)
        nonpush = actual != line
        p_cond = po / np.clip(po + pu, 1e-9, None)
        y = (actual > line).astype(float)
        model_m = prob_metrics(p_cond[nonpush], y[nonpush])
        # Market comparison: de-vigged two-way price at the same book and line.
        two_way = sub.pivot_table(index=["sportsbook_label", "player_id", "game_id", "line"], columns="pick_side", values="american_odds", aggfunc="last").dropna()
        market = None
        if not two_way.empty and {"over", "under"} <= set(two_way.columns):
            tw = two_way.reset_index()
            po_m = tw["over"].map(american_to_prob)
            pu_m = tw["under"].map(american_to_prob)
            tw["p_mkt"] = po_m / (po_m + pu_m)
            tw["overround"] = po_m + pu_m - 1
            tw = tw.merge(uniq.assign(p_model=p_cond, actual=actual), on=["player_id", "game_id", "line"], how="inner")
            tw = tw[tw["actual"] != tw["line"]]
            if len(tw):
                yy = (tw["actual"] > tw["line"]).astype(float).to_numpy()
                market = {
                    "n_book_lines": int(len(tw)),
                    "model": {k: v for k, v in prob_metrics(tw["p_model"].to_numpy(), yy).items() if k != "reliability"},
                    "market_devigged": {k: v for k, v in prob_metrics(tw["p_mkt"].to_numpy(), yy).items() if k != "reliability"},
                    "mean_overround": float(tw["overround"].mean()),
                }
        out["categories"][cat] = {
            "unique_lines": int(len(uniq)),
            "pushes_excluded": int((~nonpush).sum()),
            "model": model_m,
            "constant_half": {k: v for k, v in prob_metrics(np.full(int(nonpush.sum()), 0.5), y[nonpush]).items() if k != "reliability"},
            "market_comparison": market,
            "books": sub["sportsbook_label"].value_counts().head(15).to_dict(),
        }
    return out


def _probability_gates(synth: dict, real: dict) -> tuple[dict[str, str], dict[str, dict]]:
    status: dict[str, str] = {}
    detail: dict[str, dict] = {}
    for cat in ALL_CATEGORIES:
        s = synth[cat]
        emp = s["empirical_joint"]
        synth_ok = emp["ece"] <= SYNTHETIC_MAX_ECE and emp["brier"] < s["climatology_constant"]["brier"]
        rc = (real.get("categories") or {}).get(cat)
        real_ok = False
        if rc:
            m = rc["model"]
            real_ok = rc["unique_lines"] >= REAL_MIN_LINES and m["ece"] <= REAL_MAX_ECE and m["brier"] < rc["constant_half"]["brier"]
        status[cat] = "validated_real_lines" if (synth_ok and real_ok) else ("experimental" if synth_ok else "unavailable")
        detail[cat] = {
            "synthetic_ece": emp["ece"],
            "synthetic_brier": emp["brier"],
            "synthetic_climatology_brier": s["climatology_constant"]["brier"],
            "synthetic_pass": synth_ok,
            "real_unique_lines": rc["unique_lines"] if rc else 0,
            "real_ece": rc["model"]["ece"] if rc else None,
            "real_brier": rc["model"]["brier"] if rc else None,
            "real_constant_brier": rc["constant_half"]["brier"] if rc else None,
            "real_pass": real_ok,
        }
    return status, detail


def train_engine(
    session: Session,
    *,
    val_start: date = DEFAULT_VAL_START,
    test_start: date = DEFAULT_TEST_START,
    quick: bool = False,
    promote_if_valid: bool = True,
    progress=None,
) -> dict:
    timer = Timer()
    _log(progress, "[1/8] Loading player-game rows from PostgreSQL")
    raw = load_raw(session)
    clean, report = validate_and_clean(raw)
    timer.mark("load_and_validate")

    _log(progress, f"[2/8] Building leakage-safe features for {len(clean):,} rows")
    feats = build_features(clean)
    timer.mark("feature_engineering")
    modeled = feats[feats["usable_target"] & (feats["appearances"] >= 1)].copy()
    train, val, test = split_by_date(modeled, val_start, test_start)
    if quick:
        train = train.sample(min(len(train), 8000), random_state=42).sort_values("start_time")
    ev = lambda df: df[df["appearances"] >= MIN_EVAL_APPEARANCES]  # noqa: E731
    val_e, test_e = ev(val), ev(test)
    _log(progress, f"      train={len(train):,} val={len(val_e):,} test={len(test_e):,} (eval rows need >= {MIN_EVAL_APPEARANCES} prior appearances)")

    _log(progress, "[3/8] Fold 1: fitting baselines and candidates on TRAIN, scoring on VALIDATION")
    candidates = CANDIDATES if not quick else CANDIDATES[:2]
    selection: dict[str, dict] = {}
    fold1_models: dict[str, Any] = {}
    for stat in TARGETS:
        y_val = val_e[f"target_{stat}"].to_numpy(dtype=float)
        scores: dict[str, dict] = {}
        for kind in BASELINES:
            scores[f"baseline_{kind}"] = regression_metrics(y_val, np.nan_to_num(baseline_predict(val_e, stat, kind)))
        fitted = {}
        for spec in candidates:
            t0 = time.perf_counter()
            m = _fit_spec(spec, stat, train)
            fitted[spec.name] = m
            scores[spec.name] = {**regression_metrics(y_val, m.predict(val_e)), "fit_seconds": round(time.perf_counter() - t0, 2)}
            _log(progress, f"      {stat:5s} {spec.name:28s} val MAE {scores[spec.name]['mae']:.3f}")
        best_base = min(BASELINES, key=lambda k: scores[f"baseline_{k}"]["mae"])
        best_ml = min(fitted, key=lambda k: scores[k]["mae"])
        use_ml = scores[best_ml]["mae"] < scores[f"baseline_{best_base}"]["mae"]
        selection[stat] = {
            "validation": scores,
            "best_baseline": best_base,
            "best_ml": best_ml,
            "selected": best_ml if use_ml else f"baseline_{best_base}",
        }
        fold1_models[stat] = fitted[best_ml] if use_ml else BaselineModel(stat, best_base)
    timer.mark("fold1_selection")

    _log(progress, "[4/8] Fitting joint residual distribution on VALIDATION (out-of-sample)")
    val_pred = np.column_stack([fold1_models[s].predict(val_e) for s in TARGETS])
    val_act = np.column_stack([val_e[f"target_{s}"].to_numpy(dtype=float) for s in TARGETS])
    dist = JointResidualDistribution.fit(val_pred, val_act)
    normal_sd = {}
    climatology = {}
    for cat in ALL_CATEGORIES:
        cols = [TARGETS.index(c) for c in components(cat)]
        normal_sd[cat] = float(np.std(val_act[:, cols].sum(1) - val_pred[:, cols].sum(1), ddof=1))
        l10 = sum(val_e[f"{c}_l10"].to_numpy(dtype=float) for c in components(cat))
        a = val_act[:, cols].sum(1)
        ok = np.isfinite(l10)
        climatology[cat] = float(np.mean(a[ok] > np.floor(l10[ok]) + 0.5))
    importance = {
        s: _permutation_importance(fold1_models[s], val_e, s)
        for s in TARGETS
        if isinstance(fold1_models[s], ComponentModel) and not quick
    }
    timer.mark("distribution_and_importance")

    _log(progress, "[5/8] Fold 2: refitting selected specs on TRAIN+VALIDATION, scoring untouched TEST")
    trval = pd.concat([train, val])
    fold2_models: dict[str, Any] = {}
    for stat in TARGETS:
        sel = selection[stat]["selected"]
        if sel.startswith("baseline_"):
            fold2_models[stat] = BaselineModel(stat, sel.removeprefix("baseline_"))
        else:
            spec = next(c for c in candidates if c.name == sel)
            fold2_models[stat] = _fit_spec(spec, stat, trval)
    test_pred = np.column_stack([fold2_models[s].predict(test_e) for s in TARGETS])
    test_preds = pd.DataFrame(test_pred, columns=[f"pred_{s}" for s in TARGETS], index=test_e.index)
    old = _old_model_predictions(session, test_e)
    timer.mark("fold2_test")

    _log(progress, "[6/8] Test metrics, slices, baselines and old-model comparison on identical rows")
    test_report: dict[str, dict] = {}
    for cat in ALL_CATEGORIES:
        y = sum(test_e[f"target_{c}"].to_numpy(dtype=float) for c in components(cat))
        p = sum(test_preds[f"pred_{c}"].to_numpy() for c in components(cat))
        base = {
            k: regression_metrics(y, sum(np.nan_to_num(baseline_predict(test_e, c, k)) for c in components(cat)))
            for k in BASELINES
        }
        entry = {"model": regression_metrics(y, p), "baselines": base}
        best_k = min(base, key=lambda k: base[k]["mae"])
        entry["best_baseline"] = best_k
        entry["mae_improvement_vs_best_baseline_pct"] = pct_improvement(base[best_k]["mae"], entry["model"]["mae"])
        entry["mae_improvement_vs_last10_pct"] = pct_improvement(base["last_10"]["mae"], entry["model"]["mae"])
        entry["mae_improvement_vs_season_avg_pct"] = pct_improvement(base["season_avg"]["mae"], entry["model"]["mae"])
        if old is not None:
            o = sum(old[f"old_{c}"].to_numpy(dtype=float) for c in components(cat))
            ok = np.isfinite(o)
            entry["old_model"] = {
                "version": old.attrs.get("version"),
                "rows_compared": int(ok.sum()),
                "old": regression_metrics(y[ok], o[ok]),
                "new_same_rows": regression_metrics(y[ok], p[ok]),
                "note": "v1 features include the target game's actual starter flag (pregame leakage).",
            }
        entry["slices"] = slice_report(test_e, y, p)
        test_report[cat] = entry

    _log(progress, "[7/8] Probability evaluation: synthetic thresholds and archived real lines")
    synth = synthetic_threshold_eval(test_e, test_pred, dist, normal_sd, climatology)
    real = real_line_eval(load_archived_lines(session), test_e, test_pred, dist)
    prob_status, gate_detail = _probability_gates(synth, real)
    timer.mark("probability_eval")

    _log(progress, "[8/8] Refitting selected specs on all usable rows for deployment")
    allrows = pd.concat([train, val, test]) if not quick else trval
    final_models: dict[str, Any] = {}
    for stat in TARGETS:
        sel = selection[stat]["selected"]
        final_models[stat] = (
            BaselineModel(stat, sel.removeprefix("baseline_"))
            if sel.startswith("baseline_")
            else _fit_spec(next(c for c in candidates if c.name == sel), stat, allrows)
        )
    mins_model = minutes_model(allrows, allrows["target_minutes"].to_numpy(dtype=float))
    mins_eval = regression_metrics(
        test_e["target_minutes"].to_numpy(dtype=float),
        minutes_model(trval, trval["target_minutes"].to_numpy(dtype=float)).predict(test_e),
    )
    timer.mark("final_refit")

    sanity = np.column_stack([final_models[s].predict(test_e.head(500)) for s in TARGETS])
    checks = {
        "finite_predictions": bool(np.isfinite(sanity).all()),
        "nonnegative_predictions": bool((sanity >= 0).all()),
        "core_targets_not_worse_than_best_baseline_on_test": all(
            test_report[s]["mae_improvement_vs_best_baseline_pct"] >= 0 for s in TARGETS
        ),
    }
    version = datetime.now(UTC).strftime("v2_%Y%m%dT%H%M%SZ") + ("_quick" if quick else "")
    out_dir = art.ROOT / version
    manifest = {
        "schema_version": art.SCHEMA_VERSION,
        "engine": "hooplytics-engine-v2",
        "version": version,
        "trained_at": datetime.now(UTC).isoformat(),
        "feature_version": FEATURE_VERSION,
        "feature_sets": FEATURE_SETS,
        "library_versions": art.library_versions(),
        "selected_models": {s: selection[s]["selected"] for s in TARGETS},
        "model_specs": {c.name: {"kind": c.kind, "feature_set": c.feature_set, "params": c.params} for c in candidates},
        "hgb_hyperparameters": __import__("app.ml.engine.models", fromlist=["HGB_DEFAULTS"]).HGB_DEFAULTS,
        "split": {
            "method": "chronological by game date; walk-forward (train->val select, train+val->test)",
            "val_start": str(val_start),
            "test_start": str(test_start),
            "train_dates": _date_range(train),
            "val_dates": _date_range(val_e),
            "test_dates": _date_range(test_e),
            "rows": {"train": int(len(train)), "val_eval": int(len(val_e)), "test_eval": int(len(test_e)), "deploy_fit": int(len(allrows))},
            "min_eval_prior_appearances": MIN_EVAL_APPEARANCES,
        },
        "dataset_cutoff": str(clean["start_time"].max()),
        "data_validation": report.as_dict(),
        "distribution": {
            "method": "joint empirical residual vectors from validation, binned by projected PRA",
            "bins": len(dist.residuals),
            "vectors_per_bin": [int(len(r)) for r in dist.residuals],
            "normal_sd_legacy_comparison": normal_sd,
        },
        "feature_ranges": {
            c: [float(train[c].quantile(0.002)), float(train[c].quantile(0.998))]
            for c in FEATURE_SETS["core"]
            if train[c].notna().any()
        },
        "probability_status": prob_status,
        "probability_gates": {
            "rules": {
                "experimental": f"synthetic-threshold ECE <= {SYNTHETIC_MAX_ECE} and Brier below constant base-rate forecast",
                "validated_real_lines": f"experimental AND >= {REAL_MIN_LINES} unique archived pregame lines, ECE <= {REAL_MAX_ECE}, Brier below constant 0.5",
            },
            "detail": gate_detail,
        },
        "acceptance_checks": checks,
        "timings_seconds": timer.stages,
        "quick": quick,
    }
    metrics = {
        "selection": selection,
        "test": test_report,
        "minutes_model_test": mins_eval,
        "synthetic_thresholds": synth,
        "real_lines": real,
        "feature_importance_validation": importance,
    }
    art.save_bundle(out_dir, manifest=manifest, metrics=metrics, models=final_models, minutes_model=mins_model, distribution=dist)
    art.load_bundle(version)  # round-trip check before promotion
    promoted = False
    if promote_if_valid and not quick and all(checks.values()):
        art.promote(version)
        promoted = True
    manifest["promoted"] = promoted
    (out_dir / "manifest.json").write_text(__import__("json").dumps(manifest, indent=2, default=str))
    timer.mark("save")
    _log(progress, f"Saved {version} ({'promoted to ACTIVE' if promoted else 'not promoted'}); timings {timer.stages}")
    return {"version": version, "path": str(out_dir), "promoted": promoted, "manifest": manifest, "metrics": metrics}
