"""Map Unabated bet type names to Hooplytics stat category keys."""

import re

from app.analytics.categories import CATEGORIES

_BET_TYPE_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"player\s*points?\s*\+\s*rebounds?\s*\+\s*assists?", re.I), "pts_reb_ast"),
    (re.compile(r"player\s*points?\s*\+\s*rebounds?", re.I), "pts_reb"),
    (re.compile(r"player\s*points?\s*\+\s*assists?", re.I), "pts_ast"),
    (re.compile(r"player\s*rebounds?\s*\+\s*assists?", re.I), "reb_ast"),
    (re.compile(r"player\s*steals?\s*\+\s*blocks?", re.I), "stl_blk"),
    (re.compile(r"player\s*points?", re.I), "pts"),
    (re.compile(r"player\s*rebounds?", re.I), "reb"),
    (re.compile(r"player\s*assists?", re.I), "ast"),
    (re.compile(r"player\s*(threes|3[\s-]?pointers?(\s*made)?)", re.I), "fg3m"),
    (re.compile(r"^three\s*pointers?\s*made$", re.I), "fg3m"),
    (re.compile(r"^points?\s*assists?$", re.I), "pts_ast"),
    (re.compile(r"^points?\s*and\s*rebounds?$", re.I), "pts_reb"),
    (re.compile(r"^points?\s*rebounds?\s*assists?$", re.I), "pts_reb_ast"),
    (re.compile(r"^rebounds?\s*assists?$", re.I), "reb_ast"),
    (re.compile(r"^points?$", re.I), "pts"),
    (re.compile(r"^rebounds?$", re.I), "reb"),
    (re.compile(r"^assists?$", re.I), "ast"),
    (re.compile(r"player\s*steals?", re.I), "stl"),
    (re.compile(r"player\s*blocks?", re.I), "blk"),
    (re.compile(r"player\s*turnovers?", re.I), "tov"),
    (re.compile(r"\bpra\b", re.I), "pts_reb_ast"),
    (re.compile(r"\bpoints?\b.*\brebounds?\b.*\bassists?\b", re.I), "pts_reb_ast"),
]


def category_from_bet_type_name(name: str | None) -> str | None:
    if not name:
        return None
    normalized = name.strip()
    for pattern, key in _BET_TYPE_PATTERNS:
        if pattern.search(normalized):
            return key if key in CATEGORIES else None
    return None


def category_from_bet_type_id(bet_type_id: int, bet_type_names: dict[int, str]) -> str | None:
    return category_from_bet_type_name(bet_type_names.get(bet_type_id))
