"""Pick usable text for a filing from its PDF or CourtListener's plain_text.

Scanned filings have no text layer, but ECF still stamps a text header on
every page. Counting raw characters would mistake ten headers for a filing,
so length is measured on the body with those stamps removed.
"""

import io
import re

import pdfplumber

MIN_BODY_CHARS = 500

ECF_HEADER = re.compile(
    r"^Case \S+ Document \d+(?:-\d+)? Filed \d{2}/\d{2}/\d{2} Page \d+ of \d+$"
)


class TextUnavailable(Exception):
    pass


def extract_pdf_text(pdf: bytes) -> tuple[str, int]:
    with pdfplumber.open(io.BytesIO(pdf)) as document:
        pages = [page.extract_text() or "" for page in document.pages]
    return "\n".join(pages), len(pages)


def body_length(text: str) -> int:
    return sum(
        len(line.strip())
        for line in text.splitlines()
        if not ECF_HEADER.match(line.strip())
    )


def choose_text(pdf_text: str, api_text: str) -> tuple[str, str]:
    """Return (text, extraction_method), preferring the PDF's own text layer."""
    pdf_body = body_length(pdf_text)
    if pdf_body >= MIN_BODY_CHARS:
        return pdf_text, "pdfplumber"

    api_body = body_length(api_text)
    if api_body < MIN_BODY_CHARS:
        raise TextUnavailable(
            f"no usable text: pdfplumber body has {pdf_body} chars "
            f"and CourtListener plain_text body has {api_body}"
        )
    return api_text, "courtlistener_plain_text"
