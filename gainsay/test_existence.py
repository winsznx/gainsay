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
    assert "outside free sources" in identity.reason


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


def test_nameless_cite_is_not_called_the_wrong_case():
    nameless = Authority(5, "", ["82 F. App'x 723"], "2003", "ca2")
    api = FakeApi([lookup_result("82 F. App'x 723", 200, [cluster("De La Fuente v. DCI Telecommunications, Inc.")])])
    existence, identity = check(api, nameless)
    assert (existence.outcome, identity.outcome) == (PASS, UNVERIFIABLE)
    assert "no case name" in identity.reason

    missing = FakeApi([lookup_result("82 F. App'x 723", 404)])
    assert [f.outcome for f in check(missing, nameless)] == [UNVERIFIABLE, UNVERIFIABLE]


def test_unpublished_decision_exists_through_its_recap_docket():
    rivas = Authority(6, "Rivas v. Bowling Green Assocs., L.P.", ["2014 WL 3694983"], "2014", "nysd", "13-cv-07812")

    class DocketApi(FakeApi):
        def get_json(self, path, params):
            self.searches.append(params)
            if params["type"] == "r":
                return {"results": [{"caseName": "Rivas v. Bowling Green Associates, L.P.", "docketNumber": "1:13-cv-07812",
                                     "court_id": "nysd", "docket_id": 8, "absolute_url": "/docket/8/rivas/"}]}
            return {"results": []}

    api = DocketApi([lookup_result("2014 WL 3694983", 400)])
    existence, identity = check(api, rivas)
    assert existence.outcome == PASS
    assert existence.evidence["source"] == "recap-docket"
    assert "1:13-cv-07812" in existence.reason
    assert identity.outcome == UNVERIFIABLE
    assert [p["type"] for p in api.searches] == ["o", "r"]


def test_docket_match_needs_only_a_shared_party_word():
    battery = Authority(7, "Advanced Battery Techs., Inc. v. Zhiguo Fu", ["2015 WL 4389893"], "2015", "nysd", "11-cv-04383")

    class DocketApi(FakeApi):
        def get_json(self, path, params):
            if params["type"] == "r":
                return {"results": [
                    {"caseName": "Braun v. Fu", "docketNumber": "1:11-cv-04383", "court_id": "nysd"},
                ]}
            return {"results": []}

    assert check(DocketApi([lookup_result("2015 WL 4389893", 400)]), battery)[0].outcome == PASS

    class OtherDocketApi(DocketApi):
        def get_json(self, path, params):
            if params["type"] == "r":
                return {"results": [{"caseName": "Smith v. Jones", "docketNumber": "1:11-cv-04383", "court_id": "nysd"}]}
            return {"results": []}

    existence = check(OtherDocketApi([lookup_result("2015 WL 4389893", 400)]), battery)[0]
    assert existence.outcome == UNVERIFIABLE
    assert "outside free sources" in existence.reason


def test_westlaw_case_no_free_source_finds_is_unverifiable_not_missing():
    martinez = Authority(2, "Martinez v. Delta Airlines, Inc.", ["2019 WL 4639462"], "2019", "texapp")
    existence, identity = check(FakeApi([lookup_result("2019 WL 4639462", 404)]), martinez)
    assert existence.outcome == UNVERIFIABLE
    assert existence.reason.startswith("2019 WL 4639462 is outside free sources")
    assert "no case named Martinez" in existence.reason


def test_invented_reporter_fails_existence_without_any_api_call():
    smith = Authority(8, "Smith v. Jones Corp.", ["475 F.6th 972"], "1983", None,
                      invented_reporter="there is no F.6th: the newest series of that reporter is F.4th")

    class NoApi(FakeApi):
        def get_json(self, path, params):
            raise AssertionError("no search for an invented reporter")

    api = NoApi([])
    existence, identity = check(api, smith)
    assert existence.outcome == FAIL
    assert existence.reason == "475 F.6th 972: there is no F.6th: the newest series of that reporter is F.4th"
    assert identity.outcome == UNVERIFIABLE


def test_lookups_go_out_sixty_citations_at_a_time_a_minute_apart():
    from gainsay.existence import LOOKUP_INTERVAL_SECONDS
    authorities = [Authority(i, f"Case{i} v. Other", [f"{i} U.S. {i}"], None, None) for i in range(1, 131)]

    class CountingApi(FakeApi):
        def __init__(self):
            super().__init__([])
            self.posts = []

        def post_json(self, path, data):
            self.posts.append(data["text"].count(";") + 1)
            return []

        def response_id(self, method, path, params):
            return None

    api, pauses = CountingApi(), []
    Lookup(api, authorities, pause=pauses.append)
    assert api.posts == [60, 60, 10]
    assert pauses == [LOOKUP_INTERVAL_SECONDS, LOOKUP_INTERVAL_SECONDS]


def test_page_shared_by_several_decisions_is_not_the_wrong_case():
    spinella = Authority(9, "Spinella v. Pearce", ["873 F.2d 701"], "1989", "ca9")
    api = FakeApi(
        [lookup_result("873 F.2d 701", 200, [cluster("Ricardo Jalil v. Avdel Corporation", "1989-04-01")])],
        [{"caseName": "Spinella v. Pearce", "court_id": "ca9", "dateFiled": "1989-04-20",
          "citation": ["873 F.2d 701"], "cluster_id": 3}],
    )
    existence, identity = check(api, spinella)
    assert (existence.outcome, identity.outcome) == (PASS, PASS)
    assert "holds more than one decision" in identity.reason


from gainsay.cap import INSIDE, NOT_COVERED, STARTS, CapAnswer, CapCase, CapError


class FakeCap:
    def __init__(self, answers=None, error=None):
        self.answers = answers or {}
        self.error = error

    def lookup(self, cite):
        if self.error:
            raise CapError(self.error)
        return self.answers.get(cite, CapAnswer(cite, NOT_COVERED))


def cap_case(name, cite, first, last):
    return CapCase(1, name, name, "2019-06-14", "D.C. Cir.", cite, first, last, "f3d", cite.split()[0], f"{first}-01")


VARGHESE = Authority(2, "Varghese v. China Southern Airlines Co., Ltd.", ["925 F.3d 1339"], "2019", "ca11")


def test_a_cite_courtlistener_misses_passes_when_cap_holds_the_named_case():
    api = FakeApi([lookup_result("516 F.3d 1237", 404)])
    cap = FakeCap({"516 F.3d 1237": CapAnswer(
        "516 F.3d 1237", STARTS, (cap_case("Zicherman v. Korean Air Lines Co.", "516 F.3d 1237", 1237, 1260),),
        "https://static.case.law/f3d/516/CasesMetadata.json",
    )})
    existence, identity = check_authority(api, Lookup(api, [ZICHERMAN]), ZICHERMAN, cap)
    assert (existence.outcome, identity.outcome) == (PASS, PASS)
    assert "in the Caselaw Access Project" in existence.reason
    assert existence.evidence["cap_case"]["url"] == "https://static.case.law/f3d/516/html/1237-01.html"
    assert api.searches == []


def test_a_page_inside_another_case_in_cap_fails_identity():
    api = FakeApi([lookup_result("925 F.3d 1339", 404)])
    cap = FakeCap({"925 F.3d 1339": CapAnswer(
        "925 F.3d 1339", INSIDE, (cap_case("J.D. v. Azar", "925 F.3d 1291", 1291, 1349),),
        "https://static.case.law/f3d/925/CasesMetadata.json",
    )})
    existence, identity = check_authority(api, Lookup(api, [VARGHESE]), VARGHESE, cap)
    assert existence.outcome == FAIL
    assert identity.outcome == FAIL
    assert "inside J.D. v. Azar, 925 F.3d 1291 (pages 1291-1349)" in identity.reason
    assert identity.evidence["cap"][0]["source_url"].endswith("/925/CasesMetadata.json")


def test_without_a_cap_answer_an_unresolved_cite_stays_unverifiable():
    api = FakeApi([lookup_result("925 F.3d 1339", 404)])
    existence, identity = check_authority(api, Lookup(api, [VARGHESE]), VARGHESE, FakeCap())
    assert identity.outcome == UNVERIFIABLE


def test_a_cap_failure_is_recorded_not_skipped():
    api = FakeApi([lookup_result("925 F.3d 1339", 404)])
    existence, identity = check_authority(api, Lookup(api, [VARGHESE]), VARGHESE, FakeCap(error="static.case.law timed out"))
    assert identity.outcome == UNVERIFIABLE
    assert "the Caselaw Access Project could not be read: static.case.law timed out" in identity.reason
    assert api.searches


def test_a_cited_page_inside_the_named_case_passes():
    sherar = Authority(3, "Sherar v. Cullen", ["481 F.2d 946"], "1973", "ca9")
    api = FakeApi([lookup_result("481 F.2d 946", 404)])
    cap = FakeCap({"481 F.2d 946": CapAnswer(
        "481 F.2d 946", INSIDE, (cap_case("Sherar v. Cullen", "481 F.2d 945", 945, 948),), "url",
    )})
    existence, identity = check_authority(api, Lookup(api, [sherar]), sherar, cap)
    assert (existence.outcome, identity.outcome) == (PASS, PASS)
    assert "falls inside Sherar v. Cullen, which begins at 481 F.2d 945" in identity.reason


def test_a_page_no_case_in_cap_reaches_proves_nothing():
    from gainsay.cap import EMPTY
    jahn = Authority(4, "Jahn Transfer, Inc. v. Horizon (H&S) Freightways, Inc.", ["819 N.W.2d 563"], "2012", None)
    api = FakeApi([lookup_result("819 N.W.2d 563", 404)])
    cap = FakeCap({"819 N.W.2d 563": CapAnswer("819 N.W.2d 563", EMPTY, (), "url")})
    existence, identity = check_authority(api, Lookup(api, [jahn]), jahn, cap)
    assert identity.outcome == UNVERIFIABLE


def test_a_parallel_cite_that_points_at_another_case_fails_identity():
    sempier = Authority(5, "Sempier v. Johnson & Higgins", ["515 U.S. 1159", "622 F.2d 589"], "1995", "scotus")
    api = FakeApi([
        lookup_result("515 U.S. 1159", 200, [cluster("Johnson & Higgins v. Sempier")]),
        lookup_result("622 F.2d 589", 200, [cluster("Reyes v. Unknown Shipping Co.")]),
    ])
    existence, identity = check_authority(api, Lookup(api, [sempier]), sempier)
    assert existence.outcome == PASS
    assert identity.outcome == FAIL
    assert "parallel cite 622 F.2d 589 resolves to Reyes v. Unknown Shipping Co." in identity.reason


def test_parallels_that_resolve_to_the_same_case_under_another_caption_pass():
    tseng = Authority(6, "El Al Israel Airlines, Ltd. v. Tseng", ["525 U.S. 155", "119 S. Ct. 662"], "1999", "scotus")
    api = FakeApi([
        lookup_result("525 U.S. 155", 200, [cluster("El Al Israel Airlines, Ltd. v. Tsui Yuan Tseng")]),
        lookup_result("119 S. Ct. 662", 200, [cluster("El Al Israel Airlines, Ltd. v. Tsui Yuan Tseng")]),
    ])
    assert check_authority(api, Lookup(api, [tseng]), tseng)[1].outcome == PASS


class FakeVolumeCap(FakeCap):
    def __init__(self, cases):
        super().__init__()
        self.cases = cases

    def covering(self, cite):
        page = int(cite.rsplit(" ", 1)[1])
        return tuple(c for c in self.cases if c.first_page <= page <= c.last_page)

    def lookup(self, cite):
        page = int(cite.rsplit(" ", 1)[1])
        starting = tuple(c for c in self.cases if c.first_page == page)
        inside = tuple(c for c in self.cases if c.first_page < page < c.last_page)
        if starting:
            return CapAnswer(cite, STARTS, starting, "url")
        return CapAnswer(cite, INSIDE, inside, "url") if inside else CapAnswer(cite, NOT_COVERED)


def test_an_untied_short_cite_is_checked_against_the_case_holding_its_page():
    from gainsay.existence import check_untied_short
    torrao = cap_case("Torrao v. Cassidy", "923 F.2d 231", 231, 236)
    existence, identity, case = check_untied_short(FakeVolumeCap([torrao]), "Torrao, 923 F.2d at 234")
    assert (existence.outcome, identity.outcome) == (PASS, PASS) and case == torrao
    other = cap_case("Lopez v. Garriga", "923 F.2d 231", 231, 236)
    existence, identity, case = check_untied_short(FakeVolumeCap([other]), "Torrao, 923 F.2d at 234")
    assert identity.outcome == FAIL and case is None
    assert "923 F.2d 234 is in Lopez v. Garriga, 923 F.2d 231, in the Caselaw Access Project, not Torrao" == identity.reason
    assert identity.evidence["untied_short"] is True
    existence, identity, case = check_untied_short(FakeVolumeCap([]), "Torrao, 923 F.2d at 234")
    assert identity.outcome == UNVERIFIABLE
