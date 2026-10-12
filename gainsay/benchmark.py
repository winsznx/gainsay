"""LePhantomCite, scored on its error types.

LePhantomCite (arXiv 2606.21155) labels five error types in brief excerpts.
Each is scored on its own and together: the two citation-level types
(non_existent_citation, case_name_mismatch), which need only a lookup, and
all five, which add wrong_pincite, misquote and content_misrepresentation
and need the cited opinion's text.

Scoring follows the paper's released evaluator with a type filter
(polaris_agents/evaluation/hallucination_checker_evaluator.py): a prediction
matches a labelled span when either is a case-insensitive substring of the
other, or when a "..." in one matches in order in the other. Recall is the
share of in-scope labelled spans some prediction matches. Precision counts
predictions that match an in-scope span; a prediction that only matches an
out-of-scope span is left out of precision, as their code does.
"""

import json
import random
import re
from dataclasses import dataclass, field
from pathlib import Path

from gainsay.findings import FAIL, Finding
from gainsay.quotes import missing_passages

IN_SCOPE = ("non_existent_citation", "case_name_mismatch")
ALL_TYPES = (*IN_SCOPE, "wrong_pincite", "misquote", "content_misrepresentation")
_ELLIPSIS = re.compile(r"\.\.\.|…")


@dataclass
class Excerpt:
    index: int
    text: str
    labels: dict[str, str]
    citations: list[str]


@dataclass
class ArmScore:
    arm: str
    types: tuple[str, ...] = IN_SCOPE
    predictions: int = 0
    correct: int = 0
    found: dict[str, int] = field(default_factory=dict)
    labelled: dict[str, int] = field(default_factory=dict)

    def __post_init__(self):
        self.found = {t: self.found.get(t, 0) for t in self.types}
        self.labelled = {t: self.labelled.get(t, 0) for t in self.types}

    @property
    def precision(self) -> float:
        return self.correct / self.predictions if self.predictions else 0.0

    @property
    def recall(self) -> float:
        labelled = sum(self.labelled.values())
        return sum(self.found.values()) / labelled if labelled else 0.0

    @property
    def f1(self) -> float:
        p, r = self.precision, self.recall
        return 2 * p * r / (p + r) if p + r else 0.0

    def as_dict(self) -> dict:
        return {
            "arm": self.arm,
            "predictions": self.predictions,
            "correct": self.correct,
            "precision": round(self.precision, 3),
            "recall": round(self.recall, 3),
            "f1": round(self.f1, 3),
            "recall_by_type": {t: f"{self.found[t]}/{self.labelled[t]}" for t in self.types},
        }


def load_excerpts(path: Path) -> list[Excerpt]:
    excerpts = []
    for index, line in enumerate(path.read_text().splitlines()):
        row = json.loads(line)
        excerpts.append(Excerpt(index, row["text"], row.get("list_hallucinations") or {}, row.get("citations_in_segment") or []))
    return excerpts


def subset(excerpts: list[Excerpt], size: int, seed: int, exclude: frozenset[int] = frozenset()) -> list[Excerpt]:
    """A seeded random sample, disjoint from excluded indices (a development subset)."""
    pool = [i for i in range(len(excerpts)) if i not in exclude]
    chosen = sorted(random.Random(seed).sample(pool, min(size, len(pool))))
    return [excerpts[i] for i in chosen]


def matches(label: str, prediction: str) -> bool:
    g, p = label.strip().lower(), prediction.strip().lower()
    if g in p or p in g:
        return True
    return _ellipsis_match(g, p) or _ellipsis_match(p, g)


def score(
    arm: str, excerpts: list[Excerpt], predictions: dict[int, list[str]], types: tuple[str, ...] = IN_SCOPE
) -> ArmScore:
    result = ArmScore(arm, types)
    for excerpt in excerpts:
        in_scope = {span: kind for span, kind in excerpt.labels.items() if kind in types}
        out_of_scope = [span for span, kind in excerpt.labels.items() if kind not in types]
        predicted = predictions.get(excerpt.index, [])
        for span, kind in in_scope.items():
            result.labelled[kind] += 1
            if any(matches(span, p) for p in predicted):
                result.found[kind] += 1
        for p in predicted:
            hit = any(matches(span, p) for span in in_scope)
            if not hit and any(matches(span, p) for span in out_of_scope):
                continue
            result.predictions += 1
            result.correct += hit
    return result


def _ellipsis_match(pattern: str, text: str) -> bool:
    fragments = [f.strip() for f in _ELLIPSIS.split(pattern) if f.strip()]
    if len(fragments) < 2:
        return False
    position = 0
    for fragment in fragments:
        position = text.find(fragment, position)
        if position < 0:
            return False
        position += len(fragment)
    return True


def citation_spans(kind: str, cite_span: str, findings: list[Finding]) -> list[str]:
    """The citation, when its case doesn't exist or isn't at the cite.

    A full cite or a history cite is flagged; an Id. or short cite inherits
    its case's findings, and LePhantomCite labels the full cite. A short cite
    with no full cite in the excerpt was checked on its own, so it is flagged.
    """
    by_check = {f.check: f for f in findings}
    failed = [by_check[c] for c in ("existence", "identity") if c in by_check and by_check[c].outcome == FAIL]
    own = kind in ("full", "history") or any(f.evidence.get("untied_short") for f in failed)
    return [cite_span] if failed and own else []


def predicted_spans(kind: str, cite_span: str, proposition: str, findings: list[Finding]) -> list[str]:
    """Everything Gainsay flags for one citation, as the spans LePhantomCite labels.

    On top of citation_spans: a pincite outside the opinion flags the
    citation, a quote the opinion doesn't contain flags the quoted words, and
    an opinion that doesn't support the statement flags the statement.
    """
    by_check = {f.check: f for f in findings}
    spans = citation_spans(kind, cite_span, findings)
    if "pincite" in by_check and by_check["pincite"].outcome == FAIL and cite_span not in spans:
        spans.append(cite_span)
    if "quotation" in by_check:
        spans.extend(missing_passages(by_check["quotation"]))
    if "proposition" in by_check and by_check["proposition"].outcome == FAIL:
        spans.append(proposition)
    return spans


_COURT_YEAR = re.compile(r"\([^()]*\b\d{4}\)")
_MARKUP = r"[*_]{0,2}"


def citation_as_written(cite_text: str) -> str:
    """The citation from case name through its court-and-year parenthetical, without explanatory ones."""
    match = _COURT_YEAR.search(cite_text)
    return cite_text[: match.end()] if match else cite_text


def raw_span(raw: str, span: str) -> str:
    """A span from the cleaned text, as the excerpt itself writes it.

    clean_text drops italic asterisks and rejoins lines, so the span is found
    again in the raw excerpt allowing for those, and returned as written there.
    """
    words = span.split()
    if not words:
        return span
    pattern = r"[\s*_]+".join(_MARKUP.join(re.escape(ch) for ch in word) for word in words)
    match = re.search(pattern, raw)
    return match.group(0) if match else span
