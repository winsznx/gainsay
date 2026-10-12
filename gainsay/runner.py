"""Run every check on a filing's citations and record the findings.

Each citation gets its own neatlogs span tagged with the run version. A
CourtListener 429, an exhausted budget or a Claude rate limit pauses the run;
resuming skips every finding already recorded. A run a crash left "running"
resumes the same way.

Outages and crashes can be simulated to show recovery. Both are labelled
"simulated" in the ledger, the run page and the trace.
"""

import json
import os
import sqlite3
from dataclasses import dataclass

import anthropic

from gainsay.cache import CachedCourtListener
from gainsay.checker import CHECKS, Checker
from gainsay.courtlistener import BudgetExhausted, CourtListenerError
from gainsay.existence import Authority
from gainsay.ledger import finish_run, record_finding, record_trace, recorded_checks, resume_run, start_run
from gainsay.proposition import Judge
from gainsay.tracing import Tracing


@dataclass(frozen=True)
class RunResult:
    run_id: int
    status: str
    reason: str | None = None


class VersionMismatch(Exception):
    pass


class SimulatedOutage(BudgetExhausted):
    def __init__(self, after: int):
        super().__init__("simulated", None)
        self.args = (f"simulated CourtListener outage after {after} citations",)

    def __str__(self) -> str:
        return self.args[0]


@dataclass(frozen=True)
class Simulation:
    """Fail on purpose after this many citations checked in an attempt."""

    outage_after: int | None = None
    crash_after: int | None = None


def run_checks(
    conn: sqlite3.Connection,
    filing_id: int,
    version: str,
    api: CachedCourtListener,
    judge: Judge,
    tracing: Tracing,
    resume_run_id: int | None = None,
    simulation: Simulation | None = None,
) -> RunResult:
    if resume_run_id is not None:
        run = resume_run(conn, resume_run_id)
        if run["version"] != version:
            raise VersionMismatch(f"run {run['id']} ran {run['version']}, code is now {version}")
        run_id = run["id"]
    else:
        run_id = start_run(conn, filing_id, version)

    citations = conn.execute(
        "SELECT c.*, a.case_name FROM citations c LEFT JOIN authorities a ON a.id = c.authority_id "
        "WHERE c.filing_id = ? ORDER BY c.ordinal",
        (filing_id,),
    ).fetchall()
    done = recorded_checks(conn, run_id)
    with tracing.span("gainsay.check_run", run_id=run_id, run_version=version, filing_id=filing_id) as run_span:
        trace_id = _trace_id(run_span)
        if trace_id:
            record_trace(conn, run_id, trace_id)
        if run_span is not None:
            run_span.set_attribute("gainsay.resumed", resume_run_id is not None)
            run_span.set_attribute("gainsay.findings_already_recorded", len(done))
        checked = 0
        try:
            checker = Checker(api, load_authorities(conn, filing_id), citations, judge)
            for citation in citations:
                if all((citation["id"], check) in done for check in CHECKS):
                    continue
                _maybe_fail(conn, run_id, trace_id, simulation, checked)
                checked += 1
                with tracing.span(
                    "gainsay.check_citation",
                    kind="CHAIN",
                    run_id=run_id,
                    run_version=version,
                    citation=citation["ordinal"],
                    case_name=citation["case_name"] or "unresolved",
                ) as span:
                    for finding in checker.check(citation):
                        if (citation["id"], finding.check) in done:
                            continue
                        record_finding(
                            conn, run_id, citation["id"], finding.check,
                            finding.outcome, finding.reason, finding.evidence,
                        )
                        if span is not None:
                            span.set_attribute(f"gainsay.{finding.check}", finding.outcome)
        except (BudgetExhausted, anthropic.RateLimitError) as exc:
            result = RunResult(run_id, "paused", str(exc))
            _record_failure(run_span, exc)
        except CourtListenerError as exc:
            result = RunResult(run_id, "failed", str(exc))
            _record_failure(run_span, exc)
        else:
            result = RunResult(run_id, "complete")
        if run_span is not None:
            run_span.set_attribute("gainsay.run_status", result.status)
        if trace_id:
            record_trace(conn, run_id, trace_id, result.status, result.reason)
    finish_run(conn, run_id, result.status, result.reason)
    return result


def _maybe_fail(
    conn: sqlite3.Connection, run_id: int, trace_id: str | None, simulation: Simulation | None, checked: int
) -> None:
    if simulation is None:
        return
    if simulation.outage_after == checked:
        raise SimulatedOutage(checked)
    if simulation.crash_after == checked:
        reason = f"simulated crash after {checked} citations"
        with conn:
            conn.execute("UPDATE runs SET status_reason = ? WHERE id = ?", (reason, run_id))
        if trace_id:
            record_trace(conn, run_id, trace_id, "crashed", reason)
        os._exit(137)


def _trace_id(span: object | None) -> str | None:
    if span is None:
        return None
    return f"{span.get_span_context().trace_id:032x}"


def _record_failure(span: object | None, exc: Exception) -> None:
    """Put the failure in the trace, so a paused run shows what stopped it."""
    if span is not None:
        span.record_exception(exc)
        span.set_attribute("gainsay.status_reason", str(exc))


def paused_run(conn: sqlite3.Connection, filing_id: int, version: str) -> int | None:
    """A run of this code on this filing that a new attempt should resume:
    paused by the budget, or left "running" by a crash."""
    row = conn.execute(
        "SELECT id FROM runs WHERE filing_id = ? AND version = ? AND status IN ('paused', 'running') "
        "ORDER BY id DESC",
        (filing_id, version),
    ).fetchone()
    return row["id"] if row else None


def load_authorities(conn: sqlite3.Connection, filing_id: int) -> dict[int, Authority]:
    rows = conn.execute("SELECT * FROM authorities WHERE filing_id = ?", (filing_id,))
    return {
        row["id"]: Authority(
            id=row["id"],
            case_name=row["case_name"],
            reporter_cites=json.loads(row["reporter_cites"]),
            year=row["year"],
            court=row["court"],
            docket_number=row["docket_number"],
        )
        for row in rows
    }
