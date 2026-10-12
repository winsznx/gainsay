"""Extract the case citations from a fetched filing into the ledger.

Makes no network calls. Re-extracting replaces the filing's citations, which
deletes the findings of every run on it, so that needs --force, and the ledger
is copied to data/archive/ first so those findings stay on record.

    .venv/bin/python scripts/extract_citations.py [--entry N] [--docket CONFIG] [--force]
"""

import argparse
import json
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path

from gainsay.dockets import DEFAULT_DOCKET_CONFIG, known_docket, load_docket_config
from gainsay.extract import extract
from gainsay.ledger import DEFAULT_LEDGER_PATH, connect, find_filing, save_extraction

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_ENTRY = 21


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--docket", type=Path, default=DEFAULT_DOCKET_CONFIG)
    parser.add_argument("--entry", type=int, default=DEFAULT_ENTRY)
    parser.add_argument("--attachment", type=int, help="the entry's attachment (exhibit) instead of its main document")
    parser.add_argument("--force", action="store_true", help="replace citations that runs have findings for")
    args = parser.parse_args()

    conn = connect()
    docket = known_docket(conn, load_docket_config(args.docket))
    filing = find_filing(conn, docket.docket_id, args.entry, args.attachment) if docket else None
    if filing is None:
        print(f"error: ECF {args.entry} is not in the ledger, run fetch_filing.py first", file=sys.stderr)
        return 1
    runs = conn.execute("SELECT COUNT(*) FROM runs WHERE filing_id = ?", (filing["id"],)).fetchone()[0]
    if runs and not args.force:
        print(
            f"error: ECF {args.entry} has {runs} check runs; re-extracting deletes their findings. "
            "Pass --force to do it anyway.",
            file=sys.stderr,
        )
        return 1

    if runs:
        archive = REPO_ROOT / "data" / "archive" / f"gainsay-{datetime.now(UTC):%Y%m%dT%H%M%SZ}.sqlite"
        archive.parent.mkdir(parents=True, exist_ok=True)
        conn.execute("PRAGMA wal_checkpoint")
        shutil.copy2(DEFAULT_LEDGER_PATH, archive)
        print(f"copied the ledger with {runs} runs' findings to {archive.relative_to(REPO_ROOT)}")

    extraction = extract((REPO_ROOT / filing["text_path"]).read_text())
    save_extraction(conn, filing["id"], extraction)

    rows = conn.execute(
        "SELECT c.ordinal, c.kind, c.pincite, c.in_quotation, c.quotes, a.ordinal AS case_ordinal, "
        "a.case_name, a.reporter_cites FROM citations c LEFT JOIN authorities a ON a.id = c.authority_id "
        "WHERE c.filing_id = ? ORDER BY c.ordinal",
        (filing["id"],),
    ).fetchall()
    cases = conn.execute("SELECT COUNT(*) FROM authorities WHERE filing_id = ?", (filing["id"],)).fetchone()[0]

    print(f"{filing['case_name']} ECF {filing['entry_number']}: "
          f"{len(rows)} case citations to {cases} cases, "
          f"skipped {extraction.non_case_citations} non-case citations, {extraction.table_entries} "
          f"table entries and {extraction.record_references} Id. cites to the record")
    print(f"{'#':>3} {'kind':5} {'case':3} {'pin':7} {'quoted':6} {'quotes':6} citation")
    for row in rows:
        cites = ", ".join(json.loads(row["reporter_cites"])) if row["reporter_cites"] else "unresolved"
        print(
            f"{row['ordinal']:>3} {row['kind']:5} {row['case_ordinal'] or '-':>3} "
            f"{row['pincite'] or '-':7} {'yes' if row['in_quotation'] else 'no':6} "
            f"{len(json.loads(row['quotes'])):>6} {row['case_name'] or '-'}, {cites}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
