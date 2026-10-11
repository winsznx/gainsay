"""Run every check for each citation in a filing.

Existence and identity are decided once per case. Quotation, pincite and
proposition need the opinion text, which is fetched once per CourtListener
cluster.
"""

import json
import sqlite3
from dataclasses import replace

import anthropic

from gainsay.cache import CachedCourtListener
from gainsay.courtlistener import BudgetExhausted, CourtListenerError
from gainsay.existence import Authority, Lookup, check_authority
from gainsay.findings import PASS, UNVERIFIABLE, Finding
from gainsay.opinions import OpinionText, fetch_cluster_opinions
from gainsay.pincite import check_pincite, first_page, parse_pin, pin_reporter
from gainsay.proposition import Judge, check_proposition
from gainsay.quotes import check_quotes

CHECKS = ("existence", "identity", "quotation", "proposition", "pincite")


class Checker:
    def __init__(
        self,
        api: CachedCourtListener,
        authorities: dict[int, Authority],
        citations: list[sqlite3.Row],
        judge: Judge,
    ):
        self._api = api
        self._judge = judge
        self._authorities = authorities
        self._lookup = Lookup(api, list(authorities.values()))
        self._by_authority: dict[int, tuple[Finding, Finding]] = {}
        self._opinions: dict[int, list[OpinionText] | str] = {}
        self._pin_reporters = _pin_reporters(citations, authorities)

    def check(self, citation: sqlite3.Row) -> list[Finding]:
        quotes = json.loads(citation["quotes"])
        pincite = citation["pincite"]
        authority = self._authorities.get(citation["authority_id"])
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
        cluster_id = _cluster_for(existence, identity)
        return [
            existence,
            identity,
            self._quotation(quotes, cluster_id, reporter, existence),
            self._proposition(citation, cluster_id, reporter, existence, identity),
            self._pincite(pincite, cluster_id, reporter, identity),
        ]

    def _case_findings(self, authority: Authority) -> tuple[Finding, Finding]:
        if authority.id not in self._by_authority:
            self._by_authority[authority.id] = check_authority(self._api, self._lookup, authority)
        return self._by_authority[authority.id]

    def _quotation(
        self, quotes: list[str], cluster_id: int | None, reporter: str, existence: Finding
    ) -> Finding:
        if not quotes:
            return check_quotes(quotes, [], None)
        if cluster_id is None:
            return Finding("quotation", UNVERIFIABLE, f"no opinion to compare against: {existence.reason}")
        opinions = self._opinions_for(cluster_id)
        if isinstance(opinions, str):
            return Finding("quotation", UNVERIFIABLE, opinions, {"cluster_id": cluster_id})
        finding = check_quotes(quotes, opinions, first_page(reporter))
        return replace(finding, evidence={**finding.evidence, "cluster_id": cluster_id})

    def _proposition(
        self,
        citation: sqlite3.Row,
        cluster_id: int | None,
        reporter: str,
        existence: Finding,
        identity: Finding,
    ) -> Finding:
        if cluster_id is None:
            return Finding("proposition", UNVERIFIABLE, f"no opinion to compare against: {existence.reason}")
        opinions = self._opinions_for(cluster_id)
        if isinstance(opinions, str):
            return Finding("proposition", UNVERIFIABLE, opinions, {"cluster_id": cluster_id})
        pin = parse_pin(citation["pincite"]) if citation["pincite"] and identity.outcome == PASS else None
        try:
            finding = check_proposition(
                citation["proposition"], opinions, first_page(reporter), pin, self._judge
            )
        except anthropic.RateLimitError:
            raise
        except anthropic.APIError as exc:
            return Finding("proposition", UNVERIFIABLE, f"the model call failed: {exc}", {"cluster_id": cluster_id})
        return replace(finding, evidence={**finding.evidence, "cluster_id": cluster_id})

    def _pincite(
        self, pincite: str | None, cluster_id: int | None, reporter: str, identity: Finding
    ) -> Finding:
        if not pincite:
            return check_pincite(pincite, None, [])
        if identity.outcome != PASS or cluster_id is None:
            return Finding("pincite", UNVERIFIABLE, f"pages can't be checked: {identity.reason}")
        opinions = self._opinions_for(cluster_id)
        if isinstance(opinions, str):
            return Finding("pincite", UNVERIFIABLE, opinions, {"cluster_id": cluster_id})
        finding = check_pincite(pincite, reporter, opinions)
        return replace(finding, evidence={**finding.evidence, "cluster_id": cluster_id})

    def _opinions_for(self, cluster_id: int) -> list[OpinionText] | str:
        """Opinion texts for a cluster, or why there are none."""
        if cluster_id not in self._opinions:
            try:
                opinions = fetch_cluster_opinions(self._api, cluster_id)
            except BudgetExhausted:
                raise
            except CourtListenerError as exc:
                self._opinions[cluster_id] = f"could not fetch opinion text: {exc}"
            else:
                self._opinions[cluster_id] = opinions or f"CourtListener has no opinion text for cluster {cluster_id}"
        return self._opinions[cluster_id]


def _cluster_for(existence: Finding, identity: Finding) -> int | None:
    """The cluster holding the named case: the one the cite resolved to, else a name-search hit."""
    if identity.outcome == PASS:
        return identity.evidence["cluster"]["cluster_id"]
    if existence.outcome == PASS and existence.evidence.get("source") == "search":
        return existence.evidence["candidates"][0]["cluster_id"]
    return None


def _pin_reporters(citations: list[sqlite3.Row], authorities: dict[int, Authority]) -> dict[int, str | None]:
    reporters: dict[int, str | None] = {}
    previous = None
    for citation in citations:
        authority = authorities.get(citation["authority_id"])
        cites = authority.reporter_cites if authority else []
        previous = pin_reporter(citation["kind"], citation["cite_text"], cites, previous)
        reporters[citation["id"]] = previous
    return reporters

