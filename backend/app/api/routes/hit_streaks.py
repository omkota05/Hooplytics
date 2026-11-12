from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db import get_db
from app.schemas.hit_streaks import HitStreakListOut
from app.services.hit_streaks_service import list_hit_streaks

router = APIRouter(prefix="/hit-streaks", tags=["hit-streaks"])


@router.get("", response_model=HitStreakListOut)
def hit_streaks_list(
    category: str | None = None,
    pick_side: str | None = Query(None, pattern="^(over|under)$"),
    game_date: str | None = None,
    min_streak: int = Query(1, ge=1, le=50),
    current_season_only: bool = False,
    sort: str = Query("streak", pattern="^(streak|hcs|clearance|l10_hit_pct)$"),
    limit: int = Query(100, ge=1, le=100),
    offset: int = Query(0, ge=0),
    session: Session = Depends(get_db),
):
    return list_hit_streaks(
        session,
        category=category,
        pick_side=pick_side,
        game_date=game_date,
        min_streak=min_streak,
        current_season_only=current_season_only,
        sort=sort,
        limit=limit,
        offset=offset,
    )
