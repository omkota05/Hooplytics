"""Recommendation prop probabilities must stay plausible (not isotonic clip artifacts)."""

import numpy as np
import pytest

from app.db import session_scope
from app.ml.calibration import apply_isotonic
from app.ml.inference import get_prediction_engine
from app.ml.probability import line_probabilities
from app.services.prediction_service import predict_player_stat
from app.services.recommendation_service import (
    clear_recommendation_cache,
    filter_recommendations,
    generate_recommendations,
)


def test_recommendation_probs_not_saturated_for_near_mean_lines():
    clear_recommendation_cache()
    with session_scope() as session:
        bundle = generate_recommendations(session, days=3, expand_player_props=False)
        props = filter_recommendations(bundle, min_probability=0.55).player_props
        assert props, "expected model-backed props from synced DB"
        saturated = [p for p in props if p.model_probability >= 0.999 or p.model_probability <= 0.001]
        assert len(saturated) < len(props) * 0.5, (
            f"too many saturated picks ({len(saturated)}/{len(props)}); "
            "check isotonic extrapolation at inference"
        )
        engine = get_prediction_engine()
        for p in props:
            if p.model_probability >= 0.999:
                continue
            raw_o, _, _ = line_probabilities(p.predicted_mean, p.predicted_std_dev, p.line)
            iso = engine.bundle.isotonic_calibrators.get(p.category)
            if iso is None:
                continue
            cal_o = float(apply_isotonic(iso, np.array([raw_o]))[0])
            pred = predict_player_stat(
                session,
                player_id=p.player.id,
                game_id=p.game.id,
                category_key=p.category,
                line=p.line,
            )
            assert pred.p_over == pytest.approx(p.p_over, abs=1e-3)
            assert pred.p_under == pytest.approx(p.p_under, abs=1e-3)
            pick_prob = p.p_over if p.pick_side == "over" else p.p_under
            assert p.model_probability == pick_prob
            if raw_o < float(iso.X_min_) or raw_o > float(iso.X_max_):
                assert cal_o == pytest.approx(raw_o)
            return
        pytest.skip("all sampled props still saturated; narrow sample")


def test_pick_side_uses_higher_of_over_under():
    with session_scope() as session:
        bundle = generate_recommendations(session, days=3, expand_player_props=False)
        for p in bundle.player_props[:50]:
            if p.p_over is None or p.p_under is None:
                continue
            expected_side = "over" if p.p_over >= p.p_under else "under"
            expected_prob = max(p.p_over, p.p_under)
            assert p.pick_side == expected_side
            assert p.model_probability == pytest.approx(expected_prob, abs=1e-4)
