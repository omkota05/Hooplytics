from datetime import date

from pydantic import BaseModel

from app.schemas.common import GameOut, PlayerSummaryOut, TeamOut


class SeasonAveragesOut(BaseModel):
    season: int
    season_label: str
    games: int
    starts: int
    minutes: float | None
    pts: float | None
    reb: float | None
    ast: float | None
    stl: float | None
    blk: float | None
    tov: float | None
    fg3m: float | None
    fg_pct: float | None
    fg3_pct: float | None
    ft_pct: float | None


class TeamSeasonOut(BaseModel):
    season: int
    season_label: str
    team: TeamOut
    games_played: int


class PlayerProfileOut(BaseModel):
    player: PlayerSummaryOut
    height_in: float | None
    weight_lb: float | None
    birth_date: date | None
    current_season: int | None
    available_seasons: list[int]
    season_averages: SeasonAveragesOut | None
    team_history: list[TeamSeasonOut]
    upcoming_games: list[GameOut]
    last_game_date: date | None
    total_games_tracked: int


class DirectoryRowOut(BaseModel):
    player: PlayerSummaryOut
    season: int | None
    games: int
    minutes: float | None
    pts: float | None
    reb: float | None
    ast: float | None


class GameLogEntryOut(BaseModel):
    game_id: int
    game_date: date
    season: int
    season_label: str
    season_type: int
    opponent: TeamOut
    is_home: bool
    team_score: int | None
    opponent_score: int | None
    result: str | None
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
    fgm: int | None
    fga: int | None
    fg3m: int | None
    fg3a: int | None
    ftm: int | None
    fta: int | None
    plus_minus: int | None
