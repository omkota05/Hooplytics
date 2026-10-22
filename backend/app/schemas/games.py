from pydantic import BaseModel

from app.schemas.common import GameOut, PlayerSummaryOut


class RecentFormOut(BaseModel):
    games: int
    minutes: float | None
    pts: float | None
    reb: float | None
    ast: float | None


class GamePlayerOut(BaseModel):
    player: PlayerSummaryOut
    recent: RecentFormOut | None


class BoxScoreLineOut(BaseModel):
    player: PlayerSummaryOut
    starter: bool
    did_not_play: bool
    dnp_reason: str | None
    minutes: float | None
    pts: int | None
    reb: int | None
    ast: int | None
    stl: int | None
    blk: int | None
    tov: int | None
    fg3m: int | None
    plus_minus: int | None


class GameDetailOut(BaseModel):
    game: GameOut
    # Current rosters for upcoming games; actual participants for completed games.
    home_players: list[GamePlayerOut]
    away_players: list[GamePlayerOut]
    players_source: str
    home_boxscore: list[BoxScoreLineOut]
    away_boxscore: list[BoxScoreLineOut]
    previous_meetings: list[GameOut]


class TopPerformerOut(BaseModel):
    player: PlayerSummaryOut
    game: GameOut
    pts: int
    reb: int
    ast: int
