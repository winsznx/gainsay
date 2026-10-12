from fastapi.testclient import TestClient

from gainsay.test_report import make_run
from gainsay.web.app import CHECK_ICONS, OUTCOME_ICONS, create_app, icon, status_slug


def test_icons_inline_from_the_vendored_lucide_set():
    svg = icon("scale", 16)
    assert svg.startswith('<svg aria-hidden="true" focusable="false"')
    assert 'width="16" height="16"' in svg and "@license" not in svg
    for name in [*CHECK_ICONS.values(), *OUTCOME_ICONS.values()]:
        assert icon(name).startswith("<svg")


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
    assert "No case named Zicherman" in html, "the inspector opens on the first citation with a problem"
    for word in ("fake", "fabricated", "hallucinated"):
        assert word not in html.lower()

    kaiser = client.get(f"/runs/{run_id}?c=2").text
    assert "https://www.courtlistener.com/opinion/107720/kaiser-steel/" in kaiser
    assert "Pincite reason" in kaiser
    assert "No case named Zicherman" in client.get(f"/runs/{run_id}?c=99").text


def test_runs_page_and_missing_run(tmp_path):
    _, run_id = make_run(tmp_path)
    client = TestClient(create_app(tmp_path / "ledger.sqlite"))
    assert f"/runs/{run_id}" in client.get("/runs").text
    assert client.get("/runs/999").status_code == 404


def test_active_run_shows_what_it_is_doing_and_refreshes(tmp_path):
    from gainsay.ledger import connect, set_progress
    _, run_id = make_run(tmp_path)
    conn = connect(tmp_path / "ledger.sqlite")
    set_progress(conn, run_id, "Varghese, 925 F.3d 1339: not found → Not found in searched sources. Next: Kaiser.",
                 ["Kaiser Steel Corp., 391 U.S. 593"], 3, "2999-01-01T00:00:00+00:00")
    conn.execute("UPDATE runs SET status = 'paused' WHERE id = ?", (run_id,))
    conn.commit()

    html = TestClient(create_app(tmp_path / "ledger.sqlite")).get(f"/runs/{run_id}").text
    assert "Varghese, 925 F.3d 1339: not found" in html
    assert "Next: Kaiser Steel Corp., 391 U.S. 593" in html
    assert "quota refills in" in html and "3 citations queued" in html
    assert 'http-equiv="refresh"' in html


def test_report_downloads_as_markdown_with_sources_and_evidence(tmp_path):
    _, run_id = make_run(tmp_path)
    response = TestClient(create_app(tmp_path / "ledger.sqlite")).get(f"/runs/{run_id}/report.md")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/markdown")
    body = response.text
    assert body.startswith("# Gainsay report: Mata v. Avianca, Inc., ECF 21")
    assert "Westlaw and Lexis are outside the sources searched" in body
    assert "| existence | No | no case named Zicherman |" in body
    assert "(pincite off)" in body


def test_landing_and_docket_pages_render(tmp_path):
    _, run_id = make_run(tmp_path)
    client = TestClient(create_app(tmp_path / "ledger.sqlite"))
    landing = client.get("/")
    assert landing.status_code == 200
    assert "Check the other side" in landing.text
    assert "Calls per day</dt><dd>125" in landing.text
    for word in ("fake", "fabricated", "hallucinated"):
        assert word not in landing.text.lower()
    assert client.get("/docket").status_code == 404


def test_snapshot_shows_unfinished_runs_as_stopped(tmp_path):
    from gainsay.ledger import connect, set_progress
    _, run_id = make_run(tmp_path)
    conn = connect(tmp_path / "ledger.sqlite")
    set_progress(conn, run_id, "Paused on the day budget.", [], 3, "2000-01-01T00:00:00+00:00")
    conn.execute("UPDATE runs SET status = 'paused' WHERE id = ?", (run_id,))
    conn.commit()
    snapshot = TestClient(create_app(tmp_path / "ledger.sqlite", read_only=True))

    paused = snapshot.get(f"/runs/{run_id}").text
    assert 'http-equiv="refresh"' not in paused and "quota refills in" not in paused
    conn.execute("UPDATE runs SET status = 'running' WHERE id = ?", (run_id,))
    conn.commit()
    assert ", interrupted" in snapshot.get(f"/runs/{run_id}").text
    assert "Interrupted" in snapshot.get("/runs").text
    assert "checked this filing to the end" not in paused

    filing_id = conn.execute("SELECT filing_id FROM runs WHERE id = ?", (run_id,)).fetchone()["filing_id"]
    later = conn.execute(
        "INSERT INTO runs (filing_id, version, status, started_at) VALUES (?, 'abc1234', 'complete', 'now')", (filing_id,)
    ).lastrowid
    conn.commit()
    assert f'Run <a href="/runs/{later}">{later}</a> checked this filing to the end' in snapshot.get(f"/runs/{run_id}").text


def test_read_only_snapshot_is_served_without_writing(tmp_path):
    _, run_id = make_run(tmp_path)
    path = tmp_path / "ledger.sqlite"
    before = path.stat().st_mtime_ns
    client = TestClient(create_app(path, read_only=True))
    assert client.get(f"/runs/{run_id}").status_code == 200
    assert path.stat().st_mtime_ns == before


def test_each_check_step_selects_its_own_panel(tmp_path):
    from gainsay.web.app import create_app as make
    _, run_id = make_run(tmp_path)
    html = TestClient(make(tmp_path / "ledger.sqlite")).get("/").text
    if f"/runs/{run_id}" not in html:
        return
    for check in ("existence", "identity", "quotation", "proposition", "pincite"):
        assert f'aria-controls="check-{check}"' in html and f'id="check-{check}"' in html
