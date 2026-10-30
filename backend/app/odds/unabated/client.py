"""HTTP client for Unabated with shared rate limiting and caching."""

from __future__ import annotations

import logging
import threading
import time
from typing import Any

import httpx

from app.config import get_settings
from app.odds.unabated.response import data_records, person_display_name, record_id

logger = logging.getLogger(__name__)


class UnabatedError(RuntimeError):
    pass


class UnabatedAuthError(UnabatedError):
    pass


class UnabatedRateLimitError(UnabatedError):
    def __init__(self, message: str, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after


class UnabatedClient:
    """One odds request per interval per API key (Free tier: 5 seconds)."""

    _instance: UnabatedClient | None = None
    _lock = threading.Lock()

    def __init__(self) -> None:
        settings = get_settings()
        self._api_key = settings.unabated_api_key
        self._base_url = (settings.unabated_api_base_url or "").rstrip("/")
        self._min_interval = settings.unabated_min_request_interval_seconds
        self._timeout = settings.unabated_timeout_seconds
        self._client = httpx.Client(
            timeout=httpx.Timeout(self._timeout, connect=min(self._timeout, 10)),
            headers={"Accept": "application/json"},
            follow_redirects=True,
        )
        self._request_lock = threading.Lock()
        self._last_request = 0.0
        self._discovery_cache: dict[str, tuple[float, Any]] = {}
        self._discovery_ttl = 3600.0

    @classmethod
    def instance(cls) -> UnabatedClient:
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    @property
    def configured(self) -> bool:
        return bool(self._api_key and self._base_url)

    def close(self) -> None:
        self._client.close()

    def _wait_turn(self) -> None:
        elapsed = time.monotonic() - self._last_request
        if elapsed < self._min_interval:
            time.sleep(self._min_interval - elapsed)
        self._last_request = time.monotonic()

    def _request(self, path: str, *, params: dict[str, Any] | None = None) -> Any:
        if not self.configured:
            raise UnabatedError("Unabated API is not configured (set UNABATED_API_KEY and UNABATED_API_BASE_URL)")
        url = f"{self._base_url}{path}"
        headers = {"X-Api-Key": self._api_key}
        with self._request_lock:
            self._wait_turn()
            response = self._client.get(url, headers=headers, params=params)
        if response.status_code == 401:
            raise UnabatedAuthError("Unabated API authentication failed (check UNABATED_API_KEY)")
        if response.status_code == 429:
            retry = response.headers.get("Retry-After")
            raise UnabatedRateLimitError(
                "Unabated API rate limit exceeded",
                retry_after=float(retry) if retry else 5.0,
            )
        if response.status_code == 503:
            retry = response.headers.get("Retry-After")
            raise UnabatedRateLimitError(
                "Unabated delayed snapshot unavailable",
                retry_after=float(retry) if retry else 5.0,
            )
        if not response.is_success:
            raise UnabatedError(f"Unabated HTTP {response.status_code}: {response.text[:300]}")
        body = response.json()
        if body.get("success") is not True:
            messages = "; ".join(body.get("messages") or []) or "Unabated request failed"
            raise UnabatedError(messages)
        return body

    def _cached_discovery(self, key: str, fetcher: Any) -> Any:
        now = time.monotonic()
        hit = self._discovery_cache.get(key)
        if hit and now - hit[0] < self._discovery_ttl:
            return hit[1]
        data = fetcher()
        self._discovery_cache[key] = (now, data)
        return data

    def nba_league_name(self) -> str:
        def fetch() -> str:
            body = self._request("/league")
            for league in data_records(body.get("data"), context="/league"):
                if (league.get("name") or "").lower() == "nba":
                    return str(league["name"])
            for league in data_records(body.get("data"), context="/league"):
                if "nba" in (league.get("fullName") or "").lower():
                    return str(league.get("name") or "nba")
            raise UnabatedError("NBA league not found in Unabated /league response")

        return self._cached_discovery("nba_league", fetch)

    def bet_type_names(self) -> dict[int, str]:
        def fetch() -> dict[int, str]:
            body = self._request("/bettype")
            out: dict[int, str] = {}
            for row in data_records(body.get("data"), context="/bettype"):
                bet_id = record_id(row, "id", "betTypeId")
                name = row.get("name")
                if bet_id is not None and name:
                    out[bet_id] = str(name)
            return out

        return self._cached_discovery("bet_types", fetch)

    def market_sources(self, league: str) -> list[dict[str, Any]]:
        def fetch() -> list[dict[str, Any]]:
            body = self._request(f"/market/{league}/props/sources")
            return data_records(body.get("data"), context=f"/market/{league}/props/sources")

        return self._cached_discovery(f"sources:{league}", fetch)

    def props_odds(self, league: str) -> dict[str, Any]:
        return self._request(f"/market/{league}/props/odds")

    def props_people(self, league: str) -> dict[int, str]:
        def fetch() -> dict[int, str]:
            body = self._request(f"/market/{league}/props/people")
            out: dict[int, str] = {}
            for person in data_records(body.get("data"), context=f"/market/{league}/props/people"):
                pid = record_id(person, "id", "personId")
                name = person_display_name(person)
                if pid is not None and name:
                    out[pid] = name
            return out

        return self._cached_discovery(f"people:{league}", fetch)

    def upcoming_events(self, league: str) -> list[dict[str, Any]]:
        def fetch() -> list[dict[str, Any]]:
            body = self._request(f"/event/{league}/upcoming")
            return data_records(body.get("data"), context=f"/event/{league}/upcoming")

        return self._cached_discovery(f"events:{league}", fetch)
