"""Existence and identity: is the cited case real, and is it where the cite says?

All reporter cites in a filing go to CourtListener's citation lookup in one
request. A cite that resolves to a case with the cited name passes both checks.
Otherwise the case is searched by name, court and year:

- existence passes if either path finds the named case, and fails if neither does.
- identity fails if the cite resolves to a differently named case, or if the
  named case turns up somewhere the cite can't point: in the other court
  system (a federal case cited to a state reporter), or in the same reporter
  at a different page. Otherwise a cite that resolves to nothing is
  unverifiable, since an empty page in CourtListener isn't proof the cite is
  wrong.

A cite CourtListener can't resolve is also read from the Caselaw Access
Project's volume list, which costs no quota. The named case starting at the
cited page passes both checks without a name search. A different case there,
or a page that falls inside another case, fails identity: CAP lists every
case in the volumes it holds.
"""

import logging
import re
import time
from dataclasses import dataclass
from typing import Any, Callable

from gainsay.cache import CachedCourtListener
from gainsay.cap import EMPTY, INSIDE, STARTS, Cap, CapAnswer, CapCase, CapError
from gainsay.courtlistener import BudgetExhausted, CourtListenerError
from gainsay.findings import FAIL, PASS, UNVERIFIABLE, Finding
from gainsay.jurisdiction import court_system_fits
from gainsay.names import names_match, parties

logger = logging.getLogger(__name__)

LOOKUP_PATH = "citation-lookup/"
SEARCH_PATH = "search/"
YEAR_TOLERANCE = 1
# CourtListener looks up 60 valid citations a minute; more in one minute is a 429.
MAX_CITES_PER_LOOKUP = 60
LOOKUP_INTERVAL_SECONDS = 62
EVIDENCE_CANDIDATES = 5

_DATABASE_CITE = re.compile(r"\b(?:WL|LEXIS)\b")
_OUTSIDE_FREE_SOURCES = "{cite} is outside free sources: CourtListener can't see Westlaw or Lexis cites"

_UNRESOLVED_REASONS = {
    404: "CourtListener has no case at {cite}",
    400: "CourtListener does not index the reporter in {cite}",
    None: "CourtListener did not recognize {cite} as a citation",
}


@dataclass(frozen=True)
class Authority:
    id: int
    case_name: str
    reporter_cites: list[str]
    year: str | None
    court: str | None
    docket_number: str | None = None
    invented_reporter: str | None = None


class Lookup:
    """Citation lookup results for one filing, keyed by normalized cite."""

    def __init__(
        self,
        api: CachedCourtListener,
        authorities: list[Authority],
        pause: Callable[[float], None] = time.sleep,
    ):
        cites = list(dict.fromkeys(c for a in authorities if not a.invented_reporter for c in a.reporter_cites))
        self.results: dict[str, dict] = {}
        self.response_ids: list[int | None] = []
        for start in range(0, len(cites), MAX_CITES_PER_LOOKUP):
            data = {"text": "; ".join(cites[start : start + MAX_CITES_PER_LOOKUP])}
            if start and api.response_id("POST", LOOKUP_PATH, data) is None:
                logger.warning("citation lookup takes 60 citations a minute, waiting %ss", LOOKUP_INTERVAL_SECONDS)
                pause(LOOKUP_INTERVAL_SECONDS)
            for result in api.post_json(LOOKUP_PATH, data):
                for cite in result.get("normalized_citations") or [result["citation"]]:
                    self.results[cite] = result
            self.response_ids.append(api.response_id("POST", LOOKUP_PATH, data))


def check_authority(
    api: CachedCourtListener, lookup: Lookup, authority: Authority, cap: Cap | None = None
) -> tuple[Finding, Finding]:
    statuses: dict[str, int | None] = {}
    resolved: list[tuple[str, dict]] = []
    for cite in authority.reporter_cites:
        result = lookup.results.get(cite)
        statuses[cite] = result["status"] if result else None
        if result and result["status"] in (200, 300):
            resolved.extend((cite, cluster) for cluster in result["clusters"])

    lookup_evidence = {
        "source": "citation-lookup",
        "statuses": statuses,
        "api_response_ids": lookup.response_ids,
    }
    if authority.invented_reporter:
        reason = f"{', '.join(authority.reporter_cites)}: {authority.invented_reporter}"
        evidence = {"source": "reporters-db", "reason": authority.invented_reporter}
        return Finding("existence", FAIL, reason, evidence), Finding("identity", UNVERIFIABLE, reason, evidence)
    if not authority.case_name.strip():
        return _nameless(authority, resolved, statuses, lookup_evidence, cap)
    for cite, cluster in resolved:
        matched_name = _matched_name(authority.case_name, cluster)
        if matched_name:
            evidence = {**lookup_evidence, "cite": cite, "cluster": _cluster_summary(cluster)}
            reason = f"{cite} resolves to {_shorten(matched_name)} ({cluster.get('date_filed')})"
            return Finding("existence", PASS, reason, evidence), Finding("identity", PASS, reason, evidence)

    cap_answers, cap_error = _ask_cap(cap, authority.reporter_cites)
    if cap_error:
        lookup_evidence = {**lookup_evidence, "cap_error": cap_error}
    for answer in cap_answers:
        case = next((c for c in answer.cases if answer.status == STARTS and _cap_names_match(authority, c)), None)
        if case:
            evidence = {**lookup_evidence, "source": "cap", "cap": answer.evidence(), "cap_case": case.summary()}
            reason = f"{answer.cite} is {_shorten(case.name)} ({case.decision_date}) in the Caselaw Access Project"
            return Finding("existence", PASS, reason, evidence), Finding("identity", PASS, reason, evidence)

    existence, found = _search_by_name(api, authority)
    if existence.outcome == FAIL and authority.docket_number and authority.court:
        existence = _docket_exists(api, authority) or existence
    if existence.outcome == FAIL and _only_database_cites(authority):
        # Not finding a Westlaw or Lexis case in free sources proves nothing,
        # so it stays unresolved rather than becoming "Not found".
        existence = Finding(
            "existence",
            UNVERIFIABLE,
            f"{_OUTSIDE_FREE_SOURCES.format(cite=', '.join(authority.reporter_cites))}, "
            f"and {existence.reason}",
            existence.evidence,
        )
    shared_page = found is not None and set(authority.reporter_cites) & set(found.get("citation") or [])
    if resolved and shared_page:
        # Several short decisions can share a page; the lookup returned another one.
        identity = Finding(
            "identity",
            PASS,
            f"{', '.join(authority.reporter_cites)} holds more than one decision, and "
            f"{_shorten(found['caseName'])} is reported there",
            {**lookup_evidence, "found": _search_summary(found)},
        )
    elif resolved:
        others = [_cluster_summary(c) for _, c in resolved]
        identity = Finding(
            "identity",
            FAIL,
            f"{', '.join(dict.fromkeys(cite for cite, _ in resolved))} resolves to "
            f"{'; '.join(o['case_name'] for o in others)}, not {authority.case_name}",
            {**lookup_evidence, "clusters": others},
        )
    elif found is not None and _reported_elsewhere(authority, found):
        cites = ", ".join(found.get("citation") or []) or f"{found.get('court_id')}, {found.get('dateFiled')}"
        identity = Finding(
            "identity",
            FAIL,
            f"nothing at {', '.join(authority.reporter_cites)}; "
            f"{_shorten(found['caseName'])} is reported at {cites}",
            {**lookup_evidence, "found": _search_summary(found)},
        )
    elif contradictions := [r for a in cap_answers if (r := _cap_contradiction(authority, a))]:
        identity = Finding(
            "identity",
            FAIL,
            "; ".join(contradictions),
            {**lookup_evidence, "cap": [a.evidence() for a in cap_answers]},
        )
    else:
        reasons = [_unresolved_reason(c, s) for c, s in statuses.items()]
        if cap_error:
            reasons.append(f"the Caselaw Access Project could not be read: {cap_error}")
        identity = Finding("identity", UNVERIFIABLE, "; ".join(reasons), lookup_evidence)
    return existence, identity


def _ask_cap(cap: Cap | None, cites: list[str]) -> tuple[list[CapAnswer], str | None]:
    if cap is None:
        return [], None
    try:
        return [cap.lookup(cite) for cite in cites], None
    except CapError as exc:
        return [], str(exc)


def _cap_names_match(authority: Authority, case: CapCase) -> bool:
    return names_match(authority.case_name, case.name) or names_match(authority.case_name, case.full_name)


def _cap_contradiction(authority: Authority, answer: CapAnswer) -> str | None:
    """Why CAP shows the cite doesn't point at the named case, if it does."""
    if answer.status == STARTS:
        names = "; ".join(_shorten(c.name) for c in answer.cases)
        return f"{answer.cite} is {names} in the Caselaw Access Project, not {authority.case_name}"
    if answer.status == INSIDE:
        case = answer.cases[0]
        return (
            f"no case begins at {answer.cite} in the Caselaw Access Project; that page is inside "
            f"{_shorten(case.name)}, {case.cite} (pages {case.first_page}-{case.last_page})"
        )
    if answer.status == EMPTY:
        return f"the Caselaw Access Project's volume holds no case at {answer.cite}"
    return None


def _only_database_cites(authority: Authority) -> bool:
    return bool(authority.reporter_cites) and all(_DATABASE_CITE.search(c) for c in authority.reporter_cites)


def _unresolved_reason(cite: str, status: int | None) -> str:
    if _DATABASE_CITE.search(cite):
        return _OUTSIDE_FREE_SOURCES.format(cite=cite)
    return _UNRESOLVED_REASONS.get(status, _UNRESOLVED_REASONS[None]).format(cite=cite)


def _docket_exists(api: CachedCourtListener, authority: Authority) -> Finding | None:
    """Existence from the RECAP docket the filing cites, when no opinion turned up.

    Unpublished district court orders are often cited only to Westlaw with a
    docket number. CourtListener may hold the docket without the opinion. A
    docket number already pins the case within its court, so the caption only
    has to share a party word with the cited name: derivative suits are
    captioned under the shareholder ("Braun v. Fu") but cited under the
    company ("Advanced Battery Techs., Inc. v. Zhiguo Fu").
    """
    params = {"type": "r", "court": authority.court, "docket_number": authority.docket_number}
    try:
        results = api.get_json(SEARCH_PATH, params)["results"]
    except BudgetExhausted:
        raise
    except CourtListenerError:
        return None
    cited_words = {w for party in parties(authority.case_name) for w in party}
    match = next(
        (r for r in results
         if authority.docket_number in (r.get("docketNumber") or "").lower()
         and cited_words & {w for party in parties(r.get("caseName", "")) for w in party}),
        None,
    )
    if match is None:
        return None
    return Finding(
        "existence",
        PASS,
        f"no opinion in CourtListener, but RECAP has docket {match['docketNumber']} "
        f"({match.get('court_id')}): {_shorten(match['caseName'])}",
        {
            "source": "recap-docket",
            "query": params,
            "docket": {
                "docket_id": match.get("docket_id"),
                "case_name": match.get("caseName"),
                "docket_number": match.get("docketNumber"),
                "court_id": match.get("court_id"),
                "absolute_url": match.get("absolute_url"),
            },
            "api_response_id": api.response_id("GET", SEARCH_PATH, params),
        },
    )


def _nameless(
    authority: Authority,
    resolved: list[tuple[str, dict]],
    statuses: dict[str, int | None],
    lookup_evidence: dict,
    cap: Cap | None = None,
) -> tuple[Finding, Finding]:
    """A cite the filing gives without a case name can't be matched by name."""
    no_name = "the filing gives no case name for this cite"
    if resolved:
        cite, cluster = resolved[0]
        evidence = {**lookup_evidence, "cite": cite, "cluster": _cluster_summary(cluster)}
        name = _shorten(cluster.get("case_name") or cluster.get("case_name_full") or "a case")
        return (
            Finding("existence", PASS, f"{cite} resolves to {name} ({cluster.get('date_filed')})", evidence),
            Finding("identity", UNVERIFIABLE, f"{no_name}, so {name} can't be compared", evidence),
        )
    cap_answers, _ = _ask_cap(cap, authority.reporter_cites)
    starting = next((a for a in cap_answers if a.status == STARTS), None)
    if starting:
        case = starting.cases[0]
        evidence = {**lookup_evidence, "source": "cap", "cap": starting.evidence(), "cap_case": case.summary()}
        name = _shorten(case.name)
        found = f"{starting.cite} is {name} ({case.decision_date}) in the Caselaw Access Project"
        return (
            Finding("existence", PASS, found, evidence),
            Finding("identity", UNVERIFIABLE, f"{no_name}, so {name} can't be compared", evidence),
        )
    unresolved = "; ".join(_unresolved_reason(c, s) for c, s in statuses.items())
    reason = f"{no_name} and {unresolved}"
    return Finding("existence", UNVERIFIABLE, reason, lookup_evidence), Finding("identity", UNVERIFIABLE, reason, lookup_evidence)


def _reported_elsewhere(authority: Authority, found: dict) -> bool:
    """CourtListener shows the named case where the cite can't point.

    Either its court is in the other system from the cited reporter, or it is
    reported in the same reporter at a different volume or page. A case that
    simply lacks the cited reporter in CourtListener proves nothing.
    """
    if not court_system_fits(authority.reporter_cites, found.get("court_id")):
        return True
    found_cites = found.get("citation") or []
    return any(
        _reporter(found_cite) == _reporter(cite) and found_cite != cite
        for cite in authority.reporter_cites
        for found_cite in found_cites
    )


def _reporter(cite: str) -> str:
    parts = cite.split(" ")
    return " ".join(parts[1:-1])


def _search_by_name(api: CachedCourtListener, authority: Authority) -> tuple[Finding, dict | None]:
    """Existence by name, court and year, plus the case found, if any.

    A hit in the other court system still shows a case by that name exists;
    identity then decides whether the cite points at it.
    """
    cited_parties = [p for p in parties(authority.case_name) if p]
    if not cited_parties:
        return Finding(
            "existence",
            UNVERIFIABLE,
            f"{authority.case_name!r} has no distinctive party name to search for",
        ), None
    terms = cited_parties[0][:3] if len(cited_parties) == 1 else [p[0] for p in cited_parties]
    params: dict[str, Any] = {"type": "o", "q": f"caseName:({' AND '.join(terms)})"}
    if authority.court:
        params["court"] = authority.court
    year = int(authority.year) if authority.year and authority.year.isdigit() else None
    if year:
        params["filed_after"] = f"{year - YEAR_TOLERANCE}-01-01"
        params["filed_before"] = f"{year + YEAR_TOLERANCE}-12-31"

    try:
        results = api.get_json(SEARCH_PATH, params)["results"]
    except BudgetExhausted:
        raise
    except CourtListenerError as exc:
        return Finding("existence", UNVERIFIABLE, f"CourtListener search failed: {exc}", {"query": params}), None
    named = [
        r for r in results
        if names_match(authority.case_name, r.get("caseName", "")) and _year_fits(year, r.get("dateFiled"))
    ]
    matches = sorted(named, key=lambda r: not court_system_fits(authority.reporter_cites, r.get("court_id")))
    evidence = {
        "source": "search",
        "query": params,
        "result_count": len(results),
        "candidates": [_search_summary(r) for r in (matches or results)[:EVIDENCE_CANDIDATES]],
        "api_response_id": api.response_id("GET", SEARCH_PATH, params),
    }
    where = ", ".join(str(v) for v in (authority.court, authority.year) if v)
    if matches:
        found = matches[0]
        return Finding(
            "existence",
            PASS,
            f"found {_shorten(found['caseName'])} ({found.get('court_id')}, {found.get('dateFiled')}) "
            "by name search",
            evidence,
        ), found
    return Finding(
        "existence",
        FAIL,
        f"no case named {authority.case_name}{f' ({where})' if where else ''} "
        f"in CourtListener search; {len(results)} result{'' if len(results) == 1 else 's'} checked",
        evidence,
    ), None


def _matched_name(case_name: str, cluster: dict) -> str | None:
    names = (cluster.get(k) for k in ("case_name", "case_name_full", "case_name_short"))
    return next((n for n in names if n and names_match(case_name, n)), None)


def _shorten(name: str, limit: int = 120) -> str:
    return name if len(name) <= limit else name[: limit - 3].rstrip() + "..."


def _year_fits(year: int | None, date_filed: str | None) -> bool:
    if year is None or not date_filed:
        return True
    return abs(int(date_filed[:4]) - year) <= YEAR_TOLERANCE


def _cluster_summary(cluster: dict) -> dict:
    return {
        "cluster_id": cluster.get("id"),
        "case_name": cluster.get("case_name") or cluster.get("case_name_full"),
        "date_filed": cluster.get("date_filed"),
        "absolute_url": cluster.get("absolute_url"),
        "citations": [
            f"{c['volume']} {c['reporter']} {c['page']}" for c in cluster.get("citations", [])
        ],
        "sub_opinions": cluster.get("sub_opinions", []),
    }


def _search_summary(result: dict) -> dict:
    return {
        "cluster_id": result.get("cluster_id"),
        "case_name": result.get("caseName"),
        "court_id": result.get("court_id"),
        "date_filed": result.get("dateFiled"),
        "citations": result.get("citation", []),
        "absolute_url": result.get("absolute_url"),
        "opinion_ids": [o.get("id") for o in result.get("opinions", [])],
    }
