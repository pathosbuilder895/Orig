"""Contract for the public landing page (demo/landing.html, served at /landing.html).

ADR-011 keeps the landing page public on every deploy. On 2026-10-11 the
Collections rename (#260) deleted it in a merge commit, believing it lived only
in #228, which had already merged. Nothing tested the page, so CI stayed green
and the pilot went on serving a 404 at /landing.html. These tests make that
loud: the page must exist, a real deploy must serve it, everything it loads
must exist, and no visible text may carry the old product name.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit

# The existing pilot-mode static fixtures: demo/ mounted exactly as run.py does.
from tests.security.test_static_tree import mounted_app, mounted_pilot_client  # noqa: F401

DEMO = Path(__file__).resolve().parents[1] / "demo"
LANDING = DEMO / "landing.html"

# Attributes whose values a visitor reads or hears (screen readers, tooltips,
# search results). id, class, href and data-* are identifiers, not text.
_READABLE_ATTRS = {"alt", "title", "aria-label", "content", "placeholder"}

_OLD_NAME = re.compile(r"blue\s?book", re.IGNORECASE)


class _Page(HTMLParser):
    """Collects the page's readable text and its local asset references."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.text: list[str] = []
        self.refs: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self._skip += 1
        for name, value in attrs:
            if value is None:
                continue
            if name in _READABLE_ATTRS:
                self.text.append(value)
            if name in ("src", "href"):
                self.refs.append(value)

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self._skip:
            self._skip -= 1

    def handle_data(self, data):
        # Comments go to handle_comment, so they never reach here.
        if not self._skip:
            self.text.append(data)


def _parse() -> _Page:
    page = _Page()
    page.feed(LANDING.read_text(encoding="utf-8"))
    return page


def test_landing_page_exists():
    assert LANDING.is_file(), "demo/landing.html is gone; ADR-011 keeps it public"


def test_landing_page_is_served_on_a_real_deploy(mounted_pilot_client):  # noqa: F811
    r = mounted_pilot_client.get("/landing.html")
    assert r.status_code == 200, r.text[:200]
    # NORTH_STAR rule 10: the page talks about Original, so it carries the label.
    assert "Testing phase" in r.text


def test_every_local_asset_the_page_loads_exists():
    missing = []
    for ref in _parse().refs:
        parts = urlsplit(ref)
        if parts.scheme or parts.netloc or not parts.path:
            continue  # external link, mailto:, or a same-page #anchor
        target = DEMO / parts.path.lstrip("/")
        if parts.path.endswith("/"):
            target = target / "index.html"
        if not target.exists():
            missing.append(ref)
    assert not missing, f"landing.html references missing files: {missing}"


def test_no_visible_text_uses_the_old_product_name():
    text = " ".join(_parse().text)
    hits = sorted({m.group(0) for m in _OLD_NAME.finditer(text)})
    assert not hits, f"visible text still says {hits}; the product is Collections (#260)"
    assert "Collections" in text
