"""Check every citation in the fetched filing and record the findings in the ledger.

Each citation gets its own neatlogs span tagged with the run version. A
CourtListener 429 or exhausted budget pauses the run; --resume picks it up
from the findings already recorded.

    set -a; source .env; set +a; .venv/bin/python scripts/check_citations.py [--resume RUN_ID]
"""

import argparse
import json
import logging
import sqlite3
import sys
from pathlib import Path

from gainsay.cache import CachedCourtListener
from gainsay.checker import CHECKS, Checker
from gainsay.courtlistener import BudgetExhausted, CourtListenerError
from gainsay.existence import Authority
from gainsay.ledger import (
    connect,
    finish_run,
    record_finding,
    recorded_checks,
    resume_run,
    start_run,
)
from gainsay.tracing import Tracing
from gainsay.version import run_version

REPO_ROOT = Path(__file__).resolve().parent.parent
MANIFEST_PATH = REPO_ROOT / "data" / "manifest.json"


def load_authorities(conn: sqlite3.Connection, filing_id: int) -> dict[int, Authority]:
    rows = conn.execute("SELECT * FROM authorities WHERE filing_id = ?", (filing_id,))
    return {
        row["id"]: Authority(
            id=row["id"],
            case_name=row["case_name"],
            reporter_cites=json.loads(row["reporter_cites"]),
            year=row["year"],
            court=row["court"],
        )
        for row in rows
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--resume", type=int, metavar="RUN_ID")
    args = parser.parse_args()
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")

    conn = connect()
    manifest = json.loads(MANIFEST_PATH.read_text())
    filing = conn.execute(
        "SELECT * FROM filings WHERE recap_document_id = ?", (manifest["recap_document_id"],)
    ).fetchone()
    if filing is None:
        print("error: filing not in the ledger, run extract_citations.py first", file=sys.stderr)
        return 1

    version = run_version()
    if args.resume:
        run = resume_run(conn, args.resume)
        if run["version"] != version:
            print(f"error: run {run['id']} ran {run['version']}, code is now {version}", file=sys.stderr)
            return 1
        run_id = run["id"]
    else:
        run_id = start_run(conn, filing["id"], version)

    citations = conn.execute(
        "SELECT c.*, a.case_name FROM citations c LEFT JOIN authorities a ON a.id = c.authority_id "
        "WHERE c.filing_id = ? ORDER BY c.ordinal",
        (filing["id"],),
    ).fetchall()
    done = recorded_checks(conn, run_id)
    api = CachedCourtListener(conn)
    tracing = Tracing("check-citations")
    try:
        with tracing.span("gainsay.check_run", run_id=run_id, run_version=version, filing_id=filing["id"]):
            checker = Checker(api, load_authorities(conn, filing["id"]), citations)
            for citation in citations:
                if all((citation["id"], check) in done for check in CHECKS):
                    continue
                with tracing.span(
                    "gainsay.check_citation",
                    kind="CHAIN",
                    run_id=run_id,
                    run_version=version,
                    citation=citation["ordinal"],
                    case_name=citation["case_name"] or "unresolved",
                ) as span:
                    for finding in checker.check(citation):
                        if (citation["id"], finding.check) in done:
                            continue
                        record_finding(
                            conn, run_id, citation["id"], finding.check,
                            finding.outcome, finding.reason, finding.evidence,
                        )
                        if span is not None:
                            span.set_attribute(f"gainsay.{finding.check}", finding.outcome)
        finish_run(conn, run_id, "complete")
    except BudgetExhausted as exc:
        finish_run(conn, run_id, "paused", str(exc))
        print(f"paused: {exc}. Resume with --resume {run_id}", file=sys.stderr)
        return 2
    except CourtListenerError as exc:
        finish_run(conn, run_id, "failed", str(exc))
        print(f"error: {exc}", file=sys.stderr)
        return 1
    finally:
        tracing.close()
        print(f"CourtListener calls: {api.calls}, served from ledger: {api.cache_hits}")

    print_run(conn, run_id)
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
