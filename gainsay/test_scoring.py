import json

import pytest

from gainsay.report import CheckResult, CitationReport, RunReport
from gainsay.scoring import AnswerKeyError, load_answer_key, score_run, summarize

SOURCE = (
    "The “Miller” decision does not exist. Kaiser Steel Corp. v. W. S. Ranch Co., 391 U.S. 593 (1968) "
    "(per curiam), does not discuss the federal bankruptcy stay."
)
MILLER = {
    "case_name": "Miller v. United Airlines, Inc.", "cite": "174 F.3d 366", "exists": False,
    "court_finding": "does_not_exist", "evidence": "The “Miller” decision does not exist.",
}
KAISER = {
    "case_name": "Kaiser Steel Corp. v. W. S. Ranch Co.", "cite": "391 U.S. 593", "exists": True,
    "court_finding": "does_not_support",
    "evidence": "Kaiser Steel Corp. v. W. S. Ranch Co., 391 U.S. 593 (1968) (per curiam), does not discuss",
}


def citation(ordinal, case_name, cite_text, **outcomes):
    report = CitationReport(ordinal, "full", case_name, cite_text, None, False, "p", [])
    report.checks = {k: CheckResult(v, "", {}) for k, v in outcomes.items()}
    return report


ALL_PASS = dict(existence="pass", identity="pass", quotation="not_applicable", pincite="pass")


def write_key(tmp_path, cases):
    path = tmp_path / "key.json"
    path.write_text(json.dumps({"cases": cases}))
    return path


def test_answer_key_evidence_must_be_in_the_source(tmp_path):
    assert len(load_answer_key(SOURCE, write_key(tmp_path, [MILLER, KAISER]))) == 2
    invented = {**MILLER, "evidence": "The Miller decision is a forgery made by counsel."}
    with pytest.raises(AnswerKeyError, match="not in the source text"):
        load_answer_key(SOURCE, write_key(tmp_path, [invented]))


def test_cases_match_by_cite_and_id_cites_join_by_name():
    report = RunReport({"id": 1}, {}, [
        citation(1, "Miller v. United Airlines, Inc.", "Miller v. United Airlines, Inc., 174 F.3d 366 (2d Cir. 1999)",
                 existence="fail", identity="fail"),
        citation(2, "Kaiser Steel Corp. v. W.S. Ranch Co.", "Kaiser Steel Corp. v. W.S. Ranch Co.. 391 U.S. 593, 598",
                 **ALL_PASS, proposition="fail"),
        citation(3, "Kaiser Steel Corp. v. W.S. Ranch Co.", "Id. at 594", **ALL_PASS, proposition="pass"),
    ])
    miller, kaiser = score_run(report, [MILLER, KAISER])

    assert miller.outcome == "true positive" and miller.agrees_with_court
    assert kaiser.statuses == ["Doesn't support the proposition", "Verified"]
    assert kaiser.case_status == "Doesn't support the proposition"
    assert kaiser.outcome == "true negative" and kaiser.agrees_with_court

    summary = summarize([miller, kaiser])
    assert (summary["precision"], summary["recall"], summary["agree"]) == (1.0, 1.0, 2)


def test_incomplete_case_is_undecided_unless_already_not_found():
    report = RunReport({"id": 1}, {}, [
        citation(1, "Kaiser Steel Corp. v. W.S. Ranch Co.", "391 U.S. 593", existence="pass", identity="pass"),
        citation(2, "Miller v. United Airlines, Inc.", "174 F.3d 366", existence="fail"),
    ])
    miller, kaiser = score_run(report, [MILLER, KAISER])
    assert kaiser.agrees_with_court is None
    assert miller.agrees_with_court is True


def test_wrong_case_is_not_a_claim_that_the_case_does_not_exist():
    ehrlich = {"case_name": "Ehrlich v. American Airlines, Inc.", "cite": "360 N.J. Super. 360", "exists": True,
               "court_finding": "does_not_support", "evidence": ""}
    report = RunReport({"id": 1}, {}, [
        citation(1, "Ehrlich v. American Airlines, Inc.", "Ehrlich v. American Airlines, Inc., 360 N.J. Super. 360",
                 existence="pass", identity="fail", quotation="not_applicable", proposition="fail"),
        citation(2, "Miller v. United Airlines, Inc.", "174 F.3d 366", existence="pass", identity="fail",
                 quotation="not_applicable", proposition="fail"),
    ])
    ehrlich_score, miller_score = score_run(report, [ehrlich, MILLER])
    assert ehrlich_score.outcome == "true negative"
    assert ehrlich_score.agrees_with_court is False
    assert miller_score.outcome == "false negative"
    assert miller_score.agrees_with_court is False


def test_answer_key_case_missing_from_run_is_an_error():
    report = RunReport({"id": 1}, {}, [citation(1, "Doe v. United States", "419 F.3d 1058", **ALL_PASS)])
    with pytest.raises(AnswerKeyError, match="174 F.3d 366"):
        score_run(report, [MILLER])
