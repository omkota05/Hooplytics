from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.analysis import DistributionOut, LineResultOut


class HistoricalHitRateOut(BaseModel):
    """Empirical over/under rates from synced history (not model probability)."""

    window_label: str
    games: int
    line_result: LineResultOut
    distribution: DistributionOut
    small_sample: bool
    note: str | None = None


class PlayerStatPredictionOut(BaseModel):
    player_id: int
    player_name: str
    game_id: int
    opponent_team_id: int
    category: str
    category_label: str
    line: float
    predicted_mean: float = Field(description="Model point projection")
    predicted_std_dev: float = Field(description="Estimated predictive standard deviation")
    p_over: float | None = None
    p_under: float | None = None
    p_push: float | None = None
    probability_status: Literal["available", "experimental", "unavailable"]
    historical_hit_rate: HistoricalHitRateOut | None = None
    model_version: str
    selected_model_summary: str
    predicted_at: datetime
    disclaimer: str = (
        "Model probabilities are statistical estimates from historical patterns, not betting advice."
    )


class ModelMetricsCategoryOut(BaseModel):
    category: str
    n_train: int
    n_val: int
    n_test: int
    test_start: str
    test_end: str
    mae_baseline: float
    rmse_baseline: float
    mae_ml: float
    rmse_ml: float
    selected_model: str
    brier_test_pregame_line: float | None = None
    brier_test_calibrated: float | None = None


class ModelMetricsOut(BaseModel):
    version: str
    trained_at: str | None = None
    categories: list[ModelMetricsCategoryOut]
    calibration: dict | None = None
    split_audit: dict | None = None


class GameOutcomeFactorsOut(BaseModel):
    home_elo: float
    away_elo: float
    elo_home_win_prob: float
    home_win_pct_season: float
    away_win_pct_season: float
    home_rest_days: float
    away_rest_days: float
    home_b2b: bool
    away_b2b: bool
    h2h_home_win_pct: float
    neutral_site: bool
    games_before_home: int = 0
    games_before_away: int = 0


class GameOutcomePredictionOut(BaseModel):
    game_id: int
    home_team_id: int
    away_team_id: int
    home_team_name: str
    away_team_name: str
    start_time: datetime
    home_win_probability: float
    away_win_probability: float
    model_home_win_probability_raw: float = Field(
        description="Uncalibrated model probability (before isotonic, if any)"
    )
    calibration_applied: bool = False
    selected_model: str
    model_version: str
    probability_status: Literal["available", "experimental", "unavailable"]
    predicted_at: datetime
    factors: GameOutcomeFactorsOut
    disclaimer: str = (
        "Win probabilities are statistical estimates from historical patterns, not betting advice."
    )


class GameWinnerMetricsOut(BaseModel):
    version: str
    trained_at: str | None = None
    selected_model: str
    calibration_enabled: bool = False
    n_train: int
    n_val: int
    n_test: int
    test_start: str
    test_end: str
    test_metrics: dict
    validation_log_loss: dict
    prior_model_baseline_report: dict | None = None
