import pandas as pd

from app.ml.game_winner.features import build_game_feature_frame, split_chronological


def _game_row(gid, t, home, away, hs, as_, season=2024):
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


def test_features_do_not_use_same_game_outcome():
    games = pd.DataFrame(
        [
            _game_row(1, "2024-01-01", 10, 20, 110, 100),
            _game_row(2, "2024-01-02", 10, 30, 95, 105),
        ]
    )
    frame = build_game_feature_frame(games)
    row2 = frame.iloc[1]
    assert row2["games_before_home"] == 1
    assert row2["home_win_pct_l5"] == 1.0


def test_chronological_split_by_kickoff():
    games = pd.DataFrame(
        [
            _game_row(i, f"2024-01-{i:02d}", 1, 2, 100, 90)
            for i in range(1, 21)
        ]
    )
    frame = build_game_feature_frame(games)
    train, val, test = split_chronological(frame)
    assert train["start_time"].max() <= val["start_time"].min()
    assert val["start_time"].max() <= test["start_time"].min()


def test_season_boundary_resets_season_win_pct():
    games = pd.DataFrame(
        [
            _game_row(1, "2024-06-01", 10, 20, 110, 100, season=2024),
            _game_row(2, "2024-10-01", 10, 20, 110, 100, season=2025),
        ]
    )
    frame = build_game_feature_frame(games)
    row2 = frame.iloc[1]
    assert row2["home_win_pct_season"] == 0.5
