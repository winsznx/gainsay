import json

from gainsay.checker import Checker
from gainsay.existence import Authority
from gainsay.findings import FAIL, NOT_APPLICABLE, PASS, UNVERIFIABLE

KAISER = Authority(1, "Kaiser Steel Corp. v. W.S. Ranch Co.", ["391 U.S. 593", "88 S. Ct. 1753"], "1968", "scotus")
VARGHESE = Authority(2, "Varghese v. China Southern Airlines Co., Ltd.", ["925 F.3d 1339"], "2019", "ca11")

KAISER_CLUSTER = {
    "id": 107720,
    "case_name": "Kaiser Steel Corp. v. W. S. Ranch Co.",
    "date_filed": "1968-05-27",
    "citations": [],
    "sub_opinions": [],
}
KAISER_OPINION = (
    "<p>The tolling effect of the automatic stay is a matter of federal law."
    '<page-number label="594">*594</page-number> The question is one of state law.'
    '<page-number label="595">*595</page-number> Reversed.</p>'
)


class FakeApi:
    def __init__(self):
        self.opinion_requests = 0

    def post_json(self, path, data):
        return [
            {"citation": "391 U.S. 593", "normalized_citations": ["391 U.S. 593"], "status": 200, "clusters": [KAISER_CLUSTER]},
            {"citation": "925 F.3d 1339", "normalized_citations": ["925 F.3d 1339"], "status": 404, "clusters": []},
        ]

    def get_json(self, path, params):
        if path == "opinions/":
            self.opinion_requests += 1
            return {"results": [{"id": 9, "type": "020lead", "xml_harvard": KAISER_OPINION}], "next": None}
        return {"results": []}

    def response_id(self, method, path, params):
        return 1


def citation(id, authority_id, kind, cite_text, pincite=None, quotes=()):
    return {
        "id": id,
        "authority_id": authority_id,
        "kind": kind,
        "cite_text": cite_text,
        "pincite": pincite,
        "quotes": json.dumps(list(quotes)),
        "proposition": "The question is one of state law.",
    }


CITATIONS = [
    citation(1, 1, "full", "Kaiser Steel Corp. v. W.S. Ranch Co., 391 U.S. 593, 598 (1968)", "598"),
    citation(
        2, 1, "full", "Kaiser Steel Corp. v. W.S. Ranch Co., 391 U.S. 593, 594 (1968)", "594",
        ["the question is one of state law"],
    ),
    citation(3, 2, "full", "Varghese v. China Southern Airlines Co., Ltd., 925 F.3d 1339 (11th Cir. 2019)",
             quotes=["the limitations period was tolled during the bankruptcy"]),
]


def judge(system, user):
    return {
        "id": "msg_1",
        "model": "claude-opus-5-5",
        "stop_reason": "end_turn",
        "verdict": {"verdict": "supports", "passage_ids": ["P1"], "reason": "r"},
    }


def outcomes(findings):
    return {f.check: f.outcome for f in findings}


def test_checks_each_citation_and_fetches_each_cluster_once():
    api = FakeApi()
    checker = Checker(api, {1: KAISER, 2: VARGHESE}, CITATIONS, judge)

    past_the_end, quoted, not_found = (checker.check(c) for c in CITATIONS)

    assert outcomes(past_the_end) == {
        "existence": PASS, "identity": PASS, "quotation": NOT_APPLICABLE, "proposition": PASS, "pincite": FAIL,
    }
    assert outcomes(quoted) == {
        "existence": PASS, "identity": PASS, "quotation": PASS, "proposition": PASS, "pincite": PASS,
    }
    assert "page 594" in quoted[2].reason
    assert outcomes(not_found) == {
        "existence": FAIL, "identity": UNVERIFIABLE, "quotation": UNVERIFIABLE,
        "proposition": UNVERIFIABLE, "pincite": NOT_APPLICABLE,
    }
    assert api.opinion_requests == 1


def test_subsequent_history_skips_quotation_and_proposition():
    history = {**citation(4, 1, "history", "aff'd, 88 S. Ct. 1753 (1968)"), "quotes": json.dumps(["a quote here at length"])}
    findings = Checker(FakeApi(), {1: KAISER, 2: VARGHESE}, CITATIONS + [history], judge).check(history)
    assert outcomes(findings)["quotation"] == NOT_APPLICABLE
    assert outcomes(findings)["proposition"] == NOT_APPLICABLE
    assert "subsequent history" in findings[3].reason


from gainsay.cap import NOT_COVERED, STARTS, CapAnswer, CapCase, CapError
from gainsay.opinions import parse_opinion_html

KAISER_CAP = CapCase(
    1, "Kaiser Steel Corp. v. W. S. Ranch Co.", "Kaiser Steel Corp. v. W. S. Ranch Co.", "1968-05-27",
    "U.S.", "391 U.S. 593", 593, 595, "us", "391", "0593-01",
)
CAP_TEXT = (
    "<p>The tolling effect of the automatic stay is a matter of federal law. "
    '<a class="page-label" data-label="594">*594</a> The question is one of state law.</p>'
)


class FakeCap:
    def __init__(self, answers, fail_text=False):
        self.answers = answers
        self.fail_text = fail_text
        self.texts_read = 0

    def lookup(self, cite):
        return self.answers.get(cite, CapAnswer(cite, NOT_COVERED))

    def opinions(self, case):
        if self.fail_text:
            raise CapError(f"{case.url} returned 500 (after 3 retries)")
        self.texts_read += 1
        return [parse_opinion_html(case.id, "majority", CAP_TEXT, "cap_html")]


class KaiserCitedApi(FakeApi):
    def post_json(self, path, data):
        cluster = {**KAISER_CLUSTER, "citations": [{"volume": "391", "reporter": "U.S.", "page": "593"}]}
        return [{"citation": "391 U.S. 593", "normalized_citations": ["391 U.S. 593"], "status": 200, "clusters": [cluster]}]


def test_a_case_cap_holds_is_read_from_cap_without_spending_quota():
    api = KaiserCitedApi()
    cap = FakeCap({"391 U.S. 593": CapAnswer("391 U.S. 593", STARTS, (KAISER_CAP,))})
    quoted = Checker(api, {1: KAISER}, CITATIONS[:2], judge, cap).check(CITATIONS[1])
    assert outcomes(quoted)["quotation"] == PASS
    assert quoted[2].evidence["text_source"] == "cap"
    assert quoted[2].evidence["cap_url"] == "https://static.case.law/us/391/html/0593-01.html"
    assert quoted[2].evidence["cluster_id"] == 107720
    assert api.opinion_requests == 0 and cap.texts_read == 1


def test_a_case_only_cap_holds_is_checked_against_cap_text():
    api = FakeApi()
    varghese = CapCase(2, "Varghese v. China Southern Airlines Co.", "", "2019-01-01", "11th Cir.",
                       "925 F.3d 1339", 1339, 1350, "f3d", "925", "1339-01")
    cap = FakeCap({"925 F.3d 1339": CapAnswer("925 F.3d 1339", STARTS, (varghese,))})
    findings = Checker(api, {1: KAISER, 2: VARGHESE}, CITATIONS, judge, cap).check(CITATIONS[2])
    assert outcomes(findings)["identity"] == PASS
    assert findings[2].evidence["text_source"] == "cap"
    assert "cluster_id" not in findings[2].evidence


def test_when_cap_text_fails_courtlistener_is_used_and_the_failure_kept():
    api = KaiserCitedApi()
    cap = FakeCap({"391 U.S. 593": CapAnswer("391 U.S. 593", STARTS, (KAISER_CAP,))}, fail_text=True)
    quoted = Checker(api, {1: KAISER}, CITATIONS[:2], judge, cap).check(CITATIONS[1])
    assert quoted[2].evidence["text_source"] == "courtlistener"
    assert "returned 500" in quoted[2].evidence["cap_error"]
    assert api.opinion_requests == 1


def test_one_case_starting_at_the_clusters_cite_is_its_copy_whatever_its_caption():
    api = KaiserCitedApi()
    renamed = CapCase(**{**KAISER_CAP.__dict__, "name": "Trivelloni-Lorenzi v. Pan American", "full_name": ""})
    cap = FakeCap({"391 U.S. 593": CapAnswer("391 U.S. 593", STARTS, (renamed,))})
    quoted = Checker(api, {1: KAISER}, CITATIONS[:2], judge, cap).check(CITATIONS[1])
    assert quoted[2].evidence["text_source"] == "cap"
