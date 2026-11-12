from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.schemas.analysis import StatCategoryOut


class HitStreakGameOut(BaseModel):
    game_id: int
    game_date: date
    opponent_abbreviation: str | None = None
    stat_value: float | None = None
    outcome: Literal["over", "under", "push"] | None = None
    bet_result: Literal["hit", "miss", "push"] | None = None


class HitStreakSummaryOut(BaseModel):
    current_streak: int
    streak_at_least: bool = False
    streak_label: str
    avg_clearance_margin: float | None = None
    games_evaluated: int = 0
    last_completed_game_date: date | None = None
    recent_results: list[HitStreakGameOut] = Field(default_factory=list)
    l5_record: str
    l10_record: str
    l20_record: str
    l5_hit_pct: float | None = None
    l10_hit_pct: float | None = None
    l20_hit_pct: float | None = None
    push_count_in_streak_window: int = 0
    missing_data_flags: list[str] = Field(default_factory=list)


class HitStreakRowOut(BaseModel):
    offer_id: int
    player_id: int | None
    player_name: str
    team_abbreviation: str | None = None
    game_id: int | None
    matchup_label: str | None = None
    opponent_abbreviation: str | None = None
    opponent_team_id: int | None = None
    game_start_time: datetime | None = None
    game_date: date | None = None
    category: StatCategoryOut
    line: float
    pick_side: Literal["over", "under"]
    sportsbook: str
    hcs_score: float | None = None
    streak: HitStreakSummaryOut


class HitStreakListOut(BaseModel):
    rows: list[HitStreakRowOut]
    total: int
    total_available: int
    total_eligible_offers: int
    limit: int
    offset: int
    current_season_only: bool
    sort: str
    timing_ms: float | None = None
    disclaimer: str
