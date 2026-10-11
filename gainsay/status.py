"""Primary status: one label per citation, derived from its findings.

Checks are read in priority order and the first failure wins. A check that
hasn't run yet makes the status undecidable only if no earlier check already
failed. A failed pincite never changes the status; it is reported as a flag.
"""

from gainsay.findings import FAIL, UNVERIFIABLE

NOT_FOUND = "Not found in searched sources"
WRONG_CASE = "Wrong case"
QUOTE_NOT_IN_OPINION = "Quote not in opinion"
DOESNT_SUPPORT = "Doesn't support the proposition"
UNVERIFIABLE_STATUS = "Unverifiable"
VERIFIED = "Verified"

STATUSES = (NOT_FOUND, WRONG_CASE, QUOTE_NOT_IN_OPINION, DOESNT_SUPPORT, UNVERIFIABLE_STATUS, VERIFIED)

_FAILURE_STATUS = (
    ("existence", NOT_FOUND),
    ("identity", WRONG_CASE),
    ("quotation", QUOTE_NOT_IN_OPINION),
    ("proposition", DOESNT_SUPPORT),
)


def primary_status(outcomes: dict[str, str]) -> str | None:
    """The status for a citation's check outcomes, or None while it is incomplete."""
    for check, status in _FAILURE_STATUS:
        outcome = outcomes.get(check)
        if outcome is None:
            return None
        if outcome == FAIL:
            return status
    if any(outcomes[check] == UNVERIFIABLE for check, _ in _FAILURE_STATUS):
        return UNVERIFIABLE_STATUS
    return VERIFIED


def pincite_flag(outcomes: dict[str, str]) -> bool:
    return outcomes.get("pincite") == FAIL
