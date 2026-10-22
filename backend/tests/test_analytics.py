from dataclasses import dataclass
from datetime import date

import pytest

from app.analytics.categories import CATEGORIES, UnknownCategoryError, get_category, stat_value
from app.analytics.lines import (
    InvalidLineError,
    classify,
    evaluate_line,
    is_small_sample,
    summarize,
)
from app.analytics.windows import (
    GameWindow,
    InvalidWindowError,
    apply_window,
    filter_opponent,
    played_games,
    select_games,
)


@dataclass
class FakeGame:
    game_date: date
    season: int
    opponent_team_id: int
    did_not_play: bool = False
    pts: int | None = 0
    reb: int | None = 0
    ast: int | None = 0
    stl: int | None = 0
    blk: int | None = 0
    tov: int | None = 0
    fg3m: int | None = 0


# --------------------------------------------------------------- categories


def test_combined_categories_sum_components():
    g = FakeGame(date(2099, 1, 1), 2099, 1, pts=25, reb=10, ast=7, stl=2, blk=3)
    assert stat_value(g, get_category("pts_reb_ast")) == 42
    assert stat_value(g, get_category("pts_reb")) == 35
    assert stat_value(g, get_category("pts_ast")) == 32
    assert stat_value(g, get_category("reb_ast")) == 17
    assert stat_value(g, get_category("stl_blk")) == 5
    assert stat_value({"pts": 12}, get_category("pts")) == 12


def test_combined_category_is_none_when_component_missing():
    g = FakeGame(date(2099, 1, 1), 2099, 1, pts=25, reb=None)
    assert stat_value(g, get_category("pts_reb")) is None
    assert stat_value(g, get_category("pts")) == 25


def test_all_required_categories_exist():
    expected = {
        "pts",
        "reb",
        "ast",
        "fg3m",
        "stl",
        "blk",
        "tov",
        "pts_reb",
        "pts_ast",
        "reb_ast",
        "pts_reb_ast",
        "stl_blk",
    }
    assert set(CATEGORIES) == expected
    assert get_category("pts_reb_ast").is_combined
    assert not get_category("fg3m").is_combined


def test_unknown_category():
    with pytest.raises(UnknownCategoryError):
        get_category("dunks")


# --------------------------------------------------------------- lines


def test_classify():
    assert classify(21, 20.5) == "over"
    assert classify(20, 20.5) == "under"
    assert classify(20, 20) == "push"


def test_evaluate_line_counts_and_consistent_denominators():
    result = evaluate_line([25, 20, 18, 20, 30], line=20)
    assert (result.over, result.under, result.push, result.total) == (2, 1, 2, 5)
    # All headline percentages share the same denominator: every analyzed game.
    assert result.over_pct == 40.0
    assert result.under_pct == 20.0
    assert result.push_pct == 40.0
    assert result.over_pct + result.under_pct + result.push_pct == 100.0
    # The decided-games rate is reported separately.
    assert result.over_pct_excluding_pushes == pytest.approx(66.7)


def test_evaluate_line_half_point_has_no_pushes():
    result = evaluate_line([10, 11, 12], line=10.5)
    assert result.push == 0 and result.over == 2 and result.under == 1


def test_evaluate_line_empty():
    result = evaluate_line([], 10.5)
    assert result.total == 0 and result.over_pct is None and result.over_pct_excluding_pushes is None


@pytest.mark.parametrize("bad", [-1, 201, float("nan"), float("inf")])
def test_invalid_line(bad):
    with pytest.raises(InvalidLineError):
        evaluate_line([1, 2], bad)


def test_summarize():
    d = summarize([10, 20, 30, 40])
    assert d.count == 4
    assert d.mean == 25
    assert d.median == 25
    assert d.std_dev == pytest.approx(12.91, abs=0.01)  # sample std dev
    assert (d.minimum, d.maximum) == (10, 40)


def test_summarize_single_and_empty():
    assert summarize([7]).std_dev is None
    assert summarize([]).mean is None
    assert is_small_sample(4) and not is_small_sample(5)


# --------------------------------------------------------------- windows


def _games():
    # 2 seasons, newest last; one DNP; opponents 1/2 alternate.
    return [
        FakeGame(date(2098, 3, 1), 2098, 1, pts=10),
        FakeGame(date(2098, 3, 3), 2098, 2, pts=11),
        FakeGame(date(2098, 11, 1), 2099, 1, pts=12),
        FakeGame(date(2098, 11, 3), 2099, 2, pts=13, did_not_play=True),
        FakeGame(date(2098, 11, 5), 2099, 1, pts=14),
        FakeGame(date(2098, 11, 7), 2099, 2, pts=15),
    ]


def test_last_n_is_most_recent_first_and_skips_dnp():
    selected = select_games(_games(), GameWindow(kind="last_n", n=3))
    assert [g.pts for g in selected] == [15, 14, 12]


def test_last_n_larger_than_history():
    assert len(select_games(_games(), GameWindow(kind="last_n", n=30))) == 5


def test_season_window():
    selected = select_games(_games(), GameWindow(kind="season", season=2098))
    assert [g.pts for g in selected] == [11, 10]


def test_date_range_is_inclusive():
    w = GameWindow(kind="date_range", start_date=date(2098, 3, 3), end_date=date(2098, 11, 5))
    assert [g.pts for g in select_games(_games(), w)] == [14, 12, 11]


def test_all_window_input_order_does_not_matter():
    shuffled = list(reversed(_games()))
    assert [g.pts for g in apply_window(shuffled, GameWindow(kind="all"))] == [15, 14, 13, 12, 11, 10]


def test_opponent_filter_spans_seasons():
    vs_one = select_games(_games(), GameWindow(kind="all"), opponent_team_id=1)
    assert [g.pts for g in vs_one] == [14, 12, 10]
    assert {g.season for g in vs_one} == {2098, 2099}
    last_two = select_games(_games(), GameWindow(kind="last_n", n=2), opponent_team_id=1)
    assert [g.pts for g in last_two] == [14, 12]


def test_opponent_filter_none_and_unknown():
    assert len(filter_opponent(_games(), None)) == 6
    assert select_games(_games(), GameWindow(kind="all"), opponent_team_id=99) == []
    assert len(played_games(_games())) == 5


@pytest.mark.parametrize(
    "kwargs",
    [
        {"kind": "last_n"},
        {"kind": "last_n", "n": 0},
        {"kind": "season"},
        {"kind": "date_range", "start_date": date(2099, 1, 2)},
        {"kind": "date_range", "start_date": date(2099, 1, 2), "end_date": date(2099, 1, 1)},
    ],
)
def test_invalid_windows(kwargs):
    with pytest.raises(InvalidWindowError):
        GameWindow(**kwargs)
