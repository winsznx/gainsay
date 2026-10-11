"""The SQLite ledger: filings, the cases they cite, and each citation occurrence.

Every number Gainsay reports is read back from here, so the ledger stores the
evidence (cleaned text, spans, propositions, quotes) next to the results.
"""

import json
import sqlite3
from pathlib import Path

from gainsay.extract import Extraction

DEFAULT_LEDGER_PATH = Path(__file__).resolve().parent.parent / "data" / "gainsay.sqlite"

SCHEMA = """
CREATE TABLE IF NOT EXISTS filings (
    id INTEGER PRIMARY KEY,
    court TEXT NOT NULL,
    docket_number TEXT NOT NULL,
    docket_id INTEGER NOT NULL,
    entry_number INTEGER NOT NULL,
    recap_document_id INTEGER NOT NULL UNIQUE,
    case_name TEXT,
    description TEXT,
    source_url TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    text_path TEXT NOT NULL,
    extraction_method TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    clean_text TEXT,
    non_case_citations INTEGER
);

CREATE TABLE IF NOT EXISTS authorities (
    id INTEGER PRIMARY KEY,
    filing_id INTEGER NOT NULL REFERENCES filings(id) ON DELETE CASCADE,
    ordinal INTEGER NOT NULL,
    case_name TEXT NOT NULL,
    reporter_cites TEXT NOT NULL,
    year TEXT,
    court TEXT,
    UNIQUE (filing_id, ordinal)
);

CREATE TABLE IF NOT EXISTS citations (
    id INTEGER PRIMARY KEY,
    filing_id INTEGER NOT NULL REFERENCES filings(id) ON DELETE CASCADE,
    authority_id INTEGER REFERENCES authorities(id) ON DELETE CASCADE,
    ordinal INTEGER NOT NULL,
    kind TEXT NOT NULL,
    cite_text TEXT NOT NULL,
    pincite TEXT,
    span_start INTEGER NOT NULL,
    span_end INTEGER NOT NULL,
    proposition TEXT NOT NULL,
    quotes TEXT NOT NULL,
    in_quotation INTEGER NOT NULL,
    UNIQUE (filing_id, ordinal)
);
"""


def connect(path: Path = DEFAULT_LEDGER_PATH) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    return conn


def upsert_filing(conn: sqlite3.Connection, manifest: dict) -> int:
    columns = (
        "court", "docket_number", "docket_id", "entry_number", "recap_document_id",
        "case_name", "description", "source_url", "sha256", "text_path",
        "extraction_method", "fetched_at",
    )
    updates = ", ".join(f"{c} = excluded.{c}" for c in columns if c != "recap_document_id")
    row = conn.execute(
        f"INSERT INTO filings ({', '.join(columns)}) "
        f"VALUES ({', '.join('?' for _ in columns)}) "
        f"ON CONFLICT (recap_document_id) DO UPDATE SET {updates} RETURNING id",
        [manifest[c] for c in columns],
    ).fetchone()
    return row["id"]


def save_extraction(conn: sqlite3.Connection, filing_id: int, extraction: Extraction) -> None:
    """Replace the filing's citations with a fresh extraction, all or nothing."""
    with conn:
        conn.execute("DELETE FROM citations WHERE filing_id = ?", (filing_id,))
        conn.execute("DELETE FROM authorities WHERE filing_id = ?", (filing_id,))
        conn.execute(
            "UPDATE filings SET clean_text = ?, non_case_citations = ? WHERE id = ?",
            (extraction.text, extraction.non_case_citations, filing_id),
        )
        authority_ids = {}
        for authority in extraction.authorities:
            authority_ids[authority.ordinal] = conn.execute(
                "INSERT INTO authorities (filing_id, ordinal, case_name, reporter_cites, year, court) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    filing_id,
                    authority.ordinal,
                    authority.case_name,
                    json.dumps(authority.reporter_cites),
                    authority.year,
                    authority.court,
                ),
            ).lastrowid
        for citation in extraction.citations:
            conn.execute(
                "INSERT INTO citations (filing_id, authority_id, ordinal, kind, cite_text, pincite, "
                "span_start, span_end, proposition, quotes, in_quotation) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    filing_id,
                    authority_ids[citation.authority.ordinal] if citation.authority else None,
                    citation.ordinal,
                    citation.kind,
                    citation.cite_text,
                    citation.pincite,
                    citation.span[0],
                    citation.span[1],
                    citation.proposition,
                    json.dumps(citation.quotes),
                    int(citation.in_quotation),
                ),
            )
