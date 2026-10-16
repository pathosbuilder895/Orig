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

import datetime as dt
import json
import re
import shutil
import subprocess
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

# The T-01 caveat, in the words every page uses. It states the measured failure (small
# baselines false-alarm) and that Original is not validated on real writing, and points
# at no internal document. It is not the testing label (NOTICE), which lives only in
# live.js; it repeats one clause of it, so the uniqueness check below lets this sentence by.
T01_CAVEAT = "Small baselines can produce false alarms, and Original is not yet validated on real student writing."

# Filenames from the plan's page map that later tasks still have to build. The
# nav of an earlier page links to them at their final name, so a link to one of
# these is allowed while the file is missing. test_planned_pages_are_still_missing
# makes the list shrink: delete a name here in the commit that adds its page.
PLANNED_PAGES: set[str] = set()

# The student pages: a student's own writing voice and the piece they compare.
# They are not teacher pages, so the teacher account menu (Settings, Analysis
# (classic)) does not apply to them: theirs holds Sign out and nothing else.
STUDENT_PAGES = {"voice.html", "my-work.html"}

# Root-relative links a page may use without the target living in demo/original.
ALLOWED_ABSOLUTE = {"/bluebook/", "/index.html"}

BINARY_SUFFIXES = {".woff2", ".woff", ".jpeg", ".jpg", ".png", ".avif", ".webp", ".gif"}
TEXT_SUFFIXES = {".html", ".js", ".css", ".md", ".txt"}

EXTERNAL_SCHEMES = {"http", "https", "ws", "wss", "ftp"}

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
    # Bluebook's own integrity numbers are never shown in the suite.
    "ai_score",
    "aiscore",
)


def _suite_files() -> list[Path]:
    return sorted(p for p in SUITE.rglob("*") if p.is_file())


def _text_files() -> list[Path]:
    return [p for p in _suite_files() if p.suffix in TEXT_SUFFIXES]


def _code_files() -> list[Path]:
    """Files the browser loads or a person reads; licence text is excluded."""
    return [p for p in _text_files() if p.suffix != ".txt"]


class _Refs(HTMLParser):
    """(tag, url) for every href / src attribute, in document order, plus the
    text of every inline <script>."""

    def __init__(self) -> None:
        super().__init__()
        self.refs: list[tuple[str, str]] = []
        self.scripts: list[str] = []
        self._in_script = False

    def handle_starttag(self, tag, attrs):
        if tag == "script":
            self._in_script = True
            self.scripts.append("")
        for name, value in attrs:
            if name in ("href", "src") and value:
                self.refs.append((tag, value))

    def handle_endtag(self, tag):
        if tag == "script":
            self._in_script = False

    def handle_data(self, data):
        if self._in_script:
            self.scripts[-1] += data


# A URL written as a string literal in script code: an explicit scheme, or a
# protocol-relative host. (A bare '//' is not matched, so a quoted example of a
# bad path in a comment is not a finding.)
_JS_URL = (
    re.compile(r"""['"`]\s*((?:https?|wss?|ftp)://[^\s'"`]+)"""),
    re.compile(r"""['"`]\s*(//[\w.-]+\.\w[^\s'"`]*)"""),
)


def _refs(path: Path) -> list[tuple[str, str]]:
    """Every URL a file points at: tag attributes, CSS url() and @import (in
    any file, since a script can build a style), and URL literals in script
    code (a .js file, or an inline <script>)."""
    text = path.read_text(encoding="utf-8")
    refs: list[tuple[str, str]] = []
    scripts: list[str] = []
    if path.suffix == ".html":
        parser = _Refs()
        parser.feed(text)
        refs.extend(parser.refs)
        scripts = parser.scripts
    elif path.suffix == ".js":
        scripts = [text]
    refs.extend(("css", u) for u in re.findall(r"url\(\s*['\"]?([^)'\"]+?)['\"]?\s*\)", text))
    refs.extend(("css", u) for u in re.findall(r"@import\s+['\"]([^'\"]+)['\"]", text))
    for code in scripts:
        for pattern in _JS_URL:
            refs.extend(("js", u) for u in pattern.findall(code))
    return refs


def _normalise(url: str) -> str:
    """What a browser's URL parser sees: no tabs or newlines, backslash as slash."""
    return re.sub(r"[\t\r\n]", "", url).strip().replace("\\", "/")


def _is_external(url: str) -> bool:
    u = _normalise(url)
    return u.startswith("//") or urlsplit(u).scheme in EXTERNAL_SCHEMES


def _squash(text: str) -> str:
    """Whitespace-insensitive, case-insensitive form for phrase checks."""
    return " ".join(text.split()).lower()


@pytest.fixture(scope="module")
def live_js() -> str:
    return (SUITE / "live.js").read_text(encoding="utf-8")


def test_the_suite_has_pages():
    assert "index.html" in PAGE_IDS


@pytest.mark.parametrize("path", _code_files(), ids=lambda p: p.relative_to(SUITE).as_posix())
def test_no_suite_file_names_a_third_party_host(path):
    text = path.read_text(encoding="utf-8")
    for host in THIRD_PARTY_HOSTS:
        assert host not in text, f"{path.name} mentions {host}"


@pytest.mark.parametrize("path", _code_files(), ids=lambda p: p.relative_to(SUITE).as_posix())
def test_suite_files_carry_none_of_the_retired_copy(path):
    text = path.read_text(encoding="utf-8").lower()
    found = [phrase for phrase in BANNED_PHRASES if phrase.lower() in text]
    assert not found, f"{path.name} contains {found}"


def test_testing_label_lives_once_in_live_js(live_js):
    assert live_js.count(NOTICE) == 1


@pytest.mark.parametrize(
    "path",
    [p for p in _code_files() if p != SUITE / "live.js"],
    ids=lambda p: p.relative_to(SUITE).as_posix(),
)
def test_testing_label_is_written_nowhere_but_live_js(path):
    text = _squash(path.read_text(encoding="utf-8")).replace(_squash(T01_CAVEAT), "")
    assert _squash(NOTICE) not in text
    assert "not yet validated on real student writing" not in text


def test_live_js_checks_the_origin_of_every_request(live_js):
    # A tripwire, not a proof: it fails if the guard that keeps the bearer token
    # on this site is reverted to a look at the first characters of the path
    # ('/\\evil.com/x' and '/<TAB>/evil.com/x' slip past that).
    assert "new URL(" in live_js
    assert ".origin !== window.location.origin" in live_js


def test_live_js_reads_a_magic_link_student_session(live_js):
    # A Bluebook magic link stores bluebook_student_id and a session token but
    # no original_role; Live.gate must still send that visitor to /bluebook/.
    # The key also sits in EXTRA_KEYS (sign-out), so assert on the check itself.
    assert "read('bluebook_student_id')" in live_js
    assert "read('original_session_token')" in live_js


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
        "roster",
        "sealed",
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


@pytest.mark.parametrize("path", _code_files(), ids=lambda p: p.relative_to(SUITE).as_posix())
def test_references_stay_on_this_site_and_resolve_under_demo(path):
    demo = DEMO.resolve()
    for tag, raw in _refs(path):
        if _is_external(raw):
            # Only a plain link may leave the site; nothing may be loaded from it.
            assert tag == "a", f"{path.name}: <{tag}> loads {raw} from a third party"
            continue
        url = _normalise(raw)
        if url.startswith(("#", "data:", "mailto:", "tel:", "javascript:")):
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


# The suite's own scripts and stylesheets. A browser keeps a script it has seen,
# so a page loaded from cache next to a newer live.js would run the old code
# against new markup. Every page therefore asks for these files with one shared
# ?v= query; change the version (on every page at once) when any of them changes.
VERSIONED = ("live.js", "js/feature-data.js", "js/fingerprint.js", "suite.css", "fonts.css")


def _versioned_refs(path: Path) -> list[tuple[str, str, str]]:
    """(file, query, tag) for each href / src of a page that names one of the suite's
    own VERSIONED files. ../bluebook/fonts.css is Bluebook's file, not the suite's."""
    parser = _Refs()
    parser.feed(path.read_text(encoding="utf-8"))
    found = []
    for tag, raw in parser.refs:
        split = urlsplit(_normalise(raw))
        if split.scheme or split.netloc:
            continue
        target = (path.parent / split.path).resolve()
        for name in VERSIONED:
            if target == (SUITE / name).resolve():
                found.append((name, split.query, tag))
    return found


@pytest.mark.parametrize("path", PAGES, ids=lambda p: p.name)
def test_every_page_loads_the_suite_scripts_and_styles_with_the_shared_version(path):
    found = _versioned_refs(path)
    queries = {query for _, query, _ in found}
    assert len(queries) == 1, f"{path.name}: {sorted(queries)}"
    (query,) = queries
    assert re.fullmatch(r"v=[0-9A-Za-z._-]+", query), f"{path.name}: {query!r}"
    # Every page carries the suite's stylesheet, font file and shared script; the
    # others (feature-data.js, fingerprint.js) appear where the page uses them.
    assert {"live.js", "suite.css", "fonts.css"} <= {name for name, _, _ in found}, path.name
    assert len(found) == len({name for name, _, _ in found}), f"{path.name} loads one twice"


def test_all_pages_use_the_same_version_string():
    versions = {query for page in PAGES for _, query, _ in _versioned_refs(page)}
    assert len(versions) == 1, f"pages disagree on the version: {sorted(versions)}"


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
        "/original/students.html",
        "/original/baseline.html",
        "/original/writing-state.html",
        "/original/packet.html",
        "/original/settings.html",
        "/original/submissions.html",
        "/original/reports.html",
        "/original/voice.html",
        "/original/my-work.html",
        "/original/bluebook.html",
        "/original/live.js",
        "/original/suite.css",
        "/original/fonts.css",
        "/original/js/fingerprint.js",
        "/original/js/feature-data.js",
        "/original/assets/radcliffe-night-stars.jpeg",
        "/original/assets/st-andrews-quad.jpg",
        "/original/assets/radcliffe-observatory-watercolour.jpg",
        "/original/assets/radcliffe-interior.avif",
        "/original/assets/gonville-caius-facade.jpg",
        "/original/assets/all-souls-engraving-wide.jpg",
        "/original/assets/white-stag.jpg",
        "/original/assets/codrington-library.jpeg",
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


@pytest.mark.parametrize("path", _code_files(), ids=lambda p: p.relative_to(SUITE).as_posix())
def test_no_suite_file_reads_bluebooks_ai_score_or_flagged_status(path):
    # Bluebook's own integrity number and FLAGGED status are not shown here.
    text = path.read_text(encoding="utf-8")
    assert "FLAGGED" not in text, f"{path.name} mentions Bluebook's FLAGGED status"


@pytest.mark.parametrize("name", ["students.html", "submissions.html"])
def test_page_head_wraps_at_phone_width_so_its_button_is_never_clipped(name):
    # The title column and the action button share a flex row. At phone width the
    # row has to be allowed to wrap, or a long subtitle pushes the button off screen.
    page = (SUITE / name).read_text(encoding="utf-8")
    phone = page[page.index("@media (max-width:900px)") :]
    phone = phone[: phone.index("\n  }\n")]
    assert ".head{flex-wrap:wrap;align-items:flex-start;}" in phone


def test_students_page_loads_through_live_roster():
    page = (SUITE / "students.html").read_text(encoding="utf-8")
    assert "Live.roster()" in page
    # The loader is shared: the page keeps no copy of its requests.
    for endpoint in ("/readiness", "/bluebook/students"):
        assert endpoint not in page, f"students.html calls {endpoint} itself"


# ── Writing State (writing-state.html) ────────────────────────────────────────
# The page that shows an Original result: the testing label sits on it, purity
# is only ever shown inside a <details> that carries the T-01 caveat, and the
# report-only fields of the score response never reach the suite.


def test_writing_state_has_a_testing_notice_slot():
    page = (SUITE / "writing-state.html").read_text(encoding="utf-8")
    assert "data-testing-notice" in page


class _OutsideDetails(HTMLParser):
    """Text and attribute values outside every <details>, and the text of
    each top-level <details> block. Script bodies count as outside text, so a
    script cannot write purity anywhere."""

    def __init__(self) -> None:
        super().__init__()
        self.outside: list[str] = []
        self.blocks: list[str] = []
        self._depth = 0

    def handle_starttag(self, tag, attrs):
        values = [v for _, v in attrs if v]
        if tag == "details":
            if self._depth == 0:
                self.blocks.append("")
            self._depth += 1
        if self._depth:
            self.blocks[-1] += " ".join(values)
        else:
            self.outside.extend(values)

    def handle_endtag(self, tag):
        if tag == "details" and self._depth:
            self._depth -= 1

    def handle_data(self, data):
        if self._depth:
            self.blocks[-1] += data
        else:
            self.outside.append(data)


@pytest.mark.parametrize("path", _code_files(), ids=lambda p: p.relative_to(SUITE).as_posix())
def test_purity_trace_appears_only_inside_a_details_block_with_the_t01_caveat(path):
    text = path.read_text(encoding="utf-8")
    if path.suffix != ".html":
        assert "Tr(" not in text, f"{path.name}: Tr( outside an HTML <details> block"
        return
    parser = _OutsideDetails()
    parser.feed(text)
    outside = [chunk for chunk in parser.outside if "Tr(" in chunk]
    assert not outside, f"{path.name}: Tr( outside <details>"
    for block in parser.blocks:
        if "Tr(" in block:
            assert "T-01" in block, f"{path.name}: a <details> showing Tr( lacks the T-01 caveat"


def test_writing_state_shows_purity_with_its_caveat():
    # The guard above passes vacuously if the readout loses its purity row.
    parser = _OutsideDetails()
    parser.feed((SUITE / "writing-state.html").read_text(encoding="utf-8"))
    assert any("Tr(" in b and "T-01" in b for b in parser.blocks)


def test_writing_state_keeps_triage_local_and_names_each_analysis():
    # Until Original keeps analysis results (Task 12), "Looks fine" and "Have a
    # conversation" stay a local note, like professor.html's quick buttons: the
    # corrections endpoint writes calibration labels and mislabels a correct
    # no_action when manifests are off (original/routers/admin.py). Each score
    # call sends its own submission_id so analyses cannot share one.
    page = (SUITE / "writing-state.html").read_text(encoding="utf-8")
    assert "/submissions/" not in page
    assert "/correct" not in page
    assert "submission_id" in page
    assert "original_portfolio_" in page


# Report-only or retired fields of the score response (original/schemas.py
# Layer7OutputResponse). The suite never reads them, so it cannot show them.
REPORT_ONLY_FIELDS = (
    "authorship_probability",
    "ai_likelihood",
    "style_authorship",
    "fused_score",
    "typicality_",
)


@pytest.mark.parametrize("path", _code_files(), ids=lambda p: p.relative_to(SUITE).as_posix())
def test_no_suite_file_reads_report_only_score_fields(path):
    text = path.read_text(encoding="utf-8")
    found = [field for field in REPORT_ONLY_FIELDS if field in text]
    assert not found, f"{path.name} reads {found}"


def test_feature_data_lists_the_97_active_features_in_constants_order():
    from original.constants import ALL_FEATURE_CODES, TIER17_CODES, TIER18_CODES

    src = (SUITE / "js" / "feature-data.js").read_text(encoding="utf-8")
    codes = re.findall(r"\['([a-z0-9_]+)','", src)
    disabled = set(TIER17_CODES) | set(TIER18_CODES)
    assert codes == [c for c in ALL_FEATURE_CODES if c not in disabled]
    assert len(codes) == 97
    # Names and descriptions only: the design's invented values stay out.
    assert "base:" not in src and "sub:" not in src and "FLAGS" not in src


def test_settings_page_changes_the_password_and_offers_nothing_that_does_not_exist():
    page = (SUITE / "settings.html").read_text(encoding="utf-8")
    # POST /auth/password {current_password, new_password}, through the shared client.
    assert "Live.api('/auth/password'" in page
    assert "current_password" in page and "new_password" in page
    # A typed password is never logged or kept: no console output, no storage.
    for leak in ("console.", "localStorage", "sessionStorage"):
        assert leak not in page, f"settings.html uses {leak}"
    # A failed submit must not put the password in a URL (a form posts, it never GETs).
    assert 'method="post"' in page
    # There is no sensitivity setting and no LMS integration to configure.
    for gone in ("Flag Sensitivity", "sensitivity", "Canvas", "Blackboard"):
        assert gone not in page, f"settings.html still mentions {gone}"
    # The demo has no account to change.
    assert "The demo has no account; sign in on a real workspace to change your password." in page


def test_submissions_page_never_names_bluebooks_integrity_readings():
    # GET /bluebook/submissions returns an AI-likelihood number, a stylometric
    # number and a FLAGGED status for each sealed exam. None of them is shown,
    # so the page must not so much as name them. It does not copy fields out of
    # the response either: Live.sealed() does, through one allowlist.
    page = (SUITE / "submissions.html").read_text(encoding="utf-8")
    for word in ("ai_score", "aiscore", "stylometric", "flagged", "authenticity"):
        assert word not in page.lower(), f"submissions.html mentions {word}"
    assert "Live.sealed()" in page
    assert "FIELDS" not in page


def _inline_scripts(path: Path) -> str:
    parser = _Refs()
    parser.feed(path.read_text(encoding="utf-8"))
    return "\n".join(parser.scripts)


def test_submissions_page_names_no_bluebook_endpoint_itself():
    # The loader is shared (Live.sealed in live.js): the page makes no request.
    # A link to the Bluebook app ("/bluebook/") is not an endpoint.
    code = _inline_scripts(SUITE / "submissions.html")
    assert "Live.api(" not in code
    assert not re.findall(r"/bluebook/\w", code), "submissions.html names a Bluebook endpoint"


# The fields that may leave a /bluebook/submissions response. Pinned here so
# adding one is a decision made in a test diff.
SEALED_FIELDS = (
    "id",
    "exam_id",
    "student_id",
    "candidate",
    "exam",
    "course",
    "created_at",
    "late",
    "mark",
    "graded_at",
)


def test_live_js_has_one_sealed_exam_allowlist(live_js):
    found = re.findall(r"var SEALED_FIELDS = \[([^\]]*)\]", live_js)
    assert len(found) == 1
    assert tuple(re.findall(r"'([a-z_]+)'", found[0])) == SEALED_FIELDS
    # The allowlist is the only way a field is copied: no second list of
    # submission fields anywhere in the suite.
    for path in _code_files():
        text = path.read_text(encoding="utf-8")
        if path == SUITE / "live.js":
            assert text.count("'candidate'") == 1
        else:
            assert "'candidate'" not in text, f"{path.name} keeps its own field list"
            assert "const FIELDS" not in text, f"{path.name} keeps its own field list"


# The sealed-exam LIST route, GET /bluebook/submissions. The routes under it
# (/bluebook/submissions/{id}/baseline, approve and undo) are other endpoints.
SEALED_LIST_ROUTE = re.compile(r"/bluebook/submissions(?![\w/])")


def test_the_sealed_exam_list_route_pattern_tells_the_list_from_the_routes_under_it():
    for named in (
        "api('/bluebook/submissions')", 'fetch("/bluebook/submissions")', "`/bluebook/submissions`",
        "'/bluebook/submissions?limit=5'", "GET /bluebook/submissions response",
    ):
        assert SEALED_LIST_ROUTE.search(named), named
    for other in (
        "'/bluebook/submissions/'+enc(id)+'/baseline'", "/bluebook/submissions/x1/baseline",
        "/bluebook/students", "/bluebook/exams/e1/baseline",
    ):
        assert not SEALED_LIST_ROUTE.search(other), other


def test_no_file_but_live_js_names_the_sealed_exam_list_route(live_js):
    # Every field of a sealed exam reaches a page through Live.sealed()'s one
    # allowlist, so only live.js may ask for the list. A page that fetched it
    # itself would hold Bluebook's integrity readings, status and paper text.
    assert live_js.count("api('/bluebook/submissions')") == 1
    named = [
        path.relative_to(SUITE).as_posix()
        for path in _code_files()
        if path != SUITE / "live.js" and SEALED_LIST_ROUTE.search(path.read_text(encoding="utf-8"))
    ]
    assert not named, f"{named} name the sealed exam list route; call Live.sealed() instead"


def test_reports_page_counts_only_what_live_roster_returns():
    page = (SUITE / "reports.html").read_text(encoding="utf-8")
    assert "Live.roster()" in page
    assert "Live.sealed()" in page
    # The loader is shared, and this page reads no other endpoint: its numbers are
    # counts of the roster, the server's verdicts and the sealed exams' dates.
    assert "Live.api(" not in page
    for endpoint in ("/readiness", "/bluebook/students", "/score"):
        assert endpoint not in page, f"reports.html calls {endpoint} itself"
    # Cards with no stored source say so instead of showing a number.
    assert page.count("Appears once Original keeps analysis results") >= 3


def test_reports_page_gives_no_unsourced_guidance_about_take_home_writing():
    page = (SUITE / "reports.html").read_text(encoding="utf-8")
    for gone in ("Take-home essays", "Higher is context", "more time and sources", "worry on its own"):
        assert gone not in page, f"reports.html still says {gone!r}"
    # What the repo's docs support: conditions differ, and a difference is a
    # reason to talk, not evidence.
    assert (
        "Writing done under different conditions from a student's baseline, such as at home "
        "rather than in class, can read differently for ordinary reasons. A difference is "
        "context for a conversation, not evidence."
    ) in page


def test_reports_page_says_when_a_load_failed_and_how_readiness_was_missed():
    page = (SUITE / "reports.html").read_text(encoding="utf-8")
    assert "Nothing on file yet" not in page
    assert "Readiness could not be read for " in page
    assert "Readiness was not checked for " in page


def _node_major() -> int | None:
    """The major version of the installed ``node``, or None when there is none."""
    node = shutil.which("node")
    if node is None:
        return None
    try:
        out = subprocess.run([node, "--version"], capture_output=True, text=True, timeout=30).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    found = re.match(r"v(\d+)\.", out.strip())
    return int(found.group(1)) if found else None


# The harness below uses fetch-shaped stubs, URL and Headers: node 18 or newer.
needs_node = pytest.mark.skipif(
    (_node_major() or 0) < 18, reason="node 18 or newer is not installed"
)


# ── Conversation Packet (packet.html) ─────────────────────────────────────────
# A printable page that shows an Original result. The testing label sits at the
# top on screen and again in a print footer that repeats on every printed page;
# the label's text lives only in live.js, so the page carries two empty slots.


def _packet() -> str:
    return (SUITE / "packet.html").read_text(encoding="utf-8")


def _media_print_block(page: str) -> str:
    """The text of the page's @media print { ... } block, braces matched."""
    start = page.index("@media print")
    depth = 0
    for i in range(page.index("{", start), len(page)):
        depth += {"{": 1, "}": -1}.get(page[i], 0)
        if depth == 0:
            return page[start : i + 1]
    raise AssertionError("unclosed @media print block")


def test_packet_has_a_testing_notice_slot_on_screen_and_a_print_footer_that_shows_it():
    page = _packet()
    # Two slots, both empty in the file: Live.notices() fills them from live.js.
    assert page.count('data-testing-notice="on-paper"></div>') == 2
    # The second slot sits in the table footer the print rule turns on.
    assert re.search(r'<tfoot class="print-notice"[^>]*>.*?data-testing-notice', page, re.S)
    # Hidden on screen...
    assert re.search(r"\.print-notice\s*\{\s*display\s*:\s*none", page.replace(_media_print_block(page), ""))
    # ...and shown by the print rule, which also drops the on-screen shell.
    printed = _media_print_block(page)
    assert re.search(r"\.print-notice\s*\{\s*display\s*:\s*table-footer-group", printed)
    assert re.search(r"nav\s*,\s*\.chrome\s*\{\s*display\s*:\s*none", printed)


def test_packet_reads_what_writing_state_stores_and_nothing_else_about_the_result():
    page = _packet()
    state = (SUITE / "writing-state.html").read_text(encoding="utf-8")
    # One key, one shape: the producer writes it, this page reads it.
    for needle in ("original_last_result", "original_writing_state"):
        assert needle in state and needle in page, needle
    assert "sessionStorage.getItem(STORE_KEY)" in page
    # The packet never scores or corrects anything itself.
    for endpoint in ("/score", "/correct", "/baseline"):
        assert endpoint not in page, f"packet.html calls {endpoint}"
    # The baseline list comes from the student's own record.
    assert "Live.api('/students/'+encodeURIComponent(id))" in page
    # The stored analysis names a student, so it does not outlive a sign-out.
    assert "removeItem(STORE_KEY)" in page


def test_packet_is_a_conversation_packet_with_no_cases_quotes_or_filled_in_lines():
    page = _packet()
    assert "<title>Original · Conversation packet</title>" in page
    title = re.search(r"<title>(.*?)</title>", page).group(1).lower()
    assert "flag" not in title
    # No case numbers, no quoted passages (no text positions exist to quote).
    assert not re.search(r"\bcase\s+(?:no\.?\s*)?[A-Z]*-?\d", page, re.I)
    assert "<mark" not in page
    # Outcome and signature are blank form lines for the teacher, never data.
    assert page.count('<div class="line"></div>') == 2
    assert "Teacher signature" in page and "Outcome of the conversation" in page
    assert "<input" not in page and "<textarea" not in page
    # Without a stored result the page sends the teacher back to Writing State.
    assert "Run an analysis on the Writing State page first" in page
    assert "writing-state.html" in page


# ── Teachers land on these pages; the old page stays one click away ───────────
# Owner decision 2026-10-10: sign-in sends a teacher to /original/. The old
# professor.html stays reachable as "Analysis (classic)" until these pages cover
# it. The account menu markup is written out on every page (no templating), so
# the check runs over every page in the suite, present and future.


class _AccountMenu(HTMLParser):
    """The (href, text) of every link inside the element with class ``me-menu``,
    in document order. The text is the link's visible text only (an icon's
    markup carries none)."""

    def __init__(self) -> None:
        super().__init__()
        self.links: list[tuple[str, str]] = []
        self._depth = 0  # open elements inside the menu; 0 = not in the menu
        self._link: list | None = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if self._depth:
            self._depth += 1
            if tag == "a":
                self._link = [attrs.get("href") or "", ""]
        elif "me-menu" in (attrs.get("class") or "").split():
            self._depth = 1

    def handle_endtag(self, tag):
        if not self._depth:
            return
        if tag == "a" and self._link is not None:
            self.links.append((self._link[0], " ".join(self._link[1].split())))
            self._link = None
        self._depth -= 1

    def handle_data(self, data):
        if self._depth and self._link is not None:
            self._link[1] += data


def _account_menu(path: Path) -> list[tuple[str, str]]:
    parser = _AccountMenu()
    parser.feed(path.read_text(encoding="utf-8"))
    return parser.links


@pytest.mark.parametrize(
    "path", [p for p in PAGES if p.name not in STUDENT_PAGES], ids=lambda p: p.name
)
def test_account_menu_offers_the_classic_analysis_page_after_settings(path):
    links = _account_menu(path)
    assert links, f"{path.name} has no account menu"
    texts = [text for _, text in links]
    assert texts.count("Analysis (classic)") == 1, f"{path.name}: {texts}"
    classic = texts.index("Analysis (classic)")
    assert links[classic][0] == "/professor.html"
    assert classic > 0 and texts[classic - 1] == "Settings", f"{path.name}: {texts}"


@pytest.mark.parametrize("name", sorted(STUDENT_PAGES))
def test_student_account_menu_is_sign_out_only(name):
    # A student has no Settings page and no classic analysis page; both are
    # teacher tools, so the menu holds Sign out and nothing else.
    links = _account_menu(SUITE / name)
    assert [text for _, text in links] == ["Sign out"], f"{name}: {links}"


def test_every_page_is_either_a_teacher_page_or_a_student_page():
    # The two rules above are complementary: a page that is in neither set
    # would be held to the teacher rule, so a student page must be named.
    assert STUDENT_PAGES <= set(PAGE_IDS)


def _sign_in_redirect() -> str:
    html = (DEMO / "index.html").read_text(encoding="utf-8")
    found = re.findall(r"window\.location\.href\s*=\s*([^;]+);", html)
    assert len(found) == 1, "index.html must have exactly one post-sign-in redirect"
    return " ".join(found[0].split())


def test_sign_in_sends_a_teacher_to_the_new_original_pages():
    # Roles other than operator and admin (a teacher is role "professor") end up
    # at the last alternative, which is the suite's front page, not professor.html.
    assert _sign_in_redirect() == (
        "role === 'operator' ? 'operator.html' : role === 'admin' ? 'admin.html' "
        ": products && products.indexOf('original') < 0 ? 'bluebook/' : 'original/'"
    )
    # ...and every page it can name has to resolve to a real page under demo/.
    assert (DEMO / "original" / "index.html").is_file()
    assert (DEMO / "bluebook" / "index.html").is_file()
    assert (DEMO / "operator.html").is_file() and (DEMO / "admin.html").is_file()


def _sign_in_redirect_code() -> str:
    """The page's own code from the role to the redirect, with the assignment to
    window.location.href turned into a return, so a test can run it on a login response."""
    html = (DEMO / "index.html").read_text(encoding="utf-8")
    found = re.search(
        r"(const role = data\.role \|\| 'professor';.*?)window\.location\.href\s*=\s*([^;]+);", html, re.S
    )
    assert found, "index.html's post-sign-in redirect moved"
    return found.group(1) + "return " + found.group(2) + ";"


def _redirect_for(login_response: dict) -> str:
    run = subprocess.run(
        [
            shutil.which("node"),
            "-e",
            "process.stdout.write(String(new Function('data', 'localStorage', process.argv[1])"
            "(JSON.parse(process.argv[2]), { setItem() {} })))",
            _sign_in_redirect_code(),
            json.dumps(login_response),
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert run.returncode == 0, run.stderr
    return run.stdout


BOTH = ["bluebook", "original"]  # the order the server sends: sorted


@needs_node
@pytest.mark.parametrize(
    "response,target",
    [
        ({"role": "professor", "products": BOTH}, "original/"),
        ({"role": "professor", "products": ["original"]}, "original/"),
        # A workspace with no Original goes straight to Bluebook.
        ({"role": "professor", "products": ["bluebook"]}, "bluebook/"),
        # The role is "professor" when the response names none.
        ({"products": ["bluebook"]}, "bluebook/"),
        # A response that lists no products is not read as "no Original".
        ({"role": "professor"}, "original/"),
        ({"role": "professor", "products": []}, "original/"),
        ({"role": "professor", "products": "bluebook"}, "original/"),
        # Admins and operators keep their own pages whatever the workspace holds.
        ({"role": "admin", "products": ["bluebook"]}, "admin.html"),
        ({"role": "admin", "products": BOTH}, "admin.html"),
        ({"role": "operator", "products": ["bluebook"]}, "operator.html"),
        ({"role": "operator"}, "operator.html"),
    ],
    ids=[
        "teacher-both", "teacher-original-only", "teacher-bluebook-only", "no-role-bluebook-only",
        "no-products", "empty-products", "products-not-a-list", "admin-bluebook-only", "admin-both",
        "operator-bluebook-only", "operator-no-products",
    ],
)
def test_sign_in_redirect_evaluates_to_the_right_page(response, target):
    assert _redirect_for(response) == target


def test_sign_in_remembers_the_workspace_products_for_bluebook():
    # Bluebook reads original_products (demo/bluebook/components.jsx, products()) and
    # defaults to "Original is on" without it, so a Bluebook-only teacher would see an
    # Original link until Bluebook's first refresh.
    html = (DEMO / "index.html").read_text(encoding="utf-8")
    assert "localStorage.setItem('original_products', JSON.stringify(products))" in html
    assert "original_products" in (DEMO / "bluebook" / "components.jsx").read_text(encoding="utf-8")


def test_demo_professor_pill_opens_the_new_original_pages():
    html = (DEMO / "index.html").read_text(encoding="utf-8")
    pill = re.findall(r'<a href="([^"]+)" class="role-pill prof">', html)
    assert pill == ["original/"]


@pytest.mark.parametrize("name", ["Dashboard.jsx", "TeacherWorkspace.jsx", "bluebook.bundle.js"])
def test_bluebooks_original_link_opens_the_new_pages(name):
    # The bundle is what production serves; the sources must agree with it.
    text = (DEMO / "bluebook" / name).read_text(encoding="utf-8")
    assert "'../original/'" in text or '"../original/"' in text, name
    assert "../professor.html" not in text, f"{name} still links the old page"


# ── Live.roster and Live.sealed, run for real under node ──────────────────────
# live.js is plain browser script with no module system, so these run it in a
# bare `node` with a stubbed window, document and fetch. They need only node
# 18+ (global fetch types are not used; URL and Headers are).

PRELUDE = r"""
const fs = require('fs');
const sc = JSON.parse(fs.readFileSync(0, 'utf8'));
const src = fs.readFileSync(sc.live, 'utf8');
function store(initial) {
  const m = new Map(Object.entries(initial || {}));
  return {
    getItem(k) { return m.has(k) ? m.get(k) : null; },
    setItem(k, v) { m.set(k, String(v)); },
    removeItem(k) { m.delete(k); },
    key(i) { const ks = Array.from(m.keys()); return i < ks.length ? ks[i] : null; },
    get length() { return m.size; },
    keys() { return Array.from(m.keys()); },
  };
}
const replaced = [];
const blocked = new Proxy({}, { get() { throw new Error('storage is blocked'); } });
const window = {
  location: { href: 'http://suite.test/original/students.html', origin: 'http://suite.test', replace(u) { replaced.push(u); } },
  localStorage: sc.blockStorage ? blocked : store(sc.local),
  sessionStorage: sc.blockStorage ? blocked : store(sc.session),
};
// A document just big enough to run a page's script: elements are plain
// objects that remember what the page wrote into them. The tab buttons the
// reports page builds with innerHTML are parsed back out of it, so a test can
// press one.
const tabButtons = new Map();
function makeEl(id) {
  const e = {
    id, textContent: '', innerHTML: '', className: '', hidden: false, style: {}, tabIndex: 0,
    offsetLeft: 0, offsetWidth: 600, offsetHeight: 20, attrs: {}, handlers: {}, children: [],
    classList: { add() {}, remove() {}, toggle() {}, contains() { return false; } },
    addEventListener(type, fn) { (this.handlers[type] = this.handlers[type] || []).push(fn); },
    setAttribute(k, v) { this.attrs[k] = String(v); },
    getAttribute(k) { return k in this.attrs ? this.attrs[k] : null; },
    appendChild(c) { this.children.push(c); return c; },
    querySelector() { return makeEl(); },
    querySelectorAll(sel) {
      if (id === 'course-tabs' && sel === '.ctab') {
        return Array.from(this.innerHTML.matchAll(/data-c="([^"]*)"/g)).map((m) => {
          if (!tabButtons.has(m[1])) tabButtons.set(m[1], makeEl('tab:' + m[1]));
          const b = tabButtons.get(m[1]);
          b.attrs['data-c'] = m[1];
          return b;
        });
      }
      return [];
    },
    focus() {},
  };
  return e;
}
const elements = new Map();
const document = {
  readyState: 'complete',
  getElementById(id) { if (!elements.has(id)) elements.set(id, makeEl(id)); return elements.get(id); },
  createElement() { return makeEl(); },
  querySelector(sel) { return this.getElementById('query:' + sel); },
  querySelectorAll() { return []; },
  addEventListener() {},
};
let active = 0, max = 0;
const calls = [];
const auths = [];
const bodies = [];
function route(path) {
  let m;
  if (sc.routes && Object.prototype.hasOwnProperty.call(sc.routes, path)) return sc.routes[path];
  if (path === '/health') return sc.health || [200, { environment: 'demo' }];
  if (path === '/me/voice') return sc.meVoice || [404, {}];
  if (path === '/me/work') return sc.meWork || [404, {}];
  if (path === '/auth/me') return sc.me || [401, {}];
  if (path === '/students') return sc.students;
  if ((m = path.match(/^\/students\/(.+)\/readiness$/))) {
    return (sc.readiness || {})[decodeURIComponent(m[1])] || sc.readinessDefault || [404, { detail: 'x' }];
  }
  if (path === '/bluebook/students') return sc.bbStudents || [200, { students: [] }];
  if (path === '/bluebook/submissions') return sc.bbSubmissions || [200, { submissions: [] }];
  if (path === '/bluebook/exams') return sc.bbExams || [200, { exams: [] }];
  return [404, {}];
}
const matches = (list, path) => (list || []).some((re) => new RegExp(re).test(path));
function fakeFetch(href, init) {
  const path = new URL(href).pathname;
  calls.push(path);
  auths.push(init && init.headers && typeof init.headers.get === 'function' ? init.headers.get('Authorization') : null);
  bodies.push(init && init.body ? init.body : null);
  if (matches(sc.throwOn, path)) throw new Error('fetch threw');
  active++;
  max = Math.max(max, active);
  const [status, body] = route(path);
  const bad = matches(sc.rejectOn, path);
  return new Promise((resolve, reject) => setTimeout(() => {
    active--;
    if (bad) { reject(new Error('network down')); return; }
    resolve({ ok: status >= 200 && status < 300, status, text: () => Promise.resolve(JSON.stringify(body)) });
  }, 5));
}
new Function('window', 'document', 'fetch', src)(window, document, fakeFetch);
"""

LIVE_TAIL = r"""
// A Map does not survive JSON, so it is written as its list of entries.
const plain = (r) => Object.assign({}, r, { names: Array.from(r.names), exams: Array.from(r.exams) });
// Adding to a frozen array throws, in sloppy mode too.
const pushThrows = (list) => { try { list.push({}); return false; } catch (e) { return e instanceof TypeError; } };
(async () => {
  const out = {};
  if (sc.call === 'signOut') {
    window.Live.signOut();
    if (!sc.blockStorage) {
      out.local = window.localStorage.keys();
      out.session = window.sessionStorage.keys();
    }
  } else if (sc.call === 'sealed') {
    const sealed = await window.Live.sealed();
    out.result = plain(sealed);
    out.frozen = {
      result: Object.isFrozen(sealed),
      submissions: Object.isFrozen(sealed.submissions),
      rows: sealed.submissions.every((r) => Object.isFrozen(r)),
      pushThrows: pushThrows(sealed.submissions),
    };
  } else if (sc.call === 'rosterTwice') {
    // Two callers at once, then a third after the load has finished.
    const [a, b] = await Promise.all([window.Live.roster(), window.Live.roster()]);
    const c = await window.Live.roster();
    out.result = a;
    out.sameObject = a === b && b === c;
  } else if (sc.call === 'both') {
    const [roster, sealed, again] = await Promise.all([window.Live.roster(), window.Live.sealed(), window.Live.sealed()]);
    out.result = roster;
    out.sealed = plain(sealed);
    out.sameObject = sealed === again;
  } else {
    const roster = await window.Live.roster();
    out.result = roster;
    out.frozen = {
      result: Object.isFrozen(roster),
      students: Object.isFrozen(roster.students),
      rows: roster.students.every((s) => Object.isFrozen(s)),
      courses: roster.students.every((s) => Object.isFrozen(s.courses) && s.courses.every((c) => Object.isFrozen(c))),
      submissions: Object.isFrozen(roster.submissions),
      submissionRows: roster.submissions.every((r) => Object.isFrozen(r)),
      pushThrows: pushThrows(roster.students),
    };
  }
  process.stdout.write(JSON.stringify(Object.assign(out, { max, calls, replaced })));
})();
"""

PAGE_TAIL = r"""
const page = fs.readFileSync(sc.page, 'utf8');
const scripts = Array.from(page.matchAll(/<script>([\s\S]*?)<\/script>/g)).map((m) => m[1]);
if (scripts.length !== 1) throw new Error('expected one inline script, found ' + scripts.length);
window.matchMedia = () => ({ matches: true });  // no animation timers
// Strict mode: a page that writes into a frozen shared result throws here
// instead of being ignored.
new Function('window', 'document', 'Live', "'use strict';\n" + scripts[0])(window, document, window.Live);
const el = (id) => document.getElementById(id);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const snap = () => ({
  headline: el('headline').innerHTML,
  termD: el('term-d').textContent,
  tabNote: { text: el('tab-note').textContent, hidden: el('tab-note').hidden },
  tabs: el('course-tabs').innerHTML,
  reviewed: [el('k3-v').textContent, el('k3-m').textContent],
  ready: [el('k4-v').textContent, el('k4-m').textContent],
});
(async () => {
  for (let i = 0; i < 500 && !el('headline').innerHTML; i++) await sleep(10);
  const snaps = [snap()];
  for (const key of sc.clicks || []) {
    const btn = tabButtons.get(key);
    if (!btn) throw new Error('no tab ' + key + ' among ' + Array.from(tabButtons.keys()));
    btn.handlers.click.forEach((fn) => fn());
    snaps.push(snap());
  }
  process.stdout.write(JSON.stringify({ snaps, calls }));
})();
"""

HARNESS = PRELUDE + LIVE_TAIL
PAGE_HARNESS = PRELUDE + PAGE_TAIL


def _roster(**scenario) -> dict:
    run = subprocess.run(
        [shutil.which("node"), "-e", HARNESS],
        input=json.dumps({"live": str(SUITE / "live.js"), **scenario}),
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert run.returncode == 0, run.stderr
    # Node exits with no output when a load never finishes (its event loop drains).
    assert run.stdout, "the load never finished"
    return json.loads(run.stdout)


def _page(page: str, **scenario) -> dict:
    """Run one inline page script under node against stubbed endpoints."""
    run = subprocess.run(
        [shutil.which("node"), "-e", PAGE_HARNESS],
        input=json.dumps({"live": str(SUITE / "live.js"), "page": str(SUITE / page), **scenario}),
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert run.returncode == 0, run.stderr
    assert run.stdout, "the page never finished loading"
    return json.loads(run.stdout)


def _ready(verdict: str, auth: int = 5, samples: int = 5) -> list:
    return [200, {"verdict": verdict, "authenticated_count": auth, "sample_count": samples}]


@needs_node
def test_roster_asks_readiness_of_the_first_60_and_never_more_than_6_at_a_time():
    ids = [f"s{i:02d}" for i in range(70)]
    out = _roster(students=[200, {"students": ids, "roster": None}], readinessDefault=_ready("ready"))
    readiness = [c for c in out["calls"] if c.endswith("/readiness")]
    assert len(readiness) == 60
    # Exactly 6: the limiter is used to its full width, and never past it.
    assert out["max"] == 6
    res = out["result"]
    assert res["ok"] and not res["scoped"]
    assert [s["id"] for s in res["students"]] == ids
    assert res["beyondCap"] == 10
    assert [s["verdict"] for s in res["students"][:60]] == ["ready"] * 60
    assert [s["verdict"] for s in res["students"][60:]] == [None] * 10
    # An ids-only list takes its counts from the readiness response.
    assert res["students"][0]["counted"] == 5 and res["students"][0]["samples"] == 5
    assert res["students"][65]["counted"] is None


@needs_node
@pytest.mark.parametrize(
    "failing",
    [
        {"rejectOn": ["/readiness$"]},
        {"throwOn": ["/readiness$"]},
        {"rejectOn": ["^/bluebook/"]},
        {"rejectOn": ["^/students/.+/readiness$", "^/bluebook/"], "throwOn": ["^/bluebook/exams$"]},
    ],
    ids=["readiness-rejects", "readiness-throws", "bluebook-rejects", "mixed"],
)
def test_a_failing_fetch_with_more_than_6_queued_does_not_stall(failing):
    # 70 students queue 60 readiness calls behind 6 slots. A call that rejects
    # or throws must still give its slot back, or everything behind it waits
    # forever (the page would sit on "Loading").
    ids = [f"s{i:02d}" for i in range(70)]
    out = _roster(students=[200, {"students": ids, "roster": None}], readinessDefault=_ready("ready"), **failing)
    res = out["result"]
    assert res["ok"] and len(res["students"]) == 70
    assert len([c for c in out["calls"] if c.endswith("/readiness")]) == 60
    assert out["max"] <= 6
    if "readiness" in str(failing):
        assert [s["verdict"] for s in res["students"]] == [None] * 70
    if "bluebook" in str(failing):
        assert res["bluebook"] == "error" and res["sealedToReview"] is None


@needs_node
def test_roster_reports_the_servers_verdict_and_treats_ids_as_ids():
    roster = [
        {"id": "constructor", "name": "Ada", "authenticated_count": 6, "sample_count": 7},
        {"id": "__proto__", "name": "", "authenticated_count": 2, "sample_count": 2},
        {"id": "ten:a", "name": "Cy", "authenticated_count": None, "sample_count": 1},
    ]
    out = _roster(
        students=[200, {"students": [r["id"] for r in roster], "roster": roster}],
        readiness={
            "constructor": _ready("ready"),
            "__proto__": _ready("banana"),  # not one of the server's three words
            "ten:a": [500, {"detail": "boom"}],
        },
        bbStudents=[
            200,
            {
                "students": [
                    {
                        "student_id": "constructor",
                        "email": "ada@example.org",
                        "last_submitted_at": "2026-10-01T10:00:00Z",
                        "courses": [
                            {"course_id": "c1", "code": "THEO 301", "name": "Theology"},
                            {"course_id": "c2", "code": "", "name": "Biblical studies"},
                            {"course_id": "c3", "code": "THEO 301", "name": "Same label again"},
                        ],
                    },
                    {"student_id": "ten:a", "email": None, "courses": []},
                ]
            },
        ],
        bbSubmissions=[
            200,
            {
                "submissions": [
                    {"id": "b1", "student_id": "constructor", "created_at": "2026-10-01T10:00:00Z", "graded_at": "2026-10-02T10:00:00Z", "ai_score": 0.9, "status": "FLAGGED"},
                    {"id": "b2", "student_id": "constructor", "created_at": "2026-10-03T10:00:00Z", "graded_at": None},
                    {"id": "b3", "student_id": "ten:a", "created_at": "2026-09-20T10:00:00Z", "graded_at": None},
                ]
            },
        ],
    )
    res = out["result"]
    assert res["ok"] and res["scoped"] and res["bluebook"] == "ok" and not res["bluebookOff"]
    by_id = {s["id"]: s for s in res["students"]}
    assert [s["name"] for s in res["students"]] == ["Ada", "__proto__", "Cy"]  # no name: the id
    assert {i: s["verdict"] for i, s in by_id.items()} == {"constructor": "ready", "__proto__": None, "ten:a": None}
    ada = by_id["constructor"]
    assert ada["email"] == "ada@example.org"
    assert ada["courses"] == [
        {"id": "c1", "code": "THEO 301", "name": "Theology"},
        {"id": "c2", "code": "", "name": "Biblical studies"},
    ]
    assert (ada["counted"], ada["samples"]) == (6, 7)
    assert (ada["sealed"], ada["pending"]) == (2, 1)
    assert ada["lastSealed"] == "2026-10-01T10:00:00Z"
    assert by_id["__proto__"]["email"] is None and by_id["__proto__"]["sealed"] == 0
    assert by_id["__proto__"]["lastSealed"] is None
    assert by_id["ten:a"]["counted"] is None  # the roster had no count, and its readiness call failed
    assert by_id["ten:a"]["lastSealed"] == "2026-09-20T10:00:00Z"  # newest sealed exam when Bluebook has no date
    assert res["sealedToReview"] == 2
    assert res["courseCount"] == 3
    # Nothing Bluebook computed about a submission is passed on.
    assert all(set(s) == {"id", "student_id", "created_at", "graded_at"} for s in res["submissions"])


@needs_node
def test_roster_names_are_always_strings():
    roster = [{"id": "n1", "name": 5, "authenticated_count": 1, "sample_count": 1}]
    res = _roster(students=[200, {"students": ["n1"], "roster": roster}], readinessDefault=_ready("ready"))["result"]
    assert res["students"][0]["name"] == "5"


@needs_node
@pytest.mark.parametrize("status", [403])
def test_roster_without_bluebook_still_lists_students(status):
    out = _roster(
        students=[200, {"students": ["a"], "roster": None}],
        readinessDefault=_ready("developing", auth=3),
        bbStudents=[status, {"detail": "no"}],
        bbSubmissions=[status, {"detail": "no"}],
    )
    res = out["result"]
    assert res["ok"] and res["bluebookOff"] and res["bluebook"] == "off"
    assert res["sealedToReview"] is None and res["submissions"] == []
    assert res["students"][0]["verdict"] == "developing"
    assert res["students"][0]["sealed"] is None and res["students"][0]["lastSealed"] is None


@needs_node
@pytest.mark.parametrize(
    "students",
    [
        [500, {"detail": "boom"}],
        [200, {"students": [], "roster": [None]}],  # a shape the loader cannot read
    ],
)
def test_roster_that_cannot_read_the_students_says_so_instead_of_rejecting(students):
    res = _roster(students=students)["result"]
    assert res["ok"] is False
    assert res["error"]
    assert res["students"] == []


@needs_node
@pytest.mark.parametrize("readiness", ["answers", "fails"])
def test_roster_is_loaded_once_per_page_however_many_times_it_is_asked_for(readiness):
    # writing-state.html asks for the roster twice; two loads would also double
    # every readiness request (10 for 5 students) when they fail.
    ids = ["a", "b", "c", "d", "e"]
    answer = _ready("ready") if readiness == "answers" else [500, {"detail": "boom"}]
    out = _roster(call="rosterTwice", students=[200, {"students": ids, "roster": None}], readinessDefault=answer)
    assert out["sameObject"] is True
    assert out["result"]["ok"] and len(out["result"]["students"]) == 5
    calls = out["calls"]
    assert len([c for c in calls if c.endswith("/readiness")]) == 5
    for endpoint in ("/students", "/bluebook/students", "/bluebook/submissions", "/bluebook/exams"):
        assert calls.count(endpoint) == 1, endpoint


# ── Live.sealed ───────────────────────────────────────────────────────────────

SEALED_RESULT_KEYS = set(SEALED_FIELDS) | {"course_id", "warning_count"}


@needs_node
def test_sealed_copies_only_the_allowlisted_fields_and_adds_the_exams_course():
    out = _roster(
        call="sealed",
        bbSubmissions=[
            200,
            {
                "submissions": [
                    {
                        "id": "x1", "exam_id": "e1", "student_id": "s1", "candidate": "Ada L.",
                        "exam": "Midterm", "course": "THEO 301", "created_at": "2026-10-01T10:00:00Z",
                        "late": True, "mark": "B+", "graded_at": None,
                        # Everything below is Bluebook's own and must never come through.
                        "ai_score": 0.91, "aiScore": 0.91, "stylometric": 0.4, "status": "FLAGGED",
                        "warnings": ["pasted"], "graded_by": "teacher-1", "feedback": "see me",
                        "text": "the whole paper", "tenant_id": "demo",
                    },
                    {"id": "x2", "exam_id": "unknown-exam", "student_id": "constructor"},
                ]
            },
        ],
        bbStudents=[
            200,
            {"students": [{"student_id": "s1", "name": "Ada Lovelace", "email": "a@example.org"}, None, {"student_id": "s2"}]},
        ],
        bbExams=[
            200,
            {
                "exams": [
                    {"id": "e1", "title": "Midterm", "course": "THEO 301", "course_id": "c1", "prompt": "secret", "questions": [1], "tenant_id": "demo"},
                    None,
                ]
            },
        ],
    )
    res = out["result"]
    assert res["bluebook"] == "ok"
    first, second = res["submissions"]
    assert set(first) == SEALED_RESULT_KEYS and set(second) == SEALED_RESULT_KEYS
    assert first["course_id"] == "c1" and second["course_id"] is None  # the exam is not known
    assert (first["id"], first["late"], first["mark"], first["graded_at"]) == ("x1", True, "B+", None)
    assert (second["id"], second["mark"], second["candidate"]) == ("x2", None, None)
    for leaked in ("ai_score", "aiScore", "stylometric", "status", "warnings", "graded_by", "feedback", "text", "tenant_id"):
        assert leaked not in first, leaked
    # warning_count is derived: a number, how many warnings the sitting recorded. The
    # warnings themselves ("warnings") are not in the row, whatever Bluebook sent.
    assert isinstance(first["warning_count"], int) and not isinstance(first["warning_count"], bool)
    assert first["warning_count"] == 1 and "warnings" not in first
    assert second["warning_count"] == 0 and "warnings" not in second  # no list sent: still a number
    blob = json.dumps(res)
    for value in ("FLAGGED", "0.91", "see me", "the whole paper", "teacher-1", "pasted", "secret"):
        assert value not in blob, value
    assert res["names"] == [["s1", "Ada Lovelace"]]
    # An exam keeps only its title, course and course id.
    assert res["exams"] == [["e1", {"title": "Midterm", "course": "THEO 301", "course_id": "c1"}]]


@needs_node
def test_sealed_copies_only_scalars_so_an_object_valued_field_carries_no_nested_keys():
    # The allowlist names the keys that leave; a value is copied only when it is a
    # string, a number or a boolean. A field that arrives as an object (or a list)
    # becomes null, or its own nested keys would ride through under an allowed name.
    out = _roster(
        call="sealed",
        bbSubmissions=[
            200,
            {
                "submissions": [
                    {
                        "id": "x1", "exam_id": "e1", "student_id": "s1",
                        "mark": {"value": "B+", "ai_score": 0.91, "status": "FLAGGED"},
                        "late": {"yes": True},
                        "candidate": ["Ada", "Lovelace"],
                        "exam": {"text": "the whole paper"},
                        "course": 7,
                        "created_at": "2026-10-01T10:00:00Z",
                        "graded_at": {"at": "2026-10-02T10:00:00Z"},
                    }
                ]
            },
        ],
    )
    (row,) = out["result"]["submissions"]
    assert set(row) == SEALED_RESULT_KEYS
    for field in ("mark", "late", "candidate", "exam", "graded_at"):
        assert row[field] is None, field
    # Strings, numbers and booleans pass as they are.
    assert (row["id"], row["exam_id"], row["course"], row["created_at"]) == ("x1", "e1", 7, "2026-10-01T10:00:00Z")
    blob = json.dumps(out["result"])
    for value in ("ai_score", "FLAGGED", "the whole paper", "Lovelace", "0.91"):
        assert value not in blob, value
    scalars = _roster(
        call="sealed",
        bbSubmissions=[200, {"submissions": [{"id": "x2", "late": False, "mark": "", "created_at": 5}]}],
    )["result"]["submissions"][0]
    assert (scalars["late"], scalars["mark"], scalars["created_at"]) == (False, "", 5)


@needs_node
@pytest.mark.parametrize(
    "rows",
    [[None], ["junk"], [5], [[1, 2]], [{"id": "ok", "student_id": "s1"}, None]],
    ids=["null", "string", "number", "list", "good-row-then-null"],
)
def test_a_sealed_list_with_a_row_that_is_not_an_object_is_an_error_not_a_smaller_list(rows):
    # Dropping the bad row would count the rest as if the list were whole: an
    # undercounted "to review" with no sign anything went wrong.
    out = _roster(
        call="both",
        students=[200, {"students": ["s1"], "roster": None}],
        readinessDefault=_ready("ready"),
        bbSubmissions=[200, {"submissions": rows}],
    )
    sealed, res = out["sealed"], out["result"]
    assert sealed["bluebook"] == "error"
    assert sealed["submissions"] == [] and sealed["names"] == [] and sealed["exams"] == []
    # The roster reads the same load: the students are still listed, Bluebook is
    # reported as unreadable, and nothing is counted from the half-read list.
    assert res["ok"] and [s["id"] for s in res["students"]] == ["s1"]
    assert res["bluebook"] == "error" and res["bluebookOff"] is False
    assert res["sealedToReview"] is None and res["submissions"] == []
    assert res["students"][0]["sealed"] is None and res["students"][0]["pending"] is None


@needs_node
def test_the_roster_has_the_same_shape_whether_bluebook_answered_or_not():
    answered = _roster(students=[200, {"students": ["a"], "roster": None}], readinessDefault=_ready("ready"))
    failed = _roster(
        students=[200, {"students": ["a"], "roster": None}],
        readinessDefault=_ready("ready"),
        bbSubmissions=[200, {"submissions": [None]}],
    )
    unreadable = _roster(students=[500, {"detail": "boom"}])
    keys = set(answered["result"])
    assert keys == {
        "ok", "error", "scoped", "students", "sealedToReview", "bluebook", "bluebookOff",
        "courseCount", "beyondCap", "submissions",
    }
    assert set(failed["result"]) == keys and set(unreadable["result"]) == keys
    assert set(answered["result"]["students"][0]) == set(failed["result"]["students"][0])


@needs_node
@pytest.mark.parametrize("call", ["roster", "sealed"])
@pytest.mark.parametrize(
    "scenario",
    [
        {},
        {"bbSubmissions": [500, {"detail": "boom"}]},
        {"bbSubmissions": [403, {"detail": "no"}]},
        {"bbSubmissions": [200, {"submissions": [None]}]},
        {"students": [500, {"detail": "boom"}]},
    ],
    ids=["answered", "bluebook-500", "bluebook-off", "bad-row", "students-500"],
)
def test_the_shared_roster_and_sealed_results_are_frozen(call, scenario):
    # Every page shares one object per load. A page that sorted it in place or
    # added a field would change what the next page script reads.
    base = dict(
        students=[200, {"students": ["a", "b"], "roster": None}],
        readinessDefault=_ready("ready"),
        bbStudents=[200, {"students": [{"student_id": "a", "courses": [_course("c1", "THEO 301")]}]}],
        bbSubmissions=[
            200,
            {"submissions": [{"id": "x1", "student_id": "a", "created_at": "2026-10-01T10:00:00Z", "graded_at": None}]},
        ],
    )
    base.update(scenario)
    frozen = _roster(call=call, **base)["frozen"]
    assert frozen and all(v is True for v in frozen.values()), frozen


@needs_node
@pytest.mark.parametrize(
    "scenario,state",
    [
        ({"bbSubmissions": [403, {"detail": "no"}]}, "off"),
        ({"bbStudents": [403, {"detail": "no"}]}, "off"),
        ({"bbSubmissions": [500, {"detail": "boom"}]}, "error"),
        ({"bbSubmissions": [200, {"submissions": "nope"}]}, "error"),
        ({"bbSubmissions": [200, {}]}, "error"),
        ({"rejectOn": ["^/bluebook/submissions$"]}, "error"),
    ],
)
def test_sealed_says_off_or_error_and_hands_back_nothing(scenario, state):
    res = _roster(call="sealed", **scenario)["result"]
    assert res["bluebook"] == state
    assert res["submissions"] == [] and res["names"] == [] and res["exams"] == []


@needs_node
def test_sealed_is_off_without_a_bluebook_product_and_asks_for_nothing():
    out = _roster(
        call="sealed",
        local={"original_principal_token": "t"},
        me=[200, {"role": "professor", "products": ["original"], "tenant_id": "ten"}],
    )
    assert out["result"]["bluebook"] == "off"
    assert not [c for c in out["calls"] if c.startswith("/bluebook/")]


@needs_node
def test_roster_and_sealed_share_one_load_and_one_definition_of_awaiting_review():
    submissions = [
        {"id": "a", "student_id": "s1", "exam_id": "e1", "created_at": "2026-10-01T10:00:00Z", "graded_at": None},
        {"id": "b", "student_id": "s1", "exam_id": "e1", "created_at": "2026-10-02T10:00:00Z", "graded_at": "2026-10-03T10:00:00Z"},
        {"id": "c", "student_id": "s2", "exam_id": "e2", "created_at": "2026-10-04T10:00:00Z", "graded_at": None},
    ]
    out = _roster(
        call="both",
        students=[200, {"students": ["s1", "s2"], "roster": None}],
        readinessDefault=_ready("ready"),
        bbSubmissions=[200, {"submissions": submissions}],
    )
    # Three Bluebook requests for the whole page, however many callers ask.
    for endpoint in ("/bluebook/submissions", "/bluebook/students", "/bluebook/exams"):
        assert out["calls"].count(endpoint) == 1, endpoint
    assert out["sameObject"] is True
    awaiting = [r["id"] for r in out["sealed"]["submissions"] if not r["graded_at"]]
    assert awaiting == ["a", "c"]
    assert out["result"]["sealedToReview"] == len(awaiting)
    assert [(s["id"], s["pending"]) for s in out["result"]["students"]] == [("s1", 1), ("s2", 1)]
    assert [r["id"] for r in out["result"]["submissions"]] == ["a", "b", "c"]


# ── Live.signOut ──────────────────────────────────────────────────────────────
# A kept paper is the full text of a student's writing plus its result. On a
# shared computer it must not outlive the teacher's session.


def test_live_js_sign_out_names_the_kept_paper_keys(live_js):
    assert "var PORTFOLIO_PREFIX = 'original_portfolio_'" in live_js
    assert "var LAST_RESULT_KEY = 'original_last_result'" in live_js
    body = live_js[live_js.index("function signOut()") :]
    body = body[: body.index("\n  }\n")]
    assert "keptPaperKeys()" in body
    assert "window.sessionStorage.removeItem(LAST_RESULT_KEY)" in body


def test_every_literal_storage_key_the_pages_write_is_cleared_on_sign_out(live_js):
    # A page that starts keeping something new under a fixed key must teach
    # signOut about it (or this test says so). Keyed-by-student lists use the
    # original_portfolio_ prefix, which signOut clears by prefix.
    cleared = {"original_last_result"}
    for path in _code_files():
        if path == SUITE / "live.js":
            continue
        text = path.read_text(encoding="utf-8")
        for key in re.findall(r"""[sS]torage\.setItem\(\s*['"]([^'"]+)['"]""", text):
            assert key in cleared, f"{path.name} keeps {key!r} but sign-out does not clear it"


@needs_node
def test_sign_out_clears_kept_papers_and_the_last_result_but_nothing_else():
    papers = {f"original_portfolio_s{i:02d}": '[{"text":"a whole paper"}]' for i in range(9)}
    out = _roster(
        call="signOut",
        local={
            "original_principal_token": "tok",
            "original_name": "Pat",
            "original_email": "pat@example.org",
            "original_portfolio_": "a prefix with no student id still goes",
            **papers,
            "original_portfolio": "not a kept paper: no trailing underscore",
            "another_site_key": "left alone",
        },
        session={"original_last_result": '{"result":{}}', "unrelated": "left alone"},
    )
    assert sorted(out["local"]) == ["another_site_key", "original_portfolio"]
    assert out["session"] == ["unrelated"]
    assert out["replaced"] == ["/index.html"]


@needs_node
def test_sign_out_still_leaves_when_the_browser_blocks_storage():
    out = _roster(call="signOut", blockStorage=True)
    assert out["replaced"] == ["/index.html"]


@needs_node
@pytest.mark.parametrize(
    "local,goes_to",
    [
        # An account student, a launch-link student, and a student who carries both.
        ({"original_role": "student", "original_session_token": "s"}, "/bluebook/"),
        ({"original_session_token": "s"}, "/bluebook/"),
        ({"bluebook_student_id": "t:s1"}, "/bluebook/"),
        ({"original_role": "student"}, "/bluebook/"),
        # Teachers and everyone else: the main sign-in page.
        ({"original_principal_token": "p", "original_role": "professor"}, "/index.html"),
        ({"original_principal_token": "p", "original_session_token": "left over", "bluebook_student_id": "x"}, "/index.html"),
        ({}, "/index.html"),
    ],
    ids=["account-student", "session-only", "launch-link", "role-only", "teacher", "teacher-with-stale-student-keys", "nobody"],
)
def test_sign_out_sends_a_student_back_to_bluebooks_sign_in_and_a_teacher_to_the_main_one(local, goes_to):
    out = _roster(call="signOut", local=dict(local))
    assert out["replaced"] == [goes_to]
    # Either way the student's or teacher's keys are gone before the page moves.
    assert out["local"] == []


# ── Reports page: the numbers the headline and the course tabs stand on ──────
# reports.html is run for real (its inline script, under node) against stubbed
# endpoints; the page's text is read back from the stubbed elements.


def _ago(days: float) -> str:
    when = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)
    return when.strftime("%Y-%m-%dT%H:%M:%SZ")


def _course(cid: str, code: str) -> dict:
    return {"course_id": cid, "code": code, "name": code + " name"}


def _two_course_scenario(**extra) -> dict:
    """Four students; two courses; five sealed exams, one of them (s4) on an
    exam with no course and one (s5) from a student on no roster course."""
    roster = [
        {"id": sid, "name": sid.upper(), "authenticated_count": 5, "sample_count": 5}
        for sid in ("a", "b", "c", "d")
    ]
    scenario = dict(
        students=[200, {"students": [r["id"] for r in roster], "roster": roster}],
        readinessDefault=_ready("ready"),
        bbStudents=[
            200,
            {
                "students": [
                    {"student_id": "a", "courses": [_course("c1", "THEO 301")]},
                    {"student_id": "b", "courses": [_course("c2", "BIB 101")]},
                    {"student_id": "c", "courses": [_course("c1", "THEO 301"), _course("c2", "BIB 101")]},
                ]
            },
        ],
        bbExams=[
            200,
            {
                "exams": [
                    {"id": "e1", "title": "Midterm", "course": "THEO 301", "course_id": "c1"},
                    {"id": "e2", "title": "Quiz", "course": "BIB 101", "course_id": "c2"},
                    {"id": "e3", "title": "Open exam", "course": "", "course_id": None},
                ]
            },
        ],
        bbSubmissions=[
            200,
            {
                "submissions": [
                    {"id": "s1", "student_id": "a", "exam_id": "e1", "created_at": _ago(1), "graded_at": None},
                    {"id": "s2", "student_id": "b", "exam_id": "e2", "created_at": _ago(2), "graded_at": _ago(1)},
                    # Student c is in both courses, but this exam belongs to c1 only.
                    {"id": "s3", "student_id": "c", "exam_id": "e1", "created_at": _ago(3), "graded_at": None},
                    # No course on the exam: counted by student, so in both of c's tabs.
                    {"id": "s4", "student_id": "c", "exam_id": "e3", "created_at": _ago(4), "graded_at": None},
                    # No course, and the student is on no course roster: only in All courses.
                    {"id": "s5", "student_id": "d", "exam_id": "e3", "created_at": _ago(5), "graded_at": None},
                ]
            },
        ],
        clicks=["c1", "c2"],
    )
    scenario.update(extra)
    return scenario


NOTE = "Counted by student for exams without a course: a student in two courses appears in both."


@needs_node
def test_reports_course_tabs_count_a_sealed_exam_under_the_exams_own_course():
    everything, c1, c2 = _page("reports.html", **_two_course_scenario())["snaps"]
    # All courses: five exams, four waiting. No fallback is in play, so no note.
    assert "4 sealed exams</b> are waiting" in everything["headline"]
    assert everything["termD"] == "2 courses · 4 students · 5 sealed exams"
    assert everything["tabNote"]["hidden"] is True
    assert 'data-c="c1"' in everything["tabs"] and 'data-c="c2"' in everything["tabs"]
    # THEO 301: s1 and s3 by their exam, s4 by its student (c). Student c's s3 is
    # not counted in BIB 101 even though c is on both rosters.
    assert c1["headline"].startswith("THEO 301: ")
    assert "3 sealed exams</b> are waiting" in c1["headline"]
    assert c1["termD"] == "THEO 301 · 2 students · 3 sealed exams"
    assert c1["reviewed"] == ["0", "of 3 sealed · 3 waiting"]
    # BIB 101: s2 (reviewed) by its exam, s4 by its student.
    assert c2["headline"].startswith("BIB 101: ")
    assert "1 sealed exam</b> is waiting" in c2["headline"]
    assert c2["termD"] == "BIB 101 · 2 students · 2 sealed exams"
    assert c2["reviewed"] == ["1", "of 2 sealed · 1 waiting"]
    # The note appears exactly in the tabs where an exam was counted by student.
    for tab in (c1, c2):
        assert tab["tabNote"] == {"text": NOTE, "hidden": False}


@needs_node
def test_reports_course_tab_with_every_exam_on_a_known_course_shows_no_note():
    scenario = _two_course_scenario()
    subs = [r for r in scenario["bbSubmissions"][1]["submissions"] if r["exam_id"] != "e3"]
    scenario["bbSubmissions"] = [200, {"submissions": subs}]
    _, c1, c2 = _page("reports.html", **scenario)["snaps"]
    assert "2 sealed exams</b> are waiting" in c1["headline"]  # s1, s3
    assert c1["tabNote"]["hidden"] is True and c2["tabNote"]["hidden"] is True


@needs_node
def test_reports_headline_says_how_many_students_readiness_was_not_read_for():
    # 70 ids: the first 60 are asked about, the last 10 never are. Two of the 60
    # answered with an error, so their verdict is missing rather than "not ready".
    ids = [f"s{i:02d}" for i in range(70)]
    snap = _page(
        "reports.html",
        students=[200, {"students": ids, "roster": None}],
        readinessDefault=_ready("ready"),
        readiness={"s03": [500, {"detail": "boom"}], "s07": [500, {"detail": "boom"}]},
    )["snaps"][0]
    assert snap["headline"].startswith("<b>58 of 70 students</b> have a ready baseline.")
    assert " Readiness could not be read for 2." in snap["headline"]
    assert " Readiness was not checked for 10." in snap["headline"]


@needs_node
def test_reports_headline_makes_no_ready_claim_when_no_verdict_was_read():
    snap = _page("reports.html", students=[200, {"students": ["a", "b"], "roster": None}])["snaps"][0]
    assert "ready baseline" not in snap["headline"]
    assert snap["headline"].startswith("<b>2 students</b> on your roster.")


@needs_node
def test_reports_course_tab_counts_unread_readiness_within_its_own_students():
    scenario = _two_course_scenario(readiness={"a": [500, {"detail": "boom"}]})
    _, c1, c2 = _page("reports.html", **scenario)["snaps"]
    assert "<b>1 of 2 students</b> has a ready baseline. Readiness could not be read for 1." in c1["headline"]
    assert "Readiness could not be read" not in c2["headline"]  # a is not in BIB 101


@needs_node
@pytest.mark.parametrize(
    "scenario,term",
    [
        (dict(students=[500, {"detail": "boom"}], rejectOn=["^/bluebook/"]), "Could not load your students or sealed exams"),
        (dict(students=[500, {"detail": "boom"}]), "Could not load your students · 0 sealed exams"),
        (dict(students=[200, {"students": ["a"], "roster": None}], rejectOn=["^/bluebook/"]), "Could not load sealed exams · 1 student"),
    ],
    ids=["all", "students", "sealed"],
)
def test_reports_term_block_says_could_not_load_instead_of_nothing_on_file(scenario, term):
    snap = _page("reports.html", **scenario)["snaps"][0]
    assert snap["termD"] == term


# ── The student pages (voice.html, my-work.html) ─────────────────────────────
# Owner decision 2026-10-10: a student sees their own voice portrait and can
# compare a piece with it, on real data only. Never a score, a deviation, an
# action, "authentic", "AI", or teacher-side wording. The pages read GET
# /me/voice and POST /me/work and nothing else.

STUDENT_ENDPOINT = {"voice.html": "/me/voice", "my-work.html": "/me/work"}
STUDENT_SENTENCE = (
    "Your teacher may approve your sealed Collections work as reference writing for it, "
    "and can undo that approval."
)


@pytest.mark.parametrize("name", sorted(STUDENT_PAGES))
def test_student_pages_gate_as_students_and_call_only_their_own_endpoint(name):
    code = _inline_scripts(SUITE / name)
    assert "Live.gate(" in code and "audience:'student'" in code
    assert re.findall(r"Live\.api\(\s*'([^']+)'", code) == [STUDENT_ENDPOINT[name]]
    for teacher_side in (
        "Live.roster",
        "Live.sealed",
        "/students",
        "/auth/",
        "/bluebook/exams",
        "/bluebook/students",
        "sessionStorage",
        "localStorage",
    ):
        assert teacher_side not in code, f"{name} reaches for {teacher_side}"


@pytest.mark.parametrize("name", sorted(STUDENT_PAGES))
def test_student_pages_carry_the_student_label_slot_and_not_the_teachers(name):
    page = (SUITE / name).read_text(encoding="utf-8")
    assert page.count("data-student-notice") == 1
    assert "data-testing-notice" not in page


def test_student_label_lives_once_in_live_js_and_names_reference_writing(live_js):
    assert live_js.count(STUDENT_SENTENCE) == 1
    # The teacher's sentence is never shown to a student.
    assert "never as evidence" not in STUDENT_SENTENCE
    for path in _code_files():
        if path != SUITE / "live.js":
            assert _squash(STUDENT_SENTENCE) not in _squash(path.read_text(encoding="utf-8")), path.name


@pytest.mark.parametrize("name", sorted(STUDENT_PAGES))
def test_student_pages_show_nothing_a_student_must_not_see(name):
    text = (SUITE / name).read_text(encoding="utf-8")
    # The design's own sentence says the page is "not a score, a likeness": that
    # denial stays; any other mention of a score does not.
    text = text.replace("not a score, a likeness", "")
    banned = re.compile(
        r"\b(scor\w*|deviat\w*|authentic\w*|AI|flag\w*|verdict|fidelity|purity|"
        r"recommend\w*|escalat\w*|packet|baseline_vector|feature_vector)\b",
        re.IGNORECASE,
    )
    assert not banned.findall(text), f"{name}: {banned.findall(text)}"


@pytest.mark.parametrize("name", sorted(STUDENT_PAGES))
def test_student_pages_read_none_of_the_fields_that_carry_a_reading(name):
    code = _inline_scripts(SUITE / name)
    for field in (
        "fidelity",
        "attention",
        "review_opportunit",
        "formation",
        "subhead",
        "step_label",
        "supportive_copy",
    ):
        assert field not in code, f"{name} reads {field}"
    # (ctx.arc is the canvas call; V.arc is the term timeline the page leaves out.)
    assert not re.search(r"(?<!ctx)\.arc\b", code), f"{name} reads the term timeline"


def test_voice_page_reads_the_four_things_the_brief_names():
    code = _inline_scripts(SUITE / "voice.html")
    for field in ("V.headline", "V.fingerprint", "V.milestones", "V.voice_notes"):
        assert field in code, field


def test_my_work_page_says_what_joins_a_profile_and_reads_only_the_redacted_result():
    page = (SUITE / "my-work.html").read_text(encoding="utf-8")
    # A piece compared in My Work is never stored, so a teacher cannot add it:
    # the page says what does join a writing profile, and never offers to add it.
    assert "Only writing your teacher approves, such as sealed Collections work, joins your writing profile." in page
    assert "may choose to add" not in page
    code = _inline_scripts(SUITE / "my-work.html")
    for field in ("r.headline", "r.summary", "r.steady"):
        assert field in code, field
    # The page makes no highlight of phrases: nothing in the response says where.
    assert "<mark" not in page


def test_voice_page_is_accurate_about_what_is_kept_and_where_the_portrait_comes_from():
    page = (SUITE / "voice.html").read_text(encoding="utf-8")
    # My Work leaves audit, fidelity and manifest rows that staff can read.
    assert (
        "When you use My Work, the result of the comparison is kept and your teacher can see it. "
        "The piece itself is not kept."
    ) in page
    # Writing a student uploaded themselves still counts toward a profile, so the
    # page may not claim the portrait is drawn only from approved writing.
    assert "portrait drawn from the writing on file in your profile" in page
    for claim in (
        "portrait drawn from the writing your teacher",
        "drawn from the writing your teacher approves",
        "once your teacher has approved",
        "only when your teacher approves",
        "A record that a comparison was made",
    ):
        assert claim not in page, claim


def test_voice_page_never_calls_its_picture_an_engraving():
    page = (SUITE / "voice.html").read_text(encoding="utf-8")
    assert '<img src="assets/all-souls-engraving-wide.jpg" alt="" />' in page
    described = page.replace("all-souls-engraving-wide.jpg", "")
    for word in ("engraving", "historical", "College"):
        assert word.lower() not in described.lower(), word
    credits = (SUITE / "assets" / "CREDITS.md").read_text(encoding="utf-8")
    assert "appears to be AI-generated in an engraving style" in credits
    assert "shipped at the owner's direction" in credits


# The node harness: Live.gate with {audience:'student'}, and which token Live.api sends.

STUDENT_TAIL = r"""
(async () => {
  const el = document.getElementById('main');
  const out = {};
  if (sc.call === 'gate') {
    const s = await window.Live.gate(el, sc.opts);
    out.session = s ? { role: s.role, mode: s.mode } : null;
    out.html = el.innerHTML;
  } else if (sc.call === 'api') {
    out.res = await window.Live.api(sc.path, sc.opts);
  }
  process.stdout.write(JSON.stringify(Object.assign(out, { calls, auths, replaced })));
})();
"""


def _student(**scenario) -> dict:
    run = subprocess.run(
        [shutil.which("node"), "-e", PRELUDE + STUDENT_TAIL],
        input=json.dumps({"live": str(SUITE / "live.js"), **scenario}),
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert run.returncode == 0, run.stderr
    assert run.stdout, "the call never finished"
    return json.loads(run.stdout)


STUDENT_GATE = dict(call="gate", opts={"audience": "student"})
STAFF_ME = [200, {"role": "professor", "products": ["original", "bluebook"], "tenant_id": "t"}]


@needs_node
@pytest.mark.parametrize(
    "local",
    [
        {"original_session_token": "a-student-session"},
        # A Bluebook launch link stores the student id and a session token.
        {"original_session_token": "s", "bluebook_student_id": "northfield:ab12cd34"},
    ],
)
def test_student_gate_lets_a_student_session_in_without_asking_the_server_who_they_are(local):
    out = _student(local=local, **STUDENT_GATE)
    assert out["session"] == {"role": "student", "mode": "signed-in"}
    assert out["replaced"] == [] and out["html"] == ""
    assert out["calls"] == []


@needs_node
def test_student_gate_asks_a_student_id_with_no_session_token_to_sign_in():
    # ?sid= in a Bluebook URL stores only the id. The /me/ routes cannot tell who
    # that is, so the page must not run its calls and report an expired sign-in.
    out = _student(local={"bluebook_student_id": "northfield:ab12cd34"}, **STUDENT_GATE)
    assert out["session"] is None and out["replaced"] == []
    assert "Sign in to continue" in out["html"] and 'href="/bluebook/"' in out["html"]
    assert out["calls"] == []


@needs_node
def test_student_gate_sends_a_teacher_to_the_teacher_pages():
    out = _student(local={"original_principal_token": "p"}, me=STAFF_ME, **STUDENT_GATE)
    assert out["session"] is None
    assert out["replaced"] == ["index.html"]


@needs_node
@pytest.mark.parametrize(
    "health",
    [
        [200, {"environment": "pilot"}],  # a real deploy, nobody signed in
        [200, {"environment": "demo"}],  # the open demo has no student account
    ],
    ids=["signed-out", "open-demo"],
)
def test_student_gate_sends_everyone_else_to_bluebooks_sign_in(health):
    out = _student(local={}, health=health, **STUDENT_GATE)
    assert out["session"] is None
    assert out["replaced"] == []
    assert "Sign in to continue" in out["html"]
    assert 'href="/bluebook/"' in out["html"]


@needs_node
def test_the_teacher_gate_is_unchanged_for_a_student():
    # No options: a student on a teacher page still goes to Bluebook, as before.
    out = _student(call="gate", local={"original_session_token": "s"})
    assert out["session"] is None
    assert out["replaced"] == ["/bluebook/"]


@needs_node
@pytest.mark.parametrize(
    "local,expected",
    [
        ({"original_session_token": "stu"}, "Bearer stu"),  # a student's session token
        ({"original_principal_token": "prin"}, "Bearer prin"),  # a teacher's, as before
        ({"original_principal_token": "prin", "original_session_token": "stu"}, "Bearer prin"),
        ({}, None),
    ],
)
def test_api_sends_the_principal_token_else_the_student_session_token(local, expected):
    out = _student(call="api", path="/me/voice", local=local, meVoice=[200, {}])
    assert out["auths"] == [expected]


# The student pages, run for real under node against stubbed /me/* endpoints. The
# stub document is the one the other page tests use, made a little richer (a
# working classList, a 2-d canvas that draws nothing, element values).

STUDENT_PAGE_TAIL = r"""
const page = fs.readFileSync(sc.page, 'utf8');
const scripts = Array.from(page.matchAll(/<script>([\s\S]*?)<\/script>/g)).map((m) => m[1]);
if (scripts.length !== 1) throw new Error('expected one inline script, found ' + scripts.length);
const rich = new WeakSet();
const getById = document.getElementById.bind(document);
document.getElementById = (id) => {
  const e = getById(id);
  if (!rich.has(e)) {
    rich.add(e);
    const set = new Set();
    e.classList = {
      _s: set, add: (c) => set.add(c), remove: (c) => set.delete(c), contains: (c) => set.has(c),
      toggle: (c, on) => { const want = on === undefined ? !set.has(c) : !!on; want ? set.add(c) : set.delete(c); return want; },
    };
    e.style.setProperty = (k, v) => { e.style[k] = v; };
    e.getContext = () => new Proxy({}, { get: (t, k) => (k === 'createLinearGradient' ? () => ({ addColorStop() {} }) : () => {}), set: () => true });
    e.getBoundingClientRect = () => ({ width: 400, height: 400 });
    e.value = '';
    e.scrollIntoView = () => {};
  }
  return e;
};
window.matchMedia = () => ({ matches: true });
window.addEventListener = () => {};
window.innerWidth = 1280;
globalThis.requestAnimationFrame = () => 0;
new Function('window', 'document', 'Live', scripts[0])(window, document, window.Live);
const el = (id) => document.getElementById(id);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const until = async (fn) => { for (let i = 0; i < 500 && !fn(); i++) await sleep(10); };
const fire = (id, type) => (el(id).handlers[type] || []).forEach((fn) => fn({ preventDefault() {}, stopPropagation() {} }));
const view = (ids) => Object.fromEntries(ids.map((id) => [id, { html: el(id).innerHTML, text: el(id).textContent, hidden: el(id).hidden, cls: Array.from(el(id).classList._s || []) }]));
(async () => {
  const out = {};
  if (sc.name === 'voice.html') {
    await until(() => el('who').innerHTML || el('gate').innerHTML || el('status').textContent);
    await sleep(20);
    out.view = view(['headline', 'who', 'p-n', 'p-l', 'p-cap', 'rich-pct', 'grow-t', 'dots', 'notes', 'mk-grid', 'fam-tabs', 'status', 'gate', 'content']);
  } else {
    await sleep(30);   // the gate has resolved
    for (const run of sc.runs) {
      el('title').value = run.title || '';
      el('piece').value = run.text;
      fire('piece', 'input');
      const before = el('result').innerHTML;
      fire('go', 'click');
      if (run.text.trim()) await until(() => el('result').innerHTML !== before || el('hint').textContent.indexOf('could not') >= 0 || el('gate').innerHTML);
      await sleep(30);
      (out.runs = out.runs || []).push(view(['result', 'glance', 'glance-note', 'hint', 'count', 'go', 'gate', 'content', 'piece']));
    }
  }
  process.stdout.write(JSON.stringify(Object.assign(out, { calls, bodies })));
})();
"""


def _student_page(name: str, **scenario) -> dict:
    run = subprocess.run(
        [shutil.which("node"), "-e", PRELUDE + STUDENT_PAGE_TAIL],
        input=json.dumps(
            {"live": str(SUITE / "live.js"), "page": str(SUITE / name), "name": name, **scenario}
        ),
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert run.returncode == 0, run.stderr
    assert run.stdout, "the page never finished loading"
    return json.loads(run.stdout)


STUDENT_SESSION = {"original_session_token": "a-student-session", "original_name": "Sam Reader"}
DIMENSIONS = ["Cadence", "Diction", "Texture", "Register", "Restraint", "Architecture", "Resonance"]


def _voice_view(**extra) -> list:
    view = {
        "name": "Sam Reader",
        "headline": "Sam, your voice is settling into itself.",
        "subhead": "Voice fidelity 88 on your latest piece, up 6 since the start of term.",
        "fingerprint": [{"name": d, "value": 0.2 + 0.1 * i} for i, d in enumerate(DIMENSIONS)],
        "arc": [{"period": "2026-01-15", "fidelity": 88, "attention": True}],
        "voice_notes": [
            {"note": "You write long, then short.", "reviewer": "Dr. Pemberton", "date": "2026-01-15"}
        ],
        "review_opportunities": [{"invitation_prose": "Talk to your tutor.", "locator": "2026-01-15"}],
        "milestones": [
            {"label": "Voice Sampled", "state": "reached", "blurb": "Some of your writing is on file."},
            {"label": "Voice Established", "state": "reached", "blurb": "Enough is on file."},
            {"label": "Voice Affirmed", "state": "upcoming", "blurb": "A piece your teacher approved is on file."},
        ],
        "formation": {"active": True, "status": "open", "step_label": "Development Session"},
    }
    view.update(extra)
    return [200, view]


def _everything(view: dict) -> str:
    """All the text the voice page rendered, as one lowercase string."""
    return " ".join(f"{v['html']} {v['text']}" for v in view.values()).lower()


@needs_node
def test_voice_page_draws_the_headline_the_fingerprint_the_milestones_and_the_notes():
    out = _student_page("voice.html", local=STUDENT_SESSION, meVoice=_voice_view())
    v = out["view"]
    assert out["calls"] == ["/me/voice"]
    assert v["headline"]["html"] == "Sam, <em>your voice is settling into itself.</em>"
    assert "portrait drawn from the writing on file in your profile" in v["who"]["html"]
    assert v["p-n"]["text"] == "7" and v["p-l"]["text"] == "parts of your voice"
    # The seven parts, each with what it is about and a marker, and no number.
    for d in DIMENSIONS:
        assert f"<b>{d}</b>" in v["mk-grid"]["html"]
    assert v["mk-grid"]["html"].count('class="hab"') == 7
    # (the marker's position is a style; no number is printed anywhere in a card)
    assert not re.search(r"\d", re.sub(r"<[^>]*>", " ", v["mk-grid"]["html"]))
    # Milestones as the server worded them, two of three reached.
    assert v["rich-pct"]["text"] == "2 of 3 reached"
    assert v["dots"]["html"].count("dot on") == 2 and v["dots"]["html"].count('class="dot"') == 1
    assert "Some of your writing is on file." in v["dots"]["html"]
    assert v["grow-t"]["text"] == "Your portrait is still filling in"
    # The teacher's note, with who wrote it and when.
    assert "You write long, then short." in v["notes"]["html"]
    assert "Dr. Pemberton" in v["notes"]["html"] and "15 Jan 2026" in v["notes"]["html"]
    # Nothing that carries a reading: not the fidelity number, the term arc, the
    # invitation to talk to a tutor, or the pathway.
    shown = _everything(v)
    for left_out in ("88", "fidelity", "since the start of term", "tutor", "development session", "pathway"):
        assert left_out not in shown, left_out


@needs_node
def test_voice_page_with_every_milestone_says_the_portrait_is_filled_in():
    done = [{"label": f"M{i}", "state": "reached", "blurb": "b"} for i in range(3)]
    done[0]["label"] = "Voice Sampled"
    out = _student_page("voice.html", local=STUDENT_SESSION, meVoice=_voice_view(milestones=done))
    assert out["view"]["grow-t"]["text"] == "Your portrait is filled in"
    assert out["view"]["rich-pct"]["text"] == "3 of 3 reached"


@needs_node
def test_voice_page_draws_no_portrait_from_a_neutral_fingerprint():
    # No approved writing: the server still sends seven neutral 0.5 dimensions.
    neutral = [{"name": d, "value": 0.5} for d in DIMENSIONS]
    upcoming = [{"label": "Voice Sampled", "state": "upcoming", "blurb": "Not yet."}]
    out = _student_page(
        "voice.html",
        local=STUDENT_SESSION,
        meVoice=_voice_view(
            name="", headline="Your voice is finding its shape.", fingerprint=neutral,
            milestones=upcoming, voice_notes=[], arc=[],
        ),
    )
    v = out["view"]
    assert v["headline"]["html"] == "Your voice is finding its shape."
    assert "no writing on file in your profile yet" in v["who"]["html"]
    assert v["p-n"]["text"] == "\u2013" and v["p-l"]["text"] == "nothing drawn yet"
    assert 'class="hab"' not in v["mk-grid"]["html"]
    assert "once there is writing on file in your profile" in v["mk-grid"]["html"]
    assert v["fam-tabs"]["html"] == ""
    assert "has not left a note" in v["notes"]["html"]
    assert v["rich-pct"]["text"] == "0 of 1 reached"


@needs_node
def test_voice_page_escapes_what_the_server_sends():
    nasty = "<img src=x onerror=alert(1)>"
    out = _student_page(
        "voice.html",
        local=STUDENT_SESSION,
        meVoice=_voice_view(
            headline=nasty,
            voice_notes=[{"note": nasty, "reviewer": nasty, "date": "2026-01-15"}],
            milestones=[{"label": "Voice Sampled", "state": "reached", "blurb": nasty}],
        ),
    )
    shown = " ".join(v["html"] for v in out["view"].values())
    assert "<img" not in shown and "&lt;img" in shown


@needs_node
@pytest.mark.parametrize(
    "reply,said",
    [
        ([401, {"detail": "Not signed in."}], "Your sign-in has ended"),
        ([403, {"detail": "plan"}], "Original is off for your class"),
    ],
)
def test_voice_page_says_why_when_the_server_refuses(reply, said):
    out = _student_page("voice.html", local=STUDENT_SESSION, meVoice=reply)
    assert said in out["view"]["gate"]["html"]
    assert out["view"]["content"]["hidden"] is True and out["view"]["gate"]["hidden"] is False
    assert 'href="/bluebook/"' in out["view"]["gate"]["html"]


@needs_node
@pytest.mark.parametrize("reply", [[500, {}], [200, None], [200, ["not", "a", "view"]]])
def test_voice_page_says_so_when_the_view_cannot_be_read(reply):
    out = _student_page("voice.html", local=STUDENT_SESSION, meVoice=reply)
    v = out["view"]
    assert v["status"]["text"] == "Your voice page could not be loaded just now. Try reloading."
    assert v["status"]["hidden"] is False and v["content"]["hidden"] is False
    # Nothing is claimed about this student: not "no note yet", not "nothing
    # approved yet", not a portrait state.
    assert v["notes"]["html"].count("Not available just now.") == 1
    assert v["mk-grid"]["html"].count("Not available just now.") == 1
    assert v["dots"]["html"].count("Not available just now.") == 1
    shown = _everything({k: v[k] for k in ("who", "p-n", "p-l", "p-cap", "grow-t", "dots", "notes", "mk-grid")})
    for claim in ("has not left a note", "approved", "nothing drawn", "still filling in", "no writing on file"):
        assert claim not in shown, claim
    assert v["fam-tabs"]["html"] == "" and v["who"]["html"] == ""


@needs_node
def test_voice_page_with_a_student_id_and_no_session_token_asks_for_sign_in_and_calls_nothing():
    out = _student_page("voice.html", local={"bluebook_student_id": "northfield:ab12cd34"}, meVoice=_voice_view())
    assert "Sign in to continue" in out["view"]["gate"]["html"]
    assert "Your sign-in has ended" not in out["view"]["gate"]["html"]
    assert out["calls"] == []


PIECE = "Faithful work in an ordinary calling honors the same God who ordained the extraordinary. " * 4


@needs_node
def test_my_work_compares_a_piece_and_shows_only_the_redacted_result():
    reply = [
        200,
        {
            "headline": "Mostly your voice, with a few new notes.",
            "summary": "Most of this reads like your established writing.",
            "steady": ["Your cadence is consistent with your established voice."],
            "review_opportunity": True,
        },
    ]
    out = _student_page(
        "my-work.html", local=STUDENT_SESSION, meWork=reply, runs=[{"title": " On vocation ", "text": PIECE}]
    )
    run = out["runs"][0]
    assert out["calls"] == ["/me/work"]
    assert json.loads(out["bodies"][0]) == {"text": PIECE, "title": "On vocation"}
    assert "Mostly your voice, with a few new notes." in run["result"]["html"]
    assert "Held steady" in run["result"]["html"] and "Your cadence is consistent" in run["result"]["html"]
    # The yes/no that a review opportunity opened is not shown as such.
    assert "review" not in _everything(run).replace("review_opportunity", "")
    # At a glance: how long the piece is, and that it was not added.
    assert "<b>56</b>" in run["glance"]["html"] and "Not added" in run["glance"]["html"]
    # (the sentence itself is the page's own markup, checked above; here it stays shown)
    assert run["glance-note"]["hidden"] is False
    assert run["go"]["text"] == "Compare with my voice"


@needs_node
def test_my_work_says_the_piece_was_not_added_once_when_the_server_already_has():
    nothing = [
        200,
        {
            "headline": "Nothing to compare this with yet.",
            "summary": (
                "Original has no approved writing from you to compare this piece with yet, so it "
                "cannot say anything about it. Not added to your writing profile. Only writing your teacher approves, such as sealed Collections work, joins your writing profile."
            ),
            "steady": [],
            "review_opportunity": False,
        },
    ]
    out = _student_page("my-work.html", local=STUDENT_SESSION, meWork=nothing, runs=[{"text": PIECE}])
    run = out["runs"][0]
    assert "Nothing to compare this with yet." in run["result"]["html"]
    assert "Held steady" not in run["result"]["html"]
    assert run["glance-note"]["hidden"] is True


@needs_node
def test_my_work_does_nothing_for_an_empty_piece_and_warns_about_a_short_one():
    ok = [200, {"headline": "h", "summary": "s", "steady": [], "review_opportunity": False}]
    out = _student_page(
        "my-work.html", local=STUDENT_SESSION, meWork=ok, runs=[{"text": "   "}, {"text": "Only a few words here."}]
    )
    empty, short = out["runs"]
    assert empty["go"]["text"] != "Comparing\u2026"
    assert "0 words" in empty["count"]["text"]
    assert "A short piece tells Original little" in short["hint"]["text"]
    assert out["calls"] == ["/me/work"]  # only the short piece was sent


@needs_node
@pytest.mark.parametrize(
    "reply,said",
    [
        ([401, {"detail": "Not signed in."}], "Your sign-in has ended"),
        ([403, {"detail": "plan"}], "Original is off for your class"),
    ],
)
def test_my_work_says_why_when_the_server_refuses(reply, said):
    out = _student_page("my-work.html", local=STUDENT_SESSION, meWork=reply, runs=[{"text": PIECE}])
    run = out["runs"][0]
    assert said in run["gate"]["html"] and run["content"]["hidden"] is True


@needs_node
@pytest.mark.parametrize("reply", [[500, {"detail": "boom"}], [200, {"nope": 1}], [200, None]])
def test_my_work_keeps_the_text_and_says_so_when_a_comparison_fails(reply):
    out = _student_page("my-work.html", local=STUDENT_SESSION, meWork=reply, runs=[{"text": PIECE}])
    run = out["runs"][0]
    assert "could not compare this piece just now" in run["hint"]["text"]
    assert "err" in run["hint"]["cls"]
    assert "Your text is still here" in run["hint"]["text"]
    assert run["go"]["text"] == "Compare with my voice"


# ── Voice Baseline (baseline.html) ────────────────────────────────────────────
# One student's approved writing: what the baseline is made of, how to add to it,
# and which of their sealed Bluebook exams wait for approval. It shows no Original
# score, so it carries no testing label; purity (the one number that comes from the
# density matrix) sits inside a <details> that names the T-01 caveat.


def _baseline_page() -> str:
    return (SUITE / "baseline.html").read_text(encoding="utf-8")


def test_baseline_page_does_not_use_the_old_pending_baseline_requests():
    # professor.html's "pending baselines" belong to the Bluebook request flow
    # (bbook_client). This page lists the student's sealed exams for approval instead.
    page = _baseline_page()
    for gone in ("baseline-requests", "request-baseline", "bbook", "Bbook", "pending-baseline"):
        assert gone not in page, f"baseline.html mentions {gone}"


def test_baseline_page_shows_purity_only_inside_a_details_block_with_the_t01_caveat():
    parser = _OutsideDetails()
    parser.feed(_baseline_page())
    assert not [c for c in parser.outside if "Tr(" in c], "Tr( outside <details>"
    # The guard above passes vacuously if the purity ring loses its place.
    assert any("Tr(" in b and "T-01" in b for b in parser.blocks)
    # 1 / effective samples is a bound this page never claims (it is not reached for
    # real feature vectors, and it is false under RANK_REMEDIATION=shrinkage).
    assert "Lowest possible" not in _baseline_page() and "pur-floor" not in _baseline_page()


def test_worth_a_look_means_one_thing_in_the_suite():
    # "Worth a look" is Original's mark on a sealed exam. The note a teacher reads about a
    # sealed exam's session facts before approving it is not that mark, so it says something else.
    page = _baseline_page()
    assert "Before approving, note: " in page
    assert "Worth a look before approving" not in page
    used = {p.name for p in _code_files() if re.search(r"worth a look", p.read_text(encoding="utf-8"), re.IGNORECASE)}
    assert used == {"submissions.html"}


def test_the_t01_caveat_is_the_same_sentence_on_both_pages_that_carry_it():
    writing_state = (SUITE / "writing-state.html").read_text(encoding="utf-8")
    baseline = _baseline_page()
    assert f"<b>Testing caveat (T-01):</b> {T01_CAVEAT}" in writing_state
    assert f"<b>Testing caveat (T-01):</b> {T01_CAVEAT}" in baseline
    # ...and the "building" paragraph of Voice Baseline's short version says it the same way.
    assert f"Results from it are less reliable. {T01_CAVEAT} " in baseline
    for path in _code_files():
        text = path.read_text(encoding="utf-8")
        assert "docs/testing" not in text, f"{path.name} points a teacher at an internal document"
        assert "baselines of 3-5 samples" not in text and "baselines of 3 to 5 samples" not in text, path.name


def test_your_classes_says_enrolled_like_students_and_its_empty_table_mentions_no_flags():
    index = (SUITE / "index.html").read_text(encoding="utf-8")
    assert '<div class="card-s" id="stat1-l" style="color:var(--dim);">Enrolled</div>' in index
    assert "$('stat1-l').textContent='Enrolled';" in index
    assert "Live.empty($('ops-wrap'),'No students on your roster yet.')" in index
    assert "Flags will appear" not in index
    for path in _code_files():
        assert "Students monitored" not in path.read_text(encoding="utf-8"), path.name


def test_baseline_page_carries_no_testing_label_because_it_shows_no_score():
    assert "data-testing-notice" not in _baseline_page()


def test_baseline_page_adds_writing_through_the_professor_pages_endpoints_and_payloads():
    page = _baseline_page()
    # Single text: POST /students/{id}/baseline {text, provenance, assignment, submitted_at}.
    assert "'/baseline',{method:'POST',body:body}" in page
    for key in ("text:text", "provenance:prov", "assignment:", "submitted_at:"):
        assert key in page, key
    # Batch upload: multipart POST /students/{id}/baseline/upload-batch (files, provenance, assignment).
    assert "/baseline/upload-batch" in page
    for field in ("fd.append('files'", "fd.append('provenance'", "fd.append('assignment'"):
        assert field in page, field
    # Provenance values are the ones professor.html offers.
    assert 'value="verified"' in page and 'value="proctored"' in page
    # Pasting, uploading and approving or undoing an exam each read the student again
    # (refreshAfterWrite wraps refreshStudent so a failed read cannot lose the lock).
    assert page.count("await refreshAfterWrite()") + page.count("(await refreshAfterWrite())") >= 3
    assert page.count("await refreshStudent()") == 1
    # The Turnitin CSV import is not here: it creates empty profiles (never writing)
    # and ignores its course id. The classic page keeps it.
    for gone in ("turnitin", "/import/courses/", "tt-file"):
        assert gone not in page.lower(), f"baseline.html still has {gone}"


def test_baseline_page_approves_and_undoes_only_through_the_bluebook_baseline_routes():
    page = _baseline_page()
    # POST approves, DELETE takes the exam back out; both on the submission's /baseline.
    assert "'/bluebook/submissions/'+enc(id)+'/baseline'" in page
    assert "method:kind==='undo'?'DELETE':'POST'" in page
    # Whether an exam is already in the baseline comes from the exam's own status route.
    assert "'/bluebook/exams/'+enc(eid)+'/baseline'" in page
    # A held exam is shown as held (approval never overrides the drift check) and is
    # not offered again on this visit (the page remembers it; the server does not).
    assert "'held'" in page and "m.held=true" in page
    assert "does not override" in page and "not offered again" in page


def test_baseline_page_gets_its_sealed_exams_from_live_sealed_and_never_names_the_list_route():
    page = _baseline_page()
    assert "Live.sealed()" in page
    # The number of warnings is derived in live.js; the warnings themselves never arrive.
    assert "warning_count" in page
    assert ".warnings" not in page
    # Only a 403 (or a plan without Bluebook) is "off": Live.sealed() decides, not this page.
    assert "res.status===403||res.status===401" not in page


def test_baseline_page_reads_what_the_api_returns_and_nothing_else():
    page = _baseline_page()
    for endpoint in ("/readiness", "/samples/", "/text'", "/students/'+enc(ID)"):
        assert endpoint in page, endpoint
    # The per-sample weight is the API's own; recency is not recomputed here.
    assert "auth_weight" in page
    assert "RECENCY" not in page and "0.85" not in page
    # A sample's prose is put in as text, never as markup.
    assert ".pb').textContent=" in page
    # Bluebook's integrity readings are neither read nor named.
    for word in ("stylometric", "authenticity", "aiscore"):
        assert word not in page.lower(), f"baseline.html mentions {word}"
    # The per-tier profile comes from the shared feature table, without tiers 17 and 18.
    assert "js/feature-data.js" in page and "OF.tiers" in page


def test_baseline_page_says_what_the_baseline_holds_without_overclaiming():
    page = _baseline_page()
    # "Approved" is a teacher's act: only supervised, verified and imported samples.
    assert "const APPROVED=['proctored','verified','canvas']" in page
    # The server's authenticated_count is "counted" (student uploads are in it); it is
    # never called approved, and the server's own sentences say "counted" too.
    assert "replace(/authenticated/gi,'counted')" in page
    assert "'approved')" not in page
    # The full readiness rule, and the wording of the building verdict.
    assert "5 or more counted samples with an effective count of 3 or more" in page
    assert "results are less reliable; false alarms are likely" in page
    assert "cannot tell" not in page
    # Recency is by the order samples were added, not by the date written, and the
    # date field says it changes nothing.
    assert "by the order they were added, not the date written" in page
    assert "a little" not in page
    assert "It does not change how the paper is weighted." in page
    # The weight column is the verification weight; there is no tier average bar.
    assert "Verification weight" in page and "Effective weight" not in page
    assert "Each bar shows where the student’s usual value sits between the ends of Original’s expected range for that measure." in page
    # A held paste that is sent again is "held back", not "the second paper in a row".
    assert "This paper was held back" in page
    # A write whose answer never came may have been saved.
    assert "may not have been saved" in page


def test_baseline_page_has_one_write_in_flight_for_every_write():
    page = _baseline_page()
    for kind in ("startSave('paste')", "startSave('files')", "startSave(kind,id)"):
        assert kind in page, kind
    # Nothing writes without taking the flag first.
    assert page.count("Live.api('/students/'+enc(ID)+'/baseline'") == 1
    assert page.count("/baseline/upload-batch") == 1
    # ...and gives it back however it ends: each writer releases it in a finally
    # block, so a thrown error while drawing the result cannot leave the page locked.
    assert page.count("}finally{ endSave(); }") == 3
    assert "endSave(); return;" not in page
    assert "Saving..." in page


# The page's own script, run under node against stubbed endpoints: a write takes the
# one in-flight flag, every write button is disabled while it is held, and a second
# write started in the meantime is not sent.
BASELINE_HARNESS = r"""
const fs = require('fs');
const sc = JSON.parse(fs.readFileSync(0, 'utf8'));
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const store = new Map();
const window = {
  location: { href: 'http://suite.test/original/baseline.html?student=s1', origin: 'http://suite.test', replace() {} },
  localStorage: { getItem: (k) => (store.has(k) ? store.get(k) : null), removeItem: (k) => store.delete(k), key: () => null, length: 0 },
  sessionStorage: { removeItem() {} },
};
const location = { search: '?student=s1', href: window.location.href };
function makeEl(id) {
  return {
    id, textContent: '', innerHTML: '', className: '', hidden: false, disabled: false, value: '', style: {}, attrs: {}, handlers: {},
    classList: { add() {}, remove() {}, toggle() {}, contains() { return false; } },
    addEventListener(t, fn) { (this.handlers[t] = this.handlers[t] || []).push(fn); },
    setAttribute(k, v) { this.attrs[k] = String(v); },
    getAttribute(k) { return k in this.attrs ? this.attrs[k] : null; },
    appendChild() {}, querySelector() { return makeEl(); }, querySelectorAll() { return []; },
    closest() { return null; }, focus() {},
  };
}
const els = new Map();
const document = {
  readyState: 'complete',
  getElementById(id) { if (!els.has(id)) els.set(id, makeEl(id)); return els.get(id); },
  createElement() { return makeEl(); },
  querySelector() { return makeEl(); }, querySelectorAll() { return []; }, addEventListener() {},
};
// The lines of the message under the add forms. With sc.throwOnAddedMsg, drawing the
// "Added as sample" line throws, as a render bug would.
const addMsg = document.getElementById('add-msg');
addMsg.lines = [];
Object.defineProperty(addMsg, 'innerHTML', { get() { return ''; }, set() { addMsg.lines = []; } });
addMsg.appendChild = (c) => {
  if (sc.throwOnAddedMsg && /Added as sample/.test(c.textContent)) throw new Error('render boom');
  addMsg.lines.push(c.textContent);
};
process.on('unhandledRejection', () => {});
const calls = [];
const WORDS = Array.from({ length: 80 }, (_, i) => 'word' + i).join(' ');
let sample = 5;
let wrote = false;
function route(method, path) {
  if (path === '/health') return [200, { environment: 'demo' }];
  if (path === '/auth/me') return [401, {}];
  if (path === '/students') return [200, { students: ['s1'], roster: null }];
  // After a write the student cannot be read again (the write itself went through).
  if (sc.failStudentAfterWrite && wrote && path.startsWith('/students/s1')) return [500, { detail: 'boom' }];
  if (path === '/students/s1') {
    const samples = Array.from({ length: sample }, (_, i) => ({ index: i, assignment: 'A' + i, provenance: i === 0 ? 'unverified' : 'proctored', submitted_at: '2026-01-0' + (i + 1), auth_weight: 1 }));
    return [200, { student_id: 's1', sample_count: sample, authenticated_count: sample, purity: 0.5, effective_sample_count: 4, baseline_vector: {}, samples }];
  }
  if (path === '/students/s1/readiness') return [200, { verdict: 'developing', sample_count: sample, authenticated_count: sample, effective_sample_count: 4, recommendations: ['Collect 1 more authenticated sample(s) ' + String.fromCharCode(8212) + ' more is better.'], provenance_mix: {}, word_stats: null }];
  if (path === '/bluebook/students') return [200, { students: [] }];
  if (path === '/bluebook/exams') return [200, { exams: [] }];
  if (path === '/bluebook/submissions') return [200, { submissions: [{ id: 'x1', exam_id: 'e1', student_id: 's1', exam: 'Midterm', course: 'THEO', created_at: '2026-10-01T10:00:00Z', late: false, warnings: ['a', 'b'], ai_score: 0.9 }] }];
  if (path === '/bluebook/exams/e1/baseline') return [200, { submissions: [{ submission_id: 'x1', in_baseline: false, has_text: true }] }];
  if (method === 'POST' && path === '/students/s1/baseline') { sample += 1; wrote = true; return [200, { sample_index: sample - 1, provenance: 'verified' }]; }
  if (method === 'POST' && path === '/bluebook/submissions/x1/baseline') { sample += 1; return [200, { status: 'added' }]; }
  return [404, {}];
}
function fakeFetch(href, init) {
  const method = (init && init.method) || 'GET';
  const path = new URL(href).pathname;
  calls.push(method + ' ' + path);
  const [status, body] = route(method, path);
  const slow = (sc.delay && sc.delay[path]) || (method !== 'GET' ? 60 : 3);
  return new Promise((resolve) => setTimeout(() => resolve({ ok: status >= 200 && status < 300, status, text: () => Promise.resolve(JSON.stringify(body)) }), slow));
}
new Function('window', 'document', 'fetch', fs.readFileSync(sc.features, 'utf8'))(window, document, fakeFetch);
new Function('window', 'document', 'fetch', fs.readFileSync(sc.live, 'utf8'))(window, document, fakeFetch);
const page = fs.readFileSync(sc.page, 'utf8');
const scripts = Array.from(page.matchAll(/<script>([\s\S]*?)<\/script>/g)).map((m) => m[1]);
if (scripts.length !== 1) throw new Error('expected one inline script');
new Function('window', 'document', 'Live', 'location', scripts[0])(window, document, window.Live, location);
const el = (id) => document.getElementById(id);
const click = (id) => (el(id).handlers.click || []).forEach((fn) => fn({ target: el(id), preventDefault() {} }));
(async () => {
  const out = {};
  if (sc.early) {
    await sleep(sc.early);
    out.early = { sealed: el('sealed-list').innerHTML, short: el('short').innerHTML, meta: el('meta').textContent };
  }
  for (let i = 0; i < 300 && !el('sealed-list').innerHTML.includes('data-act="approve"'); i++) await sleep(10);
  out.before = { sealed: el('sealed-list').innerHTML, short: el('short').innerHTML, meta: el('meta').textContent, traj: el('traj-d').innerHTML };
  el('paste-text').value = WORDS;
  click('paste-go'); click('paste-go');
  await sleep(10);
  out.during = { paste: el('paste-go').disabled, pasteLabel: el('paste-go').textContent, files: el('files-go').disabled, sealed: el('sealed-list').innerHTML, noteAdd: el('save-note-add').hidden, noteSealed: el('save-note-sealed').hidden };
  // An approve clicked while the paste is saving is not sent.
  const btn = { disabled: false, getAttribute: (k) => ({ 'data-act': 'approve', 'data-id': 'x1' })[k] };
  (el('sealed-list').handlers.click || []).forEach((fn) => fn({ target: { closest: () => btn } }));
  await sleep(250);
  out.after = { paste: el('paste-go').disabled, pasteLabel: el('paste-go').textContent, lines: addMsg.lines, meta: el('meta').textContent };
  out.calls = calls.filter((c) => c.startsWith('POST'));
  process.stdout.write(JSON.stringify(out));
  process.exit(0);
})();
"""


def _baseline_run(**scenario) -> dict:
    run = subprocess.run(
        [shutil.which("node"), "-e", BASELINE_HARNESS],
        input=json.dumps(
            {
                "live": str(SUITE / "live.js"),
                "page": str(SUITE / "baseline.html"),
                "features": str(SUITE / "js" / "feature-data.js"),
                **scenario,
            }
        ),
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert run.returncode == 0, run.stderr
    assert run.stdout, "the page never finished loading"
    return json.loads(run.stdout)


@needs_node
def test_baseline_page_takes_one_write_at_a_time_and_says_it_is_saving():
    out = _baseline_run()
    # While the paste is saving: every write button is disabled and the page says so.
    during = out["during"]
    assert during["paste"] is True and during["pasteLabel"] == "Saving..."
    assert during["files"] is True
    assert during["noteAdd"] is False and during["noteSealed"] is False
    assert 'data-act="approve"' in during["sealed"] and " disabled" in during["sealed"]
    # Two clicks on Add and an Approve in the middle of it made exactly one write.
    assert out["calls"] == ["POST /students/s1/baseline"]
    # When it is done the buttons come back.
    assert out["after"]["paste"] is False and out["after"]["pasteLabel"] == "Add to baseline"


@needs_node
def test_baseline_page_counts_approved_samples_by_provenance_and_calls_the_servers_count_counted():
    out = _baseline_run()["before"]
    # 5 samples: one student upload (never "approved") and 4 supervised sittings.
    assert out["meta"] == "4 teacher-approved samples · 1 student upload"
    assert "5 counted samples (4 teacher-approved, 1 student upload)" in out["short"]
    assert "approved sample" not in out["short"].replace("teacher-approved", "")
    # The server's sentence is shown with its "authenticated" read as "counted", and no dash.
    assert "Collect 1 more counted sample(s): more is better." in out["traj"]
    assert "authenticated" not in out["traj"] and chr(0x2014) not in out["traj"]
    # This exam's warning count (a number) is shown; Bluebook's own readings never arrive.
    assert "2 lockdown warnings" in out["sealed"]
    assert "ai_score" not in out["sealed"] and "0.9" not in out["sealed"]


# ── Writing State and the Conversation Packet: wording and the verdict rule ───
# Both pages describe the same result to a teacher, so they say the same thing in
# the same words: a habit the server lists is "one of the habits furthest from
# <name>'s usual range in this paper, by Original's measure" (about a third of
# habits sit that far out by chance even in a student's own writing, so neither
# page counts them or calls them differences), and a baseline that is not rated
# ready makes the reading inconclusive. The pages' inline scripts are run under
# node for the parts that decide what is said.


def _writing_state() -> str:
    return (SUITE / "writing-state.html").read_text(encoding="utf-8")


def test_writing_state_has_one_testing_label_and_it_comes_first_in_the_result_column():
    page = _writing_state()
    assert page.count("data-testing-notice") == 1
    column = page.index('id="right-scroll"')
    assert column < page.index("data-testing-notice") < page.index('class="hero-inner"')


def test_writing_state_says_a_listed_habit_is_among_the_furthest_not_that_it_is_outside_the_range():
    page = _writing_state()
    # The detail panel's per-habit sentence, for a habit the server lists as furthest ...
    assert (
        "'This is one of the habits furthest from '+poss()+' usual range in this paper, "
        "by Original\\u2019s measure.'"
    ) in page
    # ... and for one it lists as closest.
    assert (
        "'This is one of the habits closest to '+poss()+' usual range in this paper, "
        "by Original\\u2019s measure.'"
    ) in page
    for gone in ("sits outside the range", "sits well within the range", "usually shows on this habit"):
        assert gone not in page, f"writing-state.html still says {gone!r}"


def test_writing_state_counts_no_habits_and_reads_no_explanation_text():
    page = _writing_state()
    # The server lists at most five habits, so any count would be a cap, not a finding.
    assert "of 97" not in page
    assert not re.search(r"at least '?\s*\+|at least \d", page)
    # Only the headline and the action are used: the response's explanation block
    # carries verdict and authorship wording.
    for field in ("confidence_note", "human_explanation"):
        assert field not in page, f"writing-state.html reads {field}"


def test_writing_state_cleans_the_label_it_keeps_on_this_computer():
    # professor.html's History puts a kept label into innerHTML unescaped.
    page = _writing_state()
    assert "original_portfolio_" in page
    assert """.replace(/[<>&"']/g,'')""" in page


def test_writing_state_calls_its_picture_decorative_and_names_no_symbol_that_is_not_drawn():
    page = _writing_state()
    assert "Writing pattern \u00b7 decorative" in page
    assert "The pattern above is decorative, not drawn from \u03c1: it is the same pattern for every student." in page
    # "fingerprint" is not a word the product uses for a student's writing.
    visible = re.sub(r"<script[\s\S]*?</script>|<style[\s\S]*?</style>|<[^>]+>", " ", page)
    assert "fingerprint" not in visible.lower()
    for symbol in ("|\u03c8\u1d62|", "|\u03be\u1d62|"):
        assert symbol not in page, f"the legend names {symbol}, which nothing draws"


def test_packet_says_the_same_thing_as_writing_state_about_a_listed_habit():
    page = _packet()
    for said in (
        "Furthest from their usual range",
        "This is one of the habits furthest from '+poss+' usual range in this paper, by Original\u2019s measure.",
        "(Original lists up to five.)",
        "treat this reading as inconclusive",
        "Offer a way to add reference writing",
        "What this habit measures:",
    ):
        assert said in page, said
    for gone in (
        "differs most",
        "sits outside the range",
        "Weigh the numbers",
        "path back",
        "en-GB",
        "In general terms:",
    ):
        assert gone not in page, f"packet.html still says {gone!r}"
    # The habit cards never call a listed habit "outside" anything.
    cards = page[page.index("function habitCards") : page.index("// ── where the baseline comes from")]
    assert "outside" not in cards.replace("sits outside '+poss+' usual range by Original", "")


def test_feature_descriptions_are_written_about_the_writer_not_to_them():
    # A teacher reads these about a student. Only the data (below the header
    # comment) is checked; the header may say "you".
    src = (SUITE / "js" / "feature-data.js").read_text(encoding="utf-8")
    data = src[src.index("(function () {") :]
    found = re.findall(r"\b(?:you|your|yours|yourself|you're|you've)\b", data, re.IGNORECASE)
    assert not found, f"second person in feature-data.js: {found}"


# "authentic" is a verdict word and the suite shows none: not "% authentic", not a
# tier called "Authenticity". The server's field name authenticated_count is a
# count of the samples that join a baseline, read by the pages but never printed,
# and baseline.html rewrites the server's own "authenticated" into "counted".
# settings.html matches the server's "Not authenticated" (a 401 with that detail
# means the session ended) so that it can say "Your sign-in has expired" instead.
_AUTHENTIC_ALLOWED = (
    "authenticated_count",
    "replace(/authenticated/gi,'counted')",
    r"/^not authenticated\.?$/i",
)


def _displayed_authentic(text: str) -> list[str]:
    found = []
    for line in text.splitlines():
        if line.lstrip().startswith("//"):
            continue
        for allowed in _AUTHENTIC_ALLOWED:
            line = line.replace(allowed, "")
        found.extend(re.findall(r"\w*authentic\w*", line, re.IGNORECASE))
    return found


def test_the_authentic_check_allows_the_api_field_name_and_nothing_else():
    assert _displayed_authentic("const a = bc.authenticated_count;") == []
    assert _displayed_authentic("// its authenticated is a sample it counts") == []
    assert _displayed_authentic("String(t).replace(/authenticated/gi,'counted')") == []
    assert _displayed_authentic(r"/^not authenticated\.?$/i.test(said)") == []
    for shown in ("75% authentic", "Voice Authenticity", "<b>Authentic</b>", "an authenticated sample", "authentically"):
        assert _displayed_authentic(shown), shown


@pytest.mark.parametrize("path", _code_files(), ids=lambda p: p.relative_to(SUITE).as_posix())
def test_no_suite_file_shows_the_word_authentic(path):
    assert _displayed_authentic(path.read_text(encoding="utf-8")) == [], path.name


# authenticated_count is every sample the server weighs above zero: a teacher-approved one or
# a student's own upload. It is "counted", never "approved" (a count of what a teacher
# approved needs the sample list and its provenance). So no file may call a sample
# "approved" without saying "teacher-approved", and the places that show the server's count
# say "counted". Pinned as exact strings so a reword cannot quietly bring the label back.
_APPROVED_SAMPLES = re.compile(r"(?<!teacher-)(?<!teacher )\bapproved (?:baseline )?samples?\b", re.IGNORECASE)

COUNTED_LABELS = {
    "index.html": ("<th>Counted samples</th>", "plural(r.counted,'counted sample')", "$('stat1-l').textContent='Counted samples'"),
    "writing-state.html": ("plural(counted()||0,'counted sample')", "READY_NEEDS='ready needs 5 or more counted samples and an effective count of 3 or more'", "' teacher-approved'"),
    "packet.html": ("plural(nUsed,'counted sample')", "poss+' counted samples'", "' teacher-approved)'"),
    "reports.html": ("5 or more counted samples with an effective count of 3 or more",),
}


@pytest.mark.parametrize("path", [*_code_files()], ids=lambda p: p.relative_to(SUITE).as_posix())
def test_no_suite_file_calls_the_servers_count_approved(path):
    found = [m.group(0) for m in _APPROVED_SAMPLES.finditer(path.read_text(encoding="utf-8"))]
    assert found == [], f"{path.name} calls an authenticated_count 'approved': {found}"


def test_the_approved_sample_check_allows_teacher_approved_and_nothing_else():
    for fine in ("4 teacher-approved samples", "plural(a,'teacher-approved sample')", "a teacher approved samples"):
        assert _APPROVED_SAMPLES.findall(fine) == [], fine
    for bad in ("5 approved samples", "plural(n,'approved sample')", "Approved samples", "1 approved baseline sample"):
        assert _APPROVED_SAMPLES.findall(bad), bad


@pytest.mark.parametrize("name", sorted(COUNTED_LABELS))
def test_pages_that_show_the_servers_count_call_it_counted(name):
    page = (SUITE / name).read_text(encoding="utf-8")
    for label in COUNTED_LABELS[name]:
        assert label in page, f"{name} lost {label!r}"


def test_the_roster_hands_pages_a_counted_field_and_no_approved_one():
    live = (SUITE / "live.js").read_text(encoding="utf-8")
    assert "counted: r.ac," in live and "approved: r.ac" not in live
    for page in PAGES:
        assert "s.approved" not in page.read_text(encoding="utf-8"), page.name


# The server's baseline verdict has one set of words, in live.js, and every page that names it
# uses them: ready is "Ready", developing "Building", insufficient "Needs more", and a missing
# or unknown verdict "Not available". No page keeps a map of its own or prints the raw verdict.
VERDICT_WORDS = {"ready": "Ready", "developing": "Building", "insufficient": "Needs more"}

WORDS_RUN = r"""
const fs = require('fs');
const sc = JSON.parse(fs.readFileSync(0, 'utf8'));
const window = {};
const document = { readyState: 'complete', querySelectorAll() { return []; }, addEventListener() {} };
new Function('window', 'document', fs.readFileSync(sc.live, 'utf8'))(window, document);
const L = window.Live;
process.stdout.write(JSON.stringify({
  words: L.VERDICT_WORDS, frozen: Object.isFrozen(L.VERDICT_WORDS),
  said: sc.values.map((v) => L.verdictWord(v)),
}));
"""

PAGES_THAT_NAME_THE_VERDICT = ("index.html", "students.html", "reports.html", "writing-state.html", "packet.html", "baseline.html")
RETIRED_VERDICT_LABELS = (
    "No baseline yet",
    "Building baseline",
    "Baseline ready<",
    "baseline too thin",
    "baseline building",
    "label:'None yet'",
    "miniRow('None yet'",
    "const VERDICT_WORDS",
)


@needs_node
def test_live_js_has_the_one_set_of_baseline_readiness_words():
    values = ["ready", "developing", "insufficient", None, "", "banana", "constructor", "__proto__", "toString", 3]
    run = subprocess.run(
        [shutil.which("node"), "-e", WORDS_RUN],
        input=json.dumps({"live": str(SUITE / "live.js"), "values": values}),
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert run.returncode == 0, run.stderr
    got = json.loads(run.stdout)
    assert got["words"] == VERDICT_WORDS and got["frozen"] is True
    # Only the server's three words are words; everything else, an inherited property name included, is not.
    assert got["said"] == ["Ready", "Building", "Needs more"] + ["Not available"] * 7


@pytest.mark.parametrize("name", PAGES_THAT_NAME_THE_VERDICT)
def test_pages_that_name_the_baseline_verdict_use_the_shared_words(name):
    page = (SUITE / name).read_text(encoding="utf-8")
    assert "Live.verdictWord(" in page or "Live.VERDICT_WORDS" in page, f"{name} keeps its own words"
    for retired in RETIRED_VERDICT_LABELS:
        assert retired not in page, f"{name} still says {retired!r}"


def test_students_page_markup_says_the_shared_words_before_the_script_runs():
    page = (SUITE / "students.html").read_text(encoding="utf-8")
    for verdict, word in VERDICT_WORDS.items():
        assert f'data-verdict="{verdict}">Baseline: {word}</div>' in page, verdict
        assert f'data-f="{verdict}" aria-pressed="false">{word}</button>' in page, verdict


def test_pages_never_print_the_raw_verdict():
    index = (SUITE / "index.html").read_text(encoding="utf-8")
    assert "'Baseline: '+Live.verdictWord(r.verdict)" in index
    assert "r.verdict+'.'" not in index and "'Baseline: '+r.verdict" not in index
    # An unknown verdict is "Not available" in the places that used to print a dash or nothing.
    baseline = (SUITE / "baseline.html").read_text(encoding="utf-8")
    assert "vv.textContent=Live.verdictWord(v);" in baseline
    assert "' · Baseline: '+Live.verdictWord(s.verdict)" in (SUITE / "writing-state.html").read_text(encoding="utf-8")


def _extract(script: str, name: str) -> str:
    """The source of one top-level ``const name=...;`` line or ``function name(...)``
    of a page's inline script, so a test can run just the part that decides."""
    line = re.search(rf"^\s*const {name}=[^\n]*;$", script, re.M)
    if line:
        return line.group(0)
    head = re.search(rf"^\s*function {name}\(", script, re.M)
    assert head, f"no {name} in the page's script"
    depth = 0
    for i in range(script.index("{", head.end()), len(script)):
        depth += (script[i] == "{") - (script[i] == "}")
        if depth == 0:
            return script[head.start() : i + 1]
    raise AssertionError(f"{name} is not closed")


VERDICT_RUN = r"""
const fs = require('fs');
const sc = JSON.parse(fs.readFileSync(0, 'utf8'));
// The real live.js, so the words under test are the shared map's, not a copy.
const window = {};
const document = { readyState: 'complete', querySelectorAll() { return []; }, addEventListener() {} };
new Function('window', 'document', fs.readFileSync(sc.live, 'utf8'))(window, document);
const out = sc.cases.map((S) => {
  const esc = String;
  const api = new Function('S', 'esc', 'Live', sc.src + '\nreturn {resultVerdict, verdictNow, thinResultLine, thinNote};')(S, esc, window.Live);
  return {
    result: api.resultVerdict(), now: api.verdictNow(), line: api.thinResultLine(), note: api.thinNote(),
  };
});
process.stdout.write(JSON.stringify(out));
"""


def _verdicts(cases: list[dict]) -> list[dict]:
    script = _inline_scripts(SUITE / "writing-state.html")
    src = "\n".join(
        _extract(script, name)
        for name in (
            "num", "plural", "baselineHref", "APPROVED", "counted", "teacherApproved", "countedPhrase",
            "READY_NEEDS", "rated", "resultVerdict", "verdictNow", "thinResultLine", "thinNote",
        )
    )
    run = subprocess.run(
        [shutil.which("node"), "-e", VERDICT_RUN],
        input=json.dumps({"src": src, "cases": cases, "live": str(SUITE / "live.js")}),
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert run.returncode == 0, run.stderr
    return json.loads(run.stdout)


def _scored(authenticated, effective, **state) -> dict:
    bc = {}
    if authenticated is not None:
        bc["authenticated_count"] = authenticated
    if effective is not None:
        bc["effective_sample_count"] = effective
    return {"id": "s1", "student": None, "verdict": None, "result": {"baseline_confidence": bc}, **state}


@needs_node
@pytest.mark.parametrize(
    "authenticated,effective,verdict",
    [
        (5, 3.0, "ready"),
        (5, 2.9, "developing"),  # five samples that barely count are still building
        (9, 2.0, "developing"),
        (4, 10, "developing"),
        (3, 0, "developing"),
        (2, 0, "insufficient"),  # below the 3-paper minimum Original does not compare
        (1, 1, "insufficient"),
        (0, 0, "insufficient"),
        (None, 3, None),  # a missing field is no verdict, never "fine"
        (5, None, None),
        (None, None, None),
    ],
)
def test_writing_state_applies_the_servers_readiness_rule_to_the_score_response(authenticated, effective, verdict):
    (got,) = _verdicts([_scored(authenticated, effective)])
    assert got["result"] == verdict
    assert got["now"] == verdict  # no roster verdict: the derived one stands in


@needs_node
def test_writing_state_has_no_derived_verdict_before_a_result():
    (got,) = _verdicts([{"id": "s1", "student": None, "verdict": None, "result": None}])
    assert got["result"] is None and got["now"] is None


@needs_node
def test_writing_state_prefers_the_rosters_verdict_over_the_one_it_derives():
    ready, building = _verdicts(
        [
            _scored(2, 0, verdict="ready"),  # the roster says ready: nothing is added
            _scored(5, 5, verdict="developing"),
        ]
    )
    assert ready["now"] == "ready" and ready["line"] == "" and ready["note"] == ""
    assert building["now"] == "developing" and "\u201cBuilding\u201d" in building["line"]


@needs_node
def test_writing_state_adds_the_inconclusive_line_unless_the_baseline_is_ready():
    ready, building, thin, unreadable = _verdicts(
        [_scored(5, 3), _scored(3, 2), _scored(1, 1), _scored(None, None)]
    )
    assert ready["line"] == ""
    assert building["line"] == (
        " Original rates this baseline \u201cBuilding\u201d (3 counted samples; "
        "ready needs 5 or more counted samples and an effective count of 3 or more), so treat this reading as inconclusive."
    )
    assert thin["line"] == (
        " Original rates this baseline \u201cNeeds more\u201d (1 counted sample; "
        "ready needs 5 or more counted samples and an effective count of 3 or more), so treat this reading as inconclusive."
    )
    # Nothing could be read: the page says so rather than leave the reading unqualified.
    assert unreadable["line"] == (
        " Original could not read this baseline\u2019s readiness, so treat this reading as inconclusive."
    )
    # The card's own note speaks only for a rated-thin baseline.
    assert ready["note"] == "" and unreadable["note"] == ""
    assert "\u201cBuilding\u201d (3 counted samples; ready needs 5 or more counted samples and an effective count of 3 or more)" in building["note"]
    assert "\u201cNeeds more\u201d (1 counted sample; ready needs 5 or more counted samples and an effective count of 3 or more)" in thin["note"]


def _record(counted: int, *provenances: str) -> dict:
    return {"authenticated_count": counted, "samples": [{"provenance": p} for p in provenances]}


@needs_node
def test_writing_state_counts_teacher_approved_samples_apart_from_counted_ones():
    # authenticated_count is every sample the server weighs, a student upload included: it is
    # "counted". The sample list says which of them a teacher approved (proctored, verified,
    # canvas), and that number is shown beside it, never in its place.
    split, no_list, stale = _verdicts(
        [
            _scored(3, 2, student=_record(3, "proctored", "verified", "unverified")),
            _scored(3, 2, student={"authenticated_count": 3}),  # no sample list: no split to give
            _scored(3, 2, student=_record(5, "proctored", "proctored", "verified", "canvas", "unverified")),
        ]
    )
    assert "(3 counted samples, 2 teacher-approved; ready needs 5 or more counted samples and an effective count of 3 or more)" in split["line"]
    assert "(3 counted samples, 2 teacher-approved; ready needs 5 or more counted samples and an effective count of 3 or more)" in split["note"]
    assert "teacher-approved" not in no_list["line"] and "(3 counted samples;" in no_list["line"]
    # The analysis counted 3 and the record now says 5: splitting 5 by provenance beside a 3 would mislead.
    assert "teacher-approved" not in stale["line"] and "(3 counted samples;" in stale["line"]


# The packet's inline script, run for real under node: the stored analysis is in
# sessionStorage, the student record and readiness are stubbed endpoints.
PACKET_TAIL = r"""
new Function('window', fs.readFileSync(sc.features, 'utf8'))(window);
const page = fs.readFileSync(sc.page, 'utf8');
const scripts = Array.from(page.matchAll(/<script>([\s\S]*?)<\/script>/g)).map((m) => m[1]);
if (scripts.length !== 1) throw new Error('expected one inline script, found ' + scripts.length);
const getById = document.getElementById.bind(document);
document.getElementById = (id) => {
  const e = getById(id);
  if (!e.insertAdjacentElement) e.insertAdjacentElement = function () {};
  return e;
};
window.sessionStorage.setItem('original_last_result', JSON.stringify(sc.stored));
new Function('window', 'document', 'Live', "'use strict';\n" + scripts[0])(window, document, window.Live);
const el = (id) => document.getElementById(id);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
(async () => {
  for (let i = 0; i < 500 && !el('p-baseline').innerHTML && !el('paper').innerHTML; i++) await sleep(10);
  await sleep(30);
  process.stdout.write(JSON.stringify({
    habits: el('p-habits').innerHTML, baseline: el('p-baseline').innerHTML, sub: el('p-sub').innerHTML,
    status: el('status').textContent, calls,
  }));
})();
"""


def _packet_run(stored_counts=None, student=None, readiness=None, habit=True, **scenario) -> dict:
    listed = {
        True: [{"code": "dash_rate", "name": "Dash Rate", "tier": 4, "baseline_value": 0.5, "submission_value": 0.1}],
        False: [],
        # The server named a habit but no figures were kept with the analysis.
        "no-figures": [{"code": "dash_rate"}],
    }[habit]
    result = {
        "interference": {"destructive_features": listed},
        "feature_vector": {},
        "baseline_vector": {},
        "baseline_confidence": stored_counts or {},
    }
    stored = {
        "kind": "original_writing_state", "version": 1, "student_id": "s1", "student_name": "Ada",
        "assignment": "Essay", "analysed_at": "2026-10-09T12:00:00Z", "word_count": 500,
        "summary": "Overall: worth a conversation, not a conclusion.", "result": result,
    }
    routes = {"/students/s1": student or [500, {"detail": "boom"}]}
    run = subprocess.run(
        [shutil.which("node"), "-e", PRELUDE + PACKET_TAIL],
        input=json.dumps(
            {
                "live": str(SUITE / "live.js"),
                "page": str(SUITE / "packet.html"),
                "features": str(SUITE / "js" / "feature-data.js"),
                "stored": stored,
                "routes": routes,
                "readinessDefault": readiness or [500, {"detail": "boom"}],
                **scenario,
            }
        ),
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert run.returncode == 0, run.stderr
    assert run.stdout, "the packet never finished loading"
    return json.loads(run.stdout)


def _samples(n: int) -> list:
    return [
        {"index": i, "assignment": f"Paper {i}", "provenance": "proctored", "submitted_at": "2025-01-2%d" % (i % 10)}
        for i in range(n)
    ]


@needs_node
def test_packet_card_describes_a_listed_habit_in_the_neutral_words_of_writing_state():
    out = _packet_run({"authenticated_count": 5, "effective_sample_count": 4}, student=[200, {"samples": _samples(5)}])
    habits = out["habits"]
    assert "This is one of the habits furthest from Ada\u2019s usual range in this paper, by Original\u2019s measure." in habits
    assert "outside" not in habits
    assert "<b>What this habit measures:</b> How often dashes (like this) interrupt or extend a sentence." in habits
    # 0.1 against 0.5: lower by 0.40, on the scale the page names.
    assert "Here the paper is lower than Ada\u2019s usual by 0.40, on a scale from 0 to 1." in habits
    assert "5 counted samples" in habits


@needs_node
def test_packet_with_an_unknown_approved_count_prints_no_count_and_says_so():
    # Neither the analysis nor the student record has a count: not "0 counted".
    out = _packet_run({}, student=[500, {"detail": "boom"}])
    assert not re.search(r"\d+ counted sample", out["habits"])
    assert "A weighted average of Ada\u2019s counted samples" in out["habits"]
    assert "compared against" not in out["sub"]
    assert "Original could not read this baseline\u2019s readiness, so treat this reading as inconclusive." in out["baseline"]
    assert "could not be loaded just now" in out["baseline"]


@needs_node
@pytest.mark.parametrize(
    "counts,said,not_said",
    [
        ({"authenticated_count": 5, "effective_sample_count": 3}, "A paper on a new topic or in a new genre", "inconclusive"),
        ({"authenticated_count": 5, "effective_sample_count": 2.9}, "\u201cBuilding\u201d", None),
        ({"authenticated_count": 3, "effective_sample_count": 0}, "\u201cBuilding\u201d", None),
        ({"authenticated_count": 1, "effective_sample_count": 1}, "\u201cNeeds more\u201d", None),
        ({"authenticated_count": 5}, "could not read this baseline", "\u201cBuilding\u201d"),
        ({}, "could not read this baseline", "\u201cNeeds more\u201d"),
    ],
    ids=["ready", "five-barely-counting", "three-samples", "one-sample", "no-effective-count", "no-counts"],
)
def test_packet_falls_back_to_the_counts_stored_with_the_analysis_when_readiness_fails(counts, said, not_said):
    out = _packet_run(counts, student=[200, {"samples": _samples(3)}])  # readiness: 500
    assert said in out["baseline"]
    if not_said:
        assert not_said not in out["baseline"]
    if said != "A paper on a new topic or in a new genre":
        assert "treat this reading as inconclusive" in out["baseline"]


@needs_node
@pytest.mark.parametrize(
    "readiness,said",
    [
        ([200, {"verdict": "insufficient"}], "\u201cNeeds more\u201d"),  # a fresh answer beats the stored counts
        ([200, {"verdict": "developing"}], "\u201cBuilding\u201d"),
        ([200, {"verdict": "banana"}], "A paper on a new topic or in a new genre"),  # not a word of the server's: stored counts
        ([200, {}], "A paper on a new topic or in a new genre"),
    ],
)
def test_packet_trusts_a_fresh_readiness_verdict_only_when_it_is_one_of_the_servers_three(readiness, said):
    counts = {"authenticated_count": 5, "effective_sample_count": 4}
    out = _packet_run(counts, student=[200, {"samples": _samples(5)}], readiness=readiness)
    assert said in out["baseline"]


@needs_node
@pytest.mark.parametrize(
    "student,table_says",
    [
        ([500, {"detail": "boom"}], "could not be loaded just now"),
        ([200, {"samples": []}], "No samples are on file"),
    ],
    ids=["list-fails", "list-empty"],
)
def test_packet_keeps_the_thin_baseline_caution_when_the_sample_list_is_missing(student, table_says):
    out = _packet_run({"authenticated_count": 1, "effective_sample_count": 1}, student=student)
    assert table_says in out["baseline"]
    assert "\u201cNeeds more\u201d" in out["baseline"] and "treat this reading as inconclusive" in out["baseline"]


def _mixed_samples() -> list:
    """Four supervised or verified or imported samples and one student upload."""
    kinds = ["proctored", "verified", "canvas", "proctored", "unverified"]
    return [
        {"index": i, "assignment": f"Paper {i}", "provenance": k, "submitted_at": "2025-01-2%d" % i}
        for i, k in enumerate(kinds)
    ]


@needs_node
def test_packet_counts_teacher_approved_samples_apart_from_counted_ones_and_uses_baseline_words():
    counts = {"authenticated_count": 5, "effective_sample_count": 4}
    out = _packet_run(
        counts, student=[200, {"authenticated_count": 5, "samples": _mixed_samples()}]
    )
    # The server's count is "counted"; the sample list says how many of them a teacher approved.
    assert "<b>5 counted samples</b> (4 teacher-approved)" in out["sub"]
    assert "On file now: 5 samples, 4 teacher-approved and 1 student upload." in out["baseline"]
    # The provenance words are the ones baseline.html uses.
    for word in ("Supervised sitting", "Verified by teacher", "Imported", "Student upload"):
        assert f'<span class="how">{word}</span>' in out["baseline"], word
    for retired in ("Proctored exam", "Teacher verified", "Imported from a course site", "Not verified"):
        assert retired not in out["baseline"], retired


@needs_node
def test_packet_gives_no_teacher_approved_split_beside_a_count_the_record_no_longer_has():
    # The analysis counted 4; the record now holds 5. A split of 5 beside a 4 would mislead.
    counts = {"authenticated_count": 4, "effective_sample_count": 4}
    out = _packet_run(
        counts, student=[200, {"authenticated_count": 5, "samples": _mixed_samples()}]
    )
    assert "<b>4 counted samples</b>" in out["sub"] and "teacher-approved" not in out["sub"]
    assert "This analysis compared the paper with 4 counted samples; 5 are on file now." in out["baseline"]


@needs_node
def test_packet_with_no_listed_habits_says_so_and_with_unkept_figures_says_that_instead():
    counts = {"authenticated_count": 5, "effective_sample_count": 4}
    none = _packet_run(counts, student=[200, {"samples": _samples(5)}], habit=False)
    assert (
        "None of the habits measured in this paper sits outside Ada\u2019s usual range by Original\u2019s measure"
        in none["habits"]
    )
    unkept = _packet_run(counts, student=[200, {"samples": _samples(5)}], habit="no-figures")
    assert "The figures for these habits were not kept with this analysis" in unkept["habits"]
    assert "None of the habits" not in unkept["habits"]


# ── Voice Baseline: the follow-up reads, the save lock and the opening load ──


def test_baseline_page_words_the_purity_note_and_the_upload_note_as_it_counts():
    page = _baseline_page()
    # Purity describes the papers the server counts, which are not all "approved".
    assert "how alike the counted papers are to one another" in page
    assert "how alike the approved papers" not in page
    # Student uploads still count for now; the page says that will stop, not that
    # anyone's uploads are being taken away.
    assert "new student uploads will stop counting" in page
    assert "are being retired" not in page


@needs_node
def test_baseline_page_draws_the_student_before_the_sealed_list_has_loaded():
    # The sealed list is three requests and then a readiness call per student; the
    # student's own baseline needs only two, so it is drawn without waiting for it.
    out = _baseline_run(early=300, delay={"/bluebook/submissions": 900})
    early = out["early"]
    assert early["meta"] == "4 teacher-approved samples \u00b7 1 student upload"
    assert "5 counted samples" in early["short"]
    assert 'data-act="approve"' not in early["sealed"]
    # ...and the sealed exams are there once they arrive.
    assert 'data-act="approve"' in out["before"]["sealed"]


@needs_node
def test_baseline_page_does_not_say_how_many_samples_a_student_has_when_it_could_not_read_them_again():
    out = _baseline_run(failStudentAfterWrite=True)
    lines = out["after"]["lines"]
    assert lines[0] == "Added as sample 6. The count could not be refreshed just now. Reload the page to see it."
    assert not [line for line in lines if "now has" in line or "teacher-approved sample" in line]


@needs_node
def test_baseline_page_still_says_how_many_when_the_follow_up_read_works():
    out = _baseline_run()
    assert out["after"]["lines"][0] == "Added as sample 6. s1 now has 5 teacher-approved samples."


@needs_node
def test_baseline_page_gives_back_the_save_lock_even_when_drawing_the_result_throws():
    out = _baseline_run(throwOnAddedMsg=True)
    assert out["after"]["paste"] is False and out["after"]["pasteLabel"] == "Add to baseline"


# ── Settings (settings.html) ──────────────────────────────────────────────────


def _settings() -> str:
    return (SUITE / "settings.html").read_text(encoding="utf-8")


def test_settings_page_reads_no_roster_and_sets_its_messages_as_text_only():
    page = _settings()
    # It is about the account and nothing about a student.
    assert "Live.roster" not in page and "Live.sealed" not in page
    assert "/students" not in page
    # What the server says (a sentence of its own) is shown as text, never as markup.
    code = _inline_scripts(SUITE / "settings.html")
    assert not re.search(r"\b(?:msg|errLine)\.innerHTML", code)
    assert code.count("msg.textContent=") == 1 and code.count("errLine.textContent=") == 1


def test_settings_page_is_not_gated_on_the_original_product_and_says_why():
    code = _inline_scripts(SUITE / "settings.html")
    # A workspace with Original off still has an account, products, courses and a password.
    assert "deliberately not gated on the Original product" in code
    assert "Live.gate(main)" in code  # only for signed-out visitors and students
    assert "indexOf('original')" not in code


def test_settings_page_marks_up_its_password_form_for_a_screen_reader():
    page = _settings()
    fieldset = page[page.index("<fieldset") : page.index("</fieldset>")]
    assert "<legend>Change your password</legend>" in fieldset
    # Progress and success are a polite status; a problem is an alert of its own.
    assert '<div class="pw-msg" id="pw-msg" role="status" aria-live="polite"></div>' in page
    assert '<div class="pw-msg err" id="pw-err" role="alert"></div>' in page
    assert "Choose a new password for your account." in page and "for this sign-in" not in page


def test_settings_page_names_every_staff_role_in_plain_words():
    page = _settings()
    assert "super_admin:'Platform admin'" in page
    for role in ("professor:'Teacher'", "admin:'Workspace admin'", "operator:'Operator'"):
        assert role in page


SETTINGS_TAIL = r"""
const page = fs.readFileSync(sc.page, 'utf8');
const scripts = Array.from(page.matchAll(/<script>([\s\S]*?)<\/script>/g)).map((m) => m[1]);
if (scripts.length !== 1) throw new Error('expected one inline script, found ' + scripts.length);
if (sc.breakCourses) {
  const real = window.Live.api;
  window.Live.api = (p, o) => (p === '/bluebook/courses' ? Promise.reject(new Error('down')) : real(p, o));
}
new Function('window', 'document', 'Live', "'use strict';\n" + scripts[0])(window, document, window.Live);
const el = (id) => document.getElementById(id);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
(async () => {
  for (let i = 0; i < 500 && !el('courses').innerHTML; i++) await sleep(10);
  await sleep(20);
  const out = { courses: el('courses').innerHTML, account: el('account').innerHTML, fieldsDisabled: el('pw-fields').disabled };
  if (sc.password) {
    el('pw-current').value = sc.password.current;
    el('pw-new').value = sc.password.next;
    el('pw-again').value = sc.password.again;
    el('pw-form').handlers.submit.forEach((fn) => fn({ preventDefault() {} }));
    await sleep(80);
    out.msg = el('pw-msg').textContent; out.err = el('pw-err').textContent;
    out.fields = [el('pw-current').value, el('pw-new').value, el('pw-again').value];
  }
  process.stdout.write(JSON.stringify(Object.assign(out, { calls })));
})();
"""

TEACHER = {"original_principal_token": "t"}


def _teacher_me(products=("original", "bluebook"), role="professor") -> list:
    return [200, {"role": role, "products": list(products), "tenant_id": "ten"}]


def _settings_run(**scenario) -> dict:
    run = subprocess.run(
        [shutil.which("node"), "-e", PRELUDE + SETTINGS_TAIL],
        input=json.dumps({"live": str(SUITE / "live.js"), "page": str(SUITE / "settings.html"), **scenario}),
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert run.returncode == 0, run.stderr
    assert run.stdout, "the page never finished loading"
    return json.loads(run.stdout)


def _change_password(reply, **extra) -> dict:
    return _settings_run(
        local=TEACHER,
        me=_teacher_me(),
        routes={"/auth/password": reply, "/bluebook/courses": [200, {"courses": []}]},
        password={"current": "old-secret", "next": "new-secret-1", "again": "new-secret-1"},
        **extra,
    )


@needs_node
@pytest.mark.parametrize(
    "reply,said",
    [
        ([401, {}], "Your sign-in has expired. Sign in again."),
        ([401, None], "Your sign-in has expired. Sign in again."),
        ([401, {"detail": "Not authenticated"}], "Your sign-in has expired. Sign in again."),
        ([401, {"detail": "Current password is incorrect."}], "Current password is incorrect."),
        ([422, {"detail": "Password must be at least 8 characters."}], "Password must be at least 8 characters."),
        ([429, {"detail": "Too many attempts. Try again later."}], "Too many attempts. Try again later."),
        ([500, {"detail": "Internal Server Error"}], "The server had a problem. Try again."),
        ([502, None], "The server had a problem. Try again."),
        ([404, None], "The server had a problem. Try again."),  # a reply that is not JSON
        ([422, {"detail": [{"msg": "field required"}]}], "Your password could not be changed. Check the three fields and try again."),
    ],
    ids=["401-empty", "401-no-body", "401-not-authenticated", "401-wrong-password", "422-sentence", "429", "500", "502-no-body", "404-no-body", "422-list"],
)
def test_settings_page_tells_a_teacher_what_happened_when_the_password_is_refused(reply, said):
    out = _change_password(reply)
    assert out["err"] == said and out["msg"] == ""
    assert out["fields"][0] == "old-secret"  # a refused change keeps what was typed


@needs_node
def test_settings_page_says_so_when_the_server_cannot_be_reached():
    out = _change_password([200, {"ok": True}], rejectOn=["^/auth/password$"])
    assert out["err"] == "Could not reach the server. Try again in a moment."


@needs_node
def test_settings_page_clears_the_fields_and_says_so_when_the_password_is_changed():
    out = _change_password([200, {"ok": True}])
    assert out["msg"] == "Your password was changed." and out["err"] == ""
    assert out["fields"] == ["", "", ""]
    assert [c for c in out["calls"] if c == "/auth/password"] == ["/auth/password"]


@needs_node
def test_settings_page_does_not_send_a_password_that_does_not_match_its_copy():
    out = _settings_run(
        local=TEACHER, me=_teacher_me(), routes={"/bluebook/courses": [200, {"courses": []}]},
        password={"current": "old-secret", "next": "new-secret-1", "again": "new-secret-2"},
    )
    assert out["err"] == "The two new passwords do not match." and "/auth/password" not in out["calls"]


@needs_node
@pytest.mark.parametrize(
    "scenario,said",
    [
        (dict(me=_teacher_me(("original",))), "Courses are kept in Collections, which is off for this workspace."),
        (dict(routes={"/bluebook/courses": [403, {"detail": "no"}]}), "Courses are kept in Collections, which is off for this workspace."),
        (dict(routes={"/bluebook/courses": [500, {"detail": "boom"}]}), "Your courses could not be loaded just now."),
        (dict(routes={"/bluebook/courses": [200, {"courses": "nope"}]}), "Your courses could not be loaded just now."),
        (dict(routes={"/bluebook/courses": [200, None]}), "Your courses could not be loaded just now."),
        (dict(routes={"/bluebook/courses": [200, {"courses": []}]}), 'No courses yet. <a href="/bluebook/#courses">Add one in Collections</a>.'),
        (dict(routes={"/bluebook/courses": [200, {"courses": [None, "x"]}]}), 'No courses yet. <a href="/bluebook/#courses">Add one in Collections</a>.'),
        (dict(breakCourses=True), "Your courses could not be loaded just now."),
        (
            dict(routes={"/bluebook/courses": [200, {"courses": [{"code": "THEO 301", "name": "Theology", "students": 4, "exams": 1, "active": True}]}]}),
            "THEO 301: Theology",
        ),
    ],
    ids=["no-bluebook", "403", "500", "not-a-list", "not-json", "empty", "junk-rows", "request-throws", "one-course"],
)
def test_settings_page_courses_card_always_ends_in_a_real_answer(scenario, said):
    base = dict(local=TEACHER, me=_teacher_me())
    base.update(scenario)
    out = _settings_run(**base)
    assert said in out["courses"], out["courses"]


@needs_node
def test_settings_page_shows_a_platform_admin_by_name_and_a_signed_in_account_can_change_its_password():
    out = _settings_run(local=TEACHER, me=_teacher_me(role="super_admin"), routes={"/bluebook/courses": [200, {"courses": []}]})
    assert "Platform admin" in out["account"] and out["fieldsDisabled"] is False


# ── Bluebook Sessions (bluebook.html) ─────────────────────────────────────────
# Owner decision 2026-10-11: the Bluebook pill on a teacher page opens this suite
# page; /bluebook/ itself is the public sign-up and learn site, and the Bluebook
# app opens one exam from a link (#exam/<id>, #live/<id>; demo/bluebook/deep-link.jsx).

_PILL = re.compile(r'<a class="pill[^"]*" href="([^"]*)"[^>]*>(?:<svg.*?</svg>)?([^<]*)</a>', re.S)


def _bluebook_pills(path: Path) -> list[str]:
    return [href for href, label in _PILL.findall(path.read_text(encoding="utf-8")) if label.strip() == "Collections"]


@pytest.mark.parametrize("path", PAGES, ids=lambda p: p.name)
def test_the_bluebook_pill_opens_the_suite_page_for_teachers_and_the_app_for_students(path):
    want = "/bluebook/" if path.name in STUDENT_PAGES else "bluebook.html"
    assert _bluebook_pills(path) == [want], path.name


def test_the_bluebook_pill_is_marked_current_only_on_the_bluebook_page():
    page = (SUITE / "bluebook.html").read_text(encoding="utf-8")
    assert '<a class="pill on" href="bluebook.html" aria-current="page">' in page
    for path in PAGES:
        if path.name != "bluebook.html":
            assert 'href="bluebook.html" aria-current' not in path.read_text(encoding="utf-8"), path.name


def _bluebook_page() -> str:
    return (SUITE / "bluebook.html").read_text(encoding="utf-8")


def test_bluebook_page_never_names_bluebooks_integrity_readings():
    # Bluebook's AI-likelihood number, stylometric number and FLAGGED status stay in
    # Bluebook. The page counts sealed booklets through Live.sealed()'s allowlist only.
    page = _bluebook_page()
    for word in ("ai_score", "aiscore", "stylometric", "flagged", "authenticity", "worth a look"):
        assert word not in page.lower(), f"bluebook.html mentions {word}"
    assert "Live.sealed()" in page


def test_bluebook_page_makes_no_claim_the_code_does_not_support():
    page = _bluebook_page()
    for gone in ("authenticated baseline", "typing rhythm", "keystroke", "banked", "fingerprint", "gold standard", "vouch", "join at"):
        assert gone not in page.lower(), f"bluebook.html says {gone!r}"
    # A booklet joins a baseline only by the teacher's approval, and Original's
    # comparison depends on Original being on.
    assert "only when you <b>approve</b> it, and you can undo that choice." in page
    assert "only when Original is on for your workspace" in page


# SessionSetup's submit (demo/bluebook/TeacherWorkspace.jsx): the one request that
# opens a session in Bluebook. The suite page sends the same one.
SESSION_SETUP_CREATE = (
    "onCreate({title:`${selected.code||selected.name||'Class'} · ${new Date().toLocaleDateString()}`,"
    "course:selected.code||selected.name,course_id:selected.id,duration,questions:list,"
    "status:'ACTIVE',minWords:0,maxWords:0,conditions:{}})"
)


def test_bluebook_page_opens_a_session_with_the_request_bluebooks_own_setup_sends():
    workspace = (DEMO / "bluebook" / "TeacherWorkspace.jsx").read_text(encoding="utf-8")
    assert SESSION_SETUP_CREATE in workspace, "SessionSetup's create request changed: change bluebook.html to match"
    assert "BB_API.createExam(payload)" in workspace
    script = _inline_scripts(SUITE / "bluebook.html")
    assert "Live.api('/bluebook/exams',{method:'POST',body:sessionPayload(" in script
    assert _extract(script, "sessionPayload") == (
        "  function sessionPayload(course,questions,duration,today){\n"
        "    return {title:(course.code||course.name||'Class')+' · '+today,course:course.code||course.name,"
        "course_id:course.id,duration:duration,questions:questions,status:'ACTIVE',minWords:0,maxWords:0,conditions:{}};\n"
        "  }"
    )


def test_bluebook_page_links_into_the_app_by_its_deep_links():
    page = _bluebook_page()
    assert "'<a class=\"sess\" href=\"/bluebook/#exam/'+encodeURIComponent(e.id)+'\"" in page
    assert "/bluebook/#live/'+id+'\">Open the live room</a>" in page
    assert "/bluebook/#exam/'+id+'\">Manage it in Collections</a>" in page
    deep = (DEMO / "bluebook" / "deep-link.jsx").read_text(encoding="utf-8")
    assert "const DEEP_LINK = /^#(exam|live)\\/([A-Za-z0-9_-]{1,64})$/;" in deep
    assert "DEEP_LINK_SCREEN = { exam: 'manage-exam', live: 'proctor' }" in deep


BLUEBOOK_TAIL = r"""
const page = fs.readFileSync(sc.page, 'utf8');
const scripts = Array.from(page.matchAll(/<script>([\s\S]*?)<\/script>/g)).map((m) => m[1]);
if (scripts.length !== 1) throw new Error('expected one inline script, found ' + scripts.length);
// The create call is answered here; everything else goes through the stubbed fetch.
const posts = [];
const realApi = window.Live.api;
window.Live.api = (p, o) => {
  if (o && o.method === 'POST') {
    posts.push({ path: p, body: o.body });
    return Promise.resolve(sc.created || { ok: false, status: 500, data: null });
  }
  return realApi(p, o);
};
new Function('window', 'document', 'Live', "'use strict';\n" + scripts[0])(window, document, window.Live);
const el = (id) => document.getElementById(id);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const fire = (id, type, ev) => (el(id).handlers[type] || []).forEach((fn) => fn(ev));
const snap = () => ({
  off: el('setup-live').hidden === true && el('setup-off').hidden === false,
  courses: el('course-row').innerHTML,
  sum: el('launch-sum').textContent,
  launchDisabled: el('launch').disabled,
  sessions: el('sessions').innerHTML,
  count: el('rev-count').textContent,
  more: el('more').hidden ? '' : el('more').textContent,
  note: el('rev-note').hidden ? '' : el('rev-note').textContent,
  err: el('launch-err').hidden ? '' : el('launch-err').textContent,
  chip: el('cc-text').innerHTML,
  gate: document.querySelector('main').innerHTML,
});
const settled = () => {
  const s = el('sessions').innerHTML;
  return (s && !/>Loading</.test(s)) || document.querySelector('main').innerHTML;
};
(async () => {
  for (let i = 0; i < 500 && !settled(); i++) await sleep(10);
  await sleep(60);
  const out = { before: snap() };
  if (sc.form) {
    if (sc.form.course) fire('course-row', 'click', { target: { closest: () => ({ getAttribute: () => sc.form.course }) } });
    sc.form.questions.forEach((q, i) => {
      if (i > 0) fire('add-q', 'click', {});
      fire('prompts', 'input', { target: { getAttribute: () => String(i), value: q } });
    });
    if (sc.form.duration) fire('time-slider', 'input', { target: { value: String(sc.form.duration) } });
    fire('setup', 'submit', { preventDefault() {} });
    await sleep(60);
    out.after = snap();
  }
  out.today = new Date().toLocaleDateString();
  process.stdout.write(JSON.stringify(Object.assign(out, { posts, calls, max })));
})();
"""


def _bluebook_run(**scenario) -> dict:
    run = subprocess.run(
        [shutil.which("node"), "-e", PRELUDE + BLUEBOOK_TAIL],
        input=json.dumps({"live": str(SUITE / "live.js"), "page": str(SUITE / "bluebook.html"), **scenario}),
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert run.returncode == 0, run.stderr
    assert run.stdout, "the page never finished loading"
    return json.loads(run.stdout)


def _bb_course(cid: str, code: str, name: str, students: int) -> dict:
    return {"id": cid, "code": code, "name": name, "term": "Fall", "status": "ACTIVE", "students": students, "exams": 0}


def _bb_exam(eid: str, title: str, created: str, **extra) -> dict:
    return {
        "id": eid, "title": title, "course": "THEO 301", "course_id": "c1", "created_at": created,
        "duration": 50, "status": "ACTIVE", **extra,
    }


def _bb_sealed(sid: str, exam_id: str, graded: bool = False) -> dict:
    return {
        "id": sid, "exam_id": exam_id, "student_id": "t:s-" + sid, "candidate": "A Student", "exam": "", "course": "",
        "created_at": "2026-10-01T10:00:00+00:00", "late": 0, "mark": "B" if graded else "",
        "graded_at": "2026-10-02T10:00:00+00:00" if graded else None,
    }


BB_COURSES = [
    _bb_course("c1", "THEO 301", "Theology of the Reformation", 34),
    _bb_course("c2", "HIST 210", "Early Modern Europe", 1),
]
BB_EXAMS = [
    _bb_exam("e-old", "Reformation causes", "2026-09-01T10:00:00+00:00", status="CLOSED"),
    _bb_exam("e-new", "Midterm", "2026-10-05T10:00:00+00:00"),
    _bb_exam("e-mid", "In-class essay", "2026-09-20T10:00:00+00:00", status="CLOSED"),
]


def _bb_scenario(**extra) -> dict:
    base = dict(
        local=TEACHER,
        me=_teacher_me(),
        routes={
            "/bluebook/courses": [200, {"courses": BB_COURSES}],
            "/bluebook/exams/e-mid/baseline": [200, {"submissions": [
                {"submission_id": "s2", "student": "x", "in_baseline": True, "has_text": True},
                {"submission_id": "s3", "student": "y", "in_baseline": False, "has_text": True},
            ]}],
        },
        bbExams=[200, {"exams": BB_EXAMS}],
        bbSubmissions=[200, {"submissions": [
            _bb_sealed("s1", "e-new"), _bb_sealed("s2", "e-mid", graded=True), _bb_sealed("s3", "e-mid", graded=True),
        ]}],
    )
    for k, v in extra.items():
        base[k] = {**base["routes"], **v} if k == "routes" else v
    return base


@needs_node
def test_bluebook_page_lists_past_sessions_newest_first_with_counts_from_the_sealed_loader():
    out = _bluebook_run(**_bb_scenario())
    s = out["before"]
    assert re.findall(r'<div class="s-t">([^<]*)</div>', s["sessions"]) == ["Midterm", "In-class essay", "Reformation causes"]
    hrefs = re.findall(r'<a class="sess" href="([^"]*)"', s["sessions"])
    assert hrefs == ["/bluebook/#exam/e-new", "/bluebook/#exam/e-mid", "/bluebook/#exam/e-old"]
    assert s["count"] == "3 sessions · newest first"
    # e-new is open with one ungraded booklet; e-mid has two, both graded, one in a baseline.
    assert "Open now" in s["sessions"] and "1 sealed · 1 to review" in s["sessions"]
    assert "All reviewed" in s["sessions"] and "2 sealed · 1 in a baseline" in s["sessions"]
    assert "0 sealed" in s["sessions"] and "Closed" in s["sessions"]
    # Baselines are asked only for a row with a sealed booklet; only live.js reads the list route.
    asked = sorted(c for c in out["calls"] if c.endswith("/baseline"))
    assert asked == ["/bluebook/exams/e-mid/baseline", "/bluebook/exams/e-new/baseline"]
    assert out["calls"].count("/bluebook/submissions") == 1
    # The class pills carry the real code, name and count; the first is chosen.
    assert 'aria-pressed="true" data-course="c1">THEO 301 · Theology of the Reformation · 34 students</button>' in s["courses"]
    assert "HIST 210 · Early Modern Europe · 1 student</button>" in s["courses"]
    assert s["sum"] == "THEO 301 · 1 question · 50 minutes" and s["launchDisabled"] is False


@needs_node
def test_bluebook_page_asks_about_baselines_for_the_visible_rows_only_six_at_a_time():
    exams = [_bb_exam(f"e{i:02d}", f"Session {i}", f"2026-10-{i + 1:02d}T10:00:00+00:00") for i in range(10)]
    sealed = [_bb_sealed(f"s{i}", f"e{i:02d}") for i in range(10)]
    out = _bluebook_run(**_bb_scenario(bbExams=[200, {"exams": exams}], bbSubmissions=[200, {"submissions": sealed}]))
    asked = sorted(c for c in out["calls"] if c.endswith("/baseline"))
    assert asked == [f"/bluebook/exams/e{i:02d}/baseline" for i in range(4, 10)]
    assert out["max"] <= 6
    assert out["before"]["more"] == "Show all 10 sessions"


@needs_node
def test_bluebook_page_opens_a_session_and_says_how_students_reach_it():
    created = {"ok": True, "status": 201, "data": {
        "id": "e-made", "title": "x", "course": "HIST 210", "course_id": "c2", "status": "ACTIVE",
        "duration": 75, "opens_at": None, "closes_at": None, "submissions": 0,
    }}
    form = {"course": "c2", "questions": ["  First question. ", "Second question."], "duration": 75}
    out = _bluebook_run(**_bb_scenario(created=created), form=form)
    assert out["posts"] == [{"path": "/bluebook/exams", "body": {
        "title": "HIST 210 · " + out["today"], "course": "HIST 210", "course_id": "c2", "duration": 75,
        "questions": ["First question.", "Second question."], "status": "ACTIVE", "minWords": 0, "maxWords": 0,
        "conditions": {},
    }}]
    after = out["after"]
    assert after["err"] == ""
    assert "Session is open." in after["chip"] and "<b>HIST 210</b> roster" in after["chip"]
    assert "<b>My exams</b>" in after["chip"]
    assert '<a href="/bluebook/#live/e-made">Open the live room</a>' in after["chip"]
    assert '<a href="/bluebook/#exam/e-made">Manage it in Collections</a>' in after["chip"]
    assert re.findall(r'<a class="sess" href="([^"]*)"', after["sessions"])[0] == "/bluebook/#exam/e-made"
    assert after["sum"] == "HIST 210 · 1 question · 75 minutes"  # the questions are cleared for the next session


@needs_node
@pytest.mark.parametrize(
    "reply,said",
    [
        (
            {"ok": False, "status": 403, "data": {"detail": "Free workspaces can hold 50 exams. <b>Delete</b> one."}},
            "Free workspaces can hold 50 exams. <b>Delete</b> one.",
        ),
        (
            {"ok": False, "status": 422, "data": {"detail": [{"msg": "field required"}]}},
            "The session could not be saved. Your questions are still here.",
        ),
        ({"ok": False, "status": 0, "data": None}, "Could not reach the server. Your questions are still here."),
        ({"ok": True, "status": 201, "data": {"detail": "no id"}}, "The session could not be saved. Your questions are still here."),
    ],
    ids=["server-sentence", "validation-list", "no-network", "no-id"],
)
def test_bluebook_page_shows_the_servers_refusal_as_text(reply, said):
    out = _bluebook_run(**_bb_scenario(created=reply), form={"questions": ["A question."]})
    # Set as textContent, so markup in the server's words is shown, never run.
    assert out["after"]["err"] == said
    assert "Session is open." not in out["after"]["chip"]


@needs_node
def test_bluebook_page_does_not_send_a_blank_question():
    out = _bluebook_run(**_bb_scenario(), form={"questions": ["One.", "   "]})
    assert out["posts"] == []
    assert out["after"]["err"] == "Choose a class and write each question before opening the booklets."


@needs_node
@pytest.mark.parametrize(
    "scenario",
    [
        dict(me=_teacher_me(("original",))),
        dict(routes={"/bluebook/courses": [403, {"detail": "This workspace's plan does not include Bluebook."}]}),
    ],
    ids=["no-bluebook-product", "403"],
)
def test_bluebook_page_says_bluebook_is_off_instead_of_breaking(scenario):
    out = _bluebook_run(**_bb_scenario(**scenario))
    assert out["before"]["off"] is True
    assert "Collections is off for this workspace." in out["before"]["sessions"]
    if "me" in scenario:
        assert not [c for c in out["calls"] if c.startswith("/bluebook/")]


@needs_node
def test_bluebook_page_sends_a_teacher_with_no_course_to_bluebook_first():
    out = _bluebook_run(**_bb_scenario(
        routes={"/bluebook/courses": [200, {"courses": []}]},
        bbExams=[200, {"exams": []}],
        bbSubmissions=[200, {"submissions": []}],
    ))
    s = out["before"]
    assert '<a href="/bluebook/#courses">Add a course in Collections first</a>' in s["courses"]
    assert s["launchDisabled"] is True and s["sum"] == "Choose a class · 1 question · 50 minutes"
    assert "No sessions yet. Your first one will appear here." in s["sessions"]


@needs_node
@pytest.mark.parametrize(
    "scenario,where,said",
    [
        (dict(routes={"/bluebook/courses": [500, {"detail": "boom"}]}), "courses", "Your classes could not be loaded just now."),
        (dict(bbExams=[200, {"exams": "nope"}]), "sessions", "Your sessions could not be loaded just now."),
        (dict(rejectOn=["^/bluebook/submissions$"]), "note", "Sealed booklets could not be counted just now."),
    ],
    ids=["courses-500", "exams-not-a-list", "sealed-down"],
)
def test_bluebook_page_says_what_could_not_be_loaded(scenario, where, said):
    out = _bluebook_run(**_bb_scenario(**scenario))
    assert said in out["before"][where]
    if where == "courses":
        assert out["before"]["launchDisabled"] is True


@needs_node
def test_bluebook_page_gates_like_the_other_teacher_pages():
    out = _bluebook_run(local={}, health=[200, {"environment": "pilot"}])
    assert "Sign in to continue" in out["before"]["gate"]
    assert not [c for c in out["calls"] if c.startswith("/bluebook/")]
