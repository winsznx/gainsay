"""Read a check run back out of the ledger as a report.

The UI and any written report use this one reader, so every number shown
comes from the stored findings and nothing is recomputed elsewhere.
"""

import json
import sqlite3
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from gainsay.status import (
    DOESNT_SUPPORT,
    NOT_FOUND,
    QUOTE_NOT_IN_OPINION,
    STATUSES,
    WRONG_CASE,
    pincite_flag,
    primary_status,
)

COURTLISTENER = "https://www.courtlistener.com"
PROBLEM_STATUSES = (NOT_FOUND, WRONG_CASE, QUOTE_NOT_IN_OPINION, DOESNT_SUPPORT)
INCOMPLETE = "Incomplete"


@dataclass(frozen=True)
class CheckResult:
    outcome: str
    reason: str
    evidence: dict[str, Any]


@dataclass
class CitationReport:
    ordinal: int
    kind: str
    case_name: str | None
    cite_text: str
    pincite: str | None
    in_quotation: bool
    proposition: str
    quotes: list[str]
    checks: dict[str, CheckResult] = field(default_factory=dict)

    @property
    def status(self) -> str:
        return primary_status({k: v.outcome for k, v in self.checks.items()}) or INCOMPLETE

    @property
    def pincite_flag(self) -> bool:
        return pincite_flag({k: v.outcome for k, v in self.checks.items()})

    @property
    def opinion_url(self) -> str | None:
        for check in ("identity", "existence"):
            result = self.checks.get(check)
            if result is None or result.outcome != "pass":
                continue
            cluster = result.evidence.get("cluster") or (result.evidence.get("candidates") or [{}])[0]
            if cluster.get("absolute_url"):
                return COURTLISTENER + cluster["absolute_url"]
        return None


@dataclass
class RunReport:
    run: dict[str, Any]
    filing: dict[str, Any]
    citations: list[CitationReport]

    @property
    def status_counts(self) -> dict[str, int]:
        counts = Counter(c.status for c in self.citations)
        order = [*STATUSES, INCOMPLETE]
        return {status: counts[status] for status in order if counts[status]}

    @property
    def problem_count(self) -> int:
        return sum(self.status_counts.get(s, 0) for s in PROBLEM_STATUSES)

    @property
    def headline(self) -> str:
        total = len(self.citations)
        if total == 0:
            return "This filing cites no cases."
        incomplete = self.status_counts.get(INCOMPLETE, 0)
        problems = self.problem_count
        if problems:
            sentence = f"{problems} of {total} citations {'has' if problems == 1 else 'have'} a problem."
        elif incomplete:
            sentence = f"No problems found yet in {total - incomplete} of {total} citations."
        else:
            sentence = f"None of the {total} citations failed a check."
        return sentence

    @property
    def pincite_flags(self) -> int:
        return sum(c.pincite_flag for c in self.citations)


def list_runs(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        "SELECT r.*, f.case_name, f.court, f.docket_number, f.entry_number, f.description "
        "FROM runs r JOIN filings f ON f.id = r.filing_id ORDER BY r.id DESC"
    ).fetchall()
    return [dict(row) for row in rows]


def load_run(conn: sqlite3.Connection, run_id: int) -> RunReport | None:
    run = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
    if run is None:
        return None
    filing = conn.execute("SELECT * FROM filings WHERE id = ?", (run["filing_id"],)).fetchone()
    rows = conn.execute(
        "SELECT c.*, a.case_name FROM citations c LEFT JOIN authorities a ON a.id = c.authority_id "
        "WHERE c.filing_id = ? ORDER BY c.ordinal",
        (filing["id"],),
    ).fetchall()
    citations = {
        row["id"]: CitationReport(
            ordinal=row["ordinal"],
            kind=row["kind"],
            case_name=row["case_name"],
            cite_text=row["cite_text"],
            pincite=row["pincite"],
            in_quotation=bool(row["in_quotation"]),
            proposition=row["proposition"],
            quotes=json.loads(row["quotes"]),
        )
        for row in rows
    }
    for finding in conn.execute("SELECT * FROM findings WHERE run_id = ?", (run_id,)):
        citations[finding["citation_id"]].checks[finding["check_name"]] = CheckResult(
            finding["outcome"], finding["reason"], json.loads(finding["evidence"])
        )
    filing_fields = {k: filing[k] for k in filing.keys() if k != "clean_text"}
    return RunReport(dict(run), filing_fields, list(citations.values()))
