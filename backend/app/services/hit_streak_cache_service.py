"""PostgreSQL cache for prop hit streak bundles."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.analytics.hit_streaks import HitStreakBundle
from app.models.sportsbook import PropHitStreakCache
from app.services.prop_hit_cache_service import current_data_sync_reference


def cache_key_tuple(
    *,
    player_id: int,
    before_game_id: int,
    category_key: str,
    line: float,
    pick_side: str,
    current_season_only: bool,
) -> tuple:
    return (player_id, before_game_id, category_key, float(line), pick_side, current_season_only)


def load_streak_caches(
    session: Session, keys: list[tuple], *, data_sync_reference: str | None
) -> dict[tuple, HitStreakBundle]:
    if not keys:
        return {}
    player_ids = {k[0] for k in keys}
    game_ids = {k[1] for k in keys}
    rows = session.scalars(
        select(PropHitStreakCache).where(
            PropHitStreakCache.player_id.in_(player_ids),
            PropHitStreakCache.before_game_id.in_(game_ids),
        )
    )
    out: dict[tuple, HitStreakBundle] = {}
    for row in rows:
        key = cache_key_tuple(
            player_id=row.player_id,
            before_game_id=row.before_game_id,
            category_key=row.category_key,
            line=row.line,
            pick_side=row.pick_side,
            current_season_only=row.current_season_only,
        )
        if key not in keys:
            continue
        if row.data_sync_reference != data_sync_reference:
            continue
        out[key] = HitStreakBundle.from_json(row.streak_data)
    return out


def upsert_streak_cache(
    session: Session,
    *,
    player_id: int,
    before_game_id: int,
    category_key: str,
    line: float,
    pick_side: str,
    current_season_only: bool,
    bundle: HitStreakBundle,
    data_sync_reference: str | None,
) -> None:
    now = datetime.now(UTC)
    values = {
        "player_id": player_id,
        "before_game_id": before_game_id,
        "category_key": category_key,
        "line": float(line),
        "pick_side": pick_side,
        "current_season_only": current_season_only,
        "streak_data": bundle.to_json(),
        "computed_at": now,
        "data_sync_reference": data_sync_reference,
    }
    stmt = insert(PropHitStreakCache).values(**values)
    stmt = stmt.on_conflict_do_update(
        constraint="uq_prop_hit_streak_cache_key",
        set_={
            "streak_data": values["streak_data"],
            "computed_at": now,
            "data_sync_reference": data_sync_reference,
        },
    )
    session.execute(stmt)


def get_or_compute_streak_bundle(
    session: Session,
    *,
    player_id: int,
    before_game_id: int,
    category_key: str,
    line: float,
    pick_side: str,
    current_season_only: bool,
    games,
    category,
    memory: dict[tuple, HitStreakBundle],
    persist: bool = True,
) -> HitStreakBundle:
    from app.analytics.hit_streaks import compute_hit_streak

    key = cache_key_tuple(
        player_id=player_id,
        before_game_id=before_game_id,
        category_key=category_key,
        line=line,
        pick_side=pick_side,
        current_season_only=current_season_only,
    )
    if key in memory:
        return memory[key]

    sync_ref = current_data_sync_reference(session)
    existing = session.scalar(
        select(PropHitStreakCache).where(
            PropHitStreakCache.player_id == player_id,
            PropHitStreakCache.before_game_id == before_game_id,
            PropHitStreakCache.category_key == category_key,
            PropHitStreakCache.line == float(line),
            PropHitStreakCache.pick_side == pick_side,
            PropHitStreakCache.current_season_only.is_(current_season_only),
            PropHitStreakCache.data_sync_reference == sync_ref,
        )
    )
    if existing:
        bundle = HitStreakBundle.from_json(existing.streak_data)
        memory[key] = bundle
        return bundle

    bundle = compute_hit_streak(games, category=category, line=line, pick_side=pick_side)
    memory[key] = bundle
    if persist:
        upsert_streak_cache(
            session,
            player_id=player_id,
            before_game_id=before_game_id,
            category_key=category_key,
            line=line,
            pick_side=pick_side,
            current_season_only=current_season_only,
            bundle=bundle,
            data_sync_reference=sync_ref,
        )
    return bundle
