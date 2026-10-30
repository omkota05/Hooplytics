"""Backfill HCS into prop_line_hit_cache JSON and prop_offers.hcs_score."""

from __future__ import annotations

import argparse

from sqlalchemy import select

from app.analytics.hcs_settings import HCS_VERSION
from app.db import session_scope
from app.models import Game
from app.models.sportsbook import PropLineHitCache, PropOffer
from app.services.hcs_service import compute_hcs_bundle_for_line, hcs_score_from_cache
from app.services.prop_hit_cache_service import apply_hit_to_offer_values, current_data_sync_reference


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=0, help="Max cache rows (0 = all missing hcs_v1)")
    args = parser.parse_args()

    updated_caches = 0
    updated_offers = 0
    with session_scope() as session:
        sync_ref = current_data_sync_reference(session)
        q = select(PropLineHitCache).order_by(PropLineHitCache.id)
        rows = list(session.scalars(q))
        for row in rows:
            block = (row.hit_rates or {}).get("hcs_v1")
            if block and block.get("version") == HCS_VERSION:
                continue
            if args.limit and updated_caches >= args.limit:
                break
            game = session.get(Game, row.game_id)
            if game is None:
                continue
            bundle = compute_hcs_bundle_for_line(
                session,
                player_id=row.player_id,
                category_key=row.category_key,
                line=row.line,
                before_start=game.start_time,
            )
            hit_rates = dict(row.hit_rates or {})
            hit_rates["hcs_v1"] = bundle
            row.hit_rates = hit_rates
            row.data_sync_reference = sync_ref
            updated_caches += 1
        session.flush()

        offers = list(
            session.scalars(
                select(PropOffer).where(
                    PropOffer.match_status == "matched",
                    PropOffer.hit_rates.is_not(None),
                    PropOffer.hcs_score.is_(None),
                )
            )
        )
        for offer in offers:
            cols = apply_hit_to_offer_values(
                {},
                hit_rates=offer.hit_rates,
                pick_side=offer.pick_side,
                hit_cache_id=offer.hit_cache_id,
                computed_at=offer.hit_computed_at,
            )
            offer.hcs_score = cols.get("hcs_score")
            if offer.hit_rates and not offer.hit_rates.get("hcs_v1"):
                # offer JSON stale — skip recompute here (run cache pass first)
                offer.hcs_score = hcs_score_from_cache(offer.hit_rates, pick_side=offer.pick_side)
            updated_offers += 1

    print(f"Updated {updated_caches} line caches, {updated_offers} offer hcs_score columns")


if __name__ == "__main__":
    main()
