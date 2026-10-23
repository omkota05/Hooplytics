from datetime import UTC, datetime
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from app.db import get_db
from app.main import app
from app.schemas.prediction import PlayerStatPredictionOut


@pytest.fixture
def client(session_factory):
    def override():
        with session_factory() as s:
            yield s

    app.dependency_overrides[get_db] = override
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_prediction_endpoint_returns_payload(client):
    fake = PlayerStatPredictionOut(
        player_id=1,
        player_name="Test Player",
        game_id=99,
        opponent_team_id=2,
        category="pts",
        category_label="Points",
        line=19.5,
        predicted_mean=21.0,
        predicted_std_dev=5.0,
        p_over=0.55,
        p_under=0.45,
        p_push=0.0,
        probability_status="available",
        historical_hit_rate=None,
        model_version="test",
        selected_model_summary="pts:xgboost",
        predicted_at=datetime.now(UTC),
    )
    with patch("app.api.routes.predictions.predict_player_stat", return_value=fake):
        r = client.get(
            "/api/predictions/player-stat",
            params={"player_id": 1, "game_id": 99, "stat": "pts", "line": 19.5},
        )
    assert r.status_code == 200
    body = r.json()
    assert body["predicted_mean"] == 21.0
    assert body["p_over"] == 0.55


def test_game_outcome_endpoint_returns_payload(client):
    from app.schemas.prediction import GameOutcomeFactorsOut, GameOutcomePredictionOut

    fake = GameOutcomePredictionOut(
        game_id=99,
        home_team_id=1,
        away_team_id=2,
        home_team_name="Home",
        away_team_name="Away",
        start_time=datetime.now(UTC),
        home_win_probability=0.58,
        away_win_probability=0.42,
        model_home_win_probability_raw=0.57,
        calibration_applied=False,
        selected_model="elo",
        model_version="test",
        probability_status="available",
        predicted_at=datetime.now(UTC),
        factors=GameOutcomeFactorsOut(
            home_elo=1510.0,
            away_elo=1490.0,
            elo_home_win_prob=0.55,
            home_win_pct_season=0.6,
            away_win_pct_season=0.4,
            home_rest_days=2.0,
            away_rest_days=1.0,
            home_b2b=False,
            away_b2b=True,
            h2h_home_win_pct=0.5,
            neutral_site=False,
        ),
    )
    with patch("app.api.routes.predictions.predict_game_outcome", return_value=fake):
        r = client.get("/api/predictions/game-outcome", params={"game_id": 99})
    assert r.status_code == 200
    body = r.json()
    assert abs(body["home_win_probability"] + body["away_win_probability"] - 1.0) < 1e-6


def test_metrics_endpoint_503_without_models(client):
    from app.ml.artifacts import ModelArtifactsMissingError

    with patch("app.ml.artifacts.load_bundle", side_effect=ModelArtifactsMissingError("missing")):
        r = client.get("/api/predictions/metrics")
    assert r.status_code == 503
