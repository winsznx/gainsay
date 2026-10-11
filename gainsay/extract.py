"""Find the case citations in a filing and what each one is offered for.

Each citation occurrence gets the sentence it supports, any quotation the
filing attributes to it, and whether it sits inside text the filing quotes
from another source. Occurrences that point at the same case share one
authority, so existence is checked once per case.
"""

import re
from dataclasses import dataclass, field

from eyecite import get_citations, resolve_citations
from eyecite.models import (
    CitationBase,
    FullCaseCitation,
    IdCitation,
    ShortCaseCitation,
    SupraCitation,
)

from gainsay.pdf_text import ECF_HEADER

_MARGIN_NUMBER = re.compile(r"^\d{1,3}[.,]?$")
_OCR_FIXES = (
    (re.compile(r"\([Il]st\)"), "(1st)"),
    (re.compile(r"_"), ""),
)

_DOUBLE_QUOTES = "\"“”"
_SINGLE_OPENERS = "'‘"
_SINGLE_CLOSERS = "'’"
_SENTENCE_END = re.compile(r"[.?!][\"”’)\]]*\s+(?=[\"“(]?[A-Z])")
_ABBREVIATIONS = frozenset(
    "v vs co corp inc ltd no nos ct app cir dist supp super div mr mrs ms dr st jr sr "
    "u.s e.g i.e id fed civ ill n.y n.j cal tex ga la fla stat ann al cf sec ch pp art".split()
)
# A table of contents or authorities line ends in a dot leader to page numbers.
_TABLE_LEADER = re.compile(r"\.{8,}|…{3,}")
_TABLE_LOOKAHEAD = 100
# Subsequent history between a cite and a nameless cite of a later decision.
_HISTORY = re.compile(
    r"^[\s,]*(?:aff['’][dg]|rev['’][dg]|vacated|modified|remanded|cert\.\s+denied|"
    r"reh['’]g\s+denied|abrogated|overruled)[\w\s.,'’]*?,\s*$",
    re.IGNORECASE,
)
# Record citations (declarations, exhibits, transcripts, docket entries) that
# an Id. may refer back to instead of a case.
_RECORD_REFERENCE = re.compile(
    r"\b(?:Decl|Aff|Affirm|Ex|Exh|Tr|Dkt|ECF|Doc|Compl)\.?\s*(?:No\.\s*)?[¶\d]|¶"
)
# Cites whose pages are paragraphs or star pages: neutral and database cites.
_YEAR_FIRST_CITE = re.compile(r"^\d{4} ")
_SIGNALS = re.compile(r"\b(?:see|also|cf|e\.g|accord|but|compare|and|with)\b\.?,?", re.I)
_MIN_PROPOSITION_WORDS = 5


@dataclass
class Authority:
    ordinal: int
    case_name: str
    reporter_cites: list[str]
    year: str | None
    court: str | None


@dataclass
class Occurrence:
    ordinal: int
    kind: str
    authority: Authority | None
    cite_text: str
    pincite: str | None
    span: tuple[int, int]
    proposition: str
    in_quotation: bool
    quotes: list[str] = field(default_factory=list)


@dataclass
class Extraction:
    text: str
    authorities: list[Authority]
    citations: list[Occurrence]
    non_case_citations: int
    table_entries: int = 0
    record_references: int = 0


def clean_text(raw: str) -> str:
    """Drop ECF stamps and margin paragraph numbers, rejoin lines, fix known OCR slips."""
    lines = [line.strip() for line in raw.splitlines()]
    kept = [
        line
        for line in lines
        if line and not ECF_HEADER.match(line) and not _MARGIN_NUMBER.match(line)
    ]
    text = ""
    for line in kept:
        separator = "" if not text or text.endswith("-") else " "
        text += separator + line
    for pattern, replacement in _OCR_FIXES:
        text = pattern.sub(replacement, text)
    return re.sub(r"[ \t]+", " ", text)


def find_quotes(text: str) -> list[tuple[int, int]]:
    """Spans of double-quoted text, marks excluded.

    Double quotes don't nest in legal writing, so a quote mark inside an open
    quote only closes it when it hugs the preceding word. That keeps OCR'd
    inner quotes from splitting a block quotation.
    """
    spans = []
    start = None
    for i, char in enumerate(text):
        if char not in _DOUBLE_QUOTES:
            continue
        before = text[i - 1] if i else " "
        after = text[i + 1] if i + 1 < len(text) else " "
        if start is None:
            if (before.isspace() or before in "([") and not after.isspace():
                start = i + 1
        elif not before.isspace() and (after.isspace() or after in ".,;:)]"):
            spans.append((start, i))
            start = None
    return spans


def find_nested_quotes(
    text: str, outer: list[tuple[int, int]], citation_starts: list[int]
) -> list[tuple[int, int]]:
    """Single-quoted passages inside double-quoted ones, marks excluded.

    Legal writing marks a quotation within a quotation with single quotes. An
    apostrophe hugs a letter on both sides, so only a mark after a space or
    bracket opens. When OCR loses the closing mark, the passage ends at the
    last sentence end before the citation that follows it, since a quotation
    is followed by its source.
    """
    spans = []
    for qs, qe in outer:
        i = qs
        while i < qe - 1:
            before = text[i - 1] if i else " "
            if text[i] in _SINGLE_OPENERS and (before.isspace() or before in "([") and text[i + 1].isalpha():
                start = i + 1
                end = _nested_end(text, start, qe, citation_starts)
                if end is not None:
                    spans.append((start, end))
                    i = end
            i += 1
    return spans


def _nested_end(text: str, start: int, limit: int, citation_starts: list[int]) -> int | None:
    next_citation = min((c for c in citation_starts if start < c < limit), default=limit)
    for j in range(start, next_citation):
        after = text[j + 1] if j + 1 < len(text) else " "
        if text[j] in _SINGLE_CLOSERS and not text[j - 1].isspace() and not after.isalnum():
            return j
    sentence_ends = [m.end() for m in re.finditer(r"[.?!]", text[start:next_citation])]
    if next_citation == limit or not sentence_ends:
        return None
    return start + sentence_ends[-1]


def sentence_spans(text: str, protected: list[tuple[int, int]]) -> list[tuple[int, int]]:
    starts = [0]
    for match in _SENTENCE_END.finditer(text):
        period = match.start()
        if _inside(period, protected) or _is_abbreviation(text, period):
            continue
        starts.append(match.end())
    return list(zip(starts, starts[1:] + [len(text)]))


def extract(raw_text: str) -> Extraction:
    text = clean_text(raw_text)
    found = get_citations(text)
    case_citations = [
        c
        for c in found
        if isinstance(c, (FullCaseCitation, ShortCaseCitation, IdCitation, SupraCitation))
    ]
    groups = _group_parallels(text, case_citations)
    spans = [_group_span(text, group) for group in groups]
    protected = spans + [_full_span(c) for c in found if c not in case_citations]

    # Tables of contents and authorities repeat the brief's citations with page
    # numbers and no proposition, so only the citations in the body are checked.
    body = [(g, s) for g, s in zip(groups, spans) if not _TABLE_LEADER.search(text[s[1] : s[1] + _TABLE_LOOKAHEAD])]
    table_entries = len(groups) - len(body)
    groups, spans = [g for g, _ in body], [s for _, s in body]

    sentences = sentence_spans(text, protected)
    quotes = find_quotes(text)
    antecedents = _antecedents(found)

    authorities: list[Authority] = []
    occurrences: list[Occurrence] = []
    record_references = 0
    for group, span in zip(groups, spans):
        lead = group[0]
        previous = occurrences[-1] if occurrences else None
        if isinstance(lead, IdCitation):
            if previous is None or _refers_to_record(text, previous, span, _pincite(lead)):
                record_references += 1
                continue
            authority = previous.authority
        elif previous and previous.authority and _is_history(text, previous.span[1], lead):
            authority = _authority_for(text, group, antecedents, authorities, previous.authority.case_name)
        else:
            authority = _authority_for(text, group, antecedents, authorities)
        occurrences.append(
            Occurrence(
                ordinal=len(occurrences) + 1,
                kind=_kind(lead),
                authority=authority,
                cite_text=text[span[0] : span[1]],
                pincite=_pincite(lead),
                span=span,
                proposition=_proposition(text, sentences, protected, span),
                in_quotation=any(qs <= span[0] < qe for qs, qe in quotes),
            )
        )

    nested = find_nested_quotes(text, quotes, [o.span[0] for o in occurrences])
    _attribute_quotes(text, quotes + nested, sentences, occurrences)
    return Extraction(
        text=text,
        authorities=authorities,
        citations=occurrences,
        non_case_citations=len(found) - len(case_citations),
        table_entries=table_entries,
        record_references=record_references,
    )


def _group_parallels(text: str, citations: list[CitationBase]) -> list[list[CitationBase]]:
    """Parallel reporters for one case become one occurrence.

    A full cite is a parallel when only a comma or period separates it from the
    previous cite and its pincite: "391 U.S. 593, 598, 88 S. Ct. 1753" and
    "Id. at 166, 119 S. Ct. 662". OCR often turns those commas into periods.
    """
    groups: list[list[CitationBase]] = []
    for citation in citations:
        if groups and isinstance(citation, FullCaseCitation):
            gap = text[_cite_end(groups[-1][-1]) : citation.span()[0]]
            if re.fullmatch(r"[,.]\s*", gap):
                groups[-1].append(citation)
                continue
        groups.append([citation])
    return groups


def _cite_end(citation: CitationBase) -> int:
    pin_end = getattr(citation.metadata, "pin_cite_span_end", None)
    return max(citation.span()[1], pin_end or 0)


def _group_span(text: str, group: list[CitationBase]) -> tuple[int, int]:
    lead = group[0]
    start = _name_start(text, lead)
    end = max(_full_span(lead)[1], _cite_end(group[-1]))
    return start, end


def _name_start(text: str, citation: CitationBase) -> int:
    """Skip lead-ins eyecite folds into the case name ("In the case of", "of").

    eyecite leaves "In re" out of the name, so it is pulled back in.
    """
    start = _full_span(citation)[0]
    if text[:start].endswith("In re "):
        return start - len("In re ")
    lead_in = re.match(r"(?:(?:[Ii]n|of|the|case)\s+)+(?!re\b)", text[start : citation.span()[0]])
    return start + lead_in.end() if lead_in else start


def _antecedents(citations: list[CitationBase]) -> dict[int, FullCaseCitation]:
    """Map each short, Id. and supra cite to the full cite eyecite resolved it to."""
    resolved = resolve_citations(citations)
    return {
        id(citation): resource.citation
        for resource, members in resolved.items()
        for citation in members
        if isinstance(getattr(resource, "citation", None), FullCaseCitation)
    }


def _authority_for(
    text: str,
    group: list[CitationBase],
    antecedents: dict[int, FullCaseCitation],
    authorities: list[Authority],
    case_name: str | None = None,
) -> Authority | None:
    lead = group[0]
    full = [c for c in group if isinstance(c, FullCaseCitation)]
    if not isinstance(lead, FullCaseCitation):
        antecedent = antecedents.get(id(lead))
        if antecedent is None:
            return None
        full = [antecedent, *full]

    cites = [c.corrected_citation() for c in full]
    for authority in authorities:
        if set(cites) & set(authority.reporter_cites):
            authority.reporter_cites.extend(c for c in cites if c not in authority.reporter_cites)
            return authority

    named = full[0]
    authority = Authority(
        ordinal=len(authorities) + 1,
        case_name=case_name or _case_name(text, named),
        reporter_cites=cites,
        year=named.metadata.year,
        court=named.metadata.court,
    )
    authorities.append(authority)
    return authority


def _case_name(text: str, citation: FullCaseCitation) -> str:
    start = _name_start(text, citation)
    name = text[start : citation.span()[0]].strip().rstrip(",").strip()
    name = re.sub(r"\.{2,}", ".", name)
    name = re.sub(r",\s*Nos?\.\s.*$", "", name)
    if name:
        return name
    plaintiff, defendant = citation.metadata.plaintiff, citation.metadata.defendant
    return " v. ".join(part for part in (plaintiff, defendant) if part)


def _refers_to_record(text: str, previous: "Occurrence", span: tuple[int, int], pincite: str | None) -> bool:
    """An Id. points at the record, not the last case, when a record cite comes
    between them, or when it pins a paragraph of a case reported by page."""
    if _RECORD_REFERENCE.search(text[previous.span[1] : span[0]]):
        return True
    paged = previous.authority and not any(_YEAR_FIRST_CITE.match(c) for c in previous.authority.reporter_cites)
    return bool(pincite and "¶" in pincite and paged)


def _is_history(text: str, previous_end: int, citation: CitationBase) -> bool:
    """A nameless full cite after "aff'd," and the like reports a later decision in the same case.

    eyecite sometimes folds the history into the earlier cite's span, which
    leaves the later cite inside it.
    """
    if not isinstance(citation, FullCaseCitation):
        return False
    if citation.metadata.plaintiff or citation.metadata.defendant:
        return False
    start = citation.span()[0]
    return start < previous_end or bool(_HISTORY.match(text[previous_end:start]))


def _kind(citation: CitationBase) -> str:
    if isinstance(citation, IdCitation):
        return "id"
    if isinstance(citation, SupraCitation):
        return "supra"
    if isinstance(citation, ShortCaseCitation):
        return "short"
    return "full"


def _pincite(citation: CitationBase) -> str | None:
    pin = getattr(citation.metadata, "pin_cite", None)
    if not pin:
        return None
    return re.sub(r"^at\s+", "", pin).strip(" ,") or None


def _proposition(
    text: str,
    sentences: list[tuple[int, int]],
    citation_spans: list[tuple[int, int]],
    span: tuple[int, int],
) -> str:
    """The sentence a citation supports.

    A bare citation sentence ("See Kaiser Steel ..., 391 U.S. 593 (1968).")
    supports the sentence before it, so that one is returned instead.
    """
    index = next(i for i, (s, e) in enumerate(sentences) if s <= span[0] < e)
    start, end = sentences[index]
    if index > 0 and _word_count(text, start, end, citation_spans) < _MIN_PROPOSITION_WORDS:
        start, end = sentences[index - 1]
    return text[start:end].strip()


def _word_count(text: str, start: int, end: int, citation_spans: list[tuple[int, int]]) -> int:
    pieces = []
    cursor = start
    for s, e in sorted(citation_spans):
        if e <= start or s >= end:
            continue
        pieces.append(text[cursor:max(cursor, s)])
        cursor = max(cursor, e)
    pieces.append(text[cursor:end])
    remainder = _SIGNALS.sub(" ", " ".join(pieces))
    return len(re.findall(r"[A-Za-z]{2,}", remainder))


def _attribute_quotes(
    text: str,
    quotes: list[tuple[int, int]],
    sentences: list[tuple[int, int]],
    occurrences: list[Occurrence],
) -> None:
    """Give each quotation to the citation that introduces it or follows it.

    Introduced: the last citation before the opening mark in the same sentence
    ("Varghese, 925 F.3d 1339 (11th Cir. 2019), stating “..."). Trailing: a
    citation starting right after the closing mark ("...." Smith, 1 U.S. 1).
    """
    for qs, qe in quotes:
        outside = [o for o in occurrences if not qs <= o.span[0] < qe]
        sentence_start = next(s for s, e in sentences if s <= qs - 1 < e)
        introducing = [o for o in outside if sentence_start <= o.span[0] and o.span[1] < qs]
        trailing = [o for o in outside if 0 < o.span[0] - qe <= 6]
        owner = introducing[-1] if introducing else (trailing[0] if trailing else None)
        if owner is not None:
            owner.quotes.append(text[qs:qe])


def _full_span(citation: CitationBase) -> tuple[int, int]:
    return citation.full_span()


def _inside(position: int, spans: list[tuple[int, int]]) -> bool:
    return any(s <= position < e for s, e in spans)


def _is_abbreviation(text: str, period: int) -> bool:
    token = re.search(r"([A-Za-z.]+)$", text[:period])
    if not token:
        return False
    word = token.group(1).strip(".").lower()
    return word in _ABBREVIATIONS or len(word.replace(".", "")) == 1
