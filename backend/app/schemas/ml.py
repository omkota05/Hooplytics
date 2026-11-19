from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

ProbabilityStatus = Literal["validated_real_lines", "experimental", "unavailable", "disabled_by_flag"]


class FlagsOut(BaseModel):
    enable_ml_inference: bool
    enable_ml_experimental_ui: bool
    enable_ml_recommendations: bool
    enable_ml_probabilities: bool


class ModelStatusOut(BaseModel):
    loaded: bool
    active_version: str | None
    previous_version: str | None
    versions: list[str]
    trained_at: str | None = None
    dataset_cutoff: str | None = None
    feature_version: str | None = None
    split: dict[str, Any] | None = None
    selected_models: dict[str, str] | None = None
    probability_status: dict[str, str] | None = None
    probability_gates: dict[str, Any] | None = None
    acceptance_checks: dict[str, bool] | None = None
    timings_seconds: dict[str, float] | None = None
    data_validation: dict[str, Any] | None = None
    final_games_since_training_cutoff: int | None = None
    last_sync_at: datetime | None = None
    model_load_seconds: float | None = None
    last_batch_seconds: float | None = None
    odds_archive: dict[str, Any] | None = None
    flags: FlagsOut
    warnings: list[str]


class CategoryProjectionOut(BaseModel):
    category: str
    label: str
    mean: float
    median: float
    p10: float
    p90: float
    sd: float
    probability_status: ProbabilityStatus


class PlayerProjectionOut(BaseModel):
    player_id: int
    player_name: str
    team_id: int
    team_abbreviation: str | None
    opponent_team_id: int
    opponent_abbreviation: str | None
    game_id: int
    start_time: datetime
    is_home: bool
    appearances: int
    season_appearances: int
    projected_minutes: float
    categories: list[CategoryProjectionOut]
    context: dict[str, float | None]
    warnings: list[str]
    model_version: str
    data_last_sync_at: datetime | None
    dataset_cutoff: str
    experimental: bool = True
    disclaimer: str = (
        "Statistical projection from historical box scores. Not a guarantee or betting advice; "
        "probabilities are experimental unless marked validated on archived sportsbook lines."
    )


class PropEstimateOut(BaseModel):
    player_id: int
    game_id: int
    category: str
    line: float
    mean: float
    median: float
    p10: float
    p90: float
    p_over: float | None
    p_under: float | None
    p_push: float | None
    probability_status: ProbabilityStatus
    probability_note: str
    n_samples: int
    warnings: list[str]
    model_version: str


class UpcomingProjectionRowOut(BaseModel):
    player_id: int
    player_name: str
    team_abbreviation: str | None
    opponent_abbreviation: str | None
    game_id: int
    start_time: datetime
    projected_minutes: float
    pts: float
    reb: float
    ast: float
    fg3m: float
    pra: float
    appearances: int
    warnings: list[str]


class UpcomingProjectionsOut(BaseModel):
    rows: list[UpcomingProjectionRowOut]
    total: int
    model_version: str
    batch_seconds: float | None


class ComparisonRowOut(BaseModel):
    offer_id: int
    player_id: int
    player_name: str
    team_abbreviation: str | None
    opponent_abbreviation: str | None
    game_id: int
    start_time: datetime
    sportsbook: str
    category: str
    category_label: str
    line: float
    side: str
    american_odds: int | None
    projected_mean: float
    projected_median: float
    p10: float
    p90: float
    projection_gap: float = Field(description="(projected mean - line) / predictive SD; descriptive, not a probability")
    model_leans: Literal["over", "under", "neutral"]
    agrees_with_side: bool
    p_side: float | None
    probability_status: ProbabilityStatus
    l10_hit_pct: float | None
    l20_hit_pct: float | None
    l10_games: int | None
    l20_games: int | None
    hcs_score: float | None
    appearances: int
    eligible: bool
    ineligible_reasons: list[str]
    warnings: list[str]


class ComparisonOut(BaseModel):
    mode: Literal["validated", "experimental_comparison", "disabled"]
    mode_explanation: str
    rows: list[ComparisonRowOut]
    total: int
    total_offers_considered: int
    model_version: str | None
    last_import_finished_at: datetime | None
    sportsbooks: list[str]
    gating: dict[str, Any]
