# 05 — Frontend, end-to-end, and accessibility tests

Scope: `demo/bluebook/` (the live Bluebook React app, esbuild, committed
bundle), `demo/app/` (a second React frontend, 13 entry points, committed
bundles), `demo/*.html` (professor, operator, student, admin, lab, onboard,
playground, prototypes), and `app/` (the Vite/TS rebuild target with vitest).

Strong today: ~72 Playwright tests on chromium against a *real* pilot-mode
server booted with `--skip-seed`; per-worker tenant provisioning over REST with
`storageState`; a bundle byte-identity check; axe scans on 13 Bluebook screens,
all blocking; a two-server login-lockout run. `app/` has jest-axe unit tests and
a 100 % branch threshold.

Weak today: five of twelve routers have no browser flow; `demo/app/` has no
tests and no staleness check; five `demo/*.html` pages have zero coverage;
`test_prototype_accessibility_contract.py` greps source strings and is not an
accessibility test; no visual regression; no non-chromium browser; no mobile
viewport despite `parked.html` being a phone page.

---

## 1. Unit tests for Bluebook JSX

`demo/bluebook/` has no vitest. Its JSX is tested only through the browser,
which is slow and coarse for component logic (form gating, toggle states, the
timer, the seal retry state machine). Add vitest + testing-library +
`jest-axe` mirroring `app/`'s setup (same versions, same
`vite.config.ts` thresholds pattern, thresholds starting at the measured
number and ratcheting). Targets, in order of logic density:

1. `Exam.jsx` — timer expiry auto-seal, draft restore from storage, seal retry
   on transient failure, total failure preserves draft (these have e2e specs;
   unit tests make them fast and let e2e cover only the browser-specific
   parts: fullscreen, paste blocking, key interception).
2. `NewExam.jsx` — form gating and `ToggleRow` states.
3. `Results.jsx` — `ExpandedRow` / `CorrectionPanel`, which the a11y spec
   scans *collapsed* and so never gates.
4. `components.jsx` — shared primitives, axe per component.

Do not unit-test `app.jsx` routing; the e2e smoke covers it.

## 2. `demo/app/` — the untested second frontend

Thirteen committed `*.bundle.js` files with no test script and no CI freshness
check. Two decisions to make, and a test for whichever wins:

- **If it is live** (served to anyone in pilot): add the same byte-identity
  step `bundle-e2e` runs for Bluebook, and a smoke spec per entry point (page
  loads, no console errors, no 404 assets — copy `smoke.spec.mjs`). Add axe.
- **If it is dormant** (ADR-006 territory): add it to
  `tests/test_dormant_core_reachability.py`'s pattern — a test that the pilot
  server returns 404 for its entry points under `ORIGINAL_ENV=pilot`, so it
  cannot quietly become live.

Until decided, the register carries it as a blocking unknown; the audit could
not determine which it is from the code.

## 3. Playwright coverage by router

| Router | Browser flow today | Add |
|---|---|---|
| `health` | smoke | — |
| `auth` | login/logout/lockout/bound-student routing | the student passwordless login *form* (fixtures bypass it over REST); `/auth/me` reflected in the header |
| `bluebook` | full exam loop, proctor, corrections | `GET /bluebook/launch` actually followed by a browser (today `auth.spec` fakes its consequence via `localStorage`) |
| `students` | list/get | data-inventory view; `DELETE` student with confirm dialog and post-delete 404 |
| `students_baseline` | upload, readiness, request-baseline | the pending-requests queue a professor works through |
| `students_scoring` | score, blend | explanation text matches the API payload field-for-field |
| `tenants` | CRUD, isolation | `/tenants/{id}/stats` panel |
| `proctor` | full | — |
| `lti_routes` | **none** | keep API-level (pytest); add *one* browser test that a signed launch lands on the exam page with the right candidate — decision gate in WS-9 said API-level suffices; the hole is the redirect-to-page step, which only a browser sees |
| `imports` | **none** | Turnitin CSV upload journey; Canvas list→preview→import with the server pointed at a mocked Canvas (`httpx.MockTransport` cannot cross a process boundary — start a tiny fake Canvas HTTP server in the Playwright `globalSetup`) |
| `me` | **none** | student voice/work/formation pages; assert no forbidden field is rendered (the browser twin of §02 §3) |
| `admin` | corrections + audit read-back | calibration-lab journey: list runs → suggestions → apply → tuned-thresholds history reflects it. The review found Apply is a no-op (scoring reads `constants.ACTION_THRESHOLDS`). The e2e should assert the *observable* promise: after Apply, a rescored known text changes tier. Red until fixed. |

## 4. Accessibility — make the contract test honest

`tests/test_prototype_accessibility_contract.py` asserts substrings exist in
`demo/prototypes/*.js`. It will pass on any file containing the words. Either:

- rename it `test_prototype_source_markers.py` with a docstring saying it is a
  source-marker check, not an accessibility test; **and**
- add `demo/prototypes/index.html` and the five uncovered `demo/*.html` pages
  to a Playwright axe spec (`a11y-legacy.spec.mjs`, `@a11y`, non-blocking for
  one month, then blocking per page as they are fixed — the WS-9 ramp pattern).

For Bluebook, extend `a11y.spec.mjs` to scan Results *expanded* and the
correction panel *open*, which are the two states currently ungated.

Keep `settle()` — the mid-fade phantom-contrast failure it prevents is real.

## 5. Visual regression — gated, not banned

WS-9 said "not before the React markup stabilises". Markup has been stable
since the Bluebook corrections UI landed (2026-07-23). Policy:

- Chromium-only, three screens: professor Dashboard, Results (one row
  expanded), student Exam (pre-Begin). `toHaveScreenshot` with
  `maxDiffPixelRatio: 0.01`, fonts pinned via the bundled CSS.
- Snapshots committed under `demo/bluebook/e2e/__screenshots__/`, updated by
  a documented `npx playwright test --update-snapshots` in the PR that changes
  the UI. The diff is reviewed like code.
- Non-blocking for the first month. If it flakes more than twice, drop the
  screen rather than widen the tolerance.

## 6. Browser and viewport matrix

- Add a WebKit project for `smoke.spec.mjs` and `exam-flow.spec.mjs` only.
  Seminary students on iPads are the likeliest non-Chrome population and the
  fullscreen / paste-block behaviour is engine-specific.
- Add a `mobile` project (Pixel 5 emulation) running only `proctor.spec.mjs`'s
  `parked.html` cases — that page is designed for a phone and has never been
  tested at phone width.

## 7. Cross-process fakes for e2e

The unit suite's best pattern (transport-seam fakes) does not reach Playwright
because the server is a separate process. Add `demo/bluebook/e2e/fixtures/
fake-canvas.mjs`: a ten-line Node HTTP server started in `globalSetup`,
serving recorded Canvas JSON (the same literals `test_canvas_live.py` uses,
moved to a shared `tests/fixtures/canvas/*.json` so both suites read one
source). The Original server gets `CANVAS_BASE_URL=http://localhost:<port>`.
This is also the seam §06 of the integration doc needs for recorded fixtures.

## 8. Bundle hygiene

- Keep the byte-identity CI step for Bluebook. Extend it to `demo/app/` per
  §2's decision.
- Add a test that `bluebook.bundle.js` contains no `localhost`, no
  `console.log(` outside the dev-tools gate, and no source-map URL pointing
  off-origin (the smoke spec checks CDN refs; these are the other three
  common leaks).

## 9. Acceptance for this slice

- Bluebook vitest exists with axe per component and a ratcheting threshold.
- `demo/app/` is either byte-checked + smoke-tested or proven unreachable in
  pilot.
- Every router with a user-facing flow has ≥1 spec; `imports` and `me` are
  no longer zero.
- The a11y contract test is renamed or replaced; Results-expanded is scanned.
- Visual regression runs non-blocking on three screens.
