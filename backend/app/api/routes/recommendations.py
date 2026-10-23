from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db import get_db
from app.schemas.prediction import PlayerStatPredictionOut
from app.schemas.recommendations import RecommendationsOut
from app.services.prediction_service import predict_player_stat
from app.services.recommendation_service import filter_recommendations, generate_recommendations

router = APIRouter(tags=["recommendations"])
Db = Annotated[Session, Depends(get_db)]


@router.get("/recommendations", response_model=RecommendationsOut)
def list_recommendations(
    db: Db,
    days: Annotated[int, Query(ge=1, le=14)] = 7,
    expand_player_props: bool = False,
    game_id: int | None = None,
    team_id: int | None = None,
    category: str | None = None,
    side: Annotated[str | None, Query(pattern="^(over|under)$")] = None,
    min_probability: Annotated[float | None, Query(ge=0.5, le=0.99)] = None,
    q: str | None = None,
    game_date: date | None = None,
    sort: Annotated[str, Query(pattern="^(probability|time|player)$")] = "probability",
):
    bundle = generate_recommendations(db, days=days, expand_player_props=expand_player_props)
    return filter_recommendations(
        bundle,
        game_id=game_id,
        team_id=team_id,
        category=category,
        side=side,
        min_probability=min_probability,
        player_query=q,
        game_date=game_date,
        sort=sort,
    )


@router.get("/recommendations/player-prop", response_model=PlayerStatPredictionOut)
def recommendation_custom_player_prop(
    db: Db,
    player_id: int,
    game_id: int,
    category: str,
    line: Annotated[float, Query(ge=0, le=200)],
):
    """Custom-line ML prediction (sportsbook lines not available)."""
    return predict_player_stat(db, player_id=player_id, game_id=game_id, category_key=category, line=line)
