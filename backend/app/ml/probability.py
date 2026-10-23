"""Predictive uncertainty and over/under probabilities."""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from scipy import stats

from app.ml.constants import components_for_category


@dataclass(frozen=True)
class DistributionEstimate:
    mean: float
    std_dev: float
    status: str  # available | experimental | unavailable


def combine_component_means(means: dict[str, float], category_key: str) -> float:
    comps = components_for_category(category_key)
    return float(sum(means[c] for c in comps))


def combine_component_variance(
    means: dict[str, float],
    stds: dict[str, float],
    covariance: np.ndarray,
    component_order: list[str],
    category_key: str,
) -> float:
    """Variance of a linear combination using residual covariance (not independence)."""
    comps = components_for_category(category_key)
    idx = [component_order.index(c) for c in comps]
    sub = covariance[np.ix_(idx, idx)]
    w = np.ones(len(comps))
    return float(w @ sub @ w)


def estimate_std_from_residuals(
    residual_std: dict[str, float],
    covariance: np.ndarray,
    component_order: list[str],
    category_key: str,
) -> float:
    comps = components_for_category(category_key)
    if len(comps) == 1:
        return max(residual_std.get(comps[0], 1.0), 0.5)
    var = combine_component_variance(
        {c: 0.0 for c in comps},
        {c: residual_std.get(c, 1.0) for c in comps},
        covariance,
        component_order,
        category_key,
    )
    return max(math.sqrt(var), 0.5)


def line_probabilities(
    mean: float,
    std_dev: float,
    line: float,
    *,
    min_std: float = 0.5,
) -> tuple[float, float, float]:
    """Normal approximation for a half-point line (push probability ~ 0)."""
    sigma = max(std_dev, min_std)
    if line == math.floor(line):
        # Integer line: discrete push mass from normal approximation is negligible; keep 0.
        p_push = 0.0
        p_under = stats.norm.cdf(line, loc=mean, scale=sigma)
        p_over = 1.0 - p_under
    else:
        p_push = 0.0
        p_over = 1.0 - stats.norm.cdf(line, loc=mean, scale=sigma)
        p_under = 1.0 - p_over
    return float(p_over), float(p_under), float(p_push)


def brier_score(prob_over: np.ndarray, actual_over: np.ndarray) -> float:
    return float(np.mean((prob_over - actual_over) ** 2))


def reliability_bins(prob_over: np.ndarray, actual_over: np.ndarray, bins: int = 10) -> list[dict]:
    edges = np.linspace(0, 1, bins + 1)
    out = []
    for i in range(bins):
        mask = (prob_over >= edges[i]) & (prob_over < edges[i + 1])
        if not np.any(mask):
            continue
        out.append(
            {
                "bin_start": float(edges[i]),
                "bin_end": float(edges[i + 1]),
                "predicted_mean": float(np.mean(prob_over[mask])),
                "observed_rate": float(np.mean(actual_over[mask])),
                "count": int(mask.sum()),
            }
        )
    return out
