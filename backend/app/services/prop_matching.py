"""Match Unabated players and events to Hooplytics ESPN-backed records."""

from __future__ import annotations

import re
import unicodedata
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models import Game, Player, Team
from app.models.sportsbook import UnabatedIdentityMapping


def _normalize_name(value: str) -> str:
    deaccent = unicodedata.normalize("NFKD", value)
    ascii_only = "".join(c for c in deaccent if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", " ", ascii_only.lower()).strip()


def _match_memo(session: Session) -> dict:
    return session.info.setdefault("unabated_match_memo", {})


def mapping_lookup(session: Session, entity_type: str, unabated_id: int) -> int | None:
    memo = _match_memo(session)
    key = (entity_type, int(unabated_id))
    if key in memo:
        return memo[key]
    row = session.scalar(
        select(UnabatedIdentityMapping.hooplytics_id).where(
            UnabatedIdentityMapping.entity_type == entity_type,
            UnabatedIdentityMapping.unabated_id == unabated_id,
        )
    )
    if row is None:
        return None
    hoop_id = int(row)
    memo[key] = hoop_id
    return hoop_id


def save_mapping(
    session: Session,
    *,
    entity_type: str,
    unabated_id: int,
    hooplytics_id: int,
    method: str,
    confidence: float = 1.0,
    meta: dict | None = None,
) -> None:
    """Idempotent upsert — the same Unabated event/player is matched thousands of times per import."""
    stmt = insert(UnabatedIdentityMapping).values(
        entity_type=entity_type,
        unabated_id=unabated_id,
        hooplytics_id=hooplytics_id,
        match_method=method,
        confidence=confidence,
        meta=meta,
    )
    stmt = stmt.on_conflict_do_update(
        constraint="uq_unabated_entity",
        set_={
            "hooplytics_id": stmt.excluded.hooplytics_id,
            "match_method": stmt.excluded.match_method,
            "confidence": stmt.excluded.confidence,
            "meta": stmt.excluded.meta,
        },
    )
    session.execute(stmt)
    _match_memo(session)[(entity_type, int(unabated_id))] = hooplytics_id


def match_player(
    session: Session,
    *,
    unabated_person_id: int | None,
    player_name: str | None,
    team_unabated_id: int | None,
    team_abbrev_hint: str | None,
    event_team_ids: set[int],
) -> tuple[int | None, str]:
    if unabated_person_id is not None:
        cached = mapping_lookup(session, "player", unabated_person_id)
        if cached is not None:
            return cached, "mapping_table"

    if not player_name:
        return None, "missing_name"

    if event_team_ids:
        roster_key = ("roster", frozenset(event_team_ids))
        memo = _match_memo(session)
        if roster_key not in memo:
            memo[roster_key] = list(
                session.scalars(select(Player).where(Player.current_team_id.in_(event_team_ids))).all()
            )
        team_filtered = [
            p
            for p in memo[roster_key]
            if _normalize_name(p.full_name) == _normalize_name(player_name)
        ]
        if len(team_filtered) == 1:
            pid = team_filtered[0].id
            if unabated_person_id is not None:
                save_mapping(
                    session,
                    entity_type="player",
                    unabated_id=unabated_person_id,
                    hooplytics_id=pid,
                    method="exact_name_event_teams",
                )
            return pid, "exact_name_event_teams"
        if len(team_filtered) > 1:
            return None, "ambiguous_name_event_teams"

    norm = _normalize_name(player_name)
    if not norm:
        return None, "missing_name"

    memo = _match_memo(session)
    if "active_players" not in memo:
        memo["active_players"] = list(
            session.scalars(select(Player).where(Player.is_active.is_(True)).limit(5000)).all()
        )
    candidates = memo["active_players"]
    exact = [p for p in candidates if _normalize_name(p.full_name) == norm]
    if len(exact) == 1:
        pid = exact[0].id
        if unabated_person_id is not None:
            save_mapping(session, entity_type="player", unabated_id=unabated_person_id, hooplytics_id=pid, method="exact_name")
        return pid, "exact_name"
    if len(exact) > 1:
        filtered = [p for p in exact if p.current_team_id in event_team_ids]
        if len(filtered) == 1:
            pid = filtered[0].id
            if unabated_person_id is not None:
                save_mapping(
                    session,
                    entity_type="player",
                    unabated_id=unabated_person_id,
                    hooplytics_id=pid,
                    method="exact_name_team",
                )
            return pid, "exact_name_team"
        return None, "ambiguous_name"

    if team_abbrev_hint:
        team = session.scalar(select(Team).where(Team.abbreviation == team_abbrev_hint.upper()))
        if team:
            on_team = [p for p in candidates if p.current_team_id == team.id and norm in _normalize_name(p.full_name)]
            if len(on_team) == 1:
                pid = on_team[0].id
                if unabated_person_id is not None:
                    save_mapping(session, entity_type="player", unabated_id=unabated_person_id, hooplytics_id=pid, method="fuzzy_team")
                return pid, "fuzzy_team"
    return None, "unmatched"


def _parse_event_teams(event_name: str) -> tuple[str | None, str | None]:
    """Parse team abbreviations from Unabated event titles."""

    def trailing_abbr(part: str) -> str | None:
        for token in reversed(part.strip().split()):
            if len(token) == 3 and token.isalpha() and token.isupper():
                return token
        compact = part.strip().upper()
        return compact[:3] if len(compact) >= 3 else None

    if "@" not in event_name:
        return None, None
    away, home = event_name.split("@", 1)
    return trailing_abbr(away), trailing_abbr(home)


def match_game(
    session: Session,
    *,
    unabated_event_id: int,
    event_name: str,
    start_time: datetime | None,
) -> tuple[int | None, str]:
    memo = _match_memo(session)
    hit = memo.get(("event_match", unabated_event_id))
    if hit is not None:
        return hit

    cached = mapping_lookup(session, "event", unabated_event_id)
    if cached is not None:
        result = (cached, "mapping_table")
        memo[("event_match", unabated_event_id)] = result
        return result

    away_abbr, home_abbr = _parse_event_teams(event_name)
    if not away_abbr or not home_abbr:
        return None, "unparsed_event"

    away = session.scalar(select(Team).where(Team.abbreviation == away_abbr))
    home = session.scalar(select(Team).where(Team.abbreviation == home_abbr))
    if away is None or home is None:
        return None, "unknown_team_abbr"

    window_start = (start_time or datetime.now(UTC)) - timedelta(hours=18)
    window_end = (start_time or datetime.now(UTC)) + timedelta(hours=18)
    games = session.scalars(
        select(Game).where(
            Game.home_team_id == home.id,
            Game.away_team_id == away.id,
            Game.start_time >= window_start,
            Game.start_time <= window_end,
            Game.status.in_(("scheduled", "in_progress")),
        )
    ).all()
    if len(games) == 1:
        gid = games[0].id
        save_mapping(session, entity_type="event", unabated_id=unabated_event_id, hooplytics_id=gid, method="teams_time")
        result = (gid, "teams_time")
        memo[("event_match", unabated_event_id)] = result
        return result
    if len(games) > 1:
        return None, "ambiguous_game"
    return None, "no_game"


def opponent_for_player(session: Session, game_id: int, player_id: int) -> int | None:
    game = session.get(Game, game_id)
    player = session.get(Player, player_id)
    if game is None or player is None or player.current_team_id is None:
        return None
    if player.current_team_id == game.home_team_id:
        return game.away_team_id
    if player.current_team_id == game.away_team_id:
        return game.home_team_id
    return None
