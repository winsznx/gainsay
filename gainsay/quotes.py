"""Quotation check: does each passage the filing quotes appear in the opinion?

Quotes are compared after normalizing case, quote marks, brackets, dashes and
whitespace, with fuzzy alignment to absorb OCR slips in the filing. Ellipses
split a quote into passages, and long passages are split into sentences, so a
failure names the part that is missing.
"""

import re
from dataclasses import dataclass

from rapidfuzz import fuzz

from gainsay.findings import FAIL, NOT_APPLICABLE, PASS, UNVERIFIABLE, Finding
from gainsay.opinions import OpinionText

QUOTE_SCORE = 90
SHORT_QUOTE_SCORE = 95
SHORT_QUOTE_CHARS = 40
MIN_SEGMENT_CHARS = 12
LONG_SEGMENT_CHARS = 300
EXCERPT_CHARS = 300

_DROPPED = set("\"'“”‘’`[]")
_DASHES = set("–—‐")


@dataclass(frozen=True)
class Match:
    passage: str
    score: float
    opinion_id: int | None
    page: int | None
    excerpt: str


def check_quotes(quotes: list[str], opinions: list[OpinionText], first_page: int | None) -> Finding:
    if not quotes:
        return Finding("quotation", NOT_APPLICABLE, "the filing quotes nothing for this citation")
    passages = [p for quote in quotes for p in split_passages(quote)]
    if not passages:
        return Finding("quotation", NOT_APPLICABLE, "quoted text is too short to check")
    if not opinions:
        return Finding("quotation", UNVERIFIABLE, "no opinion text to compare the quotation against")

    matches = [locate(passage, opinions, first_page) for passage in passages]
    missing = [m for m in matches if m.score < _threshold(m.passage)]
    evidence = {"passages": [m.__dict__ for m in matches]}
    if missing:
        worst = min(missing, key=lambda m: m.score)
        return Finding(
            "quotation",
            FAIL,
            f"{len(missing)} of {len(matches)} quoted passages not found in the opinion; "
            f"closest match to {_clip(worst.passage, 80)!r} scores {worst.score:.0f}",
            evidence,
        )
    pages = sorted({m.page for m in matches if m.page is not None})
    where = f" on page {', '.join(map(str, pages))}" if pages else ""
    return Finding("quotation", PASS, f"all {len(matches)} quoted passages found in the opinion{where}", evidence)


def split_passages(quote: str) -> list[str]:
    """Ellipses and bracketed rewrites of several words ("[the statements]")
    split a quote, since neither is the court's own text. A bracketed letter
    ("[T]hreadbare") stays, as it only changes case."""
    passages = []
    for part in re.split(r"\.\s?\.\s?\.|…|\[[^\]]*\s[^\]]*\]", quote):
        if len(part) > LONG_SEGMENT_CHARS:
            passages.extend(re.split(r"(?<=[.?!])\s+(?=[A-Z])", part))
        else:
            passages.append(part)
    return [p.strip() for p in passages if len(normalize(p)[0]) >= MIN_SEGMENT_CHARS]


def locate(passage: str, opinions: list[OpinionText], first_page: int | None) -> Match:
    needle, _ = normalize(passage)
    best = Match(passage, 0.0, None, None, "")
    for opinion in opinions:
        haystack, offsets = normalize(opinion.text)
        alignment = fuzz.partial_ratio_alignment(needle, haystack)
        if alignment is None or alignment.score <= best.score:
            continue
        start = offsets[alignment.dest_start]
        end = offsets[max(alignment.dest_end - 1, alignment.dest_start)] + 1
        best = Match(
            passage,
            round(alignment.score, 1),
            opinion.opinion_id,
            opinion.page_at(start, first_page),
            _clip(opinion.text[start:end], EXCERPT_CHARS),
        )
    return best


def normalize(text: str) -> tuple[str, list[int]]:
    """Lowercased text with quotes and brackets dropped, plus each char's source offset."""
    chars: list[str] = []
    offsets: list[int] = []
    for i, char in enumerate(text):
        if char in _DROPPED:
            continue
        if char.isspace():
            if not chars or chars[-1] == " ":
                continue
            char = " "
        elif char in _DASHES:
            char = "-"
        chars.append(char.lower())
        offsets.append(i)
    return "".join(chars).strip(), offsets


def _threshold(passage: str) -> int:
    return SHORT_QUOTE_SCORE if len(passage) < SHORT_QUOTE_CHARS else QUOTE_SCORE


def _clip(text: str, limit: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 3] + "..."
