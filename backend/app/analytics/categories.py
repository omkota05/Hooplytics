"""Stat categories, including combined ones derived from individual box-score fields.

Combined categories are sums of components computed per game, so PRA, P+A, etc.
never need their own provider calls or columns.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

BOX_SCORE_FIELDS = ("pts", "reb", "ast", "fg3m", "stl", "blk", "tov")


@dataclass(frozen=True)
class StatCategory:
    key: str
    label: str
    short_label: str
    components: tuple[str, ...]

    @property
    def is_combined(self) -> bool:
        return len(self.components) > 1


_CATEGORIES = (
    StatCategory("pts", "Points", "PTS", ("pts",)),
    StatCategory("reb", "Rebounds", "REB", ("reb",)),
    StatCategory("ast", "Assists", "AST", ("ast",)),
    StatCategory("fg3m", "Three-Pointers Made", "3PM", ("fg3m",)),
    StatCategory("stl", "Steals", "STL", ("stl",)),
    StatCategory("blk", "Blocks", "BLK", ("blk",)),
    StatCategory("tov", "Turnovers", "TOV", ("tov",)),
    StatCategory("pts_reb", "Points + Rebounds", "P+R", ("pts", "reb")),
    StatCategory("pts_ast", "Points + Assists", "P+A", ("pts", "ast")),
    StatCategory("reb_ast", "Rebounds + Assists", "R+A", ("reb", "ast")),
    StatCategory("pts_reb_ast", "Points + Rebounds + Assists", "PRA", ("pts", "reb", "ast")),
    StatCategory("stl_blk", "Steals + Blocks", "S+B", ("stl", "blk")),
)

CATEGORIES: dict[str, StatCategory] = {c.key: c for c in _CATEGORIES}


class UnknownCategoryError(ValueError):
    pass


def get_category(key: str) -> StatCategory:
    try:
        return CATEGORIES[key]
    except KeyError as exc:
        raise UnknownCategoryError(f"Unknown stat category '{key}'. Valid: {', '.join(CATEGORIES)}") from exc


def stat_value(game: Mapping[str, Any] | Any, category: StatCategory) -> float | None:
    """Value of `category` for one game, or None if any component is missing."""
    total = 0.0
    for field in category.components:
        value = game.get(field) if isinstance(game, Mapping) else getattr(game, field, None)
        if value is None:
            return None
        total += value
    return total
