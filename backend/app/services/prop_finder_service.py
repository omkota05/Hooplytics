"""Query sportsbook prop offers for the Prop Finder UI (cached hit rates, SQL pagination)."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import asc, desc, func, nullslast, or_, select
from sqlalchemy.orm import Session, joinedload

from app.analytics.categories import get_category
from app.models import Game, Player
from app.models.sportsbook import PropImportRun, PropOffer as PropOfferModel
from app.schemas.hcs import HCSBreakdownOut
from app.schemas.prop_finder import PropFinderDetailOut, PropFinderListOut, PropFinderRowOut, PropHitWindowOut
from app.services.analysis_service import category_out
from app.services.errors import NotFoundError
from app.services.hcs_service import breakdown_from_cache
from app.services.prop_hit_cache_service import cache_stats, denormalized_hit_columns
from app.services.prop_hit_ranking import (
    effective_min_games,
    games_column_for_sort,
    hit_pct_column_for_sort,
    sort_column,
    window_side_stats,
)
from app.services.prop_refresh_worker import refresh_state

_SAMPLE_PREFIXES = ("l5", "l10", "l20", "h2h")
RANKED_RESULTS_CAP = 100
DEFAULT_PAGE_SIZE = 10


def _latest_import(session: Session) -> PropImportRun | None:
    return session.scalar(select(PropImportRun).order_by(PropImportRun.id.desc()).limit(1))


def _now_utc() -> datetime:
    return datetime.now(UTC)


def _eligible_prop_clauses(now: datetime):
    """Upcoming, primary-line matched offers suitable for Prop Finder browsing."""
    return [
        PropOfferModel.is_active.is_(True),
        PropOfferModel.match_status == "matched",
        PropOfferModel.is_alternate_line.is_(False),
        PropOfferModel.player_id.is_not(None),
        PropOfferModel.game_id.is_not(None),
        Game.status.in_(("scheduled", "in_progress")),
        Game.start_time > now,
        or_(
            PropOfferModel.american_odds.is_(None),
            func.abs(PropOfferModel.american_odds) <= 10_000,
        ),
    ]


def _count_eligible(session: Session, now: datetime, extra_clauses: list) -> int:
    stmt = (
        select(func.count())
        .select_from(PropOfferModel)
        .join(Game, Game.id == PropOfferModel.game_id)
        .where(*_eligible_prop_clauses(now), *extra_clauses)
    )
    return int(session.scalar(stmt) or 0)


def import_status(session: Session, *, configured: bool) -> dict:
    last = _latest_import(session)
    last_success = session.scalar(
        select(PropImportRun)
        .where(PropImportRun.status == "success")
        .order_by(PropImportRun.id.desc())
        .limit(1)
    )
    now = _now_utc()
    active = session.scalar(
        select(func.count()).select_from(PropOfferModel).where(PropOfferModel.is_active.is_(True))
    )
    matched = session.scalar(
        select(func.count())
        .select_from(PropOfferModel)
        .where(PropOfferModel.is_active.is_(True), PropOfferModel.match_status == "matched")
    )
    eligible = _count_eligible(session, now, [])
    last_hit = session.scalar(
        select(func.max(PropOfferModel.hit_computed_at)).where(
            PropOfferModel.is_active.is_(True),
            PropOfferModel.match_status == "matched",
        )
    )
    worker = refresh_state()
    details = last.details if last else None
    timing = (details or {}).get("timing_ms") if details else None
    return {
        "configured": configured,
        "last_run_status": last.status if last else None,
        "last_run_finished_at": last_success.finished_at if last_success else None,
        "last_run_error": worker.last_error or (last.error if last and last.status == "failed" else None),
        "offers_active": int(active or 0),
        "offers_matched": int(matched or 0),
        "offers_eligible_upcoming": eligible,
        "last_import_details": details,
        "refresh_in_progress": worker.in_progress,
        "refresh_started_at": worker.started_at,
        "unique_line_caches": cache_stats(session)["unique_line_caches"],
        "last_hit_computed_at": last_hit,
        "refresh_progress": worker.progress,
        "diagnostics": {
            "offers_active_matched_primary": session.scalar(
                select(func.count()).select_from(PropOfferModel).where(
                    PropOfferModel.is_active.is_(True),
                    PropOfferModel.match_status == "matched",
                    PropOfferModel.is_alternate_line.is_(False),
                )
            )
            or 0,
            "offers_eligible_upcoming": eligible,
            "last_import_duration_ms": timing.get("total") if timing else None,
            "last_hit_reused_offer": (details or {}).get("hit_stats_reused_offer"),
            "last_hit_computed": (details or {}).get("hit_stats_computed"),
        },
    }


def _field(offer: PropOfferModel, cols: dict, name: str):
    val = getattr(offer, name, None)
    return val if val is not None else cols.get(name)


def _row_from_offer(offer: PropOfferModel, player: Player | None, game: Game | None) -> PropFinderRowOut:
    category = get_category(offer.category_key)
    cols = denormalized_hit_columns(offer.hit_rates, offer.pick_side)
    l5 = _field(offer, cols, "l5_hit_pct")
    l10 = _field(offer, cols, "l10_hit_pct")
    l20 = _field(offer, cols, "l20_hit_pct")
    h2h = _field(offer, cols, "h2h_hit_pct")
    sample_kwargs = {}
    for prefix in _SAMPLE_PREFIXES:
        sample_kwargs[f"{prefix}_hits"] = _field(offer, cols, f"{prefix}_hits")
        sample_kwargs[f"{prefix}_attempts"] = _field(offer, cols, f"{prefix}_attempts")
        sample_kwargs[f"{prefix}_games"] = _field(offer, cols, f"{prefix}_games")

    matchup = None
    opp_abbr = None
    if game and game.home_team and game.away_team:
        matchup = f"{game.away_team.abbreviation} @ {game.home_team.abbreviation}"
        if offer.opponent_team_id:
            opp = game.away_team if offer.opponent_team_id == game.away_team_id else game.home_team
            opp_abbr = opp.abbreviation

    return PropFinderRowOut(
        id=offer.id,
        source_kind=offer.source_kind,
        player_id=offer.player_id,
        player_name=player.full_name if player else offer.player_name_raw,
        game_id=offer.game_id,
        matchup_label=matchup or offer.event_name,
        opponent_abbreviation=opp_abbr,
        opponent_team_id=offer.opponent_team_id,
        sportsbook=offer.sportsbook_label,
        category=category_out(category),
        line=offer.line,
        pick_side=offer.pick_side,
        american_odds=offer.american_odds,
        l5_hit_pct=l5,
        l10_hit_pct=l10,
        l20_hit_pct=l20,
        h2h_hit_pct=h2h,
        **sample_kwargs,
        historical_avg=offer.historical_avg,
        game_start_time=offer.game_start_time,
        deep_link_published=offer.deep_link_published,
        is_alternate_line=offer.is_alternate_line,
        match_status=offer.match_status,
        line_modified_at=offer.line_modified_at,
        updated_at=offer.updated_at,
        hit_computed_at=offer.hit_computed_at,
        hcs_score=offer.hcs_score,
    )


def _base_filters(
    *,
    sportsbook: str | None,
    game_id: int | None,
    player_id: int | None,
    team_id: int | None,
    category: str | None,
    pick_side: str | None,
    game_date: str | None,
    min_hit_pct: float | None,
    min_games: int,
    sort: str,
):
    clauses = [
        PropOfferModel.is_active.is_(True),
        PropOfferModel.match_status == "matched",
        PropOfferModel.is_alternate_line.is_(False),
    ]
    if sportsbook:
        clauses.append(PropOfferModel.sportsbook_label.ilike(f"%{sportsbook}%"))
    if game_id:
        clauses.append(PropOfferModel.game_id == game_id)
    if player_id:
        clauses.append(PropOfferModel.player_id == player_id)
    if category:
        clauses.append(PropOfferModel.category_key == category)
    if pick_side:
        clauses.append(PropOfferModel.pick_side == pick_side)
    if game_date:
        clauses.append(PropOfferModel.game_date == game_date)
    hit_col = hit_pct_column_for_sort(sort)
    if min_hit_pct is not None and hit_col is not None:
        clauses.append(hit_col >= min_hit_pct)
    required = effective_min_games(min_games, sort)
    games_col = games_column_for_sort(sort)
    if required is not None and games_col is not None and required > 0:
        clauses.append(games_col >= required)
    return clauses, team_id


def _order_by(sort: str):
    if sort == "time":
        return asc(PropOfferModel.game_start_time).nulls_last()
    return nullslast(desc(sort_column(sort)))


def list_props(
    session: Session,
    *,
    sportsbook: str | None = None,
    game_id: int | None = None,
    player_id: int | None = None,
    team_id: int | None = None,
    category: str | None = None,
    pick_side: str | None = None,
    game_date: str | None = None,
    min_hit_pct: float | None = None,
    min_games: int = 10,
    min_sample: int | None = None,
    sort: str = "hcs",
    limit: int = DEFAULT_PAGE_SIZE,
    offset: int = 0,
    ranked_cap: int = RANKED_RESULTS_CAP,
) -> PropFinderListOut:
    if min_sample is not None and min_sample > 0:
        min_games = max(min_games, min_sample)
    limit = min(max(1, limit), DEFAULT_PAGE_SIZE)
    ranked_cap = min(max(1, ranked_cap), RANKED_RESULTS_CAP)
    now = _now_utc()
    clauses, team_filter = _base_filters(
        sportsbook=sportsbook,
        game_id=game_id,
        player_id=player_id,
        team_id=team_id,
        category=category,
        pick_side=pick_side,
        game_date=game_date,
        min_hit_pct=min_hit_pct,
        min_games=min_games,
        sort=sort,
    )
    eligible = _eligible_prop_clauses(now)
    clauses.extend(eligible)

    count_stmt = select(func.count()).select_from(PropOfferModel).join(
        Game, Game.id == PropOfferModel.game_id
    ).where(*clauses)
    if team_filter:
        count_stmt = count_stmt.where(
            (Game.home_team_id == team_filter) | (Game.away_team_id == team_filter)
        )

    total_available = session.scalar(count_stmt) or 0
    ranked_total = min(int(total_available), ranked_cap)

    if offset >= ranked_total:
        offers = []
    else:
        id_stmt = (
            select(PropOfferModel.id)
            .join(Game, Game.id == PropOfferModel.game_id)
            .where(*clauses)
        )
        if team_filter:
            id_stmt = id_stmt.where(
                (Game.home_team_id == team_filter) | (Game.away_team_id == team_filter)
            )
        ranked_ids = list(
            session.scalars(id_stmt.order_by(_order_by(sort)).limit(ranked_cap))
        )
        ranked_ids = ranked_ids[offset : offset + limit]
        if not ranked_ids:
            offers = []
        else:
            stmt = (
                select(PropOfferModel)
                .options(
                    joinedload(PropOfferModel.player),
                    joinedload(PropOfferModel.game).joinedload(Game.home_team),
                    joinedload(PropOfferModel.game).joinedload(Game.away_team),
                )
                .where(PropOfferModel.id.in_(ranked_ids))
            )
            offers = list(session.scalars(stmt).unique())
            order_map = {pid: i for i, pid in enumerate(ranked_ids)}
            offers.sort(key=lambda o: order_map.get(o.id, 999))
    rows = [_row_from_offer(o, o.player, o.game) for o in offers]

    last = _latest_import(session)
    last_success = session.scalar(
        select(PropImportRun)
        .where(PropImportRun.status == "success")
        .order_by(PropImportRun.id.desc())
        .limit(1)
    )
    worker = refresh_state()
    last_hit = session.scalar(
        select(func.max(PropOfferModel.hit_computed_at)).where(
            PropOfferModel.is_active.is_(True),
            PropOfferModel.match_status == "matched",
        )
    )
    stale_note = ""
    if worker.in_progress:
        stale_note = " Odds refresh in progress — showing cached lines until import finishes."
    return PropFinderListOut(
        rows=rows,
        total=ranked_total,
        total_available=int(total_available),
        limit=limit,
        offset=offset,
        last_import_finished_at=last_success.finished_at if last_success else None,
        last_hit_computed_at=last_hit,
        refresh_in_progress=worker.in_progress,
        disclaimer=(
            "Historical hit rates count past game results against this sportsbook line. "
            "They are not predictions of the upcoming game."
            + stale_note
        ),
    )


def get_prop_detail(session: Session, prop_id: int) -> PropFinderDetailOut:
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
    base = _row_from_offer(offer, offer.player, offer.game)

    hit = offer.hit_rates or {}
    hit_windows = []
    for w in hit.get("windows") or []:
        side = window_side_stats(w, offer.pick_side)
        hit_windows.append(
            PropHitWindowOut(
                window=w["window"],
                games=int(w.get("games") or 0),
                over_hits=int(w.get("over_hits") or 0),
                under_hits=int(w.get("under_hits") or 0),
                over_hit_pct=w.get("over_hit_pct"),
                under_hit_pct=w.get("under_hit_pct"),
                pushes=int(w.get("pushes") or 0),
                side_hits=side["hits"],
                side_attempts=side["attempts"],
            )
        )

    href = None
    if offer.player_id and offer.game_id:
        href = f"/players/{offer.player_id}?stat={offer.category_key}&opponent={offer.opponent_team_id}&game={offer.game_id}&line={offer.line}"

    hcs_bd = breakdown_from_cache(offer.hit_rates, pick_side=offer.pick_side, analysis_window="l20")
    hcs_out = HCSBreakdownOut(**hcs_bd.to_dict()) if hcs_bd else None
    if hcs_out and isinstance(hcs_out.missing_data_flags, tuple):
        hcs_out = hcs_out.model_copy(
            update={"missing_data_flags": list(hcs_out.missing_data_flags)}
        )

    return PropFinderDetailOut(
        **base.model_dump(),
        hit_windows=hit_windows,
        player_analysis_href=href,
        hcs_breakdown=hcs_out,
    )
