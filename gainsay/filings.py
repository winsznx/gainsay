"""Fetch one RECAP filing's PDF and text and describe it in a manifest.

The PDF is reused from disk when its sha1 still matches CourtListener's, so a
refetch costs one call. A scanned PDF with no text layer falls back to
CourtListener's OCR text, and the manifest says which one was used.
"""

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from gainsay.blocklist import assert_not_blocklisted
from gainsay.courtlistener import CourtListenerClient, storage_url
from gainsay.ledger import now
from gainsay.pdf_text import choose_text, extract_pdf_text

REPO_ROOT = Path(__file__).resolve().parent.parent
FILINGS_DIR = REPO_ROOT / "data" / "filings"


class FetchError(Exception):
    pass


@dataclass(frozen=True)
class Docket:
    court: str
    docket_number: str
    docket_id: int
    case_name: str


def fetch_filing(client: CourtListenerClient, docket: Docket, entry: int) -> tuple[dict, str]:
    assert_not_blocklisted(docket.court, docket.docket_number, entry)
    document = find_main_document(client, docket.docket_id, entry)
    document_number = int(document["document_number"])
    if document_number != entry:
        raise FetchError(f"asked for ECF {entry}, CourtListener returned ECF {document_number}")
    assert_not_blocklisted(docket.court, docket.docket_number, document_number)

    if not document.get("is_available") or not document.get("filepath_local"):
        raise FetchError(f"ECF {entry} has no PDF in RECAP")
    source_url = storage_url(document["filepath_local"])

    filing_dir = FILINGS_DIR / str(docket.docket_id)
    filing_dir.mkdir(parents=True, exist_ok=True)
    pdf_path = filing_dir / f"ecf{entry}.pdf"
    text_path = filing_dir / f"ecf{entry}.txt"

    pdf = cached_pdf(pdf_path, document.get("sha1"))
    if pdf is None:
        pdf = client.download(source_url)
        pdf_path.write_bytes(pdf)

    pdf_text, page_count = extract_pdf_text(pdf)
    text, method = choose_text(pdf_text, document.get("plain_text") or "")
    text_path.write_text(text)

    manifest = {
        "court": docket.court,
        "docket_number": docket.docket_number,
        "docket_id": docket.docket_id,
        "case_name": docket.case_name,
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
        "fetched_at": now(),
    }
    (filing_dir / f"ecf{entry}.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest, text


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
