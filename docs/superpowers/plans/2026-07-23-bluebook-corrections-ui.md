# Bluebook Corrections UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace `Results.jsx`'s fake, local-only "Mark Reviewed" button with a real correction-filing panel that calls the already-working `POST /submissions/{id}/correct` / `GET /admin/corrections` endpoints, per `docs/superpowers/specs/2026-07-22-bluebook-corrections-ui-design.md` (approved).

**Architecture:** Thread the Bluebook seal's `submission_uuid` (already generated client-side, already stored on the Bluebook submission row per the WS-6 P3-P6 reconciliation) into the *scoring* call too, so it becomes the same id `/submissions/{id}/correct` is keyed on — no new lookup needed. Then build a `CorrectionPanel` component that fetches correction history on row-expand and files new corrections via a small form.

**Tech Stack:** React (no build step beyond esbuild — `demo/bluebook/*.jsx`, committed bundle), FastAPI/Pydantic (`original/api.py`, `original/schemas.py` — already fully implemented, no backend changes in this plan), Playwright e2e.

## Global Constraints

- Work in the worktree `~/Desktop/Original-ws6-transplant`, branch `docs/section9-implementation-plans-transplant` (already pushed to `origin/docs/section9-implementation-plans` — this plan's commits will need a follow-up push, not covered by this plan's tasks; ask before pushing).
- Use `/Users/andrew/Desktop/Original/.venv/bin/python` for Python/pytest (shared venv).
- After any `demo/bluebook/*.jsx` change: `cd demo/bluebook && npm run build` and commit the bundle + map alongside (Render has no Node — the committed bundle is what production serves).
- **Correction verify (this plan corrects one assumption from the design spec):** `BB_API.fileCorrection` does **not** currently exist on this branch — it existed on an older, since-superseded branch state but was never carried into the `origin/main`-based reconciliation. Task 2 creates it fresh; treat the design spec's "signature change" language as "create with this shape" instead.
- No backend/Python changes anywhere in this plan — `CorrectionRequest`/`CorrectionResponse`/`CorrectionListResponse` (`original/schemas.py:202-239`) and `submit_correction`/`GET /admin/corrections` (`original/api.py:2870`, `:2984`) are complete and unchanged.

---

### Task 1: Thread the seal `submission_uuid` into the score call

**Files:**
- Modify: `demo/bluebook/Exam.jsx` (`bbScoreWithOriginal` signature + its one call site)
- Rebuild: `demo/bluebook/bluebook.bundle.js` + `.map`

**Interfaces:**
- Produces: `bbScoreWithOriginal(studentId, text, assignment, submissionId)` — `submissionId` forwarded as `submission_id` in the `POST /students/{id}/score` body. `ScoreSubmissionRequest.submission_id` (`original/schemas.py`) is already optional and already preferred over the server's auto-generated fallback (`original/api.py`'s `score_submission`: `submission_id = req.submission_id or f"{student_id}_submission_{state.sample_count}"`) — no backend change needed.

- [ ] **Step 1: Read the current function**

`grep -n -A6 "async function bbScoreWithOriginal" demo/bluebook/Exam.jsx` — confirm the exact current signature and body before editing (it is currently `async function bbScoreWithOriginal(studentId, text, assignment) { ... body: JSON.stringify({ text, assignment }) ... }`, but verify line numbers directly).

- [ ] **Step 2: Add the parameter and forward it**

Change the function signature from:
```js
async function bbScoreWithOriginal(studentId, text, assignment) {
```
to:
```js
async function bbScoreWithOriginal(studentId, text, assignment, submissionId) {
```
And change the fetch body from:
```js
      method: 'POST', headers: bbAuthHeaders(), body: JSON.stringify({ text, assignment }),
```
to:
```js
      method: 'POST', headers: bbAuthHeaders(),
      body: JSON.stringify({ text, assignment, submission_id: submissionId || undefined }),
```

- [ ] **Step 3: Update the one call site to pass the seal uuid**

Find the call in `handleSubmit`'s seal loop (`grep -n "bbScoreWithOriginal(studentId" demo/bluebook/Exam.jsx`). It currently reads:
```js
          seal.aiScore = await bbScoreWithOriginal(studentId, content, cfg.title);
```
Change to:
```js
          seal.aiScore = await bbScoreWithOriginal(studentId, content, cfg.title, seal.uuid);
```

- [ ] **Step 4: Rebuild the bundle**

```bash
cd demo/bluebook && npm run build
```

- [ ] **Step 5: Verify live** — boot a scratch pilot-mode server on a free port (pick one not already in use; check with `lsof -i :PORT` first), seal one exam via the UI or via the existing `exam-robustness.spec.mjs`/`exam-flow.spec.mjs` suites, then confirm via API that the score call's audit-log row now carries the SAME `submission_id` as the Bluebook submission's `submission_uuid`:

```bash
# after sealing one exam through the UI against your scratch server:
curl -s "http://localhost:PORT/admin/audit?student_id=<the student id>&action=score" -H "Authorization: Bearer <staff token>" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['items'][0]['details']['submission_id'])"
curl -s "http://localhost:PORT/bluebook/submissions" -H "Authorization: Bearer <staff token>" | python3 -c "import json,sys; d=json.load(sys.stdin); print(d['submissions'][0]['submission_uuid'])"
```
Expected: both values are identical. Stop your scratch server and remove its scratch DB when done; never touch an already-running server.

Also run the existing frontend e2e suites to confirm nothing regressed:
```bash
cd demo/bluebook && npx playwright test e2e/exam-flow.spec.mjs e2e/exam-robustness.spec.mjs
```
Expected: all passed (these don't assert on `submission_id` matching yet — that's proven by Step 5's manual check and by Task 3's rewritten test).

- [ ] **Step 6: Commit**

```bash
git add demo/bluebook/Exam.jsx demo/bluebook/bluebook.bundle.js demo/bluebook/bluebook.bundle.js.map
git commit -m "Thread the seal submission_uuid into the score call

The score endpoint already accepts an optional submission_id and prefers
it over its auto-generated fallback -- passing the same uuid used for the
baseline write and the Bluebook submission record means the same id now
identifies one sitting across all three, so /submissions/{id}/correct is
directly reachable from a Results row with no separate lookup.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 2: `CorrectionPanel` — replace the fake "Mark Reviewed" with a real correction form + history

**Files:**
- Modify: `demo/bluebook/components.jsx` (add `fileCorrection`, `listCorrections` to `BB_API`)
- Modify: `demo/bluebook/Results.jsx` (`ExpandedRow`'s right column — replace the notes/Mark-Reviewed block with `CorrectionPanel`)
- Rebuild: `demo/bluebook/bluebook.bundle.js` + `.map`

**Interfaces:**
- Consumes: `POST /submissions/{id}/correct` (body: `{is_correct, corrected_verdict, corrected_action, reviewer, notes}`, all but `is_correct` optional — `original/schemas.py:202`), `GET /admin/corrections?submission_id=...` (`original/api.py:2984`, returns `{total, limit, offset, items: [...]}` where each item matches `CorrectionResponse` — `id, submission_id, student_id, original_verdict, original_action, original_divergence_score, corrected_verdict, corrected_action, is_correct, reviewer, notes, created_at`), `result.submission_uuid` (already present on every row from `list_bluebook_submissions`, per `original/store.py:1877`'s `_bluebook_sub_to_dict`), `BB_API.identity().name` (`demo/bluebook/components.jsx` — already-stored staff display name, for the `reviewer` field).
- Produces: `BB_API.fileCorrection(submissionId, {isCorrect, correctedVerdict, correctedAction, reviewer, notes}) -> Promise<CorrectionResponse>` (throws on non-ok, matching every other `BB_API` write method's error-handling convention), `BB_API.listCorrections(submissionId) -> Promise<Array|null>` (matches `listSubmissions`'s fetch-and-return-array-or-null convention exactly).

- [ ] **Step 1: Add `fileCorrection` to `BB_API`**

In `demo/bluebook/components.jsx`, directly after the `listCourses` method (find it: `grep -n "async listCourses" demo/bluebook/components.jsx`), insert:

```js
  // File instructor feedback on a scoring verdict — persists to the
  // corrections ledger (drives future retraining; see original/schemas.py
  // CorrectionRequest). submissionId is the Original scoring-record id
  // for the submission (Exam.jsx now threads the seal's own uuid into the
  // score call, so it's the same as the row's submission_uuid) — not the
  // Bluebook exam id.
  async fileCorrection(submissionId, { isCorrect, correctedVerdict, correctedAction, reviewer, notes }) {
    const r = await fetch(this.base + `/submissions/${encodeURIComponent(submissionId)}/correct`, {
      method: 'POST', headers: this._headers(),
      body: JSON.stringify({
        is_correct: isCorrect,
        corrected_verdict: correctedVerdict || null,
        corrected_action: correctedAction || null,
        reviewer: reviewer || null,
        notes: notes || null,
      }),
    });
    if (!r.ok) {
      let detail = r.statusText;
      try { detail = (await r.json()).detail || detail; } catch (e) {}
      throw new Error(detail);
    }
    return r.json();
  },
  async listCorrections(submissionId) {
    try {
      const r = await fetch(
        this.base + `/admin/corrections?submission_id=${encodeURIComponent(submissionId)}`,
        { headers: this._headers() },
      );
      if (!r.ok) return null;
      return (await r.json()).items || [];
    } catch (e) { return null; }
  },
```

- [ ] **Step 2: Verify the additions parse and don't collide with existing keys**

```bash
node -e "require('esbuild').buildSync({entryPoints:['demo/bluebook/components.jsx'],bundle:false,write:false})" 2>&1 | head -20 || cd demo/bluebook && node -e "require('esbuild').buildSync({entryPoints:['components.jsx'],bundle:false,write:false})"
```
(Just a syntax sanity check — the real build happens in Step 6. If esbuild isn't invokable standalone this way, skip this micro-check and rely on Step 6's full build instead.)

- [ ] **Step 3: Write the `CorrectionPanel` component**

In `demo/bluebook/Results.jsx`, add this new component directly after `ScoreBar` (before `ExpandedRow`):

```jsx
const { useState: useCPState, useEffect: useCPEffect } = React;

const VERDICT_OPTIONS = ['authentic', 'uncertain', 'anomalous'];
const ACTION_OPTIONS = ['no_action', 'monitor', 'schedule_conversation', 'escalate'];

function relativeTime(iso) {
  const then = new Date(iso).getTime();
  if (Number.isNaN(then)) return iso;
  const diffMin = Math.round((Date.now() - then) / 60000);
  if (diffMin < 1) return 'just now';
  if (diffMin < 60) return `${diffMin}m ago`;
  const diffH = Math.round(diffMin / 60);
  if (diffH < 24) return `${diffH}h ago`;
  return `${Math.round(diffH / 24)}d ago`;
}

function CorrectionHistoryItem({ c }) {
  return (
    <div style={{
      padding:'10px 0', borderBottom:'1px solid rgba(201,169,97,0.12)',
      fontFamily:fontBody, fontSize:13, color:BB.fade,
    }}>
      <div style={{ display:'flex', justifyContent:'space-between', marginBottom:4 }}>
        <span style={{ color: c.is_correct ? '#5EB87C' : '#C47A6B', fontFamily:fontMono, fontSize:11, letterSpacing:'0.08em' }}>
          {c.is_correct ? '✓ Verdict correct' : '✗ Verdict overridden'}
        </span>
        <span style={{ fontFamily:fontMono, fontSize:10, color:'rgba(139,155,180,0.6)' }}>
          {c.reviewer || 'Unknown reviewer'} · {relativeTime(c.created_at)}
        </span>
      </div>
      {!c.is_correct && (c.corrected_verdict || c.corrected_action) && (
        <p style={{ margin:'0 0 4px', fontStyle:'italic' }}>
          {c.corrected_verdict && `→ ${c.corrected_verdict}`}
          {c.corrected_verdict && c.corrected_action && ' · '}
          {c.corrected_action && `→ ${c.corrected_action}`}
        </p>
      )}
      {c.notes && <p style={{ margin:0 }}>{c.notes}</p>}
    </div>
  );
}

function CorrectionPanel({ result }) {
  const [history,       setHistory]       = useCPState(null);
  const [isCorrect,     setIsCorrect]     = useCPState(null); // null = unset, true/false once chosen
  const [correctedVerdict, setCorrectedVerdict] = useCPState('');
  const [correctedAction,  setCorrectedAction]  = useCPState('');
  const [notes,          setNotes]         = useCPState('');
  const [submitting,     setSubmitting]    = useCPState(false);
  const [error,          setError]         = useCPState(null);

  const submissionId = result.submission_uuid;

  useCPEffect(() => {
    if (!submissionId) return;
    let live = true;
    BB_API.listCorrections(submissionId).then(items => { if (live) setHistory(items || []); });
    return () => { live = false; };
  }, [submissionId]);

  function resetForm() {
    setIsCorrect(null);
    setCorrectedVerdict('');
    setCorrectedAction('');
    setNotes('');
  }

  async function handleFile() {
    if (isCorrect === null || !submissionId) return;
    setSubmitting(true);
    setError(null);
    try {
      const identity = BB_API.identity();
      const created = await BB_API.fileCorrection(submissionId, {
        isCorrect,
        correctedVerdict: isCorrect ? null : (correctedVerdict || null),
        correctedAction: isCorrect ? null : (correctedAction || null),
        reviewer: identity.name || null,
        notes: notes || null,
      });
      setHistory(h => [created, ...(h || [])]);
      resetForm();
    } catch (e) {
      setError(String(e && e.message || e));
    } finally {
      setSubmitting(false);
    }
  }

  if (!submissionId) {
    return (
      <div>
        <MetaLabel style={{ display:'block', marginBottom:14 }}>Examiner's Correction</MetaLabel>
        <p style={{
          fontFamily:fontBody, fontStyle:'italic', fontSize:14, color:BB.fade,
          padding:'12px 14px', border:'1px solid rgba(201,169,97,0.15)', margin:0,
        }}>
          This submission wasn't scored — no verdict to correct.
        </p>
      </div>
    );
  }

  return (
    <div>
      <MetaLabel style={{ display:'block', marginBottom:14 }}>Examiner's Correction</MetaLabel>

      {history === null ? (
        <p style={{ fontFamily:fontBody, fontStyle:'italic', fontSize:13, color:BB.fade }}>Loading history…</p>
      ) : history.length > 0 ? (
        <div style={{ marginBottom:16, maxHeight:180, overflowY:'auto' }}>
          {history.map(c => <CorrectionHistoryItem key={c.id} c={c} />)}
        </div>
      ) : null}

      <div style={{ display:'flex', gap:10, marginBottom:10 }}>
        <button
          onClick={() => setIsCorrect(true)}
          style={{
            flex:1, padding:'8px 14px', fontFamily:fontMono, fontSize:11, letterSpacing:'0.08em',
            textTransform:'uppercase', cursor:'pointer',
            background: isCorrect === true ? '#5EB87C' : 'transparent',
            color: isCorrect === true ? BB.deep : '#5EB87C',
            border:'1px solid #5EB87C',
          }}
        >Correct</button>
        <button
          onClick={() => setIsCorrect(false)}
          style={{
            flex:1, padding:'8px 14px', fontFamily:fontMono, fontSize:11, letterSpacing:'0.08em',
            textTransform:'uppercase', cursor:'pointer',
            background: isCorrect === false ? '#C47A6B' : 'transparent',
            color: isCorrect === false ? BB.deep : '#C47A6B',
            border:'1px solid #C47A6B',
          }}
        >Incorrect</button>
      </div>

      {isCorrect === false && (
        <div style={{ display:'flex', gap:10, marginBottom:10 }}>
          <select
            value={correctedVerdict}
            onChange={e => setCorrectedVerdict(e.target.value)}
            style={{
              flex:1, padding:'8px 10px', background:'rgba(0,0,0,0.25)',
              border:'1px solid rgba(201,169,97,0.22)', color:BB.cream,
              fontFamily:fontMono, fontSize:12,
            }}
          >
            <option value="">No verdict change</option>
            {VERDICT_OPTIONS.map(v => <option key={v} value={v}>{v}</option>)}
          </select>
          <select
            value={correctedAction}
            onChange={e => setCorrectedAction(e.target.value)}
            style={{
              flex:1, padding:'8px 10px', background:'rgba(0,0,0,0.25)',
              border:'1px solid rgba(201,169,97,0.22)', color:BB.cream,
              fontFamily:fontMono, fontSize:12,
            }}
          >
            <option value="">No action change</option>
            {ACTION_OPTIONS.map(a => <option key={a} value={a}>{a}</option>)}
          </select>
        </div>
      )}

      <textarea
        value={notes}
        onChange={e => setNotes(e.target.value)}
        placeholder="Record observations, decision rationale, or marginal notes…"
        rows={4}
        style={{
          width:'100%', boxSizing:'border-box',
          background:'rgba(0,0,0,0.25)',
          border:'1px solid rgba(201,169,97,0.22)',
          padding:'12px 14px',
          fontFamily:fontBody, fontStyle:'italic', fontSize:15,
          color:BB.cream, outline:'none', resize:'vertical',
          lineHeight:1.65, letterSpacing:'0.01em', marginBottom:10,
        }}
      />

      {error && (
        <p style={{ color:'#C47A6B', fontFamily:fontMono, fontSize:12, margin:'0 0 10px' }}>{error}</p>
      )}

      <BtnPrimary
        onClick={handleFile}
        disabled={isCorrect === null || submitting}
        style={{ padding:'8px 20px', fontSize:14, width:'100%', opacity: (isCorrect === null || submitting) ? 0.5 : 1 }}
      >
        {submitting ? 'Filing…' : 'File Correction'}
      </BtnPrimary>
    </div>
  );
}
```

- [ ] **Step 4: Wire `CorrectionPanel` into `ExpandedRow`**

In `demo/bluebook/Results.jsx`, `ExpandedRow` currently opens with:
```jsx
function ExpandedRow({ result, onClose }) {
  const [notes, setNotes] = useResState('');
  const [marked, setMarked] = useResState(result.status === 'REVIEWED');

  return (
```
Change to (drop the two now-unused `notes`/`marked` state hooks entirely):
```jsx
function ExpandedRow({ result, onClose }) {
  return (
```

Then replace the entire "Right: review notes" block. Find the exact text starting at:
```jsx
        {/* Right: review notes */}
        <div>
          <MetaLabel style={{ display:'block', marginBottom:14 }}>Examiner's Notes</MetaLabel>
```
and ending at (this is the OUTER wrapper div's close — it comes right before the `</div>` that closes the two-column grid, i.e. two closing `</div>` tags after the button-row div, not one):
```jsx
          </div>
        </div>
```
(the whole "Right: review notes" `<div>...</div>` block, textarea + button row + Mark-Reviewed/Reviewed toggle, all of it) with:

```jsx
        {/* Right: correction form + history */}
        <div>
          <CorrectionPanel result={result} />
          <div style={{ marginTop:12 }}>
            <BtnGhost onClick={onClose} style={{ padding:'8px 20px', fontSize:14, width:'100%' }}>
              Close
            </BtnGhost>
          </div>
        </div>
```

- [ ] **Step 5: Confirm `Seal` import is still used elsewhere or remove it if now-unused**

`ExpandedRow`'s old "Reviewed" state used the `Seal` icon component (imported at the top of `Results.jsx`). Check whether `Seal` is used anywhere else in this file (`grep -n "<Seal" demo/bluebook/Results.jsx`) — if the only remaining usage was the removed block, remove `Seal` from the import line at the top of the file to avoid an unused-import lint warning; otherwise leave the import as-is.

- [ ] **Step 6: Rebuild the bundle**

```bash
cd demo/bluebook && npm run build
```

- [ ] **Step 7: Manual verification against a live server**

Boot a scratch pilot-mode server (free port, scratch DB — same pattern as Task 1 Step 5), seal one exam, open Results, expand the row, confirm: history section shows "Loading history…" then empty (first correction), Correct/Incorrect toggle works, selecting Incorrect reveals the two dropdowns, filing a correction adds it to the visible history immediately without a page reload, filing a second correction appends above the first. Screenshot or describe what you see in your report.

- [ ] **Step 8: Commit**

```bash
git add demo/bluebook/components.jsx demo/bluebook/Results.jsx demo/bluebook/bluebook.bundle.js demo/bluebook/bluebook.bundle.js.map
git commit -m "Add CorrectionPanel: real correction filing + history, replacing fake Mark Reviewed

BB_API.fileCorrection/listCorrections call the already-working
/submissions/{id}/correct and /admin/corrections endpoints. The old
'Mark Reviewed' button was pure local component state -- never persisted,
reset on reload, and didn't correspond to an actual correction judgment.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 3: e2e — drive the real panel, plus a cold-start disabled-state test

**Files:**
- Modify: `demo/bluebook/e2e/professor-journey.spec.mjs` (rewrite the existing API-only correction test to drive the UI; delete the now-stale "no frontend affordance" framing)
- Test: same file

**Interfaces:**
- Consumes: everything from Tasks 1-2 — `result.submission_uuid` now equals the score's `submission_id`, `CorrectionPanel`'s rendered DOM (Correct/Incorrect buttons, dropdowns, notes textarea, "File Correction" button, history items).

- [ ] **Step 1: Read the current test and its surrounding fixtures**

Read `demo/bluebook/e2e/professor-journey.spec.mjs`'s existing correction test (search for `'a correction filed against the scored submission'`) and the test immediately before it (`'the candidate appears on the Students roster'`) to see how `staffPage`/`workerTenant`/`journey` are used to navigate to Results and expand a row — reuse those exact patterns rather than inventing new navigation.

- [ ] **Step 2: Rewrite the test to drive the real UI**

Replace the entire test body (keep the `test('a correction filed against the scored submission lands in corrections and the audit trail', async ({ workerTenant, request, staffPage }) => { ... })` signature, adding `staffPage` to the destructured fixtures) with:

```js
  test('a correction filed against the scored submission lands in corrections and the audit trail', async ({
    workerTenant, request, staffPage,
  }) => {
    await openScreen(staffPage, 'Results')
    // The row rendered for this journey's candidate — reuse the same
    // candidate-name lookup pattern the Results-listing test above uses.
    const { candidateName } = names(workerTenant)
    const row = staffPage.getByText(candidateName, { exact: true }).locator('..').locator('..')
    await row.click()

    await expect(staffPage.getByRole('button', { name: 'Correct' })).toBeVisible({ timeout: 10_000 })
    await staffPage.getByRole('button', { name: 'Incorrect' }).click()
    await staffPage.locator('select').first().selectOption('authentic')
    await staffPage.locator('select').nth(1).selectOption('no_action')
    await staffPage.getByPlaceholder('Record observations, decision rationale, or marginal notes…')
      .fill('E2E professor-journey correction')

    const [correctionResponse] = await Promise.all([
      staffPage.waitForResponse(r => r.url().includes('/submissions/') && r.url().includes('/correct') && r.request().method() === 'POST'),
      staffPage.getByRole('button', { name: 'File Correction' }).click(),
    ])
    expect(correctionResponse.ok()).toBe(true)
    const correction = await correctionResponse.json()
    const submissionId = correction.submission_id

    // The filed correction appears in the panel's history immediately.
    await expect(staffPage.getByText('✗ Verdict overridden')).toBeVisible({ timeout: 5_000 })
    await expect(staffPage.getByText('E2E professor-journey correction')).toBeVisible()

    // API-level verification alongside the UI-level one: the pipeline is
    // proven end to end (click → write → audit), not just the click.
    const headers = staffAuth(workerTenant)
    const correctionsListRes = await request.get(
      `/admin/corrections?submission_id=${encodeURIComponent(submissionId)}`,
      { headers },
    )
    expect(correctionsListRes.ok()).toBe(true)
    const correctionsList = await correctionsListRes.json()
    expect(correctionsList.items.some(c => c.notes === 'E2E professor-journey correction')).toBe(true)

    const auditRes = await request.get(
      `/admin/audit?student_id=${encodeURIComponent(workerTenant.student.student_id)}&action=correction`,
      { headers },
    )
    expect(auditRes.ok()).toBe(true)
    const audit = await auditRes.json()
    expect(audit.total).toBeGreaterThan(0)
    expect(audit.items.some(i => i.action === 'correction')).toBe(true)
  })
```

**If the row-selection locator in the first lines doesn't reliably hit the row's clickable container** (the exact DOM structure of the Results row is a `<div onClick=...>` per `Results.jsx`'s `ResultsScreen` — verify the real structure by reading `Results.jsx` directly rather than trusting the snippet above verbatim), adjust to whatever locator reliably opens that candidate's row — e.g. `staffPage.getByText(candidateName, { exact: true })` then `.locator('xpath=ancestor::div[@style and contains(@style,"cursor")]')`, or simplest: give the clickable row a `data-testid` if no existing locator is reliable enough (a one-line addition to `Results.jsx`, e.g. `data-testid={`result-row-${result.id}`}` on the row's outer `<div>`, then `staffPage.getByTestId(...)`. Prefer this if the text-based locator proves flaky.

- [ ] **Step 3: Delete the stale "no frontend affordance" framing**

Remove the test's old leading comment block (`// No frontend affordance exists for this (see file header) — exercised...`) since it's no longer true. Also check the file's header docstring (top of `professor-journey.spec.mjs`) for a matching "one honest gap remains... Results.jsx has NO correction-filing UI at all" note (mentioned in this repo's history — search for `"NO correction-filing UI"`) — remove or update that too if present.

- [ ] **Step 4: Add the cold-start disabled-state test**

Add a new test in the same `describe` block (or a new lightweight one), after the corrections test:

```js
  test('a submission with no linked score shows the disabled correction state', async ({ staffPage, request, workerTenant }) => {
    // Record a Bluebook submission directly via the API without ever calling
    // /students/{id}/score first -- exactly the cold-start case (zero
    // authenticated baseline samples) where scoring 422s and no
    // submission_uuid-linked score exists.
    const headers = staffAuth(workerTenant)
    const res = await request.post('/bluebook/submissions', {
      headers,
      data: {
        student_id: `${workerTenant.tenant_id}:cold-start-candidate`,
        candidate: 'Cold Start Candidate',
        exam_title: 'Unscored Exam',
        course: 'TEST 000',
        word_count: 10,
        time_min: 1,
        status: 'SUBMITTED',
        // deliberately no submission_uuid
      },
    })
    expect(res.ok()).toBe(true)

    await openScreen(staffPage, 'Results')
    const row = staffPage.getByText('Cold Start Candidate', { exact: true }).locator('..').locator('..')
    await row.click()
    await expect(staffPage.getByText("This submission wasn't scored — no verdict to correct.")).toBeVisible({ timeout: 10_000 })
    await expect(staffPage.getByRole('button', { name: 'Correct' })).toHaveCount(0)
  })
```

- [ ] **Step 5: Run against a live server**

Boot a scratch pilot-mode server (free port, scratch DB), run:
```bash
cd demo/bluebook && PLAYWRIGHT_BASE_URL=http://localhost:PORT SECRET_KEY=ci-test-only-secret-do-not-deploy npx playwright test e2e/professor-journey.spec.mjs
```
Expected: all passed (this file's full suite, not just the 2 correction tests — confirm nothing else in this file broke from the `ExpandedRow` restructuring). Stop the server and clean up scratch files afterward.

- [ ] **Step 6: Commit**

```bash
git add demo/bluebook/e2e/professor-journey.spec.mjs
git commit -m "Rewrite correction e2e test to drive the real CorrectionPanel UI

Was API-only with a comment flagging the missing frontend affordance --
that's no longer true. Adds a cold-start disabled-state test for
submissions with no linked score.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 4: Final verification

- [ ] **Step 1: Full backend suite** (unaffected by this plan, but confirm nothing broke)

```bash
.venv/bin/python -m pytest tests/ validation/test_tier10_optional.py -q
```
Expected: 0 failed.

- [ ] **Step 2: Full e2e suite**

Boot a scratch pilot-mode server, run:
```bash
cd demo/bluebook && npx playwright test --grep-invert "@serial-lockout"
```
Expected: 0 failed. Stop the server, clean up scratch files.

- [ ] **Step 3: `app/` workspace** (unaffected, confirm)

```bash
cd app && npm test && npm run lint && npm run typecheck
```
Expected: all clean.

- [ ] **Step 4: Report** — summarize what was built, confirm both e2e tests pass, note this branch still needs a push (ask before pushing — this plan doesn't include that step).
