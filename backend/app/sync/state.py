from typing import Any

from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.models import SyncState


def get_state(session: Session, key: str, default: Any = None) -> Any:
    row = session.get(SyncState, key)
    return row.value if row is not None else default


def set_state(session: Session, key: str, value: dict) -> None:
    stmt = insert(SyncState).values(key=key, value=value)
    stmt = stmt.on_conflict_do_update(
        index_elements=[SyncState.key], set_={"value": stmt.excluded.value, "updated_at": func.now()}
    )
    session.execute(stmt)
