from gainsay.cache import CachedCourtListener
from gainsay.ledger import connect


class CountingClient:
    def __init__(self):
        self.calls = 0

    def get_json(self, path, params):
        self.calls += 1
        return {"path": path, "params": params}

    def post_json(self, path, data):
        self.calls += 1
        return [{"text": data["text"]}]


def test_repeat_requests_are_served_from_the_ledger(tmp_path):
    conn = connect(tmp_path / "ledger.sqlite")
    client = CountingClient()
    api = CachedCourtListener(conn, lambda: client)

    first = api.get_json("search/", {"q": "a", "type": "o"})
    second = api.get_json("search/", {"type": "o", "q": "a"})
    api.post_json("citation-lookup/", {"text": "925 F.3d 1339"})
    api.post_json("citation-lookup/", {"text": "925 F.3d 1339"})

    assert first == second
    assert client.calls == 2
    assert api.cache_hits == 2
    assert api.response_id("GET", "search/", {"q": "a", "type": "o"}) is not None


def test_cache_survives_a_new_session(tmp_path):
    path = tmp_path / "ledger.sqlite"
    CachedCourtListener(connect(path), CountingClient).get_json("search/", {"q": "a"})

    def no_client():
        raise AssertionError("a cached request must not build a client")

    api = CachedCourtListener(connect(path), no_client)
    assert api.get_json("search/", {"q": "a"}) == {"path": "search/", "params": {"q": "a"}}
    assert api.calls == 0


def test_an_offline_run_answers_from_the_ledger_and_reports_misses(tmp_path):
    import pytest
    from gainsay.cache import CachedCourtListener, OfflineClient
    from gainsay.courtlistener import CourtListenerError
    from gainsay.ledger import connect
    conn = connect(tmp_path / "ledger.sqlite")
    conn.execute(
        "INSERT INTO api_responses (method, path, params, body, fetched_at) VALUES ('GET', 'search/', '{}', '[1]', 'now')"
    )
    api = CachedCourtListener(conn, client_factory=OfflineClient)
    assert api.get_json("search/") == [1]
    with pytest.raises(CourtListenerError, match="not in the ledger and this run is offline"):
        api.get_json("opinions/", {"cluster__id": 1})
    assert api.calls == 0
