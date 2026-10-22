"""Line analysis for one player: window selection + category values + over/under/push."""

from collections.abc import Sequence
from dataclasses import asdict

from sqlalchemy.orm import Session

from app.analytics.categories import CATEGORIES, StatCategory, get_category, stat_value
from app.analytics.lines import classify, evaluate_line, is_small_sample, summarize
from app.analytics.windows import GameWindow, played_games, select_games
from app.ingestion.providers.base import TRACKED_SEASON_TYPES
from app.models import PlayerGameStat
from app.repositories import games as games_repo
from app.repositories import players as players_repo
from app.schemas.analysis import (
    AnalysisGameOut,
    DistributionOut,
    LineResultOut,
    MatchupComparisonOut,
    StatAnalysisOut,
    StatCategoryOut,
    WindowOut,
)
from app.schemas.common import season_label
from app.services.errors import NotFoundError
from app.services.player_service import game_result
from app.services.serializers import team_out

SEASON_TYPE_SCOPES: dict[str, tuple[int, ...]] = {
    "all": TRACKED_SEASON_TYPES,
    "regular": (2,),
    "postseason": (3, 5),
}


def category_out(category: StatCategory) -> StatCategoryOut:
    return StatCategoryOut(
        key=category.key,
        label=category.label,
        short_label=category.short_label,
        components=list(category.components),
        is_combined=category.is_combined,
    )


def list_categories() -> list[StatCategoryOut]:
    return [category_out(c) for c in CATEGORIES.values()]


def build_analysis(
    *,
    player_id: int,
    logs: Sequence[PlayerGameStat],
    category: StatCategory,
    line: float,
    window: GameWindow,
    opponent=None,
    season_types: Sequence[int] = TRACKED_SEASON_TYPES,
) -> StatAnalysisOut:
    opponent_id = opponent.id if opponent is not None else None
    selected = select_games(logs, window, opponent_id)

    games: list[AnalysisGameOut] = []
    for stat in reversed(selected):  # chronological for charts
        value = stat_value(stat, category)
        if value is None:
            continue
        team_score, opp_score, result = game_result(stat, stat.game)
        games.append(
            AnalysisGameOut(
                game_id=stat.game_id,
                game_date=stat.game_date,
                season=stat.season,
                season_label=season_label(stat.season),
                season_type=stat.season_type,
                opponent=team_out(stat.opponent),
                is_home=stat.is_home,
                result=result,
                team_score=team_score,
                opponent_score=opp_score,
                minutes=stat.minutes,
                value=value,
                outcome=classify(value, line),
                components={c: getattr(stat, c) for c in category.components},
            )
        )

    values = [g.value for g in games]
    line_result = evaluate_line(values, line)
    distribution = summarize(values)
    small = is_small_sample(len(values))
    available = len(
        [g for g in played_games(logs) if opponent_id is None or g.opponent_team_id == opponent_id]
    )

    scope = "vs " + opponent.abbreviation if opponent is not None else "all opponents"
    note = (
        f"Historical results from {len(values)} played game(s) ({scope}). "
        "These are past outcomes, not predicted probabilities. DNPs are excluded."
    )
    if small:
        note += " Small sample: fewer than 5 games."

    return StatAnalysisOut(
        player_id=player_id,
        category=category_out(category),
        window=WindowOut(
            kind=window.kind,
            n=window.n,
            season=window.season,
            start_date=window.start_date,
            end_date=window.end_date,
            opponent_team_id=opponent_id,
            season_types=list(season_types),
        ),
        opponent=team_out(opponent) if opponent is not None else None,
        games=games,
        distribution=DistributionOut(**asdict(distribution)),
        line_result=LineResultOut(
            line=line_result.line,
            total=line_result.total,
            over=line_result.over,
            under=line_result.under,
            push=line_result.push,
            over_pct=line_result.over_pct,
            under_pct=line_result.under_pct,
            push_pct=line_result.push_pct,
            over_pct_excluding_pushes=line_result.over_pct_excluding_pushes,
        ),
        small_sample=small,
        available_games=available,
        note=note,
    )


def _load(session: Session, player_id: int, opponent_team_id: int | None, season_types):
    if players_repo.get_player(session, player_id) is None:
        raise NotFoundError(f"Player {player_id} not found")
    opponent = None
    if opponent_team_id is not None:
        opponent = games_repo.get_team(session, opponent_team_id)
        if opponent is None:
            raise NotFoundError(f"Team {opponent_team_id} not found")
    logs = players_repo.player_game_logs(
        session, player_id, opponent_team_id=opponent_team_id, season_types=season_types
    )
    return logs, opponent


def analyze(
    session: Session,
    *,
    player_id: int,
    category_key: str,
    line: float,
    window: GameWindow,
    opponent_team_id: int | None = None,
    season_scope: str = "all",
) -> StatAnalysisOut:
    category = get_category(category_key)
    season_types = SEASON_TYPE_SCOPES[season_scope]
    logs, opponent = _load(session, player_id, opponent_team_id, season_types)
    return build_analysis(
        player_id=player_id,
        logs=logs,
        category=category,
        line=line,
        window=window,
        opponent=opponent,
        season_types=season_types,
    )


def compare_with_opponent(
    session: Session,
    *,
    player_id: int,
    opponent_team_id: int,
    category_key: str,
    line: float,
    recent_n: int,
    head_to_head_n: int | None,
    season_scope: str = "all",
) -> MatchupComparisonOut:
    category = get_category(category_key)
    season_types = SEASON_TYPE_SCOPES[season_scope]
    logs, _ = _load(session, player_id, None, season_types)
    opponent = games_repo.get_team(session, opponent_team_id)
    if opponent is None:
        raise NotFoundError(f"Team {opponent_team_id} not found")
    recent = build_analysis(
        player_id=player_id,
        logs=logs,
        category=category,
        line=line,
        window=GameWindow(kind="last_n", n=recent_n),
        season_types=season_types,
    )
    h2h_window = GameWindow(kind="last_n", n=head_to_head_n) if head_to_head_n else GameWindow(kind="all")
    head_to_head = build_analysis(
        player_id=player_id,
        logs=logs,
        category=category,
        line=line,
        window=h2h_window,
        opponent=opponent,
        season_types=season_types,
    )
    return MatchupComparisonOut(
        player_id=player_id, opponent=team_out(opponent), recent=recent, head_to_head=head_to_head
    )
