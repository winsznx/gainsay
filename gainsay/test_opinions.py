from gainsay.opinions import fetch_cluster_opinions, parse_opinion

HARVARD = (
    '<opinion type="majority"><p id="b1">PER CURIAM.</p>'
    '<p>The stay tolls the period.<page-number citation-index="1" label="594">*594</page-number>'
    " State law governs.</p></opinion>"
)
LAWBOX = '<p>First page.</p><p><span class="star-pagination">*594</span> Second page.</p>'


def test_harvard_page_numbers_become_offsets_and_leave_the_text():
    opinion = parse_opinion({"id": 1, "type": "020lead", "html_with_citations": HARVARD})
    assert "*594" not in opinion.text
    ((offset, page),) = opinion.pages
    assert page == 594
    assert opinion.text[offset:].strip().startswith("State law governs.")
    assert opinion.page_at(opinion.text.index("The stay"), first_page=593) == 593
    assert opinion.page_at(opinion.text.index("State law"), first_page=593) == 594


def test_page_at_skips_parallel_reporter_breaks():
    opinion = parse_opinion(
        {
            "id": 4,
            "type": "020lead",
            "html_lawbox": '<p>a</p><span class="star-pagination">*1755</span><p>b</p>'
            '<span class="star-pagination">*595</span><p>c</p>',
        }
    )
    assert opinion.page_at(opinion.text.index("b"), first_page=593) == 594
    assert opinion.page_at(opinion.text.index("c"), first_page=593) == 595


def test_star_pagination_spans_are_read_too():
    opinion = parse_opinion({"id": 2, "type": "010combined", "html_lawbox": LAWBOX})
    assert opinion.pages == [(opinion.text.index(" Second"), 594)]
    assert opinion.source_field == "html_lawbox"


def test_plain_text_has_no_pages():
    opinion = parse_opinion({"id": 3, "type": "010combined", "plain_text": "Some opinion."})
    assert (opinion.text, opinion.pages) == ("Some opinion.", [])


def test_cluster_fetch_follows_pagination_and_drops_empty_opinions():
    class Api:
        def __init__(self):
            self.params = []

        def get_json(self, path, params):
            self.params.append(params)
            if "cursor" in params:
                return {"results": [{"id": 2, "type": "040dissent", "plain_text": "Dissent."}], "next": None}
            return {
                "results": [{"id": 1, "type": "020lead", "plain_text": ""}],
                "next": "https://www.courtlistener.com/api/rest/v4/opinions/?cluster__id=9&cursor=abc",
            }

    api = Api()
    opinions = fetch_cluster_opinions(api, 9)
    assert [o.opinion_id for o in opinions] == [2]
    assert api.params[1] == {"cluster__id": "9", "cursor": "abc"}
