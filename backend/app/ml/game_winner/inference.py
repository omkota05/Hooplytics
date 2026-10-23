"""Game-winner inference."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

from app.ml.calibration import apply_isotonic
from app.ml.game_winner.artifacts import GameWinnerBundle, load_game_winner_bundle

_engine: GameWinnerEngine | None = None


def _sanitize_prob(p: float) -> float:
    if not math.isfinite(p):
        return 0.5
    return float(np.clip(p, 1e-6, 1 - 1e-6))


class GameWinnerEngine:
    def __init__(self, bundle: GameWinnerBundle) -> None:
        self.bundle = bundle

    def raw_home_win_prob(self, row: pd.DataFrame) -> float:
        b = self.bundle
        name = b.selected_model
        if name == "home_baseline":
            return float(b.home_baseline_rate)
        if name == "elo":
            return float(row["elo_home_win_prob"].iloc[0])
        cols = b.ml_feature_columns
        x = row[cols].fillna(0.0)
        if name == "logistic":
            assert b.logistic_pipeline is not None
            return float(b.logistic_pipeline.predict_proba(x)[0, 1])
        assert b.ml_classifier is not None
        return float(b.ml_classifier.predict_proba_home(x)[0])

    def predict_home_win_prob(self, row: pd.DataFrame) -> tuple[float, float, bool, str]:
        """Returns (production_prob, raw_model_prob, calibration_applied, status)."""
        raw = _sanitize_prob(self.raw_home_win_prob(row))
        if self.bundle.calibration_enabled and self.bundle.isotonic is not None:
            prod = _sanitize_prob(float(apply_isotonic(self.bundle.isotonic, np.array([raw]))[0]))
            status = "available"
            return prod, raw, True, status
        status = "experimental" if self.bundle.selected_model in ("logistic", "ml") else "available"
        return raw, raw, False, status


def get_game_winner_engine() -> GameWinnerEngine:
    global _engine
    if _engine is None:
        _engine = GameWinnerEngine(load_game_winner_bundle())
    return _engine


def reset_game_winner_engine() -> None:
    global _engine
    _engine = None
