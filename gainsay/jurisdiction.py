"""Whether a court could have published a case in the cited reporter.

A name search can turn up a namesake from the wrong court system: the 2d
Circuit's Ehrlich v. American Airlines is not a case reported in N.J. Super.
reporters_db says whether a reporter is federal or state, and courts_db says
the same of each CourtListener court id.
"""

from functools import cache

from courts_db import courts
from eyecite import get_citations
from eyecite.models import FullCaseCitation

_SYSTEM_BY_CITE_TYPE = {
    "federal": "federal",
    "scotus_early": "federal",
    "state": "state",
    "state_regional": "state",
    "neutral": "state",
}
_COURT_SYSTEM = {court["id"]: court["system"] for court in courts}


def court_system_fits(reporter_cites: list[str], court_id: str | None) -> bool:
    """False only when every cite's reporter is from the other court system."""
    court_system = _COURT_SYSTEM.get(court_id or "")
    systems = {s for s in map(_reporter_system, reporter_cites) if s}
    if court_system is None or not systems:
        return True
    return court_system in systems


@cache
def _reporter_system(cite: str) -> str | None:
    parsed = [c for c in get_citations(cite) if isinstance(c, FullCaseCitation)]
    if not parsed or parsed[0].edition_guess is None:
        return None
    return _SYSTEM_BY_CITE_TYPE.get(parsed[0].edition_guess.reporter.cite_type)
