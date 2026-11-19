"""Leakage-safe pregame features shared by training and inference.

Every player feature is the *state after the player's most recent prior appearance*:
rolling statistics are computed over appearance rows (inclusive), forward-filled across
DNP / upcoming rows, then shifted by one row. A row therefore never sees its own box score,
and DNP or upcoming rows never contribute stats. Team and opponent context is joined with
`merge_asof(..., allow_exact_matches=False)` on tip-off time, so only games that started
strictly earlier are used.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

FEATURE_VERSION = "fv2.1"

ROLL_STATS = ("pts", "reb", "ast", "fg3m", "minutes")
WINDOWS = (3, 5, 10, 20)
EWM_SPAN = 10
H2H_SHRINK = 5.0
REST_CAP_DAYS = 7
APPEARANCE_GAP_CAP_DAYS = 30
LOW_MINUTES = 15.0

UPCOMING_COLUMNS = (
    "player_id",
    "game_id",
    "team_id",
    "opponent_team_id",
    "season",
    "season_type",
    "is_home",
    "start_time",
    "game_date",
)


class LeakageError(AssertionError):
    pass


def _state(work: pd.DataFrame, values: pd.DataFrame, keys: list[str]) -> pd.DataFrame:
    """Turn inclusive per-appearance values into pregame state for every row in `work`.

    `values` is indexed like the appearance subset of `work`. Non-appearance rows get NaN, the
    frame is forward-filled within `keys`, then shifted one row within `keys`.
    """
    full = pd.DataFrame(index=work.index, columns=values.columns, dtype=float)
    full.loc[values.index, values.columns] = values.astype(float)
    grouper = [work[k] for k in keys]
    filled = full.groupby(grouper, sort=False).ffill()
    return filled.groupby(grouper, sort=False).shift(1)


def _rolling(app: pd.DataFrame, cols: list[str], window: int, how: str, keys=("player_id",)) -> pd.DataFrame:
    g = app.groupby(list(keys), sort=False)[cols]
    r = g.rolling(window, min_periods=1)
    out = getattr(r, how)()
    out.index = out.index.get_level_values(-1)
    return out


def team_game_table(hist: pd.DataFrame) -> pd.DataFrame:
    """Per (game, team) box-score totals from appearance rows, with opponent totals attached."""
    app = hist[hist["appeared"]]
    sums = (
        app.groupby(["game_id", "team_id"], as_index=False)[["pts", "reb", "ast", "fg3m", "fga", "fg3a", "fta", "oreb", "tov"]]
        .sum(min_count=1)
    )
    meta = hist.drop_duplicates(["game_id", "team_id"])[["game_id", "team_id", "opponent_team_id", "start_time", "season"]]
    tg = sums.merge(meta, on=["game_id", "team_id"], how="left")
    opp = tg[["game_id", "team_id", "pts", "reb", "ast", "fg3m", "fga", "fta", "oreb", "tov"]].rename(
        columns={"team_id": "opponent_team_id", **{c: f"opp_{c}" for c in ["pts", "reb", "ast", "fg3m", "fga", "fta", "oreb", "tov"]}}
    )
    tg = tg.merge(opp, on=["game_id", "opponent_team_id"], how="inner")
    # Possession estimate from box scores (FGA - OREB + TOV + 0.44*FTA); a proxy, not tracked possessions.
    poss = tg["fga"] - tg["oreb"] + tg["tov"] + 0.44 * tg["fta"]
    opp_poss = tg["opp_fga"] - tg["opp_oreb"] + tg["opp_tov"] + 0.44 * tg["opp_fta"]
    tg["pace_proxy"] = (poss + opp_poss) / 2.0
    tg["margin"] = tg["pts"] - tg["opp_pts"]
    return tg.sort_values(["team_id", "start_time"]).reset_index(drop=True)


def team_state_table(tg: pd.DataFrame) -> pd.DataFrame:
    """Inclusive rolling team/defense state at each completed team-game (joined as-of later)."""
    g = tg.groupby("team_id", sort=False)
    st = tg[["team_id", "start_time", "season"]].copy()
    roll = lambda c, w=10: g[c].transform(lambda s: s.rolling(w, min_periods=1).mean())  # noqa: E731
    st["team_margin_l10"] = roll("margin")
    st["team_pace_l10"] = roll("pace_proxy")
    st["team_pts_l10"] = roll("pts")
    for c in ("pts", "reb", "ast", "fg3m"):
        st[f"allowed_{c}_l10"] = roll(f"opp_{c}")
    st["allowed_pts_season"] = tg.groupby(["team_id", "season"], sort=False)["opp_pts"].transform(
        lambda s: s.expanding().mean()
    )
    st["team_season_games"] = tg.groupby(["team_id", "season"], sort=False).cumcount() + 1
    st["prev_start"] = tg["start_time"]
    return st.sort_values("start_time").reset_index(drop=True)


def _asof(rows: pd.DataFrame, state: pd.DataFrame, team_col: str, prefix: str, cols: list[str]) -> pd.DataFrame:
    left = rows[[team_col, "start_time"]].reset_index().rename(columns={team_col: "team_id"})
    left = left.sort_values("start_time")
    right = state[["team_id", "start_time", *cols]].sort_values("start_time")
    merged = pd.merge_asof(left, right, on="start_time", by="team_id", allow_exact_matches=False, direction="backward")
    merged = merged.set_index("index").reindex(rows.index)
    return merged[cols].add_prefix(prefix)


def build_features(hist: pd.DataFrame, upcoming: pd.DataFrame | None = None) -> pd.DataFrame:
    """Feature frame for every historical row plus optional upcoming rows (targets NaN).

    `hist` must come from `data.validate_and_clean`. `upcoming` may hold at most one row per player.
    """
    hist = hist.copy()
    hist["is_upcoming"] = False
    if upcoming is not None and not upcoming.empty:
        if upcoming["player_id"].duplicated().any():
            raise ValueError("build_features accepts at most one upcoming row per player")
        up = upcoming[list(UPCOMING_COLUMNS)].copy()
        up["start_time"] = pd.to_datetime(up["start_time"], utc=True)
        up["game_date"] = pd.to_datetime(up["game_date"])
        up["is_upcoming"] = True
        up["appeared"] = False
        up["usable_target"] = False
        up["did_not_play"] = False
        last_hist = hist.groupby("player_id")["start_time"].max()
        late = up["player_id"].map(last_hist)
        if (late.notna() & (late >= up["start_time"])).any():
            raise LeakageError("Upcoming row is not after the player's latest completed game")
        work = pd.concat([hist, up], ignore_index=True)
    else:
        work = hist
    work = work.sort_values(["player_id", "start_time"], kind="mergesort").reset_index(drop=True)

    app = work[work["appeared"]].copy()
    out = work[list(UPCOMING_COLUMNS) + ["is_upcoming", "appeared", "usable_target", "did_not_play"]].copy()
    for t in ("pts", "reb", "ast", "fg3m", "minutes"):
        out[f"target_{t}"] = work[t].where(work["usable_target"]) if t in work else np.nan

    # Team-game context (needed for FGA share).
    tg = team_game_table(hist)
    app = app.merge(tg[["game_id", "team_id", "fga"]].rename(columns={"fga": "team_fga"}), on=["game_id", "team_id"], how="left").set_index(app.index)
    app["fga_share"] = app["fga"] / app["team_fga"].replace(0, np.nan)
    app["low_min"] = (app["minutes"] < LOW_MINUTES).astype(float)
    app["starter_f"] = app["starter"].astype(float)
    app["app_time"] = app["start_time"].astype("int64") / 1e9

    vals: dict[str, pd.Series] = {}
    rs = list(ROLL_STATS)
    for w in WINDOWS:
        m = _rolling(app, rs, w, "mean")
        for c in rs:
            vals[f"{c}_l{w}"] = m[c]
    for c in rs:
        vals[f"{c}_prev"] = app[c]
        vals[f"{c}_ewm"] = app.groupby("player_id", sort=False)[c].transform(lambda s: s.ewm(span=EWM_SPAN, adjust=False).mean())
    for how in ("median", "std", "max", "min"):
        m = _rolling(app, rs, 10, how)
        for c in rs:
            vals[f"{c}_{how}10"] = m[c]
    opp_cols = ["fga", "fg3a", "fta"]
    for w in (5, 10):
        m = _rolling(app, opp_cols, w, "mean")
        for c in opp_cols:
            vals[f"{c}_l{w}"] = m[c]
    sums = _rolling(app, ["pts", "reb", "ast", "fg3m", "fga", "fg3a", "minutes"], 10, "sum")
    for c in ("pts", "reb", "ast", "fg3m", "fga", "fg3a"):
        vals[f"{c}_per_min_l10"] = sums[c] / sums["minutes"].replace(0, np.nan)
    m = _rolling(app, ["fga_share", "low_min", "starter_f"], 10, "mean")
    vals["fga_share_l10"] = m["fga_share"]
    vals["low_min_rate_l10"] = m["low_min"]
    vals["start_rate_l10"] = m["starter_f"]
    vals["appearances"] = app.groupby("player_id", sort=False).cumcount().astype(float) + 1
    vals["last_app_time"] = app["app_time"]
    vals["last_team_id"] = app["team_id"].astype(float)
    pstate = _state(work, pd.DataFrame(vals, index=app.index), ["player_id"])

    season_vals = pd.DataFrame(index=app.index)
    sg = app.groupby(["player_id", "season"], sort=False)
    for c in rs:
        season_vals[f"{c}_season"] = sg[c].transform(lambda s: s.expanding().mean())
    season_vals["season_appearances"] = sg.cumcount().astype(float) + 1
    sstate = _state(work, season_vals, ["player_id", "season"])

    team_vals = pd.DataFrame({"games_with_team": app.groupby(["player_id", "team_id"], sort=False).cumcount().astype(float) + 1}, index=app.index)
    tstate = _state(work, team_vals, ["player_id", "team_id"])

    h2h_vals = pd.DataFrame(index=app.index)
    hg = app.groupby(["player_id", "opponent_team_id"], sort=False)
    for c in ("pts", "reb", "ast", "fg3m"):
        h2h_vals[f"h2h_sum_{c}"] = hg[c].cumsum()
    h2h_vals["h2h_n"] = hg.cumcount().astype(float) + 1
    hstate = _state(work, h2h_vals, ["player_id", "opponent_team_id"])

    out = pd.concat([out, pstate, sstate, tstate], axis=1)
    out["appearances"] = out["appearances"].fillna(0)
    out["season_appearances"] = out["season_appearances"].fillna(0)
    out["games_with_team"] = out["games_with_team"].fillna(0)
    out["team_changed"] = ((out["last_team_id"].notna()) & (out["last_team_id"] != out["team_id"])).astype(float)
    now_s = out["start_time"].astype("int64") / 1e9
    gap = (now_s - out["last_app_time"]) / 86400.0
    out["days_since_last_app"] = gap.clip(upper=APPEARANCE_GAP_CAP_DAYS)
    out["long_layoff"] = (gap > 10).astype(float)
    for c in ("pts", "reb", "ast", "fg3m", "minutes"):
        out[f"{c}_trend"] = out[f"{c}_l5"] - out[f"{c}_l20"]
    n = hstate["h2h_n"].fillna(0)
    out["h2h_n"] = n
    for c in ("pts", "reb", "ast", "fg3m"):
        prior = out[f"{c}_l20"]
        shrunk = (hstate[f"h2h_sum_{c}"].fillna(0) + H2H_SHRINK * prior) / (n + H2H_SHRINK)
        out[f"h2h_delta_{c}"] = shrunk - prior

    # Team / opponent context strictly before tip-off.
    ts = team_state_table(tg)
    own_cols = ["team_margin_l10", "team_pace_l10", "team_pts_l10", "team_season_games", "prev_start"]
    own = _asof(out, ts, "team_id", "", own_cols)
    opp_state_cols = ["allowed_pts_l10", "allowed_reb_l10", "allowed_ast_l10", "allowed_fg3m_l10", "allowed_pts_season", "team_pace_l10", "team_margin_l10"]
    opp = _asof(out, ts, "opponent_team_id", "opp_", opp_state_cols)
    out = pd.concat([out, own, opp], axis=1)
    same_season = own["team_season_games"].notna()
    rest_h = (out["start_time"] - pd.to_datetime(own["prev_start"], utc=True)).dt.total_seconds() / 3600.0
    out["team_rest_days"] = (rest_h / 24.0).clip(upper=REST_CAP_DAYS)
    out["b2b"] = (rest_h < 36).astype(float)
    # Season progress uses team games already played this season (0 at the opener).
    prev_season = _asof(out, ts.assign(prev_season_val=ts["season"]), "team_id", "", ["prev_season_val"])["prev_season_val"]
    in_season = same_season & (prev_season == out["season"])
    out["team_season_games"] = own["team_season_games"].where(in_season, 0.0)
    out["season_progress"] = (out["team_season_games"] / 82.0).clip(upper=1.2)
    out.loc[~in_season, "team_rest_days"] = REST_CAP_DAYS
    out.loc[~in_season, "b2b"] = 0.0
    out["is_home_f"] = out["is_home"].astype(float)
    out["playoffs"] = (out["season_type"] == 3).astype(float)
    out = out.drop(columns=["prev_start", "last_app_time", "last_team_id"])
    return out


CORE_FEATURES: list[str] = [
    *[f"{c}_l{w}" for c in ROLL_STATS for w in (5, 10, 20)],
    *[f"{c}_season" for c in ROLL_STATS],
    *[f"{c}_ewm" for c in ROLL_STATS],
    "minutes_std10",
    "start_rate_l10",
    "fga_l10",
    "fg3a_l10",
    "fta_l10",
    "fga_share_l10",
    "appearances",
    "season_appearances",
    "days_since_last_app",
    "team_rest_days",
    "b2b",
    "is_home_f",
    "playoffs",
    "opp_allowed_pts_l10",
    "opp_allowed_reb_l10",
    "opp_allowed_ast_l10",
    "opp_allowed_fg3m_l10",
    "opp_team_pace_l10",
    "team_pace_l10",
    "team_margin_l10",
    "opp_team_margin_l10",
]

FULL_FEATURES: list[str] = sorted(
    set(CORE_FEATURES)
    | {f"{c}_l3" for c in ROLL_STATS}
    | {f"{c}_prev" for c in ROLL_STATS}
    | {f"{c}_{h}10" for c in ROLL_STATS for h in ("median", "std", "max", "min")}
    | {f"{c}_trend" for c in ROLL_STATS}
    | {f"{c}_per_min_l10" for c in ("pts", "reb", "ast", "fg3m", "fga", "fg3a")}
    | {"fga_l5", "fg3a_l5", "fta_l5", "low_min_rate_l10", "games_with_team", "team_changed", "long_layoff"}
    | {"season_progress", "team_pts_l10", "opp_allowed_pts_season", "h2h_n"}
    | {f"h2h_delta_{c}" for c in ("pts", "reb", "ast", "fg3m")}
)

FEATURE_SETS = {"core": CORE_FEATURES, "full": FULL_FEATURES}
