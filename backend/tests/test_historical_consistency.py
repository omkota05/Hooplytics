"""Unit tests for Historical Consistency Score (HCS) v2 and Parlay Consistency Score (PCS) v2."""

import math

import pytest

from app.analytics.hcs_settings import DEFAULT_HCS, DEFAULT_PCS, HCS_VERSION
from app.analytics.historical_consistency import (
    compute_hcs,
    cushion_tilt,
    kish_effective_sample_size,
    minute_tilt,
    outcome_indicator,
    recency_weights,
    recency_wilson_lower_bound,
)
from app.services.parlay_scoring import legacy_score_leg, parlay_consistency_score


def test_recency_weights_gamma_v2():
    w = recency_weights(5, gamma=0.045)
    assert w[0] > w[1] > w[2]
    assert math.isclose(w[0], 1.0)


def test_kish_effective_sample_size():
    uniform = [1.0, 1.0, 1.0, 1.0]
    assert math.isclose(kish_effective_sample_size(uniform), 4.0)


def test_over_under_push_indicators():
    assert outcome_indicator(25, 20.5, "over", push_value=0.5)[0] == 1.0
    assert outcome_indicator(20, 20.0, "over", push_value=0.5)[0] == 0.5
    assert outcome_indicator(18, 20.5, "under", push_value=0.5)[0] == 1.0


def test_eighteen_of_twenty_beats_nine_of_ten():
    line = 20.5
    stats20 = [22.0] * 18 + [18.0, 17.0]
    stats10 = [22.0] * 9 + [18.0]
    mins = [32.0] * 20
    b20 = compute_hcs(
        stat_values_recent_first=stats20,
        minutes_recent_first=mins,
        line=line,
        pick_side="over",
        analysis_window="L20",
        window_size=20,
    )
    b10 = compute_hcs(
        stat_values_recent_first=stats10,
        minutes_recent_first=mins[:10],
        line=line,
        pick_side="over",
        analysis_window="L10",
        window_size=10,
    )
    assert b20.hcs > b10.hcs
    assert b20.version == HCS_VERSION


def test_hcs_additive_composition():
    stats = [24.0] * 15
    mins = [32.0] * 15
    bd = compute_hcs(
        stat_values_recent_first=stats,
        minutes_recent_first=mins,
        line=20.5,
        pick_side="over",
        analysis_window="L15",
        window_size=15,
    )
    w_rec = bd.component_historical
    # Recover tilts from total (stored rounded)
    implied_tilts = bd.hcs - w_rec
    assert -15 <= implied_tilts <= 15


def test_cushion_tilt_symmetry_under_over():
    values = [18.0, 20.0, 22.0, 24.0, 26.0]
    line = 20.0
    t_over, _, med, _, _ = cushion_tilt(values, line, "over", DEFAULT_HCS)
    t_under, _, _, _, _ = cushion_tilt(values, line, "under", DEFAULT_HCS)
    assert math.isclose(t_over, -t_under, abs_tol=1e-6)
    assert med == 22.0


def test_minute_trend_symmetry():
    mins = [36.0, 35.0, 34.0, 33.0, 32.0, 31.0, 30.0, 29.0, 28.0, 27.0]
    t_over, trend_o, _, _, _, _, _ = minute_tilt(mins, "over", DEFAULT_HCS)
    t_under, trend_u, _, _, _, _, _ = minute_tilt(mins, "under", DEFAULT_HCS)
    assert math.isclose(trend_o, -trend_u, abs_tol=1e-6)


def test_floor_penalty_over_only():
    # Low M15 relative to M20 triggers floor on overs only
    mins = [30.0, 30.0, 30.0, 30.0, 30.0, 10.0, 10.0, 10.0, 10.0, 10.0]
    t_over, _, p_over, _, _, _, _ = minute_tilt(mins, "over", DEFAULT_HCS)
    t_under, _, p_under, _, _, _, _ = minute_tilt(mins, "under", DEFAULT_HCS)
    assert p_over > 0.0
    assert p_under == 0.0


def test_recency_wilson_monotone_in_sample():
    low = recency_wilson_lower_bound(0.9, 3.0, z=1.15)
    high = recency_wilson_lower_bound(0.9, 12.0, z=1.15)
    assert high > low


def test_pcs_weak_leg_penalty():
    weak = parlay_consistency_score([95, 95, 45], length_decay=DEFAULT_PCS.length_decay)
    even = parlay_consistency_score([80, 80, 80], length_decay=DEFAULT_PCS.length_decay)
    assert weak.pcs < even.pcs


def test_pcs_formula_exact_three_legs():
    legs = [90.0, 90.0, 90.0]
    h = [max(x, 1.0) for x in legs]
    gmean = math.prod(h) ** (1 / 3)
    expected = (0.65 * gmean + 0.35 * min(h)) * 0.97
    bd = parlay_consistency_score(legs, length_decay=0.97)
    assert math.isclose(bd.pcs, expected, abs_tol=0.01)


def test_pcs_length_decay_five_legs():
    three = parlay_consistency_score([90, 90, 90], length_decay=0.97)
    five = parlay_consistency_score([90, 90, 90, 90, 90], length_decay=0.97)
    assert five.pcs < three.pcs


def test_legacy_blend_differs_from_v2():
    legacy = legacy_score_leg(
        pick_side="over",
        line=20.5,
        historical_avg=24.0,
        primary_window="l10",
        primary_hit_pct=90.0,
        primary_wilson=65.0,
        primary_hits=9,
        primary_attempts=10,
        l20_hit_pct=90.0,
        l20_wilson=70.0,
        l20_hits=18,
        l20_attempts=20,
        h2h_wilson=55.0,
        h2h_attempts=5,
        l5_minutes=34.0,
        l20_minutes=32.0,
    )
    stats = [22.0] * 9 + [18.0]
    mins = [34.0] * 10
    new = compute_hcs(
        stat_values_recent_first=stats,
        minutes_recent_first=mins,
        line=20.5,
        pick_side="over",
        analysis_window="L10",
        window_size=10,
    )
    assert legacy.total != new.hcs
