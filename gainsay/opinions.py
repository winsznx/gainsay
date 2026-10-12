"""Opinion text and page breaks for a CourtListener cluster.

One request returns every opinion in a cluster (lead, concurrence, dissent,
and the combined copy some sources add). Page breaks come from the star
pagination CourtListener keeps in the HTML: <page-number label="594"> from
Harvard's data, <span class="star-pagination">*594</span> from others, and
<a class="page-label" data-label="594"> in CAP's own case files. Each break
is stored as (offset into the text, page number).
"""

import re
from dataclasses import dataclass, replace
from html.parser import HTMLParser
from urllib.parse import parse_qsl, urlparse

from gainsay.cache import CachedCourtListener

OPINIONS_PATH = "opinions/"
MAX_OPINION_PAGES = 400
_TEXT_FIELDS = (
    "html_with_citations",
    "html_lawbox",
    "html_columbia",
    "html",
    "html_anon_2020",
    "xml_harvard",
    "plain_text",
)
OPINION_FIELDS = ",".join(("id", "type", *_TEXT_FIELDS))
_BLOCK_TAGS = frozenset("p div br blockquote li h1 h2 h3 h4 h5 h6 tr section footnote".split())


@dataclass(frozen=True)
class OpinionText:
    opinion_id: int
    type: str
    source_field: str
    text: str
    pages: list[tuple[int, int]]
    # The reporter cite whose pages the breaks count, when the source says (CAP's
    # copy of a case is paginated in one reporter only).
    page_reporter: str | None = None

    def counts_pages_of(self, reporter_cite: str) -> bool:
        """Whether these page breaks can be read as pages of reporter_cite."""
        return self.page_reporter is None or _volume_and_reporter(self.page_reporter) == _volume_and_reporter(reporter_cite)

    def page_at(self, offset: int, first_page: int | None = None) -> int | None:
        """The page holding offset, counted in the reporter that starts at first_page.

        Breaks from parallel reporters are skipped. Text before the first break
        sits on the page before it, which for a concurrence or dissent is not
        the case's first page.
        """
        pages = self.pages_in(first_page) if first_page is not None else self.pages
        page = pages[0][1] - 1 if pages else first_page
        for start, number in pages:
            if start > offset:
                break
            page = number
        return page

    def pages_in(self, first_page: int) -> list[tuple[int, int]]:
        return [(o, p) for o, p in self.pages if first_page < p <= first_page + MAX_OPINION_PAGES]


def paginated_for(opinions: list[OpinionText], reporter_cite: str) -> list[OpinionText]:
    """The opinions, without page breaks that belong to another reporter than the one cited."""
    return [op if op.counts_pages_of(reporter_cite) else replace(op, pages=[]) for op in opinions]


def _volume_and_reporter(cite: str) -> str:
    return cite.rsplit(" ", 1)[0]


def distinct_opinions(opinions: list[OpinionText]) -> list[OpinionText]:
    """Drop "combined" copies when the cluster also has the split opinions they repeat."""
    split = [op for op in opinions if not op.type.startswith("010")]
    return split or opinions


def fetch_cluster_opinions(api: CachedCourtListener, cluster_id: int) -> list[OpinionText]:
    params: dict[str, object] = {"cluster__id": cluster_id, "fields": OPINION_FIELDS}
    opinions = []
    while True:
        body = api.get_json(OPINIONS_PATH, params)
        opinions.extend(parse_opinion(op) for op in body["results"])
        if not body.get("next"):
            return [op for op in opinions if op.text.strip()]
        params = dict(parse_qsl(urlparse(body["next"]).query))


def parse_opinion(opinion: dict) -> OpinionText:
    field = next((f for f in _TEXT_FIELDS if opinion.get(f)), None)
    if field is None:
        return OpinionText(opinion["id"], opinion.get("type", ""), "", "", [])
    if field == "plain_text":
        return OpinionText(opinion["id"], opinion.get("type", ""), field, opinion[field], [])
    return parse_opinion_html(opinion["id"], opinion.get("type", ""), opinion[field], field)


def parse_opinion_html(opinion_id: int, kind: str, html: str, source_field: str) -> OpinionText:
    parser = _PaginatedHTML()
    parser.feed(html)
    parser.close()
    return OpinionText(opinion_id, kind, source_field, parser.text(), parser.pages)


class _PaginatedHTML(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []
        self._length = 0
        self._marker: dict | None = None
        self.pages: list[tuple[int, int]] = []

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        classes = attributes.get("class") or ""
        if tag == "page-number" or "star-pagination" in classes or "page-label" in classes:
            label = attributes.get("label") or attributes.get("data-label")
            self._marker = {"tag": tag, "label": label, "text": ""}
        elif tag in _BLOCK_TAGS:
            self._append("\n")

    def handle_endtag(self, tag):
        if self._marker is not None and tag == self._marker["tag"]:
            label = self._marker["label"] or self._marker["text"]
            number = re.search(r"\d+", label or "")
            if number:
                self.pages.append((self._length, int(number.group())))
            self._marker = None
        elif tag in _BLOCK_TAGS:
            self._append("\n")

    def handle_data(self, data):
        if self._marker is not None:
            self._marker["text"] += data
        else:
            self._append(data)

    def _append(self, text: str) -> None:
        self._parts.append(text)
        self._length += len(text)

    def text(self) -> str:
        return "".join(self._parts)
