import json

import pytest

from gainsay.courtlistener import (
    API_ROOT,
    STORAGE_ROOT,
    Budget,
    BudgetExhausted,
    CourtListenerClient,
    CourtListenerError,
    MissingToken,
    storage_url,
)


class FakeClock:
    def __init__(self, now: float = 1_000_000.0):
        self.now = now
        self.slept: list[float] = []

    def __call__(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds


def make_budget(tmp_path, clock, calls=()):
    path = tmp_path / "budget.json"
    if calls:
        path.write_text(json.dumps({"calls": list(calls)}))
    return Budget(path, clock=clock, sleep=clock.sleep)


def test_minute_cap_waits_for_oldest_call_to_age_out(tmp_path):
    clock = FakeClock()
    budget = make_budget(tmp_path, clock)
    for _ in range(5):
        budget.acquire()
    budget.acquire()
    assert clock.slept == [60]


def test_hour_cap_raises_with_retry_hint(tmp_path):
    clock = FakeClock()
    calls = [clock.now - 3000 + i * 50 for i in range(50)]
    budget = make_budget(tmp_path, clock, calls)
    with pytest.raises(BudgetExhausted) as exc:
        budget.acquire()
    assert exc.value.window == "hour"
    assert exc.value.retry_after == pytest.approx(600)


def test_day_cap_raises(tmp_path):
    clock = FakeClock()
    calls = [clock.now - 80_000 + i * 100 for i in range(125)]
    budget = make_budget(tmp_path, clock, calls)
    with pytest.raises(BudgetExhausted) as exc:
        budget.acquire()
    assert exc.value.window == "day"


def test_budget_is_shared_through_the_file(tmp_path):
    clock = FakeClock()
    for _ in range(5):
        make_budget(tmp_path, clock).acquire()
    make_budget(tmp_path, clock).acquire()
    assert clock.slept == [60]


def test_calls_older_than_a_day_are_dropped(tmp_path):
    clock = FakeClock()
    budget = make_budget(tmp_path, clock, [clock.now - 90_000] * 200)
    budget.acquire()
    stored = json.loads((tmp_path / "budget.json").read_text())["calls"]
    assert stored == [clock.now]


class FakeResponse:
    def __init__(self, status_code=200, payload=None, content=b"", headers=None):
        self.status_code = status_code
        self.ok = 200 <= status_code < 400
        self._payload = payload
        self.content = content
        self.text = json.dumps(payload) if payload is not None else ""
        self.headers = headers or {}
        self.url = "https://example.test"

    def json(self):
        return self._payload


class FakeSession:
    def __init__(self, *responses):
        self._responses = list(responses)
        self.requests: list[dict] = []

    def get(self, url, params=None, headers=None, timeout=None):
        self.requests.append({"url": url, "params": params, "headers": headers})
        return self._responses.pop(0)


def make_client(tmp_path, *responses):
    session = FakeSession(*responses)
    client = CourtListenerClient(
        token="secret", budget=make_budget(tmp_path, FakeClock()), session=session
    )
    return client, session


def test_api_calls_send_token_and_storage_downloads_do_not(tmp_path):
    client, session = make_client(
        tmp_path, FakeResponse(payload={"ok": True}), FakeResponse(content=b"%PDF")
    )
    assert client.get_json("search/", {"q": "x"}) == {"ok": True}
    assert client.download("recap/a.pdf") == b"%PDF"

    api, storage = session.requests
    assert api["url"] == API_ROOT + "search/"
    assert api["headers"] == {"Authorization": "Token secret"}
    assert storage["url"] == STORAGE_ROOT + "recap/a.pdf"
    assert storage["headers"] is None
    assert client.calls == 2


def test_server_429_raises_without_retrying(tmp_path):
    client, session = make_client(
        tmp_path, FakeResponse(status_code=429, headers={"Retry-After": "120"})
    )
    with pytest.raises(BudgetExhausted) as exc:
        client.get_json("search/")
    assert exc.value.window == "server"
    assert exc.value.retry_after == 120
    assert len(session.requests) == 1


def test_http_error_raises(tmp_path):
    client, _ = make_client(tmp_path, FakeResponse(status_code=403, payload={"detail": "no"}))
    with pytest.raises(CourtListenerError, match="403"):
        client.get_json("recap-documents/")


def test_missing_token_raises(monkeypatch, tmp_path):
    monkeypatch.delenv("COURTLISTENER_TOKEN", raising=False)
    with pytest.raises(MissingToken):
        CourtListenerClient(budget=make_budget(tmp_path, FakeClock()))


def test_storage_url_accepts_full_urls_and_bare_paths():
    full = "https://storage.courtlistener.com/recap/a.pdf"
    assert storage_url(full) == full
    assert storage_url("/recap/a.pdf") == full
