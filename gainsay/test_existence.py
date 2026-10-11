from gainsay.existence import Authority, Lookup, check_authority
from gainsay.findings import FAIL, PASS, UNVERIFIABLE


class FakeApi:
    def __init__(self, lookup_results, search_results=()):
        self.lookup_results = lookup_results
        self.search_results = list(search_results)
        self.searches = []

    def post_json(self, path, data):
        return self.lookup_results

    def get_json(self, path, params):
        self.searches.append(params)
        return {"results": self.search_results}

    def response_id(self, method, path, params):
        return 7


def cluster(case_name, date_filed="2008-01-01", cites=()):
    return {
        "id": 1,
        "case_name": case_name,
        "date_filed": date_filed,
        "absolute_url": "/opinion/1/x/",
        "citations": [dict(zip(("volume", "reporter", "page"), c.split(" ", 2))) for c in cites],
        "sub_opinions": ["https://www.courtlistener.com/api/rest/v4/opinions/1/"],
    }


def lookup_result(cite, status, clusters=()):
    return {"citation": cite, "normalized_citations": [cite], "status": status, "clusters": list(clusters)}


ZICHERMAN = Authority(1, "Zicherman v. Korean Air Lines Co., Ltd.", ["516 F.3d 1237"], "2008", "ca11")


def check(api, authority):
    return check_authority(api, Lookup(api, [authority]), authority)


def test_cite_that_resolves_to_the_named_case_passes_both():
    api = FakeApi([lookup_result("516 F.3d 1237", 200, [cluster("Zicherman v. Korean Air Lines Co.")])])
    existence, identity = check(api, ZICHERMAN)
    assert (existence.outcome, identity.outcome) == (PASS, PASS)
    assert existence.evidence["cluster"]["sub_opinions"]
    assert api.searches == []


def test_cite_that_resolves_to_another_case_is_wrong_case_and_name_is_searched():
    api = FakeApi([lookup_result("516 F.3d 1237", 200, [cluster("Hopkins v. Airtran Airways")])])
    existence, identity = check(api, ZICHERMAN)
    assert identity.outcome == FAIL
    assert "Hopkins v. Airtran Airways" in identity.reason
    assert existence.outcome == FAIL
    assert api.searches == [
        {
            "type": "o",
            "q": "caseName:(zicherman AND korean)",
            "court": "ca11",
            "filed_after": "2007-01-01",
            "filed_before": "2009-12-31",
        }
    ]


def test_unresolved_cite_with_no_name_match_is_not_found():
    api = FakeApi(
        [lookup_result("516 F.3d 1237", 404)],
        [{"caseName": "Zicherman v. Korean Air Lines Co.", "court_id": "scotus", "dateFiled": "1996-01-16"}],
    )
    existence, identity = check(api, ZICHERMAN)
    assert existence.outcome == FAIL
    assert "no case named Zicherman v. Korean Air Lines Co., Ltd. (ca11, 2008)" in existence.reason
    assert identity.outcome == UNVERIFIABLE
    assert "no case at 516 F.3d 1237" in identity.reason


def test_westlaw_cite_is_found_by_name_and_identity_stays_unverifiable():
    martinez = Authority(2, "Martinez v. Delta Airlines, Inc.", ["2019 WL 4639462"], "2019", "texapp")
    api = FakeApi(
        [lookup_result("2019 WL 4639462", 400)],
        [{"caseName": "Martinez v. Delta Air Lines, Inc.", "court_id": "texapp", "dateFiled": "2019-09-25", "cluster_id": 9}],
    )
    existence, identity = check(api, martinez)
    assert existence.outcome == PASS
    assert existence.evidence["candidates"][0]["cluster_id"] == 9
    assert identity.outcome == UNVERIFIABLE
    assert "does not index the reporter" in identity.reason


def test_name_search_result_from_a_distant_year_does_not_count():
    api = FakeApi(
        [lookup_result("516 F.3d 1237", 404)],
        [{"caseName": "Zicherman v. Korean Air Lines Co.", "court_id": "ca11", "dateFiled": "1994-05-01"}],
    )
    existence, _ = check(api, ZICHERMAN)
    assert existence.outcome == FAIL


def test_namesake_in_the_other_court_system_exists_but_is_not_where_cited():
    ehrlich = Authority(4, "Ehrlich v. American Airlines, Inc.", ["360 N.J. Super. 360"], "2003", None)
    api = FakeApi(
        [lookup_result("360 N.J. Super. 360", 404)],
        [{"caseName": "Ehrlich v. American Airlines, Inc.", "court_id": "ca2", "dateFiled": "2004-03-08",
          "citation": ["360 F.3d 366"], "cluster_id": 785320}],
    )
    existence, identity = check(api, ehrlich)
    assert existence.outcome == PASS
    assert existence.evidence["candidates"][0]["cluster_id"] == 785320
    assert identity.outcome == FAIL
    assert identity.reason == (
        "nothing at 360 N.J. Super. 360; Ehrlich v. American Airlines, Inc. is reported at 360 F.3d 366"
    )


def test_same_reporter_at_another_page_is_wrong_but_a_missing_reporter_proves_nothing():
    zicherman = Authority(1, "Zicherman v. Korean Air Lines Co.", ["516 F.3d 1237"], "2008", "ca11")
    elsewhere = {"caseName": "Zicherman v. Korean Air Lines Co.", "court_id": "ca11", "dateFiled": "2008-02-01"}

    moved = FakeApi([lookup_result("516 F.3d 1237", 404)], [{**elsewhere, "citation": ["517 F.3d 1"]}])
    assert check(moved, zicherman)[1].outcome == FAIL

    unknown = FakeApi([lookup_result("516 F.3d 1237", 404)], [{**elsewhere, "citation": ["2008 WL 123"]}])
    existence, identity = check(unknown, zicherman)
    assert (existence.outcome, identity.outcome) == (PASS, UNVERIFIABLE)


def test_parallel_cite_resolving_is_enough():
    kaiser = Authority(3, "Kaiser Steel Corp. v. W.S. Ranch Co.", ["391 U.S. 593", "88 S. Ct. 1753"], "1968", "scotus")
    api = FakeApi(
        [
            lookup_result("391 U.S. 593", 404),
            lookup_result("88 S. Ct. 1753", 200, [cluster("Kaiser Steel Corp. v. W. S. Ranch Co.", "1968-06-10")]),
        ]
    )
    existence, identity = check(api, kaiser)
    assert (existence.outcome, identity.outcome) == (PASS, PASS)
    assert existence.evidence["cite"] == "88 S. Ct. 1753"
