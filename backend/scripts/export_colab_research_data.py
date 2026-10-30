#!/usr/bin/env python3
"""Read-only export of completed NBA player-game data for offline Colab research.

Usage (from backend/):
    PYTHONPATH=. .venv/bin/python scripts/export_colab_research_data.py

Writes to ../research_export/ at the repository root. Does not modify the database.
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Engine

from app.config import BACKEND_DIR, get_settings
from app.db import DatabaseNotConfiguredError, make_engine

REPO_ROOT = BACKEND_DIR.parent
EXPORT_DIR = REPO_ROOT / "research_export"

# --- SQL (read-only selects) ---

TEAMS_SQL = """
SELECT id, abbreviation, display_name, short_name, location, is_active
FROM teams
ORDER BY id
"""

PLAYERS_SQL = """
SELECT id, full_name, position, jersey, current_team_id, is_active
FROM players
ORDER BY id
"""

GAMES_SQL = """
SELECT
    g.id AS game_id,
    g.season,
    g.season_type,
    g.start_time,
    g.game_date,
    g.home_team_id,
    g.away_team_id,
    g.home_score,
    g.away_score,
    g.status,
    g.neutral_site,
    g.venue_name,
    g.venue_city,
    g.venue_state,
    g.boxscore_synced_at
FROM games g
WHERE g.status = 'final'
ORDER BY g.game_date, g.id
"""

PLAYER_GAME_STATS_SQL = """
SELECT
    pgs.id,
    pgs.player_id,
    pgs.game_id,
    pgs.team_id,
    pgs.opponent_team_id,
    pgs.game_date,
    pgs.season,
    pgs.season_type,
    pgs.is_home,
    pgs.starter,
    pgs.did_not_play,
    pgs.dnp_reason,
    pgs.minutes,
    pgs.pts,
    pgs.reb,
    pgs.ast,
    pgs.stl,
    pgs.blk,
    pgs.tov,
    pgs.fgm,
    pgs.fga,
    pgs.fg3m,
    pgs.fg3a,
    pgs.ftm,
    pgs.fta,
    pgs.oreb,
    pgs.dreb,
    pgs.pf,
    pgs.plus_minus
FROM player_game_stats pgs
INNER JOIN games g ON g.id = pgs.game_id
WHERE g.status = 'final'
ORDER BY pgs.game_date, pgs.game_id, pgs.player_id
"""

PLAYER_TEAM_SEASONS_SQL = """
SELECT player_id, team_id, season, games_played, first_game_date, last_game_date
FROM player_team_seasons
ORDER BY season DESC, player_id, team_id
"""

PROP_ARCHIVE_NOTE_SQL = """
SELECT
    (SELECT COUNT(*) FROM prop_offers WHERE is_active = true) AS active_prop_offers,
    (SELECT COUNT(*) FROM prop_line_hit_cache) AS line_hit_cache_rows,
    (SELECT MAX(finished_at) FROM prop_import_runs WHERE status = 'success') AS last_prop_import_success
"""


def _safe_db_label(database_url: str) -> str:
    parsed = urlparse(database_url)
    host = parsed.hostname or "unknown-host"
    db = (parsed.path or "").lstrip("/") or "unknown-db"
    return f"{host}/{db}"


def _read_only_engine() -> Engine:
    settings = get_settings()
    if not settings.database_url:
        raise DatabaseNotConfiguredError("DATABASE_URL is not configured.")
    return make_engine(settings.database_url)


def _fetch_dataframe(engine: Engine, sql: str, name: str) -> pd.DataFrame:
    with engine.connect() as conn:
        trans = conn.begin()
        try:
            conn.execute(text("SET TRANSACTION READ ONLY"))
            df = pd.read_sql(text(sql), conn)
        finally:
            trans.rollback()
    print(f"  loaded {name}: {len(df):,} rows", file=sys.stderr)
    return df


def _validate_export(
    teams: pd.DataFrame,
    players: pd.DataFrame,
    games: pd.DataFrame,
    pgs: pd.DataFrame,
    pts: pd.DataFrame,
) -> dict:
    issues: list[str] = []
    warnings: list[str] = []

    if games.empty:
        issues.append("games_completed is empty — no final games in database.")
    if pgs.empty:
        issues.append("player_game_stats is empty for final games.")

    if not games.empty and (games["status"] != "final").any():
        issues.append("Non-final games present in games export.")

    game_ids = set(games["game_id"].astype(int))
    orphan = pgs[~pgs["game_id"].isin(game_ids)]
    if len(orphan):
        issues.append(f"{len(orphan)} player_game_stats rows reference games not in export.")

    missing_player = pgs[~pgs["player_id"].isin(players["id"])]
    if len(missing_player):
        warnings.append(f"{len(missing_player)} stat rows reference player_ids not in players export.")

    played = pgs[~pgs["did_not_play"]]
    null_minutes_played = played["minutes"].isna().sum()
    if null_minutes_played:
        warnings.append(
            f"{int(null_minutes_played)} played rows (did_not_play=false) have null minutes."
        )

    dnp_count = int(pgs["did_not_play"].sum())
    if dnp_count:
        warnings.append(f"{dnp_count} rows are did_not_play=true (included for completeness).")

    return {
        "valid": len(issues) == 0,
        "issues": issues,
        "warnings": warnings,
        "row_counts": {
            "teams": len(teams),
            "players": len(players),
            "games_completed": len(games),
            "player_game_stats": len(pgs),
            "player_team_seasons": len(pts),
            "player_game_stats_played": int((~pgs["did_not_play"]).sum()) if len(pgs) else 0,
        },
    }


def _schema_summary() -> dict:
    return {
        "teams": {
            "description": "NBA teams (ESPN ids).",
            "primary_key": ["id"],
            "columns": {
                "id": "int — ESPN team id",
                "abbreviation": "str",
                "display_name": "str",
                "short_name": "str",
                "location": "str",
                "is_active": "bool",
            },
        },
        "players": {
            "description": "Players; current_team_id is roster snapshot, not historical team per game.",
            "primary_key": ["id"],
            "columns": {
                "id": "int — ESPN player id",
                "full_name": "str",
                "position": "str|null",
                "jersey": "str|null",
                "current_team_id": "int|null — current roster only",
                "is_active": "bool",
            },
        },
        "games_completed": {
            "description": "Final-status games only (status='final').",
            "primary_key": ["game_id"],
            "columns": {
                "game_id": "int — ESPN event id",
                "season": "int — ending year (2026 = 2025-26 season)",
                "season_type": "int — 2=regular, 3=playoffs, 5=play-in",
                "start_time": "timestamptz UTC",
                "game_date": "date — US/Eastern calendar date",
                "home_team_id": "int",
                "away_team_id": "int",
                "home_score": "int|null",
                "away_score": "int|null",
                "status": "str — always 'final' in this export",
            },
        },
        "player_game_stats": {
            "description": "Box score lines for final games only. Use did_not_play to filter playing time.",
            "primary_key": ["id"],
            "foreign_keys": {
                "player_id": "players.id",
                "game_id": "games_completed.game_id",
                "team_id": "teams.id",
                "opponent_team_id": "teams.id",
            },
            "columns": {
                "minutes": "float|null — null when DNP or missing box score field",
                "did_not_play": "bool",
                "pts": "int|null — null when DNP",
            },
        },
        "player_team_seasons": {
            "description": "Derived team membership per season from box scores.",
            "primary_key": ["player_id", "team_id", "season"],
        },
        "not_included": {
            "historical_pregame_sportsbook_lines": (
                "Current Unabated prop offers and prop_line_hit_cache are NOT exported. "
                "They do not constitute timestamped historical betting lines suitable for "
                "probability calibration research."
            ),
            "ml_artifacts": "Not exported.",
        },
    }


def _write_schema_markdown(schema: dict, path: Path) -> None:
    lines = ["# Hooplytics research export — schema summary", ""]
    for table, meta in schema.items():
        if table == "not_included":
            continue
        lines.append(f"## `{table}`")
        lines.append("")
        lines.append(meta.get("description", ""))
        lines.append("")
        if "primary_key" in meta:
            lines.append(f"- **Primary key:** `{', '.join(meta['primary_key'])}`")
        if "foreign_keys" in meta:
            lines.append("- **Foreign keys:**")
            for col, ref in meta["foreign_keys"].items():
                lines.append(f"  - `{col}` → `{ref}`")
        if "columns" in meta:
            lines.append("- **Columns:**")
            for col, desc in meta["columns"].items():
                lines.append(f"  - `{col}`: {desc}")
        lines.append("")
    lines.append("## Not included")
    lines.append("")
    for k, v in schema.get("not_included", {}).items():
        lines.append(f"- **{k}:** {v}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)

    try:
        engine = _read_only_engine()
    except DatabaseNotConfiguredError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    db_label = _safe_db_label(get_settings().database_url)
    print(f"Export target: {EXPORT_DIR}", file=sys.stderr)
    print(f"Database (read-only): {db_label}", file=sys.stderr)

    print("Fetching tables…", file=sys.stderr)
    teams = _fetch_dataframe(engine, TEAMS_SQL, "teams")
    players = _fetch_dataframe(engine, PLAYERS_SQL, "players")
    games = _fetch_dataframe(engine, GAMES_SQL, "games_completed")
    pgs = _fetch_dataframe(engine, PLAYER_GAME_STATS_SQL, "player_game_stats")
    pts = _fetch_dataframe(engine, PLAYER_TEAM_SEASONS_SQL, "player_team_seasons")

    with engine.connect() as conn:
        trans = conn.begin()
        try:
            conn.execute(text("SET TRANSACTION READ ONLY"))
            prop_note = pd.read_sql(text(PROP_ARCHIVE_NOTE_SQL), conn).iloc[0].to_dict()
        finally:
            trans.rollback()

    validation = _validate_export(teams, players, games, pgs, pts)
    schema = _schema_summary()

    generated_at = datetime.now(UTC).isoformat()
    files_written: dict[str, dict] = {}

    datasets = {
        "teams.csv": teams,
        "players.csv": players,
        "games_completed.csv": games,
        "player_game_stats.csv": pgs,
        "player_team_seasons.csv": pts,
    }

    for filename, df in datasets.items():
        path = EXPORT_DIR / filename
        df.to_csv(path, index=False)
        files_written[filename] = {
            "path": str(path.relative_to(REPO_ROOT)),
            "rows": len(df),
            "bytes": path.stat().st_size,
            "columns": list(df.columns),
        }

    schema_path = EXPORT_DIR / "schema_summary.json"
    schema_path.write_text(json.dumps(schema, indent=2) + "\n", encoding="utf-8")
    md_path = EXPORT_DIR / "schema_summary.md"
    _write_schema_markdown(schema, md_path)

    quality_path = EXPORT_DIR / "data_quality_report.json"
    quality_path.write_text(json.dumps(validation, indent=2) + "\n", encoding="utf-8")

    manifest = {
        "generated_at_utc": generated_at,
        "database_label": db_label,
        "read_only": True,
        "command_hint": "cd backend && PYTHONPATH=. .venv/bin/python scripts/export_colab_research_data.py",
        "files": files_written,
        "validation": validation,
        "prop_sportsbook_snapshot_note": {
            **{k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in prop_note.items()},
            "disclaimer": (
                "These counts describe the live app database, not exported CSVs. "
                "No historical pregame sportsbook line archive is included in this export."
            ),
        },
        "limitations": [
            "Only games with status='final' are exported.",
            "player_team_seasons and players.current_team_id are derived snapshots; "
            "use player_game_stats.team_id for historical team in a given game.",
            "No timestamped historical sportsbook odds or settled prop outcomes.",
            "Injury reports and non-box-score context are not included.",
        ],
    }
    manifest_path = EXPORT_DIR / "export_manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, default=str) + "\n", encoding="utf-8")

    print("\nVerifying CSV readability with pandas…", file=sys.stderr)
    for filename in datasets:
        path = EXPORT_DIR / filename
        check = pd.read_csv(path)
        if len(check) != files_written[filename]["rows"]:
            print(f"  FAIL row count mismatch for {filename}", file=sys.stderr)
            return 2
        print(f"  OK {filename} ({len(check):,} rows)", file=sys.stderr)

    if not validation["valid"]:
        print("\nValidation issues:", file=sys.stderr)
        for issue in validation["issues"]:
            print(f"  - {issue}", file=sys.stderr)
        return 2

    print(f"\nExport complete → {EXPORT_DIR}", file=sys.stderr)
    print(json.dumps({"manifest": str(manifest_path.relative_to(REPO_ROOT)), "validation": validation["row_counts"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
