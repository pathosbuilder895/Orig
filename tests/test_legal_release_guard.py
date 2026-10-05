"""Legal pages ship either clearly DRAFT or fully complete, never in between."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAGES = sorted((ROOT / "demo/legal").glob("*.html"))
EXPECTED_PAGES = {"privacy.html", "terms.html", "student-notice.html"}

# Tolerate extra classes and either quote style, e.g. class='draft note'.
_DRAFT_BANNER = re.compile(r"""class=["'][^"']*\bdraft\b""")
_BLANK = re.compile(r"""class=["'][^"']*\bfill\b""")
# The permanent version line, directly under each page's <h1> (not in the banner).
_VERSION_LINE = re.compile(r'<p class="meta">Version ([^<]+)</p>')


def _match(pattern: str, text: str, where: str, expected: str) -> str:
    found = re.search(pattern, text, re.M)
    assert found, f"{where}: expected a line of the form {expected}"
    return found.group(1)


def _server_version() -> str:
    text = (ROOT / "original/routers/auth.py").read_text()
    return _match(
        r'^TERMS_VERSION = "([^"]+)"',
        text,
        "original/routers/auth.py",
        'TERMS_VERSION = "<version>"',
    )


def _client_version() -> str:
    text = (ROOT / "demo/bluebook/Account.jsx").read_text()
    return _match(
        r"export const TERMS_VERSION = '([^']+)'",
        text,
        "demo/bluebook/Account.jsx",
        "export const TERMS_VERSION = '<version>'",
    )


def _page_version(page: Path, html: str) -> str:
    return _match(
        _VERSION_LINE.pattern,
        html,
        page.name,
        '<p class="meta">Version <version></p> directly under the <h1>',
    )


def test_server_and_client_record_the_same_terms_version():
    assert _server_version() == _client_version()


def test_the_three_legal_pages_are_all_present():
    # Without this the loop below passes vacuously if a page is renamed or removed.
    assert {page.name for page in PAGES} == EXPECTED_PAGES


def test_a_final_version_has_no_draft_banner_or_blanks():
    version = _server_version()
    for page in PAGES:
        html = page.read_text()
        has_blanks = bool(_BLANK.search(html))
        has_banner = bool(_DRAFT_BANNER.search(html))
        page_version = _page_version(page, html)
        assert page_version == version, (
            f"{page.name}: version line says {page_version!r} but TERMS_VERSION is {version!r}"
        )
        if version.endswith("-draft"):
            assert has_banner, f"{page.name}: draft version but no DRAFT banner"
        else:
            assert not has_blanks, f"{page.name}: final version {version} still has [blanks]"
            assert not has_banner, f"{page.name}: final version {version} still shows DRAFT"
