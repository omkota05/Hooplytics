"""Synchronization orchestration: provider -> normalized records -> PostgreSQL.

Two entry points:

* `run_incremental` keeps the current season fresh: recent/stale game days, upcoming
  schedule, rosters, and any completed games whose box scores are missing.
* `run_backfill` downloads full schedules and box scores for historical seasons. Each
  box score is committed on its own, so an interrupted backfill resumes where it left off.

Only one sync runs at a time across processes (PostgreSQL advisory lock).
"""

import logging
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import func, or_, select, text, update
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings
from app.ingestion.http import ProviderError, ProviderUnavailableError
from app.ingestion.providers.base import TRACKED_SEASON_TYPES, DataProvider, RosterEntry
from app.models import Game, SyncRun, SyncState, Team
from app.sync import writer
from app.sync.state import get_state, set_state

logger = logging.getLogger(__name__)

ADVISORY_LOCK_KEY = 7_340_021  # arbitrary constant identifying the Hooplytics sync lock
ROSTER_REFRESH = timedelta(hours=12)
UPCOMING_REFRESH = timedelta(hours=3)
FULL_SCHEDULE_REFRESH = timedelta(days=3)
MAX_CATCHUP_DAYS = 21
MAX_BOXSCORE_ATTEMPTS = 8


class SyncAlreadyRunningError(RuntimeError):
    pass


class SyncService:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        provider: DataProvider,
        settings: Settings,
        now: Callable[[], datetime] = lambda: datetime.now(UTC),
        min_expected_teams: int = 30,
        min_expected_roster_players: int = 300,
    ) -> None:
        # Sanity floors: a provider response below these is treated as broken/partial.
        self._min_teams = min_expected_teams
        self._min_roster_players = min_expected_roster_players
        self._sessions = session_factory
        self._provider = provider
        self._settings = settings
        self._now = now
        self._known_team_ids: set[int] = set()

    # ------------------------------------------------------------------ public API

    def run_incremental(self) -> SyncRun:
        with self._locked(), self._tracked_run("incremental") as run:
            season = self._refresh_current_season()
            self._ensure_teams()
            self._refresh_rosters_if_due()

            with self._sessions() as session:
                full_key = f"schedule_full:{season}"
                last_full = _parse_ts(get_state(session, full_key, {}).get("at"))
            if last_full is None or self._now() - last_full > FULL_SCHEDULE_REFRESH:
                run.games_updated += self._sync_full_schedule(season)
            else:
                run.games_updated += self._sync_scoreboard_days(self._days_to_refresh())

            synced, failed = self._sync_missing_boxscores(seasons=[season])
            run.boxscores_synced += synced
            run.details = {"season": season, "boxscore_failures": failed}
            if failed:
                run.status = "partial"
            return run

    def run_backfill(self, seasons: list[int] | None = None, max_games: int | None = None) -> SyncRun:
        with self._locked(), self._tracked_run("backfill") as run:
            current = self._refresh_current_season()
            self._ensure_teams()
            seasons = seasons or self.backfill_seasons(current)
            # Schedules are downloaded once per season here; the current season's schedule
            # is kept fresh by run_incremental.
            for season in seasons:
                with self._sessions() as session:
                    done = get_state(session, f"schedule_full:{season}", None)
                if done is None:
                    run.games_updated += self._sync_full_schedule(season)
            synced, failed = self._sync_missing_boxscores(seasons=seasons, limit=max_games)
            run.boxscores_synced += synced
            run.details = {"seasons": seasons, "boxscore_failures": failed}
            if failed:
                run.status = "partial"
            return run

    def backfill_seasons(self, current: int) -> list[int]:
        return [current - i for i in range(self._settings.history_seasons + 1)]

    def pending_backfill_count(self) -> int:
        with self._sessions() as session:
            current = get_state(session, "current_season", {}).get("season")
            if current is None:
                return 1
            seasons = self.backfill_seasons(current)
            missing_schedules = [s for s in seasons if get_state(session, f"schedule_full:{s}", None) is None]
            if missing_schedules:
                return len(missing_schedules)
            return (
                session.scalar(
                    select(func.count()).select_from(Game).where(*self._missing_boxscore_filter(seasons))
                )
                or 0
            )

    # ------------------------------------------------------------------ steps

    def _refresh_current_season(self) -> int:
        season = self._provider.current_season()
        with self._sessions.begin() as session:
            set_state(session, "current_season", {"season": season})
        return season

    def _ensure_teams(self) -> None:
        with self._sessions.begin() as session:
            last = _parse_ts(get_state(session, "teams", {}).get("at"))
            if last is None or self._now() - last > timedelta(days=7):
                teams = self._provider.fetch_teams()
                if len(teams) < self._min_teams:
                    raise ProviderError(
                        f"Expected {self._min_teams} NBA teams, provider returned {len(teams)}"
                    )
                writer.upsert_teams(session, teams)
                set_state(session, "teams", {"at": self._now().isoformat(), "count": len(teams)})
            self._known_team_ids = set(session.scalars(select(Team.id)))

    def _refresh_rosters_if_due(self) -> None:
        with self._sessions() as session:
            last = _parse_ts(get_state(session, "rosters", {}).get("at"))
        if last is not None and self._now() - last < ROSTER_REFRESH:
            return
        entries: list[RosterEntry] = []
        for team_id in sorted(self._known_team_ids):
            entries.extend(self._provider.fetch_roster(team_id))
        if len(entries) < self._min_roster_players:
            # Partial or broken response: keep the previous snapshot instead.
            logger.warning("Roster snapshot looks incomplete (%d players); skipping", len(entries))
            return
        with self._sessions.begin() as session:
            count = writer.apply_rosters(session, entries)
            set_state(session, "rosters", {"at": self._now().isoformat(), "players": count})
        logger.info("Rosters refreshed: %d players", count)

    def _sync_full_schedule(self, season: int) -> int:
        games = {}
        for team_id in sorted(self._known_team_ids):
            for season_type in TRACKED_SEASON_TYPES:
                for g in self._provider.fetch_team_schedule(team_id, season, season_type):
                    games[g.id] = g
        with self._sessions.begin() as session:
            count = writer.upsert_games(session, games.values(), self._known_team_ids)
            set_state(session, f"schedule_full:{season}", {"at": self._now().isoformat(), "games": count})
            set_state(session, "upcoming", {"at": self._now().isoformat()})
        logger.info("Season %s schedule synced: %d games", season, count)
        return count

    def _days_to_refresh(self) -> list[date]:
        """Recent days since the last success, days with stale unfinished games, and
        (every few hours) the upcoming window."""
        today = self._now().astimezone(_eastern()).date()
        with self._sessions() as session:
            last_ok = session.scalar(
                select(func.max(SyncRun.finished_at)).where(
                    SyncRun.kind == "incremental", SyncRun.status.in_(("success", "partial"))
                )
            )
            start = (last_ok.astimezone(_eastern()).date() if last_ok else today) - timedelta(days=1)
            start = max(start, today - timedelta(days=MAX_CATCHUP_DAYS))
            days = {start + timedelta(days=i) for i in range((today - start).days + 1)}

            stale_cutoff = self._now() - timedelta(hours=4)
            stale_days = session.scalars(
                select(Game.game_date)
                .where(
                    Game.status.in_(("scheduled", "in_progress", "suspended")),
                    Game.start_time < stale_cutoff,
                    Game.game_date >= today - timedelta(days=60),
                )
                .distinct()
            )
            days.update(stale_days)

            last_upcoming = _parse_ts(get_state(session, "upcoming", {}).get("at"))
        if last_upcoming is None or self._now() - last_upcoming > UPCOMING_REFRESH:
            days.update(today + timedelta(days=i) for i in range(1, self._settings.upcoming_days + 1))
            self._mark_upcoming = True
        else:
            self._mark_upcoming = False
        return sorted(days)

    def _sync_scoreboard_days(self, days: list[date]) -> int:
        total = 0
        for day in days:
            games = self._provider.fetch_scoreboard(day)
            with self._sessions.begin() as session:
                total += writer.upsert_games(session, games, self._known_team_ids)
        if getattr(self, "_mark_upcoming", False):
            with self._sessions.begin() as session:
                set_state(session, "upcoming", {"at": self._now().isoformat()})
        return total

    def _missing_boxscore_filter(self, seasons: list[int]) -> list:
        """Completed games without a box score that are due for a (re)try."""
        return [
            Game.status == "final",
            Game.boxscore_synced_at.is_(None),
            Game.boxscore_attempts < MAX_BOXSCORE_ATTEMPTS,
            or_(Game.boxscore_next_attempt_at.is_(None), Game.boxscore_next_attempt_at <= self._now()),
            Game.season.in_(seasons),
        ]

    def _sync_missing_boxscores(self, seasons: list[int], limit: int | None = None) -> tuple[int, int]:
        with self._sessions() as session:
            query = (
                select(Game.id)
                .where(*self._missing_boxscore_filter(seasons))
                .order_by(Game.start_time.desc())
            )
            if limit:
                query = query.limit(limit)
            game_ids = list(session.scalars(query))

        synced = failed = 0
        for index, game_id in enumerate(game_ids, start=1):
            try:
                box = self._provider.fetch_boxscore(game_id)
            except ProviderUnavailableError:
                raise
            except ProviderError as exc:
                failed += 1
                with self._sessions.begin() as session:
                    writer.mark_boxscore_failed(session, game_id, str(exc), now=self._now())
                continue

            with self._sessions.begin() as session:
                if box.is_complete:
                    writer.write_boxscore(session, box, self._known_team_ids)
                    synced += 1
                else:
                    failed += 1
                    if box.game is not None:
                        writer.upsert_games(session, [box.game], self._known_team_ids)
                    writer.mark_boxscore_failed(
                        session, game_id, "Box score not available yet", now=self._now()
                    )
            if index % 25 == 0:
                logger.info("Box scores: %d/%d processed", index, len(game_ids))
        if game_ids:
            logger.info("Box scores synced: %d ok, %d unavailable/failed", synced, failed)
        return synced, failed

    # ------------------------------------------------------------------ plumbing

    @contextmanager
    def _locked(self) -> Iterator[None]:
        engine = self._sessions.kw["bind"]
        with engine.connect() as conn:
            acquired = conn.scalar(text("SELECT pg_try_advisory_lock(:k)"), {"k": ADVISORY_LOCK_KEY})
            if not acquired:
                raise SyncAlreadyRunningError("Another sync is already running")
            try:
                yield
            finally:
                conn.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": ADVISORY_LOCK_KEY})
                conn.commit()

    @contextmanager
    def _tracked_run(self, kind: str) -> Iterator[SyncRun]:
        requests_before = self._provider.request_count
        with self._sessions.begin() as session:
            run = SyncRun(kind=kind, status="running", games_updated=0, boxscores_synced=0)
            session.add(run)
            session.flush()
            run_id = run.id
        try:
            yield run
            final_status = run.status if run.status != "running" else "success"
            error = None
        except Exception as exc:
            final_status, error = "failed", f"{type(exc).__name__}: {exc}"
            logger.exception("Sync %s failed", kind)
            raise
        finally:
            with self._sessions.begin() as session:
                session.execute(
                    update(SyncRun)
                    .where(SyncRun.id == run_id)
                    .values(
                        status=final_status,
                        finished_at=self._now(),
                        games_updated=run.games_updated,
                        boxscores_synced=run.boxscores_synced,
                        requests_made=self._provider.request_count - requests_before,
                        error=error,
                        details=run.details,
                    )
                )
            run.id, run.status, run.error = run_id, final_status, error


def mark_interrupted_runs(session: Session) -> None:
    """Runs left 'running' by a killed process are recorded as failed.

    Skipped while any process holds the sync lock, since its run is genuinely live.
    """
    acquired = session.scalar(text("SELECT pg_try_advisory_lock(:k)"), {"k": ADVISORY_LOCK_KEY})
    if not acquired:
        return
    try:
        session.execute(
            update(SyncRun)
            .where(SyncRun.status == "running")
            .values(status="failed", finished_at=func.now(), error="Interrupted (process exited)")
        )
    finally:
        session.execute(text("SELECT pg_advisory_unlock(:k)"), {"k": ADVISORY_LOCK_KEY})


def _parse_ts(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def _eastern():
    from app.ingestion.providers.espn.normalize import EASTERN

    return EASTERN


__all__ = ["SyncAlreadyRunningError", "SyncService", "SyncState", "mark_interrupted_runs"]
