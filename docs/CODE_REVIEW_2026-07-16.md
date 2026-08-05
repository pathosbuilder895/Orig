# Code Review — Uncommitted Working-Tree Changes (2026-07-16)

**Scope:** the uncommitted state of this working tree (unstaged modifications to tracked
files + untracked new files) as of 2026-07-16, on top of local HEAD `0e00754`
(itself 4 commits ahead of `origin/main` at `835b655`). Nothing described here is
committed anywhere yet.

**Method:** four independent code-review passes run in parallel, each scoped to a
coherent area, each read-only against the live working tree (no git state mutated),
each instructed to actually run the relevant tests rather than assume:

1. Data layer & security — Postgres/tenancy models, migrations, backup/restore tooling
2. WS-8 React component library (`app/src/components/`)
3. `demo/app/` — an unplanned, newly-discovered ~79-file directory
4. Test suite additions, validation harness, docs, CI config, Bluebook UI

**Excluded from review** (junk/artifacts found alongside the real changes, not source):
`.venv.broken-py39/` (29k files, a stale interpreter dir), `Original-handoff.zip`,
`Original_Business_Plan.docx`, `explainer-screenshot.png`, `"original 2/"` (a
Finder-duplicate directory), `.pytest_run.txt`, `demo/seed.db`, generated
`*.bundle.js`/`.map` output.

**Full suite result on this working tree:** `772 passed, 16 failed, 87 skipped, 5 xpassed`
(`.venv/bin/python -m pytest tests/ -q`). All 16 failures trace to one root cause —
see Critical #1.

---

## Summary

| Area | Verdict | Headline issue |
|---|---|---|
| Data layer (Postgres/tenancy/backup) | With fixes | Missing `Repository` method breaks the correction endpoint everywhere |
| WS-8 component library | With fixes | Solid; two a11y robustness gaps in `FileDrop`/`Modal` |
| `demo/app/` (new/unplanned) | **No** — needs a decision | Uncoordinated duplicate of both the live UI and the sanctioned WS-8 migration |
| Tests, docs, CI, Bluebook UI | With fixes | Excellent test/doc discipline, but two docs assert a false "green" state |

**Overall: not ready to merge as one unit.** The blocking items are Critical #1 (a
genuinely broken endpoint) and Critical #3 (an architectural fork that needs a human
decision, not a code fix).

---

## Strengths

- **Postgres/tenancy porting (WS-6 P2)** is careful, non-destructive work: every field
  in the 8 new model files traces back to the exact `store.py` behavior it mirrors,
  with explicit call-outs of intentional deviations (e.g. `manifest.py` keeps
  `created_at` as `Text` because it's caller-supplied and can be `""`).
  `original/db/tenancy.py` is a clean, pure, round-trip-safe shim over the existing
  `"{tenant}:{local}"` id scheme. `original/db/postgres_session.py` lazily constructs
  its engine (importing `original.repository` never opens a PG pool) and is
  dialect-defensive about pool kwargs. The alembic baseline
  (`008_postgres_convergence_baseline.py`) is a clean fresh baseline with the 7 stale
  v1 migrations correctly archived and a single resolvable head.
- **Backup/restore tooling** (`scripts/backup_offbox.py`, `restore_drill.py`,
  `export_backup_offbox.sh`) is genuinely solid FERPA-conscious ops work: default-off
  gating, a hand-rolled stdlib SigV4 signer (no new dependency), secrets never logged,
  and a restore drill that correctly treats an empty `student_profiles` as failure.
  `tests/test_backup_offbox.py` (26 tests) passes and exercises the real SigV4
  canonical-request construction, not mocks.
- **WS-8 component library** is fully plan-aligned — every file in
  `docs/implementation/WS-8-react-migration.md`'s §R2 list is present and nothing
  unplanned was added. `tokens.css` matches WS-4's canonical numbers exactly (alpha
  0.62 ink, `#5d6773` muted text, 0.55/0.65 hairline alphas, one global
  `:focus-visible` ring, one global `prefers-reduced-motion` block — zero
  component-local duplicates). Real semantics throughout: `DataTable` is an actual
  `<table>`, `NavList` implements real APG roving-tabindex, `FileDrop` exposes a
  genuinely focusable `<input type="file">` instead of `display:none`, `Modal` has a
  real focus trap + Escape + focus-restore, `Chart`'s `summary` prop is required at
  the type level. 73/73 tests pass, plus clean typecheck and lint. No `any` escapes.
- **New WS-5 tests** (`test_bluebook_api.py`, `test_scoring_flags.py`) are real
  behavioral tests — CRUD, tenant-scoping, 404/422 paths, the full scoring-flag
  matrix against a pinned byte-identical Phase-1 baseline — not tautological ones.
  All 66 tests across the reviewed test files pass individually.
- **Documentation discipline in this diff is unusually rigorous**: every
  `WS-1`…`WS-9` doc was rewritten with "verified against the working tree" markers
  and explicit DONE/NOT DONE/PARTIAL grading, and several specific claims
  (WS-9's "38 tests across 9 spec files," WS-7's `ScoringConfig` claim, ADR-006's
  repository-method count) were independently spot-checked and held up exactly.
  `docs/SECURITY_REAUDIT_2026-07-09.md` is a genuinely good self-audit that surfaces
  a real cross-tenant disclosure gap in `/tenants/*` and honestly admits no
  regression test exists for it yet. All three bugs in
  `docs/BUGS_FOUND_2026-07-08.md` are actually fixed in this diff.
- The `demo/app/` code, whatever its process problems (see Critical #3), is honest
  about its own gaps — pages with no real backend endpoint say so in-code rather than
  faking data — and correctly separates staff vs. student auth bridges to avoid a
  principal-token leak.

---

## Critical (must fix)

### 1. The correction endpoint is broken in every environment
**Files:** `original/store.py:591`, `original/repository.py:27,241,620`, `original/api.py:2942`

This slice adds `submission_student_id()` to `store.py`, but it was never added to
the `Repository` Protocol, `SqliteRepository`, or `PostgresRepository`. The new
`submit_correction` handler at `api.py:2942` (landed in the immediately-preceding
commit `901fb74`) calls `_repo().submission_student_id(submission_id)`
unconditionally on every `POST /submissions/{id}/correct`, which raises
`AttributeError` every time.

This is the confirmed root cause of **15 of the 16 currently-failing tests**: all 7
in `tests/context/test_admin_endpoints.py` (`TestCorrectionEndpoint`,
`TestAdminCorrectionsListEndpoint`), all 5 in `tests/test_correction_authz.py`, all 3
in `tests/test_repository_contract.py::TestManifests`. One reviewer independently
confirmed this by running `demo/bluebook/e2e/professor-journey.spec.mjs` against a
live server on current code and watching it fail at the correction step with the same
`AttributeError`.

**Fix:** add `submission_student_id` to the `Repository` Protocol, implement it on
`SqliteRepository` as a thin call to `store.submission_student_id()`, and add a
`_todo(...)` stub on `PostgresRepository` consistent with its current skeleton state.

### 2. A test asserts a false premise about `PostgresRepository`
**File:** `tests/test_baseline_requests.py::TestRepositorySeamWidened::test_postgres_repo_is_no_longer_a_skeleton`, also `tests/test_repository_contract.py`'s new `BACKENDS`/`_postgres_available()` machinery

The test (and its docstring) claims "WS-6 P3 replaced every `_todo(...)` stub with a
real SQLAlchemy implementation." This is not true in this diff — `PostgresRepository`
is untouched; every method still calls `self._todo(op)`, and the class's own
docstring still says "Skeleton." Per `docs/implementation/WS-6-postgres-convergence.md`,
P3 (repository parity) is a distinct, later phase from P2 (schema/models — this
slice's actual scope). This isn't an intentional `xfail` marker; it's a test rewritten
to describe work that hasn't shipped.

**Fix:** revert the test to asserting the current (still-skeleton) state, or actually
ship P3 in this slice.

### 3. `demo/app/` is an uncoordinated second frontend migration that duplicates the live UI
**Files:** `demo/app/` (79 files), `original/api.py:288-310`, `run.py:76-94` (esp. line 92), `docs/implementation/WS-8-react-migration.md`, `frontend/original-dashboard.html`, `frontend/NOT-THE-PILOT.md`

This is a large, self-contained, already-bundled (esbuild → IIFE, no CDN, mirroring
`demo/bluebook/build.mjs`) React rewrite of the admin/professor/operator surface —
but it is **not** the sanctioned WS-8 effort. `docs/implementation/WS-8-react-migration.md`
specifies a Vite + React 18 + TypeScript workspace at the repo-root `app/` with a
generated OpenAPI client and vitest+axe+ESLint/jsx-a11y — none of which this tree
uses. It traces its visual origin to `frontend/original-dashboard.html`, inside the
tracked-but-explicitly-dead v1 frontend tree (`frontend/NOT-THE-PILOT.md`: "not
maintained").

Concretely:
- `demo/app/{admin,operator,student,index}.html` **duplicate `demo/{admin,operator,student,index}.html` by name** — 14 pages total re-implementing most of the live admin/professor surface. This is exactly the dead-parallel-surface pattern ADR-006 already had to clean up once (finding F1/F5), now recurring at larger scale.
- `run.py:92` mounts all of `demo/` recursively via `StaticFiles(directory=frontend_dir, html=True)`. The instant this directory is committed, `demo/app/admin.html` etc. become live-servable at `/app/*` — nothing links to them today, but nothing blocks them either.
- `original/api.py:288-310`'s `_DEMO_ONLY_STATICS`/`_STAFF_ONLY_PREFIXES` — the gating WS-7 step 5 relies on to keep `operator.html`/`admin-context.html` non-public — has no awareness of `/app/*` paths.
- **Zero `aria-`, zero `role=`, zero `htmlFor`** anywhere across all 14 pages (grep-confirmed), and multiple keyboard-inaccessible `<div onClick>` elements (`Students.jsx:159-161`, `Flagged.jsx:84-86`, `StudentDetail.jsx:245`). This directly regresses the accessibility bar the project's own WS-4/WS-8 workstreams exist to raise.
- A third, independent design-token/CSS system (`dashboard.css`'s own palette), unrelated to WS-8's `tokens.css`.
- `Dashboard.jsx:19-45` re-implements `fmtScore`/`fmtDate`/`mapPool` locally instead of importing the identical versions already correctly exported from `util.js` — drift risk.

The bundles themselves are current (all 14 `.bundle.js`/`.map` pairs share one mtime,
2026-07-11 14:57:55, postdating every source edit), so this isn't stale leftover —
it's a finished, working, but unauthorized parallel build.

**This needs a decision, not a fix**: which migration path is real — the sanctioned
`app/` (Vite+TS) scaffold, or this `demo/app/` tree — before any code-level cleanup
makes sense. If `demo/app/` is kept, it needs gating updates in `api.py` and a full
accessibility pass before it can be considered at parity with the rest of this
codebase's UI.

### 4. Two plan docs assert a false "green" state
**Files:** `docs/implementation/WS-9-e2e-release-hygiene.md:85`, `docs/implementation/WS-6-postgres-convergence.md:118`

Both assert the professor-journey E2E spec / correction flow are landed and passing.
Both are false because of Critical #1 — independently confirmed by re-running the
full suite and by directly executing the Playwright spec against live code.

**Fix:** downgrade both claims to NOT DONE until #1 is fixed, or fix #1 first and
re-verify before merge.

---

## Important (should fix)

**WS-8 components:**
- `FileDrop.css:39-57` — the only visible focus indicator depends on a bare
  `:has()` selector with no fallback. This is the one component built specifically
  for keyboard access (W13); betting its entire visible-focus contract on one
  selector with no fallback is risky in any browser without `:has()` support.
- `Modal.tsx` — not portaled to `document.body` and doesn't mark background content
  `inert`/`aria-hidden` while open. Tab is trapped, but a screen-reader user in
  browse/virtual-cursor mode can still read behind the dialog (WAI-ARIA APG expects
  outside content to be made inert, not just Tab-trapped). Also: without a portal,
  `.modal-overlay`'s `position: fixed` will stop covering the viewport if any
  ancestor establishes a new containing block (`transform`/`filter`/`contain`) — a
  likely regression once real nested layouts (WS-8 R3) use this.
- `Chart.tsx:54` — `aria-hidden="true"` is applied unconditionally to `children`.
  Fine for today's static-SVG usage, but becomes a real `aria-hidden-focus` axe
  violation the moment a chart embeds any focusable element (legend button, tooltip
  trigger).
- `app/src/tokens.css` has no spacing scale — color/radius/shadow/type are all
  tokenized, but every component invented its own one-off px values (6/8/10/12/16/24
  scattered across 8 CSS files). Worth closing before more R3 components each pick
  their own numbers.

**Data layer / security:**
- **Unescaped `LIKE` pattern** in the new `submission_student_id`
  (`original/store.py:591-612`) — builds its audit-log fallback query via raw
  f-string interpolation (`f'%"submission_id": "{submission_id}"%'`) without the
  existing `_escape_like()` helper (`store.py:28`). Copy-pasted from a pre-existing
  instance at `store.py:1196` (`put_correction`), so not a new risk class — but since
  this new function is now the tenant-isolation check for corrections, a `%`/`_` in a
  submission id has real (if narrow) consequence. Fix both call sites together.
- `docs/implementation/WS-6-postgres-convergence.md`'s acceptance checklist is stale
  relative to this slice (still says "no archive, no fresh baseline" / "tenancy NOT
  DONE" — both now true/landed).
- `original/schemas.py` picked up ~250 lines of WS-7 typed request/response models
  that are explicitly "not yet wired" — an unrelated workstream's code bundled into
  this slice with zero current call sites. Not a bug, but easy to forget to wire up,
  and muddies this diff's scope.

**Tests / docs / CI:**
- `.github/workflows/test.yml:67` — comment says `api.py` coverage is 61%; measured
  and WS-5's own acceptance section both show 68–69% post-WS-5. Conflates
  before/after numbers.
- `CLAUDE.md:21` / `README.md:406` — claim "~720 tests"; actual collected count is
  **880** (883 with tier10-optional). ~20% undercount, more than rounding drift.
- `demo/bluebook/components.jsx:306` adds `BB_API.fileCorrection()` but it's never
  called anywhere (`grep -rn fileCorrection demo/bluebook/*.jsx` finds only the
  definition) — dead/half-landed feature; `Results.jsx` still has no
  correction-filing UI.
- `tests/test_schemas.py:13-17`'s module docstring claims
  `BaselineConfidence.von_neumann_entropy` "is dropped by `_to_response` today," but
  `api.py:2294` already includes it. Docstring should only list fields still
  actually dropped (`quantum_fidelity`, `fidelity_conformal_pvalue`,
  `expected_correlation`/`observed_product`, `paragraph_arcs`).

---

## Minor (nice to have)

- `Modal.css:6` — the one hardcoded color (`rgba(0,0,0,0.45)` scrim) in an otherwise
  fully-tokenized set; extract to a `--overlay-scrim` token.
- `Modal.tsx:51-54` — initial-focus fallback silently no-ops because the panel
  `<div>` has no `tabIndex={-1}`; currently masked by the close button always being
  present, but a latent trap if a future modal disables all its controls.
- `FileDrop.tsx:52-54` — `handleDragLeave` clears `isDragging` even on bubbled events
  from the hidden `<input>` child (cosmetic flicker only; keyboard path unaffected).
- `Timer.tsx:37-38` — the 10% and 5% milestone messages share an identical template;
  if both round to the same spoken string on a short countdown, the live region may
  not re-announce.
- No `app/src/components/index.ts` barrel file yet — fine at this size, worth adding
  before broad R3 adoption.
- `LabeledInput.test.tsx` never asserts the native `required` attribute is actually
  present on the `<input>` (only the visual asterisk + axe pass are covered).
- `DataTable` has no `onSortChange` callback and no empty-rows message — will matter
  once professor/admin pages need server-paginated rosters.
- `scripts/restore_drill.py`'s `SANITY_TABLES` checks only 4 of 16+ tables; consider
  adding `submission_manifests`/`corrections` — the tables this slice's own models
  represent.
- `original/db/models/institution.py`'s new `tenant_slug` duplicates `subdomain`'s
  value for every live-app-created row (acceptable per its own documented reasoning;
  worth an ADR follow-up note).
- `docs/implementation/WS-7-api-refactor.md:89` — cites `grep -c "body: dict"
  original/api.py` → 9; actual is 10 (misses a non-endpoint match at `api.py:2620`).
- `demo/bluebook/e2e/fixtures/api-setup.mjs`'s new `.tenants-created.log` isn't in
  `.gitignore` — harmless on a completed run (teardown deletes it, verified), but an
  interrupted run leaves it as untracked cruft.
- No automated regression coverage for the three `BUGS_FOUND_2026-07-08.md` fixes in
  `professor.html`/`operator.html`/`admin.html` — understandable given these legacy
  static pages have no test harness (that's WS-8's job), but worth a tracking note.
- The `/tenants/*` cross-tenant disclosure gap `docs/SECURITY_REAUDIT_2026-07-09.md`
  found has no regression test yet — already transparently disclosed by the doc
  itself as an open follow-up, so this is a heads-up, not a hidden defect.

---

## Recommendations (priority order)

1. Fix Critical #1 (`submission_student_id` on the Repository seam) — small,
   well-understood, unblocks 15 of 16 failures on a live endpoint.
2. Revert or correct Critical #2's false test premise.
3. Get an explicit decision on Critical #3 (`demo/app/` vs. the sanctioned `app/`
   scaffold) before any further frontend work lands on either.
4. Re-verify and correct the WS-9/WS-6 doc claims (Critical #4) once #1 is fixed.
5. Close the two WS-8 a11y robustness gaps (`FileDrop` focus fallback, `Modal`
   portal/inertness) before R3 pages start depending on them broadly.
6. Fix the shared unescaped-`LIKE` pattern in `submission_student_id` +
   `put_correction`.
7. Regenerate the stale test-count and coverage figures in `CLAUDE.md`/`README.md`/CI
   config via their own documented commands.
8. Consider splitting the unrelated WS-7 `schemas.py` additions into their own PR.

---

## Assessment

**Ready to merge as one unit? No.** The Postgres/backup work and the WS-8 component
library are each independently **"ready with fixes"** — small, well-understood
changes, not architectural rework. `demo/app/` is **not** mergeable as-is; it needs a
human decision on which frontend migration is canonical before its code-quality
issues are even worth fixing. The two false "done" doc claims should be corrected
regardless of which other fixes land first, since they're actively misleading about
current state.
