"""OpenAlex catalogue access and metadata-only candidate rules.

Nothing here downloads a paper. ``compact_work`` reduces one OpenAlex work
record to the few fields the screen needs, ``paper_candidate`` applies the
per-paper rules, and ``author_verdict`` applies the wrong-author-merge guards.
"""
from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from typing import Iterator, Optional

from . import policy

API = "https://api.openalex.org"
USER_AGENT = "scholarly-corpus-builder/0.1"  # generic: no personal contact details
SELECT = (
    "id,doi,title,publication_year,type,language,biblio,authorships,"
    "primary_topic,primary_location,best_oa_location,locations,is_paratext,is_retracted"
)

# Titles that mark non-papers (reviews, editorials, errata ...).
_NON_PAPER_TITLE = re.compile(
    r"^\s*(book\s+)?reviews?\b|\beditorial\b|\bobituar|\berrat(um|a)\b|\bcorrigend|"
    r"\bin memoriam\b|\bforeword\b|\bpreface\b|^\s*introduction\b.*\b(issue|volume|section)\b|"
    r"^\s*(reply|response|comment|rejoinder)\b|\bletter to the editor\b|"
    r"\bbook notes?\b|\bnotes on contributors\b|\b(table of )?contents\b|"
    r"\bslides?\b|\bposter\b|\babstracts?\b$|\bcover\b",
    re.I,
)


def short_id(url: Optional[str]) -> Optional[str]:
    """``https://openalex.org/A123`` -> ``A123`` (None-safe)."""
    return url.rsplit("/", 1)[-1] if url else None


def orcid_of(url: Optional[str]) -> Optional[str]:
    return url.rsplit("/", 1)[-1] if url else None


def page_count(biblio: Optional[dict]) -> Optional[int]:
    """Pages from first/last page when both are plain integers, else None."""
    if not biblio:
        return None
    try:
        a, b = int(biblio.get("first_page")), int(biblio.get("last_page"))
    except (TypeError, ValueError):
        return None
    n = b - a + 1
    return n if 1 <= n <= 400 else None


def norm_title(title: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (title or "").lower()).strip()


def _location_licence(loc: dict) -> Optional[str]:
    lic = (loc.get("license") or "").lower() or None
    return lic


# Function words of the languages that most often hide behind an "en" tag in OpenAlex
# (Afrikaans, Dutch, German, Romance languages) plus any Cyrillic letter, in a title.
_FOREIGN_TITLE = re.compile(
    r"(^|\s)(die|van|\u2019n|'n|oor|uit|vir|het|se|der|und|das|ein|eine|zur|zum|des|el|los|las|une|le|les|du|"
    r"della|il|nel|n\u00e3o|uma|dos)(\s|$)|[\u0400-\u04ff]", re.I)


def post_rules(c: dict, collection: str = "humanities") -> bool:
    """Rules added after smoke runs (see policy.EXCLUDED_*); applied on the compact records,
    so tightening needs no new catalogue requests. The science-only round needs the collection."""
    if c.get("host") in policy.EXCLUDED_HOSTS:
        return False
    if collection == "science":
        if urllib.parse.urlparse(c.get("url") or "").netloc.lower() in policy.EXCLUDED_URL_HOSTS_SCIENCE:
            return False
        if c.get("subfield") in policy.EXCLUDED_SUBFIELDS_SCIENCE and c.get("host") == "arXiv":
            return False
    return not _FOREIGN_TITLE.search(c.get("title") or "")


def pick_fulltext(work: dict) -> Optional[dict]:
    """Choose the location to fetch full text from, or None.

    Preference: a permitted-licence location with a PDF link, then an arXiv
    location (research-use class). A landing page without a PDF link is not a
    fetchable full text, so it never qualifies.
    """
    locs = list(work.get("locations") or [])
    for key in ("best_oa_location", "primary_location"):
        if work.get(key):
            locs.insert(0, work[key])
    for loc in locs:
        if not loc or not loc.get("is_oa") or not loc.get("pdf_url"):
            continue
        lic = _location_licence(loc)
        if lic in policy.PERMITTED_LICENCES:
            return {"url": loc["pdf_url"], "licence": lic,
                    "host": ((loc.get("source") or {}).get("display_name") or "")[:80],
                    "version": loc.get("version")}
    for loc in locs:
        src = short_id((loc.get("source") or {}).get("id"))
        if loc and src == policy.ARXIV_SOURCE_ID and loc.get("pdf_url"):
            return {"url": loc["pdf_url"], "licence": policy.ARXIV_TOU,
                    "host": "arXiv", "version": loc.get("version")}
    return None


def compact_work(work: dict) -> Optional[dict]:
    """One screened paper record, or None when the work cannot be a candidate.

    Metadata-only rules: single author with an OpenAlex author id and an ORCID,
    English, not paratext or retracted, article/preprint, a fetchable full text
    under a permitted licence, not obviously a review/editorial/erratum, and
    plausible length (page count when known).
    """
    auths = work.get("authorships") or []
    if len(auths) != 1 or work.get("is_paratext") or work.get("is_retracted"):
        return None
    if work.get("language") != "en" or work.get("type") not in ("article", "preprint"):
        return None
    a = auths[0]
    author = a.get("author") or {}
    aid = short_id(author.get("id"))
    orcids = {orcid_of(o) for o in (author.get("observed_orcids") or []) if o}
    for o in (author.get("orcid"), a.get("raw_orcid")):
        if o:
            orcids.add(orcid_of(o))
    if not aid or not orcids:
        return None
    title = work.get("title") or ""
    if not title or _NON_PAPER_TITLE.search(title):
        return None
    pages = page_count(work.get("biblio"))
    if pages is not None and pages < policy.MIN_PAGES_WHEN_KNOWN:
        return None
    ft = pick_fulltext(work)
    if ft is None:
        return None
    topic = work.get("primary_topic") or {}
    return {
        "work_id": short_id(work.get("id")),
        "doi": (work.get("doi") or "").replace("https://doi.org/", "") or None,
        "title": title[:200],
        "year": work.get("publication_year"),
        "pages": pages,
        "author_id": aid,
        "author_name": (a.get("raw_author_name") or author.get("display_name") or "")[:80],
        "orcids": sorted(orcids),
        "field": short_id((topic.get("field") or {}).get("id")),
        "subfield": short_id((topic.get("subfield") or {}).get("id")),
        "licence": ft["licence"],
        "url": ft["url"],
        "host": ft["host"],
        "version": ft["version"],
    }


def author_verdict(papers: list[dict]) -> tuple[bool, str, list[dict]]:
    """Apply the wrong-author-merge guards to one author's candidate papers.

    Returns (keep, reason, deduplicated papers). Guards, in order:
    more than one distinct ORCID observed on the OpenAlex id (a merge), a
    publication span over MAX_AUTHOR_SPAN_YEARS, a dominant subfield holding
    under half of the papers, and fewer than MIN_SCREEN_CANDIDATES after
    deduplicating multiple versions of one paper (same normalised title).
    """
    seen, uniq = set(), []
    for p in sorted(papers, key=lambda q: (q.get("year") or 0, q["work_id"])):
        key = norm_title(p["title"])
        if key in seen:
            continue
        seen.add(key)
        uniq.append(p)
    if len(uniq) < policy.MIN_SCREEN_CANDIDATES:
        return False, "too_few_candidates", uniq
    orcids = {o for p in uniq for o in p["orcids"]}
    if len(orcids) > policy.MAX_DISTINCT_ORCIDS:
        return False, "multiple_orcids", uniq
    years = [p["year"] for p in uniq if p.get("year")]
    if years and max(years) - min(years) > policy.MAX_AUTHOR_SPAN_YEARS:
        return False, "year_span", uniq
    subs = Counter(p["subfield"] for p in uniq if p.get("subfield"))
    if subs and max(subs.values()) / len(uniq) < policy.MIN_DOMINANT_SUBFIELD_SHARE:
        return False, "unrelated_fields", uniq
    return True, "ok", uniq


class OpenAlexClient:
    """Minimal OpenAlex client: retries 429/5xx, honours Retry-After, no key in code.

    A key, if the environment provides one (``OPENALEX_API_KEY``), is sent as a
    bearer token; deployments that inject credentials at the network layer need
    nothing here.
    """

    def __init__(self, api_key: Optional[str] = None, pause: float = 0.1):
        self.api_key = api_key
        self.pause = pause
        self.requests = 0

    def get(self, path: str, params: dict, tries: int = 6, max_rate_wait: int = 3600) -> dict:
        """GET with retries. A 429 is back-pressure, not failure: wait Retry-After and
        retry without spending a try (a new key is capped at ~$0.10 per 5 minutes)."""
        url = f"{API}{path}?{urllib.parse.urlencode(params)}"
        headers = {"User-Agent": USER_AGENT}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        attempt, waited = 0, 0
        while attempt < tries:
            self.requests += 1
            try:
                with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=90) as r:
                    data = json.load(r)
                time.sleep(self.pause)
                return data
            except urllib.error.HTTPError as e:
                if e.code == 429:
                    wait = int(e.headers.get("Retry-After", "5") or 5)
                    if wait > 900 or waited > max_rate_wait:
                        raise RuntimeError(f"OpenAlex budget exhausted; retry after {wait}s") from e
                    time.sleep(wait + 1)
                    waited += wait + 1
                    continue
                attempt += 1
                if e.code >= 500:
                    time.sleep(2 ** attempt)
                else:
                    raise
            except (urllib.error.URLError, TimeoutError, ConnectionError):
                attempt += 1
                time.sleep(2 ** attempt)
        raise RuntimeError(f"OpenAlex request failed after {tries} tries: {path}")

    def iter_works(self, filt: str) -> Iterator[dict]:
        """Cursor-page every work matching ``filt`` (needs a key for paging)."""
        cursor = "*"
        while cursor:
            d = self.get("/works", {"filter": filt, "per-page": 200, "cursor": cursor, "select": SELECT})
            yield from d.get("results", [])
            cursor = d.get("meta", {}).get("next_cursor")
            if not d.get("results"):
                break
