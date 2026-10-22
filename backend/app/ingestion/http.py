import logging
import random
import threading
import time
from typing import Any

import httpx

logger = logging.getLogger(__name__)

RETRYABLE_STATUS = {429, 500, 502, 503, 504}


class ProviderError(RuntimeError):
    """The upstream data provider failed or returned something unusable."""


class ProviderUnavailableError(ProviderError):
    """Retries were exhausted; the provider is down, blocking us, or rate limiting."""


class ThrottledHttpClient:
    """Sequential HTTP client with a minimum gap between requests and retry/backoff.

    All requests go through one lock, so callers in different threads still respect
    the global request rate toward the provider.
    """

    def __init__(
        self,
        *,
        min_interval: float,
        timeout: float,
        max_retries: int,
        headers: dict[str, str] | None = None,
    ) -> None:
        self._client = httpx.Client(
            timeout=httpx.Timeout(timeout, connect=min(timeout, 10)),
            headers=headers or {},
            follow_redirects=True,
        )
        self._min_interval = min_interval
        self._max_retries = max_retries
        self._lock = threading.Lock()
        self._last_request = 0.0
        self.request_count = 0

    def close(self) -> None:
        self._client.close()

    def _wait_turn(self) -> None:
        elapsed = time.monotonic() - self._last_request
        if elapsed < self._min_interval:
            time.sleep(self._min_interval - elapsed)
        self._last_request = time.monotonic()

    def get_json(self, url: str, params: dict[str, Any] | None = None) -> Any:
        last_error: str = ""
        for attempt in range(self._max_retries + 1):
            with self._lock:
                self._wait_turn()
                self.request_count += 1
                try:
                    response = self._client.get(url, params=params)
                except (httpx.TimeoutException, httpx.TransportError) as exc:
                    response = None
                    last_error = f"{type(exc).__name__}: {exc}"

            if response is not None:
                if response.status_code == 200:
                    try:
                        return response.json()
                    except ValueError as exc:
                        raise ProviderError(f"Invalid JSON from {url}") from exc
                if response.status_code not in RETRYABLE_STATUS:
                    raise ProviderError(f"HTTP {response.status_code} from {url} params={params}")
                last_error = f"HTTP {response.status_code}"

            if attempt == self._max_retries:
                break
            delay = self._backoff(attempt, response)
            logger.warning(
                "Provider request failed (%s); retry %d/%d in %.1fs: %s",
                last_error,
                attempt + 1,
                self._max_retries,
                delay,
                url,
            )
            time.sleep(delay)

        raise ProviderUnavailableError(
            f"Giving up on {url} after {self._max_retries + 1} attempts ({last_error})"
        )

    @staticmethod
    def _backoff(attempt: int, response: httpx.Response | None) -> float:
        if response is not None and (retry_after := response.headers.get("Retry-After")):
            try:
                return min(float(retry_after), 120.0)
            except ValueError:
                pass
        return min(2**attempt * 1.5, 60.0) + random.uniform(0, 0.5)
