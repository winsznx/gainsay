from fastapi.testclient import TestClient

from gainsay.test_report import make_run
from gainsay.web.app import create_app, status_slug


def test_status_slugs_match_the_stylesheet():
    assert status_slug("Doesn't support the proposition") == "doesnt-support-the-proposition"
    assert status_slug("Not found in searched sources") == "not-found-in-searched-sources"


def test_run_page_shows_status_flag_and_evidence(tmp_path):
    _, run_id = make_run(tmp_path)
    client = TestClient(create_app(tmp_path / "ledger.sqlite"))

    page = client.get(f"/runs/{run_id}")
    assert page.status_code == 200
    html = page.text
    assert "1 of 3 citations has a problem." in html
    assert "Not found in searched sources" in html
    assert "Pincite off" in html
    assert "No case named Zicherman" in html
    assert "https://www.courtlistener.com/opinion/107720/kaiser-steel/" in html
    for word in ("fake", "fabricated", "hallucinated"):
        assert word not in html.lower()


def test_runs_page_and_missing_run(tmp_path):
    _, run_id = make_run(tmp_path)
    client = TestClient(create_app(tmp_path / "ledger.sqlite"))
    assert f"/runs/{run_id}" in client.get("/").text
    assert client.get("/runs/999").status_code == 404
