"""Register a filing from a PDF you already have, with no CourtListener call.

For a filing served on you before RECAP has it, or one downloaded from RECAP
while the API quota is spent. The ids are the real CourtListener ones: the
docket id is in the docket's URL, and the RECAP document id is on the
document's page ("id:NNN" in its search link). The PDF is extracted and its
citations saved exactly as fetch_filing.py and extract_citations.py would.

    .venv/bin/python scripts/import_filing.py --docket dockets/gauthier-v-goodyear.json --entry 41 \\
        --pdf ecf41.pdf --docket-id 67624744 --recap-document-id 414407406 \\
        --source-url https://storage.courtlistener.com/recap/.../gov.uscourts.txed.223848.41.0.pdf \\
        --description "Response to Motion"
"""

import argparse
import hashlib
import json
import sys
from pathlib import Path

from gainsay.blocklist import BlocklistedDocument, assert_not_blocklisted
from gainsay.dockets import DEFAULT_DOCKET_CONFIG, known_docket, load_docket_config
from gainsay.extract import extract
from gainsay.filings import FILINGS_DIR, REPO_ROOT, ecf_label
from gainsay.ledger import connect, now, save_extraction, upsert_filing
from gainsay.pdf_text import TextUnavailable, choose_text, extract_pdf_text


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--docket", type=Path, default=DEFAULT_DOCKET_CONFIG)
    parser.add_argument("--entry", type=int, required=True)
    parser.add_argument("--attachment", type=int)
    parser.add_argument("--pdf", type=Path, required=True)
    parser.add_argument("--docket-id", type=int, required=True, help="CourtListener's docket id")
    parser.add_argument("--recap-document-id", type=int, required=True, help="CourtListener's RECAP document id")
    parser.add_argument("--source-url", required=True, help="where the PDF is published")
    parser.add_argument("--description", required=True)
    args = parser.parse_args()

    config = load_docket_config(args.docket)
    try:
        assert_not_blocklisted(config.court, config.docket_number, args.entry)
    except BlocklistedDocument as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    pdf = args.pdf.read_bytes()
    try:
        pdf_text, page_count = extract_pdf_text(pdf)
        text, method = choose_text(pdf_text, "")
    except TextUnavailable as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    conn = connect()
    docket = known_docket(conn, config)
    if docket is None:
        with conn:
            conn.execute(
                "INSERT INTO dockets (id, court, docket_number, case_name, resolved_at) VALUES (?, ?, ?, ?, ?)",
                (args.docket_id, config.court, config.docket_number, config.name, now()),
            )
    elif docket.docket_id != args.docket_id:
        print(f"error: the ledger has {config.name} as docket {docket.docket_id}, not {args.docket_id}", file=sys.stderr)
        return 1

    stem = ecf_label(args.entry, args.attachment).lower().replace(" ", "")
    filing_dir = FILINGS_DIR / str(args.docket_id)
    filing_dir.mkdir(parents=True, exist_ok=True)
    pdf_path, text_path = filing_dir / f"{stem}.pdf", filing_dir / f"{stem}.txt"
    pdf_path.write_bytes(pdf)
    text_path.write_text(text)
    manifest = {
        "court": config.court,
        "docket_number": config.docket_number,
        "docket_id": args.docket_id,
        "case_name": config.name,
        "entry_number": args.entry,
        "attachment_number": args.attachment,
        "recap_document_id": args.recap_document_id,
        "description": args.description,
        "source_url": args.source_url,
        "sha256": hashlib.sha256(pdf).hexdigest(),
        "byte_size": len(pdf),
        "page_count": page_count,
        "text_length": len(text),
        "extraction_method": method,
        "imported_from": "local PDF",
        "pdf_path": str(pdf_path.relative_to(REPO_ROOT)),
        "text_path": str(text_path.relative_to(REPO_ROOT)),
        "fetched_at": now(),
    }
    (filing_dir / f"{stem}.json").write_text(json.dumps(manifest, indent=2) + "\n")
    filing_id = upsert_filing(conn, manifest)
    extraction = extract(text)
    save_extraction(conn, filing_id, extraction)
    print(f"{config.name}, {ecf_label(args.entry, args.attachment)}: {page_count} pages, "
          f"{len(extraction.citations)} case citations saved as filing {filing_id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
