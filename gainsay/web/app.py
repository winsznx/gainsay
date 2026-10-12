"""Server-rendered pages over the ledger.

    .venv/bin/uvicorn gainsay.web.app:app --reload

GAINSAY_LEDGER points the site at another ledger file, and GAINSAY_READ_ONLY=1
opens it read-only. On Vercel (VERCEL is set) the site serves the published
snapshot in deploy/ read-only, since checks run where the keys and quota are.
"""

import os
import re
import sqlite3
from functools import cache
from pathlib import Path

from courts_db import courts
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from markupsafe import Markup

from gainsay.checker import CHECKS
from gainsay.courtlistener import BACKOFF_SECONDS, DAY, HOUR, MAX_RETRIES, MINUTE
from gainsay.dockets import load_docket_config
from gainsay.export import render_markdown
from gainsay.overview import budget_status, docket_overview, held_out_benchmark, latest_mata_score
from gainsay.ledger import DEFAULT_LEDGER_PATH, connect
from gainsay.report import PROBLEM_STATUSES, CitationReport, RunReport, list_runs, load_run
from gainsay.status import DOESNT_SUPPORT, NOT_FOUND, QUOTE_NOT_IN_OPINION, WRONG_CASE

HERE = Path(__file__).resolve().parent

CHECK_LABELS = {
    "existence": "Case exists",
    "identity": "Cite points to this case",
    "quotation": "Quotation is in the opinion",
    "proposition": "Opinion supports the statement",
    "pincite": "Pincite is inside the opinion",
}
OUTCOME_LABELS = {
    "pass": "Yes",
    "fail": "No",
    "unverifiable": "Can't tell",
    "not_applicable": "Not applicable",
}
CHECK_ICONS = {
    "existence": "search",
    "identity": "id-card",
    "quotation": "quote",
    "proposition": "scale",
    "pincite": "file-digit",
}
OUTCOME_ICONS = {
    "pass": "check",
    "fail": "x",
    "unverifiable": "circle-help",
    "not_applicable": "minus",
}
STATUS_SET_BY = {
    "existence": NOT_FOUND,
    "identity": WRONG_CASE,
    "quotation": QUOTE_NOT_IN_OPINION,
    "proposition": DOESNT_SUPPORT,
}
_COURT_CITES = {court["id"]: court.get("citation_string") for court in courts}


def status_slug(status: str) -> str:
    return re.sub(r"[^a-z]+", "-", status.lower().replace("'", "")).strip("-")


def sentence(text: str) -> str:
    return text[:1].upper() + text[1:]


@cache
def _lucide_svg(name: str) -> str:
    """A vendored lucide-static icon, without its license comment, on one line."""
    svg = (HERE / "icons" / f"{name}.svg").read_text()
    return " ".join(svg[svg.index("<svg"):].split())


def icon(name: str, size: int = 18) -> Markup:
    svg = _lucide_svg(name).replace('width="24" height="24"', f'width="{size}" height="{size}"', 1)
    return Markup(svg.replace("<svg ", '<svg aria-hidden="true" focusable="false" ', 1))


def cite_without_name(citation: CitationReport) -> str:
    text = citation.cite_text
    if citation.case_name and text.startswith(citation.case_name):
        text = text[len(citation.case_name):]
    return text.lstrip(" ,.")


FINDINGS = {
    "does_not_exist": "Does not exist",
    "does_not_exist_as_cited": "Does not exist as cited",
    "does_not_support": "Doesn't support the proposition",
    "quote_not_in_opinion": "Quoted language not in the opinion",
    "supports": "Supports it",
    "supports_in_part": "Supports it in part",
}


def first_of_each_status(report: RunReport) -> list[CitationReport]:
    """One citation per status, in status order, to show what each status looks like."""
    firsts: dict[str, CitationReport] = {}
    for citation in report.citations:
        firsts.setdefault(citation.status, citation)
    return [firsts[status] for status in report.status_counts]


def selected_citation(report: RunReport, ordinal: int | None) -> CitationReport | None:
    """The citation the inspector shows: the one asked for, else the first with a problem."""
    for citation in report.citations:
        if citation.ordinal == ordinal:
            return citation
    problems = (c for c in report.citations if c.status in PROBLEM_STATUSES)
    return next(problems, report.citations[0] if report.citations else None)


def create_app(ledger_path: Path = DEFAULT_LEDGER_PATH, read_only: bool = False) -> FastAPI:
    app = FastAPI(title="Gainsay", docs_url=None, redoc_url=None)
    app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
    templates = Jinja2Templates(directory=HERE / "templates")
    templates.env.filters["status_slug"] = status_slug
    templates.env.filters["sentence"] = sentence
    templates.env.filters["cite_without_name"] = cite_without_name
    templates.env.globals.update(
        CHECKS=CHECKS,
        CHECK_LABELS=CHECK_LABELS,
        OUTCOME_LABELS=OUTCOME_LABELS,
        STATUS_SET_BY=STATUS_SET_BY,
        LIMITS=(MINUTE, HOUR, DAY),
        MAX_RETRIES=MAX_RETRIES,
        BACKOFF_SECONDS=BACKOFF_SECONDS,
        court_cite=lambda court_id: _COURT_CITES.get(court_id) or court_id,
        icon=icon,
        CHECK_ICONS=CHECK_ICONS,
        OUTCOME_ICONS=OUTCOME_ICONS,
        FINDINGS=FINDINGS,
        DOCKET=load_docket_config(),
        READ_ONLY=read_only,
        scored_run_id=lambda: (latest_mata_score() or {}).get("run_id"),
    )

    def ledger() -> sqlite3.Connection:
        return connect(ledger_path, read_only=read_only)

    @app.get("/", response_class=HTMLResponse)
    def landing(request: Request):
        conn = ledger()
        score = latest_mata_score()
        specimen = load_run(conn, score["run_id"]) if score else None
        return templates.TemplateResponse(request, "landing.html", {
            "specimen": specimen,
            "exemplars": first_of_each_status(specimen) if specimen else [],
            "score": score if specimen else None,
            "docket": docket_overview(conn),
            "benchmark": held_out_benchmark(),
        })

    @app.get("/docket", response_class=HTMLResponse)
    def docket(request: Request):
        overview = docket_overview(ledger())
        if overview is None:
            raise HTTPException(status_code=404, detail="No docket in the ledger yet")
        budget = None if read_only else budget_status()
        return templates.TemplateResponse(request, "docket.html", {"docket": overview, "budget": budget})

    @app.get("/runs", response_class=HTMLResponse)
    def runs(request: Request):
        conn = ledger()
        rows = [(run, load_run(conn, run["id"])) for run in list_runs(conn)]
        return templates.TemplateResponse(request, "runs.html", {"rows": rows})

    @app.get("/runs/{run_id}", response_class=HTMLResponse)
    def run(request: Request, run_id: int, c: int | None = None):
        report = load_run(ledger(), run_id)
        if report is None:
            raise HTTPException(status_code=404, detail=f"No run {run_id} in the ledger")
        return templates.TemplateResponse(request, "run.html", {
            "report": report,
            "selected": selected_citation(report, c),
        })

    @app.get("/runs/{run_id}/report.md", response_class=PlainTextResponse)
    def run_report(run_id: int):
        report = load_run(ledger(), run_id)
        if report is None:
            raise HTTPException(status_code=404, detail=f"No run {run_id} in the ledger")
        return PlainTextResponse(
            render_markdown(report),
            media_type="text/markdown",
            headers={"Content-Disposition": f'attachment; filename="gainsay-run-{run_id}.md"'},
        )

    return app


SNAPSHOT = HERE.parent.parent / "deploy" / "gainsay-demo.sqlite"
_ON_VERCEL = bool(os.environ.get("VERCEL"))

app = create_app(
    Path(os.environ.get("GAINSAY_LEDGER", SNAPSHOT if _ON_VERCEL else DEFAULT_LEDGER_PATH)),
    read_only=_ON_VERCEL or os.environ.get("GAINSAY_READ_ONLY") == "1",
)
