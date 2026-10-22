"""Database-level sync behaviour: idempotent upserts and duplicate handling."""

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import func, select

from app.config import Settings
from app.ingestion.providers.base import BoxScore, RosterEntry
from app.ingestion.providers.espn import normalize as n
from app.models import Game, Player, PlayerGameStat, PlayerTeamSeason, SyncRun
from app.sync import writer
from app.sync.service import SyncService
from tests.fixtures import espn_payloads as fx

TEAM_IDS = {fx.HOME_ID, fx.AWAY_ID, fx.OTHER_ID}


def _seed_teams(session):
    writer.upsert_teams(session, n.normalize_teams_payload(fx.TEAMS_PAYLOAD))
    session.commit()


def _count(session, model) -> int:
    return session.scalar(select(func.count()).select_from(model))


def test_upserting_same_games_twice_does_not_duplicate(session):
    _seed_teams(session)
    games = [n.normalize_event(fx.scoreboard_event(i, "2099-01-10T00:30Z")) for i in (1, 2)]
    writer.upsert_games(session, games, TEAM_IDS)
    writer.upsert_games(session, games + games, TEAM_IDS)
    session.commit()
    assert _count(session, Game) == 2


def test_game_status_updates_in_place(session):
    _seed_teams(session)
    scheduled = n.normalize_event(
        fx.scoreboard_event(7, "2099-01-10T00:30Z", st=fx.SCHEDULED, home_score=None, away_score=None)
    )
    writer.upsert_games(session, [scheduled], TEAM_IDS)
    postponed = replace(scheduled, status="postponed")
    writer.upsert_games(session, [postponed], TEAM_IDS)
    final = n.normalize_event(fx.scoreboard_event(7, "2099-01-12T00:30Z"))
    writer.upsert_games(session, [final], TEAM_IDS)
    session.commit()
    game = session.get(Game, 7)
    assert game.status == "final" and game.game_date == date(2099, 1, 11)
    assert _count(session, Game) == 1


def test_unknown_teams_and_preseason_are_skipped(session):
    _seed_teams(session)
    allstar = n.normalize_event(fx.scoreboard_event(8, "2099-02-15T00:30Z", home=31, away=32))
    preseason = n.normalize_event(fx.scoreboard_event(9, "2098-10-05T00:30Z", season_type=1))
    assert writer.upsert_games(session, [allstar, preseason], TEAM_IDS) == 0


def test_writing_boxscore_twice_is_idempotent(session):
    _seed_teams(session)
    box = n.normalize_boxscore_payload(fx.summary_payload(event_id=500))
    writer.write_boxscore(session, box, TEAM_IDS)
    session.commit()
    writer.write_boxscore(session, box, TEAM_IDS)
    session.commit()

    assert _count(session, PlayerGameStat) == 4
    assert _count(session, Player) == 4
    assert session.get(Game, 500).boxscore_synced_at is not None

    row = session.scalars(select(PlayerGameStat).where(PlayerGameStat.player_id == 101)).one()
    assert (row.pts, row.reb, row.ast, row.game_date, row.season) == (27, 6, 8, date(2099, 1, 9), 2099)

    history = session.scalars(select(PlayerTeamSeason).where(PlayerTeamSeason.player_id == 103)).one()
    assert history.games_played == 0  # DNP rows don't count as games played


def test_boxscore_correction_removes_stale_rows_and_updates_values(session):
    _seed_teams(session)
    box = n.normalize_boxscore_payload(fx.summary_payload(event_id=501))
    writer.write_boxscore(session, box, TEAM_IDS)
    corrected = BoxScore(
        game=box.game,
        players=box.players,
        stats=[replace(s, pts=30) if s.player_id == 101 else s for s in box.stats if s.player_id != 102],
    )
    writer.write_boxscore(session, corrected, TEAM_IDS)
    session.commit()
    ids = set(session.scalars(select(PlayerGameStat.player_id).where(PlayerGameStat.game_id == 501)))
    assert ids == {101, 103, 201}
    assert session.scalars(select(PlayerGameStat.pts).where(PlayerGameStat.player_id == 101)).one() == 30


def test_score_change_marks_boxscore_for_resync(session):
    _seed_teams(session)
    box = n.normalize_boxscore_payload(fx.summary_payload(event_id=502))
    writer.write_boxscore(session, box, TEAM_IDS)
    session.commit()
    writer.upsert_games(session, [replace(box.game, home_score=box.game.home_score + 2)], TEAM_IDS)
    session.commit()
    session.expire_all()
    assert session.get(Game, 502).boxscore_synced_at is None


def test_roster_snapshot_keeps_box_score_fields_and_sets_team(session):
    _seed_teams(session)
    writer.write_boxscore(session, n.normalize_boxscore_payload(fx.summary_payload(event_id=503)), TEAM_IDS)
    boxed = session.get(Player, 101)
    writer.apply_rosters(
        session,
        [
            RosterEntry(
                player=replace(_player_record(101), headshot_url=None, position=None), team_id=fx.OTHER_ID
            )
        ],
    )
    session.commit()
    session.expire_all()
    traded = session.get(Player, 101)
    assert traded.current_team_id == fx.OTHER_ID and traded.is_active
    assert traded.headshot_url == boxed.headshot_url  # coalesced, not erased
    assert not session.get(Player, 201).is_active


def _player_record(player_id):
    box = n.normalize_boxscore_payload(fx.summary_payload())
    return next(p for p in box.players if p.id == player_id)


# ------------------------------------------------------------------ service


class FakeProvider:
    """Serves synthetic fixtures through the real normalizers."""

    name = "fake"

    def __init__(self):
        self.request_count = 0
        self.boxscore_calls: list[int] = []
        self.missing_boxscores: set[int] = set()
        self.events = [
            fx.schedule_event(600, "2099-01-05T00:30Z"),
            fx.schedule_event(601, "2099-01-07T00:30Z", home=fx.AWAY_ID, away=fx.HOME_ID),
            fx.schedule_event(602, "2099-01-09T00:30Z", st=fx.POSTPONED, home_score=None, away_score=None),
            fx.schedule_event(603, "2099-04-01T00:30Z", st=fx.SCHEDULED, home_score=None, away_score=None),
        ]

    def current_season(self):
        return 2099

    def fetch_teams(self):
        self.request_count += 1
        return n.normalize_teams_payload(fx.TEAMS_PAYLOAD)

    def fetch_roster(self, team_id):
        return []

    def fetch_team_schedule(self, team_id, season, season_type):
        self.request_count += 1
        if season_type != 2:
            return []
        return [
            g
            for g in n.normalize_schedule_payload({"events": self.events})
            if team_id in (g.home_team_id, g.away_team_id)
        ]

    def fetch_scoreboard(self, day):
        return []

    def fetch_boxscore(self, game_id):
        self.request_count += 1
        self.boxscore_calls.append(game_id)
        event = next(e for e in self.events if int(e["id"]) == game_id)
        payload = fx.summary_payload(event_id=game_id, date=event["date"])
        if game_id in self.missing_boxscores:
            payload = fx.without_boxscore(payload)
        return n.normalize_boxscore_payload(payload)


def _service(session_factory, provider, clock=None):
    settings = Settings(database_url="unused", history_seasons=0)
    clock = clock or [datetime(2099, 1, 20, tzinfo=UTC)]
    return SyncService(
        session_factory,
        provider,
        settings,
        now=lambda: clock[0],
        min_expected_teams=3,
        min_expected_roster_players=0,
    )


def test_backfill_is_idempotent_and_only_fetches_final_games(session_factory):
    provider = FakeProvider()
    service = _service(session_factory, provider)

    first = service.run_backfill(seasons=[2099])
    assert first.status == "success" and first.boxscores_synced == 2
    assert sorted(provider.boxscore_calls) == [600, 601]  # postponed/scheduled skipped

    provider.boxscore_calls.clear()
    requests_before = provider.request_count
    second = service.run_backfill(seasons=[2099])
    assert second.boxscores_synced == 0 and provider.boxscore_calls == []
    assert provider.request_count == requests_before  # schedule already downloaded

    with session_factory() as s:
        assert _count(s, Game) == 4
        assert _count(s, PlayerGameStat) == 8
        assert s.get(Game, 602).status == "postponed"
        runs = s.scalars(select(SyncRun.status)).all()
        assert runs == ["success", "success"]
    assert service.pending_backfill_count() == 0


def test_missing_boxscore_is_retried_later_not_marked_synced(session_factory):
    provider = FakeProvider()
    provider.missing_boxscores = {601}
    clock = [datetime(2099, 1, 20, tzinfo=UTC)]
    service = _service(session_factory, provider, clock)

    run = service.run_backfill(seasons=[2099])
    assert run.status == "partial" and run.boxscores_synced == 1
    with session_factory() as s:
        game = s.get(Game, 601)
        assert game.boxscore_synced_at is None and game.boxscore_attempts == 1

    # Not retried in a tight loop: the game waits out its backoff window first.
    assert service.pending_backfill_count() == 0
    provider.boxscore_calls.clear()
    service.run_backfill(seasons=[2099])
    assert provider.boxscore_calls == []

    clock[0] += timedelta(minutes=16)
    assert service.pending_backfill_count() == 1
    provider.missing_boxscores = set()
    service.run_backfill(seasons=[2099])
    assert provider.boxscore_calls == [601]
    assert service.pending_backfill_count() == 0
