"""Run every check for each citation in a filing.

Existence and identity are decided once per case. Quotation, pincite and
proposition need the opinion text, which is read once per case: from the
Caselaw Access Project when it holds the case, since that costs no quota,
and from CourtListener otherwise. Each finding records where its text came
from.
"""

import json
import sqlite3
from dataclasses import dataclass, replace

import anthropic

from gainsay.cache import CachedCourtListener
from gainsay.cap import STARTS, Cap, CapCase, CapError
from gainsay.courtlistener import BudgetExhausted, CourtListenerError
from gainsay.existence import Authority, Lookup, check_authority, check_untied_short
from gainsay.findings import FAIL, NOT_APPLICABLE, PASS, UNVERIFIABLE, Finding
from gainsay.names import names_match
from gainsay.opinions import OpinionText, fetch_cluster_opinions
from gainsay.pincite import check_pincite, first_page, parse_pin, pin_reporter
from gainsay.proposition import Judge, check_proposition
from gainsay.quotes import check_quotes

CHECKS = ("existence", "identity", "quotation", "proposition", "pincite")


@dataclass(frozen=True)
class TextSource:
    """Where a case's text can be read: a CourtListener cluster, a CAP case, or both."""

    cluster_id: int | None = None
    cites: tuple[str, ...] = ()
    case_name: str = ""
    cap_case: CapCase | None = None


class Checker:
    def __init__(
        self,
        api: CachedCourtListener,
        authorities: dict[int, Authority],
        citations: list[sqlite3.Row],
        judge: Judge,
        cap: Cap | None = None,
        lookup: Lookup | None = None,
    ):
        self._api = api
        self._cap = cap
        self._judge = judge
        self._authorities = authorities
        self._lookup = lookup or Lookup(api, list(authorities.values()))
        self._by_authority: dict[int, tuple[Finding, Finding]] = {}
        self._texts: dict[TextSource, tuple[list[OpinionText], dict] | str] = {}
        self._pin_reporters = _pin_reporters(citations, authorities)

    def check(self, citation: sqlite3.Row) -> list[Finding]:
        quotes = json.loads(citation["quotes"])
        pincite = citation["pincite"]
        authority = self._authorities.get(citation["authority_id"])
        if authority is None and citation["kind"] == "short" and self._cap is not None:
            existence, identity, case = check_untied_short(self._cap, citation["cite_text"])
            if case is not None:
                source = TextSource(cap_case=case)
                return [
                    existence,
                    identity,
                    self._quotation(quotes, source, case.cite, existence),
                    self._proposition(citation, source, case.cite, existence, identity),
                    self._pincite(pincite, source, case.cite, identity),
                ]
            if identity.outcome == FAIL:
                reason = f"pages can't be checked: {identity.reason}"
                return [
                    existence,
                    identity,
                    check_quotes(quotes, [], None) if not quotes else Finding("quotation", UNVERIFIABLE, reason),
                    Finding("proposition", UNVERIFIABLE, reason),
                    check_pincite(pincite, None, []) if not pincite else Finding("pincite", UNVERIFIABLE, reason),
                ]
        if authority is None:
            reason = "short citation could not be tied to a full citation in this filing"
            return [
                Finding("existence", UNVERIFIABLE, reason),
                Finding("identity", UNVERIFIABLE, reason),
                check_quotes(quotes, [], None) if not quotes else Finding("quotation", UNVERIFIABLE, reason),
                Finding("proposition", UNVERIFIABLE, reason),
                check_pincite(pincite, None, []) if not pincite else Finding("pincite", UNVERIFIABLE, reason),
            ]

        existence, identity = self._case_findings(authority)
        reporter = self._pin_reporters.get(citation["id"]) or authority.reporter_cites[0]
        source = _source_for(existence, identity)
        if citation["kind"] == "history":
            reason = "subsequent history: the filing's statement rests on the decision cited before it"
            return [
                existence,
                identity,
                Finding("quotation", NOT_APPLICABLE, reason),
                Finding("proposition", NOT_APPLICABLE, reason),
                self._pincite(citation["pincite"], source, reporter, identity),
            ]
        quotation = self._quotation(quotes, source, reporter, existence)
        return [
            existence,
            identity,
            quotation,
            self._proposition(citation, source, reporter, existence, identity),
            self._pincite(pincite, source, reporter, identity, quotation),
        ]

    def _case_findings(self, authority: Authority) -> tuple[Finding, Finding]:
        if authority.id not in self._by_authority:
            self._by_authority[authority.id] = check_authority(self._api, self._lookup, authority, self._cap)
        return self._by_authority[authority.id]

    def _quotation(
        self, quotes: list[str], source: TextSource | None, reporter: str, existence: Finding
    ) -> Finding:
        if not quotes:
            return check_quotes(quotes, [], None)
        if source is None:
            return Finding("quotation", UNVERIFIABLE, f"no opinion to compare against: {existence.reason}")
        text = self._text_for(source)
        if isinstance(text, str):
            return Finding("quotation", UNVERIFIABLE, text, _source_evidence(source))
        opinions, provenance = text
        finding = check_quotes(quotes, opinions, first_page(reporter))
        return replace(finding, evidence={**finding.evidence, **provenance})

    def _proposition(
        self,
        citation: sqlite3.Row,
        source: TextSource | None,
        reporter: str,
        existence: Finding,
        identity: Finding,
    ) -> Finding:
        if source is None:
            return Finding("proposition", UNVERIFIABLE, f"no opinion to compare against: {existence.reason}")
        text = self._text_for(source)
        if isinstance(text, str):
            return Finding("proposition", UNVERIFIABLE, text, _source_evidence(source))
        opinions, provenance = text
        pin = parse_pin(citation["pincite"]) if citation["pincite"] and identity.outcome == PASS else None
        try:
            finding = check_proposition(
                citation["proposition"], opinions, first_page(reporter), pin, self._judge,
                _column(citation, "signal"), _column(citation, "parenthetical"),
            )
        except anthropic.RateLimitError:
            raise
        except anthropic.APIError as exc:
            return Finding("proposition", UNVERIFIABLE, f"the model call failed: {exc}", provenance)
        return replace(finding, evidence={**finding.evidence, **provenance})

    def _pincite(
        self,
        pincite: str | None,
        source: TextSource | None,
        reporter: str,
        identity: Finding,
        quotation: Finding | None = None,
    ) -> Finding:
        if not pincite:
            return check_pincite(pincite, None, [])
        if identity.outcome != PASS or source is None:
            return Finding("pincite", UNVERIFIABLE, f"pages can't be checked: {identity.reason}")
        text = self._text_for(source)
        if isinstance(text, str):
            return Finding("pincite", UNVERIFIABLE, text, _source_evidence(source))
        opinions, provenance = text
        finding = check_pincite(pincite, reporter, opinions, _quote_pages(quotation))
        return replace(finding, evidence={**finding.evidence, **provenance})

    def _text_for(self, source: TextSource) -> tuple[list[OpinionText], dict] | str:
        """The case's opinions and where they were read, or why there are none."""
        if source not in self._texts:
            self._texts[source] = self._read_text(source)
        return self._texts[source]

    def _read_text(self, source: TextSource) -> tuple[list[OpinionText], dict] | str:
        provenance = _source_evidence(source)
        cap_case, cap_error = (source.cap_case, None) if source.cap_case else self._cap_copy(source)
        if cap_case is not None:
            try:
                opinions = self._cap.opinions(cap_case)
            except CapError as exc:
                cap_error = str(exc)
            else:
                if opinions:
                    return opinions, {**provenance, "text_source": "cap", "cap_url": cap_case.url}
                cap_error = f"{cap_case.url} has no opinion text"
        if cap_error:
            provenance["cap_error"] = cap_error
        if source.cluster_id is None:
            return f"could not read the case from the Caselaw Access Project: {cap_error}"
        try:
            opinions = fetch_cluster_opinions(self._api, source.cluster_id)
        except BudgetExhausted:
            raise
        except CourtListenerError as exc:
            return f"could not fetch opinion text: {exc}"
        if not opinions:
            return f"CourtListener has no opinion text for cluster {source.cluster_id}"
        return opinions, {**provenance, "text_source": "courtlistener"}

    def _cap_copy(self, source: TextSource) -> tuple[CapCase | None, str | None]:
        """CAP's copy of a CourtListener cluster: the case starting at one of the cluster's own cites.

        One case starting at that page is the same decision, whatever its caption
        ("In re Air Crash Disaster" is "Trivelloni-Lorenzi v. Pan American" in CAP).
        Several short decisions can share a page; then the name has to match.
        """
        if self._cap is None:
            return None, None
        try:
            for cite in source.cites:
                answer = self._cap.lookup(cite)
                if answer.status != STARTS:
                    continue
                if len(answer.cases) == 1:
                    return answer.cases[0], None
                case = next(
                    (c for c in answer.cases
                     if names_match(source.case_name, c.name) or names_match(source.case_name, c.full_name)),
                    None,
                )
                if case:
                    return case, None
        except CapError as exc:
            return None, str(exc)
        return None, None


def _column(citation, name: str) -> str | None:
    """A citation column a ledger from before it was added doesn't have."""
    try:
        return citation[name]
    except (KeyError, IndexError):
        return None


def _quote_pages(quotation: Finding | None) -> list[int]:
    """Pages where a passing quotation check found the quoted words."""
    if quotation is None or quotation.outcome != PASS:
        return []
    return [m["page"] for m in quotation.evidence.get("passages", []) if m.get("page") is not None]


def _source_for(existence: Finding, identity: Finding) -> TextSource | None:
    """Where the named case's text is: the case the cite resolved to, else a name-search hit."""
    if identity.outcome == PASS:
        if "cap_case" in identity.evidence:
            return TextSource(cap_case=_cap_case(identity.evidence["cap_case"]))
        cluster = identity.evidence["cluster"]
        return TextSource(cluster["cluster_id"], tuple(cluster.get("citations") or ()), cluster.get("case_name") or "")
    if existence.outcome == PASS and existence.evidence.get("source") == "search":
        found = existence.evidence["candidates"][0]
        return TextSource(found["cluster_id"], tuple(found.get("citations") or ()), found.get("case_name") or "")
    return None


def _cap_case(summary: dict) -> CapCase:
    return CapCase(**{k: v for k, v in summary.items() if k != "url"})


def _source_evidence(source: TextSource) -> dict:
    if source.cap_case is not None:
        return {"cap_url": source.cap_case.url}
    return {"cluster_id": source.cluster_id}


def _pin_reporters(citations: list[sqlite3.Row], authorities: dict[int, Authority]) -> dict[int, str | None]:
    reporters: dict[int, str | None] = {}
    previous = None
    for citation in citations:
        authority = authorities.get(citation["authority_id"])
        cites = authority.reporter_cites if authority else []
        previous = pin_reporter(citation["kind"], citation["cite_text"], cites, previous)
        reporters[citation["id"]] = previous
    return reporters

