"""Minutes and shot-volume trends from synced box scores (no ML)."""

from __future__ import annotations

from datetime import datetime
from typing import Sequence

from sqlalchemy.orm import Session

from app.analytics.windows import GameWindow, played_games, select_games
from app.ingestion.providers.base import TRACKED_SEASON_TYPES
from app.models import PlayerGameStat
from app.repositories import players as players_repo
from app.schemas.opportunity import (
    OpportunityGameOut,
    OpportunityMetricAverages,
    OpportunityTrendOut,
    PlayerOpportunityOut,
)
from app.services.errors import NotFoundError
from app.services.serializers import team_out

_WINDOWS = (("l5", 5), ("l10", 10), ("l20", 20))


def _mean(values: Sequence[float | int | None]) -> float | None:
    nums = [float(v) for v in values if v is not None]
    if not nums:
        return None
    return round(sum(nums) / len(nums), 1)


def _eligible_logs(
    session: Session,
    player_id: int,
    *,
    before_start: datetime | None,
) -> list[PlayerGameStat]:
    logs = players_repo.player_game_logs(session, player_id)
    games = [g for g in played_games(logs) if g.season_type in TRACKED_SEASON_TYPES]
    if before_start is not None:
        games = [g for g in games if g.game.start_time and g.game.start_time < before_start]
    return games


def _averages_for_games(games: Sequence[PlayerGameStat]) -> OpportunityMetricAverages:
    return OpportunityMetricAverages(
        games=len(games),
        minutes=_mean([g.minutes for g in games]),
        fga=_mean([g.fga for g in games]),
        fg3a=_mean([g.fg3a for g in games]),
    )


def _trend(
    metric: str,
    label: str,
    recent: OpportunityMetricAverages,
    baseline: OpportunityMetricAverages,
    recent_window: str,
    baseline_window: str,
) -> OpportunityTrendOut:
    recent_val = getattr(recent, metric)
    base_val = getattr(baseline, metric)
    diff = None
    if recent_val is not None and base_val is not None:
        diff = round(recent_val - base_val, 1)
    return OpportunityTrendOut(
        metric=metric,
        label=label,
        recent_window=recent_window,
        recent_avg=recent_val,
        baseline_window=baseline_window,
        baseline_avg=base_val,
        difference=diff,
    )


def build_opportunity(
    session: Session,
    player_id: int,
    *,
    before_start: datetime | None = None,
    season: int | None = None,
) -> PlayerOpportunityOut:
    if players_repo.get_player(session, player_id) is None:
        raise NotFoundError(f"Player {player_id} not found")

    logs = _eligible_logs(session, player_id, before_start=before_start)
    window_avgs: dict[str, OpportunityMetricAverages] = {}
    for key, n in _WINDOWS:
        subset = select_games(logs, GameWindow(kind="last_n", n=n), None)
        window_avgs[key] = _averages_for_games(subset)

    season_avg = OpportunityMetricAverages()
    if season is not None:
        subset = select_games(logs, GameWindow(kind="season", season=season), None)
        season_avg = _averages_for_games(subset)
    elif logs:
        latest_season = max(g.season for g in logs)
        subset = select_games(logs, GameWindow(kind="season", season=latest_season), None)
        season = latest_season
        season_avg = _averages_for_games(subset)

    trends = [
        _trend("minutes", "Minutes", window_avgs["l5"], window_avgs["l20"], "L5", "L20"),
        _trend("minutes", "Minutes", window_avgs["l5"], season_avg, "L5", "Season"),
        _trend("fga", "FGA", window_avgs["l5"], window_avgs["l20"], "L5", "L20"),
        _trend("fg3a", "3PA", window_avgs["l5"], window_avgs["l20"], "L5", "L20"),
    ]

    chart_games = select_games(logs, GameWindow(kind="last_n", n=82), None)
    games_out = [
        OpportunityGameOut(
            game_id=g.game_id,
            game_date=g.game_date,
            opponent=team_out(g.opponent),
            is_home=g.is_home,
            minutes=g.minutes,
            fga=g.fga,
            fg3a=g.fg3a,
        )
        for g in reversed(chart_games)
    ]

    return PlayerOpportunityOut(
        player_id=player_id,
        season=season,
        l5=window_avgs["l5"],
        l10=window_avgs["l10"],
        l20=window_avgs["l20"],
        season_to_date=season_avg,
        trends=trends,
        games=games_out,
    )
