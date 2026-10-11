"""Watched dockets: which case, who the other side is, and what's new.

A docket config names the court, the docket number and the opposing party and
counsel. Polling asks CourtListener only for entry metadata (number, date,
description), never document text, and is not cached in the ledger, so the
blocklisted sanctions opinion can't reach the agent through a docket listing.

New means created in RECAP after the newest entry seen so far, so entries
RECAP backfills later with lower numbers are still caught.
"""

import json
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import parse_qsl, urlparse

from gainsay.blocklist import normalize_docket_number
from gainsay.courtlistener import CourtListenerClient
from gainsay.filings import Docket, FetchError
from gainsay.ledger import now

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DOCKET_CONFIG = REPO_ROOT / "dockets" / "mata-v-avianca.json"
ENTRY_FIELDS = "entry_number,date_filed,date_created,description"

_COURT_ENTRY = re.compile(r"Signed by (?:Judge|Magistrate|Clerk)|SO ORDERED", re.IGNORECASE)
_FILED_BY = re.compile(r"Document filed by (.+?)\.(?=\s|\(|$)")
_FILING_ATTORNEY = re.compile(r"\(([A-Z][A-Za-z'\-]+, [A-Z][A-Za-z'\-]+)\)")


@dataclass(frozen=True)
class DocketConfig:
    name: str
    court: str
    docket_number: str
    opposing: list[str]


def load_docket_config(path: Path = DEFAULT_DOCKET_CONFIG) -> DocketConfig:
    data = json.loads(path.read_text())
    return DocketConfig(data["name"], data["court"], data["docket_number"], data["opposing"])


def opposing_names(description: str, config: DocketConfig) -> list[str]:
    """Opposing party or counsel names among those who filed a docket entry.

    Only the filer counts: the "Document filed by" clause and the filing
    attorney ECF appends as "(LoDuca, Peter)". Court orders name the parties
    too, so entries signed by a judge or clerk never match.
    """
    if _COURT_ENTRY.search(description):
        return []
    filer = " | ".join(_FILED_BY.findall(description) + _FILING_ATTORNEY.findall(description))
    return [
        name for name in config.opposing
        if re.search(rf"\b{re.escape(name)}\b", filer, re.IGNORECASE)
    ]


def known_docket(conn: sqlite3.Connection, config: DocketConfig) -> Docket | None:
    row = conn.execute(
        "SELECT * FROM dockets WHERE court = ? AND docket_number = ?", (config.court, config.docket_number)
    ).fetchone()
    return Docket(row["court"], row["docket_number"], row["id"], row["case_name"]) if row else None


def resolve_docket(conn: sqlite3.Connection, client: CourtListenerClient, config: DocketConfig) -> Docket:
    """CourtListener's id for the docket, searched once and then kept in the ledger."""
    known = known_docket(conn, config)
    if known is not None:
        return known

    results = client.get_json(
        "search/", {"type": "r", "court": config.court, "docket_number": config.docket_number}
    )["results"]
    matches = [
        r for r in results
        if r.get("court_id") == config.court and _same_docket(r.get("docketNumber", ""), config.docket_number)
    ]
    if len(matches) != 1:
        raise FetchError(
            f"expected one {config.court} docket {config.docket_number}, "
            f"search returned {len(matches)} matches in {len(results)} results"
        )
    found = matches[0]
    with conn:
        conn.execute(
            "INSERT INTO dockets (id, court, docket_number, case_name, resolved_at) VALUES (?, ?, ?, ?, ?)",
            (found["docket_id"], config.court, config.docket_number, found["caseName"], now()),
        )
    return Docket(config.court, config.docket_number, found["docket_id"], found["caseName"])


def poll_entries(conn: sqlite3.Connection, client: CourtListenerClient, docket: Docket) -> list[dict]:
    """Record docket entries created since the last poll and return them."""
    cursor = conn.execute(
        "SELECT MAX(date_created) FROM docket_entries WHERE docket_id = ?", (docket.docket_id,)
    ).fetchone()[0]
    params: dict[str, object] = {
        "docket__id": docket.docket_id,
        "order_by": "entry_number",
        "fields": ENTRY_FIELDS,
    }
    if cursor:
        params["date_created__gt"] = cursor

    new = []
    while True:
        body = client.get_json("docket-entries/", params)
        for result in body["results"]:
            if result.get("entry_number") is None:
                continue
            entry = {k: result.get(k) for k in ENTRY_FIELDS.split(",")}
            entry["description"] = entry["description"] or ""
            new.append(entry)
        if not body.get("next"):
            break
        params = dict(parse_qsl(urlparse(body["next"]).query))

    with conn:
        for entry in new:
            conn.execute(
                "INSERT INTO docket_entries (docket_id, entry_number, date_filed, date_created, description, first_seen_at) "
                "VALUES (?, ?, ?, ?, ?, ?) ON CONFLICT (docket_id, entry_number) DO UPDATE SET "
                "date_created = excluded.date_created, description = excluded.description",
                (docket.docket_id, entry["entry_number"], entry["date_filed"], entry["date_created"],
                 entry["description"], now()),
            )
    return new


def unchecked_opposing_entries(conn: sqlite3.Connection, docket: Docket, config: DocketConfig) -> list[dict]:
    """Opposing entries with no completed check run, oldest first."""
    rows = conn.execute(
        "SELECT e.* FROM docket_entries e "
        "LEFT JOIN filings f ON f.docket_id = e.docket_id AND f.entry_number = e.entry_number "
        "LEFT JOIN runs r ON r.filing_id = f.id AND r.status = 'complete' "
        "WHERE e.docket_id = ? GROUP BY e.entry_number HAVING COUNT(r.id) = 0 ORDER BY e.entry_number",
        (docket.docket_id,),
    ).fetchall()
    return [dict(row) for row in rows if opposing_names(row["description"], config)]


def _same_docket(candidate: str, target: str) -> bool:
    try:
        return normalize_docket_number(candidate) == normalize_docket_number(target)
    except ValueError:
        return False
