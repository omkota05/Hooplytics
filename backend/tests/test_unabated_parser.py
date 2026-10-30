import json
from pathlib import Path

from app.odds.unabated.deeplink import attach_partner_code
from app.odds.unabated.mapping import category_from_bet_type_name
from app.odds.unabated.parser import parse_props_odds

FIXTURE = Path(__file__).parent / "fixtures" / "unabated_props_odds_sample.json"
PEOPLE_FIXTURE = Path(__file__).parent / "fixtures" / "unabated_props_people_sample.json"


def test_parse_props_odds_includes_alternate_lines():
    body = json.loads(FIXTURE.read_text())
    lines = parse_props_odds(body)
    assert len(lines) == 3
    main = [l for l in lines if not l.is_alternate]
    alts = [l for l in lines if l.is_alternate]
    assert len(main) == 2
    assert len(alts) == 1
    assert alts[0].points == 29.5
    assert main[0].pick_side == "over"


def test_parse_props_odds_side_index_without_side_name():
    body = {
        "success": True,
        "data": {
            "odds": {
                "nba": {
                    "periodTypes": {
                        "game": {
                            "periodTypeId": 1,
                            "pregame": {
                                "g1": {
                                    "eventId": 1,
                                    "eventName": "LAL @ BOS",
                                    "betTypeId": 73,
                                    "sides": {
                                        "a": {
                                            "sideIndex": 0,
                                            "personId": 1,
                                            "marketSourceLines": {
                                                "x": {
                                                    "marketSourceId": 1,
                                                    "statusId": 1,
                                                    "disabled": False,
                                                    "points": 20.5,
                                                    "price": -110,
                                                }
                                            },
                                        }
                                    },
                                }
                            },
                            "live": {},
                        }
                    }
                }
            }
        },
    }
    lines = parse_props_odds(body)
    assert len(lines) == 1
    assert lines[0].pick_side == "over"


def test_category_mapping_player_points():
    assert category_from_bet_type_name("Player Points") == "pts"
    assert category_from_bet_type_name("Player Points + Rebounds + Assists") == "pts_reb_ast"
    assert category_from_bet_type_name("Three Pointers Made") == "fg3m"


def test_partner_code_appended_to_deep_link():
    url = attach_partner_code("https://gambly.com/example?foo=1", "hooplytics")
    assert "utm_campaign=hooplytics" in url
    assert "foo=1" in url
