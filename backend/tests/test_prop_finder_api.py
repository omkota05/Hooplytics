"""Prop Finder list cap, global sort, and async refresh behavior."""

from dataclasses import replace
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from app.db import get_db
from app.ingestion.providers.espn import normalize as n
from app.main import app
from app.models import Game
from app.models.sportsbook import PropOffer
from app.services.prop_refresh_worker import PropRefreshState, start_background_import
from app.sync import writer
from tests.fixtures import espn_payloads as fx
from tests.test_api import STAR

TEAM_IDS = {fx.HOME_ID, fx.AWAY_ID, fx.OTHER_ID}


@pytest.fixture
def client(session_factory):
    with session_factory() as s:
        writer.upsert_teams(s, n.normalize_teams_payload(fx.TEAMS_PAYLOAD))
        base = n.normalize_boxscore_payload(fx.summary_payload(event_id=1, date="2099-01-02T00:30Z"))
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
            db_game = s.get(Game, game.id)
            if db_game:
                db_game.status = "scheduled"
        s.commit()

    def override():
        with session_factory() as s:
            yield s

    app.dependency_overrides[get_db] = override
    yield TestClient(app)
    app.dependency_overrides.clear()


def _seed_props(session, count: int, *, player_id: int = STAR, game_id: int = 1000) -> list[float]:
    """Insert `count` matched props with distinct Wilson scores (descending when sorted)."""
    game = session.get(Game, game_id)
    game_start = game.start_time if game else datetime.now(UTC)
    wilsons = [90.0 - (i * 0.5) for i in range(count)]
    for i, wilson in enumerate(wilsons):
        session.add(
            PropOffer(
                source_kind="manual",
                sportsbook_label=f"RankTestBook{i}",
                player_id=player_id,
                game_id=game_id,
                category_key="pts",
                line=10.5 + i * 0.1,
                pick_side="over",
                match_status="matched",
                is_active=True,
                game_start_time=game_start,
                l10_wilson_lb=wilson,
                hcs_score=wilson,
                l10_games=10,
                l20_games=10,
                l10_hits=8,
                l10_attempts=10,
                updated_at=datetime.now(UTC),
            )
        )
    session.commit()
    return wilsons


@pytest.fixture
def prop_client(session_factory, client):
    with session_factory() as s:
        s.execute(PropOffer.__table__.delete())
        _seed_props(s, 150)

    def override():
        with session_factory() as s:
            yield s

    app.dependency_overrides[get_db] = override
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_list_global_sort_before_top_100_cap(prop_client):
    r = prop_client.get("/api/prop-finder", params={"limit": 10, "offset": 0, "min_games": 10})
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 100
    assert body["total_available"] == 150
    assert len(body["rows"]) == 10
    assert body["rows"][0]["sportsbook"] == "RankTestBook0"
    page10 = prop_client.get("/api/prop-finder", params={"limit": 10, "offset": 10, "min_games": 10})
    assert page10.json()["rows"][0]["sportsbook"] == "RankTestBook10"


def test_pagination_within_cap(prop_client):
    last = prop_client.get("/api/prop-finder", params={"limit": 10, "offset": 90, "min_games": 10})
    assert last.status_code == 200
    assert len(last.json()["rows"]) == 10
    beyond = prop_client.get("/api/prop-finder", params={"limit": 10, "offset": 100, "min_games": 10})
    assert beyond.status_code == 200
    assert beyond.json()["rows"] == []


def test_game_filter_before_cap(session_factory, client):
    with session_factory() as s:
        s.execute(PropOffer.__table__.delete())
        _seed_props(s, 30, player_id=STAR, game_id=1000)
        _seed_props(s, 40, player_id=STAR, game_id=1001)

    def override():
        with session_factory() as s:
            yield s

    app.dependency_overrides[get_db] = override
    c = TestClient(app)
    r = c.get("/api/prop-finder", params={"game_id": 1000, "limit": 10, "offset": 0, "min_games": 10})
    assert r.status_code == 200
    body = r.json()
    assert body["total_available"] == 30
    assert body["total"] == 30
    assert all(row["game_id"] == 1000 for row in body["rows"])
    app.dependency_overrides.clear()


def test_refresh_import_returns_202_without_blocking(client, monkeypatch):
    monkeypatch.setattr(
        "app.api.routes.prop_finder.start_background_import",
        lambda: True,
    )
    r = client.post("/api/prop-finder/import")
    assert r.status_code == 202
    assert "refresh_in_progress" in r.json()


def test_concurrent_refresh_prevented(monkeypatch):
    import app.services.prop_refresh_worker as worker

    monkeypatch.setattr(worker, "_state", PropRefreshState(in_progress=True))
    assert start_background_import() is False


def test_reuse_hits_from_offer():
    from app.models.sportsbook import PropOffer
    from app.services.prop_import_service import _reuse_hits_from_offer

    offer = PropOffer(
        source_kind="unabated",
        sportsbook_label="x",
        category_key="pts",
        line=20.5,
        pick_side="over",
        hit_rates={"windows": []},
        hit_cache_id=42,
        hit_computed_at=datetime.now(UTC),
    )
    rates, cache_id, at = _reuse_hits_from_offer(offer)
    assert rates == offer.hit_rates
    assert cache_id == 42
    assert at is not None

    empty = PropOffer(
        source_kind="unabated",
        sportsbook_label="y",
        category_key="pts",
        line=1.0,
        pick_side="over",
    )
    assert _reuse_hits_from_offer(empty) == (None, None, None)
