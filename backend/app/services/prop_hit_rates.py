"""Historical hit rates for sportsbook lines (no ML)."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Literal

from sqlalchemy.orm import Session

from app.analytics.categories import get_category, stat_value
from app.analytics.lines import classify, evaluate_line
from app.analytics.windows import GameWindow, played_games, select_games
from app.ingestion.providers.base import TRACKED_SEASON_TYPES
from app.repositories import players as players_repo

Side = Literal["over", "under"]

WINDOW_LAST_N = (5, 10, 15, 20, 30)
H2H_WINDOWS = (3, 5, 10)


@dataclass(frozen=True)
class WindowHitRate:
    window: str
    games: int
    over_hits: int
    under_hits: int
    pushes: int
    over_hit_pct: float | None
    under_hit_pct: float | None
    push_pct: float | None


@dataclass(frozen=True)
class PropHitRateBundle:
    historical_avg: float | None
    windows: list[WindowHitRate]

    def to_json(self) -> dict:
        return {
            "historical_avg": self.historical_avg,
            "windows": [asdict(w) for w in self.windows],
        }


def _hit_pcts(result, side: Side) -> tuple[float | None, float | None]:
    decided = result.over + result.under
    if decided == 0:
        return None, None
    over_pct = round(100 * result.over / decided, 1)
    under_pct = round(100 * result.under / decided, 1)
    return over_pct, under_pct


def _window_result(values: list[float], line: float, window_label: str, side: Side) -> WindowHitRate:
    result = evaluate_line(values, line)
    over_pct, under_pct = _hit_pcts(result, side)
    return WindowHitRate(
        window=window_label,
        games=result.total,
        over_hits=result.over,
        under_hits=result.under,
        pushes=result.push,
        over_hit_pct=over_pct,
        under_hit_pct=under_pct,
        push_pct=result.push_pct,
    )


def compute_prop_hit_rates(
    session: Session,
    *,
    player_id: int,
    category_key: str,
    line: float,
    opponent_team_id: int | None,
    season: int | None,
    before_start: datetime | None,
) -> PropHitRateBundle:
    category = get_category(category_key)
    logs = players_repo.player_game_logs(session, player_id)
    games = played_games(logs)
    if before_start is not None:
        games = [g for g in games if g.game.start_time < before_start]
    games = [g for g in games if g.season_type in TRACKED_SEASON_TYPES]

    def values_for(window: GameWindow, opp: int | None) -> list[float]:
        subset = select_games(games, window, opponent_team_id=opp)
        out: list[float] = []
        for g in subset:
            v = stat_value(g, category)
            if v is not None:
                out.append(float(v))
        return out

    windows: list[WindowHitRate] = []
    for n in WINDOW_LAST_N:
        vals = values_for(GameWindow(kind="last_n", n=n), None)
        windows.append(_window_result(vals, line, f"L{n}", "over"))

    if season is not None:
        vals = values_for(GameWindow(kind="season", season=season), None)
        windows.append(_window_result(vals, line, "season", "over"))
    else:
        windows.append(
            WindowHitRate("season", 0, 0, 0, 0, None, None, None),
        )

    if opponent_team_id is not None:
        for n in H2H_WINDOWS:
            vals = values_for(GameWindow(kind="last_n", n=n), opponent_team_id)
            windows.append(_window_result(vals, line, f"H2H_L{n}", "over"))
    else:
        for n in H2H_WINDOWS:
            windows.append(WindowHitRate(f"H2H_L{n}", 0, 0, 0, 0, None, None, None))

    l10_vals = values_for(GameWindow(kind="last_n", n=10), None)
    avg = round(sum(l10_vals) / len(l10_vals), 2) if l10_vals else None
    return PropHitRateBundle(historical_avg=avg, windows=windows)


def pick_side_hit_pct(bundle: PropHitRateBundle, window: str, side: Side) -> float | None:
    for w in bundle.windows:
        if w.window != window:
            continue
        return w.over_hit_pct if side == "over" else w.under_hit_pct
    return None
