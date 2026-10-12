"""Decide whether two case names refer to the same parties.

Whole-name fuzzy scores are fooled by shared boilerplate: "Doe v. United
States" and "Smith v. United States" score high. So each name is split into
parties, generic words are dropped, and every cited party must be found in
the other name: its first distinctive word, which carries the identity
("Korean" Air Lines, not "Delta" Air Lines), plus most of the rest ("Iran Air"
is not "Islamic Republic of Iran"). A one-party name ("In re Air Crash
Disaster Near New Orleans") has no second party to pin it down, so it needs a
higher share. Token comparison is fuzzy to absorb OCR slips, adjacent words
are also joined so "Airlines" finds "Air Lines", and Bluebook abbreviations
("Techs.", "Telecomms.", "Int'l") match the words they shorten.
"""

import re

from rapidfuzz import fuzz

_GENERIC = frozenset(
    "v vs in re the of and a an et al ex rel matter estate inc co corp corporation company "
    "ltd llc llp lp plc sa na united states america usa us people state commonwealth ii iii iv".split()
)
_PARTY_SEPARATOR = re.compile(r"\s+v(?:s)?\.?\s+", re.I)
_TOKEN_SIMILARITY = 85
_MIN_ABBREVIATION = 4
# Bluebook contractions that aren't prefixes of the word they stand for.
_CONTRACTIONS = {
    "intl": "international", "natl": "national", "assn": "association", "dept": "department",
    "govt": "government", "commn": "commission", "mgmt": "management", "grp": "group",
    "bhd": "brotherhood", "secy": "secretary", "atty": "attorney", "hosp": "hospital",
    "commr": "commissioner", "tel": "telephone", "sys": "systems", "pub": "public", "util": "utility",
    "fin": "financial", "ins": "insurance", "mfg": "manufacturing", "prods": "products", "servs": "services",
    "sch": "school", "univ": "university", "ctr": "center", "dist": "district", "envtl": "environmental",
    "hous": "housing", "dev": "development", "econ": "economic", "wis": "wisconsin", "med": "medical",
    "atl": "atlantic", "pac": "pacific", "am": "american", "gen": "general", "mut": "mutual",
    "cent": "central", "cty": "county", "elec": "electric", "inv": "investment", "invs": "investments",
    "mkt": "market", "pharm": "pharmaceutical", "bldg": "building", "assur": "assurance", "ent": "entertainment",
    "indem": "indemnity", "transp": "transportation", "tech": "technology", "techs": "technologies",
    "telecomm": "telecommunication", "telecomms": "telecommunications", "corr": "correctional",
    "fed": "federal", "sav": "savings", "ry": "railroad", "rwy": "railroad", "railway": "railroad",
    "r.r": "railroad", "rr": "railroad", "res": "resources", "def": "defense", "socy": "society",
    "soc": "society", "chas": "charles", "bd": "board", "bds": "boards", "cmty": "community",
    "dir": "director", "div": "division", "gov": "government", "hwy": "highway", "lab": "labor",
    "mun": "municipal", "org": "organization", "twp": "township", "fid": "fidelity", "guar": "guaranty",
    "cas": "casualty", "mem": "memorial", "ret": "retirement", "bros": "brothers",
    "cal": "california", "tex": "texas", "fla": "florida", "pa": "pennsylvania", "ga": "georgia",
    "la": "louisiana", "md": "maryland", "va": "virginia", "mo": "missouri", "ky": "kentucky",
    "ala": "alabama", "ark": "arkansas", "kan": "kansas", "del": "delaware", "haw": "hawaii",
    "ind": "indiana", "nev": "nevada", "neb": "nebraska", "wyo": "wyoming", "vt": "vermont",
    "ill": "illinois", "contl": "continental", "nw": "northwest", "ne": "northeast", "se": "southeast",
    "sw": "southwest", "profl": "professional", "regl": "regional", "fedn": "federation", "empt": "employment",
    "admr": "administrator", "exr": "executor", "assocs": "associates", "enters": "enterprises",
    "mktg": "marketing", "pship": "partnership", "rels": "relations", "sci": "science", "sols": "solutions",
    "commcns": "communications", "cnty": "county",
}
# "R. Co." and "R.R." stand for railroad; the single letter would otherwise be dropped.
_RAILROAD = re.compile(r"\br\.\s*(?:r\.|co\b)")
_MAX_ACRONYM = 4
_PARTY_COVERAGE = 0.6
_SINGLE_PARTY_COVERAGE = 2 / 3


def parties(name: str) -> list[list[str]]:
    return [_distinctive(part) for part in _PARTY_SEPARATOR.split(name)]


def names_match(cited: str, found: str) -> bool:
    cited_parties = [p for p in parties(cited) if p]
    found_parties = parties(found)
    found_tokens = [
        token
        for party in found_parties
        for token in party + [a + b for a, b in zip(party, party[1:])]
    ]
    if not cited_parties or not found_tokens:
        return fuzz.token_sort_ratio(cited.lower(), found.lower()) >= 90
    # "GE" for "General Electric", "DOL" for "Department of Labor": initials of
    # consecutive words in a found party, with and without its small words.
    spelled = [
        [_CONTRACTIONS.get(w, w) for w in re.sub(r"[^a-z]+", " ", re.sub(r"['’]", "", part.lower())).split()]
        for part in _PARTY_SEPARATOR.split(found)
    ]
    found_tokens += [
        "".join(w[0] for w in words[i : i + n])
        for words in [*found_parties, *spelled]
        for n in range(2, _MAX_ACRONYM + 1)
        for i in range(len(words) - n + 1)
    ]
    coverage = _SINGLE_PARTY_COVERAGE if len(cited_parties) == 1 else _PARTY_COVERAGE
    found_initials = {_initials(part) for part in _PARTY_SEPARATOR.split(found)}
    return all(
        _party_found(party, found_tokens, coverage) or (len(party) == 1 and party[0] in found_initials)
        for party in cited_parties
    )


def _initials(party: str) -> str:
    """"usda" for "United States Department of Agriculture", for acronyms like USDA or SEC."""
    words = [w for w in re.findall(r"[A-Za-z]+", party) if w.lower() not in ("of", "the", "and", "for")]
    return "".join(w[0] for w in words).lower()


def _party_found(party: list[str], found_tokens: list[str], coverage: float) -> bool:
    if not _found(party[0], found_tokens):
        return False
    covered = sum(_found(token, found_tokens) for token in party)
    return covered / len(party) >= coverage


def _found(token: str, tokens: list[str]) -> bool:
    return any(_same_word(token, other) for other in tokens)


def _same_word(a: str, b: str) -> bool:
    if fuzz.ratio(a, b) >= _TOKEN_SIMILARITY:
        return True
    short, long = sorted((a, b), key=len)
    stem = short[:-1] if short.endswith("s") and len(short) > _MIN_ABBREVIATION else short
    return len(stem) >= _MIN_ABBREVIATION and long.startswith(stem)


def _distinctive(text: str) -> list[str]:
    text = _RAILROAD.sub("railroad ", text.lower())
    words = re.sub(r"[^a-z0-9]+", " ", re.sub(r"['’]", "", text)).split()
    words = [_CONTRACTIONS.get(w, w) for w in words]
    return [w for w in words if len(w) > 1 and w not in _GENERIC]
