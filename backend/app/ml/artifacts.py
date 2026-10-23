"""Load and save trained model bundles."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from sklearn.isotonic import IsotonicRegression

from app.config import BACKEND_DIR
from app.ml.baselines import BaselineKind
from app.ml.calibration import deserialize_isotonic
from app.ml.constants import COMPONENT_STATS
from app.ml.regressors import ComponentRegressor, load_regressor

ARTIFACTS_ROOT = BACKEND_DIR / "artifacts" / "ml"
ACTIVE_VERSION_FILE = ARTIFACTS_ROOT / "active_version.txt"


class ModelArtifactsMissingError(FileNotFoundError):
    pass


@dataclass
class ModelBundle:
    version: str
    manifest: dict
    metrics: dict
    ml_models: dict[str, ComponentRegressor]
    component_selected_model: dict[str, str]
    component_baseline_kind: dict[str, BaselineKind]
    residual_std: dict[str, float]
    residual_covariance: np.ndarray
    feature_columns: list[str]
    regressor_backend: str
    isotonic_calibrators: dict[str, IsotonicRegression | None]

    @property
    def model_version(self) -> str:
        return self.version

    # Backwards-compatible alias
    @property
    def xgb_models(self) -> dict[str, ComponentRegressor]:
        return self.ml_models


def active_version() -> str | None:
    if not ACTIVE_VERSION_FILE.exists():
        return None
    return ACTIVE_VERSION_FILE.read_text().strip() or None


def bundle_dir(version: str | None = None) -> Path:
    version = version or active_version()
    if not version:
        raise ModelArtifactsMissingError("No trained model version found. Run: make ml-train")
    path = ARTIFACTS_ROOT / version
    if not path.exists():
        raise ModelArtifactsMissingError(f"Model artifacts missing at {path}")
    return path


def load_bundle(version: str | None = None) -> ModelBundle:
    root = bundle_dir(version)
    manifest = json.loads((root / "manifest.json").read_text())
    metrics_path = root / "metrics.json"
    metrics = json.loads(metrics_path.read_text()) if metrics_path.exists() else {}
    backend = manifest.get("regressor_backend", "xgboost")
    models: dict[str, ComponentRegressor] = {}
    models_dir = root / "models"
    for stat in COMPONENT_STATS:
        models[stat] = load_regressor(models_dir / stat, backend)
    cov = np.array(manifest["residual_covariance"], dtype=float)
    cal_block = manifest.get("probability_calibration", {})
    iso_raw = cal_block.get("isotonic_per_category", {})
    isotonic_calibrators = {
        cat: deserialize_isotonic(iso_raw.get(cat)) for cat in manifest.get("prediction_categories", [])
    }
    return ModelBundle(
        version=manifest["version"],
        manifest=manifest,
        metrics=metrics,
        ml_models=models,
        component_selected_model=manifest["component_selected_model"],
        component_baseline_kind=manifest["component_baseline_kind"],
        residual_std={k: float(v) for k, v in manifest["residual_std"].items()},
        residual_covariance=cov,
        feature_columns=list(manifest["feature_columns"]),
        regressor_backend=backend,
        isotonic_calibrators=isotonic_calibrators,
    )
