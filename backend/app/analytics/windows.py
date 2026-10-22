"""Historical game-window selection (last N, season, date range, opponent)."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from typing import Literal, Protocol, TypeVar

WindowKind = Literal["last_n", "season", "date_range", "all"]


class GameLike(Protocol):
    game_date: date
    season: int
    opponent_team_id: int
    did_not_play: bool


G = TypeVar("G", bound=GameLike)


class InvalidWindowError(ValueError):
    pass


@dataclass(frozen=True)
class GameWindow:
    kind: WindowKind
    n: int | None = None
    season: int | None = None
    start_date: date | None = None
    end_date: date | None = None

    def __post_init__(self) -> None:
        if self.kind == "last_n" and (self.n is None or self.n < 1):
            raise InvalidWindowError("last_n window requires n >= 1")
        if self.kind == "season" and self.season is None:
            raise InvalidWindowError("season window requires a season")
        if self.kind == "date_range":
            if self.start_date is None or self.end_date is None:
                raise InvalidWindowError("date_range window requires start_date and end_date")
            if self.start_date > self.end_date:
                raise InvalidWindowError("start_date must be on or before end_date")


def played_games(games: Sequence[G]) -> list[G]:
    """Games the player actually appeared in. DNPs are excluded from every sample,
    mirroring how player props are voided when a player does not play."""
    return [g for g in games if not g.did_not_play]


def most_recent_first(games: Sequence[G]) -> list[G]:
    return sorted(games, key=lambda g: g.game_date, reverse=True)


def filter_opponent(games: Sequence[G], opponent_team_id: int | None) -> list[G]:
    if opponent_team_id is None:
        return list(games)
    return [g for g in games if g.opponent_team_id == opponent_team_id]


def apply_window(games: Sequence[G], window: GameWindow) -> list[G]:
    """Select games for `window`, returned most recent first."""
    ordered = most_recent_first(games)
    match window.kind:
        case "last_n":
            return ordered[: window.n]
        case "season":
            return [g for g in ordered if g.season == window.season]
        case "date_range":
            return [g for g in ordered if window.start_date <= g.game_date <= window.end_date]
        case "all":
            return ordered
    raise InvalidWindowError(f"Unknown window kind {window.kind!r}")


def select_games(games: Sequence[G], window: GameWindow, opponent_team_id: int | None = None) -> list[G]:
    """Played games, optionally against one opponent, within the window."""
    return apply_window(filter_opponent(played_games(games), opponent_team_id), window)
