from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.common import GameOut, PlayerSummaryOut, TeamOut
from app.schemas.prediction import GameOutcomeFactorsOut


class HistoricalWindowHitOut(BaseModel):
    window: Literal["L5", "L10", "L20"]
    games: int
    over_pct: float | None
    under_pct: float | None
    small_sample: bool


class PlayerPropRecommendationOut(BaseModel):
    player: PlayerSummaryOut
    opponent: TeamOut
    game: GameOut
    category: str
    category_label: str
    line: float
    line_source: str = Field(
        description="How the threshold was chosen (synthetic, not a sportsbook line)"
    )
    predicted_mean: float
    predicted_std_dev: float
    pick_side: Literal["over", "under"]
    model_probability: float
    p_over: float | None
    p_under: float | None
    probability_status: Literal["available", "experimental", "unavailable"]
    games_used: int
    historical_hit_rates: list[HistoricalWindowHitOut]
    model_version: str
    player_analysis_href: str


class GameWinnerWarningOut(BaseModel):
    code: str
    message: str


class GameWinnerRecommendationOut(BaseModel):
    game: GameOut
    home_win_probability: float
    away_win_probability: float
    model_home_win_probability_raw: float
    calibration_applied: bool
    elo_home_win_probability: float
    predicted_winner_team_id: int
    selected_model: str
    model_version: str
    probability_status: Literal["available", "experimental", "unavailable"]
    factors: GameOutcomeFactorsOut
    warnings: list[GameWinnerWarningOut]
    matchup_href: str


class RecommendationsPipelineOut(BaseModel):
    """Counts for diagnosing empty or sparse recommendation feeds."""

    upcoming_games: int = 0
    rotation_player_slots: int = 0
    ml_prop_attempts: int = 0
    props_skipped_no_line: int = 0
    props_skipped_ml: int = 0
    props_candidates_before_dedupe: int = 0
    props_after_dedupe: int = 0
    props_filtered_by_query: int = 0
    player_game_prepares: int = 0


class RecommendationsMetaOut(BaseModel):
    generated_at: datetime
    player_model_version: str | None
    game_winner_model_version: str | None
    upcoming_games_scanned: int
    player_props_generated: int
    game_winners_generated: int
    data_sync_reference: str | None
    disclaimer: str
    pipeline: RecommendationsPipelineOut = Field(default_factory=RecommendationsPipelineOut)
    generation_ms: float | None = None


class RecommendationsOut(BaseModel):
    meta: RecommendationsMetaOut
    player_props: list[PlayerPropRecommendationOut]
    game_winners: list[GameWinnerRecommendationOut]
    categories: list[str]
    errors: list[str] = Field(default_factory=list)
