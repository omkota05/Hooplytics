import numpy as np
import pandas as pd
import pytest

from app.ml.engine.data import validate_and_clean
from app.ml.engine.features import FEATURE_SETS, REST_CAP_DAYS, LeakageError, build_features
from tests.ml_engine_factory import make_raw

ALL_FEATURES = sorted(set(FEATURE_SETS["full"]))


@pytest.fixture(scope="module")
def clean():
    df, rep = validate_and_clean(make_raw())
    return df


@pytest.fixture(scope="module")
def feats(clean):
    return build_features(clean)


def _row(feats, player_id, nth):
    return feats[(feats["player_id"] == player_id) & feats["appeared"]].iloc[nth]


def test_current_and_future_stats_do_not_change_features(clean, feats):
    target = feats[(feats["player_id"] == 201) & feats["appeared"]].iloc[20]
    poisoned = clean.copy()
    later = (poisoned["start_time"] >= target["start_time"])
    # Corrupt the target game and every later game for every player (incl. opponents).
    for c in ("pts", "reb", "ast", "fg3m", "minutes", "fga", "fg3a", "fta", "oreb", "tov"):
        poisoned.loc[later, c] = poisoned.loc[later, c] * 3 + 50
    again = build_features(poisoned)
    row = again[(again["player_id"] == 201) & (again["game_id"] == target["game_id"])].iloc[0]
    for col in ALL_FEATURES:
        a, b = target[col], row[col]
        assert (pd.isna(a) and pd.isna(b)) or a == pytest.approx(b), col
    assert row["target_pts"] != target["target_pts"]


def test_rolling_windows_use_prior_appearances_only(clean, feats):
    hist = clean[(clean["player_id"] == 202) & clean["appeared"]].sort_values("start_time")
    row = _row(feats, 202, 10)
    prior = hist[hist["start_time"] < row["start_time"]]
    assert row["pts_l3"] == pytest.approx(prior["pts"].tail(3).mean())
    assert row["pts_l10"] == pytest.approx(prior["pts"].tail(10).mean())
    assert row["pts_prev"] == pytest.approx(prior["pts"].iloc[-1])
    assert row["pts_median10"] == pytest.approx(prior["pts"].tail(10).median())
    assert row["appearances"] == len(prior)


def test_first_appearance_has_no_history(feats):
    first = feats[feats["player_id"] == 201].iloc[0]
    assert first["appearances"] == 0
    assert pd.isna(first["pts_l10"])


def test_dnp_rows_are_not_targets_or_history(clean, feats):
    dnp = feats[(feats["player_id"] == 101) & feats["did_not_play"]]
    assert len(dnp) > 0
    assert dnp["target_pts"].isna().all()
    hist = clean[(clean["player_id"] == 101) & clean["appeared"]]
    row = _row(feats, 101, 15)
    prior = hist[hist["start_time"] < row["start_time"]]
    assert row["pts_l5"] == pytest.approx(prior["pts"].tail(5).mean())


def test_missing_minutes_row_excluded_not_zero_filled(clean):
    r = clean[(clean["player_id"] == 102) & clean["minutes"].isna()]
    assert len(r) == 1 and not r["appeared"].iloc[0] and not r["usable_target"].iloc[0]


def test_season_boundary_resets_season_features_and_caps_rest(feats):
    p = feats[(feats["player_id"] == 202) & feats["appeared"]]
    opener = p[p["season"] == 2026].iloc[0]
    assert pd.isna(opener["pts_season"])
    assert opener["season_appearances"] == 0
    assert opener["team_rest_days"] == REST_CAP_DAYS
    assert opener["team_season_games"] == 0
    assert opener["pts_l10"] == opener["pts_l10"]  # career rolling windows carry over
    assert feats["days_since_last_app"].max() <= 30
    assert feats["team_rest_days"].max() <= REST_CAP_DAYS


def test_trade_uses_historical_team_and_flags_change(feats):
    p = feats[(feats["player_id"] == 103) & feats["appeared"]]
    first_new = p[p["team_id"] == 20].iloc[0]
    assert first_new["team_changed"] == 1
    assert first_new["games_with_team"] == 0
    before = p[p["team_id"] == 10].iloc[-1]
    assert before["team_changed"] == 0


def test_opponent_context_only_from_earlier_games(clean, feats):
    row = _row(feats, 201, 12)
    poisoned = clean.copy()
    same_or_later = poisoned["start_time"] >= row["start_time"]
    poisoned.loc[same_or_later, "pts"] += 40
    again = build_features(poisoned)
    r2 = again[(again["player_id"] == 201) & (again["game_id"] == row["game_id"])].iloc[0]
    for c in ("opp_allowed_pts_l10", "opp_team_pace_l10", "team_margin_l10", "opp_allowed_pts_season"):
        assert r2[c] == pytest.approx(row[c])


def test_upcoming_row_matches_state_after_last_game(clean, feats):
    last = clean[clean["player_id"] == 202].iloc[-1]
    up = pd.DataFrame([{
        "player_id": 202, "game_id": 999_999, "team_id": 20, "opponent_team_id": 10, "season": 2026,
        "season_type": 2, "is_home": True, "start_time": last["start_time"] + pd.Timedelta(days=2),
        "game_date": (last["start_time"] + pd.Timedelta(days=2)).normalize().tz_localize(None),
    }])
    out = build_features(clean, up)
    row = out[out["is_upcoming"]].iloc[0]
    hist = clean[(clean["player_id"] == 202) & clean["appeared"]]
    assert row["pts_l5"] == pytest.approx(hist["pts"].tail(5).mean())
    assert row["appearances"] == len(hist)
    assert pd.isna(row["target_pts"])
    # Historical rows are unchanged by appending an upcoming row.
    base = feats.set_index(["player_id", "game_id"])["pts_l10"]
    new = out[~out["is_upcoming"]].set_index(["player_id", "game_id"])["pts_l10"]
    pd.testing.assert_series_equal(base.sort_index(), new.sort_index())


def test_upcoming_row_in_the_past_is_rejected(clean):
    last = clean[clean["player_id"] == 202].iloc[-1]
    up = pd.DataFrame([{
        "player_id": 202, "game_id": 999_998, "team_id": 20, "opponent_team_id": 10, "season": 2026,
        "season_type": 2, "is_home": True, "start_time": last["start_time"] - pd.Timedelta(days=1),
        "game_date": last["game_date"],
    }])
    with pytest.raises(LeakageError):
        build_features(clean, up)


def test_duplicates_removed_and_reported():
    raw = make_raw(n_games_per_season=8, seasons=(2026,))
    dup = pd.concat([raw, raw.iloc[:5]], ignore_index=True)
    clean, rep = validate_and_clean(dup)
    assert rep.duplicate_player_game == 5
    assert not clean.duplicated(["player_id", "game_id"]).any()


def test_no_current_game_box_score_columns_in_feature_sets():
    forbidden = {"minutes", "pts", "reb", "ast", "fg3m", "fga", "fg3a", "fta", "starter", "did_not_play", "plus_minus"}
    for name, cols in FEATURE_SETS.items():
        assert not forbidden & set(cols), name
        assert not any(c.startswith("target_") for c in cols)


def test_h2h_is_shrunk_toward_recent_form(feats):
    p = feats[(feats["player_id"] == 201) & feats["appeared"] & (feats["h2h_n"] == 1)]
    assert len(p)
    # One prior meeting moves the estimate by at most 1/(1+5) of the difference.
    assert np.all(np.abs(p["h2h_delta_pts"]) <= np.abs(p["pts_l20"] - 0) / 6 + 35 / 6)
