"""Backfill denormalized hit columns and prop_line_hit_cache from existing prop_offers."""

from __future__ import annotations

from sqlalchemy import select

from app.db import session_scope
from app.models.sportsbook import PropLineHitCache, PropOffer
from app.services.prop_hit_cache_service import backfill_offer_denormalized_columns, denormalized_hit_columns


def backfill_cache_rows() -> int:
    created = 0
    with session_scope() as session:
        offers = session.scalars(
            select(PropOffer).where(
                PropOffer.match_status == "matched",
                PropOffer.player_id.is_not(None),
                PropOffer.game_id.is_not(None),
                PropOffer.hit_rates.is_not(None),
            )
        )
        seen: set[tuple] = set()
        for offer in offers:
            key = (offer.player_id, offer.game_id, offer.category_key, offer.line)
            if key in seen:
                continue
            seen.add(key)
            exists = session.scalar(
                select(PropLineHitCache.id).where(
                    PropLineHitCache.player_id == offer.player_id,
                    PropLineHitCache.game_id == offer.game_id,
                    PropLineHitCache.category_key == offer.category_key,
                    PropLineHitCache.line == offer.line,
                )
            )
            if exists:
                continue
            session.add(
                PropLineHitCache(
                    player_id=offer.player_id,
                    game_id=offer.game_id,
                    opponent_team_id=offer.opponent_team_id,
                    category_key=offer.category_key,
                    line=offer.line,
                    hit_rates=offer.hit_rates,
                    historical_avg=offer.historical_avg,
                    computed_at=offer.hit_computed_at or offer.updated_at,
                    data_sync_reference="backfill",
                )
            )
            created += 1
        session.flush()
    return created


def main() -> None:
    with session_scope() as session:
        n = backfill_offer_denormalized_columns(session)
    print(f"Denormalized {n} prop offers")
    c = backfill_cache_rows()
    print(f"Inserted {c} prop_line_hit_cache rows")


if __name__ == "__main__":
    main()
