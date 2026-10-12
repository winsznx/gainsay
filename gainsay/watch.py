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
from gainsay.filings import Docket, fetch_filing
from gainsay.ledger import find_filing, save_extraction, upsert_filing
from gainsay.proposition import Judge
from gainsay.runner import RunResult, paused_run, run_checks
from gainsay.tracing import Tracing


def prepare_filing(conn: sqlite3.Connection, client: CourtListenerClient, docket: Docket, entry: int) -> int:
    filing = find_filing(conn, docket.docket_id, entry)
    if filing is not None and filing["clean_text"] is not None:
        return filing["id"]
    manifest, text = fetch_filing(client, docket, entry)
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
