# Master Implementation Plan — Workstream detail

Detailed, code-grounded execution plans for the nine workstreams defined in
[Audit §9](../AUDIT_2026-07-06.md) ("Master implementation plan (all findings)").
Each workstream has its own file; this index gives the map, the dependency graph, a
sequencing recommendation for a **single maintainer**, a finding→workstream traceability
matrix, and a candid list of concerns about the plan's scope and approach.

> Source of truth for *what* and *why*: the audit. These files add the *how*, *in what order*,
> and *how you know it's done*. Where a workstream has a dedicated audit section (WS-6→§10,
> WS-8→§11, WS-9→§12, WS-2 configs→§13), the file is an execution checklist that references
> that section rather than repeating it.
>
> Related: [`docs/adr/`](../adr/README.md) records the decisions behind several of these
> workstreams (WS-6 in particular rests on ADR-002/004/006) — check there before re-deciding
> something a workstream file only executes.

> ⚠️ **Multiple concurrent worker threads land on this repo.** `path:line` references in these
> plans drift as work lands elsewhere — at execution, grep the symbol, don't trust the line.
> **[ANCHORS.md](ANCHORS.md)** gives a greppable symbol for every load-bearing site so refs
> survive the drift. Before starting any workstream, `git fetch origin main` and diff against
> that workstream's "Current state" section — it may already be partially or fully landed.

---

## Current status (updated 2026-07-16, against `origin/main` HEAD `835b655`)

Source: audit-remediation status review (`docs/AUDIT_2026-07-06.md` + this directory + live
`git log`/`pytest`), cross-checked against actual code in this pass — see "Verified this pass"
below. Percentages are estimated against each workstream's own acceptance criteria, not a
metric tracked automatically.

| WS | Status | Notes |
|---|---|---|
| 1 Security hotfixes | ✅ Done (100%) | No open items against its own criteria. |
| 2 Guardrails | ✅ Done (100%) | 4-job gated CI, `.venv` on 3.11.15, ruff/black/mypy + pre-commit all landed. |
| 3 Trust surface | ✅ Done (100%) | Docs/compliance corrected; VPAT correctly deferred to WS-4/WS-8. |
| 4 Accessibility (exam-flow) | 🟡 ~78% | Open: several Bluebook rows still click-only `<div>`s (not keyboard-reachable); axe CI scan is non-blocking. |
| 5 Test depth | 🟡 ~60% | Suite green (648 passed / 0 failed at last check). Open: no flag-matrix scoring tests, no full Bluebook-API CRUD tests; coverage 76.98% vs. 78% goal as of 2026-07-22 (the P6 v1 deletion removed ~2,100 dead statements from the denominator), `--cov-fail-under` now 72. |
| 6 Postgres convergence | 🟢 code-complete | **All seven phases (P0–P6) merged to `main` 2026-07-17→22** (PRs #76 P3, #77 P4, #78 P5, #90 P6). `PostgresRepository` implements the full Protocol (only `db_path()` deliberately raises — SQLite-file backup tooling, P4 scope note); `scripts/migrate_sqlite_to_pg.py` proven at checksum parity across all 16 tables; `REPO_SHADOW=postgres` mirror + `REPO_BACKEND=postgres` cutover flip ship inert (default stays SQLite); in-memory `_STORE` demoted (multi-worker unlocked, proven cross-process); dormant v1 stack + its 62 tests deleted, importlib hack dissolved. **Remaining items are operational, not code:** deploy → shadow soak → restore drill → the one-env-var cutover per OPS_RUNBOOK. |
| 7 API-layer refactor | 🟡 ~40% | Step 1 (`ScoringConfig`) + step 2 (typed pydantic request models, all but 1 of 8 endpoints) + step 5 (static gating, Canvas 501 stubs) landed. Step 3 (router split into `original/routers/`) **not started** — zero `APIRouter` usage; step 4 (de-async, flag GA, merge `ORIGINAL_ENV`/`ENVIRONMENT`) not started. |
| 8 React migration | 🔵 ~15% | R0 (Vite/TS/eslint/vitest/axe scaffold) + R1 (Bluebook ESM, ahead of schedule) landed. R2 (shared components) is a single 7-line `SkipLink.tsx`. R3 (page migration) not started — no page migrated yet. |
| 9 E2E + release hygiene | 🟡 ~87% | 4 parallel workers, professor-journey spec + Stage-2 breadth (~55 specs), `/health` returns real `commit` + single-sourced version. Open: no `pilot-YYYY-MM-DD` release-tag convention written down yet. |

**Verified this pass (2026-07-22):** confirmed directly against `origin/main` —
- WS-6 P3–P6 all merged (#76, #77, #78, #90). `PostgresRepository` is a full implementation
  (the 2026-07-16 note below that it was a skeleton is superseded); the contract suite runs
  against a real `postgres:16` CI service container on every PR.
- The dormant v1 stack is **gone**: `original/api|canvas|middleware|auth|schemas_v1|tasks` +
  `main.py` + 62 v1 tests deleted; `run.py` imports `original.api` plainly (A9 dissolved);
  the in-memory `_STORE` is demoted, so `--workers N` is safe (proven cross-process).
- Full suite green: 775 passed, 0 failed, zero xfail noise, on both backends; coverage 76.98%
  against the 72 gate. `original/api.py` measures 3,265 lines.
- The app still defaults to SQLite everywhere; Postgres activates only via the
  `REPO_SHADOW`/`REPO_BACKEND` env vars (OPS_RUNBOOK cutover procedure).

**Open items worth a deliberate decision, not a default:**
1. ~~WS-6's decision gate was never explicitly recorded as decided~~ **Resolved 2026-07-17:**
   the owner made the explicit go call ("Commit to Postgres → start P4") before P4 began;
   P3 had landed inert ahead of it (nothing production-facing depended on it). ADR-004's
   hold-on-SQLite posture is superseded by the executed WS-6 P3–P6.
2. **`api.py` is still trending the wrong way**: 2,714 → 2,964 → 3,265 lines (2026-07-22; the
   P5 maintenance middleware and db_path guards landed there). The one step that shrinks it
   (WS-7 step 3, the router split) remains untouched — and with WS-6 code-complete, the
   serialization concern is moot: WS-7.3 is now unambiguously next in line for `api.py`.
3. **Coverage gate nearly caught up** — `--cov-fail-under` is 72 with actual coverage at
   76.98% (2026-07-22) against the 78% target; the remaining WS-5 gaps (flag-matrix,
   Bluebook CRUD tests) are what close the last point.

---

## The nine workstreams

| WS | Plan | Findings | Effort (audit) | Depends on |
|---|---|---|---|---|
| 1 | [Security & data-integrity hotfixes](WS-1-security-hotfixes.md) | B10, A1, B16, F3 (token) | 1–2 days | — |
| 2 | [Guardrails: CI, pre-commit, lint, hygiene](WS-2-guardrails.md) | H1–H4, D9, B1–B9, B11–B14, B17, B18, T8, T9, S6, S10–S12 | 3–5 days | — |
| 3 | [Trust surface: docs & compliance](WS-3-trust-surface.md) | D1–D8, D10–D16, F3 (table), F8 | 3–4 days | — |
| 4 | [Accessibility: exam-flow hotfix](WS-4-accessibility-hotfix.md) | W1–W15 (now-subset) | 2–3 days | — |
| 5 | [Test depth: unit/API](WS-5-test-depth.md) | T1–T6, T10 · *T7→WS-9* | 4–6 days | WS-2 |
| 6 | [Postgres convergence](WS-6-postgres-convergence.md) (§10) | A3, A4, A5, A8, A9, F1, F4, F6, B15, B19, T4, T6, S2, S3, part S4 | 6–9 weeks | WS-1, WS-2, **WS-7.1** |
| 7 | [API-layer refactor](WS-7-api-refactor.md) | A2, A6, A7, A10, S1, S4, S5, S7, S8, S9, F2, F5 | 2–3 weeks | (WS-5 net) |
| 8 | [Frontend → React](WS-8-react-migration.md) (§11) | W5–W15 (durable), F5 | ~2 months | WS-4, **WS-7 models** |
| 9 | [E2E build-out + release hygiene](WS-9-e2e-release-hygiene.md) (§12) | T7, B20, D7 | 2–3 weeks | WS-2, WS-8 (partial) |

---

## Dependency graph

```
        ┌──────── immediate, no dependencies ────────┐
        WS-1        WS-2        WS-3        WS-4
        (sec)     (guardrails) (docs)     (a11y now)
                     │                        │
                     ▼                        ▼
                   WS-5                     WS-8 ──────────► WS-9
                (test depth)            (React, ~2mo)    (E2E + release)
                     │                        ▲              ▲
   WS-7.1 ───────────┼──────────┐             │              │
 (ScoringConfig)     │          ▼             │              │
                     └────►   WS-6  ◄─── interleaves ─── WS-7 (rest)
                           (Postgres, 6–9wk)
```

**Reading the arrows:** WS-7 *step 1* (`ScoringConfig` — hoist env reads out of `score()`,
pass genre stats as a parameter) is a hard prerequisite for WS-6 P0, because it removes the
scoring→store edge (A5) the migration would otherwise have to port. WS-8 R0 wants WS-7's
pydantic request/response models so the OpenAPI-generated TypeScript client is truthful.
WS-9's `@a11y` specs become *blocking* per page only as WS-8 lands that page.

---

## Recommended sequence for a single maintainer

The audit says "WS-1/2/3 can run in parallel." The repo has one committer, so treat the plan
as a **strictly ordered backlog**, not a parallel schedule. Suggested waves:

**Wave 0 — this week (½–1 day each, highest leverage per hour):**
1. **WS-2 task 6 first** — rebuild `.venv` on Python 3.11 (B7). *Until this is done, every
   "passes locally" signal for every other workstream is on the wrong interpreter.*
2. WS-1 in full (security + data-integrity; B10, A1, B16, token doc).
3. WS-3 tasks 1–2 (threshold + compliance-doc corrections — the trust-surface bleeders).
4. WS-4 exam-flow minimum (W3 textarea label, W4 `role="alert"`/live-region, timer) — the
   legally riskiest flow, ~1 day.

**Wave 1 — next 2–4 weeks:**
5. Rest of WS-2 (pre-commit, ruff, CI four-job shape, Makefile, hygiene deletions).
6. Rest of WS-3 (README/SETUP rewrite, banners, flag table, new docs).
7. Rest of WS-4 (keyboard/labels/contrast sweep) + **cheap durable a11y pulled forward**
   (see Concern #3): W7 heading remap and W11 reduced-motion don't need React.
8. WS-5 (test depth) — now that WS-2 gives the shared fixture + coverage gate.

**Wave 2 — the long haul (months):**
9. ✅ WS-7 step 1 (`ScoringConfig`) — landed.
10. ✅ WS-6 P0→P2 — landed (seam-widening, schema/models, alembic baseline). The decision
    gate was resolved explicitly on 2026-07-17 (owner go call).
11. ✅ WS-6 P3→P6 — landed 2026-07-17→22 (#76 PostgresRepository parity, #77 migration +
    shadow, #78 inert cutover mechanism, #90 `_STORE` demotion + v1 deletion). The cutover
    itself is now an operator action (OPS_RUNBOOK). **WS-7 step 3 (router split) is next in
    line and hasn't started.**
12. WS-8 (React migration) once WS-4 is live and WS-7 models exist. WS-9 rides alongside — it's
    already ~87% done, further along than WS-8 would suggest.

---

## Finding → workstream traceability (shared findings)

A handful of findings are split across workstreams. This matrix exists so no slice is
orphaned — each row's pieces must all land for the finding to be closed.

| Finding | Slice → WS-1 | → WS-3 | → WS-5 | → WS-6 | → WS-7 | → WS-8 |
|---|---|---|---|---|---|---|
| **F3** (env flags) | `MAINTENANCE_TOKEN`/`GUARD_DESTRUCTIVE` doc | full flag table in CLAUDE.md | — | — | merge `ORIGINAL_ENV`/`ENVIRONMENT` | — |
| **F5** (demo surface) | — | — | — | — | gate `operator.html`/`admin-context.html`; 501 Canvas stubs | retire `landing.html`/`student-coach.html` |
| **S4** (`score()` config) | — | — | — | genre-stats-as-parameter (via P0 prereq) | `ScoringConfig` injection + collapse flag branches | — |
| **T4/T6** (dead code, test naming) | — | — | interim: delete `rbac.py`/`tasks`, rename `test_api.py` | final: delete v1 API + its 62 tests (P6) | — | — |
| **W1–W15** (a11y) | — | — | — | — | — | durable AA (W5–W15, incl. W9 `Chart` alt-text + W10 `Timer` extended-time) |
| ↳ *and* WS-4 | *(WS-4 owns the now-hotfix subset of all W-findings in raw HTML/JSX)* | | | | | |
| **B20/D7** (versioning) | — | D7 version source coordinates | — | — | — | — → **WS-9** owns B20 + D7 execution |

---

## Corrections to the audit surfaced during planning

Grounding each plan in the live code turned up places where the audit (or its §9/§10/§11
summaries) is stale or wrong. These are folded into the individual WS files; collected here so
they aren't lost. All were verified against the working tree on 2026-07-07.

- **Bluebook already avoids the CDN at exam time (WS-8).** §11 implies the no-CDN-at-exam-time
  invariant isn't yet held; in fact `index.prod.html:48-49` loads React from committed `vendor/`
  files (comment: *"an unpkg outage must not take an exam down"*), and a Playwright test asserts it.
  Only **dev** `index.html` uses the unpkg CDN. The misleading signal is a **stale comment at
  `build.mjs:9`** ("loaded from the CDN by index.prod.html") that contradicts what the prod HTML does.
- **Deleting `middleware/rbac.py` is not import-graph-safe (WS-5/WS-6).** It has zero *Python*
  importers, but `cli/security_audit.py` filesystem-checks (`.exists()`) and *calls* it — the delete
  must edit `security_audit.py` in the same commit or CI's audit step breaks.
- **`MAINTENANCE_TOKEN` is also a login backdoor (WS-1).** Beyond the `X-Guard-Token` role it gates,
  it grants admin via `demo_login` (`api.py:~2684`). It 404s on real deploys, but that second use is
  why the value is security-sensitive and why rotation matters.
- **A1's "return 503" path does not exist yet (WS-1).** There is no persistence-failure→503 seam
  today; WS-1 must *build* it at the `store.put` write sites, not just "propagate."
- **B16's data-loss mechanism is reseed pollution, not `store.clear()` (WS-1).** `store.clear()`
  wipes only the in-memory cache; the real on-disk risk is `--demo` reseeding synthetic rows over
  colliding ids. Accept criterion should read "cannot clear *or reseed*."
- **Third `store._DB_PATH` private reach (WS-6).** Audit cites `api.py:153,158`; there's a third at
  `:410`. All three must move behind the repository seam.
- **Table name is `tuned_thresholds_v2`, not `tuned_thresholds_v` (WS-6/§10).** Use the real name in
  models/DDL.
- **`test_auth.py` is a v1 *unit* test, not a route test (WS-5).** §9/T4 lists it among the `/api/v1`
  route tests; it actually unit-tests `original.auth`/`original.db` modules. It stays in the 62-test
  P6 deletion set (it imports modules P6 removes), but for that reason, not "hits `/api/v1`."
- **`B14` does not exist (WS-2).** The §9 WS-2 row lists "B11–B14," but §7 has no `### B14`
  (findings jump B12/B13 → B15). No content lost; the label is phantom.
- **Manual deletion IS live (WS-3).** D5 is about *automatic* deletion only — `store.delete_student`
  and the `delete_student` CLI work today. The compliance-doc rewrite must strike the automatic claim
  without denying the real manual path (i.e. don't over-correct into a new false statement).
- **Minor drift fixed inline:** audit's `demo/bluebook/src/` path (no `src/` dir); "two aria-live
  blocks" is four; "~40 labels" is the interactive subset of ~75 controls; `_persist`/`_load_all` at
  `store.py:485-494`/`470-482`; `score()` spans `386-714`. No `get_bluebook_submission` exists
  (submission reads are list-only) — test specs must not assert a single-get.
- **`T7` is double-listed in §9 (WS-5/WS-9).** The §9 table puts T7 (professor-side E2E) under
  *both* the WS-5 and WS-9 rows. The plans resolve it to **WS-9** (E2E build-out); WS-5 owns
  T1–T6 + T10. The index table above is corrected to match.
- **Playwright CI retries: §12 says "single retry," code says 2 (WS-9).** `playwright.config.mjs`
  sets `retries: process.env.CI ? 2 : 0`, contradicting §12's "single retry in CI only." WS-9
  Stage 3 sets it to 1 (or amend §12).
- **WS-9 R.2 + Stage 0.2 are already being implemented in the working tree.** `_resolve_app_version()`
  exists at `api.py:177` and `playwright.config.mjs` is `fullyParallel: true` — so those sections'
  "Current state" snapshots (hardcoded `version="0.1.0"`, `workers: 1`) are already partially stale.
  Reconcile before executing WS-9. (See the live-edit callout at the top.)

## Cross-cutting concerns about scope & approach

These are judgment calls the plan makes that are worth a second look *before* committing months
of work. Each has a recommendation.

**1. The Postgres pivot (WS-6) is the largest bet, and its justification is thin at pilot scale.**
The §9 "Direction set 2026-07-06" overrides §8's recommendation (quarantine v1) and commits to a
6–9 week migration of the **FERPA data layer during a live pilot**. The primary *technical* driver
is multi-worker scaling (A4) — but a seminary/small-college pilot almost certainly never needs
`--workers >1`; SQLite/WAL is adequate for this load. The migration's biggest *correctness* win
(tenancy as a DB constraint instead of a string-prefix convention, P2) is achievable in SQLite too.
→ **Recommend:** make "stop after P1" an explicit, pre-committed option. P0–P1 (widen the Repository
seam, route direct `store.*` calls through it) is valuable *regardless* of backend and
de-risks everything. Insert a real go/no-go gate before P2 (first schema/model work) and don't
touch student data until the gate is passed on evidence, not momentum.
**Status (2026-07-16): P1 landed and de-risked the codebase as predicted — but the gate itself
was skipped, not inserted. P2 landed the day after ADR-006 with the go/no-go checklist still
unchecked.** The recommendation to gate P2 wasn't followed; get an explicit retroactive decision
before P3 (real Postgres wiring) starts.

**2. Effort estimates assume parallelism a solo maintainer doesn't have, and are individually optimistic.**
"WS-1/2/3 in parallel" and the per-WS numbers imply ~4–5 months *with* parallelism; serialized for
one person it's closer to 6–9 months. WS-8 (~2 months to convert 12.5k lines of inline-CSS/JS HTML,
including a 5,049-line `professor.html`, to React) and WS-6 (6–9 weeks) read as the softest estimates.
→ **Recommend:** treat §9 as a *prioritized backlog*, not a timeline. The Wave 0/1 items above deliver
most of the risk-reduction in ~2 weeks; the multi-month items (WS-6/7/8) should each carry an explicit
"is this still worth it?" checkpoint.

**3. Durable accessibility and the VPAT are gated behind the ~2-month React rewrite.**
WS-4 fixes the exam flow now (good), but durable AA — headings (W7), SPA focus/title (W8),
reduced-motion (W11), chart alt-text (W9), skip links (W15) — is deferred to WS-8, and the VPAT (D15)
depends on WS-4 **+** WS-8. §8 itself frames the WCAG-Level-A failures as a *business/procurement*
risk. If a sale needs a VPAT before the rewrite ships, this ordering blocks it.
→ **Recommend:** pull the *cheap, React-independent* durable fixes into WS-4: W7 (the audit notes the
heading remap is class-based → "no visual change") and W11 (copy the reduced-motion block that
`professor.html`/`admin.html` already have). That lets a defensible interim VPAT be written from
WS-4 evidence, months earlier.

**4. WS-6 and WS-7 both rewrite `api.py` and are told to "interleave" — a coordination hazard.**
The router split (WS-7.3) and routing every `store.*` call through the seam (WS-6 P1) edit the same
2,714-line file. Truly concurrent, they will churn and conflict.
→ **Recommend:** serialize the shared-file steps: WS-7.1 (`ScoringConfig`) → WS-6 P1 (seam) →
WS-7.3 (router split). "Interleave" should mean "alternate in sequence," not "edit in parallel."
**Status (2026-07-16): the first two landed in the recommended order** (WS-7.1 → WS-6 P1, both
confirmed on `origin/main`). **WS-7.3 (router split) is next and hasn't started** — `api.py` has
grown to 2,964 lines in the meantime (WS-6 P2 + WS-7 steps 2/5 all landed on it too). Do the
router split before any more schema/handler work touches this file.

**5. Deferring the v1 deletion to WS-6 P6 keeps the root-cause cruft alive for the whole migration.**
§8 names the dormant v1 stack the root cause of ~a dozen findings, yet it's only deleted at the *end*
of the 6–9 week Postgres effort. Meanwhile WS-2 must add ruff `extend-exclude` entries for a tree
scheduled for deletion, and the 62 v1 tests keep burning CI. Critically, deleting the v1 **API surface**
(routes/auth/canvas + its tests) does **not** actually depend on the Postgres migration — that was
§8's original standalone item 9.
→ **Recommend:** decouple. Excise the v1 API surface + 62 tests as an early, self-contained step
(kills the `original/api.py` vs `original/api/` shadowing and the importlib hack immediately), and let
WS-6 focus purely on the data layer. This also means WS-2's exclude list can be smaller and shorter-lived.

**6. Test investment (WS-5) partly targets files that WS-6/WS-7 will rewrite.**
Raising `api.py`/`store.py` coverage right before splitting/migrating them risks throwing some tests
away. The mitigation is real but partial: P1's *contract tests* are backend-agnostic by design and will
survive; handler-level tests written against the monolith may not.
→ **Recommend:** in WS-5, bias toward store-level and `score()`-level *behavioral/contract* tests
(which survive the refactor and become the WS-6 P1 contract suite) over api.py handler tests tied to
the current routing shape.

**7. `.venv` on Python 3.9.6 vs. 3.11 everywhere else (B7) undermines all local verification.**
This lives inside WS-2, but it gates the *trustworthiness of every other workstream's local checks*.
→ **Recommend:** do B7 first, before any other work (reflected in Wave 0 above).

**What the plan gets right:** the ordering genuinely de-risks forward (each WS's output feeds the next);
the security + data-integrity items are correctly front-loaded (WS-1); "flags-OFF scoring is
byte-identical" is preserved as an invariant through the refactors; and every pre-cutover Postgres
phase is shippable-inert, so the risky moment is contained to one maintenance window. The core is
well-tested and honestly documented — these plans are mostly about adding *enforcement* and paying down
the dormant-stack tax, not fixing a broken product.
