"""Background sync loop that runs inside the API process.

* On startup: sync immediately if the last successful sync is older than SYNC_STALE_MINUTES
  (this is how the app catches up after the Mac was off).
* Every SYNC_INTERVAL_MINUTES: incremental sync (cheap: a few scoreboard requests).
* Between incremental syncs, with AUTO_BACKFILL on: download historical box scores in
  small resumable chunks until the configured seasons are complete.
"""

import logging
import threading
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select

from app.config import Settings
from app.db import get_sessionmaker, session_scope
from app.ingestion.http import ProviderError, ProviderUnavailableError
from app.models import SyncRun
from app.sync.factory import build_sync_service
from app.sync.service import SyncAlreadyRunningError, mark_interrupted_runs

logger = logging.getLogger(__name__)

BACKFILL_CHUNK = 60
IDLE_POLL_SECONDS = 60
PROVIDER_DOWN_BACKOFF = timedelta(minutes=10)


class SyncScheduler:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._thread: threading.Thread | None = None
        self._force = False
        self._paused_until: datetime | None = None
        self.next_run_at: datetime | None = None
        self.enabled = settings.sync_on_startup

    def start(self) -> None:
        with session_scope() as session:
            mark_interrupted_runs(session)
        if not self.enabled:
            logger.info("Background sync disabled (SYNC_ON_STARTUP=false)")
            return
        self._thread = threading.Thread(target=self._loop, name="hooplytics-sync", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        if self._thread:
            self._thread.join(timeout=10)

    def trigger(self) -> None:
        """Request an incremental sync as soon as possible."""
        self._force = True
        self._paused_until = None
        self._wake.set()

    def run_once_in_background(self) -> None:
        if self.enabled:
            self.trigger()
        else:
            threading.Thread(target=self._incremental, daemon=True).start()

    def _last_success(self) -> datetime | None:
        with get_sessionmaker()() as session:
            return session.scalar(
                select(func.max(SyncRun.finished_at)).where(
                    SyncRun.kind == "incremental", SyncRun.status.in_(("success", "partial"))
                )
            )

    def _incremental(self) -> None:
        service, provider = build_sync_service()
        try:
            run = service.run_incremental()
            logger.info(
                "Incremental sync %s: %d games, %d box scores",
                run.status,
                run.games_updated,
                run.boxscores_synced,
            )
            if run.status in ("success", "partial"):
                from app.services.recommendation_cache import warm_recommendations_async

                warm_recommendations_async()
        finally:
            provider.close()

    def _backfill_chunk(self) -> bool:
        """Returns True if historical work remains."""
        service, provider = build_sync_service()
        try:
            if service.pending_backfill_count() == 0:
                return False
            service.run_backfill(max_games=BACKFILL_CHUNK)
            return service.pending_backfill_count() > 0
        finally:
            provider.close()

    def _loop(self) -> None:
        interval = timedelta(minutes=self._settings.sync_interval_minutes)
        stale = timedelta(minutes=self._settings.sync_stale_minutes)
        first = True
        while not self._stop.is_set():
            now = datetime.now(UTC)
            more_backfill = False
            try:
                if self._paused_until and now < self._paused_until and not self._force:
                    self._sleep(IDLE_POLL_SECONDS)
                    continue
                last = self._last_success()
                due = last is None or now - last >= (stale if first else interval)
                if self._force or due:
                    self._force = False
                    self._incremental()
                elif self._settings.auto_backfill:
                    more_backfill = self._backfill_chunk()
                first = False
            except SyncAlreadyRunningError:
                logger.info("Sync already running in another process; will retry later")
            except ProviderUnavailableError as exc:
                self._paused_until = now + PROVIDER_DOWN_BACKOFF
                logger.error("Data provider unavailable, pausing sync for 10 minutes: %s", exc)
            except ProviderError as exc:
                logger.error("Data provider error during sync: %s", exc)
            except Exception:
                logger.exception("Unexpected sync failure")

            last = self._last_success()
            self.next_run_at = (last + interval) if last else datetime.now(UTC) + interval
            if not more_backfill:
                self._sleep(IDLE_POLL_SECONDS)

    def _sleep(self, seconds: float) -> None:
        self._wake.wait(timeout=seconds)
        self._wake.clear()
