from app.services.parlay_scoring import (
    american_to_decimal,
    combination_score,
    indicative_parlay_decimal,
    margin_component,
    minutes_stability_component,
    score_leg,
    wilson_from_hits,
)
from app.analytics.wilson import wilson_lower_bound


def test_wilson_from_hits():
    assert wilson_from_hits(9, 10) == wilson_lower_bound(9, 10)
    assert wilson_from_hits(1, 1) < 100.0


def test_combination_score_weights_minimum():
    consistency, mn, avg = combination_score([90.0, 88.0, 40.0])
    assert mn == 40.0
    assert consistency < avg


def test_margin_over_under():
    assert margin_component("over", 25.0, 20.5) > margin_component("under", 25.0, 20.5)


def test_minutes_stability():
    assert minutes_stability_component(32.0, 33.0) > minutes_stability_component(32.0, 20.0)


def test_indicative_decimal_odds():
    dec = indicative_parlay_decimal([-110, -110])
    assert dec is not None
    assert dec > 1.0


def test_american_to_decimal():
    assert american_to_decimal(100) == 2.0
    assert round(american_to_decimal(-110), 2) == 1.91


def test_score_leg_bounded():
    leg = score_leg(
        pick_side="over",
        line=20.5,
        historical_avg=24.0,
        primary_window="l10",
        primary_hit_pct=80.0,
        primary_wilson=65.0,
        primary_hits=8,
        primary_attempts=10,
        l20_hit_pct=75.0,
        l20_wilson=60.0,
        l20_hits=15,
        l20_attempts=20,
        h2h_wilson=55.0,
        h2h_attempts=5,
        l5_minutes=34.0,
        l20_minutes=32.0,
    )
    assert 0 <= leg.total <= 100


def test_one_of_one_wilson_not_perfect():
    assert wilson_from_hits(1, 1) < 100.0
