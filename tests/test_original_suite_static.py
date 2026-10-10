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

# Filenames from the plan's page map that later tasks still have to build. The
# nav of an earlier page links to them at their final name, so a link to one of
# these is allowed while the file is missing. test_planned_pages_are_still_missing
# makes the list shrink: delete a name here in the commit that adds its page.
PLANNED_PAGES = {
    "packet.html",
    "baseline.html",
    "voice.html",
    "my-work.html",
}

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
    text = _squash(path.read_text(encoding="utf-8"))
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
        "/original/writing-state.html",
        "/original/settings.html",
        "/original/submissions.html",
        "/original/reports.html",
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
    for endpoint in ("/readiness", "/bluebook/students", "/bluebook/submissions"):
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


def test_reports_page_counts_only_what_live_roster_returns():
    page = (SUITE / "reports.html").read_text(encoding="utf-8")
    assert "Live.roster()" in page
    assert "Live.sealed()" in page
    # The loader is shared, and this page reads no other endpoint: its numbers are
    # counts of the roster, the server's verdicts and the sealed exams' dates.
    assert "Live.api(" not in page
    for endpoint in ("/readiness", "/bluebook/students", "/bluebook/submissions", "/score"):
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


@pytest.mark.parametrize("path", PAGES, ids=lambda p: p.name)
def test_account_menu_offers_the_classic_analysis_page_after_settings(path):
    links = _account_menu(path)
    assert links, f"{path.name} has no account menu"
    texts = [text for _, text in links]
    assert texts.count("Analysis (classic)") == 1, f"{path.name}: {texts}"
    classic = texts.index("Analysis (classic)")
    assert links[classic][0] == "/professor.html"
    assert classic > 0 and texts[classic - 1] == "Settings", f"{path.name}: {texts}"


def _sign_in_redirect() -> str:
    html = (DEMO / "index.html").read_text(encoding="utf-8")
    found = re.findall(r"window\.location\.href\s*=\s*([^;]+);", html)
    assert len(found) == 1, "index.html must have exactly one post-sign-in redirect"
    return " ".join(found[0].split())


def test_sign_in_sends_a_teacher_to_the_new_original_pages():
    # Roles other than operator and admin (a teacher is role "professor") end up
    # at the last alternative, which is the suite's front page, not professor.html.
    assert _sign_in_redirect() == (
        "role === 'operator' ? 'operator.html' : role === 'admin' ? 'admin.html' : 'original/'"
    )
    # ...and the redirect has to resolve to a real page under demo/.
    assert (DEMO / "original" / "index.html").is_file()


@needs_node
@pytest.mark.parametrize(
    "role,target",
    [
        ("professor", "original/"),
        ("admin", "admin.html"),
        ("operator", "operator.html"),
    ],
)
def test_sign_in_redirect_evaluates_to_the_right_page(role, target):
    run = subprocess.run(
        [shutil.which("node"), "-e", "process.stdout.write(String(new Function('role', 'return ' + process.argv[1])(process.argv[2])))", _sign_in_redirect(), role],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert run.returncode == 0, run.stderr
    assert run.stdout == target


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
function route(path) {
  let m;
  if (path === '/health') return [200, { environment: 'demo' }];
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
function fakeFetch(href) {
  const path = new URL(href).pathname;
  calls.push(path);
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
(async () => {
  const out = {};
  if (sc.call === 'signOut') {
    window.Live.signOut();
    if (!sc.blockStorage) {
      out.local = window.localStorage.keys();
      out.session = window.sessionStorage.keys();
    }
  } else if (sc.call === 'sealed') {
    out.result = plain(await window.Live.sealed());
  } else if (sc.call === 'both') {
    const [roster, sealed, again] = await Promise.all([window.Live.roster(), window.Live.sealed(), window.Live.sealed()]);
    out.result = roster;
    out.sealed = plain(sealed);
    out.sameObject = sealed === again;
  } else {
    out.result = await window.Live.roster();
  }
  process.stdout.write(JSON.stringify(Object.assign(out, { max, calls, replaced })));
})();
"""

PAGE_TAIL = r"""
const page = fs.readFileSync(sc.page, 'utf8');
const scripts = Array.from(page.matchAll(/<script>([\s\S]*?)<\/script>/g)).map((m) => m[1]);
if (scripts.length !== 1) throw new Error('expected one inline script, found ' + scripts.length);
window.matchMedia = () => ({ matches: true });  // no animation timers
new Function('window', 'document', 'Live', scripts[0])(window, document, window.Live);
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
    assert res["students"][0]["approved"] == 5 and res["students"][0]["samples"] == 5
    assert res["students"][65]["approved"] is None


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
    assert (ada["approved"], ada["samples"]) == (6, 7)
    assert (ada["sealed"], ada["pending"]) == (2, 1)
    assert ada["lastSealed"] == "2026-10-01T10:00:00Z"
    assert by_id["__proto__"]["email"] is None and by_id["__proto__"]["sealed"] == 0
    assert by_id["__proto__"]["lastSealed"] is None
    assert by_id["ten:a"]["approved"] is None  # the roster had no count, and its readiness call failed
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


# ── Live.sealed ───────────────────────────────────────────────────────────────

SEALED_RESULT_KEYS = set(SEALED_FIELDS) | {"course_id"}


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
                    None,
                    "junk",
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
    blob = json.dumps(res)
    for value in ("FLAGGED", "0.91", "see me", "the whole paper", "teacher-1", "pasted", "secret"):
        assert value not in blob, value
    assert res["names"] == [["s1", "Ada Lovelace"]]
    # An exam keeps only its title, course and course id.
    assert res["exams"] == [["e1", {"title": "Midterm", "course": "THEO 301", "course_id": "c1"}]]


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
