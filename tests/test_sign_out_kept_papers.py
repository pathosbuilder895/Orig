"""Every sign-out forgets the papers the Original pages keep on this computer.

Writing State and the classic Analysis page keep a student's pasted papers and
their results in localStorage (``original_portfolio_<student id>``), and the
last result in sessionStorage (``original_last_result``). On a shared computer
those must not outlive the session, whichever page the teacher signs out from:
the new pages (``Live.signOut`` in demo/original/live.js, tested in
tests/test_original_suite_static.py), Bluebook (``BB_API.logout``, run for real
in demo/bluebook/unit/sign-out.test.mjs) and the classic page
(``signOut`` in demo/professor.html, run for real here).
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PROFESSOR = ROOT / "demo" / "professor.html"
LIVE_JS = ROOT / "demo" / "original" / "live.js"
COMPONENTS = ROOT / "demo" / "bluebook" / "components.jsx"

needs_node = pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")

PREFIX = "original_portfolio_"
LAST_RESULT = "original_last_result"

RUN = r"""
const fs = require('fs');
const sc = JSON.parse(fs.readFileSync(0, 'utf8'));
function store(initial) {
  const m = new Map(Object.entries(initial || {}));
  return {
    getItem(k) { return m.has(k) ? m.get(k) : null; },
    setItem(k, v) { m.set(k, String(v)); },
    removeItem(k) { m.delete(k); },
    key(i) { return Array.from(m.keys())[i] ?? null; },
    get length() { return m.size; },
    keys() { return Array.from(m.keys()).sort(); },
  };
}
const blocked = new Proxy({}, { get() { throw new Error('storage is blocked'); } });
const replaced = [];
const localStorage = sc.blockStorage ? blocked : store(sc.local);
const sessionStorage = sc.blockStorage ? blocked : store(sc.session);
const location = { replace(u) { replaced.push(u); } };
new Function('localStorage', 'sessionStorage', 'location', sc.src + '\nsignOut();')(localStorage, sessionStorage, location);
process.stdout.write(JSON.stringify({
  local: sc.blockStorage ? null : localStorage.keys(),
  session: sc.blockStorage ? null : sessionStorage.keys(),
  replaced,
}));
"""


def _professor_sign_out() -> str:
    page = PROFESSOR.read_text(encoding="utf-8")
    found = re.search(r"^function signOut\(\) \{.*?^\}", page, re.S | re.M)
    assert found, "demo/professor.html has no signOut()"
    return found.group(0)


def _run(**scenario) -> dict:
    run = subprocess.run(
        [shutil.which("node"), "-e", RUN],
        input=json.dumps({"src": _professor_sign_out(), **scenario}),
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert run.returncode == 0, run.stderr
    return json.loads(run.stdout)


@needs_node
def test_the_classic_page_sign_out_forgets_every_kept_paper_and_the_last_result():
    papers = {f"{PREFIX}t:s{i}": '[{"text":"a whole paper"}]' for i in range(9)}
    out = _run(
        local={
            "original_principal_token": "tok",
            "original_role": "professor",
            "original_tenant": "t",
            "original_name": "Pat",
            f"{PREFIX}": "a prefix with no student id still goes",
            **papers,
            "original_portfolio": "not a kept paper: no trailing underscore",
            "another_site_key": "left alone",
        },
        session={LAST_RESULT: '{"result":{}}', "unrelated": "left alone"},
    )
    assert out["local"] == ["another_site_key", "original_portfolio"]
    assert out["session"] == ["unrelated"]
    assert out["replaced"] == ["/index.html"]


@needs_node
def test_the_classic_page_still_signs_out_when_the_browser_blocks_storage():
    out = _run(blockStorage=True)
    assert out["replaced"] == ["/index.html"]


def test_every_sign_out_names_the_same_keys():
    # The three implementations cannot share code (a static page, a script and a
    # bundle), so this keeps them from drifting apart.
    for path in (LIVE_JS, COMPONENTS, PROFESSOR):
        text = path.read_text(encoding="utf-8")
        assert f"'{PREFIX}'" in text, f"{path.name} does not clear {PREFIX}*"
        assert f"'{LAST_RESULT}'" in text, f"{path.name} does not clear {LAST_RESULT}"
