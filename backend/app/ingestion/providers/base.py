"""Provider-neutral records produced by data providers and consumed by the sync layer.

Any provider (ESPN today, potentially NBA Stats later) must normalize into these types,
so the database and analytics layers never depend on a provider's raw JSON shape.
"""

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Protocol

GAME_STATUSES = ("scheduled", "in_progress", "final", "postponed", "canceled", "suspended")

REGULAR_SEASON = 2
POSTSEASON = 3
PLAY_IN = 5
TRACKED_SEASON_TYPES = (REGULAR_SEASON, POSTSEASON, PLAY_IN)


@dataclass(frozen=True)
class TeamRecord:
    id: int
    abbreviation: str
    display_name: str
    short_name: str
    location: str
    color: str | None = None
    alternate_color: str | None = None
    logo_url: str | None = None


@dataclass(frozen=True)
class PlayerRecord:
    id: int
    full_name: str
    first_name: str | None = None
    last_name: str | None = None
    position: str | None = None
    jersey: str | None = None
    headshot_url: str | None = None
    height_in: float | None = None
    weight_lb: float | None = None
    birth_date: date | None = None


@dataclass(frozen=True)
class GameRecord:
    id: int
    season: int
    season_type: int
    start_time: datetime
    game_date: date
    home_team_id: int
    away_team_id: int
    status: str
    status_detail: str | None = None
    home_score: int | None = None
    away_score: int | None = None
    venue_name: str | None = None
    venue_city: str | None = None
    venue_state: str | None = None
    neutral_site: bool = False


@dataclass(frozen=True)
class PlayerGameStatRecord:
    player_id: int
    game_id: int
    team_id: int
    opponent_team_id: int
    is_home: bool
    starter: bool
    did_not_play: bool
    dnp_reason: str | None = None
    minutes: float | None = None
    pts: int | None = None
    reb: int | None = None
    ast: int | None = None
    stl: int | None = None
    blk: int | None = None
    tov: int | None = None
    fgm: int | None = None
    fga: int | None = None
    fg3m: int | None = None
    fg3a: int | None = None
    ftm: int | None = None
    fta: int | None = None
    oreb: int | None = None
    dreb: int | None = None
    pf: int | None = None
    plus_minus: int | None = None


@dataclass
class BoxScore:
    game: GameRecord | None
    players: list[PlayerRecord] = field(default_factory=list)
    stats: list[PlayerGameStatRecord] = field(default_factory=list)

    @property
    def is_complete(self) -> bool:
        return bool(self.stats)


@dataclass(frozen=True)
class RosterEntry:
    player: PlayerRecord
    team_id: int


class DataProvider(Protocol):
    name: str

    def current_season(self) -> int: ...

    def fetch_teams(self) -> list[TeamRecord]: ...

    def fetch_roster(self, team_id: int) -> list[RosterEntry]: ...

    def fetch_team_schedule(self, team_id: int, season: int, season_type: int) -> list[GameRecord]: ...

    def fetch_scoreboard(self, day: date) -> list[GameRecord]: ...

    def fetch_boxscore(self, game_id: int) -> BoxScore: ...

    @property
    def request_count(self) -> int: ...
