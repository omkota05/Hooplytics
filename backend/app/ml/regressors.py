"""Component regressors with XGBoost preferred and sklearn fallback."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

import joblib
import numpy as np
import pandas as pd


class ComponentRegressor(Protocol):
    backend: str

    def fit(self, x: pd.DataFrame, y: pd.Series) -> None: ...

    def predict(self, x: pd.DataFrame) -> np.ndarray: ...

    def save(self, path: Path) -> None: ...

    @classmethod
    def load(cls, path: Path, backend: str) -> ComponentRegressor: ...


def _xgb_available() -> bool:
    try:
        from xgboost import XGBRegressor  # noqa: F401

        return True
    except Exception:
        return False


def create_regressor() -> ComponentRegressor:
    if _xgb_available():
        from xgboost import XGBRegressor

        return _XGBWrapper(
            XGBRegressor(
                objective="reg:squarederror",
                n_estimators=250,
                max_depth=5,
                learning_rate=0.05,
                subsample=0.85,
                colsample_bytree=0.85,
                min_child_weight=3,
                reg_lambda=1.0,
                random_state=42,
                n_jobs=-1,
            )
        )
    from sklearn.ensemble import HistGradientBoostingRegressor

    return _SklearnWrapper(
        HistGradientBoostingRegressor(
            max_depth=6,
            learning_rate=0.05,
            max_iter=250,
            random_state=42,
        )
    )


class _XGBWrapper:
    backend = "xgboost"

    def __init__(self, model) -> None:
        self._model = model

    def fit(self, x: pd.DataFrame, y: pd.Series) -> None:
        self._model.fit(x, y)

    def predict(self, x: pd.DataFrame) -> np.ndarray:
        return self._model.predict(x)

    def save(self, path: Path) -> None:
        self._model.save_model(str(path.with_suffix(".json")))

    @classmethod
    def load(cls, path: Path, backend: str) -> _XGBWrapper:
        from xgboost import XGBRegressor

        model = XGBRegressor()
        model.load_model(str(path.with_suffix(".json")))
        return cls(model)


class _SklearnWrapper:
    backend = "sklearn_hgb"

    def __init__(self, model) -> None:
        self._model = model

    def fit(self, x: pd.DataFrame, y: pd.Series) -> None:
        self._model.fit(x, y)

    def predict(self, x: pd.DataFrame) -> np.ndarray:
        return self._model.predict(x)

    def save(self, path: Path) -> None:
        joblib.dump(self._model, path.with_suffix(".joblib"))

    @classmethod
    def load(cls, path: Path, backend: str) -> _SklearnWrapper:
        return cls(joblib.load(path.with_suffix(".joblib")))


def load_regressor(path: Path, backend: str) -> ComponentRegressor:
    if backend == "xgboost":
        return _XGBWrapper.load(path, backend)
    return _SklearnWrapper.load(path, backend)


def active_backend() -> str:
    return "xgboost" if _xgb_available() else "sklearn_hgb"
