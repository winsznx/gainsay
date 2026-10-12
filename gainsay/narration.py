"""One sentence saying what the agent just did to a citation and why.

Built from the same findings the agent records, so the sentence can't say
anything the ledger doesn't. A viewer with the sound off should be able to
follow a run from these lines alone.
"""

from gainsay.findings import FAIL, PASS, UNVERIFIABLE, Finding
from gainsay.status import primary_status

_STEP = {
    ("existence", PASS): "found",
    ("existence", FAIL): "not found after the lookup and a name search",
    ("existence", UNVERIFIABLE): "couldn't be confirmed",
    ("identity", FAIL): "the cite points to a different case",
    ("quotation", PASS): "quote matches the opinion",
    ("quotation", FAIL): "quote not in the opinion",
    ("proposition", PASS): "opinion supports the statement",
    ("proposition", FAIL): "opinion doesn't support the statement",
    ("proposition", UNVERIFIABLE): "support couldn't be judged",
    ("pincite", FAIL): "pincite past the opinion's pages",
}


def narrate(label: str, findings: list[Finding], next_label: str | None) -> str:
    outcomes = {f.check: f.outcome for f in findings}
    steps = [_STEP[(f.check, f.outcome)] for f in findings if (f.check, f.outcome) in _STEP]
    status = primary_status(outcomes) or "incomplete"
    sentence = f"{label}: {' → '.join(steps) or 'checked'} → {status}."
    return f"{sentence} Next: {next_label}." if next_label else f"{sentence} That was the last citation."


def citation_label(case_name: str | None, reporter_cite: str | None, cite_text: str) -> str:
    """"Varghese, 925 F.3d 1339": the first party and the case's first reporter cite."""
    party = (case_name or "").split(" v. ")[0].strip() or "Unresolved citation"
    return f"{party}, {reporter_cite or _trim(cite_text)}"


def _trim(text: str, limit: int = 40) -> str:
    text = text.split(" (")[0]
    return text if len(text) <= limit else text[: limit - 3] + "..."
