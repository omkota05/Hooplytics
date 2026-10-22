"""ESPN public JSON API provider.

These endpoints are undocumented and unofficial. They are free, require no key, and
include full box scores, but they can change without notice. All responses are
normalized in `normalize.py`, so a shape change surfaces as a ProviderError instead
of corrupt data.
"""

from datetime import date

from app.config import Settings
from app.ingestion.http import ThrottledHttpClient
from app.ingestion.providers.base import BoxScore, GameRecord, RosterEntry, TeamRecord
from app.ingestion.providers.espn import normalize

SITE_API = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba"

HEADERS = {
    "User-Agent": "Hooplytics/0.1 (personal analytics project)",
    "Accept": "application/json",
}


class EspnProvider:
    name = "espn"

    def __init__(self, settings: Settings) -> None:
        self._http = ThrottledHttpClient(
            min_interval=settings.provider_min_request_interval_seconds,
            timeout=settings.provider_timeout_seconds,
            max_retries=settings.provider_max_retries,
            headers=HEADERS,
        )

    @property
    def request_count(self) -> int:
        return self._http.request_count

    def close(self) -> None:
        self._http.close()

    def current_season(self) -> int:
        payload = self._http.get_json(f"{SITE_API}/scoreboard")
        season = payload.get("season") or (payload.get("leagues") or [{}])[0].get("season") or {}
        return int(season["year"])

    def fetch_teams(self) -> list[TeamRecord]:
        return normalize.normalize_teams_payload(self._http.get_json(f"{SITE_API}/teams"))

    def fetch_roster(self, team_id: int) -> list[RosterEntry]:
        payload = self._http.get_json(f"{SITE_API}/teams/{team_id}/roster")
        return normalize.normalize_roster_payload(payload, team_id)

    def fetch_team_schedule(self, team_id: int, season: int, season_type: int) -> list[GameRecord]:
        payload = self._http.get_json(
            f"{SITE_API}/teams/{team_id}/schedule",
            params={"season": season, "seasontype": season_type},
        )
        return normalize.normalize_schedule_payload(payload)

    def fetch_scoreboard(self, day: date) -> list[GameRecord]:
        payload = self._http.get_json(
            f"{SITE_API}/scoreboard", params={"dates": day.strftime("%Y%m%d"), "limit": 100}
        )
        return normalize.normalize_scoreboard_payload(payload)

    def fetch_boxscore(self, game_id: int) -> BoxScore:
        payload = self._http.get_json(f"{SITE_API}/summary", params={"event": game_id})
        return normalize.normalize_boxscore_payload(payload)
