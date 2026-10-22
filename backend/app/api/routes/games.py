from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db import get_db
from app.schemas.common import GameOut, TeamOut
from app.schemas.games import GameDetailOut, TopPerformerOut
from app.services import game_service

router = APIRouter(tags=["games"])
Db = Annotated[Session, Depends(get_db)]


@router.get("/games/upcoming", response_model=list[GameOut])
def upcoming_games(db: Db, days: Annotated[int, Query(ge=1, le=30)] = 7, team_id: int | None = None):
    return game_service.upcoming(db, days, team_id)


@router.get("/games/recent", response_model=list[GameOut])
def recent_games(db: Db, days: Annotated[int, Query(ge=1, le=14)] = 1):
    """Completed games from the most recent day(s) with synced box scores."""
    return game_service.recent(db, days)


@router.get("/games/top-performers", response_model=list[TopPerformerOut])
def top_performers(db: Db, limit: Annotated[int, Query(ge=1, le=25)] = 8):
    return game_service.top_performers(db, limit)


@router.get("/games/{game_id}", response_model=GameDetailOut)
def game_detail(db: Db, game_id: int):
    return game_service.detail(db, game_id)


@router.get("/teams", response_model=list[TeamOut])
def teams(db: Db):
    return game_service.teams(db)
