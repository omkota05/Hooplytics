"""Simple point-in-time baselines for comparison and fallback."""

from __future__ import annotations

from typing import Literal

import numpy as np
import pandas as pd

from app.ml.constants import EWM_SPAN

BaselineKind = Literal["season_avg", "last_10", "ewm"]


def baseline_column(stat: str, kind: BaselineKind) -> str:
    if kind == "season_avg":
        return f"{stat}_season_avg"
    if kind == "last_10":
        return f"{stat}_avg_10"
    if kind == "ewm":
        return f"{stat}_ewm_{EWM_SPAN}"
    raise ValueError(kind)


def predict_baseline(frame: pd.DataFrame, stat: str, kind: BaselineKind) -> np.ndarray:
    col = baseline_column(stat, kind)
    if col not in frame.columns:
        return np.zeros(len(frame))
    return frame[col].fillna(frame.get(f"{stat}_avg_5", 0)).fillna(0).to_numpy(dtype=float)


BASELINE_KINDS: tuple[BaselineKind, ...] = ("season_avg", "last_10", "ewm")


def best_baseline_on_frame(frame: pd.DataFrame, stat: str, actual: pd.Series) -> tuple[BaselineKind, float]:
    """Return the baseline kind with lowest MAE on this frame."""
    best_kind: BaselineKind = "last_10"
    best_mae = float("inf")
    for kind in BASELINE_KINDS:
        pred = predict_baseline(frame, stat, kind)
        mae = float(np.mean(np.abs(actual.to_numpy() - pred)))
        if mae < best_mae:
            best_mae = mae
            best_kind = kind
    return best_kind, best_mae
