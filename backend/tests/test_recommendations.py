import math
from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest

from app.ml.calibration import synthetic_line_from_mean
from app.services.recommendation_service import clear_recommendation_cache, filter_recommendations
from app.schemas.recommendations import (
    GameWinnerRecommendationOut,
    HistoricalWindowHitOut,
    PlayerPropRecommendationOut,
    RecommendationsMetaOut,
    RecommendationsOut,
)
from app.schemas.common import GameOut, PlayerSummaryOut, TeamOut
from app.schemas.prediction import GameOutcomeFactorsOut


def _team(tid: int, abbr: str) -> TeamOut:
    return TeamOut(
        id=tid,
        abbreviation=abbr,
        display_name=abbr,
        short_name=abbr,
        location="X",
        color=None,
        alternate_color=None,
        logo_url=None,
    )


def _game(gid: int) -> GameOut:
    home, away = _team(1, "HOM"), _team(2, "AWY")
    return GameOut(
        id=gid,
        season=2027,
        season_label="2026-27",
        season_type=2,
        season_type_label="Regular Season",
        start_time=datetime.now(UTC),
        game_date=datetime.now(UTC).date(),
        status="scheduled",
        status_detail=None,
        home_team=home,
        away_team=away,
        home_score=None,
        away_score=None,
        venue_name=None,
        venue_city=None,
        venue_state=None,
        neutral_site=False,
    )


def _prop(player_id: int, game_id: int, prob: float, side: str = "over") -> PlayerPropRecommendationOut:
    return PlayerPropRecommendationOut(
        player=PlayerSummaryOut(
            id=player_id,
            full_name=f"Player {player_id}",
            position="G",
            jersey="1",
            headshot_url=None,
            is_active=True,
            team=_team(1, "HOM"),
        ),
        opponent=_team(2, "AWY"),
        game=_game(game_id),
        category="pts",
        category_label="Points",
        line=19.5,
        line_source="synthetic_l10_half",
        predicted_mean=22.0,
        predicted_std_dev=5.0,
        pick_side=side,
        model_probability=prob,
        p_over=prob if side == "over" else 1 - prob,
        p_under=1 - prob if side == "over" else prob,
        probability_status="available",
        games_used=10,
        historical_hit_rates=[
            HistoricalWindowHitOut(window="L10", games=10, over_pct=0.5, under_pct=0.5, small_sample=False)
        ],
        model_version="test",
        player_analysis_href="/players/1",
    )


def test_synthetic_line_from_mean_half_point():
    assert synthetic_line_from_mean(20.2) == 20.5
    assert synthetic_line_from_mean(19.9) == 19.5


def test_filter_sort_and_min_probability():
    bundle = RecommendationsOut(
        meta=RecommendationsMetaOut(
            generated_at=datetime.now(UTC),
            player_model_version="v",
            game_winner_model_version="g",
            upcoming_games_scanned=1,
            player_props_generated=2,
            game_winners_generated=0,
            data_sync_reference=None,
            disclaimer="test",
        ),
        player_props=[_prop(1, 10, 0.7), _prop(2, 10, 0.55)],
        game_winners=[],
        categories=["pts"],
    )
    out = filter_recommendations(bundle, min_probability=0.6)
    assert len(out.player_props) == 1
    assert out.player_props[0].model_probability == 0.7


def test_probabilities_valid_in_props():
    p = _prop(1, 1, 0.62, "under")
    assert math.isclose(p.p_over + p.p_under, 1.0, abs_tol=1e-6)


def test_clear_cache():
    clear_recommendation_cache()
