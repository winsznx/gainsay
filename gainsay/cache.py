"""CourtListener responses kept in the ledger.

A repeated request is answered from the ledger, so a rerun or a resume after
a 429 spends no budget, and every finding can point at the exact response it
was based on. The live client is only built on a cache miss, which lets a
fully cached run work without a token.
"""

import json
import sqlite3
from typing import Any, Callable

from gainsay.courtlistener import CourtListenerClient, CourtListenerError
from gainsay.ledger import now


class CachedCourtListener:
    def __init__(
        self,
        conn: sqlite3.Connection,
        client_factory: Callable[[], CourtListenerClient] = CourtListenerClient,
    ):
        self._conn = conn
        self._client_factory = client_factory
        self._client: CourtListenerClient | None = None
        self.cache_hits = 0

    @property
    def calls(self) -> int:
        return self._client.calls if self._client else 0

    @property
    def offline(self) -> bool:
        """Whether a request the ledger lacks fails here instead of reaching CourtListener."""
        return self._client_factory is OfflineClient

    def get_json(self, path: str, params: dict[str, Any] | None = None) -> Any:
        params = params or {}
        return self._cached("GET", path, params, lambda client: client.get_json(path, params))

    def post_json(self, path: str, data: dict[str, Any]) -> Any:
        return self._cached("POST", path, data, lambda client: client.post_json(path, data))

    def response_id(self, method: str, path: str, params: dict[str, Any]) -> int | None:
        row = self._conn.execute(
            "SELECT id FROM api_responses WHERE method = ? AND path = ? AND params = ?",
            (method, path, _key(params)),
        ).fetchone()
        return row["id"] if row else None

    def _cached(
        self,
        method: str,
        path: str,
        params: dict[str, Any],
        fetch: Callable[[CourtListenerClient], Any],
    ) -> Any:
        row = self._conn.execute(
            "SELECT body FROM api_responses WHERE method = ? AND path = ? AND params = ?",
            (method, path, _key(params)),
        ).fetchone()
        if row:
            self.cache_hits += 1
            return json.loads(row["body"])

        if self._client is None:
            self._client = self._client_factory()
        body = fetch(self._client)
        with self._conn:
            self._conn.execute(
                "INSERT INTO api_responses (method, path, params, body, fetched_at) VALUES (?, ?, ?, ?, ?)",
                (method, path, _key(params), json.dumps(body), now()),
            )
        return body


class OfflineClient:
    """Stands in for the live client so a run answers only from the ledger.

    A request the ledger hasn't seen fails with a reason the finding keeps,
    instead of spending quota.
    """

    calls = 0

    def get_json(self, path: str, params: dict[str, Any] | None = None) -> Any:
        raise CourtListenerError(f"GET {path} is not in the ledger and this run is offline")

    def post_json(self, path: str, data: dict[str, Any]) -> Any:
        raise CourtListenerError(f"POST {path} is not in the ledger and this run is offline")


def _key(params: dict[str, Any]) -> str:
    return json.dumps(params, sort_keys=True)
