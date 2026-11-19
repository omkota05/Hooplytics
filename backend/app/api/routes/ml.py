from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db import get_db
from app.schemas.ml import (
    ComparisonOut,
    ModelStatusOut,
    PlayerProjectionOut,
    PropEstimateOut,
    UpcomingProjectionsOut,
)
from app.services import ml_engine_service as svc

router = APIRouter(prefix="/ml", tags=["ml"])
Db = Annotated[Session, Depends(get_db)]


@router.get("/status", response_model=ModelStatusOut)
def ml_status(db: Db):
    """Model readiness, validation gates, data freshness, and the odds-archive size."""
    return svc.status(db)


@router.get("/prospective")
def ml_prospective(db: Db):
    """Read-only summary of the immutable pregame forecast archive (never triggers a forecast run)."""
    from app.services.forecast_archive_service import forecast_summary

    return forecast_summary(db)


@router.get("/metrics")
def ml_metrics():
    """Held-out evaluation: test MAE/RMSE vs baselines, slices, calibration, archived real lines."""
    return svc.metrics_summary()


@router.get("/projections/upcoming", response_model=UpcomingProjectionsOut)
def ml_upcoming(
    db: Db,
    team_id: int | None = None,
    q: Annotated[str | None, Query(max_length=60)] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
):
    """Batch projections for every active player's next scheduled game (cached per data snapshot)."""
    return svc.upcoming(db, team_id=team_id, limit=limit, q=q)


@router.get("/projections/player/{player_id}", response_model=PlayerProjectionOut)
def ml_player_projection(db: Db, player_id: int, game_id: int | None = None):
    """Component and combined-stat projections with predictive intervals for one upcoming game."""
    return svc.player_projection(db, player_id, game_id)


@router.get("/projections/prop", response_model=PropEstimateOut)
def ml_prop_estimate(
    db: Db,
    player_id: int,
    game_id: int,
    category: str,
    line: Annotated[float, Query(ge=0, le=200)],
):
    """Distributional estimate at a line. Probabilities are null unless the category passes its gate."""
    return svc.prop_estimate(db, player_id=player_id, game_id=game_id, category=category, line=line)


@router.get("/comparison", response_model=ComparisonOut)
def ml_comparison(
    db: Db,
    sportsbook: str | None = None,
    prizepicks_only: bool = False,
    category: str | None = None,
    game_date: date | None = None,
    q: Annotated[str | None, Query(max_length=60)] = None,
    side: Annotated[str | None, Query(pattern="^(over|under)$")] = None,
    min_sample: Annotated[int, Query(ge=0, le=200)] = 0,
    eligible_only: bool = False,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
):
    """Real imported sportsbook lines vs model projections (Recommended page)."""
    return svc.comparison(
        db,
        sportsbook=sportsbook,
        prizepicks_only=prizepicks_only,
        category=category,
        game_date=game_date,
        player_query=q,
        side=side,
        min_sample=min_sample,
        eligible_only=eligible_only,
        limit=limit,
    )
