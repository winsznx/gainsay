"""Harvard's Caselaw Access Project, read from its static files at static.case.law.

CAP publishes the case law it digitized as static files: one metadata file
per reporter volume listing every case in it with its first and last page,
and one HTML file per case with the reporter's page breaks marked. Reading
them costs no CourtListener quota, so CAP answers for a cite CourtListener's
lookup can't resolve, and supplies the text of any case it holds.

Coverage ends around 2018 for most reporters. A cite to a reporter or volume
CAP doesn't have gets no answer from it, never a negative one.
"""

import json
import logging
import re
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable

import requests

from gainsay.opinions import OpinionText, parse_opinion_html

logger = logging.getLogger(__name__)

BASE_URL = "https://static.case.law"
DEFAULT_CACHE_DIR = Path(__file__).resolve().parent.parent / "data" / "cap"
TIMEOUT_SECONDS = 30
MAX_RETRIES = 3
BACKOFF_SECONDS = (2, 4, 8)

STARTS = "starts"
INSIDE = "inside"
EMPTY = "empty"
NO_VOLUME = "no_volume"
NOT_COVERED = "not_covered"

_ARTICLE = re.compile(r'<article class="opinion" data-type="([^"]*)">(.*?)</article>', re.S)
_CITE = re.compile(r"^(\d+) (.+) (\S+)$")
_KEPT_FIELDS = ("id", "name", "name_abbreviation", "decision_date", "first_page", "last_page", "file_name")


class CapError(Exception):
    pass


@dataclass(frozen=True)
class CapCase:
    id: int
    name: str
    full_name: str
    decision_date: str
    court: str
    cite: str
    first_page: int | None
    last_page: int | None
    slug: str
    volume: str
    file_name: str

    @property
    def url(self) -> str:
        return f"{BASE_URL}/{self.slug}/{self.volume}/html/{self.file_name}.html"

    def summary(self) -> dict:
        return {**asdict(self), "url": self.url}


@dataclass(frozen=True)
class CapAnswer:
    """What CAP holds at a cite: a case starting there, the case the page falls inside, or nothing."""

    cite: str
    status: str
    cases: tuple[CapCase, ...] = ()
    source_url: str | None = None

    def evidence(self) -> dict:
        return {
            "cite": self.cite,
            "status": self.status,
            "cases": [c.summary() for c in self.cases],
            "source_url": self.source_url,
        }


class Cap:
    def __init__(
        self,
        cache_dir: Path = DEFAULT_CACHE_DIR,
        session: requests.Session | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self._cache_dir = cache_dir
        self._session = session or requests.Session()
        self._sleep = sleep
        self._slugs: dict[str, list[str]] | None = None
        self._volumes: dict[tuple[str, str], list[CapCase] | None] = {}
        self.fetches = 0

    def lookup(self, cite: str) -> CapAnswer:
        parts = _CITE.match(cite)
        if not parts or not parts.group(3).isdigit():
            return CapAnswer(cite, NOT_COVERED)
        volume, reporter, page = parts.group(1), parts.group(2), int(parts.group(3))
        slugs = self.slugs().get(_reporter_key(reporter), [])
        if not slugs:
            return CapAnswer(cite, NOT_COVERED)
        for slug in slugs:
            cases = self.volume(slug, volume)
            if cases is None:
                continue
            url = f"{BASE_URL}/{slug}/{volume}/CasesMetadata.json"
            starting = tuple(c for c in cases if c.first_page == page)
            if starting:
                return CapAnswer(cite, STARTS, starting, url)
            containing = tuple(
                c for c in cases if c.first_page and c.last_page and c.first_page < page <= c.last_page
            )
            if containing:
                return CapAnswer(cite, INSIDE, containing, url)
            return CapAnswer(cite, EMPTY, (), url)
        return CapAnswer(cite, NO_VOLUME, (), f"{BASE_URL}/{slugs[0]}/{volume}/CasesMetadata.json")

    def opinions(self, case: CapCase) -> list[OpinionText]:
        """Each opinion in the case (majority, concurrence, dissent) with CAP's page breaks."""
        path = self._cache_dir / case.slug / case.volume / "html" / f"{case.file_name}.html"
        html = self._cached_text(path, case.url)
        if html is None:
            raise CapError(f"{case.url} is missing")
        return [
            parse_opinion_html(case.id, kind, body, "cap_html")
            for kind, body in _ARTICLE.findall(html)
        ]

    def slugs(self) -> dict[str, list[str]]:
        if self._slugs is None:
            path = self._cache_dir / "ReportersMetadata.json"
            text = self._cached_text(path, f"{BASE_URL}/ReportersMetadata.json")
            if text is None:
                raise CapError("CAP's reporter list is missing")
            slugs: dict[str, list[str]] = {}
            for reporter in json.loads(text):
                slugs.setdefault(_reporter_key(reporter["short_name"]), []).append(reporter["slug"])
            self._slugs = slugs
        return self._slugs

    def volume(self, slug: str, volume: str) -> list[CapCase] | None:
        key = (slug, volume)
        if key not in self._volumes:
            path = self._cache_dir / slug / volume / "CasesMetadata.json"
            text = self._cached_text(path, f"{BASE_URL}/{slug}/{volume}/CasesMetadata.json", trim=_trim_volume)
            self._volumes[key] = None if text is None else [
                _case(entry, slug, volume) for entry in json.loads(text)
            ]
        return self._volumes[key]

    def _cached_text(self, path: Path, url: str, trim: Callable[[str], str] | None = None) -> str | None:
        """The file at url, kept under the cache directory. None when CAP has no such file."""
        missing = path.with_suffix(path.suffix + ".missing")
        if missing.exists():
            return None
        if path.exists():
            return path.read_text()
        text = self._get(url)
        path.parent.mkdir(parents=True, exist_ok=True)
        if text is None:
            missing.touch()
            return None
        if trim:
            text = trim(text)
        path.write_text(text)
        return text

    def _get(self, url: str) -> str | None:
        for attempt in range(MAX_RETRIES + 1):
            try:
                response = self._session.get(url, timeout=TIMEOUT_SECONDS)
            except requests.RequestException as exc:
                failure = f"{url}: {exc}"
            else:
                self.fetches += 1
                if response.status_code in (403, 404):
                    return None
                if response.status_code == 200:
                    return response.text
                failure = f"{url} returned {response.status_code}"
            if attempt == MAX_RETRIES:
                raise CapError(f"{failure} (after {MAX_RETRIES} retries)")
            logger.warning("%s; retry %d of %d in %ss", failure, attempt + 1, MAX_RETRIES, BACKOFF_SECONDS[attempt])
            self._sleep(BACKOFF_SECONDS[attempt])
        raise AssertionError("unreachable")


def _reporter_key(reporter: str) -> str:
    return re.sub(r"\s+", "", reporter.replace("’", "'")).lower()


def _trim_volume(text: str) -> str:
    """Keep what lookups need; the full metadata repeats every case's outgoing citations."""
    return json.dumps([
        {
            **{k: entry.get(k) for k in _KEPT_FIELDS},
            "court": (entry.get("court") or {}).get("name_abbreviation"),
            "cite": next((c["cite"] for c in entry.get("citations", []) if c.get("type") == "official"), None),
        }
        for entry in json.loads(text)
    ])


def _case(entry: dict, slug: str, volume: str) -> CapCase:
    return CapCase(
        id=entry["id"],
        name=entry.get("name_abbreviation") or entry.get("name") or "",
        full_name=entry.get("name") or "",
        decision_date=entry.get("decision_date") or "",
        court=entry.get("court") or "",
        cite=entry.get("cite") or "",
        first_page=_page(entry.get("first_page")),
        last_page=_page(entry.get("last_page")),
        slug=slug,
        volume=volume,
        file_name=entry.get("file_name") or "",
    )


def _page(value: str | None) -> int | None:
    return int(value) if value and str(value).isdigit() else None
