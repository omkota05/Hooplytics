"""Background Unabated prop odds import (separate from ESPN sync)."""

import logging
import threading
from datetime import UTC, datetime, timedelta

from app.config import Settings
from app.db import session_scope
from app.odds.unabated.client import UnabatedClient, UnabatedRateLimitError
from app.services.prop_import_service import run_unabated_import

logger = logging.getLogger(__name__)


class OddsImportScheduler:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._thread: threading.Thread | None = None
        self._force = False

    def start(self) -> None:
        if not self._settings.prop_odds_sync_on_startup:
            logger.info("Prop odds sync disabled (PROP_ODDS_SYNC_ON_STARTUP=false)")
            return
        if not UnabatedClient.instance().configured:
            logger.info("Unabated not configured; prop odds sync idle")
            return
        self._thread = threading.Thread(target=self._loop, name="hooplytics-odds", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        if self._thread:
            self._thread.join(timeout=10)

    def trigger(self) -> None:
        self._force = True
        self._wake.set()

    def _import_once(self) -> None:
        try:
            with session_scope() as session:
                run = run_unabated_import(session)
            logger.info(
                "Unabated import %s: seen=%d matched=%d",
                run.status,
                run.offers_seen,
                run.offers_matched,
            )
            if run.status == "success":
                from app.services.forecast_archive_service import run_forecast_cycle

                run_forecast_cycle()
        except UnabatedRateLimitError as exc:
            logger.warning("Unabated rate limited; retry in %ss", exc.retry_after)

    def _loop(self) -> None:
        if self._settings.prop_odds_sync_on_startup:
            self._import_once()
        interval = timedelta(minutes=self._settings.prop_odds_sync_interval_minutes)
        next_run = datetime.now(UTC) + interval
        while not self._stop.is_set():
            if self._force or datetime.now(UTC) >= next_run:
                self._force = False
                self._import_once()
                next_run = datetime.now(UTC) + interval
            self._wake.wait(timeout=30)
            self._wake.clear()
