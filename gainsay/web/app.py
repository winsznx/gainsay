"""Server-rendered pages over the ledger.

    .venv/bin/uvicorn gainsay.web.app:app --reload

GAINSAY_LEDGER points the site at another ledger file, and GAINSAY_READ_ONLY=1
opens it read-only. On Vercel (VERCEL is set) the site serves the published
snapshot in deploy/ read-only, since checks run where the keys and quota are.
"""

import os
import re
import sqlite3
from pathlib import Path

from courts_db import courts
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from gainsay.checker import CHECKS
from gainsay.export import render_markdown
from gainsay.overview import budget_status, docket_overview, held_out_benchmark, latest_mata_score
from gainsay.ledger import DEFAULT_LEDGER_PATH, connect
from gainsay.report import list_runs, load_run

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
_COURT_CITES = {court["id"]: court.get("citation_string") for court in courts}


def status_slug(status: str) -> str:
    return re.sub(r"[^a-z]+", "-", status.lower().replace("'", "")).strip("-")


def sentence(text: str) -> str:
    return text[:1].upper() + text[1:]


FINDINGS = {
    "does_not_exist": "Does not exist",
    "does_not_exist_as_cited": "Does not exist as cited",
    "does_not_support": "Doesn't support the proposition",
    "quote_not_in_opinion": "Quoted language not in the opinion",
    "supports": "Supports it",
    "supports_in_part": "Supports it in part",
}


def create_app(ledger_path: Path = DEFAULT_LEDGER_PATH, read_only: bool = False) -> FastAPI:
    app = FastAPI(title="Gainsay", docs_url=None, redoc_url=None)
    app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
    templates = Jinja2Templates(directory=HERE / "templates")
    templates.env.filters["status_slug"] = status_slug
    templates.env.filters["sentence"] = sentence
    templates.env.globals.update(
        CHECKS=CHECKS,
        CHECK_LABELS=CHECK_LABELS,
        OUTCOME_LABELS=OUTCOME_LABELS,
        court_cite=lambda court_id: _COURT_CITES.get(court_id) or court_id,
        FINDINGS=FINDINGS,
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
    def run(request: Request, run_id: int):
        report = load_run(ledger(), run_id)
        if report is None:
            raise HTTPException(status_code=404, detail=f"No run {run_id} in the ledger")
        return templates.TemplateResponse(request, "run.html", {"report": report})

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
