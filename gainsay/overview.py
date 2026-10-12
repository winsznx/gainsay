"""Numbers for the landing page and the docket dashboard.

Everything here is read from the ledger, the budget log and the stored score
files, so the site can't show a number no run produced.
"""

import json
import re
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from gainsay.courtlistener import DAY, DEFAULT_BUDGET_PATH, HOUR
from gainsay.dockets import DEFAULT_DOCKET_CONFIG, DocketConfig, load_docket_config, opposing_names
from gainsay.report import PROBLEM_STATUSES, RunReport, load_run

REPO_ROOT = Path(__file__).resolve().parent.parent
RESULTS_DIR = REPO_ROOT / "scoring" / "results"


@dataclass
class EntryRow:
    entry_number: int
    date_filed: str | None
    summary: str
    filed_by: list[str]
    report: RunReport | None = None

    @property
    def role(self) -> str:
        if self.filed_by:
            return "other side"
        return "control" if self.report else "not checked"


@dataclass
class DocketOverview:
    name: str
    court: str
    docket_number: str
    entries: list[EntryRow] = field(default_factory=list)

    @property
    def checked(self) -> list[EntryRow]:
        return [e for e in self.entries if e.report]

    @property
    def opposing(self) -> list[EntryRow]:
        return [e for e in self.entries if e.filed_by]

    @property
    def citations_checked(self) -> int:
        return sum(len(e.report.citations) for e in self.checked)

    @property
    def citations_flagged(self) -> int:
        return sum(e.report.problem_count for e in self.checked)


def docket_overview(conn: sqlite3.Connection, config_path: Path = DEFAULT_DOCKET_CONFIG) -> DocketOverview | None:
    config = load_docket_config(config_path)
    docket = conn.execute(
        "SELECT * FROM dockets WHERE court = ? AND docket_number = ?", (config.court, config.docket_number)
    ).fetchone()
    if docket is None:
        return None
    overview = DocketOverview(config.name, config.court, config.docket_number)
    latest = {
        row["entry_number"]: row["run_id"]
        for row in conn.execute(
            "SELECT f.entry_number, MAX(r.id) AS run_id FROM runs r JOIN filings f ON f.id = r.filing_id "
            "WHERE f.docket_id = ? GROUP BY f.entry_number",
            (docket["id"],),
        )
    }
    for row in conn.execute(
        "SELECT * FROM docket_entries WHERE docket_id = ? ORDER BY entry_number", (docket["id"],)
    ):
        run_id = latest.get(row["entry_number"])
        overview.entries.append(
            EntryRow(
                entry_number=row["entry_number"],
                date_filed=row["date_filed"],
                summary=_summary(row["description"]),
                filed_by=opposing_names(row["description"], config),
                report=load_run(conn, run_id) if run_id else None,
            )
        )
    return overview


def budget_status(path: Path = DEFAULT_BUDGET_PATH, now: float | None = None) -> dict[str, Any] | None:
    """CourtListener calls in the last hour and day, and when the day's oldest call frees up."""
    if not path.exists():
        return None
    now = now or time.time()
    calls = sorted(t for t in json.loads(path.read_text())["calls"] if now - t < DAY.seconds)
    return {
        "day_used": len(calls),
        "day_cap": DAY.max_calls,
        "hour_used": sum(now - t < HOUR.seconds for t in calls),
        "hour_cap": HOUR.max_calls,
        "next_free": time.strftime("%H:%M UTC", time.gmtime(calls[0] + DAY.seconds)) if calls else None,
    }


def latest_mata_score(results: Path = RESULTS_DIR) -> dict[str, Any] | None:
    """The highest-numbered stored run score against the Mata sanctions opinion."""
    scored = sorted(
        (int(m.group(1)), p) for p in results.glob("run-*-score.json") if (m := re.match(r"run-(\d+)-score", p.stem))
    )
    return json.loads(scored[-1][1].read_text()) if scored else None


def held_out_benchmark(results: Path = RESULTS_DIR) -> dict[str, Any] | None:
    files = sorted(results.glob("lephantomcite-heldout-*.json"))
    if not files:
        return None
    data = json.loads(files[-1].read_text())
    return {"size": data["subset"]["size"], "arms": {a["arm"]: a for a in data["arms"]}}


def problem_statuses() -> tuple[str, ...]:
    return PROBLEM_STATUSES


def _summary(description: str) -> str:
    text = re.split(r"\.\s*Document filed by|\s\(Entered:|\.\s*\(Attachments", description)[0]
    text = re.sub(r"\.*\([A-Z][A-Za-z'\-]+, [A-Z][A-Za-z'\-]+\)\s*$", "", text)
    text = re.sub(r",{2,}", "", text).strip(" .")
    return text if len(text) <= 110 else text[:107].rstrip() + "..."
