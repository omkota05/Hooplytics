import math

import numpy as np
import pandas as pd
import pytest

from app.ml.calibration import (
    apply_isotonic,
    build_calibration_report,
    evaluate_split,
    fit_isotonic,
    synthetic_line_from_mean,
)
from app.ml.probability import brier_score
from app.ml.features import split_chronological


def test_pregame_line_does_not_use_actual_outcome():
    actual = 42.0
    pregame_mu = 18.3
    line = synthetic_line_from_mean(pregame_mu)
    assert line == math.floor(pregame_mu) + 0.5
    assert line != math.floor(actual) + 0.5


def test_apply_isotonic_does_not_extrapolate_outside_support():
    raw = np.linspace(0.47, 0.53, 60)
    outcomes = (raw > 0.5).astype(float)
    iso = fit_isotonic(raw, outcomes)
    assert iso is not None
    probe = np.array([0.35, 0.50, 0.65, 0.736, 0.85])
    calibrated = apply_isotonic(iso, probe)
    assert calibrated[0] == pytest.approx(0.35)
    assert calibrated[2] == pytest.approx(0.65)
    assert calibrated[3] == pytest.approx(0.736)
    assert calibrated[4] == pytest.approx(0.85)


def test_isotonic_fit_only_on_provided_split():
    # Deliberately overconfident raw probs
    raw = np.array([0.9, 0.9, 0.1, 0.1, 0.5, 0.5] * 20)
    outcomes = np.array([1, 0, 0, 1, 1, 0] * 20, dtype=float)
    iso = fit_isotonic(raw, outcomes)
    assert iso is not None
    calibrated = iso.predict(raw)
    assert calibrated.min() >= 0.0 and calibrated.max() <= 1.0


def test_split_by_kickoff_separates_same_calendar_day():
    rows = []
    for hour in range(12):
        rows.append(
            {
                "start_time": pd.Timestamp(f"2099-06-15 {hour:02d}:00:00Z"),
                "game_date": pd.Timestamp("2099-06-15"),
                "player_id": 1,
                "game_id": 100 + hour,
            }
        )
    frame = pd.DataFrame(rows).assign(
        games_before=1, target_pts=1.0, team_id=1, opponent_team_id=2
    )
    train, val, test = split_chronological(frame)
    # Same calendar day but different kickoffs can land in different folds.
    assert len(train) + len(val) + len(test) == 12
    assert train.iloc[0]["game_id"] == 100
    assert test.iloc[-1]["game_id"] == 111


def test_calibration_report_uses_pregame_lines_only():
    n = 200
    frame = pd.DataFrame(
        {
            "target_pts": np.random.default_rng(0).integers(5, 40, n),
            "games_before": np.full(n, 10),
            "pts_avg_10": np.linspace(10, 30, n),
            "pts_season_avg": np.linspace(10, 30, n),
        }
    )
    val = frame.iloc[:100].copy()
    test = frame.iloc[100:].copy()
    means_val = np.linspace(12, 28, len(val))
    means_test = np.linspace(12, 28, len(test))
    report, iso = build_calibration_report(
        val_frame=val,
        test_frame=test,
        category="pts",
        val_pregame_means=means_val,
        test_pregame_means=means_test,
        std_dev=5.0,
        min_games_before=8,
    )
    assert iso is not None
    primary = report["test"]["pregame_model_half"]
    assert primary["n_samples"] == len(test)
    assert primary["brier_raw_normal"] is not None
    assert "floor(pregame_model_mean)" in report["line_scheme_documentation"]["pregame_model_half"]


def test_evaluate_split_outcomes_match_lines():
    frame = pd.DataFrame({"target_pts": [30.0, 10.0], "games_before": [10, 10]})
    ev = evaluate_split(
        frame,
        category="pts",
        pregame_means=np.array([20.0, 20.0]),
        std_dev=5.0,
        line_scheme="pregame_model_half",
        min_games_before=8,
    )
    # line = 20.5 for both
    assert ev.observed_over_rate == 0.5
