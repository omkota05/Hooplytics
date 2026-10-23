import numpy as np

from app.ml.probability import (
    brier_score,
    combine_component_variance,
    estimate_std_from_residuals,
    line_probabilities,
)


def test_combined_variance_uses_covariance_not_independence():
    cov = np.array([[4.0, 2.0, 0.0], [2.0, 3.0, 0.0], [0.0, 0.0, 1.0]])
    var = combine_component_variance({}, {}, cov, ["pts", "reb", "ast"], "pts_reb_ast")
    assert var == 12.0  # 4+3+1 + 2*2 + 2*2 cross terms for pts/reb/ast


def test_line_probabilities_sum_to_one():
    p_over, p_under, p_push = line_probabilities(22.0, 5.0, 19.5)
    assert abs(p_over + p_under + p_push - 1.0) < 1e-9
    assert p_push == 0.0


def test_brier_score_perfect_and_worst():
    y = np.array([1.0, 0.0, 1.0])
    assert brier_score(y, y) == 0.0
    assert brier_score(np.array([0.0, 0.0, 0.0]), y) == 2 / 3


def test_single_component_std_floor():
    std = estimate_std_from_residuals({"pts": 0.1}, np.array([[1.0]]), ["pts"], "pts")
    assert std >= 0.5
