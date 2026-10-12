import json

from gainsay.extract import extract
from gainsay.ledger import connect, save_extraction, upsert_filing

MANIFEST = {
    "court": "nysd",
    "docket_number": "1:22-cv-01461",
    "docket_id": 63107798,
    "entry_number": 21,
    "recap_document_id": 230577042,
    "case_name": "Mata v. Avianca, Inc.",
    "description": "Affirmation in Opposition to Motion",
    "source_url": "https://storage.courtlistener.com/x.pdf",
    "sha256": "abc",
    "text_path": "data/filings/63107798/ecf21.txt",
    "extraction_method": "courtlistener_plain_text",
    "fetched_at": "2026-10-11T21:30:40+00:00",
}

TEXT = (
    "The stay tolls the period. Zicherman v. Korean Air Lines Co., Ltd., 516 F.3d 1237, 1254 "
    "(11th Cir. 2008). Courts agree. Id. at 1255."
)


def test_upsert_returns_the_same_filing_for_the_same_document(tmp_path):
    conn = connect(tmp_path / "ledger.sqlite")
    first = upsert_filing(conn, MANIFEST)
    second = upsert_filing(conn, {**MANIFEST, "sha256": "def"})
    assert first == second
    assert conn.execute("SELECT sha256 FROM filings").fetchone()["sha256"] == "def"


def test_saving_an_extraction_twice_replaces_it(tmp_path):
    conn = connect(tmp_path / "ledger.sqlite")
    filing_id = upsert_filing(conn, MANIFEST)
    save_extraction(conn, filing_id, extract(TEXT))
    save_extraction(conn, filing_id, extract(TEXT))

    rows = conn.execute(
        "SELECT c.kind, c.pincite, a.case_name, a.reporter_cites FROM citations c "
        "JOIN authorities a ON a.id = c.authority_id ORDER BY c.ordinal"
    ).fetchall()
    assert [(r["kind"], r["pincite"]) for r in rows] == [("full", "1254"), ("id", "1255")]
    assert {r["case_name"] for r in rows} == {"Zicherman v. Korean Air Lines Co., Ltd."}
    assert json.loads(rows[0]["reporter_cites"]) == ["516 F.3d 1237"]
    assert conn.execute("SELECT COUNT(*) FROM authorities").fetchone()[0] == 1


def test_upserted_filing_is_committed(tmp_path):
    path = tmp_path / "ledger.sqlite"
    upsert_filing(connect(path), MANIFEST)
    assert connect(path).execute("SELECT COUNT(*) FROM filings").fetchone()[0] == 1
