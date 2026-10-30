"""Normalize Unabated `data` payloads (list vs id-keyed dict)."""

from __future__ import annotations

from typing import Any


class UnabatedResponseShapeError(RuntimeError):
    pass


def data_records(data: Any, *, context: str) -> list[dict[str, Any]]:
    """Return object records from a discovery `data` field.

    Unabated returns either:
    - a JSON array of objects, or
    - a JSON object whose values are records (keys are often numeric ids).
    """
    if data is None:
        return []
    if isinstance(data, list):
        records: list[dict[str, Any]] = []
        for idx, item in enumerate(data):
            if isinstance(item, dict):
                records.append(item)
            else:
                raise UnabatedResponseShapeError(
                    f"{context}: expected dict at data[{idx}], got {type(item).__name__}"
                )
        return records
    if isinstance(data, dict):
        records = []
        for key, item in data.items():
            if isinstance(item, dict):
                records.append(item)
            elif isinstance(item, str):
                raise UnabatedResponseShapeError(
                    f"{context}: unexpected string value at data[{key!r}] (dict-of-records expected)"
                )
            else:
                raise UnabatedResponseShapeError(
                    f"{context}: expected dict at data[{key!r}], got {type(item).__name__}"
                )
        return records
    raise UnabatedResponseShapeError(f"{context}: data must be list or dict, got {type(data).__name__}")


def person_display_name(person: dict[str, Any]) -> str | None:
    if person.get("name"):
        return str(person["name"]).strip()
    first = str(person.get("firstName") or "").strip()
    last = str(person.get("lastName") or "").strip()
    full = f"{first} {last}".strip()
    return full or None


def record_id(record: dict[str, Any], *keys: str) -> int | None:
    for key in keys:
        if record.get(key) is not None:
            try:
                return int(record[key])
            except (TypeError, ValueError):
                continue
    return None
