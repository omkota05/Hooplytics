from datetime import date
from typing import Literal

from pydantic import BaseModel

from app.schemas.common import TeamOut


class StatCategoryOut(BaseModel):
    key: str
    label: str
    short_label: str
    components: list[str]
    is_combined: bool


class WindowOut(BaseModel):
    kind: Literal["last_n", "season", "date_range", "all"]
    n: int | None
    season: int | None
    start_date: date | None
    end_date: date | None
    opponent_team_id: int | None
    season_types: list[int]


class AnalysisGameOut(BaseModel):
    game_id: int
    game_date: date
    season: int
    season_label: str
    season_type: int
    opponent: TeamOut
    is_home: bool
    result: str | None
    team_score: int | None
    opponent_score: int | None
    minutes: float | None
    value: float
    outcome: Literal["over", "under", "push"]
    components: dict[str, int | None]


class DistributionOut(BaseModel):
    count: int
    mean: float | None
    median: float | None
    std_dev: float | None
    minimum: float | None
    maximum: float | None


class LineResultOut(BaseModel):
    line: float
    total: int
    over: int
    under: int
    push: int
    over_pct: float | None
    under_pct: float | None
    push_pct: float | None
    over_pct_excluding_pushes: float | None


class StatAnalysisOut(BaseModel):
    player_id: int
    category: StatCategoryOut
    window: WindowOut
    opponent: TeamOut | None
    # Chronological (oldest first) so charts read left to right.
    games: list[AnalysisGameOut]
    distribution: DistributionOut
    line_result: LineResultOut
    small_sample: bool
    available_games: int
    note: str


class MatchupComparisonOut(BaseModel):
    player_id: int
    opponent: TeamOut
    recent: StatAnalysisOut
    head_to_head: StatAnalysisOut
