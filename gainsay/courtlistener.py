"""The single client every CourtListener request goes through.

CourtListener throttles per token, and a 429 mid-run costs more than pacing
up front. So the client keeps its own sliding-window budget on disk, shared by
every process on this machine, and treats a server 429 as a hard stop instead
of retrying.
"""

import json
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

import requests

API_ROOT = "https://www.courtlistener.com/api/rest/v4/"
STORAGE_ROOT = "https://storage.courtlistener.com/"
DEFAULT_BUDGET_PATH = Path(__file__).resolve().parent.parent / "data" / "budget.json"

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Limit:
    window: str
    seconds: int
    max_calls: int


MINUTE = Limit("minute", 60, 5)
HOUR = Limit("hour", 3600, 50)
DAY = Limit("day", 86400, 125)

# Call times are recorded just before sending, so the server sees each call a
# little later. Waiting exactly until a call ages out of the minute window drew
# 429s with 1-2 second retry hints, so the wait gets this much extra.
WINDOW_MARGIN_SECONDS = 3


class CourtListenerError(Exception):
    pass


class MissingToken(CourtListenerError):
    pass


class BudgetExhausted(CourtListenerError):
    def __init__(self, window: str, retry_after: float | None):
        self.window = window
        self.retry_after = retry_after
        wait = f"retry after {retry_after:.0f}s" if retry_after is not None else "no retry hint"
        super().__init__(f"CourtListener {window} budget exhausted ({wait})")


class Budget:
    """Call timestamps persisted to JSON, checked against minute/hour/day caps.

    The minute cap is pacing, so it waits. The hour and day caps mean the run
    can't finish now, so they raise and let the caller resume later.
    """

    def __init__(
        self,
        path: Path = DEFAULT_BUDGET_PATH,
        minute: Limit = MINUTE,
        hour: Limit = HOUR,
        day: Limit = DAY,
        clock: Callable[[], float] = time.time,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self._path = path
        self._minute = minute
        self._hard_limits = (hour, day)
        self._clock = clock
        self._sleep = sleep

    def acquire(self) -> None:
        now = self._clock()
        longest = max(limit.seconds for limit in (self._minute, *self._hard_limits))
        calls = [t for t in self._load() if now - t < longest]

        for limit in self._hard_limits:
            in_window = [t for t in calls if now - t < limit.seconds]
            if len(in_window) >= limit.max_calls:
                raise BudgetExhausted(limit.window, min(in_window) + limit.seconds - now)

        in_minute = [t for t in calls if now - t < self._minute.seconds]
        if len(in_minute) >= self._minute.max_calls:
            wait = min(in_minute) + self._minute.seconds - now + WINDOW_MARGIN_SECONDS
            logger.warning("CourtListener minute budget full, waiting %.1fs", wait)
            self._sleep(wait)
            now = self._clock()

        calls.append(now)
        self._save(calls)

    def _load(self) -> list[float]:
        if not self._path.exists():
            return []
        return json.loads(self._path.read_text())["calls"]

    def _save(self, calls: list[float]) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        staging = self._path.with_suffix(".tmp")
        staging.write_text(json.dumps({"calls": calls}))
        os.replace(staging, self._path)


def storage_url(filepath_local: str) -> str:
    """The REST API returns filepath_local as a full URL, search returns a bare path."""
    if filepath_local.startswith(("http://", "https://")):
        return filepath_local
    return STORAGE_ROOT + filepath_local.lstrip("/")


class CourtListenerClient:
    def __init__(
        self,
        token: str | None = None,
        budget: Budget | None = None,
        session: requests.Session | None = None,
        timeout: float = 30,
    ):
        token = token or os.environ.get("COURTLISTENER_TOKEN")
        if not token:
            raise MissingToken("COURTLISTENER_TOKEN is not set")
        self._token = token
        self._budget = budget or Budget()
        self._session = session or requests.Session()
        self._timeout = timeout
        self.calls = 0

    def get_json(self, path: str, params: dict[str, Any] | None = None) -> Any:
        return self._api("GET", path, params=params).json()

    def post_json(self, path: str, data: dict[str, Any]) -> Any:
        return self._api("POST", path, data=data).json()

    def download(self, filepath_local: str) -> bytes:
        # Storage is a public bucket on another host, so the token stays home.
        return self._request("GET", storage_url(filepath_local)).content

    def _api(self, method: str, path: str, **kwargs: Any) -> requests.Response:
        return self._request(
            method,
            API_ROOT + path.lstrip("/"),
            headers={"Authorization": f"Token {self._token}"},
            **kwargs,
        )

    def _request(
        self,
        method: str,
        url: str,
        headers: dict[str, str] | None = None,
        **kwargs: Any,
    ) -> requests.Response:
        self._budget.acquire()
        self.calls += 1
        try:
            response = self._session.request(
                method, url, headers=headers, timeout=self._timeout, **kwargs
            )
        except requests.RequestException as exc:
            raise CourtListenerError(f"{method} {url} failed: {exc}") from exc

        if response.status_code == 429:
            raise BudgetExhausted("server", _retry_after(response))
        if not response.ok:
            raise CourtListenerError(
                f"{method} {response.url} returned {response.status_code}: {response.text[:300]}"
            )
        return response


def _retry_after(response: requests.Response) -> float | None:
    value = response.headers.get("Retry-After")
    try:
        return float(value) if value is not None else None
    except ValueError:
        return None
