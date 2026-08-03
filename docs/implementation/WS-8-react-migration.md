# WS-8 — Frontend → React migration

> **⚖️ AMENDED by [ADR-008](../adr/008-ws8-frontend-convergence.md) (Accepted 2026-08-02) — read this first.**
> The direction below is re-scoped: **Bluebook (`demo/bluebook/` + esbuild) is
> the permanent exam-app frontend and does NOT migrate into `app/`.** `app/` +
> the R2 component library serve the legacy static pages only (`professor.html`,
> `student.html`, …) — the pages R2's tokens were actually derived from. R1
> ("Bluebook fold-in") is closed as **superseded, not done** — Bluebook met R1's
> real goals (ESM, bundled React, dev/prod parity) via its own pipeline. The
> `@a11y` promotion gate is measurement-based and already blocking on all 13
> Bluebook screens (PR #122). R3 remains live but targets the statics only;
> before its first page: the second committed-`dist` freshness gate and
> `run.py` static mount ADR-008's Consequences require. Sections below are kept
> as written for their execution detail; where they say "one workspace" or
> describe folding Bluebook in, ADR-008 governs.

> Part of the [Master Implementation Plan](../AUDIT_2026-07-06.md) (Audit §9). Refs are a 2026-07-07 snapshot — resolve each cited `path:line` by its **named symbol** via [ANCHORS.md](ANCHORS.md); the tree is under active edit and line numbers drift.
> **Findings:** W5–W8, W11–W15 (durable a11y), F5 (retire dead pages) · **Effort:** ~2 months part-time · **Depends on:** WS-4 hotfix first (§9 table) · **Unblocks:** the VPAT (WS-3 / D15, writable from axe evidence not hope), and WS-9's professor-side E2E coverage.

## Objective
Replace the 11 static `demo/*.html` pages (~12,500 lines of inline CSS/JS; `professor.html` 5,049, `student.html` 2,010) with one Vite + React 18 + TypeScript workspace where **accessibility is the acceptance criterion of every PR** (axe in CI = zero serious/critical). This is the *durable* home for the accessibility findings WS-4 patched in raw HTML/JSX — the primitives get built once, correctly, and every page inherits them. Done = every live page served from React at its current path, WS-4's hotfixes superseded by accessible-by-construction components, and F5's dead pages retired.

**This is a WRAPPER workstream.** The detailed design lives in **audit §11 "Frontend → React migration sketch" (lines 657–677)** — target shape, deployment constraint, and phases R0–R4. This file is the *execution checklist*: owners, order, entry gates, decision gates, and the per-PR acceptance bar. Read §11 for the rationale; read this to run it.

## Prerequisites & dependencies
- **HARD GATE — WS-4 must be live before R3 begins.** §11 line 677 and the §9 table both state it: accommodated students cannot wait ~2 months for a rewrite. WS-4 lands the interim a11y hotfix (aria-labels, `role="alert"`/`status`, keyboard targets, label sweep, contrast tokens, `ToggleRow` role) in the *existing* HTML/JSX. R0–R2 (scaffold + Bluebook fold-in + component library) may proceed in parallel with WS-4; **R3 page rewrites may not start until WS-4 is shipped and its axe scan is green** (WS-4 accept: zero critical/serious on student.html, professor.html, exam flow).
- **R0 depends on WS-7 step 2** (pydantic request/response models for the 8–10 dict-body endpoints + `response_model` on the rest — A10/S8/S7). Those models make `/openapi.json` truthful, which makes the `openapi-typescript`-generated client honest. Generating the TS client before WS-7 step 2 yields types that lie. Coordinate: R0's client-gen task consumes WS-7's OpenAPI output.
- **R0 consumes WS-2's ESLint config.** §13 (lines ~795–800) specifies the ESLint flat config with `eslint-plugin-react`, `-react-hooks`, and **`eslint-plugin-jsx-a11y`**, landed by WS-2 in the existing `demo/bluebook/` CI job. §13 states it "carries directly into the R0 workspace." Reuse it verbatim; do not re-author.
- **WS-9 (E2E) is the per-page acceptance gate.** §12's Playwright specs (currently 13 tests / 2 specs, student-flow only) are what proves each migrated page still works. Its professor-side coverage (T7) partially depends on R3 landing. Each R1/R3 PR must keep the existing specs green and add coverage for the new page.
- **Shared-finding ownership.** W1, W2, W3, W4, W9, W10 have an *interim* slice owned by WS-4 (raw HTML/JSX) and a *durable* slice owned here (React primitives). This file owns only the durable rebuild; do not re-do WS-4's hotfix work. F5's `landing.html`/`student-coach.html` retirement is shared with WS-7 step 5 (which deletes `landing.html` + gates operator/admin-context server-side); **WS-7 owns the server-side gating/deletion; WS-8 owns not-porting them** (R4). Coordinate so `landing.html` isn't deleted by WS-7 before R4 confirms nothing references it.

## Tasks
Phases mirror audit §11 exactly (R0–R4). Each is a checklist with an **entry gate**, a **deliverable**, and the **per-PR acceptance criterion** (axe zero serious/critical + Playwright green). See §11 for per-phase detail — not repeated here.

### R0 — Workspace + contract (≈1 week) — foundation
- **Entry gate:** WS-7 step 2 merged (OpenAPI has pydantic request/response models); WS-2's `jsx-a11y` ESLint config exists.
- [ ] Vite scaffold at `app/` (React 18, TypeScript — §11 target shape).
- [ ] ESLint flat config + `eslint-plugin-jsx-a11y` + Prettier — **reuse WS-2/§13 config verbatim** (`npx eslint .`).
- [ ] vitest + `@testing-library/react`; wire `axe` (jest-axe/vitest-axe) into the test harness so every component test can assert zero violations.
- [ ] Generate typed API client from `/openapi.json` via `openapi-typescript`. Verify against WS-7's models — flag any `dict`-body endpoint still untyped back to WS-7.
- [ ] CI job for `app/`: lint + typecheck + vitest(+axe). No page served yet.
- **Deliverable:** empty-but-wired workspace; `npm run build` produces a `dist/`; CI green.
- **Acceptance (this PR):** lint+typecheck+vitest pass; generated client compiles. (No axe/Playwright yet — no UI.)

### R1 — Bluebook folds in (≈1 week) — proves the toolchain on real code
- **Entry gate:** R0 merged.
- **Current state:** `demo/bluebook/` — **11** `.jsx` files (`components.jsx`, `Landing.jsx`, `Dashboard.jsx`, `Exam.jsx`, `Courses.jsx`, `Students.jsx`, `Results.jsx`, `NewExam.jsx`, `tweaks-panel.jsx`, `app.jsx`; §11 says "10" — actual is 11, `Landing.jsx` added 2026-07-04). `build.mjs` concatenates them in a **comment-enforced ORDER** (classic global-scope scripts attaching to `window`, not ESM) and emits one minified IIFE via esbuild, React/ReactDOM left as externals. **Prod `index.prod.html` loads React from committed `vendor/` files (`react.production.min.js` + `react-dom.production.min.js`) — the no-CDN-at-exam-time invariant *already holds in production* (explicit comment at `index.prod.html:47`: "an unpkg outage must not take an exam down"), and a Playwright test asserts it. Dev `index.html:90–96` is the one that loads React + Babel-standalone from the unpkg CDN.** ⚠ `build.mjs:9`'s comment claims React is "loaded from the CDN by index.prod.html" — that comment is **stale/wrong**; prod uses `vendor/`. Committed artifact: `bluebook.bundle.js` (~94 KB).
- [ ] Convert the 11 global-scope `.jsx` files to real ESM `import`/`export`; delete the `ORDER` comment/array in `build.mjs` (§11: "Kill the ORDER comment forever").
- [ ] Vendored-global React → a bundled ESM `dependency`. **The win is dev/prod parity + structural enforcement — not closing a live hole:** prod *already* avoids the CDN (loads `vendor/`), so the no-CDN-at-exam-time invariant holds today via committed files + a Playwright assertion. Bundling makes it hold *by construction* and unifies **dev** (currently unpkg CDN + Babel-standalone, `index.html:90–96`) onto the same build, so dev/prod run identical React and both the fragile comment-enforced ORDER and the stale `build.mjs` "loaded from the CDN" comment die. (§11 calls React "vendored as globals" — accurate for prod; dev uses the CDN.)
- [ ] Fold the durable a11y fixes that WS-4 patched in JSX into the ported components: W2 (rows as `<button>`/`role=button`+keydown, `Logotype` button), W3 (input `label` prop), W4 (`role=alert`/`status`), W12 (`ToggleRow` `role=switch aria-checked aria-label`). These land against the R2 primitives (DataTable, LabeledInput, LiveRegion) as Bluebook adopts them.
- **Deliverable:** Bluebook builds from the Vite workspace; `bluebook.bundle.js` (or its `dist/` successor) still committed (Render has no Node — see the deploy constraint below).
- **Acceptance (this PR):** existing Playwright `exam-flow.spec.mjs` + `smoke.spec.mjs` stay **green**; axe scan of the exam flow = **zero serious/critical**; committed bundle matches source (B2 freshness gate).

### R2 — Shared component library (≈1 week) — the a11y primitives
- **Entry gate:** R1 merged. **This phase can run in parallel with WS-4** (it builds the durable replacements for WS-4's hotfixes).
- Port the existing `demo/_components/` (metric, help-hint, actions, tour) as accessible-by-construction React components, **and add the primitives the audit showed are missing everywhere.** Each primitive ships with an axe test. **This is where the durable W-findings are fixed at the root:**

  | Primitive | Fixes | What it guarantees |
  |---|---|---|
  | `LabeledInput` | **W5** (also durable W3) | `<label htmlFor>` always rendered; no placeholder-only fields. Kills the "zero `for=`" problem across student/professor/onboard/operator/lab/admin-context. |
  | `Modal` (native `<dialog>`) | **W8** | `showModal()` focus trap + Escape + focus restore; `aria-modal`. Replaces the professor import-drawer and tour dialogs that lacked trap/Escape. |
  | `LiveRegion` | **W4** (durable) | `role=status`/`role=alert` region for toasts, autosave, timer milestones, errors. |
  | `DataTable` | **W7** (durable W2) | real `<table>`/`role=table` semantics + rows keyboard-operable — replaces Bluebook's CSS-grid-of-divs. |
  | `NavList` | **W1** (durable) | keyboard-operable nav (arrow/Enter), correct roles. |
  | `FileDrop` | **W13** | visually-hidden but **focusable** `<input type=file>` behind the drop zone — keyboard path for professor/onboard drop zones. |
  | `Timer` | **W10** (durable) | announced milestones via LiveRegion; pause hook; extended-time prop. |
  | Heading primitives (`PageTitle`→`h1`, `CardTitle`→`h2`) | **W7** | correct, ordered heading structure by construction (class-based styling → no visual change). |
  | `Chart` wrapper | **W9** (durable) | `role=img` + generated `aria-label` summary; `aria-hidden` on decorative SVGs. |

- [ ] `tokens.css` extracted once — parchment palette, hairlines, type scale — **with WS-4's contrast fixes baked in as the canonical values** (W6: ink-alpha floor ≥0.62, `--text-muted`→`#5d6773`, gold→amber `#8a6a28` for text-on-cream; **W14**: hairlines ≥0.55 alpha + `:focus-visible` box-shadow).
- [ ] Reduced-motion tokens (**W11**): a single `@media (prefers-reduced-motion: reduce)` block in `tokens.css` that neutralizes the fade/pulse/film-grain animations — copy professor.html/metric.css's existing correct block. Bluebook (which had *zero* reduced-motion support) inherits it.
- [ ] `SkipLink` component + landmark structure (**W15**): skip-to-content link available to every route shell.
- **Deliverable:** documented primitive library, each with a passing axe test.
- **Acceptance (this PR):** every primitive's vitest+axe test = **zero serious/critical**; `tokens.css` contrast values match WS-4's canonical set (grep the hex/alpha values).

### R3 — Page-by-page strangler (order: risk × value)
- **⛔ ENTRY GATE — WS-4 MUST BE LIVE.** Do not start any R3 sub-item until WS-4's hotfixes are shipped and its axe scan is green. (§11 line 677; §9 table "WS-4 hotfix first".) Rationale: R3 pages take days-to-weeks each; accommodated students get WS-4's accessible raw HTML in the meantime.
- Migrate in the §11 order (each sub-item is an independently shippable PR with its own cutover):
  1. [ ] **`index.html` sign-in** (~2–3 days) — small; exercises auth + the R0 client plumbing end-to-end. First real page; validates the whole toolchain against production auth.
  2. [ ] **`student.html`** (~1–2 weeks) — the **worst a11y page** (2,010 lines → ~8 components). Durable **W7** (zero `h1–h6` → real headings), **W8** (`showView()` has no focus move / no `document.title` update → focus the view `h1[tabindex=-1]` + title on route change), **W9** (voice-radar `#fpSvg`, `#arcSvg`, `#vocabSpark` → `Chart` wrapper alt-text) land here natively. **W6**'s worst offenders (placeholder ink 1.81:1, sidebar labels 2.32:1) resolve via `tokens.css`.
  3. [ ] **`professor.html`** (~3–4 weeks) — 5,049 lines. **Decompose into feature modules** (roster / baselines / scoring-review / imports / calibration) and migrate one module at a time behind tabs (tabs get `role=tab`/`aria-selected` — durable **W12** tab-strip fix). Durable **W7** (first heading is `<h3>` then `<h2>` — broken order), **W8** (import drawer focus trap via `Modal`), **W13** (`#blDropZone`/`#importDropZone` via `FileDrop`) land here.
  4. [ ] **`admin.html`, `onboard.html`, `operator.html`, `admin-context.html`** (~1 week combined). `onboard.html`'s `#csvDropZone` → `FileDrop` (**W13**). Coordinate with WS-7 step 5, which server-side-gates `operator.html`/`admin-context.html` (F5) — migrate them into the `staff/*` route group.
  5. [ ] **`playground.html` / `lab.html`** — keep as demo-only statics (already 404'd on real deploys via `_DEMO_ONLY_STATICS`) **or** fold into staff routes later. Lowest priority; not required for the VPAT.
- **Deliverable per sub-item:** the page served from React at its **same path**; legacy reachable at `?legacy=1` for one release (R4).
- **Acceptance (per page PR):** axe scan of the migrated page = **zero serious/critical**; the page's WS-9 Playwright spec **green** (add one if none exists — professor pages currently have none, T7); keyboard-only walkthrough of the page's primary flow completes.

### R4 — Cutover per page (rolling, rides each R3 sub-item)
- **Entry gate:** the corresponding R3 page is merged and its acceptance met.
- [ ] FastAPI serves the built `dist/` assets at the **same path** the legacy page used (no route-topology change; `run.py:106` static mount stays).
- [ ] Legacy page kept reachable at `?legacy=1` for **one release**, then deleted (`git rm`).
- [ ] **F5 retirements — not ported, retired:**
  - `landing.html` (32.6 KB) — **zero inbound links** (orphaned; confirmed by grep). WS-7 step 5 deletes it server-side; R4 confirms no React route claims its path.
  - `student-coach.html` (15.3 KB) — **has one inbound reference**: `demo/student.html:1902` `openCoach()` opens it in a popup (`window.open('student-coach.html', ...)`). **Retiring it requires removing/replacing that call** when `student.html` is migrated (R3 step 2) — fold the coach content into the student React app or drop the affordance. Do not delete `student-coach.html` before R3 step 2 removes the caller.
- **Deliverable:** live pages 100% React; `student-coach.html` + `landing.html` gone; no `?legacy=1` paths remain after the release window.
- **Acceptance:** full WS-9 Playwright suite green against the React stack; grep confirms zero references to retired pages; B2 bundle-freshness gate green.

## Acceptance criteria
- [ ] **Every R2 primitive and every R3 page PR passes axe with zero serious/critical violations** — this is the standing gate that makes the VPAT (WS-3/D15) writable from evidence.
- [ ] All durable a11y findings closed at the React root, mapped to their fix: W5→`LabeledInput`; W6/W14→`tokens.css`; W7→heading primitives + `DataTable`; W8→`Modal` + route focus/title mgmt; W11→reduced-motion tokens; W12→`role=switch`/tab roles; W13→`FileDrop`; W15→`SkipLink`. (Durable slices of W1→`NavList`, W4→`LiveRegion`, W9→`Chart`, W10→`Timer` also closed.)
- [ ] Bluebook's no-CDN-at-exam-time invariant holds **by construction** (React bundled as an ESM dep, not vendored-global) — R1. (Today it already holds in *prod* via committed `vendor/` + a Playwright assertion; bundling makes it structural and brings *dev* — currently on the unpkg CDN — onto the same React.)
- [ ] The committed-`dist/` deploy pattern is generalized from Bluebook and protected by the B2 freshness gate; CI builds, artifact ships committed (Render has no Node).
- [ ] Every live page served from React at its original path; `student-coach.html` and `landing.html` retired (F5); `?legacy=1` fallbacks removed after their release window.
- [ ] WS-9 Playwright suite green on the React stack, incl. new professor-side coverage (T7).

## Risks & watch-outs
- **Committed-dist / no-Node-on-Render constraint.** Render builds nothing JS — the committed built artifact is what production serves (as with today's `bluebook.bundle.js`). Every merge that changes `app/` source **must** re-commit `dist/`; a stale bundle ships silently. The B2 freshness gate (WS-2) is the only thing catching it — treat a B2 CI failure as a release blocker, not a nuisance. §11 offers option (b) (a Render static site fronting the API) as the escape hatch when the bundle outgrows review; start with (a), revisit later.
- **R3-before-WS-4 is the cardinal ordering trap.** If R3 slips ahead of WS-4, accommodated students are stuck on the old inaccessible pages for weeks. Enforce the entry gate mechanically (don't merge R3 page PRs until WS-4 is tagged live).
- **`student-coach.html` caller.** Deleting it without removing `student.html:1902`'s `openCoach()` breaks a live popup. Order matters (R3 step 2 before deletion).
- **OpenAPI client truthfulness depends on WS-7.** If R0's client is generated before WS-7 step 2, the `dict`-body endpoints produce `any`/loose types and the "TypeScript is nearly free" premise (§11) collapses. Gate R0's client-gen on WS-7 step 2.
- **`?legacy=1` drift.** Keeping two implementations of a page reachable invites divergence. Hold the one-release window firm; delete legacy on schedule.
- **Scope note (not a task here):** §11's `professor.html` decomposition (5k lines → 5 feature modules over 3–4 weeks) is the single largest chunk and the highest re-introduction-of-bugs risk. Its safety net is the WS-9 professor-side E2E specs (T7) — those should exist *before or alongside* professor module migration, not after.

## Sequencing within the workstream
1. **R0** (workspace + contract) — blocked only by WS-7 step 2 + WS-2 lint config. Independently shippable (no UI change).
2. **R1** (Bluebook fold-in) — after R0. Independently shippable; makes the no-CDN invariant *structural* (prod already has it via `vendor/`) and brings dev onto the same bundled React.
3. **R2** (component library) — after R1; **may overlap WS-4** since it builds WS-4's durable replacements. Independently shippable (library + tests, no page cutover).
4. **R3 → R4 page-by-page**, gated on **WS-4 live**, in §11 order (index → student → professor → admin cluster → playground/lab). Each page's R3 build + R4 cutover land together as one shippable unit; pages are independent of each other and can be interleaved with other workstreams.
5. **F5 retirements** ride R4: `landing.html` any time after R0 (orphaned); `student-coach.html` only after R3 step 2 (`student.html`) removes its caller.
