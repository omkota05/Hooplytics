"""Baselines and a small, bounded set of candidate regressors per component stat."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge
from sklearn.model_selection import KFold
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

from app.ml.engine.features import FEATURE_SETS

SEED = 42
BASELINES = ("season_avg", "last_5", "last_10", "ewm", "weighted")


def _first_available(frame: pd.DataFrame, cols: list[str]) -> np.ndarray:
    out = pd.Series(np.nan, index=frame.index)
    for c in cols:
        out = out.fillna(frame[c])
    return out.to_numpy(dtype=float)


def baseline_predict(frame: pd.DataFrame, stat: str, kind: str) -> np.ndarray:
    """Simple pregame projections. Missing windows fall back to the next-longest available history."""
    chain = {
        "season_avg": [f"{stat}_season", f"{stat}_l20", f"{stat}_l10"],
        "last_5": [f"{stat}_l5", f"{stat}_l10"],
        "last_10": [f"{stat}_l10", f"{stat}_l5"],
        "ewm": [f"{stat}_ewm", f"{stat}_l10"],
    }
    if kind == "weighted":
        l5 = _first_available(frame, chain["last_5"])
        l10 = _first_available(frame, chain["last_10"])
        season = _first_available(frame, chain["season_avg"])
        return 0.2 * l5 + 0.5 * l10 + 0.3 * season
    return _first_available(frame, chain[kind])


@dataclass
class CandidateSpec:
    name: str
    kind: str  # ridge | hgb | two_stage
    feature_set: str
    params: dict[str, Any] = field(default_factory=dict)


CANDIDATES: list[CandidateSpec] = [
    CandidateSpec("ridge_core", "ridge", "core", {"alpha": 10.0}),
    CandidateSpec("hgb_core_l2", "hgb", "core", {"loss": "squared_error"}),
    CandidateSpec("hgb_full_l2", "hgb", "full", {"loss": "squared_error"}),
    CandidateSpec("hgb_full_poisson", "hgb", "full", {"loss": "poisson"}),
    CandidateSpec("two_stage_minutes_poisson", "two_stage", "full", {"loss": "poisson"}),
]

HGB_DEFAULTS = dict(
    learning_rate=0.05,
    max_iter=350,
    max_leaf_nodes=31,
    min_samples_leaf=40,
    l2_regularization=1.0,
    random_state=SEED,
)


def _hgb(loss: str) -> HistGradientBoostingRegressor:
    return HistGradientBoostingRegressor(loss=loss, **HGB_DEFAULTS)


class ComponentModel:
    """Fitted predictor for one component stat. Holds its own feature list for strict ordering."""

    def __init__(self, spec: CandidateSpec, stat: str) -> None:
        self.spec = spec
        self.stat = stat
        self.features: list[str] = list(FEATURE_SETS[spec.feature_set])
        self.model: Any = None
        self.minutes_model: Any = None

    def _x(self, frame: pd.DataFrame, minutes_pred: np.ndarray | None = None) -> pd.DataFrame:
        x = frame.reindex(columns=self.features).astype(float)
        if self.spec.kind == "two_stage":
            x = x.assign(projected_minutes=minutes_pred)
        return x

    def fit(self, frame: pd.DataFrame, y: np.ndarray, minutes: np.ndarray | None = None) -> ComponentModel:
        if self.spec.kind == "ridge":
            self.model = make_pipeline(
                SimpleImputer(strategy="median", add_indicator=True),
                StandardScaler(),
                Ridge(alpha=self.spec.params["alpha"], random_state=SEED),
            )
            self.model.fit(self._x(frame), y)
        elif self.spec.kind == "hgb":
            self.model = _hgb(self.spec.params["loss"])
            self.model.fit(self._x(frame), y)
        elif self.spec.kind == "two_stage":
            if minutes is None:
                raise ValueError("two_stage needs actual minutes for stage-1 training")
            base = self._x_base(frame)
            # Out-of-fold projected minutes for training rows so stage 2 never sees in-sample fits.
            oof = np.zeros(len(frame))
            for tr, te in KFold(n_splits=4, shuffle=False).split(base):
                m = _hgb("squared_error").fit(base.iloc[tr], minutes[tr])
                oof[te] = m.predict(base.iloc[te])
            self.minutes_model = _hgb("squared_error").fit(base, minutes)
            self.model = _hgb(self.spec.params["loss"])
            self.model.fit(self._x(frame, np.clip(oof, 0, None)), y)
        else:
            raise ValueError(self.spec.kind)
        return self

    def _x_base(self, frame: pd.DataFrame) -> pd.DataFrame:
        return frame.reindex(columns=self.features).astype(float)

    def predict(self, frame: pd.DataFrame) -> np.ndarray:
        if self.spec.kind == "two_stage":
            mins = np.clip(self.minutes_model.predict(self._x_base(frame)), 0, None)
            pred = self.model.predict(self._x(frame, mins))
        else:
            pred = self.model.predict(self._x(frame))
        return np.clip(pred, 0.0, None)


class BaselineModel:
    def __init__(self, stat: str, kind: str) -> None:
        self.stat = stat
        self.kind = kind
        self.spec = CandidateSpec(f"baseline_{kind}", "baseline", "none")
        self.features: list[str] = []

    def predict(self, frame: pd.DataFrame) -> np.ndarray:
        return np.clip(np.nan_to_num(baseline_predict(frame, self.stat, self.kind), nan=0.0), 0.0, None)


def minutes_model(frame: pd.DataFrame, minutes: np.ndarray) -> ComponentModel:
    """Standalone projected-minutes model (shown in the UI and used for usage tiers)."""
    return ComponentModel(CandidateSpec("minutes_hgb", "hgb", "full", {"loss": "squared_error"}), "minutes").fit(frame, minutes)
