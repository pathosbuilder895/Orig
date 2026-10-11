"""Fixes from the 2026-10-11 button audit of the live Original suite.

Each section pins one fix: what the page now does, so a later edit cannot quietly
put the broken behaviour back. The audit's report is
.superpowers/sdd/button-audit-report.md.
"""

from __future__ import annotations

import json
import shutil
import subprocess

from tests.test_original_suite_static import (  # noqa: F401
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
