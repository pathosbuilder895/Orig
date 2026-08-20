# Branch Coverage Part 7 — app/ Frontend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close every closable branch gap in `app/src` (measured 2026-08-17: **91.32% branch, 179/196, 17 missing**), annotate the small set of genuinely unreachable defensive branches with justified `v8 ignore` markers, and then lock the result in with enforced vitest coverage thresholds so it can never silently regress.

**Architecture:** No production-code changes except `v8 ignore` comment annotations. Each task adds targeted tests to the existing colocated `*.test.tsx` files (same RTL + `fireEvent` + `vi` + `jest-axe` idioms already in use). The final task flips `app/vite.config.ts`'s deliberately-absent `thresholds` on and points CI's app job at `test:coverage`.

**Tech Stack:** React 19, Vitest + @vitest/coverage-v8, @testing-library/react, jsdom, jest-axe.

**Index plan:** `docs/superpowers/plans/2026-08-17-branch-coverage-index.md`

## Global Constraints

- **All commands run from `app/`**: `cd app && npx vitest run --coverage` (or `npm run test:coverage`).
- **Baseline (2026-08-17, vitest v8 provider):** Statements 95.04% (211/222), Branches **91.32% (179/196)**, Functions 94.44% (51/54), Lines 96.95% (191/197). 75 tests in 10 files, all passing.
- **Never weaken an existing assertion** to make a new test pass.
- **Fake timers**: opt in per-test with `vi.useFakeTimers()` and rely on the existing `afterEach(() => vi.useRealTimers())` — never a shared `beforeEach` (jest-axe hangs under fake timers; see the comment at the top of `Timer.test.tsx`).
- **`v8 ignore` annotations require a justification comment** explaining *why* the branch is unreachable, not just the marker.
- **Commit style:** `Add ...` / `Fix ...`, one focused commit per task, co-author line `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.

## Measured branch-gap inventory (lcov BRDA, 2026-08-17)

| File | Line | Branch | Verdict |
|---|---|---|---|
| `App.tsx` | — | no branches; 0% statements (never rendered by any test) | Task 1 |
| `Timer.tsx` | 49 | `hours > 0` true arm of `formatClock` | Task 2 |
| `Timer.tsx` | 58 | `hours > 0` + `hours === 1` singular/plural arms of `formatSpoken` | Task 2 |
| `Timer.tsx` | 115 | `(remaining ?? 0)` null arm (countdown with no `durationSeconds`) | Task 3 |
| `Timer.tsx` | 156 | `durationSeconds` falsy while `mode === 'countdown'` | Task 3 |
| `Timer.tsx` | 130 | `!expiredRef.current` false arm (expiry effect re-run) | Task 4 |
| `Timer.tsx` | 127 | `remaining === null` after the line-126 guard | unreachable — Task 6 |
| `Modal.tsx` | 64 | `document.activeElement instanceof HTMLElement` false arm | Task 5 |
| `Modal.tsx` | 127 | Tab-trap fall-through (Tab pressed mid-cycle, no wrap) | Task 5 |
| `Modal.tsx` | 86 | zero-focusable fallback to panel | unreachable — Task 6 |
| `Modal.tsx` | 113 | `!panel` guard in `handleTabTrap` | unreachable — Task 6 |
| `Modal.tsx` | 116 | `focusable.length === 0` in `handleTabTrap` | unreachable — Task 6 |
| `NavList.tsx` | 45 | `ArrowRight` / `ArrowLeft` cases and `default` case of the key switch | Task 7 |
| `NavList.tsx` | 38 | `items.length === 0` guard in `focusItem` | unreachable — Task 6 |
| `FileDrop.tsx` | 63 | `files.length > 0` false arm (drop with no files) | Task 8 |
| `DataTable.tsx` | 47 | `!column` (sort key no longer in `columns`) | Task 9 |

"Unreachable" claims are argued per-branch in Task 6 — do not take them on faith; re-verify each argument against the source before annotating.

---

### Task 1: App.tsx smoke test

**Files:**
- Create: `app/src/App.test.tsx`
- Test: `app/src/App.test.tsx`

**Interfaces:**
- Consumes: `App` default export from `app/src/App.tsx` (a zero-prop component).
- Produces: nothing used by later tasks.

- [ ] **Step 1: Write the failing-by-absence test**

```tsx
import { render, screen } from '@testing-library/react';
import { axe } from 'jest-axe';
import { describe, expect, it } from 'vitest';
import App from './App';

describe('App', () => {
  it('renders the workspace placeholder inside the main landmark', () => {
    render(<App />);
    const main = screen.getByRole('main');
    expect(main).toHaveAttribute('id', 'main');
    expect(
      screen.getByRole('heading', { level: 1, name: /Original — app\/ workspace/ }),
    ).toBeInTheDocument();
  });

  it('has zero axe violations', async () => {
    const { container } = render(<App />);
    expect(await axe(container)).toHaveNoViolations();
  });
});
```

- [ ] **Step 2: Run it**

Run: `cd app && npx vitest run src/App.test.tsx`
Expected: 2 passed.

- [ ] **Step 3: Confirm the coverage effect**

Run: `cd app && npx vitest run --coverage 2>&1 | grep "App.tsx"`
Expected: `App.tsx` statements column moves 0 → 100.

- [ ] **Step 4: Commit**

```bash
git add app/src/App.test.tsx
git commit -m "Add App.tsx smoke test — first render coverage for the app entry component"
```

---

### Task 2: Timer hour-scale formatting branches (lines 49, 58)

**Files:**
- Modify: `app/src/components/Timer.test.tsx` (append inside the existing `describe('Timer', …)`)

**Interfaces:**
- Consumes: `Timer` and the file's existing `advance(seconds)` helper.
- Produces: nothing used by later tasks.

- [ ] **Step 1: Add the failing tests**

`formatClock` renders `H:MM:SS` only when `hours > 0`; `formatSpoken` pluralizes on `hours === 1`. Neither arm is exercised — every existing test uses sub-hour durations.

```tsx
  it('renders hour-scale countdowns as H:MM:SS', () => {
    render(<Timer durationSeconds={7200} />);
    expect(screen.getByText('2:00:00')).toBeInTheDocument();
    expect(screen.getByLabelText('2 hours remaining')).toBeInTheDocument();
  });

  it('speaks a single hour in the singular', () => {
    render(<Timer durationSeconds={3660} />);
    expect(screen.getByText('1:01:00')).toBeInTheDocument();
    expect(screen.getByLabelText('1 hour, 1 minute remaining')).toBeInTheDocument();
  });
```

- [ ] **Step 2: Run the Timer file**

Run: `cd app && npx vitest run src/components/Timer.test.tsx`
Expected: all pass (existing 12 + new 2). If the spoken strings differ, read `formatSpoken` in `Timer.tsx:52-64` and fix the *assertion* to the actual composition rule — the seconds part is only spoken when `hours === 0 && minutes < 5`.

- [ ] **Step 3: Verify the branches closed**

Run: `cd app && npx vitest run --coverage 2>&1 | grep "Timer.tsx"`
Expected: Timer's missed-branch count drops by the two formatting sites (re-extract exact lines from `app/coverage/lcov.info` `BRDA` records if the summary is ambiguous).

- [ ] **Step 4: Commit**

```bash
git add app/src/components/Timer.test.tsx
git commit -m "Add Timer hour-scale formatting branch tests"
```

---

### Task 3: Timer countdown-without-duration branches (lines 115, 156)

**Files:**
- Modify: `app/src/components/Timer.test.tsx`

- [ ] **Step 1: Add the failing tests**

`<Timer />` with no props is a countdown (`mode` defaults to `'countdown'`) with `durationSeconds` undefined: `remaining` is `null` (line 112-114), the display falls back through `remaining ?? 0` (115), and the low-time `fraction` short-circuits to `null` on falsy `durationSeconds` (156). No milestone/expiry effect may fire (guard at 126).

```tsx
  it('countdown with no duration pins the display at 00:00 and never fires milestones', () => {
    vi.useFakeTimers();
    const onExpire = vi.fn();
    render(<Timer onExpire={onExpire} />);
    advance(30);
    expect(screen.getByText('00:00')).toBeInTheDocument();
    expect(screen.getByLabelText('less than a second remaining')).toBeInTheDocument();
    expect(screen.getByRole('status')).toHaveTextContent('');
    expect(onExpire).not.toHaveBeenCalled();
  });

  it('a zero-second duration disables milestones and low-time styling rather than dividing by zero', () => {
    vi.useFakeTimers();
    render(<Timer durationSeconds={0} />);
    advance(2);
    expect(screen.getByText('00:00')).toBeInTheDocument();
    expect(screen.getByRole('status')).toHaveTextContent('');
  });
```

- [ ] **Step 2: Run and verify**

Run: `cd app && npx vitest run src/components/Timer.test.tsx`
Expected: all pass. Note the no-duration countdown keeps *ticking* internally (the line-102 stop-guard needs `durationSeconds != null`) — the display stays 00:00 because `remaining` is clamped, which is exactly what these tests pin.

- [ ] **Step 3: Commit**

```bash
git add app/src/components/Timer.test.tsx
git commit -m "Add Timer no-duration and zero-duration countdown branch tests"
```

---

### Task 4: Timer expiry-effect re-run branch (line 130)

**Files:**
- Modify: `app/src/components/Timer.test.tsx`

- [ ] **Step 1: Add the failing test**

The `!expiredRef.current` false arm only runs when the expiry effect re-executes *after* expiry. Deps are `[remaining, durationSeconds, mode, onExpire]`; after expiry `remaining` is frozen at 0, so hand in a **new `onExpire` identity** to force a re-run and assert one-shot semantics held.

```tsx
  it('does not re-announce or re-fire expiry when the effect re-runs after expiring', () => {
    vi.useFakeTimers();
    const first = vi.fn();
    const second = vi.fn();
    const { rerender } = render(<Timer durationSeconds={2} onExpire={first} />);
    advance(2);
    expect(first).toHaveBeenCalledTimes(1);

    rerender(<Timer durationSeconds={2} onExpire={second} />);
    expect(second).not.toHaveBeenCalled();
    expect(first).toHaveBeenCalledTimes(1);
    expect(screen.getByRole('status')).toHaveTextContent('Time has expired.');
  });
```

- [ ] **Step 2: Run and verify**

Run: `cd app && npx vitest run src/components/Timer.test.tsx`
Expected: all pass.

- [ ] **Step 3: Commit**

```bash
git add app/src/components/Timer.test.tsx
git commit -m "Add Timer expiry idempotence test for the post-expiry effect re-run branch"
```

---

### Task 5: Modal non-HTMLElement focus capture (line 64) and Tab pass-through (line 127)

**Files:**
- Modify: `app/src/components/Modal.test.tsx`

- [ ] **Step 1: Add the failing tests**

Line 64's false arm needs `document.activeElement` to not be an `HTMLElement` at open (real cases: nothing focused → `null` in a detached state, or focus inside an SVG). Mock the getter for one render. Line 127's uncovered path is Tab pressed while focus is on neither boundary — the trap must fall through *without* preventing default.

```tsx
  it('opens cleanly when nothing focusable held focus beforehand', () => {
    const spy = vi.spyOn(document, 'activeElement', 'get').mockReturnValue(null);
    const { unmount } = render(
      <Modal open onClose={() => {}} title="No prior focus">
        <button type="button">Inside</button>
      </Modal>,
    );
    expect(screen.getByRole('dialog')).toBeInTheDocument();
    spy.mockRestore();
    unmount(); // close path must not throw despite the null capture
  });

  it('lets Tab pass through when focus is between the trap boundaries', () => {
    render(
      <Modal open onClose={() => {}} title="Trap">
        <button type="button">Middle</button>
        <button type="button">Last</button>
      </Modal>,
    );
    // Focusables inside the panel: [built-in close button, Middle, Last].
    screen.getByRole('button', { name: 'Middle' }).focus();
    const notPrevented = fireEvent.keyDown(screen.getByRole('dialog'), { key: 'Tab' });
    expect(notPrevented).toBe(true); // fireEvent returns false iff preventDefault fired
    const notPreventedBack = fireEvent.keyDown(screen.getByRole('dialog'), {
      key: 'Tab',
      shiftKey: true,
    });
    expect(notPreventedBack).toBe(true);
  });
```

- [ ] **Step 2: Run and verify**

Run: `cd app && npx vitest run src/components/Modal.test.tsx`
Expected: all pass. If `vi.spyOn(document, 'activeElement', 'get')` throws (jsdom defines the getter on `Document.prototype`), fall back to `Object.defineProperty(document, 'activeElement', { value: null, configurable: true })` and `delete (document as any).activeElement` in cleanup — assert the same behavior either way.

- [ ] **Step 3: Commit**

```bash
git add app/src/components/Modal.test.tsx
git commit -m "Add Modal branch tests for null prior focus and mid-cycle Tab pass-through"
```

---

### Task 6: Annotate the five argued-unreachable defensive branches

**Files:**
- Modify: `app/src/components/Modal.tsx:86,113,116`
- Modify: `app/src/components/NavList.tsx:38`
- Modify: `app/src/components/Timer.tsx:127`

**Interfaces:**
- Produces: the exact ignore-comment syntax later verified by Task 10's threshold flip.

- [ ] **Step 1: Re-verify each unreachability argument against current source**

- `Modal.tsx:86` (`focusable.length > 0 ? … : panel`) and `Modal.tsx:116` (`focusable.length === 0`): the panel *always* contains the built-in close button (rendered unconditionally at line ~150), which matches `button:not([disabled])` in `FOCUSABLE_SELECTOR`. Zero-focusable is impossible without deleting the close button.
- `Modal.tsx:113` (`!panel`): `handleTabTrap` is the panel's own `onKeyDown` — it cannot fire before the ref is attached.
- `NavList.tsx:38` (`items.length === 0`): `focusItem` is only reachable from a rendered link's keydown handler; zero items renders zero links.
- `Timer.tsx:127` (`remaining === null`): the line-126 guard already returned unless `mode === 'countdown' && durationSeconds != null`, and under exactly those conditions lines 111-114 always produce a number. The branch exists to narrow the TS type, not to handle a runtime state.

If any argument no longer holds (the code moved), STOP and write the covering test instead of annotating.

- [ ] **Step 2: Add `v8 ignore` annotations with justifications**

Example shape (repeat at each of the five sites, adapting the wording):

```tsx
    const focusable = Array.from(panel.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR));
    /* v8 ignore next 4 -- the built-in close button always matches
       FOCUSABLE_SELECTOR, so an empty focusable list is unreachable without
       deleting it; kept as defense-in-depth for a future refactor. */
    if (focusable.length === 0) {
      event.preventDefault();
      return;
    }
```

For a ternary arm (Modal 86), use `/* v8 ignore next */` on the fallback line; for `Timer.tsx:127`, note it is TS narrowing.

- [ ] **Step 3: Run the suite and confirm 100% branch**

Run: `cd app && npx vitest run --coverage`
Expected: all tests pass; Branches column reads **100%** (or, if a residual line appears, extract it from `app/coverage/lcov.info` BRDA records and either test it or return to Step 1 for it).

- [ ] **Step 4: Commit**

```bash
git add app/src/components/Modal.tsx app/src/components/NavList.tsx app/src/components/Timer.tsx
git commit -m "Annotate argued-unreachable defensive branches with justified v8 ignores"
```

---

### Task 7: NavList horizontal-arrow and unhandled-key branches (line 45)

**Files:**
- Modify: `app/src/components/NavList.test.tsx`

- [ ] **Step 1: Add the failing tests**

The switch handles ArrowDown/ArrowRight and ArrowUp/ArrowLeft as pairs, but only the vertical members are tested; the `default` arm (unhandled key → no `preventDefault`) is also untaken.

```tsx
  it('ArrowRight and ArrowLeft mirror ArrowDown and ArrowUp', () => {
    render(<NavList items={items} aria-label="Course sections" />);
    const baselines = screen.getByRole('link', { name: 'Baselines' });
    baselines.focus();

    fireEvent.keyDown(baselines, { key: 'ArrowRight' });
    expect(document.activeElement).toBe(screen.getByRole('link', { name: 'Imports' }));

    fireEvent.keyDown(screen.getByRole('link', { name: 'Imports' }), { key: 'ArrowLeft' });
    expect(document.activeElement).toBe(baselines);
  });

  it('leaves unhandled keys alone (no preventDefault, no focus move)', () => {
    render(<NavList items={items} aria-label="Course sections" />);
    const baselines = screen.getByRole('link', { name: 'Baselines' });
    baselines.focus();
    const notPrevented = fireEvent.keyDown(baselines, { key: 'a' });
    expect(notPrevented).toBe(true);
    expect(document.activeElement).toBe(baselines);
  });
```

- [ ] **Step 2: Run and verify**

Run: `cd app && npx vitest run src/components/NavList.test.tsx`
Expected: all pass.

- [ ] **Step 3: Commit**

```bash
git add app/src/components/NavList.test.tsx
git commit -m "Add NavList horizontal-arrow and unhandled-key branch tests"
```

---

### Task 8: FileDrop empty-drop branch (line 63)

**Files:**
- Modify: `app/src/components/FileDrop.test.tsx`

- [ ] **Step 1: Add the failing test**

A drop whose `dataTransfer.files` is empty must not invoke `onFiles` (the `files.length > 0` false arm). Reuse the file's existing zone-lookup idiom (`input.closest('label')`).

```tsx
  it('ignores a drop that carries no files', () => {
    const onFiles = vi.fn();
    render(<FileDrop label="Upload files" onFiles={onFiles} />);
    const zone = screen.getByLabelText('Upload files').closest('label')!;

    fireEvent.drop(zone, { dataTransfer: { files: [] } });

    expect(onFiles).not.toHaveBeenCalled();
    expect(zone.className).not.toContain('file-drop-zone--dragging');
  });
```

(If `vi` is not yet imported in this file, add it to the existing vitest import.)

- [ ] **Step 2: Run and verify**

Run: `cd app && npx vitest run src/components/FileDrop.test.tsx`
Expected: all pass.

- [ ] **Step 3: Commit**

```bash
git add app/src/components/FileDrop.test.tsx
git commit -m "Add FileDrop empty-drop branch test"
```

---

### Task 9: DataTable stale-sort-key branch (line 47)

**Files:**
- Modify: `app/src/components/DataTable.test.tsx`

- [ ] **Step 1: Add the failing test**

`if (!column) return rows;` fires when sort state names a column that a later render no longer provides. Reachable: click-sort a column, then rerender with that column removed.

```tsx
  it('falls back to the original row order when the sorted column disappears', () => {
    const { rerender } = render(
      <DataTable columns={columns} rows={students} getRowKey={(row) => row.id} />,
    );
    const nameHeader = screen.getByRole('columnheader', { name: /Name/ });
    fireEvent.click(within(nameHeader).getByRole('button'));
    expect(nameColumnCells()).toEqual(['Amir', 'Priya', 'Zoe']);

    const withoutName = columns.filter((column) => column.key !== 'name');
    rerender(<DataTable columns={withoutName} rows={students} getRowKey={(row) => row.id} />);
    // Sort state still says "name" — the guard must fall back to input order.
    const scores = screen
      .getAllByRole('row')
      .slice(1)
      .map((row) => within(row).getAllByRole('cell')[0].textContent);
    expect(scores).toEqual(['88', '95', '72']);
  });
```

- [ ] **Step 2: Run and verify**

Run: `cd app && npx vitest run src/components/DataTable.test.tsx`
Expected: all pass.

- [ ] **Step 3: Commit**

```bash
git add app/src/components/DataTable.test.tsx
git commit -m "Add DataTable stale-sort-key branch test"
```

---

### Task 10: Enforce the ratchet — vitest thresholds + CI coverage run

**Files:**
- Modify: `app/vite.config.ts` (the `coverage` block at lines 16-29)
- Modify: `.github/workflows/test.yml` (the `app` job's "Unit + axe tests" step)

**Interfaces:**
- Consumes: the closed gaps from Tasks 1-9 (run this task LAST).

- [ ] **Step 1: Measure the final floor**

Run: `cd app && npx vitest run --coverage`
Expected: 100% branches; note the exact statements/functions/lines percentages.

- [ ] **Step 2: Add thresholds**

In `app/vite.config.ts`, replace the "No `thresholds` here on purpose" comment block with real thresholds — branches at 100, the other three at the measured value rounded *down* to the nearest integer (never above what Step 1 printed):

```ts
      coverage: {
        provider: 'v8',
        reporter: ['text', 'html', 'lcov'],
        reportsDirectory: './coverage',
        include: ['src/**/*.{ts,tsx}'],
        // Ratchet, not aspiration: set from the measured floor of the
        // 2026-08 branch-coverage effort (part 7). Raise when real coverage
        // rises; never lower to admit a regression.
        thresholds: {
          branches: 100,
          statements: 97,   // ← replace with Step 1's measured floor
          functions: 96,    // ← replace with Step 1's measured floor
          lines: 98,        // ← replace with Step 1's measured floor
        },
        exclude: [
          '**/*.test.{ts,tsx}', // test files themselves
          '**/*.d.ts', // type-only declarations (incl. src/api/schema.d.ts, generated)
          'src/test/**', // test setup/harness
          'src/main.tsx', // entry bootstrap — createRoot().render() only
        ],
      },
```

- [ ] **Step 3: Point CI at the coverage run**

In `.github/workflows/test.yml`, change the app job's test step so the thresholds actually gate merges:

```yaml
      - name: Unit + axe tests (with coverage thresholds)
        run: cd app && npm run test:coverage
```

- [ ] **Step 4: Verify both directions**

Run: `cd app && npm run test:coverage`
Expected: PASS. Then temporarily set `branches: 101`, rerun, and confirm it FAILS (the gate is live); revert to 100.

- [ ] **Step 5: Commit**

```bash
git add app/vite.config.ts .github/workflows/test.yml
git commit -m "Enforce app coverage thresholds and run them in CI"
```

---

## Self-Review Notes

- Task 6 runs *after* Tasks 1-5 close the reachable Modal/Timer gaps, so its "residual = only the five argued sites" check is meaningful; Tasks 7-9 are independent of it, and Task 10 must run last.
- All test code above follows the exact idioms already present in each target file (checked against the current sources on 2026-08-17): `advance()` helper and per-test fake timers in `Timer.test.tsx`, `within(header).getByRole('button')` in `DataTable.test.tsx`, `input.closest('label')` in `FileDrop.test.tsx`.
- The spoken-string assertions in Task 2 were derived from `formatSpoken`'s actual composition rules (`Timer.tsx:52-64`), including the sub-5-minute seconds cutoff.
