"""Fixes from the 2026-10-11 button audit of the live Original suite.

Each section pins one fix: what the page now does, so a later edit cannot quietly
put the broken behaviour back. The audit's report is
.superpowers/sdd/button-audit-report.md.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from html.parser import HTMLParser

from tests.test_original_suite_static import (  # noqa: F401
    BASELINE_HARNESS,
    DEMO,
    PRELUDE,
    ROOT,
    SUITE,
    TEACHER,
    _bb_scenario,
    _bb_sealed,
    _extract,
    _inline_scripts,
    _settings_run,
    _teacher_me,
    needs_node,
)


# ── Writing State comes back to the last analysis ─────────────────────────────

RESTORE_RUN = r"""
const fs = require('fs');
const sc = JSON.parse(fs.readFileSync(0, 'utf8'));
const out = sc.cases.map((c) => {
  const api = new Function('num', sc.src + '\nreturn {lastRecord, keptEntry};')((v) => (typeof v === 'number' && isFinite(v)) ? v : null);
  const rec = api.lastRecord(c.raw, c.id);
  return { rec: rec ? { student_id: rec.student_id } : null, entry: rec ? (api.keptEntry(c.entries || [], rec) || {}).id || null : null };
});
process.stdout.write(JSON.stringify(out));
"""


def _restore(cases: list[dict]) -> list[dict]:
    script = _inline_scripts(SUITE / "writing-state.html")
    src = "\n".join(_extract(script, name) for name in ("lastRecord", "keptEntry"))
    run = subprocess.run(
        [shutil.which("node"), "-e", RESTORE_RUN],
        input=json.dumps({"src": src, "cases": cases}),
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert run.returncode == 0, run.stderr
    return json.loads(run.stdout)


def _kept(student="s1", **over) -> str:
    rec = {
        "kind": "original_writing_state", "version": 1, "student_id": student, "assignment": "Essay",
        "word_count": 120, "analysed_at": "2026-10-11T12:00:00Z", "entry_id": "e1",
        "result": {"submission_id": "sub-9", "feature_vector": {}, "baseline_vector": {}},
    }
    rec.update(over)
    return json.dumps(rec)


@needs_node
def test_writing_state_restores_the_last_analysis_only_for_the_student_in_the_address():
    mine, other, junk, wrong_kind, wrong_version, no_vectors, not_object = _restore(
        [
            {"raw": _kept("s1"), "id": "s1"},
            {"raw": _kept("s1"), "id": "s2"},  # never across students
            {"raw": "{not json", "id": "s1"},
            {"raw": _kept("s1", kind="something_else"), "id": "s1"},
            {"raw": _kept("s1", version=2), "id": "s1"},
            {"raw": _kept("s1", result={"feature_vector": {}}), "id": "s1"},  # a result with no baseline side
            {"raw": json.dumps(["s1"]), "id": "s1"},
        ]
    )
    assert mine["rec"] == {"student_id": "s1"}
    for refused in (other, junk, wrong_kind, wrong_version, no_vectors, not_object):
        assert refused["rec"] is None
    # No record at all, and no student in the address, restore nothing.
    none, no_id = _restore([{"raw": None, "id": "s1"}, {"raw": _kept("s1"), "id": ""}])
    assert none["rec"] is None and no_id["rec"] is None


@needs_node
def test_writing_state_finds_the_kept_paper_the_record_points_at():
    entries = [{"id": "e1", "text": "one"}, None, "junk", {"id": "sub-9", "text": "nine"}]
    by_entry, by_submission, missing = _restore(
        [
            {"raw": _kept("s1"), "id": "s1", "entries": entries},
            {"raw": _kept("s1", entry_id=""), "id": "s1", "entries": entries},  # falls back to the submission id
            {"raw": _kept("s1", entry_id="gone"), "id": "s1", "entries": entries},
        ]
    )
    assert by_entry["entry"] == "e1"
    assert by_submission["entry"] == "sub-9"
    assert missing["entry"] is None  # the reading still comes back; only the pasted text and note do not


def test_writing_state_keeps_the_analysis_for_this_tab_as_soon_as_it_exists():
    page = (SUITE / "writing-state.html").read_text(encoding="utf-8")
    script = _inline_scripts(SUITE / "writing-state.html")
    # Written at analysis time (not only when the packet link is pressed), so Back from the
    # Voice baseline link finds it, and it names the kept paper so the note and text come back.
    analyse = script[script.index("async function analyse(") : script.index("function newSubmissionId(")]
    assert "storeForPacket();" in analyse
    assert "entry_id:S.entryId" in script
    # It is restored where the student loads, after the baseline is known, and says so plainly.
    assert "else if(!restoreLast()){ note(thinNote()); setCard('form'); }" in script
    assert "Showing your last analysis of this paper." in page
    assert 'id="an-again"' in page and "Analyse another" in page
    # One key, cleared by sign-out like the packet's reading of it.
    assert "sessionStorage.getItem('original_last_result')" in script


# ── A student can reach My voice and My work ──────────────────────────────────


def test_the_student_navigation_links_to_the_original_student_pages_when_original_is_on():
    account = (DEMO / "bluebook" / "Account.jsx").read_text(encoding="utf-8")
    assert "[['../original/voice.html', 'My voice'], ['../original/my-work.html', 'My work']]" in account
    assert "BB_API.hasOriginal() ? STUDENT_ORIGINAL_LINKS : []" in account
    # The pages exist, and the committed bundle production serves carries the links.
    for page in ("voice.html", "my-work.html"):
        assert (SUITE / page).is_file()
    bundle = (DEMO / "bluebook" / "bluebook.bundle.js").read_text(encoding="utf-8")
    assert "../original/voice.html" in bundle and "../original/my-work.html" in bundle


# ── Voice Baseline: pasting the same paper twice ──────────────────────────────
# POST /students/{id}/baseline skips a text already in the baseline only when the
# request carries a submission_uuid (original/routers/students_baseline.py), so the
# page sends one with every paste: stable for the same student and the same words.

PASTE_ROUTE = "if (method === 'POST' && path === '/students/s1/baseline') { sample += 1; wrote = true; return [200, { sample_index: sample - 1, provenance: 'verified' }]; }"
PASTE_HARNESS_TAIL = r"""
(async () => {
  for (let i = 0; i < 300 && !el('sealed-list').innerHTML.includes('data-act="approve"'); i++) await sleep(10);
  const out = { rounds: [] };
  for (const text of sc.pastes) {
    el('paste-text').value = text;
    click('paste-go');
    await sleep(250);
    out.rounds.push({ lines: addMsg.lines.slice(), box: el('paste-text').value, samples: sample });
  }
  out.bodies = bodies;
  process.stdout.write(JSON.stringify(out));
  process.exit(0);
})();
"""


def _paste_harness() -> str:
    head = BASELINE_HARNESS.split("(async () => {")[0]
    # Record every JSON body, and answer a paste the way the server does: a request with a
    # submission_uuid whose text is already stored is skipped, one without it is stored again.
    swaps = [
        ("const calls = [];", "const calls = [];\nconst bodies = [];\nconst stored = new Set();\nconst crypto = require('crypto');"),
        ("function route(method, path) {", "function route(method, path, init) {"),
        ("const [status, body] = route(method, path);", "const [status, body] = route(method, path, init);"),
        (
            "calls.push(method + ' ' + path);",
            "calls.push(method + ' ' + path); if (init && typeof init.body === 'string') bodies.push(JSON.parse(init.body));",
        ),
        (
            PASTE_ROUTE,
            "if (method === 'POST' && path === '/students/s1/baseline') {"
            " const sent = JSON.parse(init.body); const h = crypto.createHash('sha256').update(sent.text).digest('hex');"
            " if (sent.submission_uuid && stored.has(h)) return [200, { skipped: true, reason: 'duplicate_text', student_id: 's1', sample_index: sample - 1 }];"
            " stored.add(h); sample += 1; wrote = true; return [200, { sample_index: sample - 1, provenance: 'verified' }]; }",
        ),
    ]
    for old, new in swaps:
        assert old in head, f"the baseline harness changed: {old[:40]}"
        head = head.replace(old, new, 1)
    return head + PASTE_HARNESS_TAIL


def _pastes(*texts: str) -> dict:
    run = subprocess.run(
        [shutil.which("node"), "-e", _paste_harness()],
        input=json.dumps(
            {
                "live": str(SUITE / "live.js"),
                "page": str(SUITE / "baseline.html"),
                "features": str(SUITE / "js" / "feature-data.js"),
                "pastes": list(texts),
            }
        ),
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert run.returncode == 0, run.stderr
    assert run.stdout, "the page never finished loading"
    return json.loads(run.stdout)


PAPER = " ".join(f"word{i}" for i in range(80))


@needs_node
def test_pasting_the_same_paper_twice_adds_it_once_and_says_so_plainly():
    out = _pastes(PAPER, PAPER)
    first, second = out["rounds"]
    assert first["lines"][0].startswith("Added as sample 6.")
    assert second["lines"] == ["That paper is already in the baseline, so nothing was added."]
    assert second["samples"] == first["samples"]  # the count did not rise
    # Both pastes carried the same id: the same student and the same words.
    ids = [b["submission_uuid"] for b in out["bodies"]]
    assert len(ids) == 2 and ids[0] == ids[1] and re.fullmatch(r"[0-9a-f]{64}", ids[0])


@needs_node
def test_a_paper_that_differs_only_in_whitespace_has_the_same_id_and_another_paper_has_another():
    out = _pastes(PAPER, "  " + PAPER.replace(" ", "  \n ") + "\n", PAPER + " more")
    ids = [b["submission_uuid"] for b in out["bodies"]]
    assert ids[0] == ids[1] != ids[2]


def _async_function(script: str, name: str) -> str:
    """``async function name(...) {...}`` of a page's inline script (``_extract`` reads plain ones)."""
    head = re.search(rf"^\s*async function {name}\(", script, re.M)
    assert head, f"no async {name} in the page's script"
    depth = 0
    for i in range(script.index("{", head.end()), len(script)):
        depth += (script[i] == "{") - (script[i] == "}")
        if depth == 0:
            return script[head.start() : i + 1]
    raise AssertionError(f"{name} is not closed")


@needs_node
def test_the_paste_id_depends_on_the_student_and_has_a_fallback_without_web_crypto():
    script = _inline_scripts(SUITE / "baseline.html")
    src = "\n".join([_extract(script, "mixKey"), _async_function(script, "pasteKey")])
    run = subprocess.run(
        [
            shutil.which("node"),
            "-e",
            r"""
const fs = require('fs');
const sc = JSON.parse(fs.readFileSync(0, 'utf8'));
const mk = (window) => new Function('window', sc.src + '\nreturn pasteKey;')(window);
(async () => {
  const subtle = mk({ crypto: require('crypto').webcrypto });
  const plain = mk({});  // a page with no window.crypto: the mixing hash
  const broken = mk({ crypto: { subtle: { digest: () => { throw new Error('insecure context'); } } } });
  const out = {
    a: await subtle('s1', 'A paper'), b: await subtle('s2', 'A paper'), again: await subtle('s1', 'A  paper '),
    pa: await plain('s1', 'A paper'), pb: await plain('s2', 'A paper'), pagain: await plain('s1', 'A  paper '),
    pbroken: await broken('s1', 'A paper'),
    expected: require('crypto').createHash('sha256').update('s1\nA paper').digest('hex'),
  };
  process.stdout.write(JSON.stringify(out));
})();
""",
        ],
        input=json.dumps({"src": src}),
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert run.returncode == 0, run.stderr
    got = json.loads(run.stdout)
    assert got["a"] == got["expected"] and got["a"] == got["again"] and got["a"] != got["b"]
    for key in ("pa", "pb", "pagain", "pbroken"):
        assert re.fullmatch(r"[0-9a-f]{64}", got[key]), key
    assert got["pa"] == got["pagain"] == got["pbroken"] and got["pa"] != got["pb"]


def test_the_batch_upload_needs_no_id_because_the_server_already_skips_a_repeated_file():
    # POST /students/{id}/baseline/upload-batch skips a duplicate on its own ("skipped N duplicates").
    page = (SUITE / "baseline.html").read_text(encoding="utf-8")
    assert "skipped_duplicates" in page and "body.submission_uuid=await pasteKey(ID,text);" in page


# ── The classic page (demo/professor.html) is safe for a real teacher ─────────

CLASSIC = DEMO / "professor.html"


def _classic() -> str:
    return CLASSIC.read_text(encoding="utf-8")


class _DemoOnly(HTMLParser):
    """Every start tag that carries data-demo-only: (tag, href or onclick, has the hidden attribute)."""

    def __init__(self) -> None:
        super().__init__()
        self.found: list[tuple[str, str, bool]] = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if "data-demo-only" in a:
            what = a.get("href") or (a.get("onclick") or "").split("(")[0] or ""
            self.found.append((tag, what, "hidden" in a))


def test_the_classic_page_hides_its_demo_controls_until_health_says_demo():
    page = _classic()
    parser = _DemoOnly()
    parser.feed(page)
    marked = [(tag, what) for tag, what, _ in parser.found]
    # Hidden in the markup, so they are hidden before /health answers and when it fails.
    assert parser.found and all(hidden for _, _, hidden in parser.found)
    # Reset Demo; the Admin link (the topbar's and the sidebar's); Operator; the Research group:
    # its label, Institutions and Validation (both "#"), Lab, Context Audit and Playground.
    assert marked.count(("button", "resetDemoState")) == 1
    assert marked.count(("a", "admin.html")) == 2
    assert marked.count(("a", "#")) == 2
    assert marked.count(("div", "")) == 1
    for href in ("operator.html", "lab.html", "admin-context.html", "playground.html"):
        assert marked.count(("a", href)) == 1, href
    assert len(marked) == 1 + 2 + 2 + 1 + 4
    # The Settings panel (built by script) marks its own Reset and system-link cards the same way.
    assert page.count('<div class="card" data-demo-only hidden') == 2
    assert "Demo data</div>" in page and "System surfaces</div>" in page
    # A class's display cannot override the hidden attribute, and the cards are revealed with the rest.
    assert "[data-demo-only][hidden] { display: none !important; }" in page
    assert "revealDemoOnly(sec);" in page and "loadEnvironmentChrome();" in page


@needs_node
def test_the_classic_page_shows_demo_controls_only_for_a_health_reply_that_says_demo():
    script = _inline_scripts(CLASSIC)
    src = "\n".join([_extract(script, "isDemoEnvironment")])
    cases = [
        {"environment": "demo"}, {"environment": "pilot"}, {"environment": "staging"}, {"environment": "Demo"},
        {"environment": None}, {}, None, "demo", ["demo"], 0,
    ]
    run = subprocess.run(
        [shutil.which("node"), "-e", "const fs=require('fs');const sc=JSON.parse(fs.readFileSync(0,'utf8'));"
         "const f=new Function(sc.src+'\\nreturn isDemoEnvironment;')();process.stdout.write(JSON.stringify(sc.cases.map(f)));"],
        input=json.dumps({"src": src, "cases": cases}),
        capture_output=True, text=True, timeout=60,
    )
    assert run.returncode == 0, run.stderr
    assert json.loads(run.stdout) == [True, False, False, False, False, False, False, False, False, False]
    # Health is asked once, and a failure falls to "not the demo".
    assert ".catch(() => null)" in script[script.index("function loadEnvironmentChrome") :][:300]


def test_the_classic_page_names_no_stand_in_person_and_shows_the_signed_in_name():
    page = _classic()
    assert "Adeyemi" not in page
    assert "localStorage.getItem('original_name')" in page
    assert 'id="hdrProfName"' in page and 'id="sidebarName"' in page
    assert "greetEl.textContent = who;" in page  # no name, no greeting name


def test_the_classic_page_has_a_visible_way_back_to_original_and_signs_out_to_the_sign_in_page():
    page = _classic()
    assert '<a href="/original/" id="backToOriginal"' in page
    assert "← Back to Original</a>" in page
    # The way back is not one of the demo-only controls.
    line = next(l for l in page.splitlines() if 'id="backToOriginal"' in l)
    assert "data-demo-only" not in line
    assert "location.replace('/index.html');" in page
    assert "location.replace('professor.html')" not in page


# ── The Bluebook Sessions page after review (demo/original/bluebook.html) ─────


def _bluebook_page() -> str:
    return (SUITE / "bluebook.html").read_text(encoding="utf-8")


def test_bluebook_page_carries_no_testing_label_because_it_shows_no_original_result():
    # The label belongs on a view that shows an Original score, action or deviation; this page
    # shows none (a booklet joins a baseline only when the teacher approves it).
    assert "data-testing-notice" not in _bluebook_page()


def test_bluebook_page_words_the_baseline_count_as_a_match_by_text_never_banked_or_approved():
    page = _bluebook_page()
    assert "' in a baseline'" in page and "in baselines" not in page
    assert "Matched by text against each student\\u2019s baseline samples. Approve or undo in Bluebook." in page
    for gone in ("banked", "approved"):
        label = page[page.index("function rightHTML") : page.index("function rowHTML")]
        assert gone not in label.lower().replace("approve or undo", ""), gone


# A page script run under node with the sessions list modelled well enough to patch one row:
# the rows come back out of what was written, and a row's right-hand side can be rewritten.
PATCH_TAIL = r"""
const page = fs.readFileSync(sc.page, 'utf8');
const scripts = Array.from(page.matchAll(/<script>([\s\S]*?)<\/script>/g)).map((m) => m[1]);
if (scripts.length !== 1) throw new Error('expected one inline script, found ' + scripts.length);
const el = (id) => document.getElementById(id);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const sess = el('sessions');
let writes = 0, html = '';
Object.defineProperty(sess, 'innerHTML', { get() { return html; }, set(v) { writes++; html = v; } });
const tail = '<div class="s-right">';
sess.querySelectorAll = (sel) => {
  if (sel !== 'a.sess') return [];
  return Array.from(html.matchAll(/<a class="sess"[^>]*data-exam="([^"]*)"/g)).map((m) => ({
    getAttribute: (k) => (k === 'data-exam' ? m[1] : null),
    querySelector: (q) => (q !== '.s-right' ? null : {
      set innerHTML(v) {
        const re = new RegExp('(<a class="sess"[^>]*data-exam="' + m[1] + '"[\\s\\S]*?' + tail + ')([\\s\\S]*?)(</div></a>)');
        html = html.replace(re, (all, a, b, c) => a + v + c);
      },
    }),
  }));
};
// What the HTML says before the script runs: the demo note starts hidden.
el('demo-note').hidden = true;
new Function('window', 'document', 'Live', "'use strict';\n" + scripts[0])(window, document, window.Live);
(async () => {
  for (let i = 0; i < 500 && !/class="sess"/.test(html); i++) await sleep(10);
  const first = writes;
  await sleep(300);
  process.stdout.write(JSON.stringify({ html, writesAtRows: first, writesAfter: writes, demoHidden: el('demo-note').hidden, calls }));
})();
"""


def _patch_run(**scenario) -> dict:
    run = subprocess.run(
        [shutil.which("node"), "-e", PRELUDE + PATCH_TAIL],
        input=json.dumps({"live": str(SUITE / "live.js"), "page": str(SUITE / "bluebook.html"), **scenario}),
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert run.returncode == 0, run.stderr
    assert run.stdout, "the page never finished loading"
    return json.loads(run.stdout)


@needs_node
def test_bluebook_page_patches_one_row_when_a_baseline_answer_comes_instead_of_redrawing_the_list():
    out = _patch_run(**_bb_scenario())
    # The baseline answer arrived (e-mid has one booklet in a baseline) ...
    assert "2 sealed · 1 in a baseline" in out["html"]
    assert "Matched by text against each student\u2019s baseline samples. Approve or undo in Bluebook." in out["html"]
    assert [c for c in out["calls"] if c.endswith("/baseline")]
    # ... and drew nothing but that row: the list was written once, so a focused row keeps its focus.
    assert out["writesAfter"] == out["writesAtRows"]
    # The rows that had no answer show no baseline count and no title.
    assert out["html"].count("in a baseline") == 1 and out["html"].count("Matched by text") == 1


@needs_node
def test_bluebook_page_says_in_the_open_demo_that_sessions_open_for_a_signed_in_teacher_only():
    demo = _patch_run(**_bb_scenario(local={}, me=None, health=[200, {"environment": "demo"}], routes={
        "/bluebook/courses": [200, {"courses": []}],
    }))
    assert demo["demoHidden"] is False
    teacher = _patch_run(**_bb_scenario())
    assert teacher["demoHidden"] is True
    page = _bluebook_page()
    assert '<p class="rev-note" id="demo-note" hidden>Sign in to open sessions in Bluebook.</p>' in page
    assert "if(sess.mode==='demo') $('demo-note').hidden=false;" in page


# ── Every suite link opens the right Bluebook screen ──────────────────────────
# /bluebook/#exam/<id>, #live/<id>, #students and #courses (demo/bluebook/deep-link.jsx).

SUBMISSIONS_TAIL = r"""
const page = fs.readFileSync(sc.page, 'utf8');
const scripts = Array.from(page.matchAll(/<script>([\s\S]*?)<\/script>/g)).map((m) => m[1]);
if (scripts.length !== 1) throw new Error('expected one inline script, found ' + scripts.length);
new Function('window', 'document', 'Live', "'use strict';\n" + scripts[0])(window, document, window.Live);
const el = (id) => document.getElementById(id);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
(async () => {
  for (let i = 0; i < 500 && !el('rows').innerHTML; i++) await sleep(10);
  process.stdout.write(JSON.stringify({ rows: el('rows').innerHTML, foot: el('foot').textContent }));
})();
"""


def _submissions_run(**scenario) -> dict:
    run = subprocess.run(
        [shutil.which("node"), "-e", PRELUDE + SUBMISSIONS_TAIL],
        input=json.dumps({"live": str(SUITE / "live.js"), "page": str(SUITE / "submissions.html"), **scenario}),
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert run.returncode == 0, run.stderr
    assert run.stdout, "the page never finished loading"
    return json.loads(run.stdout)


@needs_node
def test_a_submissions_row_opens_its_own_exam_in_bluebook():
    sealed = [_bb_sealed("s1", "e-new"), _bb_sealed("s2", "e/odd id", graded=True), _bb_sealed("s3", "")]
    out = _submissions_run(
        local=TEACHER, me=_teacher_me(), students=[200, {"students": [], "roster": []}],
        bbSubmissions=[200, {"submissions": sealed}], bbExams=[200, {"exams": []}],
    )
    rows = out["rows"]
    assert 'href="/bluebook/#exam/e-new" title="Opens this exam in Bluebook"' in rows
    assert 'href="/bluebook/#exam/e%2Fodd%20id" title="Opens this exam in Bluebook"' in rows  # an id is encoded, never spliced in
    assert 'href="/bluebook/" title="Opens this exam in Bluebook"' in rows  # a booklet with no exam id opens Bluebook itself
    assert 'title="Opens Bluebook"' not in rows


def test_the_submissions_page_no_longer_says_bluebook_has_no_address_for_an_exam():
    page = (SUITE / "submissions.html").read_text(encoding="utf-8")
    assert "no address" not in page and "Read &amp; mark" not in page
    assert "Each row opens that exam in Bluebook." in page


def test_add_student_and_the_empty_roster_line_open_the_students_screen_and_courses_open_courses():
    students = (SUITE / "students.html").read_text(encoding="utf-8")
    assert '<a class="add-btn" id="add-btn" href="/bluebook/#students"' in students
    assert 'Add them in <a href="/bluebook/#students">Bluebook</a>.' in (SUITE / "writing-state.html").read_text(encoding="utf-8")
    assert '<a href="/bluebook/#courses">Add a course in Bluebook first</a>' in _bluebook_page()


@needs_node
def test_settings_links_its_courses_to_bluebooks_courses_screen():
    course = {"code": "THEO 301", "name": "Theology", "students": 4, "exams": 1, "active": True}
    one = _settings_run(local=TEACHER, me=_teacher_me(), routes={"/bluebook/courses": [200, {"courses": [course]}]})
    assert '<div class="c-more"><a href="/bluebook/#courses">Manage your courses in Bluebook</a></div>' in one["courses"]
    none = _settings_run(local=TEACHER, me=_teacher_me(), routes={"/bluebook/courses": [200, {"courses": []}]})
    assert 'No courses yet. <a href="/bluebook/#courses">Add one in Bluebook</a>.' in none["courses"]
    # A workspace without Bluebook has no courses screen to send anyone to.
    off = _settings_run(local=TEACHER, me=_teacher_me(("original",)))
    assert "/bluebook/" not in off["courses"]


# The student's own page: "Add more samples" goes to the exam a booklet is waiting in, else the Students screen.
BB_CTA_TAIL = r"""
(async () => {
  for (let i = 0; i < 300 && !el('sealed-list').innerHTML.includes('data-act="approve"') && !/No sealed exams for this student/.test(el('sealed-list').innerHTML); i++) await sleep(10);
  process.stdout.write(JSON.stringify({ href: el('bb-cta').href, hidden: el('bb-cta').hidden, sealed: el('sealed-list').innerHTML }));
  process.exit(0);
})();
"""


def _cta_run(**scenario) -> dict:
    head = BASELINE_HARNESS.split("(async () => {")[0]
    anchor = "if (path === '/bluebook/submissions') return"
    assert anchor in head, "the baseline harness changed"
    head = head.replace(anchor, "if (path === '/bluebook/submissions' && sc.noSealed) return [200, { submissions: [] }];\n  " + anchor, 1)
    run = subprocess.run(
        [shutil.which("node"), "-e", head + BB_CTA_TAIL],
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
def test_voice_baseline_sends_add_more_samples_to_the_exam_waiting_for_approval_else_to_students():
    assert 'id="bb-cta" href="/bluebook/#students"' in (SUITE / "baseline.html").read_text(encoding="utf-8")
    waiting = _cta_run()
    assert waiting["href"] == "/bluebook/#exam/e1" and waiting["hidden"] is False
    none = _cta_run(noSealed=True)
    assert none["href"] == "/bluebook/#students"


# ── The pill strip says it scrolls at phone width ─────────────────────────────

SUITE_CSS = (SUITE / "suite.css").read_text(encoding="utf-8")

# live.js run with a strip that overflows: the classes follow the scroll position.
FADE_PRELUDE_ANCHOR = "  querySelectorAll() { return []; },\n  addEventListener() {},\n};\nlet active = 0"
FADE_TAIL = r"""
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
(async () => {
  await sleep(10);
  const out = [];
  for (const s of strips) {
    const seen = [s.classes()];
    for (const left of sc.scrolls || []) { s.scrollLeft = left; s.handlers.scroll.forEach((fn) => fn()); seen.push(s.classes()); }
    out.push({ start: seen[0], scrolled: seen.slice(1), opened: s.scrollLeft0 });
  }
  process.stdout.write(JSON.stringify(out));
})();
"""


def _fade_run(strips: list[dict], scrolls: list[int] | None = None) -> list[dict]:
    prelude = PRELUDE.replace(
        FADE_PRELUDE_ANCHOR,
        """  querySelectorAll(sel) { return sel === '.pills' ? strips : []; },
  addEventListener() {},
};
let active = 0""",
        1,
    )
    assert prelude != PRELUDE, "the harness prelude changed"
    # The strips exist before live.js runs, so its page-ready code finds them.
    strips_js = r"""
const strips = (sc.strips || []).map((d) => {
  const set = new Set();
  const here = d.here ? { offsetLeft: d.here.left, offsetWidth: d.here.width } : null;
  const s = {
    scrollWidth: d.scrollWidth, clientWidth: d.clientWidth, offsetLeft: d.offsetLeft || 0, scrollLeft: 0, handlers: {},
    classList: { toggle(c, on) { if (on) set.add(c); else set.delete(c); } },
    classes() { return Array.from(set).sort(); },
    querySelector() { return here; },
    addEventListener(t, fn) { (this.handlers[t] = this.handlers[t] || []).push(fn); },
  };
  return s;
});
"""
    marker = "const document = {"
    assert marker in prelude
    prelude = prelude.replace(marker, strips_js + marker, 1)
    # Remember where the strip was opened, before any scroll the test makes.
    tail = FADE_TAIL.replace("const seen = [s.classes()];", "s.scrollLeft0 = s.scrollLeft; const seen = [s.classes()];")
    run = subprocess.run(
        [shutil.which("node"), "-e", prelude + tail],
        input=json.dumps({"live": str(SUITE / "live.js"), "strips": strips, "scrolls": scrolls or []}),
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert run.returncode == 0, run.stderr
    return json.loads(run.stdout)


@needs_node
def test_the_suite_pill_strip_fades_on_the_edge_that_has_more_pills():
    (out,) = _fade_run([{"scrollWidth": 580, "clientWidth": 305}], scrolls=[100, 275, 0])
    assert out["start"] == ["fade-end"]
    assert out["scrolled"] == [["fade-end", "fade-start"], ["fade-start"], ["fade-end"]]


@needs_node
def test_a_strip_that_fits_gets_no_fade_and_one_that_overflows_opens_on_the_current_page():
    fits, wide = _fade_run(
        [
            {"scrollWidth": 305, "clientWidth": 305},
            {"scrollWidth": 580, "clientWidth": 305, "offsetLeft": 26, "here": {"left": 300, "width": 100}},
        ]
    )
    assert fits["start"] == [] and fits["opened"] == 0
    # The current pill (left 300, 100 wide) is centred in the 305px strip that starts at 26.
    assert wide["opened"] == 300 - 26 - (305 - 100) / 2
    assert wide["start"] == ["fade-end", "fade-start"]


def test_the_fade_is_drawn_for_each_edge_and_both_in_suite_css_and_the_teacher_nav_css():
    for css in (SUITE_CSS, (DEMO / "bluebook" / "teacher-workspace.css").read_text(encoding="utf-8")):
        for cls in (".fade-end", ".fade-start", ".fade-start.fade-end"):
            assert cls in css, cls
        assert "mask-image" in css
    jsx = (DEMO / "bluebook" / "TeacherWorkspace.jsx").read_text(encoding="utf-8")
    assert "usePillFade(pills, [active, demo]);" in jsx and 'ref={pills} className={\'teacher-pills\'' in jsx


# ── Small things from the audit ───────────────────────────────────────────────

SIGN_IN = DEMO / "index.html"

SIGN_IN_RUN = r"""
const fs = require('fs');
const sc = JSON.parse(fs.readFileSync(0, 'utf8'));
const page = fs.readFileSync(sc.page, 'utf8');
const scripts = Array.from(page.matchAll(/<script>([\s\S]*?)<\/script>/g)).map((m) => m[1]);
const els = new Map();
const el = (id) => { if (!els.has(id)) els.set(id, { id, style: {}, textContent: '', innerHTML: '', disabled: false, value: '', classList: { add() { this.on = true; }, remove() { this.on = false; } } }); return els.get(id); };
const document = { getElementById: el };
const localStorage = { setItem() {}, getItem() { return null; } };
const window = { location: {} };
const fetch = (url) => {
  if (String(url).endsWith('/health')) return Promise.resolve({ json: () => Promise.resolve({ environment: sc.environment }) });
  return Promise.resolve({ ok: false, status: 401, json: () => Promise.resolve({}) });
};
const run = new Function('document', 'localStorage', 'window', 'fetch', scripts[scripts.length - 1] + '\nreturn handleLogin;');
const handleLogin = run(document, localStorage, window, fetch);
(async () => {
  await new Promise((r) => setTimeout(r, 20));   // the health check has answered
  await handleLogin({ preventDefault() {} });
  process.stdout.write(JSON.stringify({ msg: el('errorMsg').textContent, shown: !!el('errorMsg').classList.on, pills: el('demoRolePills').style.display || '' }));
})();
"""


def _sign_in_failure(environment: str) -> dict:
    run = subprocess.run(
        [shutil.which("node"), "-e", SIGN_IN_RUN],
        input=json.dumps({"page": str(SIGN_IN), "environment": environment}),
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert run.returncode == 0, run.stderr
    return json.loads(run.stdout)


@needs_node
def test_the_sign_in_error_names_the_demo_buttons_only_where_they_are_shown():
    demo = _sign_in_failure("demo")
    assert demo["pills"] == "" and demo["msg"] == "Invalid email or password. Try the demo buttons below."
    for real in ("pilot", "staging", "production"):
        out = _sign_in_failure(real)
        assert out["pills"] == "none"  # a real deploy hides them ...
        assert out["msg"] == "Invalid email or password." and out["shown"] is True  # ... and the message does not point at them
    # Markup default: no sentence about buttons before the script has decided.
    assert '<div class="error-msg" id="errorMsg">Invalid email or password.</div>' in SIGN_IN.read_text(encoding="utf-8")


def test_the_sign_in_page_links_to_the_existing_password_reset():
    page = SIGN_IN.read_text(encoding="utf-8")
    assert '<a href="bluebook/#forgot" id="forgotLink">Forgot your password?</a>' in page
    # It opens Bluebook's existing reset form (POST /auth/password-reset/request); no new backend.
    deep = (DEMO / "bluebook" / "deep-link.jsx").read_text(encoding="utf-8")
    app = (DEMO / "bluebook" / "app.jsx").read_text(encoding="utf-8")
    assert "export const FORGOT_HASH = '#forgot';" in deep
    assert "if (window.location.hash === FORGOT_HASH) return 'forgot';" in app
    assert "<ForgotPasswordScreen onNavigate={navigate} />" in app


# Voice Baseline: the name is the heading and the raw id is small secondary text.
GREET_TAIL = r"""
(async () => {
  for (let i = 0; i < 300 && !el('sealed-list').innerHTML.includes('data-act="approve"'); i++) await sleep(10);
  process.stdout.write(JSON.stringify({ greet: el('greet').textContent, id: el('greet-id').textContent, idHidden: el('greet-id').hidden, meta: el('meta').textContent }));
  process.exit(0);
})();
"""


def _greet_run(roster) -> dict:
    head = BASELINE_HARNESS.split("(async () => {")[0]
    anchor = "if (path === '/students') return [200, { students: ['s1'], roster: null }];"
    assert anchor in head, "the baseline harness changed"
    head = head.replace(anchor, "if (path === '/students') return [200, { students: ['s1'], roster: sc.roster || null }];", 1)
    run = subprocess.run(
        [shutil.which("node"), "-e", head + GREET_TAIL],
        input=json.dumps(
            {
                "live": str(SUITE / "live.js"),
                "page": str(SUITE / "baseline.html"),
                "features": str(SUITE / "js" / "feature-data.js"),
                "roster": roster,
            }
        ),
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert run.returncode == 0, run.stderr
    return json.loads(run.stdout)


@needs_node
def test_voice_baseline_shows_the_roster_name_and_the_raw_id_only_as_small_secondary_text():
    named = _greet_run([{"id": "s1", "name": "Ada Student", "sample_count": 5, "authenticated_count": 5}])
    assert named["greet"] == "Ada Student"
    assert named["id"] == "ID s1" and named["idHidden"] is False
    assert "s1" not in named["meta"]  # the counts line no longer opens with the id
    # With no name to show, the heading is the id already: it is not said twice.
    nameless = _greet_run(None)
    assert nameless["greet"] == "s1" and nameless["idHidden"] is True
    assert "s1" not in nameless["meta"]


def test_writing_state_opens_a_habits_evidence_from_the_keyboard():
    script = _inline_scripts(SUITE / "writing-state.html")
    # The bars (one tab stop, arrow keys along them), the tier band labels and the Feature Detail
    # rows are buttons; the evidence says when it is open (aria-expanded) and where focus goes.
    for needle in (
        "col.tabIndex=-1; col.setAttribute('role','button'); col.setAttribute('aria-expanded','false');",
        "onPress(col,()=>{ if(S.base) EVI.open(f.code,col); else CHIPS.toggle(f.tier); });",
        "b.tabIndex=0; b.setAttribute('role','button');",
        "r.tabIndex=0; r.setAttribute('role','button'); r.setAttribute('aria-expanded','false');",
        "onPress(r,()=>EVI.open(r.dataset.code,r));",
        "markExpanded(code);",
        "if(from) $('evi-close').focus();",
        "e.key==='Escape'&&box.classList.contains('show')",
    ):
        assert needle in script, needle


@needs_node
def test_enter_and_space_press_a_clickable_habit_bar_and_nothing_else_does():
    script = _inline_scripts(SUITE / "writing-state.html")
    run = subprocess.run(
        [
            shutil.which("node"),
            "-e",
            r"""
const fs = require('fs');
const sc = JSON.parse(fs.readFileSync(0, 'utf8'));
const onPress = new Function(sc.src + '\nreturn onPress;')();
const out = [];
for (const key of ['Enter', ' ', 'Spacebar', 'a', 'Tab', 'Escape', 'ArrowRight']) {
  let handler = null, pressed = 0, prevented = 0;
  onPress({ addEventListener(t, fn) { if (t === 'keydown') handler = fn; } }, () => { pressed++; });
  handler({ key, preventDefault() { prevented++; } });
  out.push([key, pressed, prevented]);
}
process.stdout.write(JSON.stringify(out));
""",
        ],
        input=json.dumps({"src": _extract(script, "onPress")}),
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert run.returncode == 0, run.stderr
    assert json.loads(run.stdout) == [
        ["Enter", 1, 1], [" ", 1, 1], ["Spacebar", 1, 1], ["a", 0, 0], ["Tab", 0, 0], ["Escape", 0, 0], ["ArrowRight", 0, 0],
    ]
