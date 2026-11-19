"""Predictive distributions from out-of-sample joint residual vectors.

Residual vectors (pts, reb, ast, fg3m) are collected on a validation period the point models
never trained on, grouped into bins of projected PRA. A prediction's distribution is
`round(mean + residual_vector)` clipped at 0 for every stored vector in its bin, so combined
categories are sums of the same simulated component draws and keep their empirical
correlation. No random sampling: the full empirical set is used deterministically.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from app.ml.engine.data import TARGETS, components

N_BINS = 10
MIN_BIN_ROWS = 200


@dataclass
class LineProbabilities:
    p_over: float
    p_under: float
    p_push: float
    n_samples: int


class JointResidualDistribution:
    def __init__(self, edges: np.ndarray, residuals: list[np.ndarray]) -> None:
        self.edges = np.asarray(edges, dtype=float)
        self.residuals = [np.asarray(r, dtype=np.float32) for r in residuals]

    @classmethod
    def fit(cls, pred: np.ndarray, actual: np.ndarray, n_bins: int = N_BINS) -> JointResidualDistribution:
        """`pred` and `actual` are (n, 4) arrays in TARGETS order."""
        key = pred[:, :3].sum(axis=1)
        qs = np.unique(np.quantile(key, np.linspace(0, 1, n_bins + 1)[1:-1]))
        edges = qs
        idx = np.searchsorted(edges, key, side="right")
        res = actual - pred
        bins = [res[idx == b] for b in range(len(edges) + 1)]
        # Merge sparse bins into neighbours so each bin has enough vectors.
        merged_edges, merged_bins = [], []
        acc = np.empty((0, res.shape[1]))
        for b, r in enumerate(bins):
            acc = np.vstack([acc, r])
            if len(acc) >= MIN_BIN_ROWS and b < len(edges):
                merged_bins.append(acc)
                merged_edges.append(edges[b])
                acc = np.empty((0, res.shape[1]))
        if len(acc):
            if merged_bins and len(acc) < MIN_BIN_ROWS:
                merged_bins[-1] = np.vstack([merged_bins[-1], acc])
                merged_edges = merged_edges[:-1]
            else:
                merged_bins.append(acc)
        return cls(np.array(merged_edges), merged_bins)

    def bin_index(self, means: np.ndarray) -> np.ndarray:
        return np.searchsorted(self.edges, means[..., :3].sum(axis=-1), side="right")

    def samples(self, means: np.ndarray) -> np.ndarray:
        """(n_vectors, 4) simulated integer outcomes for one prediction."""
        b = int(self.bin_index(np.asarray(means, dtype=float)))
        return np.clip(np.rint(np.asarray(means, dtype=float) + self.residuals[b]), 0, None)

    def category_samples(self, means: np.ndarray, category: str) -> np.ndarray:
        s = self.samples(means)
        cols = [TARGETS.index(c) for c in components(category)]
        return s[:, cols].sum(axis=1)

    @staticmethod
    def line_probabilities(samples: np.ndarray, line: float) -> LineProbabilities:
        n = len(samples)
        over = int((samples > line).sum())
        under = int((samples < line).sum())
        push = n - over - under
        # Half-count smoothing so a finite sample never yields exactly 0 or 1.
        return LineProbabilities(
            p_over=(over + 0.5) / (n + 1),
            p_under=(under + 0.5) / (n + 1),
            p_push=push / (n + 1),
            n_samples=n,
        )

    @staticmethod
    def summary(samples: np.ndarray) -> dict[str, float]:
        q = np.quantile(samples, [0.1, 0.25, 0.5, 0.75, 0.9])
        return {
            "median": float(q[2]),
            "p10": float(q[0]),
            "p25": float(q[1]),
            "p75": float(q[3]),
            "p90": float(q[4]),
            "sd": float(np.std(samples)),
        }

    def batch_category_samples(self, means: np.ndarray, category: str) -> list[np.ndarray]:
        return [self.category_samples(m, category) for m in means]

    def to_npz(self) -> dict[str, np.ndarray]:
        out: dict[str, np.ndarray] = {"edges": self.edges}
        for i, r in enumerate(self.residuals):
            out[f"bin_{i}"] = r
        return out

    @classmethod
    def from_npz(cls, data) -> JointResidualDistribution:
        n = len([k for k in data.files if k.startswith("bin_")])
        return cls(data["edges"], [data[f"bin_{i}"] for i in range(n)])


def normal_over_probability(mean: float, sd: float, line: float) -> float:
    """Legacy approach (continuous normal, independent of count structure) for comparison only."""
    if sd <= 0:
        return 1.0 if mean > line else 0.0
    z = (line - mean) / sd
    return 0.5 * math.erfc(z / math.sqrt(2))
