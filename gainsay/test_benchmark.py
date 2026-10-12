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
