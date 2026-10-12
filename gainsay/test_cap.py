import json

import pytest
import requests

from gainsay.cap import EMPTY, INSIDE, NO_VOLUME, NOT_COVERED, STARTS, Cap, CapError

REPORTERS = [{"short_name": "F.3d", "slug": "f3d"}, {"short_name": "F. Supp. 2d", "slug": "f-supp-2d"}]
VOLUME_925 = [
    {
        "id": 12521244,
        "name": "J.D., on behalf of herself and others similarly situated v. Alex Michael AZAR, II",
        "name_abbreviation": "J.D. v. Azar",
        "decision_date": "2019-06-14",
        "first_page": "1291",
        "last_page": "1349",
        "file_name": "1291-01",
        "court": {"name_abbreviation": "D.C. Cir."},
        "citations": [{"type": "official", "cite": "925 F.3d 1291"}],
        "cites_to": [{"cite": "401 U.S. 402"}],
    },
    {
        "id": 12521245,
        "name": "Sierra Club v. United States Fish & Wildlife Service",
        "name_abbreviation": "Sierra Club v. U.S. Fish & Wildlife Serv.",
        "decision_date": "2019-05-30",
        "first_page": "1350",
        "last_page": "1360",
        "file_name": "1350-01",
        "court": {"name_abbreviation": "9th Cir."},
        "citations": [{"type": "official", "cite": "925 F.3d 1350"}],
    },
]
CASE_HTML = """<section class="casebody" data-firstpage="1291" data-lastpage="1349">
  <section class="head-matter"><p class="parties">J.D. v. Azar</p></section>
  <article class="opinion" data-type="majority">
    <p>Per Curiam:</p>
    <p><a id="p1299" href="#p1299" data-label="1299" class="page-label">*1299</a>Unaccompanied alien children
    have no parent in the United States.</p>
    <p><a id="p1300" href="#p1300" data-label="1300" class="page-label">*1300</a>The policy is enjoined.</p>
  </article>
  <article class="opinion" data-type="dissent">
    <p><a data-label="1340" class="page-label">*1340</a>I respectfully dissent.</p>
  </article>
</section>"""


class FakeResponse:
    def __init__(self, status_code, text=""):
        self.status_code = status_code
        self.text = text


class FakeSession:
    def __init__(self, files, failures=0):
        self.files = files
        self.failures = failures
        self.requested = []

    def get(self, url, timeout):
        self.requested.append(url)
        if self.failures:
            self.failures -= 1
            raise requests.ConnectionError("connection reset")
        path = url.removeprefix("https://static.case.law/")
        if path not in self.files:
            return FakeResponse(404)
        body = self.files[path]
        return FakeResponse(200, body if isinstance(body, str) else json.dumps(body))


FILES = {
    "ReportersMetadata.json": REPORTERS,
    "f3d/925/CasesMetadata.json": VOLUME_925,
    "f3d/925/html/1291-01.html": CASE_HTML,
}


def cap(tmp_path, files=FILES, **kwargs):
    session = FakeSession(files, **kwargs)
    return Cap(tmp_path, session=session, sleep=lambda s: None), session


def test_a_case_starting_at_the_cited_page_is_found(tmp_path):
    client, _ = cap(tmp_path)
    answer = client.lookup("925 F.3d 1291")
    assert answer.status == STARTS
    assert [c.name for c in answer.cases] == ["J.D. v. Azar"]
    assert answer.cases[0].cite == "925 F.3d 1291"
    assert answer.source_url == "https://static.case.law/f3d/925/CasesMetadata.json"


def test_a_page_in_the_middle_of_another_case_is_inside_it(tmp_path):
    client, _ = cap(tmp_path)
    answer = client.lookup("925 F.3d 1339")
    assert answer.status == INSIDE
    assert answer.cases[0].name == "J.D. v. Azar"
    assert (answer.cases[0].first_page, answer.cases[0].last_page) == (1291, 1349)


def test_a_page_no_case_reaches_is_empty(tmp_path):
    client, _ = cap(tmp_path)
    assert client.lookup("925 F.3d 1500").status == EMPTY


def test_a_volume_cap_lacks_gives_no_answer_and_is_not_fetched_twice(tmp_path):
    client, session = cap(tmp_path)
    assert client.lookup("990 F.3d 12").status == NO_VOLUME
    assert cap(tmp_path)[0].lookup("990 F.3d 12").status == NO_VOLUME
    assert session.requested.count("https://static.case.law/f3d/990/CasesMetadata.json") == 1


def test_reporters_cap_does_not_hold_are_not_covered(tmp_path):
    client, _ = cap(tmp_path)
    assert client.lookup("2019 WL 4639462").status == NOT_COVERED
    assert client.lookup("905 F. Supp 2d 121").status == NOT_COVERED
    assert client.lookup("905 F. Supp. 2d 121").status == NO_VOLUME


def test_volumes_are_cached_trimmed_on_disk(tmp_path):
    client, session = cap(tmp_path)
    client.lookup("925 F.3d 1291")
    stored = json.loads((tmp_path / "f3d" / "925" / "CasesMetadata.json").read_text())
    assert "cites_to" not in stored[0] and stored[0]["court"] == "D.C. Cir."
    fresh, fresh_session = cap(tmp_path)
    assert fresh.lookup("925 F.3d 1339").status == INSIDE
    assert fresh_session.requested == []


def test_opinions_keep_each_article_and_its_page_breaks(tmp_path):
    client, _ = cap(tmp_path)
    majority, dissent = client.opinions(client.lookup("925 F.3d 1291").cases[0])
    assert (majority.type, dissent.type) == ("majority", "dissent")
    assert majority.source_field == "cap_html"
    assert [page for _, page in majority.pages] == [1299, 1300]
    offset = majority.text.index("The policy is enjoined")
    assert majority.page_at(offset, 1291) == 1300
    assert "J.D. v. Azar" not in majority.text


def test_dropped_connections_are_retried_then_reported(tmp_path):
    client, _ = cap(tmp_path, failures=2)
    assert client.lookup("925 F.3d 1291").status == STARTS
    with pytest.raises(CapError):
        cap(tmp_path / "other", failures=10)[0].lookup("925 F.3d 1291")


def test_the_last_page_of_a_case_may_begin_the_next_one(tmp_path):
    client, _ = cap(tmp_path)
    assert client.lookup("925 F.3d 1349").status == EMPTY
    assert client.lookup("925 F.3d 1348").status == INSIDE


def test_pages_follow_the_official_cite_when_cap_numbers_them_off(tmp_path):
    files = {
        **FILES,
        "f3d/675/CasesMetadata.json": [{
            "id": 7, "name": "Noah Systems, Inc. v. Intuit Inc.", "name_abbreviation": "Noah Sys., Inc. v. Intuit Inc.",
            "decision_date": "2012-04-09", "first_page": "1292", "last_page": "1309", "file_name": "1292-01",
            "court": {"name_abbreviation": "Fed. Cir."}, "citations": [{"type": "official", "cite": "675 F.3d 1302"}],
        }],
        "f3d/675/html/1292-01.html": '<article class="opinion" data-type="majority"><p>'
                                     '<a class="page-label" data-label="1294">*1294</a>The claim is indefinite.</p></article>',
    }
    client, _ = cap(tmp_path, files)
    answer = client.lookup("675 F.3d 1302")
    assert answer.status == STARTS
    case = answer.cases[0]
    assert (case.first_page, case.last_page, case.page_offset) == (1302, 1319, 10)
    assert client.lookup("675 F.3d 1312").status == INSIDE
    (opinion,) = client.opinions(case)
    assert [page for _, page in opinion.pages] == [1304]
