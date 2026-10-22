"""Endpoint tests over synthetic box scores in the test database."""

from dataclasses import replace

import pytest
from fastapi.testclient import TestClient

from app.db import get_db
from app.ingestion.providers.espn import normalize as n
from app.main import app
from app.sync import writer
from tests.fixtures import espn_payloads as fx

TEAM_IDS = {fx.HOME_ID, fx.AWAY_ID, fx.OTHER_ID}
STAR = 101  # synthetic "Testy McTestface" on the home fixture team


@pytest.fixture
def client(session_factory):
    with session_factory() as s:
        writer.upsert_teams(s, n.normalize_teams_payload(fx.TEAMS_PAYLOAD))
        base = n.normalize_boxscore_payload(fx.summary_payload(event_id=1, date="2099-01-02T00:30Z"))
        # Five games: points 27, 20, 15, 30, 20; games 2 and 4 are vs OTHER_ID.
        for i, (pts, opp) in enumerate(
            [(27, fx.AWAY_ID), (20, fx.OTHER_ID), (15, fx.AWAY_ID), (30, fx.OTHER_ID), (20, fx.AWAY_ID)]
        ):
            game = replace(
                base.game,
                id=1000 + i,
                away_team_id=opp,
                start_time=base.game.start_time.replace(day=2 + i),
                game_date=base.game.game_date.replace(day=1 + i),
            )
            stats = [
                replace(s, game_id=game.id, opponent_team_id=opp, pts=pts if s.player_id == STAR else s.pts)
                for s in base.stats
                if s.team_id == fx.HOME_ID
            ]
            writer.write_boxscore(s, replace(base, game=game, stats=stats), TEAM_IDS)
        s.commit()

    def override():
        with session_factory() as s:
            yield s

    app.dependency_overrides[get_db] = override
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_last_n_analysis(client):
    r = client.get(f"/api/players/{STAR}/stat-analysis", params={"stat": "pts", "line": 20, "n": 4})
    assert r.status_code == 200
    body = r.json()
    assert [g["value"] for g in body["games"]] == [20, 15, 30, 20]  # chronological
    lr = body["line_result"]
    assert (lr["over"], lr["under"], lr["push"], lr["total"]) == (1, 1, 2, 4)
    assert lr["over_pct"] == 25.0 and lr["push_pct"] == 50.0
    assert body["distribution"]["mean"] == 21.25
    assert body["small_sample"] is True


def test_combined_category_via_api(client):
    r = client.get(
        f"/api/players/{STAR}/stat-analysis", params={"stat": "pts_reb_ast", "line": 40.5, "window": "all"}
    )
    games = r.json()["games"]
    assert all(g["value"] == g["components"]["pts"] + 6 + 8 for g in games)  # fixture reb=6, ast=8


def test_head_to_head_only_includes_that_opponent(client):
    r = client.get(
        f"/api/players/{STAR}/stat-analysis",
        params={"stat": "pts", "line": 24.5, "window": "all", "opponent_id": fx.OTHER_ID},
    )
    body = r.json()
    assert {g["opponent"]["id"] for g in body["games"]} == {fx.OTHER_ID}
    assert [g["value"] for g in body["games"]] == [20, 30]
    assert body["opponent"]["abbreviation"] == "FXT"
    assert "vs FXT" in body["note"]


def test_matchup_comparison(client):
    r = client.get(
        f"/api/players/{STAR}/matchup-comparison",
        params={"opponent_id": fx.AWAY_ID, "stat": "pts", "line": 19.5, "recent_n": 2},
    )
    body = r.json()
    assert body["recent"]["distribution"]["count"] == 2
    assert [g["value"] for g in body["head_to_head"]["games"]] == [27, 15, 20]


def test_validation_errors(client):
    assert client.get(f"/api/players/{STAR}/stat-analysis", params={"stat": "dunks"}).status_code == 400
    assert client.get(f"/api/players/{STAR}/stat-analysis", params={"window": "season"}).status_code == 400
    assert client.get(f"/api/players/{STAR}/stat-analysis", params={"line": -2}).status_code == 422
    assert client.get("/api/players/999999/stat-analysis").status_code == 404


def test_search_and_profile(client):
    results = client.get("/api/players/search", params={"q": "testy"}).json()
    assert results[0]["id"] == STAR
    profile = client.get(f"/api/players/{STAR}").json()
    assert profile["total_games_tracked"] == 5
    assert profile["season_averages"]["games"] == 5
    assert profile["team_history"][0]["games_played"] == 5
