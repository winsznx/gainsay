"""Server-rendered pages over the ledger.

    .venv/bin/uvicorn gainsay.web.app:app --reload
"""

import re
import sqlite3
from pathlib import Path

from courts_db import courts
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from gainsay.checker import CHECKS
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


def create_app(ledger_path: Path = DEFAULT_LEDGER_PATH) -> FastAPI:
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
    )

    def ledger() -> sqlite3.Connection:
        return connect(ledger_path)

    @app.get("/", response_class=HTMLResponse)
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

    return app


app = create_app()
