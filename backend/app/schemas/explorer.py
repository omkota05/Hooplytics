from datetime import datetime

from pydantic import BaseModel

from app.schemas.analysis import DistributionOut, LineResultOut, StatCategoryOut
from app.schemas.common import PlayerSummaryOut, TeamOut


class TrendRowOut(BaseModel):
    player: PlayerSummaryOut
    opponent: TeamOut | None
    game_id: int | None
    game_start: datetime | None
    distribution: DistributionOut
    line_result: LineResultOut
    recent_values: list[float]


class TrendExplorerOut(BaseModel):
    category: StatCategoryOut
    line: float
    last_n: int
    min_games: int
    scope: str
    rows: list[TrendRowOut]
    note: str
