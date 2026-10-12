import json

from gainsay.overview import benchmark_result


def arms(*names):
    return [{"arm": n, "precision": 0.5, "recall": 0.5, "f1": 0.5} for n in names]


def five_types(role, size):
    return {
        "subset": {"size": size, "role": role},
        "scores": {"citation_level": {"arms": arms("gainsay", "no-tools")}, "all_types": {"arms": arms("gainsay")}},
    }


def test_the_full_split_is_preferred_over_the_held_out_subset(tmp_path):
    (tmp_path / "lephantomcite-heldout-n100-seed777.json").write_text(json.dumps(
        {"subset": {"size": 100}, "arms": arms("gainsay", "no-tools")}
    ))
    assert benchmark_result(tmp_path)["all_types"] is None
    (tmp_path / "lephantomcite-heldout-n100-seed777-five-types.json").write_text(json.dumps(five_types("heldout", 100)))
    assert benchmark_result(tmp_path)["role"] == "heldout"
    (tmp_path / "lephantomcite-full-n390-five-types.json").write_text(json.dumps(five_types("full", 390)))
    result = benchmark_result(tmp_path)
    assert (result["role"], result["size"]) == ("full", 390)
    assert set(result["all_types"]) == {"gainsay"}


def test_development_results_are_never_shown(tmp_path):
    (tmp_path / "lephantomcite-dev-n100-seed1-five-types.json").write_text(json.dumps(five_types("dev", 100)))
    assert benchmark_result(tmp_path) is None


def test_an_entrys_exhibits_are_listed_under_it(tmp_path):
    from gainsay.extract import extract
    from gainsay.ledger import connect, save_extraction, start_run, upsert_filing
    from gainsay.overview import docket_overview
    from gainsay.test_ledger import MANIFEST
    conn = connect(tmp_path / "ledger.sqlite")
    conn.execute("INSERT INTO dockets (id, court, docket_number, case_name, resolved_at) "
                 "VALUES (63107798, 'nysd', '1:22-cv-01461', 'Mata v. Avianca, Inc.', 'now')")
    conn.execute("INSERT INTO docket_entries (docket_id, entry_number, date_filed, date_created, description, first_seen_at) "
                 "VALUES (63107798, 21, '2023-03-01', 'now', 'AFFIRMATION of Peter LoDuca in Opposition', 'now')")
    conn.commit()
    text = "The stay tolls the period. Ashcroft v. Iqbal, 556 U.S. 662 (2009)."
    for attachment, document_id in ((None, 1), (1, 2)):
        filing = upsert_filing(conn, {**MANIFEST, "recap_document_id": document_id, "attachment_number": attachment,
                                      "description": "Exhibit A" if attachment else MANIFEST["description"]})
        save_extraction(conn, filing, extract(text))
        start_run(conn, filing, "v1")
    (entry,) = docket_overview(conn).entries
    assert entry.report is not None
    (exhibit,) = entry.exhibits
    assert (exhibit.attachment_number, exhibit.description) == (1, "Exhibit A")
    assert exhibit.report.run["id"] != entry.report.run["id"]
