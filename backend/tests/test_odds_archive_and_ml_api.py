"""Odds snapshot archive, settlement, and v2 ML API integration (DB-backed)."""

from datetime import UTC, date, datetime, timedelta
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text

from app.config import get_settings
from app.db import get_db
from app.main import app
from app.models import Game, Player, PlayerGameStat, Team
from app.models.sportsbook import PropImportRun, PropOffer, PropOfferSnapshot
from app.services.odds_archive_service import (
    archive_status,
    backfill_last_seen_pregame,
    record_import_snapshots,
    settle_snapshots,
)

T0 = datetime(2026, 11, 1, 23, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _clean_prop_tables(session_factory):
    with session_factory() as s:
        s.execute(text("TRUNCATE prop_offer_snapshots, prop_offers, prop_import_runs RESTART IDENTITY CASCADE"))
        s.commit()


def _seed(s):
    s.add_all([
        Team(id=1, abbreviation="AAA", display_name="Alpha", short_name="Alpha", location="A"),
        Team(id=2, abbreviation="BBB", display_name="Beta", short_name="Beta", location="B"),
    ])
    s.add_all([
        Player(id=11, full_name="Scorer One", search_name="scorer one", current_team_id=1, is_active=True),
        Player(id=12, full_name="Bench Two", search_name="bench two", current_team_id=1, is_active=True),
        Player(id=13, full_name="Missing Three", search_name="missing three", current_team_id=1, is_active=True),
    ])
    s.add(Game(id=500, season=2027, season_type=2, start_time=T0, game_date=T0.date(), home_team_id=1, away_team_id=2,
               home_score=110, away_score=100, status="final", boxscore_synced_at=T0 + timedelta(hours=3)))
    s.flush()
    common = dict(game_id=500, team_id=1, opponent_team_id=2, game_date=T0.date(), season=2027, season_type=2, is_home=True)
    s.add_all([
        PlayerGameStat(player_id=11, minutes=34, pts=25, reb=5, ast=4, fg3m=3, **common),
        PlayerGameStat(player_id=12, did_not_play=True, **common),
    ])
    s.add(PropImportRun(id=1, status="success"))
    s.flush()


def _offer(s, *, pid, line, side="over", odds=-110, cat="pts", updated=None, imported=None, book="FanDuel"):
    o = PropOffer(source_kind="unabated", sportsbook_label=book, player_id=pid, game_id=500, category_key=cat, line=line,
                  pick_side=side, american_odds=odds, unabated_event_id=9, unabated_person_id=pid, unabated_bet_type_id=1,
                  game_start_time=T0, match_status="matched", is_active=True)
    s.add(o)
    s.flush()
    if updated or imported:
        s.execute(text("UPDATE prop_offers SET updated_at=:u, imported_at=:i WHERE id=:id"),
                  {"u": updated or imported, "i": imported or updated, "id": o.id})
    return o


def test_snapshots_extend_on_same_price_and_version_on_change(session):
    _seed(session)
    o = _offer(session, pid=11, line=24.5)
    t1 = T0 - timedelta(hours=6)
    session.execute(text("UPDATE prop_offers SET updated_at=:t"), {"t": t1})
    assert record_import_snapshots(session, import_run_id=1, observed_at=t1)["snapshots_inserted"] == 1
    t2 = T0 - timedelta(hours=3)
    session.execute(text("UPDATE prop_offers SET updated_at=:t"), {"t": t2})
    r = record_import_snapshots(session, import_run_id=1, observed_at=t2)
    assert r == {"snapshots_extended": 1, "snapshots_closed": 0, "snapshots_inserted": 0}
    t3 = T0 - timedelta(hours=1)
    session.execute(text("UPDATE prop_offers SET updated_at=:t, american_odds=-125"), {"t": t3})
    r = record_import_snapshots(session, import_run_id=1, observed_at=t3)
    assert r["snapshots_closed"] == 1 and r["snapshots_inserted"] == 1
    snaps = session.scalars(select(PropOfferSnapshot).where(PropOfferSnapshot.offer_id == o.id).order_by(PropOfferSnapshot.id)).all()
    assert [x.american_odds for x in snaps] == [-110, -125]
    assert snaps[0].first_observed_at == t1 and snaps[0].last_observed_at == t2 and snaps[0].observation_count == 2
    assert not snaps[0].is_latest and snaps[1].is_latest


def test_backfill_only_pregame_and_settlement_outcomes(session):
    _seed(session)
    pre = T0 - timedelta(hours=2)
    _offer(session, pid=11, line=24.5, updated=pre, imported=pre - timedelta(hours=5))           # hit
    _offer(session, pid=11, line=25.5, updated=pre, imported=pre, book="DraftKings")              # miss
    _offer(session, pid=11, line=25.0, updated=pre, imported=pre, book="Caesars")                 # push
    _offer(session, pid=11, line=24.5, side="under", updated=pre, imported=pre, book="BetMGM")    # miss
    _offer(session, pid=12, line=8.5, updated=pre, imported=pre)                                  # DNP -> void
    _offer(session, pid=13, line=8.5, updated=pre, imported=pre)                                  # no box row
    _offer(session, pid=11, line=30.5, updated=T0 + timedelta(minutes=30), imported=pre, book="Live")  # seen after tip
    assert backfill_last_seen_pregame(session) == 6
    counts = settle_snapshots(session)
    assert counts == {"hit": 1, "miss": 2, "push": 1, "void_dnp": 1, "unresolved": 1}
    st = archive_status(session)
    assert st["snapshots"] == 6 and st["graded"] == 4 and st["pregame_observations"] == 6
    assert settle_snapshots(session) == {}  # idempotent


@pytest.fixture
def client(session_factory):
    def override():
        with session_factory() as s:
            yield s

    app.dependency_overrides[get_db] = override
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_ml_endpoints_report_missing_model_without_fabricating(client, monkeypatch):
    from app.ml.engine import artifacts as art
    from app.ml.engine.service import get_engine_service

    monkeypatch.setattr(art, "active_version", lambda: None)
    get_engine_service().reset()
    r = client.get("/api/ml/status")
    assert r.status_code == 200
    body = r.json()
    assert body["loaded"] is False and any(w.startswith("artifact_load_failed") for w in body["warnings"])
    r = client.get("/api/ml/projections/prop", params={"player_id": 1, "game_id": 1, "category": "pts", "line": 20.5})
    assert r.status_code == 503
    get_engine_service().reset()


def test_ml_pages_never_train_or_call_unabated(client):
    from app.ml.engine.service import get_engine_service

    get_engine_service().reset()
    with patch("app.ml.engine.training.train_engine", side_effect=AssertionError("trained on request")), patch(
        "app.odds.unabated.client.UnabatedClient.instance", side_effect=AssertionError("Unabated called")
    ):
        for url in ("/api/ml/status", "/api/ml/comparison", "/api/ml/comparison?prizepicks_only=true", "/api/prop-finder"):
            assert client.get(url).status_code in (200, 503), url


def test_comparison_withholds_probabilities_unless_flag_and_gate(client, session_factory, monkeypatch):
    from app.ml.engine import artifacts as art
    from app.ml.engine.service import get_engine_service

    if not art.active_version():
        pytest.skip("No trained v2 model in artifacts/ml_engine")
    with session_factory() as s:
        _seed(s)
        s.add(Game(id=501, season=2027, season_type=2, start_time=datetime.now(UTC) + timedelta(days=1),
                   game_date=date.today() + timedelta(days=1), home_team_id=1, away_team_id=2, status="scheduled"))
        for k in range(12):
            g = 400 + k
            t = T0 - timedelta(days=2 * (k + 1))
            s.add(Game(id=g, season=2027, season_type=2, start_time=t, game_date=t.date(), home_team_id=1, away_team_id=2,
                       home_score=100, away_score=90, status="final", boxscore_synced_at=t))
            s.flush()
            for pid in (11, 12):
                s.add(PlayerGameStat(player_id=pid, game_id=g, team_id=1, opponent_team_id=2, game_date=t.date(), season=2027,
                                     season_type=2, is_home=True, minutes=30, pts=20 + k % 5, reb=6, ast=4, fg3m=2, fga=15, fg3a=5, fta=4, oreb=1, tov=2))
        s.add(PropOffer(source_kind="unabated", sportsbook_label="PrizePicks", player_id=11, game_id=501, category_key="pts",
                        line=21.5, pick_side="over", match_status="matched", is_active=True, game_start_time=datetime.now(UTC) + timedelta(days=1)))
        s.add(PropOffer(source_kind="unabated", sportsbook_label="PrizePicks", player_id=11, game_id=501, category_key="fg3m",
                        line=1.5, pick_side="over", match_status="matched", is_active=True, game_start_time=datetime.now(UTC) + timedelta(days=1)))
        s.commit()
    get_engine_service().reset()
    settings = get_settings()
    monkeypatch.setattr(settings, "enable_ml_probabilities", False)
    body = client.get("/api/ml/comparison", params={"prizepicks_only": True}).json()
    assert body["mode"] == "experimental_comparison"
    assert body["total"] == 2
    assert all(r["p_side"] is None for r in body["rows"])
    monkeypatch.setattr(settings, "enable_ml_probabilities", True)
    get_engine_service().reset()
    rows = {r["category"]: r for r in client.get("/api/ml/comparison", params={"prizepicks_only": True}).json()["rows"]}
    status = get_engine_service().bundle().probability_status
    for cat, row in rows.items():
        if status.get(cat) == "unavailable":
            assert row["p_side"] is None and not row["eligible"]
        else:
            assert 0 < row["p_side"] < 1
    proj = client.get("/api/ml/projections/player/11", params={"game_id": 501}).json()
    cats = {c["category"]: c for c in proj["categories"]}
    assert cats["pts_reb_ast"]["mean"] == pytest.approx(
        round(cats["pts"]["mean"] + cats["reb"]["mean"] + cats["ast"]["mean"], 2), abs=0.02
    )
    assert all(c["p10"] <= c["median"] <= c["p90"] for c in proj["categories"])
    # Second request is served from the per-snapshot cache.
    assert client.get("/api/ml/projections/player/11", params={"game_id": 501}).status_code == 200
    get_engine_service().reset()
