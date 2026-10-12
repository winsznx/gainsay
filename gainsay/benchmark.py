"""LePhantomCite, scored on the two citation-level error types.

LePhantomCite (arXiv 2606.21155) labels five error types in brief excerpts.
Checking quotes, propositions and pincites needs an opinion for nearly every
citation, which CourtListener's quota (125 calls a day) can't cover, so this
harness scores only non_existent_citation and case_name_mismatch.

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

IN_SCOPE = ("non_existent_citation", "case_name_mismatch")
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
    predictions: int = 0
    correct: int = 0
    found: dict[str, int] = field(default_factory=lambda: {t: 0 for t in IN_SCOPE})
    labelled: dict[str, int] = field(default_factory=lambda: {t: 0 for t in IN_SCOPE})

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
            "recall_by_type": {t: f"{self.found[t]}/{self.labelled[t]}" for t in IN_SCOPE},
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


def score(arm: str, excerpts: list[Excerpt], predictions: dict[int, list[str]]) -> ArmScore:
    result = ArmScore(arm)
    for excerpt in excerpts:
        in_scope = {span: kind for span, kind in excerpt.labels.items() if kind in IN_SCOPE}
        out_of_scope = [span for span, kind in excerpt.labels.items() if kind not in IN_SCOPE]
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
