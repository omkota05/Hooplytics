"""Synthetic candidate lines for prop recommendations (not sportsbook odds)."""

from __future__ import annotations

from collections.abc import Sequence

from app.analytics.categories import StatCategory, stat_value
from app.analytics.windows import GameWindow, played_games, select_games
from app.ingestion.providers.base import TRACKED_SEASON_TYPES
from app.ml.calibration import synthetic_line_from_mean
from app.models import PlayerGameStat


def synthetic_line_from_recent_mean(
    logs: Sequence[PlayerGameStat],
    category: StatCategory,
    *,
    window_n: int = 10,
) -> float | None:
    """floor(L10 category mean) + 0.5 — same family as ML calibration priors."""
    window = GameWindow(kind="last_n", n=window_n)
    eligible = [
        g
        for g in played_games(logs)
        if getattr(g, "season_type", 2) in TRACKED_SEASON_TYPES
    ]
    games = select_games(eligible, window, opponent_team_id=None)
    if len(games) < 3:
        return None
    values = [stat_value(g, category) for g in games[-window_n:]]
    if not values:
        return None
    mean = sum(values) / len(values)
    return synthetic_line_from_mean(mean)
