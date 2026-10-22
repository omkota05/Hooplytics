"""Historical trend explorer: hit rates at a user-chosen line across players in
upcoming games. Purely descriptive; no projections."""

from dataclasses import asdict
from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from app.analytics.categories import get_category, stat_value
from app.analytics.lines import evaluate_line, summarize
from app.repositories import games as games_repo
from app.repositories import players as players_repo
from app.schemas.analysis import DistributionOut, LineResultOut
from app.schemas.explorer import TrendExplorerOut, TrendRowOut
from app.services.analysis_service import category_out
from app.services.serializers import player_summary, team_out


def trends(
    session: Session,
    *,
    category_key: str,
    line: float,
    last_n: int,
    min_games: int,
    days: int,
    sort: str,
    limit: int,
) -> TrendExplorerOut:
    category = get_category(category_key)
    now = datetime.now(UTC)
    upcoming = games_repo.upcoming_games(session, now=now, until=now + timedelta(days=days))

    next_game_by_team = {}
    for g in upcoming:
        next_game_by_team.setdefault(g.home_team_id, (g, g.away_team))
        next_game_by_team.setdefault(g.away_team_id, (g, g.home_team))

    players = players_repo.active_players_on_teams(session, list(next_game_by_team))
    logs = players_repo.last_n_games_for_players(session, [p.id for p in players], last_n)

    rows: list[TrendRowOut] = []
    for player in players:
        values = [v for s in logs.get(player.id, []) if (v := stat_value(s, category)) is not None]
        if len(values) < min_games:
            continue
        game, opponent = next_game_by_team[player.current_team_id]
        lr = evaluate_line(values, line)
        rows.append(
            TrendRowOut(
                player=player_summary(player),
                opponent=team_out(opponent),
                game_id=game.id,
                game_start=game.start_time,
                distribution=DistributionOut(**asdict(summarize(values))),
                line_result=LineResultOut(
                    line=lr.line,
                    total=lr.total,
                    over=lr.over,
                    under=lr.under,
                    push=lr.push,
                    over_pct=lr.over_pct,
                    under_pct=lr.under_pct,
                    push_pct=lr.push_pct,
                    over_pct_excluding_pushes=lr.over_pct_excluding_pushes,
                ),
                recent_values=list(reversed(values)),
            )
        )

    sort_keys = {
        "over_pct": lambda r: (r.line_result.over_pct or 0, r.distribution.mean or 0),
        "under_pct": lambda r: (r.line_result.under_pct or 0, -(r.distribution.mean or 0)),
        "mean": lambda r: r.distribution.mean or 0,
        "consistency": lambda r: -(r.distribution.std_dev or 1e9),
    }
    rows.sort(key=sort_keys.get(sort, sort_keys["over_pct"]), reverse=True)

    return TrendExplorerOut(
        category=category_out(category),
        line=line,
        last_n=last_n,
        min_games=min_games,
        scope=f"Players on teams with games in the next {days} day(s)",
        rows=rows[:limit],
        note=(
            "Descriptive history only: each row shows how often the player's last "
            f"{last_n} played games finished over/under {line}. Not a prediction."
        ),
    )
