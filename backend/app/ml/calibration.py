"""Pregame line definitions and probability calibration (validation-fit, test-eval)."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Literal

import numpy as np
import pandas as pd
from sklearn.isotonic import IsotonicRegression

from app.ml.constants import components_for_category
from app.ml.probability import brier_score, line_probabilities, reliability_bins

LineScheme = Literal["pregame_model_half", "pregame_prior_l10_half", "pregame_prior_season_half"]

LINE_SCHEME_DOCS: dict[LineScheme, str] = {
    "pregame_model_half": "floor(pregame_model_mean) + 0.5 — half-point line from the model mean only",
    "pregame_prior_l10_half": "floor(sum of component last-10 rolling averages from features) + 0.5",
    "pregame_prior_season_half": "floor(sum of component season-to-date averages from features) + 0.5",
}


def synthetic_line_from_mean(pregame_mean: float) -> float:
    """Standard synthetic half-point line from a pregame point estimate (no outcome data)."""
    mu = float(pregame_mean)
    if not math.isfinite(mu):
        return 0.5
    return math.floor(mu) + 0.5


def synthetic_line_from_prior_row(row: pd.Series, category: str, scheme: LineScheme) -> float:
    comps = components_for_category(category)
    if scheme == "pregame_prior_l10_half":
        parts = [float(row.get(f"{c}_avg_10") or 0.0) for c in comps]
    elif scheme == "pregame_prior_season_half":
        parts = [float(row.get(f"{c}_season_avg") or 0.0) for c in comps]
    else:
        raise ValueError(scheme)
    for i, p in enumerate(parts):
        if not math.isfinite(p):
            parts[i] = 0.0
    return synthetic_line_from_mean(sum(parts))


def actual_over(actual: float, line: float) -> float:
    if actual > line:
        return 1.0
    if actual < line:
        return 0.0
    return 0.5  # integer-line push (rare with half-point synthetic lines)


@dataclass
class CalibrationEval:
    line_scheme: str
    n_samples: int
    n_skipped_low_history: int
    brier_raw: float | None
    brier_calibrated: float | None
    mean_predicted_p_over: float | None
    observed_over_rate: float | None
    reliability_raw: list[dict]
    reliability_calibrated: list[dict]


def raw_probabilities(
    pregame_means: np.ndarray,
    std_dev: float,
    lines: np.ndarray,
) -> np.ndarray:
    probs = []
    for mu, line in zip(pregame_means, lines, strict=True):
        p_over, _, _ = line_probabilities(float(mu), std_dev, float(line))
        probs.append(p_over)
    return np.array(probs, dtype=float)


def fit_isotonic(prob_over: np.ndarray, outcomes: np.ndarray) -> IsotonicRegression | None:
    if len(prob_over) < 50:
        return None
    if len(np.unique(outcomes)) < 2:
        return None
    reg = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0)
    reg.fit(prob_over, outcomes)
    return reg


def serialize_isotonic(reg: IsotonicRegression | None) -> dict[str, Any] | None:
    if reg is None:
        return None
    return {
        "x_thresholds": [float(x) for x in reg.X_thresholds_],
        "y_thresholds": [float(y) for y in reg.y_thresholds_],
    }


def deserialize_isotonic(data: dict[str, Any] | None) -> IsotonicRegression | None:
    if not data:
        return None
    x = np.array(data["x_thresholds"], dtype=float)
    y = np.array(data["y_thresholds"], dtype=float)
    if len(x) < 2:
        return None
    reg = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0)
    reg.fit(x, y)
    return reg


def apply_isotonic(reg: IsotonicRegression | None, prob_over: np.ndarray) -> np.ndarray:
    """Calibrate in-bounds probabilities; leave out-of-support values unchanged.

    Isotonic models are fit on validation rows where synthetic pregame lines keep
    raw over probabilities in a narrow band. Clipping extrapolation to 0/1 at
    inference (custom lines, L10 half-point props) produced false 0% / 100%.
    """
    if reg is None:
        return prob_over
    p = np.asarray(prob_over, dtype=float)
    if p.size == 0:
        return p
    x_min = float(reg.X_min_)
    x_max = float(reg.X_max_)
    out = p.copy()
    in_bounds = (p >= x_min) & (p <= x_max)
    if np.any(in_bounds):
        out[in_bounds] = reg.predict(p[in_bounds])
    return out


def high_probability_audit(prob_home_win: np.ndarray, home_won: np.ndarray) -> dict[str, Any]:
    """Summarize calibration for high-confidence home-win predictions."""
    p = np.asarray(prob_home_win, dtype=float)
    y = np.asarray(home_won, dtype=float)
    out: dict[str, Any] = {}
    for thr in (0.8, 0.9):
        mask = p >= thr
        n = int(mask.sum())
        out[f"p_home_gte_{int(thr * 100)}"] = {
            "count": n,
            "mean_predicted": float(p[mask].mean()) if n else None,
            "observed_home_win_rate": float(y[mask].mean()) if n else None,
        }
    return out


def evaluate_split(
    frame: pd.DataFrame,
    *,
    category: str,
    pregame_means: np.ndarray,
    std_dev: float,
    line_scheme: LineScheme,
    min_games_before: int,
    isotonic: IsotonicRegression | None = None,
) -> CalibrationEval:
    """Evaluate normal (and optional isotonic) probabilities on one chronological split."""
    y_col = f"target_{category}"
    actuals = frame[y_col].to_numpy(dtype=float)
    games_before = frame["games_before"].to_numpy(dtype=int)
    mask = games_before >= min_games_before
    n_skipped = int((~mask).sum())

    if line_scheme == "pregame_model_half":
        lines = np.array([synthetic_line_from_mean(m) for m in pregame_means])
    else:
        lines = frame.apply(
            lambda r: synthetic_line_from_prior_row(r, category, line_scheme), axis=1
        ).to_numpy()

    lines = lines[mask]
    means = pregame_means[mask]
    actuals = actuals[mask]
    if len(actuals) == 0:
        return CalibrationEval(
            line_scheme=line_scheme,
            n_samples=0,
            n_skipped_low_history=n_skipped,
            brier_raw=None,
            brier_calibrated=None,
            mean_predicted_p_over=None,
            observed_over_rate=None,
            reliability_raw=[],
            reliability_calibrated=[],
        )

    outcomes = np.array([actual_over(a, line) for a, line in zip(actuals, lines, strict=True)])
    raw = raw_probabilities(means, std_dev, lines)
    cal = apply_isotonic(isotonic, raw)
    return CalibrationEval(
        line_scheme=line_scheme,
        n_samples=int(len(actuals)),
        n_skipped_low_history=n_skipped,
        brier_raw=brier_score(raw, outcomes),
        brier_calibrated=brier_score(cal, outcomes) if isotonic is not None else None,
        mean_predicted_p_over=float(np.mean(raw)),
        observed_over_rate=float(np.mean(outcomes)),
        reliability_raw=reliability_bins(raw, outcomes),
        reliability_calibrated=reliability_bins(cal, outcomes) if isotonic is not None else [],
    )


def build_calibration_report(
    *,
    val_frame: pd.DataFrame,
    test_frame: pd.DataFrame,
    category: str,
    val_pregame_means: np.ndarray,
    test_pregame_means: np.ndarray,
    std_dev: float,
    min_games_before: int = 8,
    primary_line_scheme: LineScheme = "pregame_model_half",
) -> tuple[dict[str, Any], IsotonicRegression | None]:
    """Fit isotonic on validation (pregame lines only), report test metrics."""
    val_eval_primary = evaluate_split(
        val_frame,
        category=category,
        pregame_means=val_pregame_means,
        std_dev=std_dev,
        line_scheme=primary_line_scheme,
        min_games_before=min_games_before,
    )
    val_mask = val_frame["games_before"].to_numpy(dtype=int) >= min_games_before
    val_lines = np.array([synthetic_line_from_mean(m) for m in val_pregame_means])[val_mask]
    val_actuals = val_frame[f"target_{category}"].to_numpy(dtype=float)[val_mask]
    val_outcomes = np.array([actual_over(a, line) for a, line in zip(val_actuals, val_lines, strict=True)])
    val_raw = raw_probabilities(val_pregame_means[val_mask], std_dev, val_lines)
    iso = fit_isotonic(val_raw, val_outcomes)
    if iso is not None:
        val_cal = apply_isotonic(iso, val_raw)
        if brier_score(val_cal, val_outcomes) >= brier_score(val_raw, val_outcomes):
            iso = None

    test_eval_model = evaluate_split(
        test_frame,
        category=category,
        pregame_means=test_pregame_means,
        std_dev=std_dev,
        line_scheme="pregame_model_half",
        min_games_before=min_games_before,
        isotonic=iso,
    )
    test_eval_prior_l10 = evaluate_split(
        test_frame,
        category=category,
        pregame_means=test_pregame_means,
        std_dev=std_dev,
        line_scheme="pregame_prior_l10_half",
        min_games_before=min_games_before,
        isotonic=iso,
    )

    report = {
        "category": category,
        "primary_line_scheme": primary_line_scheme,
        "line_scheme_documentation": LINE_SCHEME_DOCS,
        "min_games_before": min_games_before,
        "distribution_assumption": "Gaussian predictive distribution (normal CDF)",
        "isotonic_fitted_on": "validation_split_only",
        "validation": {
            "n_samples": val_eval_primary.n_samples,
            "brier_raw_normal": val_eval_primary.brier_raw,
            "observed_over_rate": val_eval_primary.observed_over_rate,
        },
        "test": {
            "pregame_model_half": _eval_to_dict(test_eval_model),
            "pregame_prior_l10_half": _eval_to_dict(test_eval_prior_l10),
        },
        "limitations": [
            "Lines are synthetic pregame estimates, not historical sportsbook prices.",
            "Normal approximation may mis-calibrate tails for discrete counting stats.",
            "Isotonic calibration is fit on the validation window only; test is untouched for fitting.",
            "Team/opponent features use shift(1) by start_time; split boundaries use kickoff time.",
        ],
    }
    return report, iso


def _eval_to_dict(ev: CalibrationEval) -> dict[str, Any]:
    return {
        "line_scheme": ev.line_scheme,
        "n_samples": ev.n_samples,
        "n_skipped_low_history": ev.n_skipped_low_history,
        "brier_raw_normal": ev.brier_raw,
        "brier_isotonic_calibrated": ev.brier_calibrated,
        "mean_predicted_p_over": ev.mean_predicted_p_over,
        "observed_over_rate": ev.observed_over_rate,
        "reliability_raw": ev.reliability_raw,
        "reliability_calibrated": ev.reliability_calibrated,
    }
