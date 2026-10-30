"""Parse Unabated props odds board into normalized offer records."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal

from app.odds.unabated.response import UnabatedResponseShapeError

SideName = Literal["over", "under"]


def _nested_values(node: Any, *, context: str) -> list[Any]:
    if node is None:
        return []
    if isinstance(node, dict):
        return list(node.values())
    if isinstance(node, list):
        return node
    raise UnabatedResponseShapeError(
        f"{context}: expected dict or list, got {type(node).__name__}"
    )


@dataclass(frozen=True)
class ParsedPropLine:
    event_id: int
    event_name: str
    bet_type_id: int
    period_type_id: int | None
    person_id: int | None
    player_name: str | None
    side_index: int
    side_name: str
    pick_side: SideName
    market_source_id: int
    market_line_id: int | None
    points: float
    american_odds: int | None
    deep_link: str | None
    modified_on: datetime | None
    is_alternate: bool = False
    alternate_key: str | None = None
    team_id: int | None = None
    event_start: datetime | None = None


def _parse_side(side: dict[str, Any]) -> SideName | None:
    pick = _parse_side_name(side.get("sideName"))
    if pick is not None:
        return pick
    idx = side.get("sideIndex")
    if idx == 0:
        return "over"
    if idx == 1:
        return "under"
    return None


def _parse_side_name(name: str | None) -> SideName | None:
    if not name:
        return None
    lower = name.strip().lower()
    if lower in ("over", "o"):
        return "over"
    if lower in ("under", "u"):
        return "under"
    if "over" in lower:
        return "over"
    if "under" in lower:
        return "under"
    return None


def _ms_to_dt(value: Any) -> datetime | None:
    if value is None:
        return None
    try:
        ms = int(value)
        return datetime.fromtimestamp(ms / 1000, tz=UTC)
    except (TypeError, ValueError):
        return None


def _emit_line(
    group: dict[str, Any],
    period_type_id: int | None,
    side: dict[str, Any],
    line: dict[str, Any],
    *,
    is_alternate: bool,
    alternate_key: str | None,
) -> ParsedPropLine | None:
    if line.get("statusId") != 1 or line.get("disabled"):
        return None
    points = line.get("points")
    if points is None:
        return None
    try:
        points_f = float(points)
    except (TypeError, ValueError):
        return None
    pick = _parse_side(side)
    if pick is None:
        return None
    event_id = group.get("eventId")
    bet_type_id = group.get("betTypeId")
    if event_id is None or bet_type_id is None:
        return None
    price = line.get("price")
    american = int(price) if price is not None else None
    return ParsedPropLine(
        event_id=int(event_id),
        event_name=str(group.get("eventName") or ""),
        bet_type_id=int(bet_type_id),
        period_type_id=period_type_id,
        person_id=int(side["personId"]) if side.get("personId") is not None else None,
        player_name=side.get("sideName") if side.get("personId") else side.get("sideName"),
        side_index=int(side.get("sideIndex") or 0),
        side_name=str(side.get("sideName") or ""),
        pick_side=pick,
        market_source_id=int(line.get("marketSourceId") or side.get("marketSourceId") or 0),
        market_line_id=int(line["marketLineId"]) if line.get("marketLineId") is not None else None,
        points=points_f,
        american_odds=american,
        deep_link=line.get("deepLink"),
        modified_on=_ms_to_dt(line.get("modifiedOn")),
        is_alternate=is_alternate,
        alternate_key=alternate_key,
        team_id=int(side["teamId"]) if side.get("teamId") is not None else None,
        event_start=_ms_to_dt(group.get("eventStart")),
    )


def _parse_alternate_lines(line: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    raw = line.get("alternateLines")
    if raw is None:
        return []
    if isinstance(raw, dict):
        return [(str(k), v) for k, v in raw.items() if isinstance(v, dict)]
    if isinstance(raw, list):
        return [(str(i), alt) for i, alt in enumerate(raw) if isinstance(alt, dict)]
    raise UnabatedResponseShapeError(
        f"alternateLines: expected dict or list, got {type(raw).__name__}"
    )


def parse_props_odds(body: dict[str, Any]) -> list[ParsedPropLine]:
    odds_root = (body.get("data") or {}).get("odds") or {}
    out: list[ParsedPropLine] = []
    for league_obj in _nested_values(odds_root, context="data.odds"):
        if not isinstance(league_obj, dict):
            continue
        for period in _nested_values(league_obj.get("periodTypes"), context="periodTypes"):
            if not isinstance(period, dict):
                continue
            period_type_id = int(period["periodTypeId"]) if period.get("periodTypeId") is not None else None
            for phase in ("pregame", "live"):
                for group in _nested_values(period.get(phase), context=phase):
                    if not isinstance(group, dict):
                        continue
                    for side in _nested_values(group.get("sides"), context="sides"):
                        if not isinstance(side, dict):
                            continue
                        for line in _nested_values(side.get("marketSourceLines"), context="marketSourceLines"):
                            if not isinstance(line, dict):
                                continue
                            parsed = _emit_line(
                                group, period_type_id, side, line, is_alternate=False, alternate_key=None
                            )
                            if parsed:
                                out.append(parsed)
                            for alt_key, alt in _parse_alternate_lines(line):
                                alt_parsed = _emit_line(
                                    group,
                                    period_type_id,
                                    side,
                                    alt,
                                    is_alternate=True,
                                    alternate_key=alt_key,
                                )
                                if alt_parsed:
                                    out.append(alt_parsed)
    return out


def last_updated_ms(body: dict[str, Any]) -> int | None:
    value = (body.get("data") or {}).get("lastUpdated")
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None
