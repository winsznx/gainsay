"""Score a check run against the court's own findings.

Mata v. Avianca's sanctions opinion (ECF 54) says which cited cases do not
exist. It is the answer key, so it never goes near the agent: it is fetched
here with the plain budgeted client, never through the agent's ledger cache,
and stored under data/scoring/, which nothing in the check path reads.

The answer key (scoring/mata_answer_key.json) labels each cited case and
backs every label with words quoted from ECF 54. Scoring refuses to run if
any quote is missing from the opinion text, so a label can't drift from the
source.
"""

import json
import re
from dataclasses import dataclass
from pathlib import Path

from gainsay.courtlistener import CourtListenerClient, storage_url
from gainsay.pdf_text import choose_text, extract_pdf_text
from gainsay.quotes import locate
from gainsay.opinions import OpinionText
from gainsay.report import INCOMPLETE, RunReport
from gainsay.status import (
    DOESNT_SUPPORT,
    NOT_FOUND,
    QUOTE_NOT_IN_OPINION,
    STATUSES,
    VERIFIED,
    WRONG_CASE,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
ANSWER_KEY_PATH = REPO_ROOT / "scoring" / "mata_answer_key.json"
SCORING_DIR = REPO_ROOT / "data" / "scoring"
EVIDENCE_SCORE = 95
# Only "Not found" says a case doesn't exist. Statuses are read in order, so
# "Wrong case" always comes with a passed existence check.
FLAGGED_STATUSES = (NOT_FOUND,)


class AnswerKeyError(Exception):
    pass


# The statuses that agree with each court finding.
EXPECTED_STATUSES = {
    "does_not_exist": {NOT_FOUND},
    "does_not_exist_as_cited": {NOT_FOUND, WRONG_CASE},
    "quote_not_in_opinion": {QUOTE_NOT_IN_OPINION},
    "does_not_support": {DOESNT_SUPPORT},
    "supports": {VERIFIED},
    "supports_in_part": {VERIFIED, DOESNT_SUPPORT},
}


@dataclass(frozen=True)
class CaseScore:
    case_name: str
    exists: bool
    court_finding: str
    statuses: list[str]

    @property
    def flagged(self) -> bool:
        return any(s in FLAGGED_STATUSES for s in self.statuses)

    @property
    def outcome(self) -> str:
        if self.flagged:
            return "true positive" if not self.exists else "false positive"
        return "false negative" if not self.exists else "true negative"

    @property
    def case_status(self) -> str | None:
        """The most severe status among the case's citations, None while undecided."""
        decided = [s for s in STATUSES if s in self.statuses]
        if not decided:
            return None
        if INCOMPLETE in self.statuses and decided[0] not in FLAGGED_STATUSES:
            return None
        return decided[0]

    @property
    def agrees_with_court(self) -> bool | None:
        status = self.case_status
        return None if status is None else status in EXPECTED_STATUSES[self.court_finding]


def fetch_answer_source(client: CourtListenerClient, docket_id: int, entry: int) -> str:
    """ECF text for scoring. Deliberately skips the agent's blocklist."""
    path = SCORING_DIR / f"{docket_id}-ecf{entry}.txt"
    if path.exists():
        return path.read_text()
    results = client.get_json(
        "recap-documents/",
        {"docket_entry__docket__id": docket_id, "docket_entry__entry_number": entry},
    )["results"]
    (document,) = [d for d in results if d.get("attachment_number") is None]
    pdf_text = ""
    if document.get("is_available") and document.get("filepath_local"):
        pdf_text, _ = extract_pdf_text(client.download(storage_url(document["filepath_local"])))
    text, _ = choose_text(pdf_text, document.get("plain_text") or "")
    SCORING_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return text


def load_answer_key(source_text: str, path: Path = ANSWER_KEY_PATH) -> list[dict]:
    key = json.loads(path.read_text())
    source = [OpinionText(0, "answer_source", "text", source_text, [])]
    for case in key["cases"]:
        match = locate(case["evidence"], source, None)
        if match.score < EVIDENCE_SCORE:
            raise AnswerKeyError(
                f"evidence for {case['case_name']} is not in the source text "
                f"(best match {match.score:.0f}): {case['evidence']!r}"
            )
    return key["cases"]


def score_run(report: RunReport, cases: list[dict]) -> list[CaseScore]:
    """Match each answer-key case to its citations by reporter cite.

    Matching by cite, not name, keeps OCR'd names ("Al Israel Airlines" for
    El Al) from hiding a case. Id. cites join through the matched case name.
    """
    scores = []
    for case in cases:
        cite = _squash(case["cite"])
        names = {c.case_name for c in report.citations if cite in _squash(c.cite_text)}
        citations = [c for c in report.citations if c.case_name in names]
        if not citations:
            raise AnswerKeyError(f"{case['cite']} is in the answer key but not in run {report.run['id']}")
        scores.append(
            CaseScore(
                case_name=case["case_name"],
                exists=case["exists"],
                court_finding=case["court_finding"],
                statuses=[c.status for c in citations],
            )
        )
    return scores


def summarize(scores: list[CaseScore]) -> dict[str, float | int]:
    """Existence precision and recall, plus agreement with the court's full finding."""
    counts = {o: sum(s.outcome == o for s in scores) for o in
              ("true positive", "false positive", "false negative", "true negative")}
    tp, fp, fn = counts["true positive"], counts["false positive"], counts["false negative"]
    return {
        **counts,
        "precision": tp / (tp + fp) if tp + fp else 0.0,
        "recall": tp / (tp + fn) if tp + fn else 0.0,
        "agree": sum(s.agrees_with_court is True for s in scores),
        "disagree": sum(s.agrees_with_court is False for s in scores),
        "undecided": sum(s.agrees_with_court is None for s in scores),
    }


def _squash(text: str) -> str:
    return re.sub(r"\s+", "", text)
