from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db import get_db
from app.schemas.analysis import StatCategoryOut
from app.schemas.explorer import TrendExplorerOut
from app.services import analysis_service, explorer_service

router = APIRouter(tags=["stats"])
Db = Annotated[Session, Depends(get_db)]


@router.get("/stats/categories", response_model=list[StatCategoryOut])
def categories():
    return analysis_service.list_categories()


@router.get("/explorer/trends", response_model=TrendExplorerOut)
def trend_explorer(
    db: Db,
    stat: str = "pts",
    line: Annotated[float, Query(ge=0, le=200)] = 19.5,
    last_n: Annotated[int, Query(ge=3, le=50)] = 10,
    min_games: Annotated[int, Query(ge=1, le=50)] = 5,
    days: Annotated[int, Query(ge=1, le=7)] = 1,
    sort: Literal["over_pct", "under_pct", "mean", "consistency"] = "over_pct",
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
):
    return explorer_service.trends(
        db,
        category_key=stat,
        line=line,
        last_n=last_n,
        min_games=min(min_games, last_n),
        days=days,
        sort=sort,
        limit=limit,
    )
