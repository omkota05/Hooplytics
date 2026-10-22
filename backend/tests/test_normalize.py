from datetime import date

import pytest

from app.ingestion.http import ProviderError
from app.ingestion.providers.espn import normalize as n
from app.sync.writer import normalize_search_name
from tests.fixtures import espn_payloads as fx


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (fx.FINAL, "final"),
        (fx.SCHEDULED, "scheduled"),
        (fx.IN_PROGRESS, "in_progress"),
        (fx.POSTPONED, "postponed"),
        (fx.CANCELED, "canceled"),
        (fx.status("STATUS_SUSPENDED", "in", False), "suspended"),
        (fx.status("STATUS_HALFTIME", "in", False), "in_progress"),
        (fx.status("STATUS_DELAYED", "pre", False), "scheduled"),
    ],
)
def test_status_mapping(raw, expected):
    assert n.normalize_status(raw["type"]) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [("34", 34.0), ("29:30", 29.5), ("--", None), ("", None), (None, None), ("0", 0.0)],
)
def test_parse_minutes(value, expected):
    assert n.parse_minutes(value) == expected


def test_parse_made_attempted_and_ints():
    assert n.parse_made_attempted("10-18") == (10, 18)
    assert n.parse_made_attempted("--") == (None, None)
    assert n.parse_int("+9") == 9
    assert n.parse_int("-3") == -3
    assert n.parse_int("--") is None


def test_scoreboard_event_normalization_uses_eastern_game_date():
    # 00:30 UTC on Jan 10 is 7:30 PM Eastern on Jan 9.
    game = n.normalize_event(fx.scoreboard_event(1, "2099-01-10T00:30Z"))
    assert game.game_date == date(2099, 1, 9)
    assert (game.home_team_id, game.away_team_id) == (fx.HOME_ID, fx.AWAY_ID)
    assert (game.home_score, game.away_score) == (101, 99)
    assert game.status == "final"
    assert game.venue_name == "Fixture Arena"
    assert game.season == 2099 and game.season_type == 2


def test_schedule_event_scores_are_objects():
    game = n.normalize_event(fx.schedule_event(2, "2099-02-01T00:00Z", season_type=3))
    assert game.home_score == 101
    assert game.season_type == 3


def test_scheduled_game_has_no_scores():
    game = n.normalize_event(
        fx.scoreboard_event(3, "2099-03-01T00:00Z", st=fx.SCHEDULED, home_score="0", away_score="0")
    )
    assert game.status == "scheduled"
    assert game.home_score is None and game.away_score is None


def test_event_without_competitors_raises():
    event = fx.scoreboard_event(4, "2099-03-01T00:00Z")
    event["competitions"][0]["competitors"] = []
    with pytest.raises(ProviderError):
        n.normalize_event(event)


def test_boxscore_normalization():
    box = n.normalize_boxscore_payload(fx.summary_payload())
    assert box.is_complete
    by_player = {s.player_id: s for s in box.stats}
    star = by_player[101]
    assert (star.pts, star.reb, star.ast, star.fg3m, star.fg3a, star.tov) == (27, 6, 8, 3, 7, 2)
    assert star.minutes == 34.0 and star.plus_minus == 9
    assert star.is_home and star.team_id == fx.HOME_ID and star.opponent_team_id == fx.AWAY_ID

    dnp = by_player[103]
    assert dnp.did_not_play and dnp.pts is None and dnp.dnp_reason == "COACH'S DECISION"

    away = by_player[201]
    assert not away.is_home and away.opponent_team_id == fx.HOME_ID
    assert {p.id for p in box.players} == {101, 102, 103, 201}


def test_boxscore_without_players_is_incomplete():
    box = n.normalize_boxscore_payload(fx.without_boxscore(fx.summary_payload()))
    assert box.game is not None and not box.is_complete


def test_teams_payload():
    teams = n.normalize_teams_payload(fx.TEAMS_PAYLOAD)
    assert [t.abbreviation for t in teams] == ["TST", "MCK", "FXT"]
    assert teams[0].logo_url == "https://example.test/TST.png"


def test_search_name_normalization():
    assert normalize_search_name("Nikola Jokić") == "nikola jokic"
    assert normalize_search_name("  Shai Gilgeous-Alexander ") == "shai gilgeous alexander"
    assert normalize_search_name("D'Angelo  Russell") == "d angelo russell"
