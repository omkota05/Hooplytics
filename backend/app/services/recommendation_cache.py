"""Shared recommendation cache and background warm after data sync."""

from __future__ import annotations

import logging
import threading
import time

from app.db import session_scope
from app.services.recommendation_service import clear_recommendation_cache, generate_recommendations

logger = logging.getLogger("hooplytics")

_warm_lock = threading.Lock()
_warm_in_progress = False

DEFAULT_WARM_DAYS = 7


def warm_recommendations_async(days: int = DEFAULT_WARM_DAYS) -> None:
    """Precompute recommendations after sync (non-blocking)."""
    global _warm_in_progress
    with _warm_lock:
        if _warm_in_progress:
            return
        _warm_in_progress = True

    def _run() -> None:
        global _warm_in_progress
        try:
            t0 = time.perf_counter()
            clear_recommendation_cache()
            with session_scope() as session:
                out = generate_recommendations(session, days=days, expand_player_props=False)
            elapsed = time.perf_counter() - t0
            logger.info(
                "Warmed recommendation cache: %d props, %d games in %.1fs",
                out.meta.player_props_generated,
                out.meta.upcoming_games_scanned,
                elapsed,
            )
        except Exception:
            logger.exception("Recommendation cache warm failed")
        finally:
            with _warm_lock:
                _warm_in_progress = False

    threading.Thread(target=_run, name="hooplytics-rec-warm", daemon=True).start()
