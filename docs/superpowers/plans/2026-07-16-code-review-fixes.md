# Code-Review Fixes (2026-07-16) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Land the fixes from `docs/CODE_REVIEW_2026-07-16.md` — repair the broken correction endpoint (16 failing tests), correct a false-premise test, escape the shared LIKE pattern, harden two WS-8 components, and bring every stale doc/CI claim back in line with measured reality.

**Architecture:** All fixes are small, surgical edits to the existing uncommitted working tree in `/Users/andrew/Desktop/Original`. The repository-seam fix (Task 1) is the keystone — 15 of 16 failures and two false doc claims all trace to it. Component fixes (Tasks 4–7) touch only `app/src/`; doc fixes (Task 8) run last so they can record a verified-green state.

**Tech Stack:** Python 3.11 (`.venv/bin/python`), pytest, FastAPI, SQLite; React 18 + TypeScript + Vitest + axe in `app/` (npm scripts: `test`, `lint`, `typecheck`).

## Global Constraints

- **Work in `/Users/andrew/Desktop/Original` (the main checkout), NOT the `code-review-changes-a28b2a` worktree.** The reviewed code exists only as uncommitted changes in the main checkout; the worktree is at `origin/main` and lacks all of it.
- **NO git commits, stashes, checkouts, or `git clean` anywhere in this plan.** The entire reviewed state is uncommitted user work; any commit would sweep unrelated WIP into it, and any stash/checkout risks losing it (see memory: `feedback_git_stash_diagnostic_risk`, `feedback_preserve_before_overwrite`). Every task ends with a test run instead of a commit. Commit strategy is a user decision (see "Decisions required" below).
- **Do NOT delete or modify `demo/app/` or `demo/bluebook/components.jsx`'s `fileCorrection`.** Both are uncommitted (unrecoverable if deleted) and are explicit decision items, not fixes.
- Python: always `.venv/bin/python` / `.venv/bin/python -m pytest`, never system python3.
- Never kill or restart a running dev server.
- Do not change `original/constants.py` feature ordering or NORM_BOUNDS (not needed by any task here).
- A clean full-suite run is **0 failed** (XFAIL/XPASS from `TestAuthEndpoints` are expected under rate-limit exhaustion).

## Decisions required from the user (no code changes in this plan)

1. **Critical #3 — `demo/app/` (79 files):** an unsanctioned second React migration duplicating the live UI, conflicting with the sanctioned `app/` (Vite+TS) WS-8 workspace. Review verdict: needs a human decision on which migration is canonical. Until decided: left untouched. If kept, it needs `_STAFF_ONLY_PREFIXES`/`_DEMO_ONLY_STATICS` gating for `/app/*` in `original/api.py:288-310` and a full a11y pass (zero `aria-`/`role=` today).
2. **`BB_API.fileCorrection()`** (`demo/bluebook/components.jsx:306`): defined, never called. Either staged work for a Results.jsx correction UI (keep) or dead code (remove + rebuild bundle). Deleting uncommitted code is unrecoverable — user's call.
3. **WS-7 `schemas.py` additions (~250 lines, "not yet wired"):** review suggests splitting into their own PR. This is a commit-strategy question, moot until the user decides how to commit this tree at all.
4. **Commit strategy for the whole tree:** review says "not ready to merge as one unit." Candidate split: (a) data-layer + backup work, (b) WS-8 component library, (c) docs, (d) `demo/app/` pending decision 1.

---

### Task 1: Add `submission_student_id` to the Repository seam (Critical #1)

**Files:**
- Modify: `original/repository.py` (Protocol ~line 70, `SqliteRepository` ~line 328, `PostgresRepository` ~line 697)
- Test: already written — `tests/test_repository_contract.py::TestManifests` (lines 494–503), `tests/test_correction_authz.py`, `tests/context/test_admin_endpoints.py`

**Interfaces:**
- Consumes: `store.submission_student_id(submission_id: str) -> str | None` (exists, `original/store.py:591`)
- Produces: `Repository.submission_student_id(submission_id: str) -> str | None` — called by `original/api.py:2942` (`_repo().submission_student_id(...)`)

The failing tests already exist — this is TDD with the red phase pre-supplied.

- [ ] **Step 1: Confirm the tests fail for the expected reason**

Run: `.venv/bin/python -m pytest tests/test_repository_contract.py::TestManifests -q`
Expected: 3 FAILED (`test_submission_student_id_*[sqlite]`) with `AttributeError: 'SqliteRepository' object has no attribute 'submission_student_id'`

- [ ] **Step 2: Add the method to the `Repository` Protocol**

In `original/repository.py`, in the Protocol's Manifests section, directly after `def manifest_stats(...) -> dict: ...` (~line 68):

```python
    def submission_student_id(self, submission_id: str) -> str | None: ...
```

- [ ] **Step 3: Implement on `SqliteRepository`**

Directly after `SqliteRepository.manifest_stats` (~line 328):

```python
    def submission_student_id(self, submission_id: str) -> str | None:
        return store.submission_student_id(submission_id)
```

- [ ] **Step 4: Add the `PostgresRepository` stub**

In the `PostgresRepository` Manifests section, after its `manifest_stats` stub (~line 697), matching the class's existing stub style:

```python
    def submission_student_id(self, submission_id):
        self._todo("submission_student_id")
```

- [ ] **Step 5: Run all tests broken by Critical #1**

Run: `.venv/bin/python -m pytest tests/test_repository_contract.py tests/test_correction_authz.py tests/context/test_admin_endpoints.py -q`
Expected: the 15 previously-failing tests PASS. (`tests/test_baseline_requests.py`'s 1 remaining failure is Task 2's.)

---

### Task 2: Correct the false-premise "P3 landed" test and comments (Critical #2)

**Files:**
- Modify: `tests/test_baseline_requests.py:117-141` (`test_postgres_repo_is_no_longer_a_skeleton`)
- Modify: `tests/test_repository_contract.py:1-24` (module docstring) and `:41-46` (`BACKENDS` comment)

**Interfaces:**
- Consumes: `repository.PostgresRepository` (still a `_todo` skeleton — 56 stubs), `repository.get_repository()` / `reset_repository()`
- Produces: nothing new — pins current state so WS-6 P3 flips it deliberately.

WS-6 P3 (repository parity) has NOT shipped; every `PostgresRepository` method raises `NotImplementedError`. The test and two comment blocks claim otherwise.

- [ ] **Step 1: Replace the test with one asserting the real (skeleton) state**

In `tests/test_baseline_requests.py`, replace the entire `test_postgres_repo_is_no_longer_a_skeleton` method (lines 117–139, through the final `repository.reset_repository()`) with:

```python
    def test_postgres_repo_is_still_a_skeleton(self):
        """
        WS-6 P3 (repository parity) has NOT landed yet: every
        ``PostgresRepository`` method still raises NotImplementedError via
        ``_todo(...)``, and ``get_repository()`` stays hard-wired to SQLite
        for every environment. This pins the current P2 state so P3 flips
        this test deliberately rather than the gap going unnoticed.
        """
        import original.repository as repository

        pg = repository.PostgresRepository()
        with pytest.raises(NotImplementedError):
            pg.db_path()

        repository.reset_repository()
        assert isinstance(repository.get_repository("pilot"), repository.SqliteRepository)
        repository.reset_repository()
```

(`import pytest` already exists at line 13.)

- [ ] **Step 2: Fix the module docstring in `tests/test_repository_contract.py`**

Replace the sentence `the same assertions run unchanged against ``SqliteRepository`` and, as of WS-6 P3, ``PostgresRepository``` with:

```
the same assertions run unchanged against ``SqliteRepository`` today and,
once WS-6 P3 lands, ``PostgresRepository``
```

- [ ] **Step 3: Fix the `BACKENDS` comment**

Replace the comment block above `BACKENDS` (starting `# WS-6 P3: "postgres" is real now (PostgresRepository has zero NotImplementedError`) with:

```python
# WS-6 P3 has NOT landed: PostgresRepository is still an all-``_todo()``
# skeleton, so the "postgres" parametrization is staged ahead of P3. It only
# runs when a Postgres instance is actually reachable (see
# `_postgres_available()` below) and will fail until P3 ships — CI has no
# postgres service container yet, so it self-skips everywhere today.
# `pytest -m "not postgres"` deselects this parametrization entirely.
```

- [ ] **Step 4: Verify**

Run: `.venv/bin/python -m pytest tests/test_baseline_requests.py tests/test_repository_contract.py -q`
Expected: 0 failed (postgres params skip).

---

### Task 3: Escape the shared LIKE pattern in the audit-log fallback (Important, security)

**Files:**
- Modify: `original/store.py:602-608` (`submission_student_id`) and `original/store.py:1194-1198` (`put_correction` fallback)
- Test: `tests/test_repository_contract.py::TestManifests` (add one test)

**Interfaces:**
- Consumes: `store._escape_like(s: str) -> str` (`store.py:28`) — pair with `LIKE ? ESCAPE '\'` per its docstring.
- Produces: unchanged signatures; literal-safe matching for submission ids containing `%`/`_`.

- [ ] **Step 1: Write the failing regression test**

Append to `TestManifests` in `tests/test_repository_contract.py` (after `test_submission_student_id_unknown_returns_none`):

```python
    def test_submission_student_id_treats_wildcards_as_literal(self, repo):
        # '_' in an unescaped LIKE pattern matches any single character, so
        # looking up "sub_1" would mis-attribute this "subX1" audit row.
        repo.log_audit(action="score", student_id="sem:eve", details={"submission_id": "subX1"})
        assert repo.submission_student_id("sub_1") is None
        repo.log_audit(action="score", student_id="sem:dan", details={"submission_id": "sub_1"})
        assert repo.submission_student_id("sub_1") == "sem:dan"
```

- [ ] **Step 2: Run it to verify it fails**

Run: `.venv/bin/python -m pytest "tests/test_repository_contract.py::TestManifests::test_submission_student_id_treats_wildcards_as_literal[sqlite]" -q`
Expected: FAIL — first assert returns `"sem:eve"` instead of `None`.

- [ ] **Step 3: Fix both call sites identically**

In `original/store.py`, in **both** `submission_student_id` (~line 604) and `put_correction`'s fallback (~line 1195), change the query and parameter from:

```python
                "SELECT student_id FROM audit_log WHERE action = 'score' "
                "AND details_json LIKE ? ORDER BY created_at DESC LIMIT 1",
                (f'%"submission_id": "{submission_id}"%',),
```

to:

```python
                "SELECT student_id FROM audit_log WHERE action = 'score' "
                r"AND details_json LIKE ? ESCAPE '\' ORDER BY created_at DESC LIMIT 1",
                (f'%"submission_id": "{_escape_like(submission_id)}"%',),
```

- [ ] **Step 4: Verify the new test passes and nothing regressed**

Run: `.venv/bin/python -m pytest tests/test_repository_contract.py tests/context/test_admin_endpoints.py tests/test_correction_authz.py tests/test_store_tenants.py -q`
Expected: 0 failed.

- [ ] **Step 5: Checkpoint — full backend suite**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: **0 failed** (first fully-green run; Tasks 1–3 clear all 16 review failures). Record the exact `N passed, M skipped` line — Task 8 needs it.

---

### Task 4: Modal — portal, inert background, focus fallback, scrim token (Important + 2 Minors)

**Files:**
- Modify: `app/src/components/Modal.tsx`, `app/src/components/Modal.css:6`, `app/src/tokens.css` (add one token)
- Test: `app/src/components/Modal.test.tsx` (add one test)

**Interfaces:**
- Consumes: `createPortal` from `react-dom` (already a dependency).
- Produces: same `ModalProps` API — no consumer-visible change; overlay now renders as a direct child of `document.body`, background body children get the `inert` attribute while open.

- [ ] **Step 1: Write the failing test**

Add to `app/src/components/Modal.test.tsx` inside `describe('Modal', ...)`:

```tsx
  it('portals to document.body and marks background content inert while open', () => {
    const { rerender } = render(
      <div data-testid="background">
        <button type="button">Background action</button>
        <Modal open onClose={() => {}} title="Portaled">
          <p>Content</p>
        </Modal>
      </div>,
    );
    const dialog = screen.getByRole('dialog');
    // The dialog escapes its React parent via a portal…
    expect(screen.getByTestId('background')).not.toContainElement(dialog);
    // …background content is inert, the dialog is not.
    expect(screen.getByTestId('background').closest('[inert]')).not.toBeNull();
    expect(dialog.closest('[inert]')).toBeNull();

    rerender(
      <div data-testid="background">
        <button type="button">Background action</button>
        <Modal open={false} onClose={() => {}} title="Portaled">
          <p>Content</p>
        </Modal>
      </div>,
    );
    expect(screen.getByTestId('background').closest('[inert]')).toBeNull();
  });
```

- [ ] **Step 2: Run it to verify it fails**

Run: `cd app && npx vitest run src/components/Modal.test.tsx`
Expected: the new test FAILS (`toContainElement` — dialog currently renders inline); the 7 existing tests PASS.

- [ ] **Step 3: Rework `Modal.tsx`**

Three changes: portal the overlay to `document.body`, add an inert effect (declared *before* the focus effect so its cleanup runs first and focus can be restored to a no-longer-inert trigger), and `tabIndex={-1}` on the panel so the initial-focus fallback can actually take focus.

Replace `Modal.tsx`'s imports and component body as follows (docstring, `FOCUSABLE_SELECTOR`, `ModalProps`, Escape handler, and `handleTabTrap` stay unchanged):

```tsx
import { useEffect, useId, useRef } from 'react';
import { createPortal } from 'react-dom';
import type { KeyboardEvent as ReactKeyboardEvent, ReactNode } from 'react';
import './Modal.css';
```

Inside the component, add `overlayRef` next to the existing refs:

```tsx
  const overlayRef = useRef<HTMLDivElement>(null);
```

Add this effect ABOVE the existing focus effect (cleanups run in declaration order, so inert must be removed before focus is restored to the trigger):

```tsx
  // Make everything behind the dialog inert while it is open — Tab-trapping
  // alone doesn't stop a screen reader's browse/virtual cursor from reading
  // background content (WAI-ARIA APG dialog pattern). Only marks elements
  // this effect itself made inert, so pre-existing inert content (or a
  // second stacked modal) is left alone on cleanup.
  useEffect(() => {
    if (!open) return;

    const overlay = overlayRef.current;
    const madeInert: Element[] = [];
    for (const el of Array.from(document.body.children)) {
      if (el === overlay || el.hasAttribute('inert')) continue;
      el.setAttribute('inert', '');
      madeInert.push(el);
    }
    return () => {
      for (const el of madeInert) el.removeAttribute('inert');
    };
  }, [open]);
```

Replace the `return (...)` JSX with a portal, adding `ref={overlayRef}` and `tabIndex={-1}`:

```tsx
  return createPortal(
    <div className="modal-overlay" ref={overlayRef}>
      {/* eslint-disable-next-line jsx-a11y/no-noninteractive-element-interactions --
          role="dialog" is a window role, not a widget role, so jsx-a11y treats it as
          non-interactive — but attaching the Tab-trap keydown handler to the dialog
          container is exactly the WAI-ARIA APG dialog pattern. */}
      <div
        ref={panelRef}
        className={['modal-panel', className].filter(Boolean).join(' ')}
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        tabIndex={-1}
        onKeyDown={handleTabTrap}
      >
        <button
          type="button"
          className="modal-close-button"
          aria-label="Close dialog"
          onClick={onClose}
        >
          <span aria-hidden="true">×</span>
        </button>
        <h2 id={titleId} className="modal-title">
          {title}
        </h2>
        {children}
      </div>
    </div>,
    document.body,
  );
```

Also extend the component docstring with one sentence: `Portaled to document.body so the fixed overlay cannot be captured by an ancestor containing block (transform/filter/contain), with background content made inert while open.`

- [ ] **Step 4: Tokenize the scrim**

In `app/src/tokens.css`, under the `/* ── Structure ── */` group (after `--shadow-md`):

```css
  --overlay-scrim: rgba(0, 0, 0, 0.45);
```

In `app/src/components/Modal.css:6`, change `background: rgba(0, 0, 0, 0.45);` to `background: var(--overlay-scrim);`.

- [ ] **Step 5: Verify all Modal tests + workspace checks pass**

Run: `cd app && npx vitest run src/components/Modal.test.tsx && npm run lint && npm run typecheck`
Expected: 8/8 PASS (including the axe test), lint and typecheck clean.

---

### Task 5: FileDrop — `:has()` focus fallback + dragleave guard (Important + Minor)

**Files:**
- Modify: `app/src/components/FileDrop.css:55-57`, `app/src/components/FileDrop.tsx:52-54`
- Test: `app/src/components/FileDrop.test.tsx` (add one test)

**Interfaces:**
- Consumes: `--focus-ring` token; existing DOM (`label.file-drop-zone > input.file-drop-input`).
- Produces: same `FileDropProps` API.

- [ ] **Step 1: Add the CSS fallback**

In `app/src/components/FileDrop.css`, directly after the `.file-drop-zone:has(.file-drop-input:focus-visible)` rule:

```css
/* Fallback for browsers without :has() (the rule above): :focus-within is
   universally supported and never leaves keyboard focus invisible. Slightly
   broader — it also rings on mouse-initiated focus — which is why the
   precise :has(:focus-visible) rule remains the primary. @supports gates it
   so :has()-capable browsers don't get the broader behavior. */
@supports not selector(.a:has(.b)) {
  .file-drop-zone:focus-within {
    box-shadow: var(--focus-ring);
  }
}
```

- [ ] **Step 2: Write the failing dragleave test**

Add to `app/src/components/FileDrop.test.tsx`:

```tsx
  it('ignores dragleave events bubbling from the hidden input', () => {
    render(<FileDrop label="Upload files" onFiles={() => {}} />);
    const input = screen.getByLabelText('Upload files');
    const zone = input.closest('label')!;

    fireEvent.dragOver(zone);
    expect(zone.className).toContain('file-drop-zone--dragging');

    // Leaving *into a child* of the zone must not clear the dragging state…
    fireEvent.dragLeave(zone, { relatedTarget: input });
    expect(zone.className).toContain('file-drop-zone--dragging');

    // …leaving the zone entirely must.
    fireEvent.dragLeave(zone, { relatedTarget: document.body });
    expect(zone.className).not.toContain('file-drop-zone--dragging');
  });
```

(If the file doesn't already import `fireEvent`, extend the `@testing-library/react` import.)

- [ ] **Step 3: Run to verify it fails**

Run: `cd app && npx vitest run src/components/FileDrop.test.tsx`
Expected: new test FAILS on the second assertion (state cleared by bubbled dragleave).

- [ ] **Step 4: Guard `handleDragLeave`**

In `app/src/components/FileDrop.tsx`, replace:

```tsx
  function handleDragLeave() {
    setIsDragging(false);
  }
```

with:

```tsx
  function handleDragLeave(event: DragEvent<HTMLLabelElement>) {
    // dragleave fires when the pointer moves onto a child (the hidden
    // input); only clear when actually leaving the zone.
    if (event.currentTarget.contains(event.relatedTarget as Node | null)) return;
    setIsDragging(false);
  }
```

- [ ] **Step 5: Verify**

Run: `cd app && npx vitest run src/components/FileDrop.test.tsx && npm run lint && npm run typecheck`
Expected: all PASS, clean.

---

### Task 6: Chart — document the `aria-hidden` children constraint (Important)

**Files:**
- Modify: `app/src/components/Chart.tsx` (the `children` prop JSDoc and/or component docstring)

**Interfaces:** none — comment-only.

The review notes `aria-hidden="true"` on `children` (`Chart.tsx:54`) becomes an axe `aria-hidden-focus` violation if a chart ever embeds a focusable element. Today's usage is static SVG only; adding an escape-hatch prop now would be YAGNI. Make the constraint explicit instead.

- [ ] **Step 1: Add the constraint to the JSDoc**

On the `children` prop in `ChartProps` (or the component docstring if children has no JSDoc), add:

```tsx
  /**
   * The visual chart (static SVG/markup). Rendered aria-hidden — the
   * accessible experience is the `summary`/`details` props — so children
   * MUST NOT contain focusable/interactive elements (an embedded legend
   * button or tooltip trigger would be an aria-hidden-focus violation).
   * Interactive charts need an API change here first, not a workaround.
   */
```

- [ ] **Step 2: Verify nothing broke**

Run: `cd app && npx vitest run src/components/Chart.test.tsx && npm run typecheck`
Expected: PASS.

---

### Task 7: Spacing scale in `tokens.css` + mechanical sweep (Important)

**Files:**
- Modify: `app/src/tokens.css` (add scale), all 8 component stylesheets: `Chart.css`, `DataTable.css`, `FileDrop.css`, `Heading.css`, `LabeledInput.css`, `Modal.css`, `NavList.css`, `Timer.css`

**Interfaces:**
- Produces: `--space-2/-6/-8/-10/-12/-16/-24/-32` tokens (value-named; zero visual change by construction).

- [ ] **Step 1: Add the scale to `tokens.css`**

After the `/* ── Structure ── */` group:

```css
  /* ── Spacing — value-named scale (--space-N = Npx). Components must use
     these for padding/margin/gap/inset instead of inventing raw px. ── */
  --space-2: 2px;
  --space-6: 6px;
  --space-8: 8px;
  --space-10: 10px;
  --space-12: 12px;
  --space-16: 16px;
  --space-24: 24px;
  --space-32: 32px;
```

- [ ] **Step 2: Sweep the 8 component stylesheets**

In every `padding`, `margin`, `gap`, `top`, `right`, `bottom`, `left` declaration, replace each px value with its token (e.g. `padding: 8px 12px` → `padding: var(--space-8) var(--space-12)`; `gap: 6px` → `gap: var(--space-6)`). **Leave untouched:** `border*` widths, `border-radius` (already tokenized), `0` values, `1px` values (optical/hairline, e.g. `bottom: 1px`), and anything inside `.sr-only`-style clip patterns (`width/height: 1px; margin: -1px` in `FileDrop.css`'s `.file-drop-input`).

- [ ] **Step 3: Verify the sweep is complete and non-destructive**

Run: `cd app && grep -nE "(padding|margin|gap|top|right|bottom|left)[^:]*: *[0-9]{2,}px" src/components/*.css src/tokens.css | grep -v "space-"`
Expected: no output (all ≥2-digit px spacing is tokenized; tokens.css definitions don't match the pattern).

Run: `cd app && npm test && npm run lint`
Expected: 73 existing + new tests PASS, lint clean.

---

### Task 8: Docs/CI truth pass (Critical #4 + Recommendation 7 + small doc fixes)

**Files:**
- Modify: `docs/implementation/WS-9-e2e-release-hygiene.md:84`, `docs/implementation/WS-6-postgres-convergence.md` (~lines 110, 113, 118), `docs/implementation/WS-7-api-refactor.md` (~line 88), `CLAUDE.md:21`, `README.md:406`, `.github/workflows/test.yml` (~line 64 comment), `tests/test_schemas.py:13-17`, `.gitignore`

**Interfaces:** none — docs/comments only. **Precondition:** Tasks 1–3 done and `pytest tests/ -q` shows 0 failed.

- [ ] **Step 1: Measure the real numbers (do not trust the review or the old docs)**

```bash
.venv/bin/python -m pytest tests/ --collect-only -q | tail -1                                   # expect ~880
.venv/bin/python -m pytest tests/ validation/test_tier10_optional.py --collect-only -q | tail -1 # expect ~883
grep -c "body: dict" original/api.py                                                             # expect 10
grep -c "^def " original/store.py; grep -c "^def [^_]" original/store.py                        # for WS-6 §110 counts
.venv/bin/python -m pytest tests/ validation/test_tier10_optional.py --cov=original --cov-report=term-missing -q 2>&1 | grep -E "api\.py|store\.py|TOTAL"
```

Record: collected counts, full-suite wall time, and the measured `api.py` / `store.py` coverage %.

- [ ] **Step 2: Update the test-count claims**

- `CLAUDE.md:21`: replace `(~720 tests as of 2026-07-09, ~80s; ~722 with validation/test_tier10_optional.py)` with the measured numbers, e.g. `(~880 tests as of 2026-07-16, ~80s; ~883 with validation/test_tier10_optional.py)` (use actual counts/time from Step 1).
- `README.md:406`: replace `~720 tests as of 2026-07-09` with the measured count and today's date (keep the "treat this as approximate" sentence).

- [ ] **Step 3: Fix the CI coverage comment**

In `.github/workflows/test.yml`, in the comment above the pytest step, replace `api.py sits at 61% and store.py at 80%` with the Step-1 measured values (review measured api.py at 68–69% — confirm, don't copy). Do not change `--cov-fail-under=72` unless the measured TOTAL is below it (it isn't expected to be).

- [ ] **Step 4: Correct WS-9's acceptance claim (Critical #4a)**

`docs/implementation/WS-9-e2e-release-hygiene.md:84` claims the professor-journey spec is green. Re-verify it against the now-fixed code:

```bash
cd demo/bluebook && npx playwright test e2e/professor-journey.spec.mjs
```

(Check `playwright.config.mjs` first — if it needs a live server and one is already running, use it; NEVER kill/restart an existing server. If the spec cannot be run in this environment, the doc claim must be downgraded, not left standing.)

- If it passes: amend the bullet with `— re-verified green 2026-07-16 after the submission_student_id repository-seam fix (it was failing at the correction step until then).`
- If it fails or can't run: change `- [x]` to `- [ ]` and state exactly what was observed.

- [ ] **Step 5: Correct WS-6's stale checklist (Critical #4b + Important)**

In `docs/implementation/WS-6-postgres-convergence.md`:
- Line ~110 (`Repository Protocol covers all 55 public functions ... 56 methods total`): recount using Step 1's `grep -c "^def [^_]" original/store.py` and the Protocol method count; update both numbers (adding `submission_student_id` in Task 1 makes these 56 public functions / 57 methods, if the grep agrees).
- The tenancy bullet (~line 113, `NOT DONE (P2, not started): store.py still uses the "{tenant_id}:{local_id}" string-prefix convention`): update to reflect what actually landed — e.g. `PARTIAL (P2 landed): SQLAlchemy models + original/db/tenancy.py round-trip shim exist; the tenant_id column/FK/composite-unique swap in the live store has not happened — store.py still uses the "{tenant}:{local}" prefix convention.`
- The alembic bullet (`NOT DONE (P2): alembic/versions/ still holds only the original 7 v1 migrations; no archive, no fresh baseline`): update to `- [x] ... DONE (P2): the 7 v1 migrations are archived under alembic/versions/archived_v1/ and 008_postgres_convergence_baseline.py is the single fresh head.`
- Line ~118 (flags-OFF bullet, `...and the full suite is green`): re-verify with the Task-3 Step-5 result and amend: `re-verified green 2026-07-16 (a broken correction-endpoint seam had 16 tests failing until the submission_student_id fix).`

- [ ] **Step 6: Small doc/comment corrections**

- `docs/implementation/WS-7-api-refactor.md` (~line 88): the bullet says `grep -c "body: dict" ... currently returns **9**`; actual is **10**. Update the number and note one match is a non-endpoint occurrence at `api.py:2620`.
- `tests/test_schemas.py:13-17`: remove `BaselineConfidence.von_neumann_entropy` from the docstring's dropped-fields list (`api.py` now includes it at ~line 2294); the list should read `(AuthorshipSignal.quantum_fidelity, AuthorshipSignal.fidelity_conformal_pvalue, EntanglementAnomaly.expected_correlation/observed_product, TensionArcResult.paragraph_arcs)`. Reword "fields that _to_response does silently drop today" to "fields that were silently dropped when this test was written (von_neumann_entropy has since been wired up)".
- `.gitignore`: add a line `demo/bluebook/e2e/fixtures/.tenants-created.log` (interrupted e2e runs leave it behind).

- [ ] **Step 7: Verify docs weren't broken**

Run: `.venv/bin/python -m pytest tests/test_schemas.py -q`
Expected: PASS (docstring edit only).

---

### Task 9: Final verification (superpowers:verification-before-completion)

**Files:** none — verification only.

- [ ] **Step 1: Full backend suite, exact CI command**

Run: `.venv/bin/python -m pytest tests/ validation/test_tier10_optional.py -q`
Expected: **0 failed** (XFAIL/XPASS acceptable), skips only from optional deps/postgres.

- [ ] **Step 2: Full `app/` workspace checks**

Run: `cd app && npm test && npm run lint && npm run typecheck`
Expected: all tests pass (73 pre-existing + ~3 new), lint and typecheck clean.

- [ ] **Step 3: Report**

Summarize for the user: which review items were fixed (Criticals 1, 2, 4; Importants: LIKE-escaping, Modal, FileDrop, Chart doc, spacing scale, doc/CI numbers; Minors: scrim token, panel tabIndex, dragleave guard, .gitignore), the before/after test counts, and the four open decisions from the "Decisions required" section — especially Critical #3 (`demo/app/`), which blocks any merge plan.

---

## Explicitly deferred (noted, not planned)

Review Minors judged not worth changes this pass: `Timer.tsx` milestone-template duplication (cosmetic, speculative), missing `index.ts` barrel (review itself says "fine at this size"), `LabeledInput.test.tsx` `required`-attribute assertion, `DataTable` `onSortChange`/empty-state (feature work for R3), `restore_drill.py` `SANITY_TABLES` expansion (WS-6 P4 territory), `institution.py` `tenant_slug` ADR note, regression tests for the three `BUGS_FOUND_2026-07-08` fixes (WS-8's harness job), `/tenants/*` disclosure regression test (already tracked by `SECURITY_REAUDIT_2026-07-09.md`).
