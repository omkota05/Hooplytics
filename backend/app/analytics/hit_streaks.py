"""Consecutive hit streaks for a prop line and pick side (appearance-based)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import date
from typing import Any, Literal

from app.analytics.categories import StatCategory, stat_value
from app.analytics.lines import Outcome, classify

Side = Literal["over", "under"]
RecentResult = Literal["hit", "miss", "push"]


def side_is_hit(outcome: Outcome, pick_side: Side) -> bool:
    return outcome == pick_side


def clearance_margin(value: float, line: float, pick_side: Side) -> float:
    if pick_side == "over":
        return value - line
    return line - value


@dataclass(frozen=True)
class StreakGameRow:
    game_id: int
    game_date: date
    opponent_abbreviation: str | None
    stat_value: float | None
    outcome: Outcome | None
    bet_result: RecentResult | None


@dataclass(frozen=True)
class HitStreakBundle:
    current_streak: int
    streak_at_least: bool
    push_count_in_streak_window: int
    avg_clearance_margin: float | None
    games_evaluated: int
    last_completed_game_date: date | None
    recent_results: tuple[StreakGameRow, ...]
    l5_record: str
    l10_record: str
    l20_record: str
    l5_hit_pct: float | None
    l10_hit_pct: float | None
    l20_hit_pct: float | None
    missing_data_flags: tuple[str, ...]

    def to_json(self) -> dict:
        def row_dict(r: StreakGameRow) -> dict:
            d = asdict(r)
            d["game_date"] = r.game_date.isoformat()
            return d

        return {
            "current_streak": self.current_streak,
            "streak_at_least": self.streak_at_least,
            "push_count_in_streak_window": self.push_count_in_streak_window,
            "avg_clearance_margin": self.avg_clearance_margin,
            "games_evaluated": self.games_evaluated,
            "last_completed_game_date": (
                self.last_completed_game_date.isoformat() if self.last_completed_game_date else None
            ),
            "recent_results": [row_dict(r) for r in self.recent_results],
            "l5_record": self.l5_record,
            "l10_record": self.l10_record,
            "l20_record": self.l20_record,
            "l5_hit_pct": self.l5_hit_pct,
            "l10_hit_pct": self.l10_hit_pct,
            "l20_hit_pct": self.l20_hit_pct,
            "missing_data_flags": list(self.missing_data_flags),
        }

    @classmethod
    def from_json(cls, data: dict) -> HitStreakBundle:
        rows = []
        for r in data.get("recent_results") or []:
            rows.append(
                StreakGameRow(
                    game_id=int(r["game_id"]),
                    game_date=date.fromisoformat(r["game_date"]),
                    opponent_abbreviation=r.get("opponent_abbreviation"),
                    stat_value=r.get("stat_value"),
                    outcome=r.get("outcome"),
                    bet_result=r.get("bet_result"),
                )
            )
        lcd = data.get("last_completed_game_date")
        return cls(
            current_streak=int(data.get("current_streak") or 0),
            streak_at_least=bool(data.get("streak_at_least")),
            push_count_in_streak_window=int(data.get("push_count_in_streak_window") or 0),
            avg_clearance_margin=data.get("avg_clearance_margin"),
            games_evaluated=int(data.get("games_evaluated") or 0),
            last_completed_game_date=date.fromisoformat(lcd) if lcd else None,
            recent_results=tuple(rows),
            l5_record=str(data.get("l5_record") or "—"),
            l10_record=str(data.get("l10_record") or "—"),
            l20_record=str(data.get("l20_record") or "—"),
            l5_hit_pct=data.get("l5_hit_pct"),
            l10_hit_pct=data.get("l10_hit_pct"),
            l20_hit_pct=data.get("l20_hit_pct"),
            missing_data_flags=tuple(data.get("missing_data_flags") or []),
        )


def _record_label(values: Sequence[float], line: float, pick_side: Side) -> tuple[str, float | None]:
    values = list(values)
    if not values:
        return "—", None
    hits = misses = pushes = 0
    for v in values:
        outcome = classify(v, line)
        if outcome == "push":
            pushes += 1
        elif side_is_hit(outcome, pick_side):
            hits += 1
        else:
            misses += 1
    parts = []
    if hits:
        parts.append(f"{hits}H")
    if misses:
        parts.append(f"{misses}M")
    if pushes:
        parts.append(f"{pushes}P")
    label = "-".join(parts) if parts else "—"
    decided = hits + misses
    pct = round(100 * hits / decided, 1) if decided else None
    return label, pct


def compute_hit_streak(
    games: Sequence[Any],
    *,
    category: StatCategory,
    line: float,
    pick_side: Side,
) -> HitStreakBundle:
    """`games` must be chronological most-recent-first, played appearances only."""
    flags: list[str] = []
    appearance_values: list[float] = []
    recent_rows: list[StreakGameRow] = []

    for g in games:
        value = stat_value(g, category)
        opp_abbr = None
        opponent = getattr(g, "opponent", None)
        if opponent is not None:
            opp_abbr = getattr(opponent, "abbreviation", None)

        if value is None:
            recent_rows.append(
                StreakGameRow(
                    game_id=int(getattr(g, "game_id", 0)),
                    game_date=getattr(g, "game_date"),
                    opponent_abbreviation=opp_abbr,
                    stat_value=None,
                    outcome=None,
                    bet_result=None,
                )
            )
            continue

        outcome = classify(value, line)
        if outcome == "push":
            bet: RecentResult = "push"
        elif side_is_hit(outcome, pick_side):
            bet = "hit"
        else:
            bet = "miss"

        appearance_values.append(float(value))
        recent_rows.append(
            StreakGameRow(
                game_id=int(getattr(g, "game_id", 0)),
                game_date=getattr(g, "game_date"),
                opponent_abbreviation=opp_abbr,
                stat_value=float(value),
                outcome=outcome,
                bet_result=bet,
            )
        )

    # Walk valid appearances only for streak (skip incomplete in the walk)
    valid_appearances = [r for r in recent_rows if r.stat_value is not None]
    streak = 0
    margins: list[float] = []
    in_streak = True
    push_in_window = 0

    for row in valid_appearances:
        if not in_streak:
            break
        if row.outcome == "push":
            push_in_window += 1
            in_streak = False
            break
        if row.bet_result == "hit":
            streak += 1
            margins.append(clearance_margin(row.stat_value, line, pick_side))
        else:
            in_streak = False

    streak_at_least = in_streak and streak > 0 and len(valid_appearances) > 0

    if not valid_appearances:
        flags.append("no_completed_appearances")
    elif len(valid_appearances) < 5:
        flags.append("limited_history")

    l5_vals = appearance_values[:5]
    l10_vals = appearance_values[:10]
    l20_vals = appearance_values[:20]
    l5_record, l5_pct = _record_label(l5_vals, line, pick_side)
    l10_record, l10_pct = _record_label(l10_vals, line, pick_side)
    l20_record, l20_pct = _record_label(l20_vals, line, pick_side)

    last_date = valid_appearances[0].game_date if valid_appearances else None
    avg_margin = round(sum(margins) / len(margins), 2) if margins else None

    viz = valid_appearances[:10]
    viz_rows = tuple(viz)

    return HitStreakBundle(
        current_streak=streak,
        streak_at_least=streak_at_least,
        push_count_in_streak_window=push_in_window,
        avg_clearance_margin=avg_margin,
        games_evaluated=len(appearance_values),
        last_completed_game_date=last_date,
        recent_results=viz_rows,
        l5_record=l5_record,
        l10_record=l10_record,
        l20_record=l20_record,
        l5_hit_pct=l5_pct,
        l10_hit_pct=l10_pct,
        l20_hit_pct=l20_pct,
        missing_data_flags=tuple(flags),
    )


def window_side_hit_pct(values: Sequence[float], line: float, pick_side: Side) -> float | None:
    if not values:
        return None
    _, pct = _record_label(values, line, pick_side)
    return pct
