"""Temporary script: EXPLAIN ANALYZE for representative DB queries (read-only)."""
from __future__ import annotations

import json
import time

from sqlalchemy import func, select, text

from app.db import session_scope
from app.models import PlayerGameStat
from app.repositories import players as players_repo


def _percentile(sorted_vals: list[float], p: float) -> float:
    if not sorted_vals:
        return 0.0
    k = (len(sorted_vals) - 1) * p
    f = int(k)
    c = min(f + 1, len(sorted_vals) - 1)
    if f == c:
        return sorted_vals[f]
    return sorted_vals[f] + (sorted_vals[c] - sorted_vals[f]) * (k - f)


def bench_player_logs(player_id: int, runs: int = 30) -> dict:
    times_ms: list[float] = []
    row_count = 0
    for _ in range(runs):
        with session_scope() as s:
            t0 = time.perf_counter()
            rows = players_repo.player_game_logs(s, player_id)
            elapsed = (time.perf_counter() - t0) * 1000
            times_ms.append(elapsed)
            row_count = len(rows)
    times_ms.sort()
    return {
        "query": "player_game_logs (full history, joinedload game+opponent)",
        "player_id": player_id,
        "runs": runs,
        "rows_returned": row_count,
        "avg_ms": sum(times_ms) / len(times_ms),
        "p50_ms": _percentile(times_ms, 0.5),
        "p95_ms": _percentile(times_ms, 0.95),
    }


def explain_player_logs_indexed(player_id: int) -> str:
    sql = """
    EXPLAIN (ANALYZE, BUFFERS, FORMAT TEXT)
    SELECT pgs.*
    FROM player_game_stats pgs
    WHERE pgs.player_id = :pid
    ORDER BY pgs.game_date DESC
    """
    with session_scope() as s:
        rows = s.execute(text(sql), {"pid": player_id}).all()
    return "\n".join(r[0] for r in rows)


def explain_season_aggregates(player_id: int, season: int) -> str:
    sql = """
    EXPLAIN (ANALYZE, BUFFERS, FORMAT TEXT)
    SELECT season, COUNT(*), AVG(pts::float), AVG(reb::float)
    FROM player_game_stats
    WHERE player_id = :pid AND season = :season AND did_not_play = false
    GROUP BY season
    """
    with session_scope() as s:
        rows = s.execute(text(sql), {"pid": player_id, "season": season}).all()
    return "\n".join(r[0] for r in rows)


def explain_directory_sort_pts() -> str:
    sql = """
    EXPLAIN (ANALYZE, BUFFERS, FORMAT TEXT)
    SELECT p.id, AVG(pgs.pts::float) as pts_avg
    FROM players p
    JOIN player_game_stats pgs ON pgs.player_id = p.id AND pgs.did_not_play = false
    WHERE p.is_active = true
    GROUP BY p.id
    ORDER BY pts_avg DESC NULLS LAST
    LIMIT 50
    """
    with session_scope() as s:
        rows = s.execute(text(sql)).all()
    return "\n".join(r[0] for r in rows)


def main() -> None:
    with session_scope() as s:
        player_id = s.scalar(
            select(PlayerGameStat.player_id)
            .where(PlayerGameStat.did_not_play.is_(False))
            .group_by(PlayerGameStat.player_id)
            .having(func.count() > 80)
            .order_by(func.count().desc())
            .limit(1)
        )
        season = 2026

    out = {
        "bench_full_game_log": bench_player_logs(int(player_id), runs=30),
        "explain_player_game_logs": explain_player_logs_indexed(int(player_id)),
        "explain_season_aggregate": explain_season_aggregates(int(player_id), season),
        "explain_active_directory_pts_sort": explain_directory_sort_pts(),
    }
    print(json.dumps({k: v for k, v in out.items() if k.startswith("bench")}, indent=2))
    print("\n--- EXPLAIN player_game_logs ---\n", out["explain_player_game_logs"])
    print("\n--- EXPLAIN season aggregate ---\n", out["explain_season_aggregate"])
    print("\n--- EXPLAIN directory sort ---\n", out["explain_active_directory_pts_sort"])


if __name__ == "__main__":
    main()