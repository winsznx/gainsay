import pytest

from gainsay.pdf_text import TextUnavailable, body_length, choose_text

HEADERS_ONLY = "\n".join(
    f"Case 1:22-cv-01461-PKC Document 21 Filed 03/01/23 Page {n} of 10"
    for n in range(1, 11)
)
BODY = "The plaintiff relies on Varghese v. China Southern Airlines. " * 20


def test_ecf_headers_do_not_count_as_body():
    assert len(HEADERS_ONLY) > 500
    assert body_length(HEADERS_ONLY) == 0


def test_attachment_headers_are_recognized():
    assert body_length("Case 1:22-cv-01461-PKC Document 29-1 Filed 04/25/23 Page 1 of 5") == 0


def test_scanned_pdf_falls_back_to_courtlistener_text():
    text, method = choose_text(HEADERS_ONLY, BODY)
    assert method == "courtlistener_plain_text"
    assert text == BODY


def test_pdf_text_layer_is_preferred():
    pdf_text = HEADERS_ONLY + "\n" + BODY
    text, method = choose_text(pdf_text, "different OCR text " * 50)
    assert method == "pdfplumber"
    assert text == pdf_text


def test_raises_when_neither_source_has_a_body():
    with pytest.raises(TextUnavailable, match="0 chars"):
        choose_text(HEADERS_ONLY, HEADERS_ONLY)
