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
    "submissions.html",
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
        "/original/live.js",
        "/original/suite.css",
        "/original/fonts.css",
        "/original/js/fingerprint.js",
        "/original/js/feature-data.js",
        "/original/assets/radcliffe-night-stars.jpeg",
        "/original/assets/st-andrews-quad.jpg",
        "/original/assets/radcliffe-observatory-watercolour.jpg",
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


needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")

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


# ── Live.roster, run for real under node ──────────────────────────────────────
# live.js is plain browser script with no module system, so these run it in a
# bare `node` with a stubbed window, document and fetch. They need only node
# 18+ (global fetch types are not used; URL and Headers are).

HARNESS = r"""
const fs = require('fs');
const sc = JSON.parse(fs.readFileSync(0, 'utf8'));
const src = fs.readFileSync(sc.live, 'utf8');
const window = {
  location: { href: 'http://suite.test/original/students.html', origin: 'http://suite.test', replace() {} },
  localStorage: { getItem() { return null; }, removeItem() {} },
};
const document = { readyState: 'complete', querySelectorAll() { return []; }, addEventListener() {} };
let active = 0, max = 0;
const calls = [];
function route(path) {
  let m;
  if (path === '/health') return [200, { environment: 'demo' }];
  if (path === '/students') return sc.students;
  if ((m = path.match(/^\/students\/(.+)\/readiness$/))) {
    return (sc.readiness || {})[decodeURIComponent(m[1])] || sc.readinessDefault || [404, { detail: 'x' }];
  }
  if (path === '/bluebook/students') return sc.bbStudents || [200, { students: [] }];
  if (path === '/bluebook/submissions') return sc.bbSubmissions || [200, { submissions: [] }];
  return [404, {}];
}
function fakeFetch(href) {
  const path = new URL(href).pathname;
  calls.push(path);
  active++;
  max = Math.max(max, active);
  const [status, body] = route(path);
  return new Promise((resolve) => setTimeout(() => {
    active--;
    resolve({ ok: status >= 200 && status < 300, status, text: () => Promise.resolve(JSON.stringify(body)) });
  }, 5));
}
new Function('window', 'document', 'fetch', src)(window, document, fakeFetch);
window.Live.roster().then((result) => process.stdout.write(JSON.stringify({ result, max, calls })));
"""


def _roster(**scenario) -> dict:
    run = subprocess.run(
        [shutil.which("node"), "-e", HARNESS],
        input=json.dumps({"live": str(SUITE / "live.js"), **scenario}),
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert run.returncode == 0, run.stderr
    return json.loads(run.stdout)


def _ready(verdict: str, auth: int = 5, samples: int = 5) -> list:
    return [200, {"verdict": verdict, "authenticated_count": auth, "sample_count": samples}]


@needs_node
def test_roster_asks_readiness_of_the_first_60_and_never_more_than_6_at_a_time():
    ids = [f"s{i:02d}" for i in range(70)]
    out = _roster(students=[200, {"students": ids, "roster": None}], readinessDefault=_ready("ready"))
    readiness = [c for c in out["calls"] if c.endswith("/readiness")]
    assert len(readiness) == 60
    assert out["max"] <= 6
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
