"""Pure functions converting ESPN JSON payloads into provider-neutral records."""

from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from app.ingestion.http import ProviderError
from app.ingestion.providers.base import (
    BoxScore,
    GameRecord,
    PlayerGameStatRecord,
    PlayerRecord,
    RosterEntry,
    TeamRecord,
)

EASTERN = ZoneInfo("America/New_York")


def headshot_url(player_id: int) -> str:
    return f"https://a.espncdn.com/i/headshots/nba/players/full/{player_id}.png"


def parse_datetime(value: str) -> datetime:
    # ESPN uses e.g. "2026-10-21T23:00Z" (no seconds).
    value = value.replace("Z", "+00:00")
    return datetime.fromisoformat(value)


def eastern_date(moment: datetime) -> date:
    return moment.astimezone(EASTERN).date()


def parse_int(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return int(value)
    text = str(value).strip()
    if not text or text in {"--", "-"}:
        return None
    try:
        return int(float(text.lstrip("+")))
    except ValueError:
        return None


def parse_minutes(value: Any) -> float | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text in {"--", "-"}:
        return None
    if ":" in text:
        mins, _, secs = text.partition(":")
        try:
            return round(int(mins) + int(secs) / 60, 2)
        except ValueError:
            return None
    try:
        return float(text)
    except ValueError:
        return None


def parse_made_attempted(value: Any) -> tuple[int | None, int | None]:
    if value is None:
        return None, None
    made, sep, attempted = str(value).partition("-")
    if not sep:
        return None, None
    return parse_int(made), parse_int(attempted)


def parse_score(value: Any) -> int | None:
    if isinstance(value, dict):
        return parse_int(value.get("value", value.get("displayValue")))
    return parse_int(value)


def normalize_status(status_type: dict[str, Any]) -> str:
    name = str(status_type.get("name", "")).upper()
    state = status_type.get("state")
    if "POSTPONED" in name:
        return "postponed"
    if "CANCEL" in name:
        return "canceled"
    if "SUSPENDED" in name:
        return "suspended"
    if state == "post" and status_type.get("completed", False):
        return "final"
    if state == "in":
        return "in_progress"
    return "scheduled"


def normalize_team(raw: dict[str, Any]) -> TeamRecord:
    logos = raw.get("logos") or []
    logo = next((lg["href"] for lg in logos if "default" in lg.get("rel", [])), None)
    if logo is None and logos:
        logo = logos[0].get("href")
    return TeamRecord(
        id=int(raw["id"]),
        abbreviation=raw["abbreviation"],
        display_name=raw["displayName"],
        short_name=raw.get("shortDisplayName") or raw.get("name") or raw["displayName"],
        location=raw.get("location") or raw["displayName"],
        color=raw.get("color"),
        alternate_color=raw.get("alternateColor"),
        logo_url=logo,
    )


def normalize_teams_payload(payload: dict[str, Any]) -> list[TeamRecord]:
    try:
        teams = payload["sports"][0]["leagues"][0]["teams"]
    except (KeyError, IndexError) as exc:
        raise ProviderError("Unexpected ESPN teams payload shape") from exc
    return [normalize_team(t["team"]) for t in teams if t.get("team", {}).get("isActive", True)]


def _season_info(event: dict[str, Any]) -> tuple[int, int]:
    season = event.get("season") or {}
    year = season.get("year")
    season_type = (event.get("seasonType") or {}).get("type") or season.get("type")
    if year is None or season_type is None:
        raise ProviderError(f"Event {event.get('id')} is missing season info")
    return int(year), int(season_type)


def normalize_event(event: dict[str, Any]) -> GameRecord:
    """Normalize an event from either the scoreboard or a team-schedule payload."""
    competition = (event.get("competitions") or [{}])[0]
    competitors = competition.get("competitors") or []
    home = next((c for c in competitors if c.get("homeAway") == "home"), None)
    away = next((c for c in competitors if c.get("homeAway") == "away"), None)
    if home is None or away is None:
        raise ProviderError(f"Event {event.get('id')} is missing home/away competitors")

    status_type = (competition.get("status") or event.get("status") or {}).get("type", {})
    status = normalize_status(status_type)
    season, season_type = _season_info(event)
    start = parse_datetime(competition.get("date") or event["date"])
    venue = competition.get("venue") or {}
    address = venue.get("address") or {}

    has_score = status in {"final", "in_progress", "suspended"}
    return GameRecord(
        id=int(event["id"]),
        season=season,
        season_type=season_type,
        start_time=start,
        game_date=eastern_date(start),
        home_team_id=int(home.get("id") or home["team"]["id"]),
        away_team_id=int(away.get("id") or away["team"]["id"]),
        status=status,
        status_detail=status_type.get("shortDetail") or status_type.get("detail"),
        home_score=parse_score(home.get("score")) if has_score else None,
        away_score=parse_score(away.get("score")) if has_score else None,
        venue_name=venue.get("fullName"),
        venue_city=address.get("city"),
        venue_state=address.get("state"),
        neutral_site=bool(competition.get("neutralSite", False)),
    )


def normalize_schedule_payload(payload: dict[str, Any]) -> list[GameRecord]:
    return [normalize_event(e) for e in payload.get("events") or []]


def normalize_scoreboard_payload(payload: dict[str, Any]) -> list[GameRecord]:
    return [normalize_event(e) for e in payload.get("events") or []]


def _height_weight(raw: dict[str, Any]) -> tuple[float | None, float | None]:
    height = raw.get("height")
    weight = raw.get("weight")
    return (float(height) if height else None, float(weight) if weight else None)


def normalize_athlete(raw: dict[str, Any]) -> PlayerRecord:
    player_id = int(raw["id"])
    position = raw.get("position") or {}
    headshot = (raw.get("headshot") or {}).get("href") or headshot_url(player_id)
    dob = raw.get("dateOfBirth")
    height, weight = _height_weight(raw)
    return PlayerRecord(
        id=player_id,
        full_name=raw.get("fullName") or raw.get("displayName") or str(player_id),
        first_name=raw.get("firstName"),
        last_name=raw.get("lastName"),
        position=position.get("abbreviation") or None,
        jersey=raw.get("jersey"),
        headshot_url=headshot,
        height_in=height,
        weight_lb=weight,
        birth_date=parse_datetime(dob).date() if dob else None,
    )


def normalize_roster_payload(payload: dict[str, Any], team_id: int) -> list[RosterEntry]:
    athletes = payload.get("athletes") or []
    # Some ESPN roster responses group athletes by position.
    if athletes and isinstance(athletes[0], dict) and "items" in athletes[0]:
        athletes = [a for group in athletes for a in group.get("items", [])]
    return [RosterEntry(player=normalize_athlete(a), team_id=team_id) for a in athletes]


STAT_NAME_MAP = {
    "PTS": "pts",
    "REB": "reb",
    "AST": "ast",
    "STL": "stl",
    "BLK": "blk",
    "TO": "tov",
    "OREB": "oreb",
    "DREB": "dreb",
    "PF": "pf",
    "+/-": "plus_minus",
}
SHOOTING_MAP = {"FG": ("fgm", "fga"), "3PT": ("fg3m", "fg3a"), "FT": ("ftm", "fta")}


def _stat_line(names: list[str], values: list[Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for name, value in zip(names, values, strict=False):
        key = name.upper()
        if key == "MIN":
            out["minutes"] = parse_minutes(value)
        elif key in STAT_NAME_MAP:
            out[STAT_NAME_MAP[key]] = parse_int(value)
        elif key in SHOOTING_MAP:
            made_key, att_key = SHOOTING_MAP[key]
            out[made_key], out[att_key] = parse_made_attempted(value)
    return out


def normalize_boxscore_payload(payload: dict[str, Any]) -> BoxScore:
    game: GameRecord | None = None
    header = payload.get("header") or {}
    competitions = header.get("competitions") or []
    if competitions:
        event = {
            "id": header.get("id") or competitions[0].get("id"),
            "season": header.get("season"),
            "competitions": competitions,
            "date": competitions[0].get("date"),
        }
        if not competitions[0].get("venue"):
            venue = (payload.get("gameInfo") or {}).get("venue")
            if venue:
                competitions[0] = {**competitions[0], "venue": venue}
        game = normalize_event(event)

    team_sides = (payload.get("boxscore") or {}).get("players") or []
    if game is None or len(team_sides) != 2:
        return BoxScore(game=game)

    home_id, away_id = game.home_team_id, game.away_team_id
    players: dict[int, PlayerRecord] = {}
    stats: list[PlayerGameStatRecord] = []

    for side in team_sides:
        team_id = int(side["team"]["id"])
        if team_id not in (home_id, away_id):
            raise ProviderError(f"Box score team {team_id} not in game {game.id}")
        opponent_id = away_id if team_id == home_id else home_id
        for group in side.get("statistics") or []:
            names = group.get("names") or group.get("labels") or []
            for entry in group.get("athletes") or []:
                athlete = entry.get("athlete") or {}
                if "id" not in athlete:
                    continue
                player = normalize_athlete(athlete)
                players[player.id] = player
                values = entry.get("stats") or []
                dnp = bool(entry.get("didNotPlay")) or not values
                line = {} if dnp else _stat_line(names, values)
                if not dnp and not line.get("minutes"):
                    # Listed with a stat line but no minutes logged: treat as not played.
                    dnp = line.get("pts") is None
                stats.append(
                    PlayerGameStatRecord(
                        player_id=player.id,
                        game_id=game.id,
                        team_id=team_id,
                        opponent_team_id=opponent_id,
                        is_home=team_id == home_id,
                        starter=bool(entry.get("starter")),
                        did_not_play=dnp,
                        dnp_reason=(entry.get("reason") or None) if dnp else None,
                        **line,
                    )
                )

    return BoxScore(game=game, players=list(players.values()), stats=stats)
