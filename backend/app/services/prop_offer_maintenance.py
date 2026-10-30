"""Prop offer housekeeping: stale game deactivation and duplicate consolidation."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import text
from sqlalchemy.orm import Session


def deactivate_past_game_offers(session: Session, *, now: datetime | None = None) -> int:
    """Mark active offers inactive when their game has started or finished."""
    ts = now or datetime.now(UTC)
    result = session.execute(
        text(
            """
            UPDATE prop_offers o
            SET is_active = false
            FROM games g
            WHERE o.game_id = g.id
              AND o.is_active = true
              AND (
                g.status IN ('final', 'postponed', 'canceled', 'suspended')
                OR g.start_time <= :now
                OR (o.game_start_time IS NOT NULL AND o.game_start_time <= :now)
              )
            """
        ),
        {"now": ts},
    )
    return int(result.rowcount or 0)


def consolidate_duplicate_offers(session: Session) -> int:
    """Keep one active row per (player, game, category, line, side, sportsbook); deactivate extras."""
    result = session.execute(
        text(
            """
            WITH ranked AS (
                SELECT id,
                       ROW_NUMBER() OVER (
                           PARTITION BY player_id, game_id, category_key, line, pick_side, sportsbook_label
                           ORDER BY updated_at DESC NULLS LAST, id DESC
                       ) AS rn
                FROM prop_offers
                WHERE is_active = true
                  AND match_status = 'matched'
                  AND is_alternate_line = false
                  AND player_id IS NOT NULL
                  AND game_id IS NOT NULL
            )
            UPDATE prop_offers
            SET is_active = false
            WHERE id IN (SELECT id FROM ranked WHERE rn > 1)
            """
        )
    )
    return int(result.rowcount or 0)


def eligible_offer_filter_sql(*, alias: str = "o") -> str:
    """SQL fragment (no leading AND) for Prop Finder eligible offers."""
    return f"""
        {alias}.is_active = true
        AND {alias}.match_status = 'matched'
        AND {alias}.is_alternate_line = false
        AND {alias}.player_id IS NOT NULL
        AND {alias}.game_id IS NOT NULL
        AND EXISTS (
            SELECT 1 FROM games g
            WHERE g.id = {alias}.game_id
              AND g.start_time > :now
              AND g.status IN ('scheduled', 'in_progress')
        )
        AND ({alias}.american_odds IS NULL OR abs({alias}.american_odds) <= 10000)
    """
