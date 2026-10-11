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
