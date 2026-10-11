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
from gainsay.courtlistener import BudgetExhausted, CourtListenerError
from gainsay.existence import Authority, Lookup, check_authority
from gainsay.findings import UNVERIFIABLE, Finding
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
CHECKS = ("existence", "identity")


class Checker:
    def __init__(self, api: CachedCourtListener, authorities: dict[int, Authority]):
        self._api = api
        self._authorities = authorities
        self._lookup = Lookup(api, list(authorities.values()))
        self._by_authority: dict[int, tuple[Finding, Finding]] = {}

    def check(self, citation: sqlite3.Row) -> list[Finding]:
        authority_id = citation["authority_id"]
        if authority_id is None:
            reason = "short citation could not be tied to a full citation in this filing"
            return [Finding(check, UNVERIFIABLE, reason) for check in CHECKS]
        if authority_id not in self._by_authority:
            self._by_authority[authority_id] = check_authority(
                self._api, self._lookup, self._authorities[authority_id]
            )
        return list(self._by_authority[authority_id])


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
            checker = Checker(api, load_authorities(conn, filing["id"]))
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
    for ordinal, entry in by_citation.items():
        existence, identity = entry["existence"], entry["identity"]
        print(f"{ordinal:>3} {entry['case'][:48]:48} existence={existence[0]:12} identity={identity[0]}")
        print(f"      existence: {existence[1]}")
        print(f"      identity:  {identity[1]}")


if __name__ == "__main__":
    sys.exit(main())
