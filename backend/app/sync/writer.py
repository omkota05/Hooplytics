"""Idempotent database writes for synchronized provider data.

Every write is an INSERT ... ON CONFLICT upsert keyed on provider IDs, so re-running
any sync step never creates duplicate teams, players, games, or player-game rows.
"""

import unicodedata
from collections.abc import Iterable, Sequence
from dataclasses import asdict
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, select, text, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.ingestion.providers.base import (
    TRACKED_SEASON_TYPES,
    BoxScore,
    GameRecord,
    PlayerGameStatRecord,
    PlayerRecord,
    RosterEntry,
    TeamRecord,
)
from app.models import Game, Player, PlayerGameStat, PlayerTeamSeason, Team


def normalize_search_name(name: str) -> str:
    decomposed = unicodedata.normalize("NFKD", name)
    ascii_only = "".join(c for c in decomposed if not unicodedata.combining(c))
    cleaned = "".join(c if c.isalnum() or c.isspace() else " " for c in ascii_only.lower())
    return " ".join(cleaned.split())


def upsert_teams(session: Session, teams: Sequence[TeamRecord]) -> int:
    if not teams:
        return 0
    rows = [asdict(t) | {"is_active": True} for t in teams]
    stmt = insert(Team).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=[Team.id],
        set_={c: stmt.excluded[c] for c in rows[0] if c != "id"} | {"updated_at": func.now()},
    )
    session.execute(stmt)
    return len(rows)


def upsert_players(session: Session, players: Iterable[PlayerRecord]) -> int:
    rows = [
        asdict(p) | {"search_name": normalize_search_name(p.full_name)}
        for p in {p.id: p for p in players}.values()
    ]
    if not rows:
        return 0
    stmt = insert(Player).values(rows)
    always = {"full_name", "search_name"}
    # Box-score athletes carry fewer fields than roster athletes; never erase known values.
    set_ = {
        c: stmt.excluded[c] if c in always else func.coalesce(stmt.excluded[c], getattr(Player, c))
        for c in rows[0]
        if c != "id"
    }
    stmt = stmt.on_conflict_do_update(index_elements=[Player.id], set_=set_ | {"updated_at": func.now()})
    session.execute(stmt)
    return len(rows)


def apply_rosters(session: Session, entries: Sequence[RosterEntry]) -> int:
    """Make the given roster snapshot authoritative for current team / active status.

    Only call this with a complete snapshot of all teams; players missing from it are
    marked inactive (free agents, retired, or out of the league).
    """
    upsert_players(session, (e.player for e in entries))
    team_by_player = {e.player.id: e.team_id for e in entries}
    session.execute(
        update(Player).where(Player.is_active.is_(True)).values(is_active=False, current_team_id=None)
    )
    for team_id in set(team_by_player.values()):
        ids = [pid for pid, tid in team_by_player.items() if tid == team_id]
        session.execute(
            update(Player).where(Player.id.in_(ids)).values(is_active=True, current_team_id=team_id)
        )
    return len(team_by_player)


def upsert_games(session: Session, games: Iterable[GameRecord], known_team_ids: set[int]) -> int:
    """Upsert tracked games. Skips exhibition/All-Star games with non-NBA teams."""
    unique: dict[int, GameRecord] = {}
    for g in games:
        if g.season_type not in TRACKED_SEASON_TYPES:
            continue
        if g.home_team_id not in known_team_ids or g.away_team_id not in known_team_ids:
            continue
        unique[g.id] = g
    if not unique:
        return 0
    rows = [asdict(g) for g in unique.values()]
    stmt = insert(Game).values(rows)
    set_ = {c: stmt.excluded[c] for c in rows[0] if c != "id"}
    # A changed score means a stat correction: re-fetch the box score next sync.
    set_["boxscore_synced_at"] = text(
        "CASE WHEN (games.home_score IS DISTINCT FROM excluded.home_score "
        "OR games.away_score IS DISTINCT FROM excluded.away_score) "
        "THEN NULL ELSE games.boxscore_synced_at END"
    )
    set_["updated_at"] = func.now()
    stmt = stmt.on_conflict_do_update(index_elements=[Game.id], set_=set_)
    session.execute(stmt)
    return len(rows)


def write_boxscore(session: Session, box: BoxScore, known_team_ids: set[int]) -> int:
    """Persist a complete box score and mark its game as synced. Returns rows written."""
    if box.game is None or not box.is_complete:
        raise ValueError("write_boxscore requires a complete box score")
    game = box.game
    upsert_games(session, [game], known_team_ids)
    upsert_players(session, box.players)

    stat_rows = [_stat_row(s, game) for s in {s.player_id: s for s in box.stats}.values()]
    stmt = insert(PlayerGameStat).values(stat_rows)
    stmt = stmt.on_conflict_do_update(
        constraint="uq_player_game_stats_player_game",
        set_={c: stmt.excluded[c] for c in stat_rows[0] if c not in ("player_id", "game_id")}
        | {"updated_at": func.now()},
    )
    session.execute(stmt)

    # Drop rows for players no longer listed (provider-side box score corrections).
    session.execute(
        delete(PlayerGameStat).where(
            PlayerGameStat.game_id == game.id,
            PlayerGameStat.player_id.not_in([r["player_id"] for r in stat_rows]),
        )
    )
    session.execute(
        update(Game)
        .where(Game.id == game.id)
        .values(boxscore_synced_at=datetime.now(UTC), boxscore_error=None, boxscore_next_attempt_at=None)
    )
    refresh_player_team_seasons(session, [r["player_id"] for r in stat_rows], game.season)
    return len(stat_rows)


BOXSCORE_RETRY_BASE = timedelta(minutes=15)


def mark_boxscore_failed(session: Session, game_id: int, error: str, now: datetime | None = None) -> None:
    """Record a failed fetch and schedule the next try with exponential backoff
    (15m, 30m, 1h, 2h, ... after attempt 1, 2, 3, 4, ...)."""
    attempts = session.scalar(select(Game.boxscore_attempts).where(Game.id == game_id)) or 0
    retry_at = (now or datetime.now(UTC)) + BOXSCORE_RETRY_BASE * (2**attempts)
    session.execute(
        update(Game)
        .where(Game.id == game_id)
        .values(
            boxscore_attempts=attempts + 1,
            boxscore_error=error[:500],
            boxscore_next_attempt_at=retry_at,
        )
    )


def refresh_player_team_seasons(session: Session, player_ids: Sequence[int], season: int) -> None:
    if not player_ids:
        return
    session.execute(
        delete(PlayerTeamSeason).where(
            PlayerTeamSeason.player_id.in_(player_ids), PlayerTeamSeason.season == season
        )
    )
    aggregate = (
        select(
            PlayerGameStat.player_id,
            PlayerGameStat.team_id,
            PlayerGameStat.season,
            func.count().filter(PlayerGameStat.did_not_play.is_(False)),
            func.min(PlayerGameStat.game_date),
            func.max(PlayerGameStat.game_date),
        )
        .where(PlayerGameStat.player_id.in_(player_ids), PlayerGameStat.season == season)
        .group_by(PlayerGameStat.player_id, PlayerGameStat.team_id, PlayerGameStat.season)
    )
    session.execute(
        insert(PlayerTeamSeason).from_select(
            ["player_id", "team_id", "season", "games_played", "first_game_date", "last_game_date"],
            aggregate,
        )
    )


def _stat_row(stat: PlayerGameStatRecord, game: GameRecord) -> dict:
    return asdict(stat) | {
        "game_date": game.game_date,
        "season": game.season,
        "season_type": game.season_type,
    }
