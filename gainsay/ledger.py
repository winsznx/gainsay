"""The SQLite ledger: filings, citations, check runs and their findings.

Every number Gainsay reports is read back from here, so the ledger stores the
evidence (cleaned text, spans, propositions, quotes, raw CourtListener
responses) next to the results.
"""

import json
import sqlite3
from datetime import UTC, datetime
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
    docket_number TEXT,
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

CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY,
    filing_id INTEGER NOT NULL REFERENCES filings(id) ON DELETE CASCADE,
    version TEXT NOT NULL,
    status TEXT NOT NULL,
    status_reason TEXT,
    started_at TEXT NOT NULL,
    finished_at TEXT
);

CREATE TABLE IF NOT EXISTS run_traces (
    run_id INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    trace_id TEXT NOT NULL PRIMARY KEY,
    started_at TEXT NOT NULL,
    outcome TEXT,
    reason TEXT
);

CREATE TABLE IF NOT EXISTS findings (
    id INTEGER PRIMARY KEY,
    run_id INTEGER NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    citation_id INTEGER NOT NULL REFERENCES citations(id) ON DELETE CASCADE,
    check_name TEXT NOT NULL,
    outcome TEXT NOT NULL,
    reason TEXT NOT NULL,
    evidence TEXT NOT NULL,
    checked_at TEXT NOT NULL,
    UNIQUE (run_id, citation_id, check_name)
);

CREATE TABLE IF NOT EXISTS dockets (
    id INTEGER PRIMARY KEY,
    court TEXT NOT NULL,
    docket_number TEXT NOT NULL,
    case_name TEXT NOT NULL,
    resolved_at TEXT NOT NULL,
    UNIQUE (court, docket_number)
);

CREATE TABLE IF NOT EXISTS docket_entries (
    docket_id INTEGER NOT NULL,
    entry_number INTEGER NOT NULL,
    date_filed TEXT,
    date_created TEXT,
    description TEXT NOT NULL,
    first_seen_at TEXT NOT NULL,
    PRIMARY KEY (docket_id, entry_number)
);

CREATE TABLE IF NOT EXISTS api_responses (
    id INTEGER PRIMARY KEY,
    method TEXT NOT NULL,
    path TEXT NOT NULL,
    params TEXT NOT NULL,
    body TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    UNIQUE (method, path, params)
);
"""


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def connect(path: Path = DEFAULT_LEDGER_PATH) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    _add_missing_columns(conn)
    return conn


def _add_missing_columns(conn: sqlite3.Connection) -> None:
    """Columns added after a ledger was created. CREATE TABLE IF NOT EXISTS skips them."""
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(authorities)")}
    if "docket_number" not in columns:
        with conn:
            conn.execute("ALTER TABLE authorities ADD COLUMN docket_number TEXT")


def find_filing(conn: sqlite3.Connection, docket_id: int, entry_number: int) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM filings WHERE docket_id = ? AND entry_number = ?", (docket_id, entry_number)
    ).fetchone()


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
                "INSERT INTO authorities (filing_id, ordinal, case_name, reporter_cites, year, court, docket_number) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    filing_id,
                    authority.ordinal,
                    authority.case_name,
                    json.dumps(authority.reporter_cites),
                    authority.year,
                    authority.court,
                    authority.docket_number,
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


def start_run(conn: sqlite3.Connection, filing_id: int, version: str) -> int:
    with conn:
        return conn.execute(
            "INSERT INTO runs (filing_id, version, status, started_at) VALUES (?, ?, 'running', ?)",
            (filing_id, version, now()),
        ).lastrowid


def finish_run(conn: sqlite3.Connection, run_id: int, status: str, reason: str | None = None) -> None:
    with conn:
        conn.execute(
            "UPDATE runs SET status = ?, status_reason = ?, finished_at = ? WHERE id = ?",
            (status, reason, now(), run_id),
        )


def record_trace(
    conn: sqlite3.Connection, run_id: int, trace_id: str, outcome: str | None = None, reason: str | None = None
) -> None:
    """The neatlogs trace for one attempt at a run. A resumed run has one per attempt."""
    with conn:
        conn.execute(
            "INSERT INTO run_traces (run_id, trace_id, started_at, outcome, reason) VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT (trace_id) DO UPDATE SET outcome = excluded.outcome, reason = excluded.reason",
            (run_id, trace_id, now(), outcome, reason),
        )


def resume_run(conn: sqlite3.Connection, run_id: int) -> sqlite3.Row:
    run = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
    if run is None:
        raise ValueError(f"no run {run_id} in the ledger")
    if run["status"] == "complete":
        raise ValueError(f"run {run_id} is already complete")
    with conn:
        conn.execute(
            "UPDATE runs SET status = 'running', status_reason = NULL, finished_at = NULL WHERE id = ?",
            (run_id,),
        )
    return run


def recorded_checks(conn: sqlite3.Connection, run_id: int) -> set[tuple[int, str]]:
    rows = conn.execute("SELECT citation_id, check_name FROM findings WHERE run_id = ?", (run_id,))
    return {(row["citation_id"], row["check_name"]) for row in rows}


def record_finding(
    conn: sqlite3.Connection,
    run_id: int,
    citation_id: int,
    check_name: str,
    outcome: str,
    reason: str,
    evidence: dict,
) -> None:
    with conn:
        conn.execute(
            "INSERT INTO findings (run_id, citation_id, check_name, outcome, reason, evidence, checked_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (run_id, citation_id, check_name, outcome, reason, json.dumps(evidence), now()),
        )
