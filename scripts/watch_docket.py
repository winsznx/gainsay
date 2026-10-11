"""Poll a docket and check the opposing side's filings that have no finished run.

Every new entry is recorded. Entries whose description names the opposing
party or counsel (from the docket config) are fetched, extracted and checked;
the rest are listed and left alone. A paused run stops the watch, and the
next watch resumes it.

    set -a; source .env; set +a
    .venv/bin/python scripts/watch_docket.py [--docket CONFIG] [--list]
"""

import argparse
import logging
import sys
from pathlib import Path

from gainsay.blocklist import BlocklistedDocument
from gainsay.cache import CachedCourtListener
from gainsay.courtlistener import CourtListenerClient, CourtListenerError
from gainsay.dockets import (
    DEFAULT_DOCKET_CONFIG,
    load_docket_config,
    opposing_names,
    poll_entries,
    resolve_docket,
    unchecked_opposing_entries,
)
from gainsay.filings import FetchError
from gainsay.ledger import connect
from gainsay.pdf_text import TextUnavailable
from gainsay.proposition import ClaudeJudge, MissingCredentials, anthropic_client
from gainsay.report import load_run
from gainsay.tracing import Tracing
from gainsay.version import run_version
from gainsay.watch import check_entry


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--docket", type=Path, default=DEFAULT_DOCKET_CONFIG)
    parser.add_argument("--list", action="store_true", help="poll and list, don't check anything")
    args = parser.parse_args()
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")

    config = load_docket_config(args.docket)
    conn = connect()
    client = CourtListenerClient()
    try:
        docket = resolve_docket(conn, client, config)
        new = poll_entries(conn, client, docket)
    except (CourtListenerError, FetchError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    opposing = [e for e in new if opposing_names(e["description"], config)]
    print(f"{config.name}: {len(new)} new docket entries, {len(opposing)} from the opposing side")
    pending = unchecked_opposing_entries(conn, docket, config)
    for entry in pending:
        names = ", ".join(opposing_names(entry["description"], config))
        print(f"  ECF {entry['entry_number']:>3} ({entry['date_filed']}, names {names}): {entry['description'][:100]}")
    if args.list or not pending:
        print(f"{len(pending)} opposing filings have no finished check run. CourtListener calls: {client.calls}")
        return 0

    try:
        claude = anthropic_client()
    except MissingCredentials as exc:
        print(f"error: {exc}. Run with --list to poll without checking.", file=sys.stderr)
        return 1

    api = CachedCourtListener(conn)
    tracing = Tracing("watch-docket")
    judge = ClaudeJudge(conn, tracing.wrap(claude))
    version = run_version()
    status = 0
    try:
        for entry in pending:
            number = entry["entry_number"]
            try:
                result = check_entry(conn, client, api, judge, tracing, docket, number, version)
            except (BlocklistedDocument, FetchError, TextUnavailable) as exc:
                print(f"ECF {number}: skipped, {exc}")
                continue
            report = load_run(conn, result.run_id)
            print(f"ECF {number}: run {result.run_id} {result.status}. {report.headline if report else ''}")
            if result.status == "paused":
                print(f"paused: {result.reason}. The next watch resumes it.", file=sys.stderr)
                status = 2
                break
    finally:
        tracing.close()
        print(f"CourtListener calls: {client.calls + api.calls}, served from ledger: {api.cache_hits}")
        print(f"Claude calls: {judge.calls}, served from ledger: {judge.cache_hits}")
    return status


if __name__ == "__main__":
    sys.exit(main())
