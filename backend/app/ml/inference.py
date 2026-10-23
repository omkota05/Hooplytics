"""Inference using saved model artifacts."""

from __future__ import annotations

from datetime import UTC

import numpy as np
import pandas as pd

from app.ml.artifacts import ModelArtifactsMissingError, ModelBundle, load_bundle
from app.ml.baselines import predict_baseline
from app.ml.calibration import apply_isotonic
from app.ml.constants import (
    MIN_GAMES_FOR_POINT_PREDICTION,
    MIN_GAMES_FOR_PROBABILITIES,
    components_for_category,
    is_supported_category,
)
from dataclasses import dataclass

from app.ml.constants import COMPONENT_STATS
from app.ml.prediction import LineProbability, StatProjection
from app.ml.probability import estimate_std_from_residuals, line_probabilities


@dataclass(frozen=True)
class PreparedPlayerGame:
    """One feature row + component means (reused across categories and lines)."""

    row: pd.DataFrame
    component_means: dict[str, float]
    games_before: int
    player_id: int
    game_id: int


class PredictionEngine:
    def __init__(self, bundle: ModelBundle | None = None) -> None:
        self._bundle = bundle

    @property
    def bundle(self) -> ModelBundle:
        if self._bundle is None:
            self._bundle = load_bundle()
        return self._bundle

    @property
    def model_version(self) -> str:
        return self.bundle.model_version

    def component_means_for_row(self, row: pd.DataFrame) -> dict[str, float]:
        return self._component_predictions(row)

    def prepare_player_game(self, row: pd.DataFrame, *, player_id: int, game_id: int) -> PreparedPlayerGame:
        if "games_before" in row.columns:
            games_before = int(pd.Series(row["games_before"]).iloc[0])
        else:
            games_before = 0
        return PreparedPlayerGame(
            row=row,
            component_means=self._component_predictions(row),
            games_before=games_before,
            player_id=player_id,
            game_id=game_id,
        )

    def _category_mean_and_std(self, component_means: dict[str, float], category: str) -> tuple[float, float]:
        mean = sum(component_means[c] for c in components_for_category(category))
        std = estimate_std_from_residuals(
            self.bundle.residual_std,
            self.bundle.residual_covariance,
            list(COMPONENT_STATS),
            category,
        )
        return float(mean), float(std)

    def _component_predictions(self, row: pd.DataFrame) -> dict[str, float]:
        bundle = self.bundle
        x = row[bundle.feature_columns].fillna(0.0)
        out: dict[str, float] = {}
        for stat in bundle.xgb_models:
            if bundle.component_selected_model[stat] == "ml":
                out[stat] = float(bundle.ml_models[stat].predict(x)[0])
            else:
                kind = bundle.component_baseline_kind[stat]
                out[stat] = float(predict_baseline(row, stat, kind)[0])
        return out

    def project_row(
        self, row: pd.DataFrame, category: str, *, player_id: int, game_id: int
    ) -> StatProjection:
        if not is_supported_category(category):
            raise ValueError(f"Unsupported category {category}")
        means = self._component_predictions(row)
        mean, std = self._category_mean_and_std(means, category)
        as_of = row["start_time"].iloc[0]
        if hasattr(as_of, "to_pydatetime"):
            as_of = as_of.to_pydatetime()
        if as_of.tzinfo is None:
            as_of = as_of.replace(tzinfo=UTC)
        return StatProjection(
            player_id=player_id,
            game_id=game_id,
            category=category,
            mean=float(mean),
            std_dev=float(std),
            model_version=self.model_version,
            features_as_of=as_of,
        )

    def line_probability_row(
        self, row: pd.DataFrame, category: str, line: float, *, player_id: int, game_id: int
    ) -> LineProbability:
        prepared = self.prepare_player_game(row, player_id=player_id, game_id=game_id)
        return self.line_probability_prepared(prepared, category, line)

    def line_probability_prepared(self, prepared: PreparedPlayerGame, category: str, line: float) -> LineProbability:
        if not is_supported_category(category):
            raise ValueError(f"Unsupported category {category}")
        if prepared.games_before < MIN_GAMES_FOR_POINT_PREDICTION:
            raise ValueError("Insufficient historical games for a prediction")
        mean, std = self._category_mean_and_std(prepared.component_means, category)
        as_of = prepared.row["start_time"].iloc[0]
        if hasattr(as_of, "to_pydatetime"):
            as_of = as_of.to_pydatetime()
        if as_of.tzinfo is None:
            as_of = as_of.replace(tzinfo=UTC)
        projection = StatProjection(
            player_id=prepared.player_id,
            game_id=prepared.game_id,
            category=category,
            mean=mean,
            std_dev=std,
            model_version=self.model_version,
            features_as_of=as_of,
        )
        if prepared.games_before < MIN_GAMES_FOR_PROBABILITIES:
            return LineProbability(
                projection=projection,
                line=line,
                p_over=None,
                p_under=None,
                p_push=None,
            )
        p_over, p_under, p_push = line_probabilities(mean, std, line)
        iso = self.bundle.isotonic_calibrators.get(category)
        if iso is not None:
            p_over = float(apply_isotonic(iso, np.array([p_over]))[0])
            p_under = max(0.0, 1.0 - p_over)
        return LineProbability(
            projection=projection,
            line=line,
            p_over=p_over,
            p_under=p_under,
            p_push=p_push,
        )


_engine: PredictionEngine | None = None


def get_prediction_engine() -> PredictionEngine:
    global _engine
    if _engine is None:
        try:
            _engine = PredictionEngine()
        except ModelArtifactsMissingError:
            raise
    return _engine


def reset_prediction_engine() -> None:
    global _engine
    _engine = None
