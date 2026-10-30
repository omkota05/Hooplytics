"""Prop Finder sort windows, min-games filters, and Wilson ranking helpers."""

from __future__ import annotations

from typing import Literal

from app.analytics.wilson import wilson_lower_bound
from app.models.sportsbook import PropOffer

MinGamesOption = Literal[1, 5, 10, 20]

SORT_WINDOW_CAP: dict[str, int] = {
    "l5": 5,
    "wilson_l5": 5,
    "l10": 10,
    "wilson_l10": 10,
    "l20": 20,
    "wilson_l20": 20,
    "h2h": 5,
    "wilson_h2h": 5,
    "hcs": 20,
}

WINDOW_LABEL: dict[str, str] = {
    "l5": "L5",
    "wilson_l5": "L5",
    "l10": "L10",
    "wilson_l10": "L10",
    "l20": "L20",
    "wilson_l20": "L20",
    "h2h": "H2H_L5",
    "wilson_h2h": "H2H_L5",
}


def effective_min_games(min_games: int, sort: str) -> int | None:
    """Cap required games in the active window (e.g. L5 sort cannot require more than 5)."""
    cap = SORT_WINDOW_CAP.get(sort)
    if cap is None:
        return None
    return min(min_games, cap)


def games_column_for_sort(sort: str):
    mapping = {
        "l5": PropOffer.l5_games,
        "wilson_l5": PropOffer.l5_games,
        "l10": PropOffer.l10_games,
        "wilson_l10": PropOffer.l10_games,
        "l20": PropOffer.l20_games,
        "wilson_l20": PropOffer.l20_games,
        "h2h": PropOffer.h2h_games,
        "wilson_h2h": PropOffer.h2h_games,
        "hcs": PropOffer.l20_games,
    }
    return mapping.get(sort)


def hit_pct_column_for_sort(sort: str):
    mapping = {
        "l5": PropOffer.l5_hit_pct,
        "wilson_l5": PropOffer.l5_hit_pct,
        "l10": PropOffer.l10_hit_pct,
        "wilson_l10": PropOffer.l10_hit_pct,
        "l20": PropOffer.l20_hit_pct,
        "wilson_l20": PropOffer.l20_hit_pct,
        "h2h": PropOffer.h2h_hit_pct,
        "wilson_h2h": PropOffer.h2h_hit_pct,
        "hcs": PropOffer.hcs_score,
    }
    return mapping.get(sort, PropOffer.l10_hit_pct)


def sort_column(sort: str):
    if sort == "hcs":
        return PropOffer.hcs_score
    if sort.startswith("wilson_"):
        key = sort.replace("wilson_", "")
        mapping = {
            "l5": PropOffer.l5_wilson_lb,
            "l10": PropOffer.l10_wilson_lb,
            "l20": PropOffer.l20_wilson_lb,
            "h2h": PropOffer.h2h_wilson_lb,
        }
        return mapping.get(key, PropOffer.l10_wilson_lb)
    mapping = {
        "l5": PropOffer.l5_hit_pct,
        "l10": PropOffer.l10_hit_pct,
        "l20": PropOffer.l20_hit_pct,
        "h2h": PropOffer.h2h_hit_pct,
        "line": PropOffer.line,
    }
    return mapping.get(sort, PropOffer.l10_hit_pct)


def window_side_stats(window: dict | None, pick_side: str) -> dict:
    if not window:
        return {
            "games": 0,
            "hits": None,
            "attempts": None,
            "hit_pct": None,
            "wilson_lb": None,
        }
    over_hits = int(window.get("over_hits") or 0)
    under_hits = int(window.get("under_hits") or 0)
    attempts = over_hits + under_hits
    hits = over_hits if pick_side == "over" else under_hits
    games = int(window.get("games") or 0)
    if pick_side == "over":
        hit_pct = window.get("over_hit_pct")
    else:
        hit_pct = window.get("under_hit_pct")
    wilson = wilson_lower_bound(hits, attempts) if attempts else None
    return {
        "games": games,
        "hits": hits if attempts else None,
        "attempts": attempts or None,
        "hit_pct": hit_pct if attempts else None,
        "wilson_lb": wilson,
    }
