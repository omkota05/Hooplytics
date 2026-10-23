"""Load game-winner model bundles."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import joblib
from sklearn.isotonic import IsotonicRegression
from sklearn.pipeline import Pipeline

from app.config import BACKEND_DIR
from app.ml.calibration import deserialize_isotonic
from app.ml.game_winner.classifiers import WinClassifier, load_classifier
from app.ml.game_winner.features import feature_columns, logistic_feature_columns

ARTIFACTS_ROOT = BACKEND_DIR / "artifacts" / "ml" / "game_winner"
ACTIVE_VERSION_FILE = ARTIFACTS_ROOT / "active_version.txt"


class GameWinnerArtifactsMissingError(FileNotFoundError):
    pass


@dataclass
class GameWinnerBundle:
    version: str
    manifest: dict
    metrics: dict
    selected_model: str
    home_baseline_rate: float
    feature_columns: list[str]
    ml_feature_columns: list[str]
    classifier_backend: str
    logistic_pipeline: Pipeline | None
    ml_classifier: WinClassifier | None
    isotonic: IsotonicRegression | None
    calibration_enabled: bool


def active_version() -> str | None:
    if not ACTIVE_VERSION_FILE.exists():
        return None
    return ACTIVE_VERSION_FILE.read_text().strip() or None


def bundle_dir(version: str | None = None) -> Path:
    version = version or active_version()
    if not version:
        raise GameWinnerArtifactsMissingError("No game-winner model. Run: make ml-train-games")
    path = ARTIFACTS_ROOT / version
    if not path.exists():
        raise GameWinnerArtifactsMissingError(f"Game-winner artifacts missing at {path}")
    return path


def load_game_winner_bundle(version: str | None = None) -> GameWinnerBundle:
    root = bundle_dir(version)
    manifest = json.loads((root / "manifest.json").read_text())
    metrics_path = root / "metrics.json"
    metrics = json.loads(metrics_path.read_text()) if metrics_path.exists() else {}
    selected = manifest["selected_model"]
    backend = manifest.get("classifier_backend", "sklearn_hgb")
    models_dir = root / "models"
    logistic_pipeline = None
    ml_classifier = None
    if (models_dir / "logistic_pipeline.joblib").exists():
        logistic_pipeline = joblib.load(models_dir / "logistic_pipeline.joblib")
    elif (models_dir / "logistic.joblib").exists():
        logistic_pipeline = joblib.load(models_dir / "logistic.joblib")
    if (models_dir / "classifier.json").exists() or (models_dir / "classifier.joblib").exists():
        ml_classifier = load_classifier(models_dir / "classifier", backend)
    cal = manifest.get("probability_calibration", {})
    calibration_enabled = bool(cal.get("enabled", False))
    isotonic = deserialize_isotonic(cal.get("isotonic")) if calibration_enabled else None
    ml_cols = list(manifest.get("ml_feature_columns") or logistic_feature_columns())
    return GameWinnerBundle(
        version=manifest["version"],
        manifest=manifest,
        metrics=metrics,
        selected_model=selected,
        home_baseline_rate=float(manifest["home_baseline_rate"]),
        feature_columns=list(manifest.get("feature_columns") or feature_columns()),
        ml_feature_columns=ml_cols,
        classifier_backend=backend,
        logistic_pipeline=logistic_pipeline,
        ml_classifier=ml_classifier,
        isotonic=isotonic,
        calibration_enabled=calibration_enabled,
    )
