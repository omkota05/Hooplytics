import pandas as pd

from app.ml.game_winner.features import (
    DEFAULT_REST_DAYS,
    build_game_feature_frame,
    build_pregame_features,
    add_derived_columns,
)


def _row(gid, t, home, away, hs, as_, season=2024):
    return {
        "id": gid,
        "season": season,
        "season_type": 2,
        "start_time": pd.Timestamp(t, tz="UTC"),
        "game_date": pd.Timestamp(t).normalize(),
        "home_team_id": home,
        "away_team_id": away,
        "home_score": hs,
        "away_score": as_,
        "neutral_site": False,
        "home_win": int(hs > as_),
    }


def test_offseason_rest_uses_default_not_hundreds_of_days():
    games = pd.DataFrame(
        [
            _row(1, "2024-06-01", 10, 20, 110, 100, season=2024),
            _row(2, "2024-10-15", 10, 30, 105, 100, season=2025),
        ]
    )
    frame = build_game_feature_frame(games)
    assert frame.iloc[1]["away_rest_days"] == DEFAULT_REST_DAYS
    assert frame.iloc[1]["home_rest_days"] == DEFAULT_REST_DAYS


def test_pregame_offseason_rest_matches_training_frame():
    completed = pd.DataFrame([_row(1, "2024-06-01", 10, 20, 110, 100, season=2024)])
    pre = build_pregame_features(
        completed,
        home_team_id=10,
        away_team_id=30,
        season=2025,
        season_type=2,
        game_date=pd.Timestamp("2024-10-15"),
        start_time=pd.Timestamp("2024-10-15T19:00:00Z"),
        neutral_site=False,
        game_id=99,
    )
    assert pre.iloc[0]["away_rest_days"] == DEFAULT_REST_DAYS


def test_no_future_leakage_in_feature_row():
    games = pd.DataFrame(
        [
            _row(1, "2024-01-01", 10, 20, 110, 100),
            _row(2, "2024-01-02", 10, 20, 99, 120),
        ]
    )
    frame = build_game_feature_frame(games)
    assert frame.iloc[1]["home_win_pct_l5"] == 1.0
    assert frame.iloc[0]["games_before_home"] == 0
