"""Legal pages ship either clearly DRAFT or fully complete, never in between."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAGES = sorted((ROOT / "demo/legal").glob("*.html"))


def _server_version() -> str:
    text = (ROOT / "original/routers/auth.py").read_text()
    return re.search(r'^TERMS_VERSION = "([^"]+)"', text, re.M).group(1)


def _client_version() -> str:
    text = (ROOT / "demo/bluebook/Account.jsx").read_text()
    return re.search(r"export const TERMS_VERSION = '([^']+)'", text).group(1)


def test_server_and_client_record_the_same_terms_version():
    assert _server_version() == _client_version()


def test_a_final_version_has_no_draft_banner_or_blanks():
    version = _server_version()
    for page in PAGES:
        html = page.read_text()
        has_blanks = 'class="fill"' in html
        has_banner = 'class="draft"' in html
        if version.endswith("-draft"):
            assert has_banner, f"{page.name}: draft version but no DRAFT banner"
        else:
            assert not has_blanks, f"{page.name}: final version {version} still has [blanks]"
            assert not has_banner, f"{page.name}: final version {version} still shows DRAFT"
            assert version in html, f"{page.name}: version line does not say {version}"
