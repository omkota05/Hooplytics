from typing import Annotated

from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.orm import Session

from app.db import get_db
from app.schemas.sync import SyncStatusOut
from app.services.sync_status import get_sync_status

router = APIRouter(prefix="/sync", tags=["sync"])
Db = Annotated[Session, Depends(get_db)]


@router.get("/status", response_model=SyncStatusOut)
def sync_status(db: Db, request: Request):
    scheduler = request.app.state.scheduler
    return get_sync_status(db, scheduler_enabled=scheduler.enabled, next_run_at=scheduler.next_run_at)


@router.post("/run", status_code=status.HTTP_202_ACCEPTED)
def trigger_sync(request: Request):
    """Queue an incremental sync in the background."""
    request.app.state.scheduler.run_once_in_background()
    return {"queued": True}
