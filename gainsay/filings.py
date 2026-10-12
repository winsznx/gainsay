"""Fetch one RECAP filing's PDF and text and describe it in a manifest.

A filing is a docket entry's main document or one of its attachments
(exhibits). One request lists them all. The PDF is reused from disk when its
sha1 still matches CourtListener's, so a refetch costs one call. A scanned
PDF with no text layer falls back to CourtListener's OCR text, and the
manifest says which one was used.
"""

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from gainsay.blocklist import assert_not_blocklisted
from gainsay.cache import CachedCourtListener
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


def fetch_filing(
    client: CourtListenerClient,
    docket: Docket,
    entry: int,
    attachment: int | None = None,
    documents: list[dict] | None = None,
) -> tuple[dict, str]:
    """The main document, or attachment N, with documents from list_documents if already fetched."""
    assert_not_blocklisted(docket.court, docket.docket_number, entry)
    documents = documents if documents is not None else list_documents(client, docket.docket_id, entry)
    document = pick_document(documents, docket.docket_id, entry, attachment)
    document_number = int(document["document_number"])
    if document_number != entry:
        raise FetchError(f"asked for ECF {entry}, CourtListener returned ECF {document_number}")
    assert_not_blocklisted(docket.court, docket.docket_number, document_number)

    label = ecf_label(entry, attachment)
    if not document.get("is_available") or not document.get("filepath_local"):
        raise FetchError(f"{label} has no PDF in RECAP")
    source_url = storage_url(document["filepath_local"])

    filing_dir = FILINGS_DIR / str(docket.docket_id)
    filing_dir.mkdir(parents=True, exist_ok=True)
    stem = label.lower().replace(" ", "")
    pdf_path = filing_dir / f"{stem}.pdf"
    text_path = filing_dir / f"{stem}.txt"

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
        "attachment_number": attachment,
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
    (filing_dir / f"{stem}.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest, text


def ecf_label(entry: int, attachment: int | None = None) -> str:
    """How a court cites the document: "ECF 29", or "ECF 29-1" for its first attachment."""
    return f"ECF {entry}" if attachment is None else f"ECF {entry}-{attachment}"


def list_documents(client: CourtListenerClient | CachedCourtListener, docket_id: int, entry: int) -> list[dict]:
    """The entry's main document and its attachments, in one request (from the ledger when cached)."""
    return client.get_json(
        "recap-documents/",
        {"docket_entry__docket__id": docket_id, "docket_entry__entry_number": entry},
    )["results"]


def available_attachments(documents: list[dict]) -> list[int]:
    """Attachment numbers whose PDFs RECAP holds, in order."""
    return sorted(
        _attachment(d)
        for d in documents
        if _attachment(d) is not None and d.get("is_available") and d.get("filepath_local")
    )


def pick_document(documents: list[dict], docket_id: int, entry: int, attachment: int | None) -> dict:
    wanted = [d for d in documents if _attachment(d) == attachment]
    if len(wanted) != 1:
        raise FetchError(
            f"expected one {'main document' if attachment is None else f'attachment {attachment}'} for "
            f"docket {docket_id} ECF {entry}, found {len(wanted)} among {len(documents)} documents"
        )
    return wanted[0]


def cached_pdf(path: Path, expected_sha1: str | None) -> bytes | None:
    """Reuse a PDF from an earlier run only if it still matches CourtListener's hash."""
    if not expected_sha1 or not path.exists():
        return None
    pdf = path.read_bytes()
    return pdf if hashlib.sha1(pdf).hexdigest() == expected_sha1 else None


def _attachment(document: dict) -> int | None:
    number = document.get("attachment_number")
    return None if number is None else int(number)
