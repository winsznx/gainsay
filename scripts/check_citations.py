"""Check every citation in a fetched filing and record the findings in the ledger.

Each citation gets its own neatlogs span tagged with the run version. A
CourtListener 429, an exhausted budget or a Claude rate limit pauses the run;
--resume picks it up from the findings already recorded.

    set -a; source .env; set +a
    .venv/bin/python scripts/check_citations.py [--entry N] [--docket CONFIG] [--resume RUN_ID]
"""

import argparse
import logging
import sqlite3
import sys
from pathlib import Path

from gainsay.cache import CachedCourtListener
from gainsay.cap import Cap
from gainsay.checker import CHECKS
from gainsay.dockets import DEFAULT_DOCKET_CONFIG, known_docket, load_docket_config
from gainsay.ledger import connect, find_filing
from gainsay.proposition import ClaudeJudge, MissingCredentials, anthropic_client
from gainsay.runner import Simulation, VersionMismatch, paused_run, run_checks
from gainsay.tracing import Tracing
from gainsay.version import run_version

DEFAULT_ENTRY = 21


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--docket", type=Path, default=DEFAULT_DOCKET_CONFIG)
    parser.add_argument("--entry", type=int, default=DEFAULT_ENTRY)
    parser.add_argument("--resume", type=int, metavar="RUN_ID")
    parser.add_argument("--simulate-outage-after", type=int, metavar="N",
                        help="pause with a labelled simulated outage after N citations")
    parser.add_argument("--simulate-crash-after", type=int, metavar="N",
                        help="kill the process after N citations, leaving a labelled note in the ledger")
    args = parser.parse_args()
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")

    conn = connect()
    docket = known_docket(conn, load_docket_config(args.docket))
    filing = find_filing(conn, docket.docket_id, args.entry) if docket else None
    if filing is None or filing["clean_text"] is None:
        print(f"error: ECF {args.entry} has no extracted citations, run extract_citations.py first", file=sys.stderr)
        return 1
    try:
        client = anthropic_client()
    except MissingCredentials as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    api = CachedCourtListener(conn)
    cap = Cap()
    tracing = Tracing("check-citations")
    judge = ClaudeJudge(conn, tracing.wrap(client))
    version = run_version()
    simulation = None
    if args.simulate_outage_after is not None or args.simulate_crash_after is not None:
        simulation = Simulation(args.simulate_outage_after, args.simulate_crash_after)
    resume = args.resume or paused_run(conn, filing["id"], version)
    if resume and not args.resume:
        print(f"resuming run {resume}, which was paused or interrupted")
    try:
        result = run_checks(
            conn, filing["id"], version, api, judge, tracing, resume_run_id=resume, simulation=simulation,
            cap=cap,
        )
    except (VersionMismatch, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    finally:
        tracing.close()
        print(f"CourtListener calls: {api.calls}, served from ledger: {api.cache_hits}")
        print(f"Caselaw Access Project files fetched: {cap.fetches}")
        print(f"Claude calls: {judge.calls}, served from ledger: {judge.cache_hits}")

    if result.status == "paused":
        print(f"paused: {result.reason}. Resume with --resume {result.run_id}", file=sys.stderr)
        return 2
    if result.status == "failed":
        print(f"error: {result.reason}", file=sys.stderr)
        return 1
    print_run(conn, result.run_id)
    return 0


def print_run(conn: sqlite3.Connection, run_id: int) -> None:
    run = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
    print(f"run {run_id} ({run['version']}): {run['status']}")
    rows = conn.execute(
        "SELECT c.ordinal, a.case_name, f.check_name, f.outcome, f.reason FROM findings f "
        "JOIN citations c ON c.id = f.citation_id LEFT JOIN authorities a ON a.id = c.authority_id "
        "WHERE f.run_id = ? ORDER BY c.ordinal, f.check_name",
        (run_id,),
    ).fetchall()
    by_citation: dict[int, dict] = {}
    for row in rows:
        entry = by_citation.setdefault(row["ordinal"], {"case": row["case_name"] or "-"})
        entry[row["check_name"]] = (row["outcome"], row["reason"])
    print(f"{'#':>3} {'case':44} " + " ".join(f"{check:12}" for check in CHECKS))
    for ordinal, entry in by_citation.items():
        outcomes = " ".join(f"{entry[check][0]:12}" for check in CHECKS)
        print(f"{ordinal:>3} {entry['case'][:44]:44} {outcomes}")
        for check in CHECKS:
            if entry[check][0] != "not_applicable":
                print(f"      {check}: {entry[check][1]}")


if __name__ == "__main__":
    sys.exit(main())
