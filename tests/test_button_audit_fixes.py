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
    ROOT,
    SUITE,
    _extract,
    _inline_scripts,
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
