"""Documents the agent must never fetch.

The Mata v. Avianca sanctions opinion (ECF 54) and the Gauthier v. Goodyear
sanctions order (ECF 48) name every bad citation in their cases. Scored runs
use them as answer keys, so letting the agent read them would leak the
answers into the run. In Gauthier the show-cause order (ECF 44) and
Goodyear's reply (ECF 42), which first named the bad cites, are blocked too.
"""

import re

BLOCKLISTED_ENTRIES = frozenset(
    {
        ("nysd", "22-cv-1461", 54),
        ("txed", "23-cv-281", 42),
        ("txed", "23-cv-281", 44),
        ("txed", "23-cv-281", 48),
    }
)

_DOCKET_NUMBER = re.compile(r"^(?:\d+:)?(\d{2})-?([a-z]+)-?0*(\d+)$")


class BlocklistedDocument(Exception):
    pass


def normalize_docket_number(docket_number: str) -> str:
    """Reduce "1:22-cv-01461", "22-cv-1461" and "22cv1461" to one key."""
    compact = re.sub(r"\s+", "", docket_number.lower())
    match = _DOCKET_NUMBER.match(compact)
    if not match:
        raise ValueError(f"unrecognized docket number: {docket_number!r}")
    year, case_type, number = match.groups()
    return f"{year}-{case_type}-{int(number)}"


def assert_not_blocklisted(court: str, docket_number: str, entry_number: int) -> None:
    key = (court.lower(), normalize_docket_number(docket_number), entry_number)
    if key in BLOCKLISTED_ENTRIES:
        raise BlocklistedDocument(
            f"refusing to fetch {court} {docket_number} ECF {entry_number}: "
            "it is the scoring answer key and is blocklisted from the agent"
        )
