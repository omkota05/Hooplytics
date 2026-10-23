"""Prepared inference must match per-category line_probability_row."""

import numpy as np
import pandas as pd
import pytest

from app.ml.constants import PREDICTION_CATEGORIES
from app.ml.inference import get_prediction_engine


@pytest.fixture
def sample_row():
    engine = get_prediction_engine()
    data = {c: [0.0] for c in engine.bundle.feature_columns}
    data["games_before"] = [12]
    data["start_time"] = [pd.Timestamp("2026-10-22T23:00:00Z")]
    return pd.DataFrame(data)


def test_prepared_line_probability_matches_row_path(sample_row):
    engine = get_prediction_engine()
    row = sample_row
    prepared = engine.prepare_player_game(row, player_id=1, game_id=99)
    for cat in PREDICTION_CATEGORIES:
        line = 19.5
        direct = engine.line_probability_row(row, cat, line, player_id=1, game_id=99)
        batched = engine.line_probability_prepared(prepared, cat, line)
        assert abs(direct.projection.mean - batched.projection.mean) < 1e-5
        assert abs(direct.projection.std_dev - batched.projection.std_dev) < 1e-5
        if direct.p_over is not None and batched.p_over is not None:
            assert abs(direct.p_over - batched.p_over) < 1e-6
