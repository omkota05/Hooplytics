"""Versioned artifact storage with an ACTIVE pointer, a PREVIOUS pointer for rollback,
and compatibility checks on load. Artifacts are local, trusted files produced by `ml-train`."""

from __future__ import annotations

import json
import platform
from dataclasses import dataclass
from pathlib import Path

import joblib
import numpy as np

from app.config import BACKEND_DIR
from app.ml.engine.distribution import JointResidualDistribution
from app.ml.engine.features import FEATURE_VERSION

ROOT = BACKEND_DIR / "artifacts" / "ml_engine"
ACTIVE = ROOT / "ACTIVE"
PREVIOUS = ROOT / "PREVIOUS"
SCHEMA_VERSION = 1


class EngineArtifactsMissingError(FileNotFoundError):
    pass


class EngineArtifactsIncompatibleError(RuntimeError):
    pass


def library_versions() -> dict[str, str]:
    import pandas
    import scipy
    import sklearn

    return {
        "python": platform.python_version(),
        "numpy": np.__version__,
        "pandas": pandas.__version__,
        "scikit_learn": sklearn.__version__,
        "scipy": scipy.__version__,
    }


@dataclass
class EngineBundle:
    version: str
    path: Path
    manifest: dict
    metrics: dict
    models: dict  # stat -> ComponentModel | BaselineModel
    minutes_model: object
    distribution: JointResidualDistribution

    @property
    def probability_status(self) -> dict[str, str]:
        return self.manifest.get("probability_status", {})


def save_bundle(out_dir: Path, *, manifest: dict, metrics: dict, models: dict, minutes_model, distribution) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    joblib.dump({"models": models, "minutes_model": minutes_model}, out_dir / "models.joblib", compress=3)
    np.savez_compressed(out_dir / "distribution.npz", **distribution.to_npz())
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, default=str))
    (out_dir / "metrics.json").write_text(json.dumps(metrics, indent=2, default=str))


def active_version() -> str | None:
    return ACTIVE.read_text().strip() if ACTIVE.exists() else None


def previous_version() -> str | None:
    return PREVIOUS.read_text().strip() if PREVIOUS.exists() else None


def list_versions() -> list[str]:
    if not ROOT.exists():
        return []
    return sorted(p.name for p in ROOT.iterdir() if p.is_dir() and (p / "manifest.json").exists())


def promote(version: str) -> None:
    current = active_version()
    if current and current != version:
        PREVIOUS.write_text(current)
    ACTIVE.write_text(version)


def rollback() -> str:
    prev = previous_version()
    if not prev:
        raise EngineArtifactsMissingError("No previous model version recorded")
    promote(prev)
    return prev


def load_bundle(version: str | None = None) -> EngineBundle:
    version = version or active_version()
    if not version:
        raise EngineArtifactsMissingError("No active v2 model. Train one with: make ml-train")
    path = ROOT / version
    if not (path / "manifest.json").exists():
        raise EngineArtifactsMissingError(f"Model artifacts missing for version {version}")
    manifest = json.loads((path / "manifest.json").read_text())
    if manifest.get("schema_version") != SCHEMA_VERSION:
        raise EngineArtifactsIncompatibleError(f"Artifact schema {manifest.get('schema_version')} != {SCHEMA_VERSION}")
    if manifest.get("feature_version") != FEATURE_VERSION:
        raise EngineArtifactsIncompatibleError(
            f"Model built with features {manifest.get('feature_version')}, code has {FEATURE_VERSION}; retrain"
        )
    trained_sklearn = manifest.get("library_versions", {}).get("scikit_learn")
    if trained_sklearn and trained_sklearn != library_versions()["scikit_learn"]:
        raise EngineArtifactsIncompatibleError(
            f"Model trained with scikit-learn {trained_sklearn}, runtime has {library_versions()['scikit_learn']}"
        )
    blob = joblib.load(path / "models.joblib")
    with np.load(path / "distribution.npz") as data:
        dist = JointResidualDistribution.from_npz(data)
    metrics = json.loads((path / "metrics.json").read_text()) if (path / "metrics.json").exists() else {}
    return EngineBundle(
        version=version,
        path=path,
        manifest=manifest,
        metrics=metrics,
        models=blob["models"],
        minutes_model=blob["minutes_model"],
        distribution=dist,
    )
