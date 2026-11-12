from datetime import date
from typing import Literal

from pydantic import BaseModel

from app.schemas.analysis import MatchupComparisonOut
from app.schemas.common import TeamOut
from app.schemas.opportunity import PlayerOpportunityOut
from app.schemas.hit_streaks import HitStreakSummaryOut
from app.schemas.prop_finder import PropFinderDetailOut


class PropAnalyzerGameRowOut(BaseModel):
    game_id: int
    game_date: date
    opponent: TeamOut
    is_home: bool
    minutes: float | None
    pts: int | None
    reb: int | None
    ast: int | None
    fga: int | None
    fg3a: int | None
    prop_value: float | None
    outcome: Literal["over", "under", "push"] | None = None


class PropAnalyzerOut(BaseModel):
    prop: PropFinderDetailOut
    opportunity: PlayerOpportunityOut | None = None
    matchup: MatchupComparisonOut | None = None
    game_log: list[PropAnalyzerGameRowOut] = []
    hit_streak: HitStreakSummaryOut | None = None
