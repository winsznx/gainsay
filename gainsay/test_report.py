from gainsay.extract import extract
from gainsay.ledger import connect, record_finding, save_extraction, start_run, upsert_filing
from gainsay.report import INCOMPLETE, list_runs, load_run
from gainsay.status import NOT_FOUND, VERIFIED
from gainsay.test_ledger import MANIFEST

TEXT = (
    "The stay tolls the period. Zicherman v. Korean Air Lines Co., Ltd., 516 F.3d 1237, 1254 "
    "(11th Cir. 2008). Federal law governs tolling. Kaiser Steel Corp. v. W.S. Ranch Co., "
    "391 U.S. 593, 598 (1968). State law decides water rights. Ashcroft v. Iqbal, 556 U.S. 662 (2009)."
)
CLUSTER = {"cluster": {"cluster_id": 1, "absolute_url": "/opinion/107720/kaiser-steel/"}}


def make_run(tmp_path):
    conn = connect(tmp_path / "ledger.sqlite")
    filing_id = upsert_filing(conn, MANIFEST)
    save_extraction(conn, filing_id, extract(TEXT))
    run_id = start_run(conn, filing_id, "abc1234")
    zicherman, kaiser, iqbal = conn.execute("SELECT id FROM citations ORDER BY ordinal").fetchall()
    record_finding(conn, run_id, zicherman["id"], "existence", "fail", "no case named Zicherman", {})
    for check, outcome in [
        ("existence", "pass"), ("identity", "pass"), ("quotation", "not_applicable"),
        ("proposition", "pass"), ("pincite", "fail"),
    ]:
        record_finding(conn, run_id, kaiser["id"], check, outcome, f"{check} reason", CLUSTER)
    record_finding(conn, run_id, iqbal["id"], "existence", "pass", "found", {})
    return conn, run_id


def test_report_derives_status_flags_and_links_from_findings(tmp_path):
    conn, run_id = make_run(tmp_path)
    report = load_run(conn, run_id)

    zicherman, kaiser, iqbal = report.citations
    assert zicherman.status == NOT_FOUND
    assert kaiser.status == VERIFIED and kaiser.pincite_flag
    assert kaiser.opinion_url == "https://www.courtlistener.com/opinion/107720/kaiser-steel/"
    assert iqbal.status == INCOMPLETE
    assert report.status_counts == {NOT_FOUND: 1, VERIFIED: 1, INCOMPLETE: 1}
    assert report.headline == "1 of 3 citations has a problem."
    assert report.pincite_flags == 1
    assert "clean_text" not in report.filing


def test_report_lists_each_attempt_trace(tmp_path):
    from gainsay.ledger import record_trace
    conn, run_id = make_run(tmp_path)
    record_trace(conn, run_id, "a" * 32)
    record_trace(conn, run_id, "a" * 32, "paused", "CourtListener hour budget exhausted")
    record_trace(conn, run_id, "b" * 32, "complete")
    traces = load_run(conn, run_id).traces
    assert [(t["trace_id"][0], t["outcome"]) for t in traces] == [("a", "paused"), ("b", "complete")]


def test_list_runs_and_missing_run(tmp_path):
    conn, run_id = make_run(tmp_path)
    (run,) = list_runs(conn)
    assert run["id"] == run_id and run["case_name"] == "Mata v. Avianca, Inc."
    assert load_run(conn, 999) is None


def test_filing_without_case_citations_says_so():
    from gainsay.report import RunReport
    assert RunReport({"id": 1}, {}, []).headline == "This filing cites no cases."
