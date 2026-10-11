"""Extract the case citations from the fetched filing into the ledger.

Reads data/manifest.json from fetch_filing.py. Makes no network calls.
    .venv/bin/python scripts/extract_citations.py
"""

import json
import sys
from pathlib import Path

from gainsay.extract import extract
from gainsay.ledger import connect, save_extraction, upsert_filing

REPO_ROOT = Path(__file__).resolve().parent.parent
MANIFEST_PATH = REPO_ROOT / "data" / "manifest.json"


def main() -> int:
    if not MANIFEST_PATH.exists():
        print(f"error: {MANIFEST_PATH.relative_to(REPO_ROOT)} not found, run fetch_filing.py first", file=sys.stderr)
        return 1
    manifest = json.loads(MANIFEST_PATH.read_text())
    extraction = extract((REPO_ROOT / manifest["text_path"]).read_text())

    conn = connect()
    filing_id = upsert_filing(conn, manifest)
    save_extraction(conn, filing_id, extraction)

    rows = conn.execute(
        "SELECT c.ordinal, c.kind, c.pincite, c.in_quotation, c.quotes, a.ordinal AS case_ordinal, "
        "a.case_name, a.reporter_cites FROM citations c LEFT JOIN authorities a ON a.id = c.authority_id "
        "WHERE c.filing_id = ? ORDER BY c.ordinal",
        (filing_id,),
    ).fetchall()
    cases = conn.execute("SELECT COUNT(*) FROM authorities WHERE filing_id = ?", (filing_id,)).fetchone()[0]

    print(f"{manifest['case_name']} ECF {manifest['entry_number']}: "
          f"{len(rows)} case citations to {cases} cases, "
          f"{extraction.non_case_citations} non-case citations skipped")
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
