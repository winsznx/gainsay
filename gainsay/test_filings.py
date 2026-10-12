import pytest

from gainsay.filings import FetchError, available_attachments, ecf_label, pick_document

DOCUMENTS = [
    {"id": 10, "document_number": "29", "attachment_number": None, "is_available": True, "filepath_local": "a.pdf"},
    {"id": 11, "document_number": "29", "attachment_number": 1, "is_available": True, "filepath_local": "b.pdf"},
    {"id": 12, "document_number": "29", "attachment_number": "2", "is_available": True, "filepath_local": "c.pdf"},
    {"id": 13, "document_number": "29", "attachment_number": 3, "is_available": False, "filepath_local": None},
]


def test_exhibits_are_cited_like_the_court_cites_them():
    assert ecf_label(29) == "ECF 29"
    assert ecf_label(29, 1) == "ECF 29-1"


def test_only_exhibits_recap_holds_are_listed_whatever_their_number_type():
    assert available_attachments(DOCUMENTS) == [1, 2]


def test_the_main_document_or_an_attachment_is_picked():
    assert pick_document(DOCUMENTS, 1, 29, None)["id"] == 10
    assert pick_document(DOCUMENTS, 1, 29, 2)["id"] == 12
    with pytest.raises(FetchError, match="attachment 7"):
        pick_document(DOCUMENTS, 1, 29, 7)
