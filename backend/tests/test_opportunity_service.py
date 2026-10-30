from datetime import date
from types import SimpleNamespace

from app.analytics.lines import classify, evaluate_line
from app.analytics.wilson import wilson_lower_bound
from app.services.opportunity_service import _averages_for_games, _mean
from app.services.prop_hit_ranking import window_side_stats


def _stat(**kwargs):
    defaults = {
        "minutes": 30.0,
        "fga": 15,
        "fg3a": 5,
        "did_not_play": False,
        "game_date": date(2099, 1, 1),
        "season": 2099,
        "season_type": 2,
    }
    defaults.update(kwargs)
    return SimpleNamespace(**defaults)


def test_mean_ignores_missing():
    assert _mean([10.0, None, 20.0]) == 15.0
    assert _mean([None, None]) is None


def test_l5_l10_l20_averages():
    games = [_stat(minutes=35, fga=20, fg3a=8) for _ in range(5)]
    games += [_stat(minutes=25, fga=10, fg3a=2) for _ in range(15)]
    l5 = _averages_for_games(games[:5])
    l20 = _averages_for_games(games[:20])
    assert l5.games == 5
    assert l5.minutes == 35.0
    assert l20.minutes == 27.5


def test_limited_history_does_not_fake_samples():
    w = {
        "games": 2,
        "over_hits": 2,
        "under_hits": 0,
        "pushes": 0,
        "over_hit_pct": 100.0,
        "under_hit_pct": 0.0,
    }
    s = window_side_stats(w, "over")
    assert s["attempts"] == 2
    assert s["games"] == 2


def test_push_handling_hit_rate():
    result = evaluate_line([21, 20, 19], 20.0)
    assert result.push == 1
    decided = result.over + result.under
    assert decided == 2
    s = window_side_stats(
        {
            "games": 3,
            "over_hits": result.over,
            "under_hits": result.under,
            "pushes": result.push,
            "over_hit_pct": 50.0,
            "under_hit_pct": 50.0,
        },
        "over",
    )
    assert s["attempts"] == 2


def test_wilson_one_of_one_below_raw():
    assert wilson_lower_bound(1, 1) < 100.0


def test_line_propagation_classify():
    assert classify(21.0, 20.5) == "over"
    assert classify(20.0, 20.5) == "under"
    assert classify(20.0, 20.0) == "push"


def test_combined_stat_line():
    values = [30, 20]
    line = 25.5
    outcomes = [classify(v, line) for v in values]
    assert outcomes == ["over", "under"]
