"""Temporary script: in-process API/service latency (read-only, no server required)."""
from __future__ import annotations

import json
import statistics
import time

from fastapi.testclient import TestClient

from app.main import app
from app.db import session_scope
from app.models import Game, PlayerGameStat
from app.services.recommendation_service import clear_recommendation_cache, generate_recommendations
from app.services.prediction_service import predict_player_stat
from sqlalchemy import func, select


def _pct(sorted_vals: list[float], p: float) -> float:
    if not sorted_vals:
        return 0.0
    k = (len(sorted_vals) - 1) * p
    f = int(k)
    c = min(f + 1, len(sorted_vals) - 1)
    if f == c:
        return sorted_vals[f]
    return sorted_vals[f] + (sorted_vals[c] - sorted_vals[f]) * (k - f)


def summarize(times: list[float]) -> dict:
    times = sorted(times)
    return {
        "runs": len(times),
        "avg_ms": statistics.mean(times),
        "p50_ms": _pct(times, 0.5),
        "p95_ms": _pct(times, 0.95),
        "min_ms": min(times),
        "max_ms": max(times),
    }


def bench_http(client: TestClient, method: str, url: str, *, runs: int = 30) -> dict:
    # warm
    client.request(method, url)
    times = []
    last_body = None
    for _ in range(runs):
        t0 = time.perf_counter()
        r = client.request(method, url)
        times.append((time.perf_counter() - t0) * 1000)
        assert r.status_code == 200, (url, r.status_code, r.text[:200])
        last_body = r.json()
    sample = None
    if isinstance(last_body, dict):
        sample = list(last_body.keys())[:8]
    elif isinstance(last_body, list):
        sample = f"list[{len(last_body)}]"
    return {"endpoint": url, **summarize(times), "response_shape": sample}


def bench_prediction_cold_warm(player_id: int, game_id: int, runs: int = 30) -> dict:
    times = []
    with session_scope() as s:
        for i in range(runs):
            t0 = time.perf_counter()
            predict_player_stat(s, player_id=player_id, game_id=game_id, category_key="pts", line=24.5)
            times.append((time.perf_counter() - t0) * 1000)
    return {
        "service": "predict_player_stat (pts)",
        "player_id": player_id,
        "game_id": game_id,
        **summarize(times),
        "note": "Same session; feature build may cache in-process after first call",
    }


def bench_recommendations_cache(runs: int = 5) -> dict:
    clear_recommendation_cache()
    cold = []
    warm = []
    with session_scope() as s:
        t0 = time.perf_counter()
        first = generate_recommendations(s, days=3, expand_player_props=False)
        cold.append((time.perf_counter() - t0) * 1000)
        for _ in range(runs - 1):
            t0 = time.perf_counter()
            second = generate_recommendations(s, days=3, expand_player_props=False)
            warm.append((time.perf_counter() - t0) * 1000)
    equiv = (
        first.meta.player_props_generated == second.meta.player_props_generated
        and first.meta.upcoming_games_scanned == second.meta.upcoming_games_scanned
    )
    return {
        "cold_once_ms": cold[0],
        "warm_runs": runs - 1,
        "warm": summarize(warm) if warm else None,
        "player_props_generated": first.meta.player_props_generated,
        "cache_output_equivalent": equiv,
    }


def pick_ids() -> tuple[int, int]:
    with session_scope() as s:
        game_id = s.scalar(
            select(Game.id).where(Game.status == "scheduled").order_by(Game.start_time).limit(1)
        )
        if game_id is None:
            game_id = s.scalar(select(Game.id).order_by(Game.start_time.desc()).limit(1))
        player_id = s.scalar(
            select(PlayerGameStat.player_id)
            .group_by(PlayerGameStat.player_id)
            .having(func.count() > 50)
            .order_by(func.count().desc())
            .limit(1)
        )
    return int(player_id), int(game_id)


def main() -> None:
    player_id, game_id = pick_ids()
    client = TestClient(app)
    report = {
        "ids": {"player_id": player_id, "game_id": game_id},
        "http": [
            bench_http(client, "GET", f"/api/players/{player_id}"),
            bench_http(client, "GET", f"/api/players/{player_id}/game-logs?limit=82"),
            bench_http(client, "GET", f"/api/players/{player_id}/stat-analysis?stat=pts&line=24.5&window=last_n&n=82"),
            bench_http(client, "GET", f"/api/predictions/player-stat?player_id={player_id}&game_id={game_id}&stat=pts&line=24.5"),
            bench_http(client, "GET", "/api/predictions/metrics"),
        ],
        "recommendations_cache": bench_recommendations_cache(runs=6),
        "prediction_service_direct": bench_prediction_cold_warm(player_id, game_id, runs=30),
    }
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()