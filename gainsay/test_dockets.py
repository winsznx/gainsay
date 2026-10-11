import pytest

from gainsay.dockets import (
    DocketConfig,
    opposing_names,
    poll_entries,
    resolve_docket,
    unchecked_opposing_entries,
)
from gainsay.filings import Docket
from gainsay.ledger import connect, finish_run, start_run, upsert_filing
from gainsay.test_ledger import MANIFEST

CONFIG = DocketConfig("Mata v. Avianca, Inc.", "nysd", "1:22-cv-01461", ["Roberto Mata", "LoDuca", "Schwartz"])
DOCKET = Docket("nysd", "1:22-cv-01461", 63107798, "Mata v. Avianca, Inc.")


def entry(number, description, created):
    return {"entry_number": number, "date_filed": "2023-03-01", "date_created": created, "description": description}


class FakeClient:
    def __init__(self, *pages):
        self.pages = list(pages)
        self.requests = []

    def get_json(self, path, params):
        self.requests.append((path, params))
        return self.pages.pop(0)


@pytest.mark.parametrize(
    ("description", "names"),
    [
        ("AFFIRMATION of Peter LoDuca in Opposition re: 16 MOTION.(LoDuca, Peter) (Entered: 03/01/2023)",
         ["LoDuca"]),
        ("LETTER from Steven Schwartz re: bankruptcy. Document filed by Roberto Mata..(LoDuca, Peter) "
         "(Entered: 05/05/2022)", ["Roberto Mata", "LoDuca"]),
        ("MEMORANDUM OF LAW re: 33 Order to Show Cause. Document filed by Levidow, Levidow & Oberman, P.C., "
         "Steven Schwartz..(Maulsby, Tyler) (Entered: 06/06/2023)", ["Schwartz"]),
        ("DECLARATION re: 33 Order. Document filed by Peter Loduca. (Attachments: # 1 Exhibit).(Foti, Catherine)",
         ["LoDuca"]),
        ("MOTION to Dismiss. Document filed by Avianca, Inc...(Banino, Bartholomew) (Entered: 02/22/2022)", []),
        ("ORDER TO SHOW CAUSE: Let Peter LoDuca, counsel for plaintiff, show cause. (Signed by Judge P. Kevin "
         "Castel on 5/04/2023) (ama) (Entered: 05/04/2023)", []),
        ("MEMO ENDORSEMENT on re: 12 Letter filed by Roberto Mata. SO ORDERED. (ama)", []),
        ("CLERK'S JUDGMENT in favor of Avianca, Inc. against Roberto Mata. (Signed by Clerk of Court) (tp)", []),
    ],
)
def test_only_the_filer_counts_and_court_entries_never_match(description, names):
    assert opposing_names(description, CONFIG) == names


def test_docket_is_searched_once_then_read_from_the_ledger(tmp_path):
    conn = connect(tmp_path / "ledger.sqlite")
    client = FakeClient(
        {"results": [{"court_id": "nysd", "docketNumber": "1:22-cv-01461", "docket_id": 63107798, "caseName": "Mata v. Avianca, Inc."}]}
    )
    assert resolve_docket(conn, client, CONFIG) == DOCKET
    assert resolve_docket(conn, client, CONFIG) == DOCKET
    assert len(client.requests) == 1


def test_poll_records_new_entries_and_uses_the_newest_creation_time_as_cursor(tmp_path):
    conn = connect(tmp_path / "ledger.sqlite")
    client = FakeClient(
        {
            "results": [entry(16, "MOTION to Dismiss filed by Avianca", "2023-01-10T00:00:00Z")],
            "next": "https://www.courtlistener.com/api/rest/v4/docket-entries/?cursor=abc&docket__id=63107798",
        },
        {"results": [entry(21, "AFFIRMATION of Peter LoDuca in Opposition", "2023-03-02T00:00:00Z"),
                     {"entry_number": None, "description": "minute entry"}], "next": None},
        {"results": [entry(29, "AFFIDAVIT of Peter LoDuca", "2023-04-26T00:00:00Z")], "next": None},
    )

    first = poll_entries(conn, client, DOCKET)
    second = poll_entries(conn, client, DOCKET)

    assert [e["entry_number"] for e in first] == [16, 21]
    assert [e["entry_number"] for e in second] == [29]
    assert "date_created__gt" not in client.requests[0][1]
    assert client.requests[1][1] == {"cursor": "abc", "docket__id": "63107798"}
    assert client.requests[2][1]["date_created__gt"] == "2023-03-02T00:00:00Z"
    assert client.requests[2][1]["fields"] == "entry_number,date_filed,date_created,description"


def test_unchecked_entries_are_opposing_ones_without_a_complete_run(tmp_path):
    conn = connect(tmp_path / "ledger.sqlite")
    poll_entries(conn, FakeClient({"results": [
        entry(16, "MOTION to Dismiss filed by Avianca", "2023-01-10T00:00:00Z"),
        entry(21, "AFFIRMATION of Peter LoDuca in Opposition.(LoDuca, Peter)", "2023-03-02T00:00:00Z"),
        entry(29, "AFFIDAVIT of Peter LoDuca.(LoDuca, Peter)", "2023-04-26T00:00:00Z"),
    ], "next": None}), DOCKET)
    filing_id = upsert_filing(conn, MANIFEST)
    finish_run(conn, start_run(conn, filing_id, "abc"), "paused")

    assert [e["entry_number"] for e in unchecked_opposing_entries(conn, DOCKET, CONFIG)] == [21, 29]
    finish_run(conn, start_run(conn, filing_id, "abc"), "complete")
    assert [e["entry_number"] for e in unchecked_opposing_entries(conn, DOCKET, CONFIG)] == [29]
