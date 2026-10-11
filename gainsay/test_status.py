import pytest

from gainsay.findings import FAIL, NOT_APPLICABLE, PASS, UNVERIFIABLE
from gainsay.status import (
    DOESNT_SUPPORT,
    NOT_FOUND,
    QUOTE_NOT_IN_OPINION,
    UNVERIFIABLE_STATUS,
    VERIFIED,
    WRONG_CASE,
    pincite_flag,
    primary_status,
)

ALL_PASS = {
    "existence": PASS, "identity": PASS, "quotation": PASS, "proposition": PASS, "pincite": PASS,
}


@pytest.mark.parametrize(
    ("changes", "status"),
    [
        ({}, VERIFIED),
        ({"quotation": NOT_APPLICABLE, "pincite": NOT_APPLICABLE}, VERIFIED),
        ({"existence": FAIL, "identity": FAIL, "quotation": FAIL}, NOT_FOUND),
        ({"identity": FAIL, "proposition": FAIL}, WRONG_CASE),
        ({"quotation": FAIL, "proposition": FAIL}, QUOTE_NOT_IN_OPINION),
        ({"proposition": FAIL}, DOESNT_SUPPORT),
        ({"identity": UNVERIFIABLE}, UNVERIFIABLE_STATUS),
        ({"proposition": UNVERIFIABLE, "pincite": FAIL}, UNVERIFIABLE_STATUS),
        ({"pincite": FAIL}, VERIFIED),
    ],
)
def test_first_failure_wins_and_pincite_never_sets_status(changes, status):
    assert primary_status({**ALL_PASS, **changes}) == status


def test_missing_check_is_incomplete_unless_an_earlier_check_failed():
    assert primary_status({"existence": PASS, "identity": PASS}) is None
    assert primary_status({"existence": FAIL}) == NOT_FOUND
    assert primary_status({"existence": PASS, "identity": PASS, "quotation": PASS}) is None


def test_pincite_flag():
    assert pincite_flag({**ALL_PASS, "pincite": FAIL})
    assert not pincite_flag({**ALL_PASS, "pincite": UNVERIFIABLE})
