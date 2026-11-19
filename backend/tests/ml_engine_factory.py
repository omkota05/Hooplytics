"""Synthetic box-score frames shaped like `app.ml.engine.data.load_raw` output."""

from __future__ import annotations

import numpy as np
import pandas as pd

TEAMS = (10, 20, 30, 40)


def make_raw(n_games_per_season: int = 30, seasons: tuple[int, ...] = (2025, 2026), seed: int = 0) -> pd.DataFrame:
    """Four teams round-robin; three players per team; player 103 is traded from team 10 to 20 mid-way
    through the last season; player 101 has DNPs; one played row has missing minutes."""
    rng = np.random.default_rng(seed)
    rows = []
    gid = 1000
    for season in seasons:
        start = pd.Timestamp(f"{season - 1}-10-22T23:00:00Z")
        for k in range(n_games_per_season):
            day = start + pd.Timedelta(days=2 * k)
            pairs = ((10, 20), (30, 40)) if k % 2 == 0 else ((10, 30), (20, 40))
            for home, away in pairs:
                gid += 1
                for team, opp, is_home in ((home, away, True), (away, home, False)):
                    for slot in range(3):
                        pid = team * 10 + slot + 1 - 100 + 100  # 101..103, 201..203, ...
                        pid = team // 10 * 100 + slot + 1
                        if pid == 103 and season == seasons[-1] and k >= n_games_per_season // 2:
                            continue
                        if pid == 203 and season == seasons[-1] and k < n_games_per_season // 2:
                            continue
                        rows.append(_row(rng, pid, gid, team, opp, season, is_home, day, slot))
                    if team == 20 and season == seasons[-1] and k >= n_games_per_season // 2:
                        rows.append(_row(rng, 103, gid, team, opp, season, is_home, day, 2))
    df = pd.DataFrame(rows)
    dnp_mask = (df["player_id"] == 101) & (df.index % 7 == 3)
    df.loc[dnp_mask, ["did_not_play", "minutes"] + list(STATS)] = [True, np.nan] + [np.nan] * len(STATS)
    miss = df.index[(df["player_id"] == 102)][5]
    df.loc[miss, "minutes"] = np.nan
    df["start_time"] = pd.to_datetime(df["start_time"], utc=True)
    df["game_date"] = pd.to_datetime(df["start_time"].dt.date)
    return df.sort_values(["player_id", "start_time"]).reset_index(drop=True)


STATS = ("pts", "reb", "ast", "fg3m", "fga", "fg3a", "fta", "oreb", "tov")


def _row(rng, pid, gid, team, opp, season, is_home, day, slot):
    minutes = float(rng.integers(18, 38))
    fg3a = float(rng.integers(0, 9))
    return {
        "player_id": pid,
        "game_id": gid,
        "team_id": team,
        "opponent_team_id": opp,
        "season": season,
        "season_type": 2,
        "is_home": is_home,
        "starter": slot < 2,
        "did_not_play": False,
        "minutes": minutes,
        "pts": float(rng.integers(2, 35)),
        "reb": float(rng.integers(0, 12)),
        "ast": float(rng.integers(0, 10)),
        "fg3m": float(min(fg3a, rng.integers(0, 5))),
        "fga": float(rng.integers(5, 22)),
        "fg3a": fg3a,
        "fta": float(rng.integers(0, 8)),
        "oreb": float(rng.integers(0, 4)),
        "tov": float(rng.integers(0, 5)),
        "start_time": day,
        "status": "final",
    }
