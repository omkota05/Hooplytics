"""Detailed prop analysis bundle (loaded on demand, not on Prop Finder list)."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app.analytics.categories import get_category, stat_value
from app.analytics.lines import classify
from app.analytics.windows import GameWindow, played_games, select_games
from app.ingestion.providers.base import TRACKED_SEASON_TYPES
from app.models import Game
from app.models.sportsbook import PropOffer as PropOfferModel
from app.repositories import players as players_repo
from app.schemas.prop_analyzer import PropAnalyzerGameRowOut, PropAnalyzerOut
from app.services.analysis_service import compare_with_opponent
from app.services.errors import NotFoundError
from app.services.opportunity_service import build_opportunity
from app.services.hit_streaks_service import streak_for_offer
from app.services.prop_finder_service import get_prop_detail
from app.services.serializers import team_out


def _prop_game_log(
    session: Session,
    *,
    player_id: int,
    category_key: str,
    line: float,
    pick_side: str,
    before_start,
    opponent_team_id: int | None,
    limit: int = 100,
) -> list[PropAnalyzerGameRowOut]:
    category = get_category(category_key)
    logs = players_repo.player_game_logs(session, player_id)
    games = [g for g in played_games(logs) if g.season_type in TRACKED_SEASON_TYPES]
    if before_start is not None:
        games = [g for g in games if g.game.start_time and g.game.start_time < before_start]
    windowed = select_games(games, GameWindow(kind="last_n", n=limit), opponent_team_id)

    rows: list[PropAnalyzerGameRowOut] = []
    for g in windowed:
        prop_value = stat_value(g, category)
        outcome = None
        if prop_value is not None:
            outcome = classify(prop_value, line)
        rows.append(
            PropAnalyzerGameRowOut(
                game_id=g.game_id,
                game_date=g.game_date,
                opponent=team_out(g.opponent),
                is_home=g.is_home,
                minutes=g.minutes,
                pts=g.pts,
                reb=g.reb,
                ast=g.ast,
                fga=g.fga,
                fg3a=g.fg3a,
                prop_value=prop_value,
                outcome=outcome,
            )
        )
    return rows


def get_prop_analyzer(session: Session, prop_id: int) -> PropAnalyzerOut:
    offer = session.scalar(
        select(PropOfferModel)
        .options(
            joinedload(PropOfferModel.player),
            joinedload(PropOfferModel.game).joinedload(Game.home_team),
            joinedload(PropOfferModel.game).joinedload(Game.away_team),
        )
        .where(PropOfferModel.id == prop_id)
    )
    if offer is None or not offer.is_active:
        raise NotFoundError(f"Prop offer {prop_id} not found")

    prop = get_prop_detail(session, prop_id)
    game = offer.game
    opportunity = None
    matchup = None
    game_log: list[PropAnalyzerGameRowOut] = []

    if offer.player_id and offer.match_status == "matched":
        before = game.start_time if game else None
        season = game.season if game else None
        opportunity = build_opportunity(
            session,
            offer.player_id,
            before_start=before,
            season=season,
        )
        if offer.opponent_team_id:
            matchup = compare_with_opponent(
                session,
                player_id=offer.player_id,
                opponent_team_id=offer.opponent_team_id,
                category_key=offer.category_key,
                line=offer.line,
                recent_n=10,
                head_to_head_n=5,
            )
        game_log = _prop_game_log(
            session,
            player_id=offer.player_id,
            category_key=offer.category_key,
            line=offer.line,
            pick_side=offer.pick_side,
            before_start=before,
            opponent_team_id=None,
        )

    hit_streak = None
    if offer.player_id and offer.match_status == "matched":
        hit_streak = streak_for_offer(session, offer, current_season_only=False)

    return PropAnalyzerOut(
        prop=prop,
        opportunity=opportunity,
        matchup=matchup,
        game_log=game_log,
        hit_streak=hit_streak,
    )
