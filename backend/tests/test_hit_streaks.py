"""Hit streak analytics, API, caching, and integration behavior."""

from dataclasses import dataclass
from dataclasses import replace
from datetime import date, UTC, datetime

import pytest
from fastapi.testclient import TestClient

from app.analytics.categories import get_category
from app.analytics.hit_streaks import compute_hit_streak
from app.db import get_db
from app.main import app
from sqlalchemy import select

from app.models.sportsbook import PropHitStreakCache, PropOffer, SportsbookSource
from app.services.hit_streak_cache_service import get_or_compute_streak_bundle
from app.ingestion.providers.espn import normalize as n
from app.sync import writer
from tests.fixtures import espn_payloads as fx
from tests.test_api import STAR

TEAM_IDS = {fx.HOME_ID, fx.AWAY_ID, fx.OTHER_ID}


@dataclass
class FakeGame:
    game_id: int
    game_date: date
    pts: int | None
    did_not_play: bool = False
    opponent: object | None = None
    game: object | None = None
    season_type: int = 2
    season: int = 2099
    reb: int | None = 0
    ast: int | None = 0
    fg3m: int | None = 0
    stl: int | None = 0
    blk: int | None = 0
    tov: int | None = 0


def test_user_example_five_game_streak():
    pts = [25, 28, 24, 31, 26, 18, 29]
    games = [FakeGame(i, date(2099, 1, 20 - i), p) for i, p in enumerate(pts)]
    bundle = compute_hit_streak(games, category=get_category("pts"), line=20.5, pick_side="over")
    assert bundle.current_streak == 5


def test_current_season_only_mode():
    games = [
        FakeGame(1, date(2099, 1, 10), 30, season=2099),
        FakeGame(2, date(2098, 6, 1), 30, season=2098),
    ]
    season_games = [g for g in games if g.season == 2099]
    bundle = compute_hit_streak(season_games, category=get_category("pts"), line=20.5, pick_side="over")
    assert bundle.current_streak == 1
    full = compute_hit_streak(games, category=get_category("pts"), line=20.5, pick_side="over")
    assert full.current_streak == 2


def test_streak_stops_at_first_miss():
    games = [FakeGame(1, date(2099, 1, 10), 25), FakeGame(2, date(2099, 1, 9), 28), FakeGame(3, date(2099, 1, 8), 18)]
    bundle = compute_hit_streak(games, category=get_category("pts"), line=20.5, pick_side="over")
    assert bundle.current_streak == 2


def test_push_breaks_streak():
    games = [
        FakeGame(1, date(2099, 1, 10), 21),
        FakeGame(2, date(2099, 1, 9), 22),
        FakeGame(3, date(2099, 1, 8), 20),
        FakeGame(4, date(2099, 1, 7), 25),
    ]
    bundle = compute_hit_streak(games, category=get_category("pts"), line=20, pick_side="over")
    assert bundle.current_streak == 2


def test_dnp_excluded():
    games = [
        FakeGame(1, date(2099, 1, 10), 30, did_not_play=False),
        FakeGame(2, date(2099, 1, 9), 0, did_not_play=True),
        FakeGame(3, date(2099, 1, 8), 28),
    ]
    from app.analytics.windows import played_games

    played = played_games(games)
    bundle = compute_hit_streak(played, category=get_category("pts"), line=20.5, pick_side="over")
    assert bundle.current_streak == 2


def test_missing_stat_skipped_not_counted():
    g1 = FakeGame(1, date(2099, 1, 10), 30)
    g2 = FakeGame(2, date(2099, 1, 9), None)
    g3 = FakeGame(3, date(2099, 1, 8), 15)
    bundle = compute_hit_streak([g1, g2, g3], category=get_category("pts"), line=20.5, pick_side="over")
    assert bundle.current_streak == 1


def test_over_under_separate():
    games = [FakeGame(1, date(2099, 1, 10), 15), FakeGame(2, date(2099, 1, 9), 12)]
    over = compute_hit_streak(games, category=get_category("pts"), line=20.5, pick_side="over")
    under = compute_hit_streak(games, category=get_category("pts"), line=20.5, pick_side="under")
    assert over.current_streak == 0
    assert under.current_streak == 2


def test_combined_prop():
    games = [
        FakeGame(1, date(2099, 1, 10), 20, reb=10, ast=5),
        FakeGame(2, date(2099, 1, 9), 15, reb=8, ast=7),
    ]
    bundle = compute_hit_streak(games, category=get_category("pts_reb_ast"), line=34.5, pick_side="over")
    assert bundle.current_streak == 1


def test_cross_season_not_reset():
    games = [
        FakeGame(1, date(2099, 1, 10), 25, season=2099),
        FakeGame(2, date(2098, 6, 1), 22, season=2098),
    ]
    bundle = compute_hit_streak(games, category=get_category("pts"), line=20.5, pick_side="over")
    assert bundle.current_streak == 2


def test_at_least_when_history_ends_on_streak():
    games = [FakeGame(i, date(2099, 1, 10 - i), 30) for i in range(3)]
    bundle = compute_hit_streak(games, category=get_category("pts"), line=20.5, pick_side="over")
    assert bundle.current_streak == 3
    assert bundle.streak_at_least is True


@pytest.fixture
def streak_client(session_factory):
    with session_factory() as s:
        writer.upsert_teams(s, n.normalize_teams_payload(fx.TEAMS_PAYLOAD))
        book = s.scalar(select(SportsbookSource).where(SportsbookSource.name == "PrizePicks"))
        if book is None:
            book = SportsbookSource(unabated_market_source_id=99901, name="PrizePicks")
            s.add(book)
            s.flush()
        base = n.normalize_boxscore_payload(fx.summary_payload(event_id=1, date="2099-01-02T00:30Z"))
        pts_seq = [28, 27, 26, 25, 24, 18, 29, 30, 31, 32]
        for i, pts in enumerate(pts_seq):
            game = replace(
                base.game,
                id=2000 + i,
                away_team_id=fx.AWAY_ID,
                start_time=base.game.start_time.replace(day=2 + i),
                game_date=base.game.game_date.replace(day=1 + i),
                status="scheduled",
            )
            stats = [
                replace(s_row, game_id=game.id, opponent_team_id=fx.AWAY_ID, pts=pts if s_row.player_id == STAR else s_row.pts)
                for s_row in base.stats
                if s_row.team_id == fx.HOME_ID
            ]
            writer.write_boxscore(s, replace(base, game=game, stats=stats), TEAM_IDS)
        future = replace(
            base.game,
            id=3000,
            away_team_id=fx.AWAY_ID,
            start_time=datetime(2099, 6, 1, 0, 30, tzinfo=UTC),
            game_date=date(2099, 6, 1),
            status="scheduled",
        )
        writer.upsert_games(s, [future], TEAM_IDS)
        for side in ("over", "under"):
            s.add(
                PropOffer(
                    source_kind="manual",
                    sportsbook_label="PrizePicks",
                    sportsbook_source_id=book.id,
                    player_id=STAR,
                    game_id=3000,
                    category_key="pts",
                    line=20.5,
                    pick_side=side,
                    match_status="matched",
                    is_active=True,
                    game_start_time=future.start_time,
                    game_date=future.game_date,
                )
            )
        s.add(
            PropOffer(
                source_kind="manual",
                sportsbook_label="OtherBook",
                player_id=STAR,
                game_id=3000,
                category_key="pts",
                line=20.5,
                pick_side="over",
                match_status="matched",
                is_active=True,
                game_start_time=future.start_time,
            )
        )
        s.commit()

    def override():
        with session_factory() as s:
            yield s

    app.dependency_overrides[get_db] = override
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_api_only_prizepicks_no_import_call(streak_client, monkeypatch):
    called = {"n": 0}

    def boom():
        called["n"] += 1
        raise RuntimeError("should not import")

    monkeypatch.setattr("app.api.routes.prop_finder.start_background_import", boom)
    r = streak_client.get("/api/hit-streaks")
    assert r.status_code == 200
    assert called["n"] == 0
    books = {row["sportsbook"] for row in r.json()["rows"]}
    assert books <= {"PrizePicks"}


def test_global_sort_before_limit(streak_client):
    full = streak_client.get("/api/hit-streaks", params={"min_streak": 1, "limit": 100})
    assert full.status_code == 200
    all_rows = full.json()["rows"]
    if len(all_rows) >= 2:
        assert all_rows[0]["streak"]["current_streak"] >= all_rows[1]["streak"]["current_streak"]
    page = streak_client.get("/api/hit-streaks", params={"min_streak": 1, "limit": 1, "offset": 0})
    assert page.json()["rows"][0]["offer_id"] == all_rows[0]["offer_id"]


def test_duplicate_offers_deduped(streak_client):
    r = streak_client.get("/api/hit-streaks", params={"pick_side": "over"})
    over_rows = [x for x in r.json()["rows"] if x["pick_side"] == "over"]
    assert len(over_rows) <= 1


def test_analyzer_includes_hit_streak(streak_client):
    listing = streak_client.get("/api/hit-streaks")
    offer_id = listing.json()["rows"][0]["offer_id"]
    r = streak_client.get(f"/api/prop-finder/{offer_id}/analyzer")
    assert r.status_code == 200
    assert r.json()["hit_streak"] is not None
    assert r.json()["prop"]["line"] == 20.5


def test_cache_invalidation_on_sync_reference(streak_client, session_factory):
    with session_factory() as s:
        s.add(
            PropHitStreakCache(
                player_id=STAR,
                before_game_id=3000,
                category_key="pts",
                line=20.5,
                pick_side="over",
                current_season_only=False,
                streak_data={
                    "current_streak": 99,
                    "streak_at_least": False,
                    "recent_results": [],
                    "l5_record": "—",
                    "l10_record": "—",
                    "l20_record": "—",
                    "games_evaluated": 0,
                    "push_count_in_streak_window": 0,
                    "missing_data_flags": [],
                },
                data_sync_reference="old-sync",
            )
        )
        s.commit()
        games = [FakeGame(1, date(2099, 1, 1), 30)]
        bundle = get_or_compute_streak_bundle(
            s,
            player_id=STAR,
            before_game_id=3000,
            category_key="pts",
            line=20.5,
            pick_side="over",
            current_season_only=False,
            games=games,
            category=get_category("pts"),
            memory={},
            persist=True,
        )
        s.commit()
        assert bundle.current_streak == 1
