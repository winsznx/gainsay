"""Documents the agent must never fetch.

The Mata v. Avianca sanctions opinion (ECF 54) names every bad citation in
the case. Scored runs use it as the answer key, so letting the agent read it
would leak the answers into the run.
"""

import re

BLOCKLISTED_ENTRIES = frozenset(
    {
        ("nysd", "22-cv-1461", 54),
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
