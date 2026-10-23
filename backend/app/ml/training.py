"""Train baselines and ML models with chronological validation."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.metrics import mean_absolute_error, mean_squared_error

from app.config import BACKEND_DIR
from app.ml.baselines import best_baseline_on_frame, predict_baseline
from app.ml.calibration import build_calibration_report, serialize_isotonic
from app.ml.constants import COMPONENT_STATS, PREDICTION_CATEGORIES, components_for_category
from app.ml.features import build_training_frame, feature_columns, split_chronological, target_column
from app.ml.probability import estimate_std_from_residuals
from app.ml.regressors import active_backend, create_regressor

ARTIFACTS_ROOT = BACKEND_DIR / "artifacts" / "ml"
MIN_GAMES_CALIBRATION = 8


@dataclass
class CategoryMetrics:
    category: str
    n_train: int
    n_val: int
    n_test: int
    train_start: str
    train_end: str
    test_start: str
    test_end: str
    mae_baseline: float
    rmse_baseline: float
    mae_ml: float
    rmse_ml: float
    selected_model: str
    baseline_kind: str
    brier_test_pregame_line: float | None = None
    brier_test_calibrated: float | None = None


def _metrics(y_true: np.ndarray, y_pred: np.ndarray) -> tuple[float, float]:
    mae = float(mean_absolute_error(y_true, y_pred))
    rmse = float(np.sqrt(mean_squared_error(y_true, y_pred)))
    return mae, rmse


def _predict_components_ml(models: dict, x: pd.DataFrame) -> dict[str, np.ndarray]:
    return {stat: models[stat].predict(x) for stat in COMPONENT_STATS}


def _predict_components_baseline(frame: pd.DataFrame, baseline_kind: dict[str, str]) -> dict[str, np.ndarray]:
    return {stat: predict_baseline(frame, stat, baseline_kind[stat]) for stat in COMPONENT_STATS}


def _category_actual(frame: pd.DataFrame, category: str) -> np.ndarray:
    return frame[target_column(category)].to_numpy(dtype=float)


def _category_pred_from_components(preds: dict[str, np.ndarray], category: str) -> np.ndarray:
    comps = components_for_category(category)
    return sum(preds[c] for c in comps)


def _category_std(category: str, residual_std: dict[str, float], cov: np.ndarray) -> float:
    return estimate_std_from_residuals(residual_std, cov, list(COMPONENT_STATS), category)


def _pregame_means_for_category(
    frame: pd.DataFrame,
    x: pd.DataFrame,
    ml_models: dict,
    selected: dict[str, str],
    baseline_kind: dict[str, str],
    category: str,
) -> np.ndarray:
    parts = {}
    for stat in COMPONENT_STATS:
        if selected[stat] == "ml":
            parts[stat] = ml_models[stat].predict(x)
        else:
            parts[stat] = predict_baseline(frame, stat, baseline_kind[stat])
    return _category_pred_from_components(parts, category)


def train_all(session, version: str | None = None) -> Path:
    frame = build_training_frame(session)
    if len(frame) < 500:
        raise ValueError(f"Not enough played games for training ({len(frame)} rows; need ~500+)")

    train, val, test = split_chronological(frame)
    cols = feature_columns()
    x_train = train[cols].fillna(0.0)
    x_val = val[cols].fillna(0.0)
    x_test = test[cols].fillna(0.0)

    version = version or datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out_dir = ARTIFACTS_ROOT / version
    models_dir = out_dir / "models"
    models_dir.mkdir(parents=True, exist_ok=True)

    regressor_backend = active_backend()
    ml_models: dict = {}
    baseline_kind: dict[str, str] = {}
    selected: dict[str, str] = {}
    residual_std: dict[str, float] = {}

    for stat in COMPONENT_STATS:
        y_train = train[f"target_{stat}"].astype(float)
        y_val = val[f"target_{stat}"].astype(float)
        model = create_regressor()
        model.fit(x_train, y_train)
        ml_models[stat] = model
        model.save(models_dir / stat)

        kind, _ = best_baseline_on_frame(val, stat, y_val)
        baseline_kind[stat] = kind
        pred_baseline = predict_baseline(val, stat, kind)
        pred_ml = model.predict(x_val)
        mae_x, _ = _metrics(y_val.to_numpy(), pred_ml)
        mae_b, _ = _metrics(y_val.to_numpy(), pred_baseline)
        selected[stat] = "ml" if mae_x <= mae_b else f"baseline_{kind}"

    val_preds = {}
    for stat in COMPONENT_STATS:
        if selected[stat] == "ml":
            val_preds[stat] = ml_models[stat].predict(x_val)
        else:
            val_preds[stat] = predict_baseline(val, stat, baseline_kind[stat])
    residuals = np.column_stack(
        [val[f"target_{stat}"].to_numpy() - val_preds[stat] for stat in COMPONENT_STATS]
    )
    cov = np.cov(residuals, rowvar=False)
    for i, stat in enumerate(COMPONENT_STATS):
        residual_std[stat] = float(np.std(residuals[:, i], ddof=1)) if len(residuals) > 1 else 1.0

    metrics_rows: list[CategoryMetrics] = []
    calibration_reports: dict[str, Any] = {}
    isotonic_models: dict[str, Any] = {}

    base_comp_test = _predict_components_baseline(test, baseline_kind)
    ml_comp_test = _predict_components_ml(ml_models, x_test)

    for category in PREDICTION_CATEGORIES:
        y_test = _category_actual(test, category)
        test_preds_base = _category_pred_from_components(base_comp_test, category)
        test_preds_ml = _category_pred_from_components(ml_comp_test, category)

        mae_b, rmse_b = _metrics(y_test, test_preds_base)
        mae_x, rmse_x = _metrics(y_test, test_preds_ml)
        chosen = "ml" if mae_x <= mae_b else "baseline"

        std_cat = _category_std(category, residual_std, cov)
        val_means = _pregame_means_for_category(val, x_val, ml_models, selected, baseline_kind, category)
        test_means = _pregame_means_for_category(test, x_test, ml_models, selected, baseline_kind, category)

        cal_report, iso = build_calibration_report(
            val_frame=val,
            test_frame=test,
            category=category,
            val_pregame_means=val_means,
            test_pregame_means=test_means,
            std_dev=std_cat,
            min_games_before=MIN_GAMES_CALIBRATION,
        )
        calibration_reports[category] = cal_report
        isotonic_models[category] = serialize_isotonic(iso)

        test_primary = cal_report["test"]["pregame_model_half"]
        metrics_rows.append(
            CategoryMetrics(
                category=category,
                n_train=len(train),
                n_val=len(val),
                n_test=len(test),
                train_start=str(train["game_date"].min().date()),
                train_end=str(train["game_date"].max().date()),
                test_start=str(test["game_date"].min().date()),
                test_end=str(test["game_date"].max().date()),
                mae_baseline=mae_b,
                rmse_baseline=rmse_b,
                mae_ml=mae_x,
                rmse_ml=rmse_x,
                selected_model=chosen,
                baseline_kind=",".join(f"{s}:{baseline_kind[s]}" for s in COMPONENT_STATS),
                brier_test_pregame_line=test_primary.get("brier_raw_normal"),
                brier_test_calibrated=test_primary.get("brier_isotonic_calibrated"),
            )
        )

    train_kick = pd.to_datetime(train["start_time"], utc=True)
    test_kick = pd.to_datetime(test["start_time"], utc=True)
    manifest: dict[str, Any] = {
        "version": version,
        "trained_at": datetime.now(UTC).isoformat(),
        "feature_columns": cols,
        "component_stats": list(COMPONENT_STATS),
        "prediction_categories": list(PREDICTION_CATEGORIES),
        "regressor_backend": regressor_backend,
        "component_selected_model": selected,
        "component_baseline_kind": baseline_kind,
        "residual_std": residual_std,
        "residual_covariance": cov.tolist(),
        "row_counts": {"train": len(train), "val": len(val), "test": len(test)},
        "split_method": "chronological_by_kickoff_utc",
        "date_ranges": {
            "train": [str(train["game_date"].min().date()), str(train["game_date"].max().date())],
            "val": [str(val["game_date"].min().date()), str(val["game_date"].max().date())],
            "test": [str(test["game_date"].min().date()), str(test["game_date"].max().date())],
        },
        "kickoff_ranges": {
            "train": [train_kick.min().isoformat(), train_kick.max().isoformat()],
            "test": [test_kick.min().isoformat(), test_kick.max().isoformat()],
        },
        "probability_calibration": {
            "isotonic_per_category": isotonic_models,
            "primary_line_scheme": "pregame_model_half",
        },
    }
    metrics_payload = {
        "categories": [m.__dict__ for m in metrics_rows],
        "calibration": calibration_reports,
        "split_audit": {
            "method": manifest["split_method"],
            "note": "All games sharing the same UTC kickoff are assigned to the same fold.",
        },
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))
    (out_dir / "metrics.json").write_text(json.dumps(metrics_payload, indent=2))
    (ARTIFACTS_ROOT / "active_version.txt").write_text(version)
    return out_dir
