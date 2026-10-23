from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.db import get_db
from app.ml.constants import PREDICTION_CATEGORIES
from app.schemas.prediction import (
    GameOutcomePredictionOut,
    GameWinnerMetricsOut,
    ModelMetricsCategoryOut,
    ModelMetricsOut,
    PlayerStatPredictionOut,
)
from app.services.prediction_service import (
    ModelNotReadyError,
    predict_game_outcome,
    predict_player_stat,
    reload_all_prediction_models,
)

router = APIRouter(tags=["predictions"])
Db = Annotated[Session, Depends(get_db)]


@router.get("/predictions/categories")
def prediction_categories():
    return {"categories": list(PREDICTION_CATEGORIES)}


@router.get("/predictions/metrics", response_model=ModelMetricsOut)
def prediction_metrics():
    from app.ml.artifacts import ModelArtifactsMissingError, load_bundle

    try:
        bundle = load_bundle()
    except ModelArtifactsMissingError as exc:
        raise ModelNotReadyError(str(exc)) from exc
    manifest = bundle.manifest
    cats = [ModelMetricsCategoryOut(**row) for row in bundle.metrics.get("categories", [])]
    return ModelMetricsOut(
        version=bundle.version,
        trained_at=manifest.get("trained_at"),
        categories=cats,
        calibration=bundle.metrics.get("calibration"),
        split_audit=bundle.metrics.get("split_audit"),
    )


@router.get("/predictions/player-stat", response_model=PlayerStatPredictionOut)
def player_stat_prediction(
    db: Db,
    player_id: int,
    game_id: int,
    stat: str = Query(..., description="Category key, e.g. pts_reb_ast"),
    line: Annotated[float, Query(ge=0, le=200)] = 19.5,
):
    return predict_player_stat(db, player_id=player_id, game_id=game_id, category_key=stat, line=line)


@router.get("/predictions/game-outcome", response_model=GameOutcomePredictionOut)
def game_outcome_prediction(db: Db, game_id: int):
    return predict_game_outcome(db, game_id=game_id)


@router.get("/predictions/game-winner/metrics", response_model=GameWinnerMetricsOut)
def game_winner_metrics():
    from app.ml.game_winner.artifacts import GameWinnerArtifactsMissingError, load_game_winner_bundle

    try:
        bundle = load_game_winner_bundle()
    except GameWinnerArtifactsMissingError as exc:
        raise ModelNotReadyError(str(exc)) from exc
    m = bundle.metrics
    return GameWinnerMetricsOut(
        version=bundle.version,
        trained_at=bundle.manifest.get("trained_at"),
        selected_model=m.get("selected_model", bundle.selected_model),
        calibration_enabled=bool(m.get("calibration_enabled", bundle.calibration_enabled)),
        n_train=int(m.get("n_train", 0)),
        n_val=int(m.get("n_val", 0)),
        n_test=int(m.get("n_test", 0)),
        test_start=str(m.get("test_start", "")),
        test_end=str(m.get("test_end", "")),
        test_metrics=m.get("test_metrics", {}),
        validation_log_loss=m.get("validation_log_loss_raw", m.get("validation_log_loss", {})),
        prior_model_baseline_report=m.get("prior_model_baseline_report"),
    )


@router.post("/predictions/reload")
def reload_models():
    """Reload model artifacts from disk (after training)."""
    reload_all_prediction_models()
    return {"status": "ok"}
