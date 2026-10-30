"""Import Unabated NBA player prop offers into the database."""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.config import get_settings
from app.odds.unabated.client import UnabatedClient, UnabatedError
from app.odds.unabated.deeplink import attach_partner_code
from app.odds.unabated.mapping import category_from_bet_type_id
from app.odds.unabated.parser import parse_props_odds
from app.models import Game
from app.models.sportsbook import PropImportRun, PropOffer, SportsbookSource
from app.services.prop_hit_cache_service import (
    apply_hit_to_offer_values,
    current_data_sync_reference,
    get_or_compute_hit_cache,
)
from app.services.prop_matching import match_game, match_player, opponent_for_player
from app.services.prop_offer_maintenance import consolidate_duplicate_offers, deactivate_past_game_offers

logger = logging.getLogger(__name__)

BATCH_SIZE = 200
ProgressHook = Callable[[dict[str, Any]], None]

_progress_hook: ProgressHook | None = None


def set_import_progress_hook(hook: ProgressHook | None) -> None:
    global _progress_hook
    _progress_hook = hook


def _emit_progress(payload: dict[str, Any]) -> None:
    if _progress_hook:
        _progress_hook(payload)


def _upsert_sportsbook(session: Session, source_id: int, name: str) -> SportsbookSource:
    row = session.scalar(
        select(SportsbookSource).where(SportsbookSource.unabated_market_source_id == source_id)
    )
    if row:
        row.name = name
        return row
    row = SportsbookSource(unabated_market_source_id=source_id, name=name)
    session.add(row)
    session.flush()
    return row


def _event_start_map(events: list[dict]) -> dict[int, datetime]:
    out: dict[int, datetime] = {}
    for ev in events:
        eid = ev.get("id") or ev.get("eventId")
        start = ev.get("eventStart") or ev.get("startTime")
        if eid is None or start is None:
            continue
        try:
            if isinstance(start, (int, float)):
                out[int(eid)] = datetime.fromtimestamp(int(start) / 1000, tz=UTC)
            else:
                out[int(eid)] = datetime.fromisoformat(str(start).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            continue
    return out


def _natural_key(
    *,
    sportsbook_label: str,
    event_id: int | None,
    person_id: int | None,
    bet_type_id: int | None,
    side_index: int | None,
    market_line_id: int | None,
    line: float,
    pick_side: str,
    alternate_key: str | None,
) -> tuple:
    """Canonical identity — one row per sportsbook/player/event/market/line/side."""
    del side_index, market_line_id, alternate_key  # stored on row, not part of upsert key
    return (
        sportsbook_label,
        event_id,
        person_id,
        bet_type_id,
        line,
        pick_side,
    )


def _natural_key_from_offer(o: PropOffer) -> tuple:
    return _natural_key(
        sportsbook_label=o.sportsbook_label,
        event_id=o.unabated_event_id,
        person_id=o.unabated_person_id,
        bet_type_id=o.unabated_bet_type_id,
        side_index=o.unabated_side_index,
        market_line_id=o.unabated_market_line_id,
        line=o.line,
        pick_side=o.pick_side,
        alternate_key=o.alternate_key,
    )


def _lookup_prev_offer(session: Session, cache: dict[tuple, PropOffer | None], nkey: tuple) -> PropOffer | None:
    if nkey in cache:
        return cache[nkey]
    book, event_id, person_id, bet_type_id, line, pick_side = nkey
    prev = session.scalar(
        select(PropOffer)
        .where(
            PropOffer.source_kind == "unabated",
            PropOffer.sportsbook_label == book,
            PropOffer.unabated_event_id == event_id,
            PropOffer.unabated_person_id == person_id,
            PropOffer.unabated_bet_type_id == bet_type_id,
            PropOffer.line == line,
            PropOffer.pick_side == pick_side,
        )
        .order_by(PropOffer.id.desc())
        .limit(1)
    )
    cache[nkey] = prev
    return prev


def _normalize_american_odds(value: int | None) -> int | None:
    if value is None:
        return None
    if abs(value) > 10_000:
        return None
    return value


def _line_cache_key(player_id: int, game_id: int, category: str, line: float) -> tuple[int, int, str, float]:
    return (player_id, game_id, category, line)


def _reuse_hits_from_offer(offer: PropOffer) -> tuple[dict | None, int | None, datetime | None]:
    if not offer.hit_rates:
        return None, None, None
    return offer.hit_rates, offer.hit_cache_id, offer.hit_computed_at or offer.updated_at


def _flush_batch(session: Session, batch: list[dict]) -> None:
    if not batch:
        return
    stmt = insert(PropOffer).values(batch)
    update_cols = {k: stmt.excluded[k] for k in batch[0] if k != "source_kind"}
    stmt = stmt.on_conflict_do_update(constraint="uq_prop_offer_canonical_key", set_=update_cols)
    session.execute(stmt)


def run_unabated_import(session: Session) -> PropImportRun:
    settings = get_settings()
    run = PropImportRun(status="running")
    session.add(run)
    session.flush()

    client = UnabatedClient.instance()
    if not client.configured:
        run.status = "failed"
        run.error = "Unabated API not configured"
        run.finished_at = datetime.now(UTC)
        return run

    hit_computed = hit_reused_offer = hit_reused_line_cache = 0
    import_started = datetime.now(UTC)
    prev_cache: dict[tuple, PropOffer | None] = {}

    try:
        t0 = datetime.now(UTC)
        league = client.nba_league_name()
        bet_types = client.bet_type_names()
        sources = {int(s["id"]): str(s.get("name") or f"Book {s['id']}") for s in client.market_sources(league)}
        people = client.props_people(league)
        try:
            event_starts = _event_start_map(client.upcoming_events(league))
        except UnabatedError as exc:
            logger.warning("Unabated upcoming events unavailable: %s", exc)
            event_starts = {}
        t_api = datetime.now(UTC)
        body = client.props_odds(league)
        t_parsed = datetime.now(UTC)
        parsed = parse_props_odds(body)
        run.offers_seen = len(parsed)

        source_rows: dict[int, SportsbookSource] = {}
        for sid, name in sources.items():
            source_rows[sid] = _upsert_sportsbook(session, sid, name)

        upserted = matched = unmatched = 0
        memory_cache: dict[tuple[int, int, str, float], tuple[dict, int | None, datetime]] = {}
        sync_ref = current_data_sync_reference(session)
        unmapped_categories = 0
        game_cache: dict[int, Game | None] = {}
        batch: list[dict] = []

        def flush() -> None:
            nonlocal batch
            _flush_batch(session, batch)
            batch = []
            if upserted and upserted % 2000 == 0:
                session.commit()

        for idx, line in enumerate(parsed):
            if line.is_alternate:
                continue
            category = category_from_bet_type_id(line.bet_type_id, bet_types)
            if category is None:
                unmapped_categories += 1
                continue
            book = source_rows.get(line.market_source_id)
            book_label = book.name if book else f"source_{line.market_source_id}"
            player_name = people.get(line.person_id) if line.person_id else line.player_name
            alt_key = line.alternate_key if line.is_alternate else None

            game_id, game_method = match_game(
                session,
                unabated_event_id=line.event_id,
                event_name=line.event_name,
                start_time=event_starts.get(line.event_id) or line.event_start or line.modified_on,
            )
            event_team_ids: set[int] = set()
            if game_id:
                if game_id not in game_cache:
                    game_cache[game_id] = session.get(Game, game_id)
                game = game_cache[game_id]
                if game:
                    event_team_ids = {game.home_team_id, game.away_team_id}
            else:
                game = None

            player_id, player_method = match_player(
                session,
                unabated_person_id=line.person_id,
                player_name=player_name,
                team_unabated_id=line.team_id,
                team_abbrev_hint=None,
                event_team_ids=event_team_ids,
            )

            match_status = "matched"
            note = None
            if player_id is None or game_id is None:
                match_status = "unmatched"
                note = f"player={player_method}; game={game_method}"
                unmatched += 1
            else:
                matched += 1

            opponent_id = opponent_for_player(session, game_id, player_id) if player_id and game_id else None
            if game_id and game is None:
                game = game_cache.get(game_id) or session.get(Game, game_id)

            nkey = _natural_key(
                sportsbook_label=book_label,
                event_id=line.event_id,
                person_id=line.person_id,
                bet_type_id=line.bet_type_id,
                side_index=line.side_index,
                market_line_id=line.market_line_id,
                line=line.points,
                pick_side=line.pick_side,
                alternate_key=alt_key,
            )
            prev = _lookup_prev_offer(session, prev_cache, nkey)

            hit_json = None
            hit_cache_id = None
            hit_computed_at = None
            if player_id and match_status == "matched" and game:
                pg_key = _line_cache_key(player_id, game.id, category, line.points)
                if prev and prev.line == line.points and prev.category_key == category and prev.hit_rates:
                    hit_json, hit_cache_id, hit_computed_at = _reuse_hits_from_offer(prev)
                    hit_reused_offer += 1
                elif pg_key in memory_cache:
                    hit_json, hit_cache_id, hit_computed_at = memory_cache[pg_key]
                    hit_reused_line_cache += 1
                else:
                    memory_cache[pg_key] = get_or_compute_hit_cache(
                        session,
                        player_id=player_id,
                        game_id=game.id,
                        opponent_team_id=opponent_id,
                        category_key=category,
                        line=line.points,
                        season=game.season,
                        before_start=game.start_time,
                        data_sync_reference=sync_ref,
                    )
                    hit_json, hit_cache_id, hit_computed_at = memory_cache[pg_key]
                    hit_computed += 1

            published = attach_partner_code(line.deep_link, settings.unabated_partner_code)

            values = {
                "source_kind": "unabated",
                "sportsbook_source_id": book.id if book else None,
                "sportsbook_label": book_label,
                "player_id": player_id,
                "game_id": game_id,
                "opponent_team_id": opponent_id,
                "unabated_event_id": line.event_id,
                "unabated_person_id": line.person_id,
                "unabated_bet_type_id": line.bet_type_id,
                "unabated_market_line_id": line.market_line_id,
                "unabated_side_index": line.side_index,
                "period_type_id": line.period_type_id,
                "category_key": category,
                "line": line.points,
                "pick_side": line.pick_side,
                "american_odds": _normalize_american_odds(line.american_odds),
                "is_alternate_line": line.is_alternate,
                "alternate_key": alt_key,
                "deep_link_raw": line.deep_link,
                "deep_link_published": published,
                "event_name": line.event_name,
                "player_name_raw": player_name,
                "game_start_time": game.start_time if game else None,
                "game_date": game.game_date if game else None,
                "line_modified_at": line.modified_on,
                "is_active": True,
                "match_status": match_status,
                "match_note": note,
                "updated_at": datetime.now(UTC),
            }
            values = apply_hit_to_offer_values(
                values,
                hit_rates=hit_json,
                pick_side=line.pick_side,
                hit_cache_id=hit_cache_id,
                computed_at=hit_computed_at,
            )
            batch.append(values)
            upserted += 1
            if len(batch) >= BATCH_SIZE:
                flush()
            if idx % 500 == 0:
                _emit_progress(
                    {
                        "phase": "importing",
                        "processed": idx,
                        "parsed_total": len(parsed),
                        "upserted": upserted,
                    }
                )

        flush()
        session.flush()

        stale = session.execute(
            update(PropOffer)
            .where(
                PropOffer.source_kind == "unabated",
                PropOffer.is_active.is_(True),
                PropOffer.updated_at < import_started,
            )
            .values(is_active=False)
        )
        deactivated_stale = int(stale.rowcount or 0)
        deactivated_past = deactivate_past_game_offers(session)
        deduped = consolidate_duplicate_offers(session)

        run.offers_upserted = upserted
        run.offers_matched = matched
        run.offers_unmatched = unmatched
        run.status = "success"
        t_end = datetime.now(UTC)
        run.details = {
            "league": league,
            "bet_types_mapped": len(bet_types),
            "sportsbooks": list(sources.values()),
            "last_updated": body.get("data", {}).get("lastUpdated"),
            "parsed_total": len(parsed),
            "skipped_alternate_lines": sum(1 for l in parsed if l.is_alternate),
            "skipped_unmapped_bet_types": unmapped_categories,
            "people_index_size": len(people),
            "hit_stats_computed": hit_computed,
            "hit_stats_reused_offer": hit_reused_offer,
            "hit_stats_reused_line_cache": hit_reused_line_cache,
            "unique_line_cache_keys": len(memory_cache),
            "deactivated_stale_import": deactivated_stale,
            "deactivated_past_games": deactivated_past,
            "deactivated_duplicates": deduped,
            "timing_ms": {
                "api_setup": int((t_api - t0).total_seconds() * 1000),
                "props_odds_fetch": int((t_parsed - t_api).total_seconds() * 1000),
                "import_loop": int((t_end - t_parsed).total_seconds() * 1000),
                "total": int((t_end - t0).total_seconds() * 1000),
            },
        }
    except Exception as exc:
        logger.exception("Unabated import failed")
        run.status = "failed"
        run.error = str(exc)
        run.finished_at = datetime.now(UTC)
        session.flush()
        raise
    run.finished_at = datetime.now(UTC)
    return run
