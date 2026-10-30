from datetime import date

from pydantic import BaseModel, Field

from app.schemas.common import TeamOut


class OpportunityMetricAverages(BaseModel):
    games: int = 0
    minutes: float | None = None
    fga: float | None = None
    fg3a: float | None = None


class OpportunityTrendOut(BaseModel):
    metric: str
    label: str
    recent_window: str
    recent_avg: float | None
    baseline_window: str
    baseline_avg: float | None
    difference: float | None
    note: str = "Observed historical change, not a prediction of future playing time or shot volume."


class OpportunityGameOut(BaseModel):
    game_id: int
    game_date: date
    opponent: TeamOut
    is_home: bool
    minutes: float | None
    fga: int | None
    fg3a: int | None


class PlayerOpportunityOut(BaseModel):
    player_id: int
    season: int | None = None
    l5: OpportunityMetricAverages
    l10: OpportunityMetricAverages
    l20: OpportunityMetricAverages
    season_to_date: OpportunityMetricAverages
    trends: list[OpportunityTrendOut]
    games: list[OpportunityGameOut] = Field(
        description="Played games, most recent first, for interactive charts."
    )
    disclaimer: str = (
        "Minutes and shot attempts are from synced ESPN box scores. "
        "Missing stats are omitted from averages, not treated as zero."
    )
