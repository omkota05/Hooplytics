"""Historical sportsbook odds archive: snapshot recording and post-game settlement.

Snapshots reuse data already returned by the normal Unabated import — this module never calls
the Unabated API. Observation timestamps are real import times; nothing is backdated.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.analytics.categories import CATEGORIES

logger = logging.getLogger("hooplytics")

_SNAPSHOT_COLS = """source_kind, sportsbook_label, player_id, game_id, category_key, line, pick_side,
    american_odds, is_alternate_line, unabated_event_id, unabated_person_id, unabated_bet_type_id,
    unabated_market_line_id, game_start_time, line_modified_at"""


def record_import_snapshots(session: Session, *, import_run_id: int | None, observed_at: datetime) -> dict[str, int]:
    """Version every offer touched by the import that started at `observed_at`.

    Unchanged price -> extend the latest snapshot. Changed price -> close the old snapshot and
    append a new one. New offer -> append.
    """
    params = {"t": observed_at, "run": import_run_id}
    extended = session.execute(
        text(
            """
            UPDATE prop_offer_snapshots s
            SET last_observed_at = :t, observation_count = s.observation_count + 1
            FROM prop_offers o
            WHERE s.offer_id = o.id AND s.is_latest
              AND o.source_kind = 'unabated' AND o.updated_at >= :t
              AND s.american_odds IS NOT DISTINCT FROM o.american_odds
              AND s.line = o.line
            """
        ),
        params,
    ).rowcount
    closed = session.execute(
        text(
            """
            UPDATE prop_offer_snapshots s
            SET is_latest = false
            FROM prop_offers o
            WHERE s.offer_id = o.id AND s.is_latest
              AND o.source_kind = 'unabated' AND o.updated_at >= :t
              AND (s.american_odds IS DISTINCT FROM o.american_odds OR s.line <> o.line)
            """
        ),
        params,
    ).rowcount
    inserted = session.execute(
        text(
            f"""
            INSERT INTO prop_offer_snapshots (offer_id, import_run_id, origin, {_SNAPSHOT_COLS},
                first_observed_at, last_observed_at, observation_count, market_status, is_latest)
            SELECT o.id, :run, 'import', {', '.join('o.' + c.strip() for c in _SNAPSHOT_COLS.split(','))},
                :t, :t, 1, 'open', true
            FROM prop_offers o
            WHERE o.source_kind = 'unabated' AND o.updated_at >= :t
              AND NOT EXISTS (SELECT 1 FROM prop_offer_snapshots s WHERE s.offer_id = o.id AND s.is_latest)
            """
        ),
        params,
    ).rowcount
    return {"snapshots_extended": int(extended or 0), "snapshots_closed": int(closed or 0), "snapshots_inserted": int(inserted or 0)}


def backfill_last_seen_pregame(session: Session) -> int:
    """One-time import of offers whose last stored observation predates tip-off.

    `prop_offers` keeps the most recent price per offer; `imported_at` is the first time it was
    seen and `updated_at` the last write, both genuine import times. Only rows written strictly
    before the game started are archived, flagged with origin `prop_offers_last_seen`.
    """
    n = session.execute(
        text(
            f"""
            INSERT INTO prop_offer_snapshots (offer_id, import_run_id, origin, {_SNAPSHOT_COLS},
                first_observed_at, last_observed_at, observation_count, market_status, is_latest)
            SELECT o.id, NULL, 'prop_offers_last_seen', {', '.join('o.' + c.strip() for c in _SNAPSHOT_COLS.split(','))},
                o.imported_at, o.updated_at, 1, 'closed', true
            FROM prop_offers o JOIN games g ON g.id = o.game_id
            WHERE o.updated_at < g.start_time AND o.imported_at < g.start_time
              AND o.player_id IS NOT NULL AND o.match_status = 'matched'
              AND NOT EXISTS (SELECT 1 FROM prop_offer_snapshots s WHERE s.offer_id = o.id)
            """
        )
    ).rowcount
    return int(n or 0)


def _actual_sql() -> str:
    cases = []
    for key, cat in CATEGORIES.items():
        parts = " + ".join(f"p.{c}" for c in cat.components)
        cases.append(f"WHEN '{key}' THEN ({parts})")
    return "CASE s.category_key " + " ".join(cases) + " ELSE NULL END"


def settle_snapshots(session: Session, *, now: datetime | None = None) -> dict[str, int]:
    """Settle unsettled snapshots for final games with synced box scores.

    hit/miss/push from the player's box score; `void_dnp` when the box score lists the player as
    DNP; `unresolved` when the player is absent from the box score or a component stat is missing.
    Unresolved rows are never counted as losses.
    """
    ts = now or datetime.now(UTC)
    actual = _actual_sql()
    res = session.execute(
        text(
            f"""
            WITH targets AS (
                SELECT s.id, s.line, s.pick_side, p.did_not_play, p.player_id AS pgs_player,
                       {actual} AS actual
                FROM prop_offer_snapshots s
                JOIN games g ON g.id = s.game_id AND g.status = 'final' AND g.boxscore_synced_at IS NOT NULL
                LEFT JOIN player_game_stats p ON p.game_id = s.game_id AND p.player_id = s.player_id
                WHERE s.result IS NULL AND s.player_id IS NOT NULL
            )
            UPDATE prop_offer_snapshots s
            SET actual_value = t.actual,
                settled_at = :ts,
                result = CASE
                    WHEN t.pgs_player IS NULL THEN 'unresolved'
                    WHEN t.did_not_play THEN 'void_dnp'
                    WHEN t.actual IS NULL THEN 'unresolved'
                    WHEN t.actual = t.line THEN 'push'
                    WHEN (t.actual > t.line) = (t.pick_side = 'over') THEN 'hit'
                    ELSE 'miss'
                END
            FROM targets t WHERE s.id = t.id
            RETURNING s.result
            """
        ),
        {"ts": ts},
    ).all()
    counts: dict[str, int] = {}
    for (r,) in res:
        counts[r] = counts.get(r, 0) + 1
    return counts


def archive_status(session: Session) -> dict:
    row = session.execute(
        text(
            """
            SELECT count(*), count(*) FILTER (WHERE result IS NOT NULL),
                   count(*) FILTER (WHERE result IN ('hit','miss','push')),
                   count(DISTINCT game_id), min(first_observed_at), max(last_observed_at),
                   count(*) FILTER (WHERE origin = 'import'),
                   count(*) FILTER (WHERE origin = 'prop_offers_last_seen'),
                   count(*) FILTER (WHERE last_observed_at < game_start_time)
            FROM prop_offer_snapshots
            """
        )
    ).one()
    by_result = dict(
        session.execute(text("SELECT coalesce(result,'pending'), count(*) FROM prop_offer_snapshots GROUP BY 1")).all()
    )
    return {
        "snapshots": int(row[0]),
        "settled": int(row[1]),
        "graded": int(row[2]),
        "games": int(row[3]),
        "first_observed_at": row[4],
        "last_observed_at": row[5],
        "from_live_imports": int(row[6]),
        "from_prop_offers_last_seen": int(row[7]),
        "pregame_observations": int(row[8]),
        "by_result": {k: int(v) for k, v in by_result.items()},
    }
