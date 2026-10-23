from datetime import UTC, date, datetime

import pandas as pd

from app.ml.features import enrich_player_game_frame


def _row(player_id, day, pts, opp=2, season=2099):
    return {
        "player_id": player_id,
        "game_id": 1000 + day,
        "team_id": 1,
        "opponent_team_id": opp,
        "game_date": date(2099, 1, day),
        "start_time": datetime(2099, 1, day, 23, tzinfo=UTC),
        "season": season,
        "season_type": 2,
        "is_home": True,
        "starter": True,
        "did_not_play": False,
        "minutes": 30.0,
        "pts": pts,
        "reb": 5,
        "ast": 4,
        "fg3m": 1,
        "stl": 1,
        "blk": 0,
        "tov": 2,
        "fga": 15,
        "fta": 4,
    }


def test_season_average_excludes_current_game():
    frame = pd.DataFrame([_row(1, 1, 10), _row(1, 2, 30), _row(1, 3, 20)])
    out = enrich_player_game_frame(frame)
    p = out.sort_values("game_date").reset_index(drop=True)
    assert pd.isna(p.loc[0, "pts_season_avg"])
    assert p.loc[1, "pts_season_avg"] == 10
    assert p.loc[2, "pts_season_avg"] == 20


def test_head_to_head_only_uses_same_opponent_history():
    frame = pd.DataFrame([_row(1, 1, 10, opp=2), _row(1, 2, 40, opp=3), _row(1, 3, 20, opp=2)])
    out = enrich_player_game_frame(frame).sort_values("game_date").reset_index(drop=True)
    assert pd.isna(out.loc[0, "pts_h2h_avg"])
    assert out.loc[2, "pts_h2h_avg"] == 10
