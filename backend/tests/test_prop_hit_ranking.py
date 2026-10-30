from app.analytics.wilson import wilson_lower_bound
from app.services.prop_hit_ranking import effective_min_games, window_side_stats


def test_effective_min_games_caps_by_window():
    assert effective_min_games(20, "l5") == 5
    assert effective_min_games(20, "l10") == 10
    assert effective_min_games(20, "l20") == 20
    assert effective_min_games(5, "wilson_l10") == 5


def test_window_side_stats_one_of_one():
    w = {
        "window": "L10",
        "games": 1,
        "over_hits": 1,
        "under_hits": 0,
        "pushes": 0,
        "over_hit_pct": 100.0,
        "under_hit_pct": 0.0,
    }
    s = window_side_stats(w, "over")
    assert s["hits"] == 1
    assert s["attempts"] == 1
    assert s["games"] == 1
    assert s["hit_pct"] == 100.0
    assert s["wilson_lb"] is not None
    assert s["wilson_lb"] < 100.0


def test_window_side_stats_nine_of_ten():
    w = {
        "games": 10,
        "over_hits": 9,
        "under_hits": 1,
        "pushes": 0,
        "over_hit_pct": 90.0,
        "under_hit_pct": 10.0,
    }
    s = window_side_stats(w, "over")
    assert s["hits"] == 9
    assert s["attempts"] == 10
    lb = wilson_lower_bound(9, 10)
    assert s["wilson_lb"] == lb
    assert s["wilson_lb"] > wilson_lower_bound(1, 1)


def test_window_side_stats_eighteen_of_twenty():
    w = {"games": 20, "over_hits": 18, "under_hits": 2, "pushes": 0, "over_hit_pct": 90.0, "under_hit_pct": 10.0}
    s = window_side_stats(w, "over")
    assert s["hits"] == 18
    assert s["attempts"] == 20
    assert s["games"] == 20


def test_window_side_stats_five_of_five():
    w = {"games": 5, "over_hits": 5, "under_hits": 0, "pushes": 0, "over_hit_pct": 100.0, "under_hit_pct": 0.0}
    s = window_side_stats(w, "over")
    assert s["hits"] == 5
    assert s["attempts"] == 5


def test_window_side_stats_pushes_excluded_from_attempts():
    w = {
        "games": 4,
        "over_hits": 1,
        "under_hits": 1,
        "pushes": 2,
        "over_hit_pct": 50.0,
        "under_hit_pct": 50.0,
    }
    s = window_side_stats(w, "under")
    assert s["attempts"] == 2
    assert s["hits"] == 1
    assert s["hit_pct"] == 50.0


def test_window_side_stats_missing_window():
    s = window_side_stats(None, "over")
    assert s["hits"] is None
    assert s["attempts"] is None
    assert s["games"] == 0
    assert s["hit_pct"] is None
    assert s["wilson_lb"] is None
