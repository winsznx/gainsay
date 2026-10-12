"""Pincite check: are the cited pages inside the opinion, and where the quote is?

The opinion's pages come from its star pagination. A pincite fails when it
falls before the first page or after the last page break of the cited
reporter, when the passages the citation quotes were found only on other
pages, or when the judge found the statement made only off the pinned pages.
Star-paged database cites (WL, LEXIS) and paragraph pins have no
page breaks to check against, so they are unverifiable.
"""

import re

from eyecite import get_citations
from eyecite.models import FullCaseCitation, ShortCaseCitation

from gainsay.findings import FAIL, NOT_APPLICABLE, PASS, UNVERIFIABLE, Finding
from gainsay.opinions import OpinionText
_DATABASE_REPORTERS = re.compile(r"\b(?:WL|LEXIS)\b")


def parse_pin(pincite: str) -> tuple[int, int] | None:
    """"371-72" becomes (371, 372); "1254" becomes (1254, 1254)."""
    match = re.match(r"^(\d+)(?:\s*[-–]\s*(\d+))?", pincite.strip())
    if not match:
        return None
    start = int(match.group(1))
    end_digits = match.group(2)
    if not end_digits:
        return start, start
    if len(end_digits) < len(match.group(1)):
        end_digits = match.group(1)[: -len(end_digits)] + end_digits
    return start, int(end_digits)


def first_page(reporter_cite: str) -> int | None:
    page = reporter_cite.rsplit(" ", 1)[-1]
    return int(page) if page.isdigit() else None


def pin_reporter(
    kind: str, cite_text: str, authority_cites: list[str], previous: str | None
) -> str | None:
    """The reporter cite a pincite counts pages in.

    A full cite's pin follows its first reporter. Id. inherits the cite before
    it, even when a parallel follows ("Id. at 166, 119 S. Ct. 662" counts in
    U.S.). A short cite ("525 U.S., at 161") names its volume and reporter,
    which pick the matching full cite.
    """
    if kind == "id":
        return previous
    parsed = [c for c in get_citations(cite_text) if isinstance(c, (FullCaseCitation, ShortCaseCitation))]
    if not parsed:
        return previous
    lead = parsed[0]
    if isinstance(lead, FullCaseCitation):
        return lead.corrected_citation()
    prefix = f"{lead.groups.get('volume')} {lead.corrected_reporter()} "
    return next((c for c in authority_cites if c.startswith(prefix)), None)


def check_pincite(
    pincite: str | None,
    reporter_cite: str | None,
    opinions: list[OpinionText],
    quote_pages: list[int] | None = None,
    point_pages: list[int] | None = None,
) -> Finding:
    if not pincite:
        return Finding("pincite", NOT_APPLICABLE, "no pincite given")
    if not reporter_cite:
        return Finding("pincite", UNVERIFIABLE, f"could not tell which reporter pincite {pincite} refers to")
    if _DATABASE_REPORTERS.search(reporter_cite):
        return Finding("pincite", UNVERIFIABLE, f"{reporter_cite} is a database cite with no page breaks to check")
    pin = parse_pin(pincite)
    first = first_page(reporter_cite)
    if pin is None or first is None:
        return Finding("pincite", UNVERIFIABLE, f"pincite {pincite!r} is not a page number")

    start, end = pin
    pages = sorted({p for op in opinions for _, p in op.pages_in(first)})
    evidence = {"reporter_cite": reporter_cite, "pin": [start, end], "first_page": first, "page_breaks": pages}
    if start < first:
        return Finding("pincite", FAIL, f"page {start} is before {reporter_cite} begins", evidence)
    if not pages:
        if end == first:
            return Finding("pincite", PASS, f"page {first} is the first page of {reporter_cite}", evidence)
        return Finding(
            "pincite", UNVERIFIABLE, f"CourtListener has no page breaks for {reporter_cite}", evidence
        )
    last = pages[-1]
    if end > last:
        return Finding(
            "pincite",
            FAIL,
            f"{reporter_cite} runs from page {first} to {last}; pincite {pincite} is past the end",
            evidence,
        )
    if quote_pages and not any(start - 1 <= page <= end for page in quote_pages):
        # A quote can begin at the foot of the page before the one cited, so that page counts too.
        found = ", ".join(str(p) for p in sorted(set(quote_pages)))
        return Finding(
            "pincite",
            FAIL,
            f"the quoted words are on page {found} of {reporter_cite}, not page {pincite}",
            {**evidence, "quote_pages": sorted(set(quote_pages))},
        )
    if point_pages and not quote_pages and not any(start <= page <= end for page in point_pages):
        found = ", ".join(str(p) for p in sorted(set(point_pages)))
        return Finding(
            "pincite",
            FAIL,
            f"the opinion makes the point on page {found} of {reporter_cite}, not page {pincite}",
            {**evidence, "point_pages": sorted(set(point_pages))},
        )
    return Finding("pincite", PASS, f"pincite {pincite} is within pages {first}-{last} of {reporter_cite}", evidence)
