"""Decide whether two case names refer to the same parties.

Whole-name fuzzy scores are fooled by shared boilerplate: "Doe v. United
States" and "Smith v. United States" score high. So each name is split into
parties, generic words are dropped, and every cited party must be found in
the other name: its first distinctive word, which carries the identity
("Korean" Air Lines, not "Delta" Air Lines), plus most of the rest ("Iran Air"
is not "Islamic Republic of Iran"). A one-party name ("In re Air Crash
Disaster Near New Orleans") has no second party to pin it down, so it needs a
higher share. Token comparison is fuzzy to absorb OCR slips, and adjacent
words are also joined so "Airlines" finds "Air Lines".
"""

import re

from rapidfuzz import fuzz

_GENERIC = frozenset(
    "v vs in re the of and a an et al ex rel matter estate inc co corp corporation company "
    "ltd llc llp lp plc sa na united states america usa us people state commonwealth".split()
)
_PARTY_SEPARATOR = re.compile(r"\s+v(?:s)?\.?\s+", re.I)
_TOKEN_SIMILARITY = 85
_PARTY_COVERAGE = 0.6
_SINGLE_PARTY_COVERAGE = 2 / 3


def parties(name: str) -> list[list[str]]:
    return [_distinctive(part) for part in _PARTY_SEPARATOR.split(name)]


def names_match(cited: str, found: str) -> bool:
    cited_parties = [p for p in parties(cited) if p]
    found_tokens = [
        token
        for party in parties(found)
        for token in party + [a + b for a, b in zip(party, party[1:])]
    ]
    if not cited_parties or not found_tokens:
        return fuzz.token_sort_ratio(cited.lower(), found.lower()) >= 90
    coverage = _SINGLE_PARTY_COVERAGE if len(cited_parties) == 1 else _PARTY_COVERAGE
    return all(_party_found(party, found_tokens, coverage) for party in cited_parties)


def _party_found(party: list[str], found_tokens: list[str], coverage: float) -> bool:
    if not _found(party[0], found_tokens):
        return False
    covered = sum(_found(token, found_tokens) for token in party)
    return covered / len(party) >= coverage


def _found(token: str, tokens: list[str]) -> bool:
    return any(fuzz.ratio(token, other) >= _TOKEN_SIMILARITY for other in tokens)


def _distinctive(text: str) -> list[str]:
    words = re.sub(r"[^a-z0-9]+", " ", text.lower()).split()
    return [w for w in words if len(w) > 1 and w not in _GENERIC]
