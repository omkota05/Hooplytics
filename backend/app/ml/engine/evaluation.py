"""Regression metrics, slice reports, and probabilistic calibration metrics."""

from __future__ import annotations

import math

import numpy as np
import pandas as pd

from app.ml.engine.data import ALL_CATEGORIES, TARGETS, components
from app.ml.engine.distribution import JointResidualDistribution, normal_over_probability

EPS = 1e-6


def regression_metrics(y: np.ndarray, p: np.ndarray) -> dict[str, float]:
    e = p - y
    return {
        "n": int(len(y)),
        "mae": float(np.mean(np.abs(e))),
        "rmse": float(np.sqrt(np.mean(e**2))),
        "median_ae": float(np.median(np.abs(e))),
        "bias": float(np.mean(e)),
    }


def pct_improvement(base: float, new: float) -> float:
    return float((base - new) / base * 100.0) if base else 0.0


def _tier(series: pd.Series, bins: list[float], labels: list[str]) -> pd.Series:
    return pd.cut(series, bins=bins, labels=labels, right=False).astype(str)


def slice_report(frame: pd.DataFrame, y: np.ndarray, p: np.ndarray) -> dict[str, dict]:
    df = frame.assign(_y=y, _p=p, _ae=np.abs(p - y), _e=p - y)

    def agg(key: pd.Series) -> dict:
        g = df.groupby(key.values)
        return {
            str(k): {"n": int(len(v)), "mae": float(v["_ae"].mean()), "bias": float(v["_e"].mean())}
            for k, v in g
        }

    mins = df["minutes_l10"].fillna(0)
    return {
        "season": agg(df["season"]),
        "season_type": agg(df["season_type"].map({2: "regular", 3: "playoffs", 5: "play_in"}).fillna("other")),
        "home_away": agg(df["is_home"].map({True: "home", False: "away"})),
        "usage_tier_minutes_l10": agg(_tier(mins, [0, 15, 25, 32, 100], ["<15", "15-25", "25-32", "32+"])),
        "minutes_high_low": agg(pd.Series(np.where(mins >= 28, "high_28plus", np.where(mins < 20, "low_under20", "mid")))),
        "history_appearances": agg(_tier(df["appearances"], [0, 10, 30, 80, 10_000], ["3-9", "10-29", "30-79", "80+"])),
        "opponent": agg(df["opponent_team_id"]),
        "month": agg(df["start_time"].dt.strftime("%Y-%m")),
    }


def reliability_bins(p: np.ndarray, y: np.ndarray, n_bins: int = 10) -> list[dict]:
    edges = np.linspace(0, 1, n_bins + 1)
    idx = np.clip(np.digitize(p, edges[1:-1]), 0, n_bins - 1)
    out = []
    for b in range(n_bins):
        m = idx == b
        if m.sum() == 0:
            continue
        out.append(
            {
                "bin_start": float(edges[b]),
                "bin_end": float(edges[b + 1]),
                "predicted_mean": float(p[m].mean()),
                "observed_rate": float(y[m].mean()),
                "count": int(m.sum()),
            }
        )
    return out


def prob_metrics(p: np.ndarray, y: np.ndarray) -> dict:
    p = np.asarray(p, dtype=float)
    y = np.asarray(y, dtype=float)
    pc = np.clip(p, EPS, 1 - EPS)
    bins = reliability_bins(p, y)
    n = len(p)
    ece = sum(b["count"] / n * abs(b["predicted_mean"] - b["observed_rate"]) for b in bins) if n else float("nan")
    return {
        "n": int(n),
        "brier": float(np.mean((p - y) ** 2)) if n else float("nan"),
        "log_loss": float(-np.mean(y * np.log(pc) + (1 - y) * np.log(1 - pc))) if n else float("nan"),
        "ece": float(ece),
        "mean_predicted": float(p.mean()) if n else float("nan"),
        "observed_rate": float(y.mean()) if n else float("nan"),
        "share_below_5pct_or_above_95pct": float(np.mean((p < 0.05) | (p > 0.95))) if n else float("nan"),
        "reliability": bins,
    }


def vectorized_category_probs(
    dist: JointResidualDistribution, means: np.ndarray, category: str, lines: np.ndarray
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Return p_over, p_under, p_push, q10, q90 for many rows at once."""
    cols = [TARGETS.index(c) for c in components(category)]
    n = len(means)
    p_over = np.zeros(n)
    p_under = np.zeros(n)
    p_push = np.zeros(n)
    q10 = np.zeros(n)
    q90 = np.zeros(n)
    bidx = dist.bin_index(means)
    for b, res in enumerate(dist.residuals):
        rows = np.where(bidx == b)[0]
        for start in range(0, len(rows), 2000):
            r = rows[start : start + 2000]
            sims = np.clip(np.rint(means[r][:, None, :] + res[None, :, :]), 0, None)[:, :, cols].sum(axis=2)
            line = lines[r][:, None]
            k = sims.shape[1]
            over = (sims > line).sum(axis=1)
            under = (sims < line).sum(axis=1)
            p_over[r] = (over + 0.5) / (k + 1)
            p_under[r] = (under + 0.5) / (k + 1)
            p_push[r] = (k - over - under) / (k + 1)
            q10[r] = np.quantile(sims, 0.1, axis=1)
            q90[r] = np.quantile(sims, 0.9, axis=1)
    return p_over, p_under, p_push, q10, q90


def vectorized_category_quantiles(
    dist: JointResidualDistribution, means: np.ndarray, category: str, qs: tuple[float, ...]
) -> np.ndarray:
    """(n, len(qs)) quantiles of the simulated category outcome for many rows at once."""
    cols = [TARGETS.index(c) for c in components(category)]
    out = np.zeros((len(means), len(qs)))
    bidx = dist.bin_index(means)
    for b, res in enumerate(dist.residuals):
        rows = np.where(bidx == b)[0]
        for start in range(0, len(rows), 2000):
            r = rows[start : start + 2000]
            sims = np.clip(np.rint(means[r][:, None, :] + res[None, :, :]), 0, None)[:, :, cols].sum(axis=2)
            out[r] = np.quantile(sims, qs, axis=1).T
    return out


def category_values(frame_or_preds: pd.DataFrame, category: str, prefix: str) -> np.ndarray:
    return sum(frame_or_preds[f"{prefix}{c}"].to_numpy(dtype=float) for c in components(category))


def synthetic_threshold_eval(
    frame: pd.DataFrame,
    pred_means: np.ndarray,
    dist: JointResidualDistribution,
    normal_sd: dict[str, float],
    climatology: dict[str, float] | None = None,
) -> dict:
    """Score over/under forecasts at thresholds derived only from pregame features.

    SYNTHETIC: threshold = floor(sum of component L10 averages) + 0.5. Integer thresholds
    (round of the same average) are also scored to check push handling. This measures the
    quality of the predictive distribution; it is *not* a sportsbook backtest.
    """
    out: dict[str, dict] = {}
    for cat in ALL_CATEGORIES:
        l10 = sum(frame[f"{c}_l10"].to_numpy(dtype=float) for c in components(cat))
        actual = sum(frame[f"target_{c}"].to_numpy(dtype=float) for c in components(cat))
        ok = np.isfinite(l10) & np.isfinite(actual)
        means = pred_means[ok]
        a = actual[ok]
        half = np.floor(l10[ok]) + 0.5
        p_over, _, _, q10, q90 = vectorized_category_probs(dist, means, cat, half)
        y = (a > half).astype(float)
        cat_mean = sum(means[:, TARGETS.index(c)] for c in components(cat))
        p_norm = np.array([normal_over_probability(m, normal_sd[cat], ln) for m, ln in zip(cat_mean, half, strict=False)])
        base_rate = (climatology or {}).get(cat, float(y.mean()))
        integer = np.rint(l10[ok])
        po_i, pu_i, pp_i, _, _ = vectorized_category_probs(dist, means, cat, integer)
        push_actual = (a == integer).astype(float)
        out[cat] = {
            "threshold_scheme": "floor(L10 component-sum average) + 0.5 (synthetic, pregame-only)",
            "empirical_joint": prob_metrics(p_over, y),
            "normal_legacy": prob_metrics(p_norm, y),
            "climatology_constant": {"p": base_rate, **{k: v for k, v in prob_metrics(np.full(len(y), base_rate), y).items() if k != "reliability"}},
            "interval_80_coverage": float(np.mean((a >= q10) & (a <= q90))),
            "interval_80_mean_width": float(np.mean(q90 - q10)),
            "integer_line_push": {
                "mean_predicted_push": float(pp_i.mean()),
                "observed_push_rate": float(push_actual.mean()),
                "probabilities_sum_to_one_max_error": float(np.max(np.abs(po_i + pu_i + pp_i - 1))),
            },
        }
    return out


def american_to_prob(odds: float | None) -> float | None:
    if odds is None or (isinstance(odds, float) and math.isnan(odds)) or odds == 0:
        return None
    return 100.0 / (odds + 100.0) if odds > 0 else -odds / (-odds + 100.0)
