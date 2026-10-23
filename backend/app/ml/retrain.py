"""Helpers for deciding when to retrain models after new games sync."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.ml.artifacts import active_version, bundle_dir
from app.models import Game, PlayerGameStat

DEFAULT_RETRAIN_GAME_THRESHOLD = 150


def games_since_training(session: Session) -> int | None:
    version = active_version()
    if not version:
        return None
    manifest_path = bundle_dir(version) / "manifest.json"
    if not manifest_path.exists():
        return None
    import json

    manifest = json.loads(manifest_path.read_text())
    trained_at = manifest.get("trained_at")
    if not trained_at:
        return None
    last_train_date = session.scalar(
        select(func.max(PlayerGameStat.game_date)).where(PlayerGameStat.did_not_play.is_(False))
    )
    if last_train_date is None:
        return 0
    # Count final games with box scores synced after the training timestamp's calendar day.
    from datetime import datetime

    trained_day = datetime.fromisoformat(trained_at.replace("Z", "+00:00")).date()
    return (
        session.scalar(
            select(func.count(func.distinct(PlayerGameStat.game_id)))
            .join(Game, Game.id == PlayerGameStat.game_id)
            .where(
                Game.status == "final",
                Game.boxscore_synced_at.is_not(None),
                PlayerGameStat.game_date > trained_day,
            )
        )
        or 0
    )


def should_retrain(session: Session, threshold: int = DEFAULT_RETRAIN_GAME_THRESHOLD) -> bool:
    added = games_since_training(session)
    return added is not None and added >= threshold
