"""Leakage-safe feature engineering for training and inference."""

from __future__ import annotations

import numpy as np
import pandas as pd

from app.analytics.categories import BOX_SCORE_FIELDS
from app.ml.constants import COMPONENT_STATS, EWM_SPAN, TRAIN_FRAC, VAL_FRAC
from app.ml.dataset import FEATURE_STATS, ROLLING_WINDOWS, add_point_in_time_features, load_player_games

ROLLING_STD_WINDOW = 5


def _expanding_season_mean(frame: pd.DataFrame, stat: str) -> pd.Series:
    """Season-to-date average of `stat` using only prior games in the same season."""
    return frame.groupby(["player_id", "season"], sort=False)[stat].transform(
        lambda s: s.shift(1).expanding(min_periods=1).mean()
    )


def _rolling_std_prior(frame: pd.DataFrame, stat: str, window: int = ROLLING_STD_WINDOW) -> pd.Series:
    prior = frame.groupby("player_id", sort=False)[stat].shift(1)
    return prior.groupby(frame["player_id"]).transform(lambda s: s.rolling(window, min_periods=2).std())


def _ewm_prior(frame: pd.DataFrame, stat: str, span: int = EWM_SPAN) -> pd.Series:
    return frame.groupby("player_id", sort=False)[stat].transform(
        lambda s: s.shift(1).ewm(span=span, min_periods=1, adjust=False).mean()
    )


def _head_to_head_prior(frame: pd.DataFrame, stat: str) -> pd.Series:
    return frame.groupby(["player_id", "opponent_team_id"], sort=False)[stat].transform(
        lambda s: s.shift(1).expanding(min_periods=1).mean()
    )


def _team_game_strength(session_frame: pd.DataFrame) -> pd.DataFrame:
    """Per-team per-game scoring margin inferred from summed player points."""
    played = session_frame[~session_frame["did_not_play"].fillna(True)].copy()
    team_pts = played.groupby(["game_id", "team_id"], as_index=False)["pts"].sum()
    game_total = team_pts.groupby("game_id")["pts"].transform("sum")
    team_pts["team_margin"] = team_pts["pts"] - (game_total - team_pts["pts"])
    meta = played[["game_id", "team_id", "game_date", "start_time"]].drop_duplicates(["game_id", "team_id"])
    team_game = team_pts.merge(meta, on=["game_id", "team_id"]).sort_values(["team_id", "start_time"])
    team_game["team_strength_avg"] = (
        team_game.groupby("team_id", sort=False)["team_margin"]
        .apply(lambda s: s.shift(1).expanding(min_periods=1).mean())
        .reset_index(level=0, drop=True)
    )
    return team_game[["game_id", "team_id", "team_strength_avg"]]


def _opponent_defense_prior(session_frame: pd.DataFrame) -> pd.DataFrame:
    """Opponent rolling average of points allowed per game (from player box scores)."""
    allowed = (
        session_frame.groupby(["game_id", "opponent_team_id", "game_date", "start_time"], as_index=False)[
            "pts"
        ]
        .sum()
        .rename(columns={"opponent_team_id": "def_team_id", "pts": "pts_allowed"})
        .sort_values(["def_team_id", "start_time"])
    )
    allowed["opp_pts_allowed_avg"] = (
        allowed.groupby("def_team_id", sort=False)["pts_allowed"]
        .apply(lambda s: s.shift(1).expanding(min_periods=1).mean())
        .reset_index(level=0, drop=True)
    )
    return allowed[["game_id", "def_team_id", "opp_pts_allowed_avg"]]


def enrich_player_game_frame(raw: pd.DataFrame) -> pd.DataFrame:
    """Build the full training feature matrix from raw player-game rows."""
    raw = raw.copy()
    raw["game_date"] = pd.to_datetime(raw["game_date"]).dt.normalize()
    base = add_point_in_time_features(raw)
    if base.empty:
        return base
    frame = base.sort_values(["player_id", "start_time"]).reset_index(drop=True)

    for stat in COMPONENT_STATS:
        frame[f"{stat}_season_avg"] = _expanding_season_mean(frame, stat)
        frame[f"{stat}_std_{ROLLING_STD_WINDOW}"] = _rolling_std_prior(frame, stat)
        frame[f"{stat}_ewm_{EWM_SPAN}"] = _ewm_prior(frame, stat)
        frame[f"{stat}_h2h_avg"] = _head_to_head_prior(frame, stat)

    team_strength = _team_game_strength(raw)
    frame = frame.merge(team_strength, on=["game_id", "team_id"], how="left")

    opp_def = _opponent_defense_prior(raw)
    frame = frame.merge(
        opp_def,
        left_on=["game_id", "opponent_team_id"],
        right_on=["game_id", "def_team_id"],
        how="left",
    )

    frame["is_home_int"] = frame["is_home"].astype(int)
    frame["starter_int"] = frame["starter"].astype(int)
    return frame


def build_training_frame(session) -> pd.DataFrame:
    return enrich_player_game_frame(load_player_games(session))


def feature_columns() -> list[str]:
    cols: list[str] = [
        "games_before",
        "rest_days",
        "is_home_int",
        "starter_int",
        "team_strength_avg",
        "opp_pts_allowed_avg",
    ]
    for stat in FEATURE_STATS:
        for window in ROLLING_WINDOWS:
            cols.append(f"{stat}_avg_{window}")
    for stat in COMPONENT_STATS:
        cols.extend(
            [
                f"{stat}_season_avg",
                f"{stat}_std_{ROLLING_STD_WINDOW}",
                f"{stat}_ewm_{EWM_SPAN}",
                f"{stat}_h2h_avg",
            ]
        )
    return cols


def target_column(category_key: str) -> str:
    return f"target_{category_key}"


def prepare_xy(frame: pd.DataFrame, category_key: str) -> tuple[pd.DataFrame, pd.Series]:
    cols = feature_columns()
    y_col = target_column(category_key)
    usable = frame.dropna(subset=[y_col])
    x = usable[cols].copy()
    for col in cols:
        x[col] = x[col].fillna(0.0)
    return x, usable[y_col].astype(float)


def component_target_columns() -> list[str]:
    return [f"target_{s}" for s in COMPONENT_STATS]


def split_chronological(frame: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Train / val / test split by distinct game tip-off times (UTC).

    Using kickoff timestamps avoids putting an early game on the same calendar day
    in train while a later game that day is in test (which would leak future team
    context into features for the early game if we trained on the later one).
    """
    work = frame.copy()
    work["_kickoff"] = pd.to_datetime(work["start_time"], utc=True)
    kickoffs = np.sort(work["_kickoff"].unique())
    n = len(kickoffs)
    if n < 10:
        raise ValueError("Not enough distinct kickoff times for chronological ML split")
    train_end = int(n * TRAIN_FRAC)
    val_end = int(n * (TRAIN_FRAC + VAL_FRAC))
    train_k = set(kickoffs[:train_end])
    val_k = set(kickoffs[train_end:val_end])
    test_k = set(kickoffs[val_end:])
    train = work[work["_kickoff"].isin(train_k)].drop(columns="_kickoff")
    val = work[work["_kickoff"].isin(val_k)].drop(columns="_kickoff")
    test = work[work["_kickoff"].isin(test_k)].drop(columns="_kickoff")
    return train, val, test


# Backwards-compatible alias
def split_by_game_date(frame: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    return split_chronological(frame)


def build_inference_row(
    history: pd.DataFrame,
    *,
    player_id: int,
    game_id: int,
    team_id: int,
    opponent_team_id: int,
    game_date,
    start_time,
    season: int,
    season_type: int,
    is_home: bool,
    starter: bool = True,
) -> pd.DataFrame:
    """Construct one feature row for an upcoming game using only prior history."""
    synthetic = pd.concat(
        [
            history,
            pd.DataFrame(
                [
                    {
                        "player_id": player_id,
                        "game_id": game_id,
                        "team_id": team_id,
                        "opponent_team_id": opponent_team_id,
                        "game_date": pd.Timestamp(game_date),
                        "start_time": pd.Timestamp(start_time),
                        "season": season,
                        "season_type": season_type,
                        "is_home": is_home,
                        "starter": starter,
                        "did_not_play": False,
                        "minutes": np.nan,
                        **{f: np.nan for f in BOX_SCORE_FIELDS},
                        "fga": np.nan,
                        "fta": np.nan,
                    }
                ]
            ),
        ],
        ignore_index=True,
    )
    enriched = enrich_player_game_frame(synthetic)
    row = enriched[enriched["game_id"] == game_id].iloc[-1:]
    return row
