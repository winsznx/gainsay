"""Fetch one RECAP filing's PDF and text from CourtListener.

Defaults to Mata v. Avianca, S.D.N.Y. 1:22-cv-01461, ECF 21: the March 1, 2023
affirmation in opposition, the first filing Gainsay checks.

Run with .env loaded:
    set -a; source .env; set +a; .venv/bin/python scripts/fetch_filing.py
"""

import argparse
import hashlib
import json
import logging
import sys
from datetime import UTC, datetime
from pathlib import Path

from gainsay.blocklist import BlocklistedDocument, assert_not_blocklisted, normalize_docket_number
from gainsay.courtlistener import CourtListenerClient, CourtListenerError, storage_url
from gainsay.pdf_text import TextUnavailable, choose_text, extract_pdf_text
from gainsay.tracing import Tracing

COURT = "nysd"
DOCKET_NUMBER = "1:22-cv-01461"
DEFAULT_ENTRY = 21
PREVIEW_LINES = 40

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data"


class FetchError(Exception):
    pass


def same_docket(candidate: str, target: str) -> bool:
    try:
        return normalize_docket_number(candidate) == normalize_docket_number(target)
    except ValueError:
        return False


def find_docket(client: CourtListenerClient, court: str, docket_number: str) -> dict:
    results = client.get_json(
        "search/", {"type": "r", "court": court, "docket_number": docket_number}
    )["results"]
    matches = [
        r
        for r in results
        if r.get("court_id") == court and same_docket(r.get("docketNumber", ""), docket_number)
    ]
    if len(matches) != 1:
        raise FetchError(
            f"expected one {court} docket {docket_number}, "
            f"search returned {len(matches)} matches in {len(results)} results"
        )
    return matches[0]


def find_main_document(client: CourtListenerClient, docket_id: int, entry: int) -> dict:
    results = client.get_json(
        "recap-documents/",
        {"docket_entry__docket__id": docket_id, "docket_entry__entry_number": entry},
    )["results"]
    main = [d for d in results if d.get("attachment_number") is None]
    if len(main) != 1:
        raise FetchError(
            f"expected one main document for docket {docket_id} ECF {entry}, "
            f"found {len(main)} among {len(results)} documents"
        )
    return main[0]


def cached_pdf(path: Path, expected_sha1: str | None) -> bytes | None:
    """Reuse a PDF from an earlier run only if it still matches CourtListener's hash."""
    if not expected_sha1 or not path.exists():
        return None
    pdf = path.read_bytes()
    return pdf if hashlib.sha1(pdf).hexdigest() == expected_sha1 else None


def fetch(client: CourtListenerClient, entry: int) -> tuple[dict, str]:
    docket = find_docket(client, COURT, DOCKET_NUMBER)
    document = find_main_document(client, docket["docket_id"], entry)

    document_number = int(document["document_number"])
    if document_number != entry:
        raise FetchError(f"asked for ECF {entry}, CourtListener returned ECF {document_number}")
    assert_not_blocklisted(COURT, DOCKET_NUMBER, document_number)

    if not document.get("is_available") or not document.get("filepath_local"):
        raise FetchError(f"ECF {entry} has no PDF in RECAP")
    source_url = storage_url(document["filepath_local"])

    filing_dir = DATA_DIR / "filings" / str(docket["docket_id"])
    filing_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = filing_dir / f"ecf{entry}.pdf"
    text_path = filing_dir / f"ecf{entry}.txt"

    pdf = cached_pdf(pdf_path, document.get("sha1"))
    if pdf is None:
        pdf = client.download(source_url)
        pdf_path.write_bytes(pdf)
    else:
        print(f"reusing {pdf_path.relative_to(REPO_ROOT)}, sha1 matches", file=sys.stderr)

    pdf_text, page_count = extract_pdf_text(pdf)
    text, method = choose_text(pdf_text, document.get("plain_text") or "")
    text_path.write_text(text)

    manifest = {
        "court": COURT,
        "docket_number": DOCKET_NUMBER,
        "docket_id": docket["docket_id"],
        "case_name": docket.get("caseName"),
        "entry_number": entry,
        "recap_document_id": document["id"],
        "description": document.get("description"),
        "source_url": source_url,
        "sha256": hashlib.sha256(pdf).hexdigest(),
        "courtlistener_sha1_match": hashlib.sha1(pdf).hexdigest() == document.get("sha1"),
        "byte_size": len(pdf),
        "page_count": page_count,
        "text_length": len(text),
        "extraction_method": method,
        "ocr_status": document.get("ocr_status"),
        "pdf_path": str(pdf_path.relative_to(REPO_ROOT)),
        "text_path": str(text_path.relative_to(REPO_ROOT)),
        "fetched_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    (DATA_DIR / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest, text


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--entry", type=int, default=DEFAULT_ENTRY)
    args = parser.parse_args()
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")

    try:
        assert_not_blocklisted(COURT, DOCKET_NUMBER, args.entry)
        client = CourtListenerClient()
    except (BlocklistedDocument, CourtListenerError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    tracing = Tracing("fetch-filing")
    try:
        with tracing.span(
            "gainsay.fetch_filing",
            court=COURT,
            docket_number=DOCKET_NUMBER,
            entry_number=args.entry,
        ):
            manifest, text = fetch(client, args.entry)
    except (BlocklistedDocument, CourtListenerError, FetchError, TextUnavailable) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    finally:
        tracing.close()
        print(f"CourtListener calls: {client.calls}")

    print(json.dumps(manifest, indent=2))
    print(f"--- first {PREVIEW_LINES} lines of {manifest['text_path']} ---")
    print("\n".join(text.splitlines()[:PREVIEW_LINES]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
