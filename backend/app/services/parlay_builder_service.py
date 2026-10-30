"""Server-side parlay candidate filtering, scoring, and combination search."""

from __future__ import annotations

import itertools
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, desc, nullslast, or_, select
from sqlalchemy.orm import Session, joinedload

from app.analytics.categories import get_category
from app.models import Game, Player
from app.models.sportsbook import PropImportRun, PropOffer
from app.repositories import players as players_repo
from app.analytics.hcs_settings import HCS_VERSION, PCS_VERSION
from app.schemas.hcs import HCSBreakdownOut
from app.schemas.parlay_builder import (
    ParlayCombinationOut,
    ParlayLegOut,
    ParlayLegScoreOut,
    ParlayPCSBreakdownOut,
    ParlaySearchIn,
    ParlaySearchMetaOut,
    ParlaySearchOut,
)
from app.services.analysis_service import category_out
from app.services.hcs_service import breakdown_from_cache
from app.services.parlay_scoring import (
    indicative_parlay_decimal,
    parlay_consistency_score,
    score_leg_from_hcs,
)

SHORTLIST_SIZE = 72
MAX_COMBINATIONS_EVAL = 40_000
PROP_KEY = ("player_id", "game_id", "category_key", "line", "pick_side")


@dataclass
class _ScoredCandidate:
    offer: PropOffer
    player_name: str
    opponent_label: str | None
    breakdown: object
    l5_minutes: float | None
    l20_minutes: float | None


def _latest_import(session: Session) -> PropImportRun | None:
    return session.scalar(select(PropImportRun).order_by(PropImportRun.id.desc()).limit(1))


def _window_cols(window: str):
    mapping = {
        "l5": (PropOffer.l5_games, PropOffer.l5_hit_pct, PropOffer.l5_wilson_lb, PropOffer.l5_hits, PropOffer.l5_attempts),
        "l10": (PropOffer.l10_games, PropOffer.l10_hit_pct, PropOffer.l10_wilson_lb, PropOffer.l10_hits, PropOffer.l10_attempts),
        "l20": (PropOffer.l20_games, PropOffer.l20_hit_pct, PropOffer.l20_wilson_lb, PropOffer.l20_hits, PropOffer.l20_attempts),
        "l30": (PropOffer.l20_games, PropOffer.l30_hit_pct, PropOffer.l20_wilson_lb, None, None),
    }
    return mapping[window]


def _minutes_avgs(session: Session, player_ids: list[int]) -> dict[int, tuple[float | None, float | None]]:
    if not player_ids:
        return {}
    batch = players_repo.last_n_games_for_players(session, player_ids, 20)
    out: dict[int, tuple[float | None, float | None]] = {}
    for pid, rows in batch.items():
        mins = [r.minutes for r in rows if r.minutes is not None]
        l5 = sum(mins[:5]) / len(mins[:5]) if len(mins) >= 5 else (sum(mins) / len(mins) if mins else None)
        l20 = sum(mins) / len(mins) if mins else None
        out[pid] = (l5, l20)
    return out


def _dedupe_offers(offers: list[PropOffer], sportsbook: str | None) -> list[PropOffer]:
    best: dict[tuple, PropOffer] = {}
    for o in offers:
        key = (o.player_id, o.game_id, o.category_key, o.line, o.pick_side)
        if sportsbook and o.sportsbook_label.lower() != sportsbook.lower():
            continue
        prev = best.get(key)
        if prev is None:
            best[key] = o
            continue
        # Prefer sharper odds (higher decimal for the bettor on same side — simplified: max american for under negative logic skip)
        if o.american_odds is not None and (prev.american_odds is None or o.american_odds > prev.american_odds):
            best[key] = o
    return list(best.values())


def _valid_combo(
    combo: tuple[_ScoredCandidate, ...],
    *,
    different_games: bool,
    one_per_player: bool,
    sportsbook: str | None,
) -> bool:
    games: set[int] = set()
    players: set[int] = set()
    books: set[str] = set()
    for c in combo:
        o = c.offer
        if o.player_id is None or o.game_id is None:
            return False
        if one_per_player and o.player_id in players:
            return False
        players.add(o.player_id)
        if different_games and o.game_id in games:
            return False
        games.add(o.game_id)
        books.add(o.sportsbook_label)
        if o.is_alternate_line:
            return False
    if sportsbook and len(books) > 1:
        return False
    return True


def _explain(combo: tuple[_ScoredCandidate, ...], window: str, pcs: float) -> str:
    legs = len(combo)
    hcs_vals = [c.breakdown.hcs for c in combo]
    min_h = min(hcs_vals)
    max_h = max(hcs_vals)
    deep = sum(1 for c in combo if c.breakdown.qualifying_games >= 10)
    w = window.upper()
    parts = [
        f"This {legs}-leg combination has Parlay Consistency Score {pcs:.0f} "
        f"with leg HCS between {min_h:.0f} and {max_h:.0f} (weakest leg {min_h:.0f}).",
    ]
    if deep == legs:
        parts.append(f"Each leg has at least 10 qualifying games in the {w} historical window.")
    elif deep:
        parts.append(f"{deep} of {legs} legs have at least 10 qualifying games in the {w} window.")
    unstable = sum(1 for c in combo if "insufficient_minutes_sample" in c.breakdown.missing_data_flags)
    if unstable == 0:
        parts.append("Recent minutes (L5 vs L20) did not trigger major instability flags.")
    elif unstable:
        parts.append(f"{unstable} leg(s) have limited minutes data; minute modifier used neutral fallbacks.")
    parts.append("These scores rank historical consistency only — not joint win probability.")
    return " ".join(parts)


def _leg_hcs(offer: PropOffer, window: str) -> object | None:
    bd = breakdown_from_cache(offer.hit_rates, pick_side=offer.pick_side, analysis_window=window)
    if bd is None:
        return None
    return score_leg_from_hcs(bd)


def search_parlays(session: Session, params: ParlaySearchIn) -> ParlaySearchOut:
    t0 = time.perf_counter()
    now = datetime.now(UTC)
    end = now + timedelta(days=params.upcoming_days)

    games_col, hit_col, wilson_col, hits_col, attempts_col = _window_cols(params.analysis_window)
    # l30 may not have games column — use l20 games as qualifying sample for l30 window
    if params.analysis_window == "l30":
        games_col = PropOffer.l20_games
        hits_col = None
        attempts_col = None

    clauses = [
        PropOffer.is_active.is_(True),
        PropOffer.match_status == "matched",
        PropOffer.player_id.is_not(None),
        PropOffer.game_id.is_not(None),
        PropOffer.game_start_time.is_not(None),
        PropOffer.game_start_time > now,
        PropOffer.game_start_time <= end,
        PropOffer.is_alternate_line.is_(False),
        games_col.is_not(None),
        games_col >= params.min_games,
        attempts_col.is_not(None) if attempts_col is not None else PropOffer.l10_attempts.is_not(None),
    ]
    if params.pick_side != "both":
        clauses.append(PropOffer.pick_side == params.pick_side)
    if params.category:
        clauses.append(PropOffer.category_key == params.category)
    if params.min_hit_pct is not None:
        clauses.append(hit_col >= params.min_hit_pct)
    if params.sportsbook:
        clauses.append(PropOffer.sportsbook_label.ilike(f"%{params.sportsbook}%"))
    if params.team_id:
        clauses.append(
            or_(
                Game.home_team_id == params.team_id,
                Game.away_team_id == params.team_id,
            )
        )

    stmt = (
        select(PropOffer)
        .join(Game, Game.id == PropOffer.game_id)
        .options(
            joinedload(PropOffer.player),
            joinedload(PropOffer.game).joinedload(Game.home_team),
            joinedload(PropOffer.game).joinedload(Game.away_team),
        )
        .where(and_(*clauses))
        .order_by(nullslast_desc(PropOffer.hcs_score))
        .limit(1200)
    )
    offers = list(session.scalars(stmt).unique())
    offers = _dedupe_offers(offers, params.sportsbook)

    pw = params.analysis_window
    if pw == "l30":
        pw = "l20"

    scored: list[_ScoredCandidate] = []
    for o in offers:
        if o.player_id is None:
            continue
        breakdown = _leg_hcs(o, pw)
        if breakdown is None:
            continue
        p_name = o.player.full_name if o.player else o.player_name_raw or "Player"
        opp = None
        if o.game and o.game.home_team and o.game.away_team:
            is_home = o.player and o.player.current_team_id == o.game.home_team_id
            opp_team = o.game.away_team if is_home else o.game.home_team
            opp = f"{'vs' if is_home else '@'} {opp_team.abbreviation}"
        scored.append(
            _ScoredCandidate(
                offer=o,
                player_name=p_name,
                opponent_label=opp,
                breakdown=breakdown,
                l5_minutes=breakdown.m5_minutes,
                l20_minutes=breakdown.m20_minutes,
            )
        )

    scored.sort(key=lambda c: -c.breakdown.hcs)
    pool = scored[:SHORTLIST_SIZE]

    combos_out: list[ParlayCombinationOut] = []
    evaluated = 0
    ranked: list[tuple[float, float, float, tuple[_ScoredCandidate, ...]]] = []

    for combo in itertools.combinations(pool, params.legs):
        evaluated += 1
        if evaluated > MAX_COMBINATIONS_EVAL:
            break
        if not _valid_combo(
            combo,
            different_games=params.different_games_only,
            one_per_player=params.one_per_player,
            sportsbook=params.sportsbook,
        ):
            continue
        totals = [c.breakdown.hcs for c in combo]
        pcs_bd = parlay_consistency_score(totals)
        consistency = pcs_bd.pcs
        mn = pcs_bd.min_leg
        avg = round(sum(totals) / len(totals), 2)
        ranked.append((consistency, mn, avg, pcs_bd, combo))

    ranked.sort(key=lambda x: (-x[0], -x[1], -x[2]))
    seen_sigs: set[tuple] = set()
    rank = 0
    for consistency, mn, avg, pcs_bd, combo in ranked:
        sig = tuple(sorted((c.offer.player_id, c.offer.category_key, c.offer.line, c.offer.pick_side) for c in combo))
        if sig in seen_sigs:
            continue
        seen_sigs.add(sig)
        rank += 1
        if rank > params.limit:
            break
        books = {c.offer.sportsbook_label for c in combo}
        single_book = books.pop() if len(books) == 1 else None
        odds = [c.offer.american_odds for c in combo if c.offer.american_odds is not None]
        dec = indicative_parlay_decimal(odds) if single_book and len(odds) == len(combo) else None
        payout_note = None
        if dec:
            payout_note = (
                f"Indicative {dec:.2f}x from listed American odds at {single_book}. "
                "Not verified — sportsbooks may reject or reprice parlays, especially same-game."
            )
        same_game = None
        if not params.different_games_only:
            game_ids = {c.offer.game_id for c in combo}
            if len(game_ids) < len(combo):
                same_game = (
                    "Same-game legs included. Joint hit rates and sportsbook parlay acceptance are not verified."
                )

        legs_out = []
        for c in combo:
            o = c.offer
            cat = get_category(o.category_key)
            raw_bd = breakdown_from_cache(o.hit_rates, pick_side=o.pick_side, analysis_window=pw)
            hcs_out = None
            if raw_bd:
                hcs_out = HCSBreakdownOut(**raw_bd.to_dict())
                if isinstance(hcs_out.missing_data_flags, tuple):
                    hcs_out = hcs_out.model_copy(update={"missing_data_flags": list(raw_bd.missing_data_flags)})
            legs_out.append(
                ParlayLegOut(
                    prop_offer_id=o.id,
                    player_id=o.player_id,
                    player_name=c.player_name,
                    game_id=o.game_id,
                    opponent_label=c.opponent_label,
                    category=category_out(cat),
                    line=o.line,
                    pick_side=o.pick_side,
                    american_odds=o.american_odds,
                    sportsbook=o.sportsbook_label,
                    game_start_time=o.game_start_time,
                    l10_hits=o.l10_hits,
                    l10_attempts=o.l10_attempts,
                    l10_hit_pct=o.l10_hit_pct,
                    l20_hits=o.l20_hits,
                    l20_attempts=o.l20_attempts,
                    l20_hit_pct=o.l20_hit_pct,
                    games_in_window=c.breakdown.qualifying_games,
                    score=ParlayLegScoreOut(
                        **{
                            **c.breakdown.to_dict(),
                            "missing_data_flags": list(c.breakdown.missing_data_flags),
                        }
                    ),
                    hcs_breakdown=hcs_out,
                    prop_analyzer_path=f"/prop-finder",
                )
            )

        pcs_out = ParlayPCSBreakdownOut(
            version=pcs_bd.version,
            pcs=pcs_bd.pcs,
            geometric_mean=pcs_bd.geometric_mean,
            min_leg=pcs_bd.min_leg,
            length_factor=pcs_bd.length_factor,
            leg_hcs=list(pcs_bd.leg_hcs),
        )
        combos_out.append(
            ParlayCombinationOut(
                rank=rank,
                parlay_consistency_score=consistency,
                historical_consistency_score=consistency,
                min_leg_score=mn,
                avg_leg_score=avg,
                pcs_breakdown=pcs_out,
                legs=legs_out,
                sportsbook=single_book,
                explanation=_explain(combo, params.analysis_window, consistency),
                indicative_decimal_odds=dec,
                indicative_payout_note=payout_note,
                same_game_warning=same_game,
            )
        )

    last = _latest_import(session)
    stale = None
    if last and last.finished_at:
        age = now - last.finished_at
        if age > timedelta(hours=6):
            stale = f"Sportsbook import last finished {int(age.total_seconds() // 3600)}h ago; lines may be stale."

    ms = (time.perf_counter() - t0) * 1000
    return ParlaySearchOut(
        meta=ParlaySearchMetaOut(
            candidates_considered=len(scored),
            combinations_evaluated=evaluated,
            generation_ms=round(ms, 1),
            last_import_finished_at=last.finished_at if last else None,
            stale_warning=stale,
            hcs_version=HCS_VERSION,
            pcs_version=PCS_VERSION,
        ),
        combinations=combos_out,
    )


def nullslast_desc(col):
    return nullslast(desc(col))
