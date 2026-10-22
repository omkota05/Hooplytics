from datetime import UTC, date, datetime

import pandas as pd

from app.ml.dataset import add_point_in_time_features


def _row(player_id, day, pts, dnp=False):
    return {
        "player_id": player_id,
        "game_id": day,
        "team_id": 1,
        "opponent_team_id": 2,
        "game_date": date(2099, 1, day),
        "start_time": datetime(2099, 1, day, 23, tzinfo=UTC),
        "season": 2099,
        "season_type": 2,
        "is_home": True,
        "starter": True,
        "did_not_play": dnp,
        "minutes": None if dnp else 30.0,
        "pts": None if dnp else pts,
        "reb": None if dnp else 5,
        "ast": None if dnp else 5,
        "fg3m": None if dnp else 1,
        "stl": None if dnp else 1,
        "blk": None if dnp else 0,
        "tov": None if dnp else 2,
        "fga": None if dnp else 15,
        "fta": None if dnp else 4,
    }


def test_rolling_features_only_use_prior_games():
    frame = pd.DataFrame(
        [_row(1, 1, 10), _row(1, 3, 20), _row(1, 4, 0, dnp=True), _row(1, 6, 30), _row(2, 2, 50)]
    )
    out = add_point_in_time_features(frame)

    p1 = out[out.player_id == 1].reset_index(drop=True)
    assert len(p1) == 3  # DNP rows are not training examples
    assert pd.isna(p1.loc[0, "pts_avg_5"])  # no history before the first game
    assert p1.loc[1, "pts_avg_5"] == 10  # never includes the same game's 20
    assert p1.loc[2, "pts_avg_5"] == 15
    assert list(p1["games_before"]) == [0, 1, 2]
    assert p1.loc[2, "rest_days"] == 3
    assert list(p1["target_pts_reb_ast"]) == [20, 30, 40]

    # Another player's games never leak into this player's features.
    p2 = out[out.player_id == 2].reset_index(drop=True)
    assert pd.isna(p2.loc[0, "pts_avg_5"])
