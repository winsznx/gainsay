import pytest

from gainsay.findings import FAIL, NOT_APPLICABLE, PASS, UNVERIFIABLE
from gainsay.opinions import OpinionText
from gainsay.pincite import check_pincite, parse_pin, pin_reporter

KAISER = [OpinionText(1, "020lead", "xml_harvard", "text", [(10, 594), (20, 595)])]


@pytest.mark.parametrize(
    ("pin", "pages"),
    [("598", (598, 598)), ("371-72", (371, 372)), ("1165-66", (1165, 1166)), ("161, 119", (161, 161))],
)
def test_parse_pin(pin, pages):
    assert parse_pin(pin) == pages


def test_pin_past_the_last_page_fails():
    finding = check_pincite("598", "391 U.S. 593", KAISER)
    assert finding.outcome == FAIL
    assert "runs from page 593 to 595" in finding.reason


def test_pin_inside_the_opinion_passes():
    assert check_pincite("595", "391 U.S. 593", KAISER).outcome == PASS


def test_pin_before_the_first_page_fails():
    assert check_pincite("590", "391 U.S. 593", KAISER).outcome == FAIL


def test_page_breaks_from_a_parallel_reporter_are_ignored():
    opinions = [OpinionText(1, "020lead", "x", "t", [(5, 594), (9, 1755), (12, 1756)])]
    assert check_pincite("1756", "391 U.S. 593", opinions).outcome == FAIL


def test_no_page_breaks_is_unverifiable_unless_pin_is_the_first_page():
    bare = [OpinionText(1, "020lead", "plain_text", "t", [])]
    assert check_pincite("1165", "821 F.2d 1147", bare).outcome == UNVERIFIABLE
    assert check_pincite("1147", "821 F.2d 1147", bare).outcome == PASS


def test_database_cites_and_missing_pins():
    assert check_pincite("3", "2019 WL 4639462", KAISER).outcome == UNVERIFIABLE
    assert check_pincite(None, "391 U.S. 593", KAISER).outcome == NOT_APPLICABLE


def test_pin_reporter_by_citation_kind():
    tseng = ["525 U.S. 155", "119 S. Ct. 662", "142 L. Ed. 2d 576"]
    assert pin_reporter("full", "Tseng, 525 U.S. 155, 161, 119 S.Ct. 662", tseng, None) == "525 U.S. 155"
    assert pin_reporter("id", "Id. at 166, 119 S. Ct. 662", tseng, "525 U.S. 155") == "525 U.S. 155"
    assert pin_reporter("short", "Tseng, 525 U.S., at 161", tseng, None) == "525 U.S. 155"
