"""A run as a Markdown report someone can file away or attach to a reply.

Built from the same report reader as the web pages, so it says exactly what
the ledger says, including which sources were searched and which parts of
a run were simulated.
"""

from courts_db import courts

from gainsay.checker import CHECKS
from gainsay.filings import ecf_label
from gainsay.report import RunReport

SOURCES = (
    "CourtListener citation lookup, case-law search, RECAP docket search and opinion text. "
    "Westlaw and Lexis are outside the sources searched."
)
_OUTCOMES = {"pass": "Yes", "fail": "No", "unverifiable": "Can't tell", "not_applicable": "Not applicable"}
_COURT_CITES = {court["id"]: court.get("citation_string") for court in courts}


def render_markdown(report: RunReport) -> str:
    filing, run = report.filing, report.run
    court = _COURT_CITES.get(filing["court"]) or filing["court"]
    lines = [
        f"# Gainsay report: {filing['case_name']}, {ecf_label(filing['entry_number'], filing.get('attachment_number'))}",
        "",
        f"{filing['case_name']}, No. {filing['docket_number']} ({court}), {ecf_label(filing['entry_number'], filing.get('attachment_number'))}: "
        f"{filing['description']}",
        "",
        f"Run {run['id']} on commit `{run['version']}`, {run['status']}, started {run['started_at']}.",
        f"Sources searched: {SOURCES}",
        "",
        f"**{report.headline}**",
        "",
        "| Status | Citations |",
        "|---|---|",
        *[f"| {status} | {count} |" for status, count in report.status_counts.items()],
        "",
    ]
    if report.pincite_flags:
        lines += [f"{report.pincite_flags} pincite(s) point past the opinion's pages.", ""]
    if report.traces:
        lines += ["neatlogs traces, one per attempt:", ""]
        lines += [f"- `{t['trace_id']}`: {t['outcome'] or 'running'}{f' ({t['reason']})' if t['reason'] else ''}"
                  for t in report.traces]
        lines.append("")

    for citation in report.citations:
        flag = " (pincite off)" if citation.pincite_flag else ""
        lines += [
            f"## {citation.ordinal}. {citation.case_name or 'Short citation with no full cite to match'}: "
            f"{citation.status}{flag}",
            "",
            f"As cited: {citation.cite_text}",
            "",
            "The filing says:",
            "",
            f"> {citation.proposition}",
            "",
        ]
        if citation.in_quotation:
            lines += ["This citation sits inside a passage the filing presents as a quotation from another case.", ""]
        for quote in citation.quotes:
            lines += ["Quoted as this case's words:", "", f"> {quote}", ""]
        lines += ["| Check | Answer | Why |", "|---|---|---|"]
        for check in CHECKS:
            result = citation.checks.get(check)
            answer = _OUTCOMES.get(result.outcome, result.outcome) if result else "Not run"
            reason = result.reason.replace("|", "\\|").replace("\n", " ") if result else ""
            lines.append(f"| {check} | {answer} | {reason} |")
        lines.append("")
        if citation.opinion_url:
            lines += [f"Opinion: {citation.opinion_url}", ""]
    return "\n".join(lines)
