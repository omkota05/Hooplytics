"""Pregame team-game features (one row per game, home-win target)."""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from app.ml.constants import TRAIN_FRAC, VAL_FRAC
from app.ml.game_winner.elo import HOME_ELO_ADVANTAGE, EloTracker

DEFAULT_REST_DAYS = 3.0
MAX_REST_DAYS = 7.0  # cap; longer gaps are treated as normal rest (not offseason signal)


@dataclass
class TeamHistory:
    last_dates: deque = field(default_factory=lambda: deque(maxlen=30))
    last_season_played: int | None = None
    margins: deque = field(default_factory=lambda: deque(maxlen=30))
    pts_for: deque = field(default_factory=lambda: deque(maxlen=30))
    pts_against: deque = field(default_factory=lambda: deque(maxlen=30))
    results: deque = field(default_factory=lambda: deque(maxlen=30))
    season_wins: int = 0
    season_losses: int = 0
    home_wins: int = 0
    home_losses: int = 0
    away_wins: int = 0
    away_losses: int = 0
    season: int | None = None


def _win_pct(wins: int, losses: int) -> float:
    total = wins + losses
    return wins / total if total else 0.5


def _rolling_mean(values: deque, n: int, *, empty_default: float = 0.0) -> float:
    if not values:
        return empty_default
    subset = list(values)[-n:]
    return float(np.mean(subset))


def _rest_days(hist: TeamHistory, game_date, game_season: int) -> float:
    """Days since last game; season openers and long breaks use DEFAULT_REST_DAYS."""
    if not hist.last_dates:
        return DEFAULT_REST_DAYS
    if hist.last_season_played is not None and hist.last_season_played != game_season:
        return DEFAULT_REST_DAYS
    last_date = hist.last_dates[-1]
    delta = (pd.Timestamp(game_date).normalize() - pd.Timestamp(last_date).normalize()).days
    if delta < 0:
        return DEFAULT_REST_DAYS
    if delta > MAX_REST_DAYS:
        return DEFAULT_REST_DAYS
    return float(delta)


def _b2b_flag(hist: TeamHistory, game_date, game_season: int) -> float:
    if not hist.last_dates:
        return 0.0
    if hist.last_season_played is not None and hist.last_season_played != game_season:
        return 0.0
    last_date = hist.last_dates[-1]
    delta = (pd.Timestamp(game_date).normalize() - pd.Timestamp(last_date).normalize()).days
    return float(0 <= delta <= 1)


def _season_transition(elo: EloTracker, teams: dict[int, TeamHistory], season: int) -> None:
    elo.season_mean_regression()
    for hist in teams.values():
        hist.season_wins = hist.season_losses = 0
        hist.home_wins = hist.home_losses = 0
        hist.away_wins = hist.away_losses = 0
        hist.season = season
        hist.last_dates.clear()
        hist.margins.clear()
        hist.pts_for.clear()
        hist.pts_against.clear()
        hist.results.clear()
        hist.last_season_played = None


def _snapshot_features(
    *,
    game_id: int,
    season: int,
    season_type: int,
    start_time,
    game_date,
    home_team_id: int,
    away_team_id: int,
    neutral_site: bool,
    home_hist: TeamHistory,
    away_hist: TeamHistory,
    elo: EloTracker,
    h2h_hist: list[int],
    home_win: int | None = None,
) -> dict:
    home_adv = 0.0 if neutral_site else HOME_ELO_ADVANTAGE
    home_elo, away_elo, elo_prob = elo.pregame(home_team_id, away_team_id, home_advantage=home_adv)
    h2h_home_pct = float(np.mean(h2h_hist)) if h2h_hist else 0.5
    feat = {
        "game_id": game_id,
        "season": season,
        "season_type": season_type,
        "start_time": start_time,
        "game_date": game_date,
        "home_team_id": home_team_id,
        "away_team_id": away_team_id,
        "neutral_site": bool(neutral_site),
        "home_elo": home_elo,
        "away_elo": away_elo,
        "elo_diff": home_elo - away_elo,
        "elo_home_win_prob": elo_prob,
        "home_win_pct_season": _win_pct(home_hist.season_wins, home_hist.season_losses),
        "away_win_pct_season": _win_pct(away_hist.season_wins, away_hist.season_losses),
        "home_win_pct_l5": _rolling_mean(home_hist.results, 5, empty_default=0.5),
        "away_win_pct_l5": _rolling_mean(away_hist.results, 5, empty_default=0.5),
        "home_win_pct_l10": _rolling_mean(home_hist.results, 10, empty_default=0.5),
        "away_win_pct_l10": _rolling_mean(away_hist.results, 10, empty_default=0.5),
        "home_pts_for_l10": _rolling_mean(home_hist.pts_for, 10),
        "away_pts_for_l10": _rolling_mean(away_hist.pts_for, 10),
        "home_pts_against_l10": _rolling_mean(home_hist.pts_against, 10),
        "away_pts_against_l10": _rolling_mean(away_hist.pts_against, 10),
        "home_margin_l10": _rolling_mean(home_hist.margins, 10),
        "away_margin_l10": _rolling_mean(away_hist.margins, 10),
        "home_rest_days": _rest_days(home_hist, game_date, season),
        "away_rest_days": _rest_days(away_hist, game_date, season),
        "home_b2b": _b2b_flag(home_hist, game_date, season),
        "away_b2b": _b2b_flag(away_hist, game_date, season),
        "home_home_win_pct": _win_pct(home_hist.home_wins, home_hist.home_losses),
        "away_away_win_pct": _win_pct(away_hist.away_wins, away_hist.away_losses),
        "h2h_home_win_pct": h2h_home_pct,
        "games_before_home": len(home_hist.results),
        "games_before_away": len(away_hist.results),
    }
    if home_win is not None:
        feat["home_win"] = int(home_win)
    return feat


def _apply_game_result(
    row,
    teams: dict[int, TeamHistory],
    elo: EloTracker,
    h2h: dict[tuple[int, int], list[int]],
) -> None:
    home_id, away_id = int(row.home_team_id), int(row.away_team_id)
    home_hist, away_hist = teams[home_id], teams[away_id]
    home_adv = 0.0 if row.neutral_site else HOME_ELO_ADVANTAGE
    home_win_val = 1.0 if row.home_score > row.away_score else 0.0
    if row.home_score == row.away_score:
        home_win_val = 0.5
    elo.apply_result(home_id, away_id, home_win_val, home_advantage=home_adv)
    h2h[(home_id, away_id)].append(1 if row.home_score > row.away_score else 0)
    season = int(row.season)
    for _tid, hist, is_home, pts_for, pts_against, margin, won in (
        (home_id, home_hist, True, row.home_score, row.away_score, row.home_score - row.away_score, int(row.home_score > row.away_score)),
        (away_id, away_hist, False, row.away_score, row.home_score, row.away_score - row.home_score, int(row.away_score > row.home_score)),
    ):
        hist.last_dates.append(row.game_date)
        hist.last_season_played = season
        hist.margins.append(float(margin))
        hist.pts_for.append(float(pts_for))
        hist.pts_against.append(float(pts_against))
        hist.results.append(float(won))
        hist.season_wins += int(won)
        hist.season_losses += int(1 - won)
        if is_home:
            hist.home_wins += int(won)
            hist.home_losses += int(1 - won)
        else:
            hist.away_wins += int(won)
            hist.away_losses += int(1 - won)
        hist.season = season


def build_game_feature_frame(games: pd.DataFrame) -> pd.DataFrame:
    """Chronological pass: features use only games strictly before each tip."""
    if games.empty:
        return games
    games = games.sort_values(["start_time", "id"]).reset_index(drop=True)
    teams: dict[int, TeamHistory] = defaultdict(TeamHistory)
    h2h: dict[tuple[int, int], list[int]] = defaultdict(list)
    elo = EloTracker()
    rows: list[dict] = []
    last_season: int | None = None

    for row in games.itertuples(index=False):
        season = int(row.season)
        if last_season is not None and season != last_season:
            _season_transition(elo, teams, season)
        last_season = season

        home_id, away_id = int(row.home_team_id), int(row.away_team_id)
        home_hist, away_hist = teams[home_id], teams[away_id]
        feat = _snapshot_features(
            game_id=int(row.id),
            season=season,
            season_type=int(row.season_type),
            start_time=row.start_time,
            game_date=row.game_date,
            home_team_id=home_id,
            away_team_id=away_id,
            neutral_site=bool(row.neutral_site),
            home_hist=home_hist,
            away_hist=away_hist,
            elo=elo,
            h2h_hist=h2h[(home_id, away_id)],
            home_win=int(row.home_win),
        )
        rows.append(feat)
        _apply_game_result(row, teams, elo, h2h)

    return pd.DataFrame(rows)


def feature_columns() -> list[str]:
    """Columns stored in artifacts (includes Elo levels for transparency and Elo baseline)."""
    return [
        "home_elo",
        "away_elo",
        "elo_diff",
        "elo_home_win_prob",
        "home_win_pct_season",
        "away_win_pct_season",
        "home_win_pct_l5",
        "away_win_pct_l5",
        "home_win_pct_l10",
        "away_win_pct_l10",
        "home_pts_for_l10",
        "away_pts_for_l10",
        "home_pts_against_l10",
        "away_pts_against_l10",
        "home_margin_l10",
        "away_margin_l10",
        "home_rest_days",
        "away_rest_days",
        "home_b2b",
        "away_b2b",
        "home_home_win_pct",
        "away_away_win_pct",
        "h2h_home_win_pct",
        "neutral_site",
        "is_playoffs",
    ]


def logistic_feature_columns() -> list[str]:
    """Inputs for logistic / HGB — Elo as a single probability (avoid redundant levels)."""
    skip = {"home_elo", "away_elo", "elo_diff"}
    return [c for c in feature_columns() if c not in skip]


def add_derived_columns(frame: pd.DataFrame) -> pd.DataFrame:
    out = frame.copy()
    out["neutral_site"] = out["neutral_site"].astype(float)
    out["is_playoffs"] = (out["season_type"] != 2).astype(float)
    return out


def split_chronological(frame: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    work = frame.copy()
    work["_kickoff"] = pd.to_datetime(work["start_time"], utc=True)
    kickoffs = np.sort(work["_kickoff"].unique())
    n = len(kickoffs)
    if n < 10:
        raise ValueError("Not enough games for chronological split")
    train_end = int(n * TRAIN_FRAC)
    val_end = int(n * (TRAIN_FRAC + VAL_FRAC))
    train = work[work["_kickoff"].isin(set(kickoffs[:train_end]))].drop(columns="_kickoff")
    val = work[work["_kickoff"].isin(set(kickoffs[train_end:val_end]))].drop(columns="_kickoff")
    test = work[work["_kickoff"].isin(set(kickoffs[val_end:]))].drop(columns="_kickoff")
    return train, val, test


def build_pregame_features(
    completed: pd.DataFrame,
    home_team_id: int,
    away_team_id: int,
    season: int,
    season_type: int,
    game_date,
    start_time,
    neutral_site: bool,
    game_id: int,
) -> pd.DataFrame:
    """Compute pregame features by replaying completed games only (no future leakage)."""
    if completed.empty:
        raise ValueError("No completed games to build pregame features")
    teams: dict[int, TeamHistory] = defaultdict(TeamHistory)
    h2h: dict[tuple[int, int], list[int]] = defaultdict(list)
    elo = EloTracker()
    last_season = None
    for row in completed.sort_values(["start_time", "id"]).itertuples(index=False):
        season_row = int(row.season)
        if last_season is not None and season_row != last_season:
            _season_transition(elo, teams, season_row)
        last_season = season_row
        _apply_game_result(row, teams, elo, h2h)

    if last_season is not None and season != last_season:
        _season_transition(elo, teams, season)

    home_hist, away_hist = teams[home_team_id], teams[away_team_id]
    snap = _snapshot_features(
        game_id=game_id,
        season=season,
        season_type=season_type,
        start_time=pd.Timestamp(start_time),
        game_date=pd.Timestamp(game_date),
        home_team_id=home_team_id,
        away_team_id=away_team_id,
        neutral_site=neutral_site,
        home_hist=home_hist,
        away_hist=away_hist,
        elo=elo,
        h2h_hist=h2h.get((home_team_id, away_team_id), []),
    )
    return add_derived_columns(pd.DataFrame([snap]))
