"""Prospective forecast archive: pregame-only, write-once, deduplicated, idempotent settlement (DB-backed)."""

from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, IntegrityError

from app.db import get_db
from app.main import app
from app.models import Game, Player, PlayerGameStat, Team
from app.models.sportsbook import PropOffer, PropOfferSnapshot
from app.services.forecast_archive_service import forecast_summary, record_forecasts, settle_forecasts

TIP = datetime.now(UTC).replace(microsecond=0) + timedelta(days=1)


@pytest.fixture(autouse=True)
def _requires_model_and_clean(session_factory):
    from app.ml.engine import artifacts as art
    from app.ml.engine.service import get_engine_service

    if not art.active_version():
        pytest.skip("No trained v2 model in artifacts/ml_engine")
    with session_factory() as s:
        s.execute(text("TRUNCATE ml_forecast_lines, ml_forecasts, prop_offer_snapshots, prop_offers, prop_import_runs RESTART IDENTITY CASCADE"))
        s.commit()
    get_engine_service().reset()
    yield
    get_engine_service().reset()


def _seed(s):
    s.add_all([
        Team(id=1, abbreviation="AAA", display_name="Alpha", short_name="Alpha", location="A"),
        Team(id=2, abbreviation="BBB", display_name="Beta", short_name="Beta", location="B"),
    ])
    s.add_all([
        Player(id=pid, full_name=f"Player {pid}", search_name=f"player {pid}", current_team_id=1, is_active=True)
        for pid in (11, 12, 13)
    ])
    s.flush()
    for k in range(12):
        t = TIP - timedelta(days=3 * (k + 1))
        s.add(Game(id=400 + k, season=2027, season_type=2, start_time=t, game_date=t.date(), home_team_id=1, away_team_id=2,
                   home_score=100, away_score=90, status="final", boxscore_synced_at=t))
        s.flush()
        for pid in (11, 12, 13):
            s.add(PlayerGameStat(player_id=pid, game_id=400 + k, team_id=1, opponent_team_id=2, game_date=t.date(), season=2027,
                                 season_type=2, is_home=True, minutes=30, pts=20 + k % 5, reb=6, ast=4, fg3m=2, fga=15, fg3a=5,
                                 fta=4, oreb=1, tov=2))
    s.add(Game(id=501, season=2027, season_type=2, start_time=TIP, game_date=TIP.date(), home_team_id=1, away_team_id=2, status="scheduled"))
    s.commit()


def _finish_game(s, *, include_13: bool):
    s.execute(text("UPDATE games SET status='final', boxscore_synced_at=now(), home_score=101, away_score=99 WHERE id=501"))
    common = dict(game_id=501, team_id=1, opponent_team_id=2, game_date=TIP.date(), season=2027, season_type=2, is_home=True)
    s.add(PlayerGameStat(player_id=11, minutes=31, pts=25, reb=7, ast=3, fg3m=4, **common))
    s.add(PlayerGameStat(player_id=12, did_not_play=True, **common))
    if include_13:
        s.add(PlayerGameStat(player_id=13, minutes=20, pts=9, reb=2, ast=1, fg3m=1, **common))
    s.commit()


def test_records_pregame_forecasts_once_and_rejects_edits(session_factory):
    with session_factory() as s:
        _seed(s)
        first = record_forecasts(s)
        s.commit()
        assert first["candidates"] == 3 and first["inserted"] == 3
        again = record_forecasts(s)
        s.commit()
        assert again["inserted"] == 0 and again["already_recorded"] == 3
        row = s.execute(text("SELECT * FROM ml_forecasts WHERE player_id = 11")).mappings().one()
        assert row["predicted_at"] < row["scheduled_tipoff"] and row["status"] == "pending"
        q = row["quantiles"]["pts_reb_ast"]
        assert q["p05"] <= q["p10"] <= q["p25"] <= q["p50"] <= q["p75"] <= q["p90"] <= q["p95"]
        assert row["proj_pts_reb_ast"] == pytest.approx(row["proj_pts"] + row["proj_reb"] + row["proj_ast"], abs=1e-3)
        assert set(row["baselines"]) >= {"weighted", "last_10", "season_avg"}
        with pytest.raises(DBAPIError, match="immutable"):
            s.execute(text("UPDATE ml_forecasts SET proj_pts = proj_pts + 1 WHERE player_id = 11"))
        s.rollback()
        with pytest.raises(DBAPIError, match="append-only"):
            s.execute(text("DELETE FROM ml_forecasts WHERE player_id = 11"))
        s.rollback()
        s.execute(text("UPDATE ml_forecasts SET status = 'pending' WHERE player_id = 11"))  # settlement columns stay writable
        s.commit()


def test_no_forecast_at_or_after_tipoff(session_factory):
    with session_factory() as s:
        _seed(s)
        assert record_forecasts(s, now=TIP + timedelta(minutes=1))["candidates"] == 0
        assert record_forecasts(s, now=TIP)["candidates"] == 0
        s.commit()
        with pytest.raises(IntegrityError, match="ck_ml_forecast_pregame"):
            s.execute(text(
                """INSERT INTO ml_forecasts (player_id, game_id, team_id, opponent_team_id, predicted_at, scheduled_tipoff, model_version,
                   feature_version, data_snapshot, appearances, season_appearances, projected_minutes, proj_pts, proj_reb, proj_ast,
                   proj_fg3m, proj_pts_reb, proj_pts_ast, proj_reb_ast, proj_pts_reb_ast, quantiles, baselines, context, warnings,
                   probability_status)
                   VALUES (11, 501, 1, 2, :t, :t, 'x', 'x', 'x', 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, '{}', '{}', '{}', '[]', '{}')"""
            ), {"t": TIP})


def test_lines_attached_only_when_observed_before_tipoff(session_factory):
    with session_factory() as s:
        _seed(s)
        o = PropOffer(source_kind="unabated", sportsbook_label="PrizePicks", player_id=11, game_id=501, category_key="pts", line=21.5,
                      pick_side="over", american_odds=-120, match_status="matched", is_active=True, game_start_time=TIP)
        s.add(o)
        s.flush()
        seen = datetime.now(UTC) - timedelta(minutes=5)
        s.add(PropOfferSnapshot(offer_id=o.id, origin="import", source_kind="unabated", sportsbook_label="PrizePicks", player_id=11,
                                game_id=501, category_key="pts", line=21.5, pick_side="over", american_odds=-120, game_start_time=TIP,
                                first_observed_at=seen, last_observed_at=seen))
        s.commit()
        stats = record_forecasts(s)
        s.commit()
        assert stats["lines_inserted"] == 1
        assert record_forecasts(s)["lines_inserted"] == 0
        line = s.execute(text("SELECT * FROM ml_forecast_lines")).mappings().one()
        assert line["offer_observed_at"] < line["recorded_at"] < line["scheduled_tipoff"]
        assert 0 < line["model_p_over"] < 1
        with pytest.raises(IntegrityError, match="ck_ml_forecast_line_pregame"):
            s.execute(text(
                """INSERT INTO ml_forecast_lines (forecast_id, sportsbook_label, category_key, line, pick_side, offer_observed_at,
                   recorded_at, scheduled_tipoff, model_mean) VALUES (:f, 'Book', 'pts', 30.5, 'over', :late, :now, :tip, 20)"""
            ), {"f": line["forecast_id"], "late": TIP + timedelta(minutes=1), "now": datetime.now(UTC), "tip": TIP})
        s.rollback()
        with pytest.raises(DBAPIError, match="append-only"):
            s.execute(text("UPDATE ml_forecast_lines SET line = 99"))


def test_settlement_outcomes_are_correct_and_idempotent(session_factory):
    with session_factory() as s:
        _seed(s)
        record_forecasts(s)
        s.commit()
        assert settle_forecasts(s) == {}  # game not final yet
        _finish_game(s, include_13=False)
        assert settle_forecasts(s) == {"settled": 1, "void_dnp": 1, "unresolved": 1}
        s.commit()
        assert settle_forecasts(s) == {}
        r11 = s.execute(text("SELECT * FROM ml_forecasts WHERE player_id = 11")).mappings().one()
        assert (r11["status"], r11["actual_pts"], r11["actual_fg3m"], r11["actual_minutes"]) == ("settled", 25, 4, 31)
        r12 = s.execute(text("SELECT status, actual_pts FROM ml_forecasts WHERE player_id = 12")).one()
        assert r12 == ("void_dnp", None)
        # A late box-score row resolves the previously unresolved forecast exactly once.
        s.add(PlayerGameStat(player_id=13, game_id=501, team_id=1, opponent_team_id=2, game_date=TIP.date(), season=2027, season_type=2,
                             is_home=True, minutes=20, pts=9, reb=2, ast=1, fg3m=1))
        s.commit()
        assert settle_forecasts(s) == {"settled": 1}
        assert settle_forecasts(s) == {}
        s.commit()
        # Postponed games void their forecasts.
        s.add(Game(id=503, season=2027, season_type=2, start_time=TIP + timedelta(days=2), game_date=(TIP + timedelta(days=2)).date(),
                   home_team_id=1, away_team_id=2, status="postponed"))
        s.flush()
        s.execute(text(
            """INSERT INTO ml_forecasts (player_id, game_id, team_id, opponent_team_id, predicted_at, scheduled_tipoff, model_version,
               feature_version, data_snapshot, appearances, season_appearances, projected_minutes, proj_pts, proj_reb, proj_ast,
               proj_fg3m, proj_pts_reb, proj_pts_ast, proj_reb_ast, proj_pts_reb_ast, quantiles, baselines, context, warnings,
               probability_status)
               VALUES (11, 503, 1, 2, now(), :t, 'x', 'x', 'x', 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, '{}', '{}', '{}', '[]', '{}')"""
        ), {"t": TIP + timedelta(days=2)})
        assert settle_forecasts(s) == {"void_game": 1}
        s.commit()


def test_prospective_endpoint_is_read_only_and_flags_small_samples(session_factory):
    with session_factory() as s:
        _seed(s)
        record_forecasts(s)
        s.commit()
        _finish_game(s, include_13=True)
        settle_forecasts(s)
        s.commit()
        summary = forecast_summary(s)
    assert summary["forecasts_settled"] == 2 and summary["by_status"]["void_dnp"] == 1
    assert any(w.startswith("insufficient_sample") for w in summary["warnings"])
    pts = summary["categories"]["pts"]
    assert pts["n"] == 2 and pts["mae"] >= 0 and 0 <= pts["coverage_80"] <= 1 and "weighted" in pts["baselines"]

    def override():
        with session_factory() as s2:
            yield s2

    app.dependency_overrides[get_db] = override
    try:
        with patch("app.services.forecast_archive_service.record_forecasts", side_effect=AssertionError("recorded on request")):
            body = TestClient(app).get("/api/ml/prospective").json()
    finally:
        app.dependency_overrides.clear()
    assert body["forecasts_recorded"] == 3
    with session_factory() as s:
        assert s.scalar(text("SELECT COUNT(*) FROM ml_forecasts")) == 3
