# Bulk Approval Sets Aside Late and Warned Sittings Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** "Add all sealed submissions to baselines" stops adding late or warned sittings and lists them for the professor's separate review; one-at-a-time approval is unchanged.

**Architecture:** The rule lives server-side in `original/routers/bluebook_baselines.py`: `_add` gains a `set_aside_flagged` switch used only by the bulk route, returning status `needs_review` with a plain reason after the existing nothing-written, workspace and already-in-baseline checks. The bulk response and audit gain `needs_review`; the page's `baselineSummary` lists the set-aside students.

**Tech Stack:** Python 3.11, FastAPI, React 19 (esbuild bundle), node:test, Playwright.

**Spec:** `docs/superpowers/specs/2026-10-05-baseline-approval-design.md`, section "Addendum (2026-10-05): bulk approval sets aside late and warned sittings".

## Global Constraints

- Report-only, consistency-not-accusation wording: sittings are "set aside for your review", never "flagged" or "suspicious".
- No student text in audit details or logs; ids and counts only.
- Python: `/Users/andrew/Desktop/Original/.venv/bin/python`; add `--no-cov` to focused pytest runs.
- After editing `demo/bluebook/*.jsx`: `cd demo/bluebook && npm run build` and commit the rebuilt `*.bundle.*` files in the same commit.
- Commit messages end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Do not push.

---

### Task 1: Set aside late and warned sittings in bulk approval

**Files:**
- Modify: `original/routers/bluebook_baselines.py` (`_add` and `approve_exam_baselines`)
- Modify: `demo/bluebook/Teacher.jsx` (`baselineSummary`)
- Test: `tests/test_bluebook_baselines.py`, `demo/bluebook/unit/baselines.test.mjs`

**Interfaces:**
- Produces: `_review_reason(rec: dict) -> str` ("" when neither late nor warned); `_add(rec, request, set_aside_flagged: bool = False)`; bulk response key `needs_review` (int) and rows with `status: "needs_review"`, `detail: <reason>`; audit detail `needs_review_ids`.

- [ ] **Step 1: Write the failing Python tests**

In `tests/test_bluebook_baselines.py`, change the `_seal` helper's signature and body so extra fields can be sent:

```python
def _seal(client, student, exam_id, answers=ANSWERS, **extra):
    client.post(f"/bluebook/me/exams/{exam_id}/start", headers=_auth(student["token"]))
    body = {
        "exam_id": exam_id,
        "student_id": student["student_id"],
        "word_count": 120,
        "text": "\n\n".join(f"Question {i + 1}.\n{a}" for i, a in enumerate(answers)),
        "answers": answers,
        "submission_uuid": f"uuid-{student['student_id']}-{exam_id}",
        **extra,
    }
    r = client.post("/bluebook/submissions", json=body, headers=_auth(student["token"]))
    assert r.status_code == 201, r.text
    return r.json()["id"]
```

Append:

```python
def _seal_late(client, student, exam_id, monkeypatch):
    """Seal after the sitting's deadline: the seal route tags it late."""
    from datetime import datetime as _real_dt
    from datetime import timedelta

    import original.routers.bluebook as bb_mod

    class _Later:
        @staticmethod
        def now(tz=None):
            return _real_dt.now(tz) + timedelta(hours=6)

        fromisoformat = _real_dt.fromisoformat

    client.post(f"/bluebook/me/exams/{exam_id}/start", headers=_auth(student["token"]))
    monkeypatch.setattr(bb_mod, "datetime", _Later)
    try:
        sub = _seal(client, student, exam_id, answers=[ANSWERS[1], ANSWERS[0]])
    finally:
        monkeypatch.undo()
    assert get_repository().get_bluebook_submission(sub)["late"] == 1
    return sub


def test_bulk_sets_aside_late_and_warned_sittings(live_client, monkeypatch):
    prof, course, exam = _workspace(live_client)
    clean = _student(live_client, prof, course, "clean@school.edu")
    late = _student(live_client, prof, course, "late@school.edu")
    warned = _student(live_client, prof, course, "warned@school.edu")
    _seal(live_client, clean, exam["id"])
    _seal_late(live_client, late, exam["id"], monkeypatch)
    _seal(
        live_client, warned, exam["id"], answers=[ANSWERS[0][::-1]],
        warnings=[{"type": "focus_lost"}, {"type": "paste_blocked"}],
    )

    r = live_client.post(f"/bluebook/exams/{exam['id']}/baseline", headers=_auth(prof["token"]))

    assert r.status_code == 200, r.text
    body = r.json()
    assert (body["added"], body["needs_review"]) == (1, 2)
    reasons = {row["student"]: row["detail"] for row in body["results"] if row["status"] == "needs_review"}
    assert sorted(reasons.values()) == ["2 lockdown warnings", "late"]
    assert _sample_count(clean) == 1
    assert _sample_count(late) == 0
    assert _sample_count(warned) == 0
    audit = get_repository().list_audit(action="baseline_approve_bulk")["items"][0]
    assert len(audit["details"]["needs_review_ids"]) == 2


def test_a_warned_sitting_can_still_be_added_one_at_a_time(live_client):
    prof, course, exam = _workspace(live_client)
    stu = _student(live_client, prof, course, "warned@school.edu")
    sub = _seal(live_client, stu, exam["id"], warnings=[{"type": "tab_hidden"}])

    r = live_client.post(f"/bluebook/submissions/{sub}/baseline", headers=_auth(prof["token"]))

    assert r.json()["status"] == "added"
    assert _sample_count(stu) == 1


def test_bulk_reports_an_already_added_warned_sitting_as_in_baseline(live_client):
    prof, course, exam = _workspace(live_client)
    stu = _student(live_client, prof, course, "warned@school.edu")
    sub = _seal(live_client, stu, exam["id"], warnings=[{"type": "tab_hidden"}])
    live_client.post(f"/bluebook/submissions/{sub}/baseline", headers=_auth(prof["token"]))

    r = live_client.post(f"/bluebook/exams/{exam['id']}/baseline", headers=_auth(prof["token"]))

    assert (r.json()["already_in_baseline"], r.json()["needs_review"]) == (1, 0)
```

If `list_audit` returns entries oldest-first, select the bulk entry whose `details["exam_id"] == exam["id"]` instead of `[0]` — read the current `list_audit` ordering before asserting.

- [ ] **Step 2: Run them to verify they fail**

Run: `/Users/andrew/Desktop/Original/.venv/bin/python -m pytest tests/test_bluebook_baselines.py -q --no-cov -k "set_aside or one_at_a_time or already_added_warned"`
Expected: `test_bulk_sets_aside_late_and_warned_sittings` and `test_bulk_reports_an_already_added_warned_sitting_as_in_baseline` FAIL with `KeyError: 'needs_review'`; `test_a_warned_sitting_can_still_be_added_one_at_a_time` passes already (it pins that single approval stays unchanged).

- [ ] **Step 3: Implement the server change**

In `original/routers/bluebook_baselines.py`, add above `_add`:

```python
def _review_reason(rec: dict) -> str:
    """Why bulk approval leaves this sitting for the professor to look at
    first: a late seal and/or any recorded lockdown warning. Empty when
    neither. Plain wording; these are listed for a closer look, not flagged."""
    reasons = []
    if rec.get("late"):
        reasons.append("late")
    count = len(rec.get("warnings") or [])
    if count:
        reasons.append(f"{count} lockdown warning{'' if count == 1 else 's'}")
    return ", ".join(reasons)
```

Change `_add`'s signature to `def _add(rec: dict, request: Request, set_aside_flagged: bool = False) -> dict:` and, directly after the existing `already_in_baseline` return (the fingerprint check), add:

```python
    if set_aside_flagged:
        reason = _review_reason(rec)
        if reason:
            return _row(rec, "needs_review", reason)
```

In `approve_exam_baselines`: add `"needs_review"` to the tuple that builds `ids`; call `_add(rec, request, set_aside_flagged=True)`; add `"needs_review": len(ids["needs_review"]),` to `counts` (after `"held"`). The audit's `needs_review_ids` then follows from the existing `**{f"{status}_ids": …}` expression. Update the route's docstring to: `"""Add every sealed submission of an examination to its student's baseline, except late or warned sittings, which are set aside for the professor's review."""`

- [ ] **Step 4: Run the Python tests**

Run: `/Users/andrew/Desktop/Original/.venv/bin/python -m pytest tests/test_bluebook_baselines.py tests/test_bluebook_api.py -q --no-cov`
Expected: all pass.

- [ ] **Step 5: Write the failing unit test**

Append to `demo/bluebook/unit/baselines.test.mjs`:

```js
test('the bulk summary lists sittings set aside for review', () => {
  assert.equal(
    baselineSummary({ added: 1, already_in_baseline: 0, held: 0, needs_review: 2, nothing_written: 0, errors: 0,
      results: [
        { status: 'needs_review', student: 'Ana', detail: 'late' },
        { status: 'needs_review', student: 'Ben', detail: '2 lockdown warnings' },
        { status: 'added', student: 'Cy' },
      ] }),
    '1 added · 0 already in baseline · 0 not added (differ strongly from earlier samples) · '
      + '2 set aside for your review (late or with lockdown warnings). '
      + 'Set aside: Ana (late), Ben (2 lockdown warnings).',
  );
});
```

Run: `cd demo/bluebook && node --test unit/baselines.test.mjs`
Expected: the new test FAILS (no set-aside text); the existing two pass.

- [ ] **Step 6: Implement the summary**

Replace `baselineSummary` in `demo/bluebook/Teacher.jsx` with:

```jsx
export function baselineSummary(r) {
  const parts = [
    `${r.added} added`,
    `${r.already_in_baseline} already in baseline`,
    `${r.held} not added (differ strongly from earlier samples)`,
  ];
  if (r.needs_review) parts.push(`${r.needs_review} set aside for your review (late or with lockdown warnings)`);
  if (r.nothing_written) parts.push(`${r.nothing_written} with nothing written`);
  if (r.errors) parts.push(`${r.errors} could not be added`);
  const rows = r.results || [];
  const held = rows.filter(x => x.status === 'held').map(x => x.student).filter(Boolean);
  const setAside = rows.filter(x => x.status === 'needs_review')
    .map(x => `${x.student || 'Candidate'} (${x.detail})`);
  let text = parts.join(' · ') + '.';
  if (held.length) text += ` Not added: ${held.join(', ')}.`;
  if (setAside.length) text += ` Set aside: ${setAside.join(', ')}.`;
  return text;
}
```

Also change the bulk confirm text in `ManageExamScreen.addAllToBaselines` to: `'Add every sealed submission of this examination to the students’ writing baselines? Late sittings and sittings with lockdown warnings are set aside for you to review one at a time, and exams that differ strongly from a student’s existing samples are not added.'`

- [ ] **Step 7: Build and run unit tests**

Run: `cd demo/bluebook && npm run build && node --test unit/`
Expected: three ✓ build lines; all unit tests pass (the two existing summary tests keep their exact strings).

- [ ] **Step 8: Docs**

In `docs/BLUEBOOK_LAUNCH_CHECKLIST.md`, in the "Approving exams as writing baselines" item, add: `**Add all** sets aside late sittings and sittings with any lockdown warning and lists them; add those one at a time from the reader after looking.` In `docs/API_REFERENCE.md`, add `needs_review` (count, and per-row status with a reason) to the `POST /bluebook/exams/{id}/baseline` response.

- [ ] **Step 9: Browser check**

Start your own pilot-mode server (port 8771, scratch `ORIGINAL_DB`, `ORIGINAL_ENV=pilot SECRET_KEY=ci-test-only-secret-do-not-deploy MAINTENANCE_TOKEN=ci-test-only LOGIN_THROTTLE_MAX_ATTEMPTS=500 /Users/andrew/Desktop/Original/.venv/bin/python run.py --demo --frontend-dir demo --port 8771 --skip-seed`). Run: `cd demo/bluebook && PLAYWRIGHT_BASE_URL=http://localhost:8771 SECRET_KEY=ci-test-only-secret-do-not-deploy MAINTENANCE_TOKEN=ci-test-only npx playwright test e2e/baseline-approval.spec.mjs --workers=2 --timeout=90000`
Expected: all pass (its seals carry no warnings and are on time, so its summary string is unchanged). Stop the server.

- [ ] **Step 10: Commit**

```bash
git add original/routers/bluebook_baselines.py tests/test_bluebook_baselines.py demo/bluebook/Teacher.jsx demo/bluebook/unit/baselines.test.mjs demo/bluebook/*.bundle.* docs/BLUEBOOK_LAUNCH_CHECKLIST.md docs/API_REFERENCE.md
git commit -m "Add setting aside late and warned sittings in bulk baseline approval

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```
