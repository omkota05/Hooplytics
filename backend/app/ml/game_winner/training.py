"""Train game-winner baselines and ML models."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import joblib
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, brier_score_loss, log_loss
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from app.config import BACKEND_DIR
from app.ml.calibration import fit_isotonic, high_probability_audit, reliability_bins, serialize_isotonic
from app.ml.game_winner.classifiers import active_backend, create_classifier
from app.ml.game_winner.dataset import load_completed_games
from app.ml.game_winner.features import (
    add_derived_columns,
    build_game_feature_frame,
    feature_columns,
    logistic_feature_columns,
    split_chronological,
)

ARTIFACTS_ROOT = BACKEND_DIR / "artifacts" / "ml" / "game_winner"
ACTIVE_VERSION_FILE = ARTIFACTS_ROOT / "active_version.txt"

SelectedModel = Literal["home_baseline", "elo", "logistic", "ml"]

# Prior run (20261022T173119Z) kept in metrics for honest comparison — do not re-tune on test.
PRIOR_MODEL_BASELINE_REPORT = {
    "version": "20261022T173119Z",
    "note": "Pre-fix pipeline (uncapped rest, redundant Elo cols, isotonic always on)",
    "test_selected_logistic_calibrated": {
        "accuracy": 0.6997,
        "log_loss": 0.546,
        "brier": 0.185,
    },
    "test_logistic_raw": {"accuracy": 0.7507, "log_loss": 0.533, "brier": 0.177},
    "test_elo": {"accuracy": 0.7426, "log_loss": 0.542, "brier": 0.181},
}


def _raw_probs(
    name: SelectedModel,
    frame: pd.DataFrame,
    *,
    home_rate: float,
    logistic: Pipeline | None,
    ml_model,
    ml_cols: list[str],
) -> np.ndarray:
    if name == "home_baseline":
        return np.full(len(frame), home_rate, dtype=float)
    if name == "elo":
        return frame["elo_home_win_prob"].to_numpy(dtype=float)
    cols = ml_cols if name in ("logistic", "ml") else feature_columns()
    x = frame[cols].fillna(0.0)
    if name == "logistic":
        assert logistic is not None
        return logistic.predict_proba(x)[:, 1]
    return ml_model.predict_proba_home(x)


def _eval_split(y: np.ndarray, p: np.ndarray) -> dict[str, float]:
    p = np.clip(p, 1e-6, 1 - 1e-6)
    return {
        "accuracy": float(accuracy_score(y, (p >= 0.5).astype(int))),
        "log_loss": float(log_loss(y, p)),
        "brier": float(brier_score_loss(y, p)),
    }


def _production_probs(
    name: SelectedModel,
    frame: pd.DataFrame,
    *,
    home_rate: float,
    logistic: Pipeline | None,
    ml_model,
    ml_cols: list[str],
    isotonic,
    calibration_enabled: bool,
) -> np.ndarray:
    raw = _raw_probs(name, frame, home_rate=home_rate, logistic=logistic, ml_model=ml_model, ml_cols=ml_cols)
    if calibration_enabled and isotonic is not None and name in ("logistic", "ml"):
        return isotonic.predict(raw)
    return raw


def train_game_winner(session, version: str | None = None) -> Path:
    games = load_completed_games(session)
    if len(games) < 200:
        raise ValueError(f"Not enough completed games ({len(games)}); sync more history")

    frame = add_derived_columns(build_game_feature_frame(games))
    train, val, test = split_chronological(frame)
    all_cols = feature_columns()
    ml_cols = logistic_feature_columns()
    y_train = train["home_win"].astype(int)
    y_val = val["home_win"].astype(int)
    y_test = test["home_win"].astype(int)

    x_train_ml = train[ml_cols].fillna(0.0)

    home_rate = float(y_train.mean())
    logistic: Pipeline = Pipeline(
        [
            ("scaler", StandardScaler()),
            (
                "clf",
                LogisticRegression(max_iter=4000, random_state=42, C=0.5),
            ),
        ]
    )
    logistic.fit(x_train_ml, y_train)
    ml_model = create_classifier()
    ml_model.fit(x_train_ml, y_train)
    classifier_backend = active_backend()

    candidates: list[SelectedModel] = ["home_baseline", "elo", "logistic", "ml"]
    val_metrics_raw: dict[str, dict[str, float]] = {}
    val_log_loss_raw: dict[str, float] = {}

    for name in candidates:
        p_val = _raw_probs(
            name, val, home_rate=home_rate, logistic=logistic, ml_model=ml_model, ml_cols=ml_cols
        )
        val_metrics_raw[name] = _eval_split(y_val.to_numpy(), p_val)
        val_log_loss_raw[name] = val_metrics_raw[name]["log_loss"]

    isotonic = None
    calibration_enabled = False
    for cal_candidate in ("logistic", "ml"):
        p_cand = _raw_probs(
            cal_candidate, val, home_rate=home_rate, logistic=logistic, ml_model=ml_model, ml_cols=ml_cols
        )
        iso_try = fit_isotonic(p_cand, y_val.to_numpy())
        if iso_try is None:
            continue
        p_cal = iso_try.predict(p_cand)
        raw_brier = val_metrics_raw[cal_candidate]["brier"]
        cal_brier = _eval_split(y_val.to_numpy(), p_cal)["brier"]
        if cal_brier < raw_brier:
            isotonic = iso_try
            calibration_enabled = True
            break

    val_metrics_production: dict[str, dict[str, float]] = {}
    for name in candidates:
        p_val = _production_probs(
            name,
            val,
            home_rate=home_rate,
            logistic=logistic,
            ml_model=ml_model,
            ml_cols=ml_cols,
            isotonic=isotonic,
            calibration_enabled=calibration_enabled and name in ("logistic", "ml"),
        )
        val_metrics_production[name] = _eval_split(y_val.to_numpy(), p_val)

    selected: SelectedModel = min(
        val_metrics_production,
        key=lambda n: val_metrics_production[n]["log_loss"],
    )

    def test_block(name: SelectedModel) -> dict[str, Any]:
        p_raw = _raw_probs(
            name, test, home_rate=home_rate, logistic=logistic, ml_model=ml_model, ml_cols=ml_cols
        )
        use_cal = (
            calibration_enabled
            and name == selected
            and name in ("logistic", "ml")
            and isotonic is not None
        )
        p_prod = isotonic.predict(p_raw) if use_cal else p_raw
        m_raw = _eval_split(y_test.to_numpy(), p_raw)
        m_prod = _eval_split(y_test.to_numpy(), p_prod)
        out: dict[str, Any] = {
            "raw": m_raw,
            "production": m_prod,
            "reliability_raw": reliability_bins(p_raw, y_test.to_numpy()),
            "reliability_production": reliability_bins(p_prod, y_test.to_numpy()),
            "high_probability_audit_raw": high_probability_audit(p_raw, y_test.to_numpy()),
            "high_probability_audit_production": high_probability_audit(p_prod, y_test.to_numpy()),
        }
        return out

    test_metrics = {name: test_block(name) for name in candidates}

    version = version or datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out_dir = ARTIFACTS_ROOT / version
    models_dir = out_dir / "models"
    models_dir.mkdir(parents=True, exist_ok=True)
    ml_model.save(models_dir / "classifier")
    joblib.dump(logistic, models_dir / "logistic_pipeline.joblib")

    manifest = {
        "kind": "game_winner",
        "version": version,
        "trained_at": datetime.now(UTC).isoformat(),
        "selected_model": selected,
        "home_baseline_rate": home_rate,
        "classifier_backend": classifier_backend,
        "feature_columns": all_cols,
        "ml_feature_columns": ml_cols,
        "probability_calibration": {
            "method": "isotonic_validation" if calibration_enabled else "none",
            "enabled": calibration_enabled,
            "isotonic": serialize_isotonic(isotonic) if calibration_enabled else None,
        },
    }
    metrics = {
        "n_games_total": len(frame),
        "n_train": len(train),
        "n_val": len(val),
        "n_test": len(test),
        "train_start": str(train["start_time"].min()),
        "train_end": str(train["start_time"].max()),
        "val_start": str(val["start_time"].min()),
        "val_end": str(val["start_time"].max()),
        "test_start": str(test["start_time"].min()),
        "test_end": str(test["start_time"].max()),
        "validation_log_loss_raw": val_log_loss_raw,
        "validation_log_loss_production": {
            n: val_metrics_production[n]["log_loss"] for n in candidates
        },
        "validation_metrics_raw": val_metrics_raw,
        "validation_metrics_production": val_metrics_production,
        "test_metrics": test_metrics,
        "selected_model": selected,
        "calibration_enabled": calibration_enabled,
        "prior_model_baseline_report": PRIOR_MODEL_BASELINE_REPORT,
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))
    (out_dir / "metrics.json").write_text(json.dumps(metrics, indent=2))
    ACTIVE_VERSION_FILE.write_text(version)
    return out_dir
