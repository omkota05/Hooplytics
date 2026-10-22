"""Synthetic payloads shaped like ESPN API responses.

Every team, player, and stat here is invented for tests ("Testville", "Mockton", ...).
None of it is real NBA data and it must never be loaded into a development database.
"""

from copy import deepcopy

HOME_ID = 9001
AWAY_ID = 9002
OTHER_ID = 9003


def team(team_id: int, abbr: str, name: str, location: str) -> dict:
    return {
        "id": str(team_id),
        "abbreviation": abbr,
        "displayName": f"{location} {name}",
        "shortDisplayName": name,
        "name": name,
        "location": location,
        "color": "112233",
        "alternateColor": "445566",
        "isActive": True,
        "logos": [{"href": f"https://example.test/{abbr}.png", "rel": ["full", "default"]}],
    }


TEAMS = [
    team(HOME_ID, "TST", "Testers", "Testville"),
    team(AWAY_ID, "MCK", "Mocks", "Mockton"),
    team(OTHER_ID, "FXT", "Fixtures", "Fixture City"),
]

TEAMS_PAYLOAD = {"sports": [{"leagues": [{"teams": [{"team": t} for t in TEAMS]}]}]}


def status(name: str, state: str, completed: bool, detail: str = "") -> dict:
    return {"type": {"name": name, "state": state, "completed": completed, "shortDetail": detail}}


FINAL = status("STATUS_FINAL", "post", True, "Final")
SCHEDULED = status("STATUS_SCHEDULED", "pre", False, "7:00 PM")
IN_PROGRESS = status("STATUS_IN_PROGRESS", "in", False, "Q3 4:12")
POSTPONED = status("STATUS_POSTPONED", "post", False, "Postponed")
CANCELED = status("STATUS_CANCELED", "post", False, "Canceled")


def scoreboard_event(
    event_id: int,
    date: str,
    *,
    home: int = HOME_ID,
    away: int = AWAY_ID,
    home_score: str | None = "101",
    away_score: str | None = "99",
    st: dict = FINAL,
    season: int = 2099,
    season_type: int = 2,
) -> dict:
    """Scoreboard-style event: scores are strings, status lives on the event."""
    return {
        "id": str(event_id),
        "date": date,
        "season": {"year": season, "type": season_type},
        "status": st,
        "competitions": [
            {
                "id": str(event_id),
                "date": date,
                "neutralSite": False,
                "venue": {"fullName": "Fixture Arena", "address": {"city": "Testville", "state": "TS"}},
                "status": st,
                "competitors": [
                    {"id": str(home), "homeAway": "home", "score": home_score, "team": {"id": str(home)}},
                    {"id": str(away), "homeAway": "away", "score": away_score, "team": {"id": str(away)}},
                ],
            }
        ],
    }


def schedule_event(event_id: int, date: str, *, home_score: float | None = 101.0, **kw) -> dict:
    """Team-schedule style event: scores are objects, season type in `seasonType`."""
    event = scoreboard_event(event_id, date, **kw)
    season_type = event["season"].pop("type")
    event["seasonType"] = {"type": season_type}
    for c in event["competitions"][0]["competitors"]:
        raw = c["score"]
        c["score"] = None if raw is None else {"value": float(raw), "displayValue": raw}
    return event


STAT_NAMES = ["MIN", "PTS", "FG", "3PT", "FT", "REB", "AST", "TO", "STL", "BLK", "OREB", "DREB", "PF", "+/-"]


def athlete_entry(
    player_id: int, name: str, stats: list[str] | None, *, starter=True, dnp=False, reason=None
):
    return {
        "active": not dnp,
        "starter": starter,
        "didNotPlay": dnp,
        "reason": reason,
        "athlete": {
            "id": str(player_id),
            "displayName": name,
            "position": {"abbreviation": "G"},
            "jersey": "0",
            "headshot": {"href": f"https://example.test/p/{player_id}.png"},
        },
        "stats": stats or [],
    }


def summary_payload(event_id: int = 500, date: str = "2099-01-10T00:30Z", **event_kw) -> dict:
    event = scoreboard_event(event_id, date, **event_kw)
    competition = event["competitions"][0]
    return {
        "header": {
            "id": str(event_id),
            "season": event["season"],
            "competitions": [competition],
        },
        "gameInfo": {"venue": competition["venue"]},
        "boxscore": {
            "players": [
                {
                    "team": {"id": str(HOME_ID)},
                    "statistics": [
                        {
                            "names": STAT_NAMES,
                            "athletes": [
                                athlete_entry(
                                    101,
                                    "Testy McTestface",
                                    [
                                        "34",
                                        "27",
                                        "10-18",
                                        "3-7",
                                        "4-5",
                                        "6",
                                        "8",
                                        "2",
                                        "1",
                                        "0",
                                        "1",
                                        "5",
                                        "2",
                                        "+9",
                                    ],
                                ),
                                athlete_entry(
                                    102,
                                    "Fixture Fred",
                                    [
                                        "22",
                                        "8",
                                        "3-9",
                                        "2-5",
                                        "0-0",
                                        "4",
                                        "1",
                                        "1",
                                        "0",
                                        "2",
                                        "0",
                                        "4",
                                        "3",
                                        "-3",
                                    ],
                                    starter=False,
                                ),
                                athlete_entry(
                                    103,
                                    "Benchy Mock",
                                    None,
                                    starter=False,
                                    dnp=True,
                                    reason="COACH'S DECISION",
                                ),
                            ],
                        }
                    ],
                },
                {
                    "team": {"id": str(AWAY_ID)},
                    "statistics": [
                        {
                            "names": STAT_NAMES,
                            "athletes": [
                                athlete_entry(
                                    201,
                                    "Mocky Mockerson",
                                    [
                                        "38",
                                        "31",
                                        "11-20",
                                        "5-9",
                                        "4-4",
                                        "5",
                                        "6",
                                        "3",
                                        "2",
                                        "1",
                                        "0",
                                        "5",
                                        "1",
                                        "-9",
                                    ],
                                ),
                            ],
                        }
                    ],
                },
            ]
        },
    }


def without_boxscore(payload: dict) -> dict:
    out = deepcopy(payload)
    out["boxscore"] = {"players": []}
    return out
