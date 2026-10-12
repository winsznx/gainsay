"""Bring one docket entry from RECAP to a finished check run.

A filing already in the ledger is not fetched or extracted again, so
re-running the watcher after a pause costs no calls for work already done,
and a paused run of the same code is resumed instead of started over.
"""

import sqlite3

from gainsay.cache import CachedCourtListener
from gainsay.cap import Cap
from gainsay.courtlistener import CourtListenerClient
from gainsay.extract import extract
from gainsay.filings import Docket, available_attachments, fetch_filing, list_documents
from gainsay.ledger import find_filing, save_extraction, upsert_filing
from gainsay.proposition import Judge
from gainsay.runner import RunResult, paused_run, run_checks
from gainsay.tracing import Tracing


def prepare_filing(
    conn: sqlite3.Connection,
    client: CourtListenerClient,
    docket: Docket,
    entry: int,
    attachment: int | None = None,
    documents: list[dict] | None = None,
) -> int:
    filing = find_filing(conn, docket.docket_id, entry, attachment)
    if filing is not None and filing["clean_text"] is not None:
        return filing["id"]
    manifest, text = fetch_filing(client, docket, entry, attachment, documents)
    filing_id = upsert_filing(conn, manifest)
    save_extraction(conn, filing_id, extract(text))
    return filing_id


def check_entry(
    conn: sqlite3.Connection,
    client: CourtListenerClient,
    api: CachedCourtListener,
    judge: Judge,
    tracing: Tracing,
    docket: Docket,
    entry: int,
    version: str,
    cap: Cap | None = None,
) -> RunResult:
    filing_id = prepare_filing(conn, client, docket, entry)
    return run_checks(
        conn, filing_id, version, api, judge, tracing, resume_run_id=paused_run(conn, filing_id, version), cap=cap
    )


def check_exhibits(
    conn: sqlite3.Connection,
    client: CourtListenerClient,
    api: CachedCourtListener,
    judge: Judge,
    tracing: Tracing,
    docket: Docket,
    entry: int,
    version: str,
    cap: Cap | None = None,
) -> list[tuple[int, RunResult]]:
    """Check each exhibit RECAP holds for the entry, as its own filing.

    The entry's documents are listed through the ledger cache, so an entry is
    listed once however often the watcher runs; exhibits with a finished run
    are skipped.
    """
    finished = {
        row["attachment_number"]
        for row in conn.execute(
            "SELECT f.attachment_number FROM filings f JOIN runs r ON r.filing_id = f.id "
            "WHERE f.docket_id = ? AND f.entry_number = ? AND f.attachment_number IS NOT NULL "
            "AND r.status = 'complete'",
            (docket.docket_id, entry),
        )
    }
    documents = list_documents(api, docket.docket_id, entry)
    results = []
    for attachment in available_attachments(documents):
        if attachment in finished:
            continue
        filing_id = prepare_filing(conn, client, docket, entry, attachment, documents)
        result = run_checks(
            conn, filing_id, version, api, judge, tracing, resume_run_id=paused_run(conn, filing_id, version), cap=cap
        )
        results.append((attachment, result))
    return results
