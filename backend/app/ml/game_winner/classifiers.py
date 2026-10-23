"""Win-probability classifiers with XGBoost preferred and sklearn fallback."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

import joblib
import numpy as np
import pandas as pd


class WinClassifier(Protocol):
    backend: str

    def fit(self, x: pd.DataFrame, y: pd.Series) -> None: ...

    def predict_proba_home(self, x: pd.DataFrame) -> np.ndarray: ...

    def save(self, path: Path) -> None: ...

    @classmethod
    def load(cls, path: Path, backend: str) -> WinClassifier: ...


def _xgb_available() -> bool:
    try:
        from xgboost import XGBClassifier  # noqa: F401

        return True
    except Exception:
        return False


def create_classifier() -> WinClassifier:
    if _xgb_available():
        from xgboost import XGBClassifier

        return _XGBWrapper(
            XGBClassifier(
                objective="binary:logistic",
                n_estimators=300,
                max_depth=4,
                learning_rate=0.05,
                subsample=0.85,
                colsample_bytree=0.85,
                min_child_weight=5,
                reg_lambda=1.0,
                random_state=42,
                n_jobs=-1,
                eval_metric="logloss",
            )
        )
    from sklearn.ensemble import HistGradientBoostingClassifier

    return _SklearnWrapper(
        HistGradientBoostingClassifier(
            max_depth=5,
            learning_rate=0.05,
            max_iter=300,
            random_state=42,
        )
    )


class _XGBWrapper:
    backend = "xgboost"

    def __init__(self, model) -> None:
        self._model = model

    def fit(self, x: pd.DataFrame, y: pd.Series) -> None:
        self._model.fit(x, y)

    def predict_proba_home(self, x: pd.DataFrame) -> np.ndarray:
        return self._model.predict_proba(x)[:, 1]

    def save(self, path: Path) -> None:
        self._model.save_model(str(path.with_suffix(".json")))

    @classmethod
    def load(cls, path: Path, backend: str) -> _XGBWrapper:
        from xgboost import XGBClassifier

        model = XGBClassifier()
        model.load_model(str(path.with_suffix(".json")))
        return cls(model)


class _SklearnWrapper:
    backend = "sklearn_hgb"

    def __init__(self, model) -> None:
        self._model = model

    def fit(self, x: pd.DataFrame, y: pd.Series) -> None:
        self._model.fit(x, y)

    def predict_proba_home(self, x: pd.DataFrame) -> np.ndarray:
        return self._model.predict_proba(x)[:, 1]

    def save(self, path: Path) -> None:
        joblib.dump(self._model, path.with_suffix(".joblib"))

    @classmethod
    def load(cls, path: Path, backend: str) -> _SklearnWrapper:
        return cls(joblib.load(path.with_suffix(".joblib")))


def load_classifier(path: Path, backend: str) -> WinClassifier:
    if backend == "xgboost":
        return _XGBWrapper.load(path, backend)
    return _SklearnWrapper.load(path, backend)


def active_backend() -> str:
    return "xgboost" if _xgb_available() else "sklearn_hgb"
