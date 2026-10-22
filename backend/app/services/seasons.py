from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Game
from app.sync.state import get_state


def current_season(session: Session) -> int | None:
    """Season reported by the provider at last sync, else the latest season we have."""
    state = get_state(session, "current_season", {})
    if state.get("season"):
        return int(state["season"])
    return session.scalar(select(func.max(Game.season)))
