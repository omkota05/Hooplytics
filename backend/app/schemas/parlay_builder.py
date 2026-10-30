from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.analysis import StatCategoryOut
from app.schemas.hcs import HCSBreakdownOut


class ParlaySearchIn(BaseModel):
    legs: int = Field(default=3, ge=2, le=5)
    analysis_window: Literal["l5", "l10", "l20", "l30"] = "l20"
    min_games: Literal[5, 10, 15, 20] = 10
    upcoming_days: Literal[1, 3, 7] = 3
    sportsbook: str | None = None
    pick_side: Literal["both", "over", "under"] = "both"
    category: str | None = None
    team_id: int | None = None
    min_hit_pct: float | None = Field(default=None, ge=0, le=100)
    different_games_only: bool = True
    one_per_player: bool = True
    limit: int = Field(default=10, ge=1, le=20)


class ParlayLegScoreOut(BaseModel):
    hcs: float
    component_historical: float
    component_cushion: float
    component_minutes: float
    h_weighted: float
    h_shrunk: float
    hits: int
    misses: int
    pushes: int
    qualifying_games: int
    effective_sample_size: float
    median: float | None
    iqr: float | None
    c_cushion: float
    m_modifier: float
    m5_minutes: float | None
    m20_minutes: float | None
    analysis_window: str
    missing_data_flags: list[str] = []
    version: str


class ParlayPCSBreakdownOut(BaseModel):
    version: str
    pcs: float
    geometric_mean: float
    min_leg: float
    length_factor: float
    leg_hcs: list[float]


class ParlayLegOut(BaseModel):
    prop_offer_id: int
    player_id: int
    player_name: str
    game_id: int
    opponent_label: str | None
    category: StatCategoryOut
    line: float
    pick_side: Literal["over", "under"]
    american_odds: int | None
    sportsbook: str
    game_start_time: datetime | None
    l10_hits: int | None
    l10_attempts: int | None
    l10_hit_pct: float | None
    l20_hits: int | None
    l20_attempts: int | None
    l20_hit_pct: float | None
    games_in_window: int | None
    score: ParlayLegScoreOut
    hcs_breakdown: HCSBreakdownOut | None = None
    prop_analyzer_path: str


class ParlayCombinationOut(BaseModel):
    rank: int
    parlay_consistency_score: float
    historical_consistency_score: float  # alias for PCS (backward compat)
    min_leg_score: float
    avg_leg_score: float
    pcs_breakdown: ParlayPCSBreakdownOut | None = None
    legs: list[ParlayLegOut]
    sportsbook: str | None
    explanation: str
    indicative_decimal_odds: float | None = None
    indicative_payout_note: str | None = None
    same_game_warning: str | None = None


class ParlaySearchMetaOut(BaseModel):
    candidates_considered: int
    combinations_evaluated: int
    generation_ms: float
    last_import_finished_at: datetime | None
    stale_warning: str | None = None
    hcs_version: str = "hcs_v2"
    pcs_version: str = "pcs_v2"


class ParlaySearchOut(BaseModel):
    meta: ParlaySearchMetaOut
    combinations: list[ParlayCombinationOut]
    disclaimer: str = (
        "Historical Consistency Scores and Parlay Consistency Scores summarize past results "
        "against posted sportsbook lines. They are descriptive ranking indexes, not win "
        "probabilities, predictions, or betting advice."
    )
