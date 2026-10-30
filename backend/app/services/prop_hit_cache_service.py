"""Persistent PostgreSQL cache for prop line historical hit rates."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models.sportsbook import PropLineHitCache, PropOffer
from app.analytics.hcs_settings import HCS_VERSION
from app.services.hcs_service import compute_hcs_bundle_for_line, hcs_score_from_cache
from app.services.prop_hit_rates import compute_prop_hit_rates
from app.services.prop_hit_ranking import window_side_stats

_WINDOW_KEYS = (
    ("l5", "L5"),
    ("l10", "L10"),
    ("l20", "L20"),
    ("h2h", "H2H_L5"),
)


def _window_map(hit_rates: dict) -> dict[str, dict]:
    return {w["window"]: w for w in hit_rates.get("windows") or []}


def side_hit_pct(hit_rates: dict | None, window: str, pick_side: str) -> float | None:
    if not hit_rates:
        return None
    w = _window_map(hit_rates).get(window)
    if not w:
        return None
    return w["over_hit_pct"] if pick_side == "over" else w["under_hit_pct"]


def denormalized_hit_columns(hit_rates: dict | None, pick_side: str) -> dict:
    windows = _window_map(hit_rates or {})
    out: dict = {}
    for prefix, label in _WINDOW_KEYS:
        stats = window_side_stats(windows.get(label), pick_side)
        out[f"{prefix}_hit_pct"] = stats["hit_pct"]
        out[f"{prefix}_games"] = stats["games"] or None
        out[f"{prefix}_hits"] = stats["hits"]
        out[f"{prefix}_attempts"] = stats["attempts"]
        out[f"{prefix}_wilson_lb"] = stats["wilson_lb"]
    # legacy l15/l30 pct only
    out["l15_hit_pct"] = side_hit_pct(hit_rates, "L15", pick_side)
    out["l30_hit_pct"] = side_hit_pct(hit_rates, "L30", pick_side)
    return out


def current_data_sync_reference(session: Session) -> str | None:
    from app.models import SyncRun

    ts = session.scalar(
        select(func.max(SyncRun.finished_at)).where(
            SyncRun.kind == "incremental", SyncRun.status.in_(("success", "partial"))
        )
    )
    return ts.isoformat() if ts else None


def _hcs_cache_current(hit_rates: dict | None) -> bool:
    block = (hit_rates or {}).get("hcs_v1")
    return bool(block) and block.get("version") == HCS_VERSION


def get_or_compute_hit_cache(
    session: Session,
    *,
    player_id: int,
    game_id: int,
    opponent_team_id: int | None,
    category_key: str,
    line: float,
    season: int,
    before_start: datetime,
    data_sync_reference: str | None,
    force: bool = False,
) -> tuple[dict, int | None, datetime]:
    """Return (hit_rates_json, cache_id, computed_at)."""
    existing = session.scalar(
        select(PropLineHitCache).where(
            PropLineHitCache.player_id == player_id,
            PropLineHitCache.game_id == game_id,
            PropLineHitCache.category_key == category_key,
            PropLineHitCache.line == line,
        )
    )
    if (
        existing
        and not force
        and existing.data_sync_reference == data_sync_reference
        and existing.hit_rates
        and _hcs_cache_current(existing.hit_rates)
    ):
        return existing.hit_rates, existing.id, existing.computed_at

    bundle = compute_prop_hit_rates(
        session,
        player_id=player_id,
        category_key=category_key,
        line=line,
        opponent_team_id=opponent_team_id,
        season=season,
        before_start=before_start,
    )
    hit_json = bundle.to_json()
    hit_json["hcs_v1"] = compute_hcs_bundle_for_line(
        session,
        player_id=player_id,
        category_key=category_key,
        line=line,
        before_start=before_start,
    )
    now = datetime.now(UTC)
    values = {
        "player_id": player_id,
        "game_id": game_id,
        "opponent_team_id": opponent_team_id,
        "category_key": category_key,
        "line": line,
        "hit_rates": hit_json,
        "historical_avg": bundle.historical_avg,
        "computed_at": now,
        "data_sync_reference": data_sync_reference,
    }
    stmt = insert(PropLineHitCache).values(**values)
    stmt = stmt.on_conflict_do_update(
        constraint="uq_prop_line_hit_cache_key",
        set_={
            "hit_rates": hit_json,
            "historical_avg": bundle.historical_avg,
            "computed_at": now,
            "data_sync_reference": data_sync_reference,
            "opponent_team_id": opponent_team_id,
        },
    ).returning(PropLineHitCache.id)
    cache_id = session.scalar(stmt)
    return hit_json, int(cache_id) if cache_id else None, now


def apply_hit_to_offer_values(
    values: dict,
    *,
    hit_rates: dict | None,
    pick_side: str,
    hit_cache_id: int | None,
    computed_at: datetime | None,
) -> dict:
    values = dict(values)
    values["hit_rates"] = hit_rates
    values["historical_avg"] = (hit_rates or {}).get("historical_avg")
    values["hit_cache_id"] = hit_cache_id
    values["hit_computed_at"] = computed_at
    values.update(denormalized_hit_columns(hit_rates, pick_side))
    values["hcs_score"] = hcs_score_from_cache(hit_rates, pick_side=pick_side, analysis_window="l20")
    return values


def backfill_offer_denormalized_columns(session: Session, *, batch_size: int = 2000) -> int:
    """Populate denormalized hit columns from stored JSON (no recalculation)."""
    updated = 0
    last_id = 0
    while True:
        offers = list(
            session.scalars(
                select(PropOffer)
                .where(
                    PropOffer.id > last_id,
                    PropOffer.match_status == "matched",
                    PropOffer.hit_rates.is_not(None),
                    PropOffer.l10_wilson_lb.is_(None),
                )
                .order_by(PropOffer.id)
                .limit(batch_size)
            )
        )
        if not offers:
            break
        for offer in offers:
            cols = denormalized_hit_columns(offer.hit_rates, offer.pick_side)
            for key, val in cols.items():
                setattr(offer, key, val)
            if offer.hit_rates and not offer.hit_computed_at:
                offer.hit_computed_at = offer.updated_at
            updated += 1
            last_id = offer.id
        session.flush()
    return updated


def cache_stats(session: Session) -> dict:
    total = session.scalar(select(func.count()).select_from(PropLineHitCache)) or 0
    return {"unique_line_caches": int(total)}
