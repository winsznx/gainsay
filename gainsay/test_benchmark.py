from gainsay.benchmark import Excerpt, matches, score, subset


def test_match_is_substring_either_way_or_ordered_ellipsis_fragments():
    assert matches("475 F.6th 972, 1010 (8th Cir. 1983)", "475 F.6th 972")
    assert matches("409 U.S. at 67", "Benson, 409 U.S. at 67")
    assert matches("the claims are ... too broad", "the claims are so theoretical and too broad here")
    assert not matches("475 F.6th 972", "391 U.S. 593")


def test_out_of_scope_hits_are_left_out_of_precision():
    excerpt = Excerpt(0, "text", {
        "475 F.6th 972": "non_existent_citation",
        "'so theoretical and broad'": "misquote",
    }, [])
    result = score("arm", [excerpt], {0: ["475 F.6th 972", "so theoretical and broad", "391 U.S. 593"]})
    assert (result.predictions, result.correct) == (2, 1)
    assert result.found["non_existent_citation"] == 1
    assert result.recall == 1.0
    assert result.precision == 0.5


def test_subset_is_seeded_and_ordered():
    excerpts = [Excerpt(i, "", {}, []) for i in range(390)]
    first = [e.index for e in subset(excerpts, 100, seed=7)]
    assert first == [e.index for e in subset(excerpts, 100, seed=7)]
    assert first == sorted(first) and len(set(first)) == 100
    held_out = [e.index for e in subset(excerpts, 100, seed=8, exclude=frozenset(first))]
    assert not set(held_out) & set(first)


from gainsay.benchmark import ALL_TYPES, citation_spans, predicted_spans
from gainsay.findings import FAIL as F, NOT_APPLICABLE as NA, PASS as P, Finding


def findings(existence=P, identity=P, pincite=NA, proposition=P, quote_scores=()):
    quote = Finding("quotation", F if any(s < 90 for _, s in quote_scores) else NA, "q", {
        "passages": [{"passage": text, "score": s} for text, s in quote_scores]
    })
    return [Finding("existence", existence, "e"), Finding("identity", identity, "i"), quote,
            Finding("proposition", proposition, "p"), Finding("pincite", pincite, "n")]


def test_each_failed_check_flags_the_span_its_error_type_labels():
    assert predicted_spans("full", "925 F.3d 1339", "s", findings(identity=F)) == ["925 F.3d 1339"]
    assert predicted_spans("short", "755 N.E.2d at 598", "s", findings(pincite=F)) == ["755 N.E.2d at 598"]
    flagged = predicted_spans("short", "755 N.E.2d at 598", "The court held X.", findings(
        proposition=F, quote_scores=[("the name used by defendant", 41.0), ("has come to denote", 99.0)],
    ))
    assert flagged == ["the name used by defendant", "The court held X."]
    assert predicted_spans("full", "391 U.S. 593", "s", findings()) == []


def test_an_id_cite_does_not_repeat_its_cases_existence_flag():
    assert citation_spans("id", "Id. at 5", findings(existence=F)) == []
    assert citation_spans("full", "925 F.3d 1339", findings(existence=F, pincite=F)) == ["925 F.3d 1339"]
    assert predicted_spans("full", "925 F.3d 1339", "s", findings(existence=F, pincite=F)) == ["925 F.3d 1339"]


def test_all_types_counts_quote_and_statement_labels():
    excerpt = Excerpt(0, "text", {
        "925 F.3d 1339": "non_existent_citation",
        "the name used by defendant": "misquote",
        "unfair competition category": "optional",
    }, [])
    two = score("arm", [excerpt], {0: ["925 F.3d 1339", "the name used by defendant"]})
    five = score("arm", [excerpt], {0: ["925 F.3d 1339", "the name used by defendant"]}, ALL_TYPES)
    assert (two.predictions, two.correct) == (1, 1)
    assert (five.predictions, five.correct) == (2, 2)
    assert five.as_dict()["recall_by_type"]["misquote"] == "1/1"


from gainsay.benchmark import citation_as_written, raw_span


def test_a_citation_is_reported_as_the_excerpt_writes_it():
    raw = "In *Simon v. City of\nClute*, 825 F.2d 940 (5th Cir. 1987) (reassigning), for example, the court erred."
    cleaned = "Simon v. City of Clute, 825 F.2d 940 (5th Cir. 1987) (reassigning)"
    assert citation_as_written(cleaned) == "Simon v. City of Clute, 825 F.2d 940 (5th Cir. 1987)"
    assert raw_span(raw, citation_as_written(cleaned)) == "Simon v. City of\nClute*, 825 F.2d 940 (5th Cir. 1987)"
    assert raw_span(raw, "nowhere in the excerpt") == "nowhere in the excerpt"


def test_history_and_untied_short_cites_are_flagged_themselves():
    untied = [Finding("existence", NA, "e"), Finding("identity", F, "i", {"untied_short": True})]
    assert citation_spans("short", "Torrao, 923 F.2d at 234", untied) == ["Torrao, 923 F.2d at 234"]
    assert citation_spans("history", "cert. denied, 622 F.2d 589", findings(identity=F)) == ["cert. denied, 622 F.2d 589"]
    assert citation_spans("short", "Torrao, 923 F.2d at 234", findings(identity=F)) == []
