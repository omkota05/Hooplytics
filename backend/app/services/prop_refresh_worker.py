"""Background Unabated import (non-blocking HTTP)."""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from app.db import session_scope
from app.services.prop_import_service import run_unabated_import, set_import_progress_hook

logger = logging.getLogger(__name__)


@dataclass
class PropRefreshState:
    in_progress: bool = False
    started_at: datetime | None = None
    finished_at: datetime | None = None
    last_error: str | None = None
    last_run_id: int | None = None
    last_details: dict | None = None
    progress: dict | None = None


_lock = threading.Lock()
_state = PropRefreshState()
_MAX_REFRESH_AGE = timedelta(hours=2)


def _maybe_reset_stale_worker() -> None:
    with _lock:
        if not _state.in_progress or _state.started_at is None:
            return
        age = datetime.now(UTC) - _state.started_at
        if age > _MAX_REFRESH_AGE:
            _state.in_progress = False
            _state.progress = None
            _state.last_error = _state.last_error or "Refresh timed out; worker state was reset."


def refresh_state() -> PropRefreshState:
    _maybe_reset_stale_worker()
    with _lock:
        return PropRefreshState(
            in_progress=_state.in_progress,
            started_at=_state.started_at,
            finished_at=_state.finished_at,
            last_error=_state.last_error,
            last_run_id=_state.last_run_id,
            last_details=_state.last_details,
            progress=_state.progress,
        )


def start_background_import() -> bool:
    """Start import thread if idle. Returns False if already running."""
    with _lock:
        if _state.in_progress:
            return False
        _state.in_progress = True
        _state.started_at = datetime.now(UTC)
        _state.finished_at = None
        _state.last_error = None

    def _run() -> None:
        def on_progress(payload: dict) -> None:
            with _lock:
                _state.progress = payload

        try:
            set_import_progress_hook(on_progress)
            with session_scope() as session:
                run = run_unabated_import(session)
            with _lock:
                _state.last_run_id = run.id
                _state.last_details = run.details
                _state.progress = None
                if run.status != "success":
                    _state.last_error = run.error or f"import status {run.status}"
        except Exception as exc:
            logger.exception("Background prop import failed")
            with _lock:
                _state.last_error = str(exc)
                _state.progress = None
        finally:
            set_import_progress_hook(None)
            with _lock:
                _state.in_progress = False
                _state.finished_at = datetime.now(UTC)

    threading.Thread(target=_run, name="prop-odds-import", daemon=True).start()
    return True
