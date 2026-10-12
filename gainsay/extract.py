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
from gainsay.reporters import CITE_WITH_SERIES, invented_series

_MARGIN_NUMBER = re.compile(r"^\d{1,3}[.,]?$")
_OCR_FIXES = (
    (re.compile(r"\([Il]st\)"), "(1st)"),
    (re.compile(r"_"), ""),
    # Asterisks marking italics ("*Reed v. Union*"). A star page ("at *3") keeps its asterisk.
    (re.compile(r"(?<![\w*])\*(?=[A-Za-z])|(?<=[A-Za-z.’'])\*(?![\w*])"), ""),
)

_DOUBLE_QUOTES = "\"“”"
_SINGLE_OPENERS = "'‘"
_SINGLE_CLOSERS = "'’"
# A footnote number can sit right after the period: "(1985).2 Pursuant".
_SENTENCE_END = re.compile(r"[.?!][\"”’)\]]*(?:\d{1,2}(?=\s))?\s+(?=[\"“(]?[A-Z])")
_ABBREVIATIONS = frozenset(
    "v vs co corp inc ltd no nos ct app cir dist supp super div mr mrs ms dr st jr sr "
    "u.s e.g i.e id fed civ ill n.y n.j cal tex ga la fla stat ann al cf sec ch pp art ex exh decl aff".split()
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
# A district court docket number as cited: "No. 13-CV-7812 PKC", "No. 13 CIV. 4861 ER".
_DOCKET_NUMBER = re.compile(r",\s*Nos?\.\s*(\d{2})[\s-]*(cv|civ|cr)\.?[\s-]*(\d+)", re.IGNORECASE)
_SIGNALS = re.compile(r"\b(?:see|also|cf|e\.g|accord|but|compare|and|with)\b\.?,?", re.I)
_ENUMERATED_HEADING = re.compile(r"^(?:[IVXL]+|[A-Z])\.\s+")
_HEADING_ENDERS = frozenset(".?!:;,")
_SENTENCE_CLOSE = re.compile(r"[.?!:][\"”’)\]]*$")
_TITLE_CASE_SHARE = 0.6
# "Ex. A." ends a sentence on the exhibit's letter.
_EXHIBIT_LABEL = re.compile(r"\b(?:Ex|Exh|Exhibit)s?\.?\s+[A-Z]$")
_MIN_PROPOSITION_WORDS = 5
_COURT_YEAR_ONLY = re.compile(r"^\([^()]*\b\d{4}\)\s*$")
# A citation signal inside a name walked back over a sentence end ("Evolutionary. See Content ...").
_SIGNAL_LEAD = re.compile(r"\b(?:See|see|Cf\.|cf\.|Accord|accord|Compare|compare)(?:,?\s+(?:also|e\.g\.,?|generally))?,?\s+")
_SIGNAL_BEFORE = re.compile(
    r"(?:^|[\s(;.,])((?:[Ss]ee|[Cc]f\.|[Aa]ccord|[Cc]ompare|[Bb]ut\s+(?:see|cf\.))"
    r"(?:,?\s+(?:also|generally|e\.g\.))?|[Ee]\.g\.)\s*,?\s*$"
)
_PIN_AFTER = re.compile(r"[\s,]*(?:(?:at\s+)?\*?\d[\d\s,\-–n.&*]*)?\s*")
_COURT_YEAR_CONTENT = re.compile(r"^[^()]*\b\d{4}$")
_BOILERPLATE = re.compile(
    r"^(?:(?:internal\s+)?(?:citations?|quotations?|quotation\s+marks|alterations?|footnotes?|emphasis)"
    r"(?:\s+and\s+\w+(?:\s+marks)?)?\s+(?:omitted|added|in\s+original|supplied)|quoting\b|citing\b|"
    r"per\s+curiam|en\s+banc|unpublished|table|mem\.?|plurality|same|alteration|emphasis|"
    r"(?:\w+\s+)?(?:dissenting|concurring)|[\w.'’-]+,\s+(?:C\.\s*)?J{1,2}\.)",
    re.IGNORECASE,
)
# Text eyecite folds into the front of a name: the end of a parenthetical, or an Id. cite.
_NAME_JUNK = re.compile(r"^(?:.*\)\.\s+|(?:Id|Ibid)\.(?:\s+at\s+[\d,\s\-–]+)?\.?\s+)")


@dataclass
class Authority:
    ordinal: int
    case_name: str
    reporter_cites: list[str]
    year: str | None
    court: str | None
    docket_number: str | None = None
    invented_reporter: str | None = None


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
    signal: str | None = None
    parenthetical: str | None = None


@dataclass
class Extraction:
    text: str
    authorities: list[Authority]
    citations: list[Occurrence]
    non_case_citations: int
    table_entries: int = 0
    record_references: int = 0


def clean_text(raw: str) -> str:
    """Drop ECF stamps and margin paragraph numbers, rejoin lines, fix known OCR slips.

    Headings carry no closing period, so a line break stays wherever a heading
    starts or ends and sentence_spans splits there.
    """
    lines = [line.strip() for line in raw.splitlines()]
    kept = [
        line
        for line in lines
        if line and not ECF_HEADER.match(line) and not _MARGIN_NUMBER.match(line)
    ]
    text = ""
    previous_heading = False
    for line in kept:
        heading = _is_heading(line, text)
        if not text:
            separator = ""
        elif heading != previous_heading:
            separator = "\n"
        else:
            separator = "" if text.endswith("-") else " "
        text += separator + line
        previous_heading = heading
    for pattern, replacement in _OCR_FIXES:
        text = pattern.sub(replacement, text)
    return re.sub(r"[ \t]+", " ", text)


def _is_heading(line: str, text_before: str) -> bool:
    """An all-caps line, or an enumerated title-case line that starts after a sentence ends.

    "II. SANCTIONS ARE NOT WARRANTED" and "A. Mr. Schwartz's Misunderstanding of
    ChatGPT Does Not Show Bad Faith" are headings; "A. Smith and others who
    found nothing amiss" wrapped from the line before is not.
    """
    if line[-1] in _HEADING_ENDERS:
        return False
    words = re.findall(r"[A-Za-z][A-Za-z’'.-]*", line)
    if sum(len(w) > 2 for w in words) >= 1 and len(words) >= 2 and line == line.upper():
        return True
    enumerated = _ENUMERATED_HEADING.match(line)
    if not enumerated or (text_before and not _SENTENCE_CLOSE.search(text_before)):
        return False
    title_words = re.findall(r"[A-Za-z][\w’']*", line[enumerated.end():])
    capitalized = sum(w[0].isupper() for w in title_words)
    return len(title_words) >= 2 and capitalized >= _TITLE_CASE_SHARE * len(title_words)


def find_quotes(text: str) -> list[tuple[int, int]]:
    """Spans of double-quoted text, marks excluded.

    Double quotes don't nest in legal writing, so a quote mark inside an open
    quote only closes it when it hugs the preceding word. That keeps OCR'd
    inner quotes from splitting a block quotation. A right curly quote can
    only close, so it closes even with a space before it ("uses. ” Sony").
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
        elif (not before.isspace() or char == "”") and (after.isspace() or after in ".,;:)]"):
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
    starts.extend(m.end() for m in re.finditer("\n", text) if not _inside(m.start(), protected))
    starts = sorted(set(starts))
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
    invented = _invented_cites(text, [_full_span(c) for c in found])
    protected = spans + [_full_span(c) for c in found if c not in case_citations] + [i["span"] for i in invented]

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
        kind = _kind(lead)
        if isinstance(lead, IdCitation):
            if previous is None or _refers_to_record(text, previous, span, _pincite(lead)):
                record_references += 1
                continue
            authority = previous.authority
        elif previous and previous.authority and _is_history(text, previous.span[1], lead):
            authority = _authority_for(text, group, antecedents, authorities, previous.authority.case_name)
            kind = "history"
        else:
            authority = _authority_for(text, group, antecedents, authorities)
        if authority is None and _is_cross_reference(lead):
            record_references += 1
            continue
        occurrences.append(
            Occurrence(
                ordinal=len(occurrences) + 1,
                kind=kind,
                authority=authority,
                cite_text=text[span[0] : span[1]],
                pincite=_pincite(lead),
                span=span,
                proposition=_proposition(text, sentences, protected, span),
                in_quotation=any(qs <= span[0] < qe for qs, qe in quotes),
                signal=_signal(text, span[0]),
                parenthetical=_explanatory_parenthetical(text, group[-1].span()[1]),
            )
        )

    nested = find_nested_quotes(text, quotes, [o.span[0] for o in occurrences])
    for item in invented:
        authority = Authority(
            ordinal=len(authorities) + 1,
            case_name=item["case_name"],
            reporter_cites=[item["cite"]],
            year=item["year"],
            court=None,
            invented_reporter=item["reason"],
        )
        authorities.append(authority)
        occurrences.append(
            Occurrence(
                ordinal=0,
                kind="full",
                authority=authority,
                cite_text=text[item["span"][0] : item["span"][1]],
                pincite=item["pincite"],
                span=item["span"],
                proposition=_proposition(text, sentences, protected, item["span"]),
                in_quotation=any(qs <= item["span"][0] < qe for qs, qe in quotes),
            )
        )
    occurrences.sort(key=lambda o: o.span[0])
    for ordinal, occurrence in enumerate(occurrences, start=1):
        occurrence.ordinal = ordinal

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
    """Where the case name begins, correcting eyecite's guess.

    eyecite leaves "In re" out of the name, so it is pulled back in. It stops
    a first party at an ampersand ("G. D. Searle & | Co. v. ..."), so the name
    is walked back over it. It also starts too early after a parenthetical
    ("Hughes, J.). In Simon v. ...") or an Id. cite ("Id. Conoshenti v. ..."),
    and folds in lead-ins ("In the case of", "of"); those are skipped.
    """
    start = _full_span(citation)[0]
    if text[:start].endswith("In re "):
        return start - len("In re ")
    cite_start = citation.span()[0]
    if isinstance(citation, FullCaseCitation) and text[:start].rstrip().endswith("&"):
        name, name_start = _name_before(text, cite_start)
        if name and name_start < start:
            signals = list(_SIGNAL_LEAD.finditer(text, name_start, start))
            start = signals[-1].end() if signals else name_start
    if _COURT_YEAR_ONLY.match(text[start:cite_start]):
        start = _name_before_parenthetical(text, start)
    if isinstance(citation, ShortCaseCitation):
        # A short form is one name ("Weaver, 744 F.3d at 143"); eyecite can
        # reach back past the sentence before it ("MCMIS. Weaver").
        segment = text[start:cite_start]
        ends = [m.end() for m in _SENTENCE_END.finditer(segment) if not _is_abbreviation(segment, m.start())]
        ends += [m.end() for m in re.finditer("\n", segment)]
        if ends:
            start += max(ends)
    junk = _NAME_JUNK.match(text[start:cite_start])
    if junk:
        start += junk.end()
    lead_in = re.match(r"(?:(?:[Ii]n|of|the|case)\s+)+(?!re\b)", text[start:cite_start])
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
        docket_number=_docket_number(text, named),
    )
    authorities.append(authority)
    return authority


def _case_name(text: str, citation: FullCaseCitation) -> str:
    start = _name_start(text, citation)
    name = text[start : citation.span()[0]].strip().rstrip(",").strip()
    name = re.sub(r"\.{2,}", ".", name)
    name = re.sub(r",\s*(?:(?:Ca|Case|Civ|Civil|Adv|Pro|Cr|Crim)\.?\s+)*Nos?\.\s.*$", "", name)
    name = re.sub(r"\s*\([^()]*\b\d{4}\)$", "", name)
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


def _invented_cites(text: str, known_spans: list[tuple[int, int]]) -> list[dict]:
    """Citations to reporter series that don't exist, which eyecite can't see.

    "Smith v. Jones, 475 F.6th 972, 1010 (8th Cir. 1983)": the case name is
    taken back to the start of its clause, and the pincite and year forward.
    """
    found = []
    for match in CITE_WITH_SERIES.finditer(text):
        reason = invented_series(match.group("reporter"))
        if reason is None or _inside(match.start(), known_spans):
            continue
        name, start = _name_before(text, match.start())
        after = re.match(r"(?:,\s*(?:at\s*)?(\d+(?:[-–]\d+)?))?\s*(\(([^)]*?(\d{4}))\))?", text[match.end() :])
        found.append({
            "span": (start, match.end() + (after.end() if after else 0)),
            "cite": f"{match.group('volume')} {match.group('reporter')} {match.group('page')}",
            "case_name": name,
            "pincite": after.group(1) if after else None,
            "year": after.group(4) if after and after.group(4) else None,
            "reason": reason,
        })
    return found


_NAME_CONNECTORS = frozenset("of the & and ex rel. de la in re v. for".split())
_LEAD_INS = frozenset("in see also cf. e.g., but compare".split())


def _name_before_parenthetical(text: str, paren_start: int) -> int:
    """California style puts court and year before the reporter: "(Smith v. Jones (9th Cir. 1996) 111 F.3d 1)".

    The name is the "X v. Y" between the last opening parenthesis or sentence
    end and the court-and-year parenthetical.
    """
    window_start = max(0, paren_start - 200)
    window = text[window_start:paren_start]
    boundary = window.rfind("(") + 1
    if not boundary:
        ends = [m.end() for m in _SENTENCE_END.finditer(window) if not _is_abbreviation(window, m.start())]
        boundary = ends[-1] if ends else 0
    name = window[boundary:]
    if " v. " not in name:
        return paren_start
    return window_start + boundary + (len(name) - len(name.lstrip()))


def _name_before(text: str, cite_start: int) -> tuple[str, int]:
    """The "Smith v. Jones Corp." just before a cite, and where it starts.

    Walks back from the comma before the cite over capitalised words and
    connectors, so it stops at the sentence that came before.
    """
    window_start = max(0, cite_start - 160)
    head = text[window_start:cite_start].rstrip()
    if not head.endswith(",") or " v. " not in head:
        return "", cite_start
    words = head[:-1].split(" ")
    kept: list[str] = []
    for word in reversed(words):
        if word and (word[0].isupper() or word[0].isdigit() or word.lower() in _NAME_CONNECTORS):
            kept.append(word)
            continue
        break
    kept.reverse()
    while kept and kept[0].lower().strip(",") in _LEAD_INS and not (
        kept[0].lower() == "in" and len(kept) > 1 and kept[1].lower() == "re"
    ):
        kept.pop(0)
    name = " ".join(kept)
    if " v. " not in f" {name} ":
        return "", cite_start
    return name, window_start + head.rfind(name)


def _docket_number(text: str, citation: FullCaseCitation) -> str | None:
    """The docket number cited with an unpublished decision, as "13-cv-07812"."""
    match = _DOCKET_NUMBER.search(text[_name_start(text, citation) : citation.span()[0]])
    if not match:
        return None
    year, case_type, number = match.groups()
    case_type = "cv" if case_type.lower() in ("cv", "civ") else case_type.lower()
    return f"{year}-{case_type}-{int(number):05d}"


def _is_cross_reference(citation: CitationBase) -> bool:
    """"supra at n. 4" points to the filing's own footnote, not a case."""
    if not isinstance(citation, SupraCitation):
        return False
    guess = citation.metadata.antecedent_guess or ""
    return not guess[:1].isupper()


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


def _signal(text: str, start: int) -> str | None:
    """The introductory signal right before a citation ("see also", "cf.", "but see"), lowercased."""
    match = _SIGNAL_BEFORE.search(text[max(0, start - 40) : start])
    if not match:
        return None
    return re.sub(r"\s+", " ", match.group(1).lower().replace(",", "")).strip()


def _explanatory_parenthetical(text: str, cite_end: int) -> str | None:
    """What the filing says the case holds, from the parenthetical after the cite.

    Court-and-year parentheticals and boilerplate ("citation omitted",
    "quoting ...", "emphasis added") are skipped; the citation clause ends at
    anything other than a pincite, space or another parenthetical.
    """
    position = cite_end + len(_PIN_AFTER.match(text, cite_end).group())
    while position < len(text) and text[position] == "(":
        depth, end = 0, position
        while end < len(text):
            depth += {"(": 1, ")": -1}.get(text[end], 0)
            if depth == 0:
                break
            end += 1
        content = text[position + 1 : end].strip()
        if not _COURT_YEAR_CONTENT.search(content) and not _BOILERPLATE.match(content):
            return content or None
        position = end + 1
        while position < len(text) and text[position] in " \t\n":
            position += 1
    return None


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
    if _EXHIBIT_LABEL.search(text[:period]):
        return False
    token = re.search(r"([A-Za-z.]+)$", text[:period])
    if not token:
        return False
    word = token.group(1).strip(".").lower()
    return word in _ABBREVIATIONS or len(word.replace(".", "")) == 1
