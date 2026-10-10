"""Contract for the live navy suite (demo/original/*.html).

Every page in the suite is parametrized in automatically, so a later task
that adds ``demo/original/students.html`` is held to the same rules without
touching this file, except to take its filename off ``PLANNED_PAGES``.

What the suite promises (docs/superpowers/plans/2026-10-10-live-navy-suite.md):
no third-party requests, none of the retired copy, the testing-phase label in
exactly one place (``live.js``), links that resolve, credited images, and no
em dash.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit

import pytest

# The existing pilot-mode static fixtures: demo/ mounted exactly as run.py does.
from tests.security.test_static_tree import mounted_app, mounted_pilot_client  # noqa: F401

ROOT = Path(__file__).resolve().parents[1]
DEMO = ROOT / "demo"
SUITE = DEMO / "original"
PAGES = sorted(SUITE.glob("*.html"))
PAGE_IDS = [p.name for p in PAGES]

NOTICE = (
    "Testing phase: Original is not yet validated on real student writing. "
    "Treat any result as a reason for a conversation, never as evidence."
)

# Filenames from the plan's page map that later tasks still have to build. The
# nav of an earlier page links to them at their final name, so a link to one of
# these is allowed while the file is missing. test_planned_pages_are_still_missing
# makes the list shrink: delete a name here in the commit that adds its page.
PLANNED_PAGES = {
    "students.html",
    "submissions.html",
    "writing-state.html",
    "packet.html",
    "baseline.html",
    "reports.html",
    "settings.html",
    "voice.html",
    "my-work.html",
    "library.html",
}

# Root-relative links a page may use without the target living in demo/original.
ALLOWED_ABSOLUTE = {"/bluebook/", "/index.html"}

BINARY_SUFFIXES = {".woff2", ".woff", ".jpeg", ".jpg", ".png", ".avif", ".webp", ".gif"}
TEXT_SUFFIXES = {".html", ".js", ".css", ".md", ".txt"}

THIRD_PARTY_HOSTS = (
    "fonts.googleapis.com",
    "fonts.gstatic.com",
    "cdn.jsdelivr.net",
    "unpkg.com",
)

BANNED_PHRASES = (
    "Integrity Operations",
    "seminary",
    "Seminary",
    "department",
    "keystroke",
    "typing rhythm",
    "Authorship Probability",
    "AI-Typical",
    "% authentic",
    "103 ",
    "fictional",
    "JetBrains",
)


def _suite_files() -> list[Path]:
    return sorted(p for p in SUITE.rglob("*") if p.is_file())


def _text_files() -> list[Path]:
    return [p for p in _suite_files() if p.suffix in TEXT_SUFFIXES]


def _code_files() -> list[Path]:
    """Files the browser loads or a person reads; licence text is excluded."""
    return [p for p in _text_files() if p.suffix != ".txt"]


class _Refs(HTMLParser):
    """href / src values of every tag, in document order."""

    def __init__(self) -> None:
        super().__init__()
        self.urls: list[str] = []

    def handle_starttag(self, tag, attrs):
        for name, value in attrs:
            if name in ("href", "src") and value:
                self.urls.append(value)


def _refs(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    urls: list[str] = []
    if path.suffix == ".html":
        parser = _Refs()
        parser.feed(text)
        urls.extend(parser.urls)
    urls.extend(re.findall(r"url\(\s*['\"]?([^)'\"]+?)['\"]?\s*\)", text))
    return urls


def _is_external(url: str) -> bool:
    return bool(urlsplit(url).scheme) or url.startswith("//")


@pytest.fixture(scope="module")
def live_js() -> str:
    return (SUITE / "live.js").read_text(encoding="utf-8")


def test_the_suite_has_pages():
    assert "index.html" in PAGE_IDS


@pytest.mark.parametrize("page", PAGES, ids=PAGE_IDS)
def test_page_makes_no_third_party_requests(page):
    text = page.read_text(encoding="utf-8")
    for host in THIRD_PARTY_HOSTS:
        assert host not in text, f"{page.name} mentions {host}"
    assert not re.search(r"<script[^>]+src=[\"'](?:https?:)?//", text), "remote script"
    assert not re.search(r"<link[^>]+href=[\"'](?:https?:)?//", text), "remote stylesheet"
    assert not re.search(r"@import|url\(\s*['\"]?(?:https?:)?//", text), "remote CSS"


@pytest.mark.parametrize("path", _code_files(), ids=lambda p: p.relative_to(SUITE).as_posix())
def test_no_suite_file_loads_from_a_third_party(path):
    text = path.read_text(encoding="utf-8")
    for host in THIRD_PARTY_HOSTS:
        assert host not in text, f"{path.name} mentions {host}"
    assert not re.search(r"url\(\s*['\"]?(?:https?:)?//", text), f"{path.name} loads remote CSS"


@pytest.mark.parametrize("page", PAGES, ids=PAGE_IDS)
def test_page_carries_none_of_the_retired_copy(page):
    text = page.read_text(encoding="utf-8")
    found = [phrase for phrase in BANNED_PHRASES if phrase in text]
    assert not found, f"{page.name} still contains {found}"


@pytest.mark.parametrize("path", _text_files(), ids=lambda p: p.relative_to(SUITE).as_posix())
def test_suite_files_carry_none_of_the_retired_copy(path):
    text = path.read_text(encoding="utf-8")
    found = [phrase for phrase in BANNED_PHRASES if phrase in text]
    assert not found, f"{path.name} contains {found}"


def test_testing_label_lives_once_in_live_js(live_js):
    assert live_js.count(NOTICE) == 1


@pytest.mark.parametrize("page", PAGES, ids=PAGE_IDS)
def test_testing_label_is_never_written_into_a_page(page):
    text = page.read_text(encoding="utf-8")
    assert NOTICE not in text
    assert "not yet validated on real student writing" not in text


def test_live_js_exposes_the_shared_interface(live_js):
    exported = live_js[live_js.index("window.Live = {") :]
    for key in (
        "TOKEN_KEYS",
        "NOTICE",
        "esc",
        "api",
        "session",
        "notices",
        "empty",
        "gate",
        "signOut",
    ):
        assert re.search(rf"\b{key}\s*:", exported), f"Live.{key} is not exported"
    for token_key in (
        "original_principal_token",
        "original_session_token",
        "original_role",
        "original_tenant",
        "original_name",
    ):
        assert f"'{token_key}'" in live_js


@pytest.mark.parametrize("path", [*PAGES, *sorted(SUITE.glob("*.css"))], ids=lambda p: p.name)
def test_relative_references_resolve_under_demo(path):
    demo = DEMO.resolve()
    for url in _refs(path):
        if url.startswith(("#", "data:", "mailto:", "tel:", "javascript:")) or _is_external(url):
            continue
        split = urlsplit(url)
        if split.path in ALLOWED_ABSOLUTE:
            continue
        if split.path.startswith("/"):
            target = (DEMO / split.path.lstrip("/")).resolve()
        else:
            target = (path.parent / split.path).resolve()
        if target.parent == SUITE.resolve() and target.name in PLANNED_PAGES:
            continue
        assert str(target).startswith(str(demo)), f"{path.name}: {url} leaves demo/"
        assert target.is_file(), f"{path.name}: {url} does not resolve to a file"


def test_planned_pages_are_still_missing():
    built = sorted(name for name in PLANNED_PAGES if (SUITE / name).exists())
    assert not built, f"{built} now exist: delete them from PLANNED_PAGES in this test file"


def test_every_image_is_credited():
    assets = SUITE / "assets"
    credits = (assets / "CREDITS.md").read_text(encoding="utf-8")
    rows = [line for line in credits.splitlines() if line.lstrip().startswith("|")]
    for image in sorted(p for p in assets.iterdir() if p.is_file() and p.name != "CREDITS.md"):
        assert any(f"`{image.name}`" in row for row in rows), f"{image.name} has no CREDITS.md row"


def test_no_em_dash_anywhere_in_the_suite():
    # U+2014 and U+2015, built from code points so this file carries neither.
    pattern = re.compile(f"[{chr(0x2014)}{chr(0x2015)}]")
    for path in _suite_files():
        if path.suffix in BINARY_SUFFIXES:
            continue
        assert not pattern.search(path.read_text(encoding="utf-8")), f"em dash in {path.name}"


def test_no_file_in_the_suite_exceeds_the_commit_limit():
    # .pre-commit-config.yaml: check-added-large-files --maxkb=700
    for path in _suite_files():
        assert path.stat().st_size <= 700 * 1024, f"{path.name} is over 700 KB"


@pytest.mark.parametrize(
    "url",
    [
        "/original/",
        "/original/live.js",
        "/original/suite.css",
        "/original/fonts.css",
        "/original/js/fingerprint.js",
        "/original/assets/radcliffe-night-stars.jpeg",
        "/original/fonts/ibm-plex-mono-latin-700-normal.woff2",
        "/bluebook/fonts.css",
    ],
)
def test_suite_is_served_on_a_real_deploy(mounted_pilot_client, url):  # noqa: F811
    assert mounted_pilot_client.get(url).status_code == 200, url


def test_original_root_serves_the_page_with_live_js(mounted_pilot_client):  # noqa: F811
    r = mounted_pilot_client.get("/original/")
    assert r.status_code == 200
    assert "live.js" in r.text
