from gainsay.courtlistener import BudgetExhausted
from gainsay.extract import extract
from gainsay.ledger import connect, save_extraction, upsert_filing
from gainsay.runner import paused_run, run_checks
from gainsay.test_checker import KAISER_CLUSTER, KAISER_OPINION, judge
from gainsay.test_ledger import MANIFEST
from gainsay.tracing import Tracing

TEXT = (
    "The tolling effect of the stay is a matter of federal law. "
    "Kaiser Steel Corp. v. W.S. Ranch Co., 391 U.S. 593, 598 (1968). "
    "The court lacked jurisdiction. Kaiser Steel Corp. v. W.S. Ranch Co., 391 U.S. 593, 594 (1968)."
)


class FakeApi:
    def __init__(self, fail_opinions_once=False):
        self.fail_opinions_once = fail_opinions_once
        self.calls = 0

    def post_json(self, path, data):
        return [{"citation": "391 U.S. 593", "normalized_citations": ["391 U.S. 593"], "status": 200,
                 "clusters": [KAISER_CLUSTER]}]

    def get_json(self, path, params):
        if self.fail_opinions_once:
            self.fail_opinions_once = False
            raise BudgetExhausted("minute", 30)
        return {"results": [{"id": 9, "type": "020lead", "xml_harvard": KAISER_OPINION}], "next": None}

    def response_id(self, method, path, params):
        return 1


class NoTracing(Tracing):
    def __init__(self):
        self.enabled = False


def setup(tmp_path):
    conn = connect(tmp_path / "ledger.sqlite")
    filing_id = upsert_filing(conn, MANIFEST)
    save_extraction(conn, filing_id, extract(TEXT))
    return conn, filing_id


def outcomes(conn, run_id):
    rows = conn.execute(
        "SELECT c.ordinal, f.check_name, f.outcome FROM findings f JOIN citations c ON c.id = f.citation_id "
        "WHERE f.run_id = ? ORDER BY c.ordinal, f.check_name",
        (run_id,),
    )
    return {(r["ordinal"], r["check_name"]): r["outcome"] for r in rows}


def test_run_records_every_check_for_every_citation(tmp_path):
    conn, filing_id = setup(tmp_path)
    result = run_checks(conn, filing_id, "v1", FakeApi(), judge, NoTracing())
    assert result.status == "complete"
    found = outcomes(conn, result.run_id)
    assert len(found) == 10
    assert found[(1, "pincite")] == "fail" and found[(2, "pincite")] == "pass"


def test_budget_pause_is_resumed_without_repeating_findings(tmp_path):
    conn, filing_id = setup(tmp_path)
    paused = run_checks(conn, filing_id, "v1", FakeApi(fail_opinions_once=True), judge, NoTracing())
    assert paused.status == "paused"
    assert paused_run(conn, filing_id, "v1") == paused.run_id
    assert paused_run(conn, filing_id, "v2") is None

    resumed = run_checks(conn, filing_id, "v1", FakeApi(), judge, NoTracing(), resume_run_id=paused.run_id)
    assert (resumed.run_id, resumed.status) == (paused.run_id, "complete")
    assert len(outcomes(conn, resumed.run_id)) == 10
