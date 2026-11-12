"""Hit Streaks listing for PrizePicks NBA props."""

from __future__ import annotations

import time
from datetime import UTC, datetime

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, joinedload

from app.analytics.categories import CATEGORIES, get_category
from app.analytics.windows import played_games, select_games, GameWindow
from app.ingestion.providers.base import TRACKED_SEASON_TYPES
from app.models import Game, Player, PlayerGameStat
from app.models.sportsbook import PropOffer as PropOfferModel, SportsbookSource
from app.repositories import players as players_repo
from app.schemas.hit_streaks import HitStreakGameOut, HitStreakListOut, HitStreakRowOut, HitStreakSummaryOut
from app.services.analysis_service import category_out
from app.services.hit_streak_cache_service import get_or_compute_streak_bundle
from app.services.prop_finder_service import _eligible_prop_clauses, _now_utc

RANKED_RESULTS_CAP = 100
DEFAULT_PAGE_SIZE = 100
VALID_SORTS = ("streak", "hcs", "clearance", "l10_hit_pct")


def prizepicks_filter(session: Session):
    source_ids = list(
        session.scalars(
            select(SportsbookSource.id).where(func.lower(SportsbookSource.name).like("%prizepicks%"))
        )
    )
    if source_ids:
        return or_(
            PropOfferModel.sportsbook_source_id.in_(source_ids),
            PropOfferModel.sportsbook_label.ilike("%PrizePicks%"),
        )
    return PropOfferModel.sportsbook_label.ilike("%PrizePicks%")


def _streak_label(streak: int, at_least: bool) -> str:
    if streak <= 0:
        return "0"
    return f"{streak}+" if at_least else str(streak)


def _bundle_to_summary(bundle) -> HitStreakSummaryOut:
    recent = [
        HitStreakGameOut(
            game_id=r.game_id,
            game_date=r.game_date,
            opponent_abbreviation=r.opponent_abbreviation,
            stat_value=r.stat_value,
            outcome=r.outcome,
            bet_result=r.bet_result,
        )
        for r in bundle.recent_results
    ]
    return HitStreakSummaryOut(
        current_streak=bundle.current_streak,
        streak_at_least=bundle.streak_at_least,
        streak_label=_streak_label(bundle.current_streak, bundle.streak_at_least),
        avg_clearance_margin=bundle.avg_clearance_margin,
        games_evaluated=bundle.games_evaluated,
        last_completed_game_date=bundle.last_completed_game_date,
        recent_results=recent,
        l5_record=bundle.l5_record,
        l10_record=bundle.l10_record,
        l20_record=bundle.l20_record,
        l5_hit_pct=bundle.l5_hit_pct,
        l10_hit_pct=bundle.l10_hit_pct,
        l20_hit_pct=bundle.l20_hit_pct,
        push_count_in_streak_window=bundle.push_count_in_streak_window,
        missing_data_flags=list(bundle.missing_data_flags),
    )


def _batch_game_logs(session: Session, player_ids: set[int]) -> dict[int, list]:
    if not player_ids:
        return {}
    stmt = (
        select(PlayerGameStat)
        .options(joinedload(PlayerGameStat.game), joinedload(PlayerGameStat.opponent))
        .where(PlayerGameStat.player_id.in_(player_ids))
        .order_by(PlayerGameStat.player_id, PlayerGameStat.game_date.desc())
    )
    out: dict[int, list] = {}
    for row in session.scalars(stmt).unique():
        out.setdefault(row.player_id, []).append(row)
    return out


def _games_before_tipoff(
    logs: list,
    *,
    before_start: datetime | None,
    season: int | None,
    current_season_only: bool,
) -> list:
    games = played_games(logs)
    games = [g for g in games if g.season_type in TRACKED_SEASON_TYPES]
    if before_start is not None:
        games = [g for g in games if g.game and g.game.start_time and g.game.start_time < before_start]
    if current_season_only and season is not None:
        games = [g for g in games if g.season == season]
    return select_games(games, GameWindow(kind="all"))


def _sort_key(row: HitStreakRowOut, sort: str):
    s = row.streak
    if sort == "hcs":
        return (row.hcs_score if row.hcs_score is not None else -1, s.current_streak)
    if sort == "clearance":
        return (s.avg_clearance_margin if s.avg_clearance_margin is not None else -1, s.current_streak)
    if sort == "l10_hit_pct":
        return (s.l10_hit_pct if s.l10_hit_pct is not None else -1, s.current_streak)
    return (s.current_streak, s.avg_clearance_margin if s.avg_clearance_margin is not None else -1)


def list_hit_streaks(
    session: Session,
    *,
    category: str | None = None,
    pick_side: str | None = None,
    game_date: str | None = None,
    min_streak: int = 1,
    current_season_only: bool = False,
    sort: str = "streak",
    limit: int = DEFAULT_PAGE_SIZE,
    offset: int = 0,
) -> HitStreakListOut:
    t0 = time.perf_counter()
    if sort not in VALID_SORTS:
        sort = "streak"
    limit = min(max(1, limit), DEFAULT_PAGE_SIZE)
    now = _now_utc()

    clauses = [
        PropOfferModel.is_active.is_(True),
        PropOfferModel.match_status == "matched",
        PropOfferModel.is_alternate_line.is_(False),
        PropOfferModel.player_id.is_not(None),
        PropOfferModel.game_id.is_not(None),
        prizepicks_filter(session),
    ]
    if category and category in CATEGORIES:
        clauses.append(PropOfferModel.category_key == category)
    if pick_side in ("over", "under"):
        clauses.append(PropOfferModel.pick_side == pick_side)
    if game_date:
        clauses.append(PropOfferModel.game_date == game_date)

    clauses.extend(_eligible_prop_clauses(now))

    stmt = (
        select(PropOfferModel)
        .join(Game, Game.id == PropOfferModel.game_id)
        .options(
            joinedload(PropOfferModel.player).joinedload(Player.current_team),
            joinedload(PropOfferModel.game).joinedload(Game.home_team),
            joinedload(PropOfferModel.game).joinedload(Game.away_team),
        )
        .where(*clauses)
    )
    offers = list(session.scalars(stmt).unique())
    total_eligible = len(offers)

    player_ids = {o.player_id for o in offers if o.player_id}
    logs_by_player = _batch_game_logs(session, player_ids)
    memory: dict = {}

    built: list[HitStreakRowOut] = []
    seen_keys: set[tuple] = set()

    for offer in offers:
        if not offer.player_id or not offer.game_id:
            continue
        dedupe = (
            offer.player_id,
            offer.game_id,
            offer.category_key,
            float(offer.line),
            offer.pick_side,
        )
        if dedupe in seen_keys:
            continue
        seen_keys.add(dedupe)

        game = offer.game
        before = game.start_time if game else offer.game_start_time
        season = game.season if game else None
        logs = logs_by_player.get(offer.player_id, [])
        games = _games_before_tipoff(
            logs,
            before_start=before,
            season=season,
            current_season_only=current_season_only,
        )
        category_obj = get_category(offer.category_key)
        bundle = get_or_compute_streak_bundle(
            session,
            player_id=offer.player_id,
            before_game_id=offer.game_id,
            category_key=offer.category_key,
            line=offer.line,
            pick_side=offer.pick_side,
            current_season_only=current_season_only,
            games=games,
            category=category_obj,
            memory=memory,
        )
        summary = _bundle_to_summary(bundle)
        if summary.current_streak < min_streak:
            continue

        matchup = None
        opp_abbr = None
        if game and game.home_team and game.away_team:
            matchup = f"{game.away_team.abbreviation} @ {game.home_team.abbreviation}"
            if offer.opponent_team_id:
                opp = game.away_team if offer.opponent_team_id == game.away_team_id else game.home_team
                opp_abbr = opp.abbreviation

        team_abbr = None
        if offer.player and offer.player.current_team:
            team_abbr = offer.player.current_team.abbreviation

        built.append(
            HitStreakRowOut(
                offer_id=offer.id,
                player_id=offer.player_id,
                player_name=offer.player.full_name if offer.player else (offer.player_name_raw or "Unknown"),
                team_abbreviation=team_abbr,
                game_id=offer.game_id,
                matchup_label=matchup or offer.event_name,
                opponent_abbreviation=opp_abbr,
                opponent_team_id=offer.opponent_team_id,
                game_start_time=offer.game_start_time,
                game_date=offer.game_date,
                category=category_out(category_obj),
                line=offer.line,
                pick_side=offer.pick_side,
                sportsbook=offer.sportsbook_label,
                hcs_score=offer.hcs_score,
                streak=summary,
            )
        )

    reverse = True
    built.sort(key=lambda r: _sort_key(r, sort), reverse=reverse)
    total_available = len(built)
    ranked_total = min(total_available, RANKED_RESULTS_CAP)
    page = built[offset : offset + limit]
    elapsed = round((time.perf_counter() - t0) * 1000, 1)

    session.commit()

    return HitStreakListOut(
        rows=page,
        total=ranked_total,
        total_available=total_available,
        total_eligible_offers=total_eligible,
        limit=limit,
        offset=offset,
        current_season_only=current_season_only,
        sort=sort,
        timing_ms=elapsed,
        disclaimer=(
            "Consecutive hit counts are historical observations over completed appearances before this "
            "PrizePicks line — not predictions. DNPs and incomplete box scores are excluded from the streak."
        ),
    )


def streak_for_offer(
    session: Session,
    offer: PropOfferModel,
    *,
    current_season_only: bool = False,
) -> HitStreakSummaryOut | None:
    if not offer.player_id or not offer.game_id:
        return None
    game = offer.game
    before = game.start_time if game else offer.game_start_time
    season = game.season if game else None
    logs = players_repo.player_game_logs(session, offer.player_id)
    games = _games_before_tipoff(
        logs,
        before_start=before,
        season=season,
        current_season_only=current_season_only,
    )
    category_obj = get_category(offer.category_key)
    bundle = get_or_compute_streak_bundle(
        session,
        player_id=offer.player_id,
        before_game_id=offer.game_id,
        category_key=offer.category_key,
        line=offer.line,
        pick_side=offer.pick_side,
        current_season_only=current_season_only,
        games=games,
        category=category_obj,
        memory={},
    )
    return _bundle_to_summary(bundle)
