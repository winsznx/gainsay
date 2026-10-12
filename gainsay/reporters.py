"""Reporter series that don't exist.

A cite to "475 F.6th 972" fails before any lookup: the Federal Reporter's
newest series is F.4th. eyecite doesn't recognise such cites at all, so
neither does CourtListener's lookup, which runs eyecite too. reporters_db is
the authority on which series exist. Only a series past the newest known one
of a recognised reporter counts, so an OCR-garbled abbreviation never does.
"""

import re
from functools import cache

from reporters_db import REPORTERS

_SERIES = re.compile(r"^(?P<base>.+?)\s?(?P<number>\d+)(?:d|th|st|nd|rd)$")

# A volume, a reporter ending in a series ordinal, and a page: "475 F.6th 972".
CITE_WITH_SERIES = re.compile(
    r"\b(?P<volume>\d{1,4})\s+(?P<reporter>(?:[A-Z][A-Za-z.']*\s?){1,4}?\d+(?:d|th|st|nd|rd))\s+(?P<page>\d{1,5})\b"
)


def invented_series(reporter: str) -> str | None:
    """Why this reporter series can't exist, or None if it might."""
    match = _SERIES.match(reporter.strip())
    if not match:
        return None
    base = match.group("base").strip()
    newest = _newest_series().get(_squash(base))
    if newest is None or reporter.strip() in _known():
        return None
    number, name = newest
    if int(match.group("number")) <= number:
        return None
    return f"there is no {reporter.strip()}: the newest series of that reporter is {name}"


@cache
def _known() -> frozenset[str]:
    names = set()
    for key, entries in REPORTERS.items():
        names.add(key)
        for entry in entries:
            names.update(entry.get("editions", {}))
            names.update(entry.get("variations", {}))
    return frozenset(names)


@cache
def _editions() -> frozenset[str]:
    return frozenset(
        edition for entries in REPORTERS.values() for entry in entries for edition in entry.get("editions", {})
    )


@cache
def _newest_series() -> dict[str, tuple[int, str]]:
    """Base reporter (spaces removed) to its highest known series number and canonical name."""
    newest: dict[str, tuple[int, str]] = {}
    for edition in _editions():
        match = _SERIES.match(edition)
        base, number = (match.group("base"), int(match.group("number"))) if match else (edition, 1)
        key = _squash(base)
        if number > newest.get(key, (0, ""))[0]:
            newest[key] = (number, edition)
    return newest


def _squash(text: str) -> str:
    return re.sub(r"\s+", "", text)
