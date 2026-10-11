"""Existence and identity: is the cited case real, and is it where the cite says?

All reporter cites in a filing go to CourtListener's citation lookup in one
request. A cite that resolves to a case with the cited name passes both checks.
Otherwise the case is searched by name, court and year, and a hit only counts
if its court belongs to the system (federal or state) of the cited reporter:

- existence passes if either path finds the named case, and fails if neither does.
- identity fails if the cite resolves to a differently named case. It is
  unverifiable if the cite resolves to nothing, since an empty page in
  CourtListener isn't proof the cite is wrong.
"""

from dataclasses import dataclass
from typing import Any

from gainsay.cache import CachedCourtListener
from gainsay.courtlistener import BudgetExhausted, CourtListenerError
from gainsay.findings import FAIL, PASS, UNVERIFIABLE, Finding
from gainsay.jurisdiction import court_system_fits
from gainsay.names import names_match, parties

LOOKUP_PATH = "citation-lookup/"
SEARCH_PATH = "search/"
YEAR_TOLERANCE = 1
MAX_CITES_PER_LOOKUP = 250
EVIDENCE_CANDIDATES = 5

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


class Lookup:
    """Citation lookup results for one filing, keyed by normalized cite."""

    def __init__(self, api: CachedCourtListener, authorities: list[Authority]):
        cites = list(dict.fromkeys(c for a in authorities for c in a.reporter_cites))
        self.results: dict[str, dict] = {}
        self.response_ids: list[int | None] = []
        for start in range(0, len(cites), MAX_CITES_PER_LOOKUP):
            data = {"text": "; ".join(cites[start : start + MAX_CITES_PER_LOOKUP])}
            for result in api.post_json(LOOKUP_PATH, data):
                for cite in result.get("normalized_citations") or [result["citation"]]:
                    self.results[cite] = result
            self.response_ids.append(api.response_id("POST", LOOKUP_PATH, data))


def check_authority(
    api: CachedCourtListener, lookup: Lookup, authority: Authority
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
    for cite, cluster in resolved:
        matched_name = _matched_name(authority.case_name, cluster)
        if matched_name:
            evidence = {**lookup_evidence, "cite": cite, "cluster": _cluster_summary(cluster)}
            reason = f"{cite} resolves to {_shorten(matched_name)} ({cluster.get('date_filed')})"
            return Finding("existence", PASS, reason, evidence), Finding("identity", PASS, reason, evidence)

    if resolved:
        others = [_cluster_summary(c) for _, c in resolved]
        identity = Finding(
            "identity",
            FAIL,
            f"{', '.join(dict.fromkeys(cite for cite, _ in resolved))} resolves to "
            f"{'; '.join(o['case_name'] for o in others)}, not {authority.case_name}",
            {**lookup_evidence, "clusters": others},
        )
    else:
        identity = Finding(
            "identity",
            UNVERIFIABLE,
            "; ".join(_UNRESOLVED_REASONS.get(s, _UNRESOLVED_REASONS[None]).format(cite=c)
                      for c, s in statuses.items()),
            lookup_evidence,
        )
    return _search_by_name(api, authority), identity


def _search_by_name(api: CachedCourtListener, authority: Authority) -> Finding:
    cited_parties = [p for p in parties(authority.case_name) if p]
    if not cited_parties:
        return Finding(
            "existence",
            UNVERIFIABLE,
            f"{authority.case_name!r} has no distinctive party name to search for",
        )
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
        return Finding("existence", UNVERIFIABLE, f"CourtListener search failed: {exc}", {"query": params})
    matches = [
        r for r in results
        if names_match(authority.case_name, r.get("caseName", ""))
        and _year_fits(year, r.get("dateFiled"))
        and court_system_fits(authority.reporter_cites, r.get("court_id"))
    ]
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
        )
    return Finding(
        "existence",
        FAIL,
        f"no case named {authority.case_name}{f' ({where})' if where else ''} "
        f"in CourtListener search; {len(results)} result{'' if len(results) == 1 else 's'} checked",
        evidence,
    )


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
