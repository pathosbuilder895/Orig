# Original — Testing Strategy (index)

**Status:** strategy, 2026-09-07. Written against local `main@0d35d486`
(122 commits ahead of `origin/main`; includes the TermSim merge, the G5/G6
machinery fix, and the weekly battery workflow) plus the audit that produced
`docs/testing/01-current-state.md`.
**Scope:** the whole product — feature pipeline, scoring, persistence, API,
integrations, two frontends, the validation battery, deploy, and the test
infrastructure itself.
**Audience:** whoever picks up the next test-quality workstream, human or agent.

---

## The one-paragraph thesis

Original has 3,334 collected tests, 99.61 % combined statement+branch coverage
on `original/`, zero `xfail`s, zero unconditional skips, a falsifiability
meta-test over its scientific gates, and a Playwright suite that boots the real
pilot server in CI. By the usual metrics it is over-tested. And yet the
2026-09-02 architecture review found the pilot-blocking defect — same-author
submissions scoring 0.75–0.82 (escalate) at the pilot's modal three baselines —
by direct probe, not by any test. Five security holes and a boot-bricking
lockset gap surfaced the same way. **Coverage is saturated; behaviour is not.**
This strategy stops spending on the coverage axis and moves investment to the
axes the suite is structurally blind on: deployment-shaped behaviour,
adversarial security, configuration reality, performance under load, and the
quality of the assertions themselves.

## What this document set is and is not

It is a plan for *testing*, not a plan for fixing the product. Where a known
defect exists, the plan says "write the failing test first, then fix" and
points at the branch or doc that owns the fix. The gap register in
`10-gap-register.md` is the single prioritised list; every other document
explains one slice of it.

## Document map

| # | File | Slice | Read when |
|---|------|-------|-----------|
| 01 | `01-current-state.md` | Audit of what exists, what is strong, and the structural blind spots | first, always |
| 02 | `02-unit-property-math.md` | Feature tiers, quantum scoring invariants, redaction, pure helpers; property tests; mutation testing | touching `original/features/`, `original/quantum/`, `voice.py` |
| 03 | `03-api-persistence.md` | Routers, repository contract, Alembic, shadow dual-write, cutover, migration drift | touching `store.py`, `postgres_repository.py`, `alembic/`, `routers/` |
| 04 | `04-security-adversarial.md` | Abuse-case suite: tenant isolation, auth matrix, CORS, throttle, LTI replay, secrets, destructive guards | any auth/tenant/LTI change; before pilot go-live |
| 05 | `05-frontend-e2e-a11y.md` | Playwright, the untested second React frontend, axe, visual regression policy, mobile | touching `demo/`, `demo/bluebook/`, `demo/app/`, `app/` |
| 06 | `06-scientific-validation.md` | The gate battery, cold-start FPR as a CI test, TermSim, corpora, how results may be cited | any change to scoring thresholds, flags, or corpora |
| 07 | `07-performance-reliability.md` | Latency budgets, event-loop blocking, per-score table scans, concurrency, single-worker constraint | before enabling shadow flags; before load |
| 08 | `08-config-deploy-readiness.md` | Env-flag byte-identity matrix, lockset boot matrix, render.yaml vs preflight drift, restore drill, container smoke | any `run.py`, `render.yaml`, requirements, or flag change |
| 09 | `09-test-infrastructure-ci.md` | Suite speed (xdist/sharding), fixture consolidation, markers, flake policy, CI job shape, ownership | any CI or conftest change |
| 10 | `10-gap-register.md` | Prioritised gap IDs with severity, effort, acceptance criteria, and phase | planning the next sprint |

## The pyramid, adapted to Original

The classic pyramid assumes the risk is in code paths. Original's risk is in
*numbers under realistic conditions* and in *who can read whose data*. The
layers below are ordered by how many should exist, top is fewest.

```
        ┌─────────────────────────────┐
        │  Scheduled batteries        │  gate battery (G1–G8, T-1…T-4), load run,
        │  (weekly, non-blocking)     │  restore drill, mutation score, full e2e matrix
        ├─────────────────────────────┤
        │  Browser e2e (per PR)       │  ~72 Playwright, chromium, real pilot server
        ├─────────────────────────────┤
        │  Behavioural certification  │  cold-start FPR, flag byte-identity matrix,
        │  (per PR, seconds)          │  lockset boot, abuse cases, latency budgets
        ├─────────────────────────────┤
        │  Contract + integration     │  repo contract × 2 backends, Alembic round-trip,
        │  (per PR)                   │  TestClient router tests, integration fakes
        ├─────────────────────────────┤
        │  Unit + property            │  tiers, scoring math, pure helpers, hypothesis
        └─────────────────────────────┘
```

The new layer is **behavioural certification**: small, fast tests that assert
what the product *does* at pilot-shaped inputs and pilot-shaped configuration,
rather than which lines ran. `06-scientific-validation.md` §3 and
`08-config-deploy-readiness.md` §2 define it.

## Coverage targets

Coverage stays a *tripwire*, not a goal.

| Metric | Today | Target | Rule |
|---|---|---|---|
| `original/` combined branch coverage | 99.61 % | hold ≥ 98 % (CI floor) | do not raise the floor; do not chase the last 0.4 % |
| `app/src` branch coverage | 100 % | hold | enforced by `app/vite.config.ts` |
| Mutation score on the 6 named critical modules (§02 §5) | unmeasured | ≥ 80 % surviving-mutant kill rate, measured weekly | the metric that says whether 99.6 % means anything |
| Cold-start FPR certification (§06 §3) | **fails today** by probe | passes at N=3 baselines on the committed corpus | pilot go-live blocker |
| Abuse-case suite (§04) | 5 known holes, 0 tests | 0 open holes with tests green | pilot go-live blocker |
| e2e on live-stack routers | 7 of 12 routers touched | every router with a user-facing flow has ≥1 spec | see §05 §3 |
| Full pytest wall-clock in CI | 15–18 min serial | ≤ 8 min via 3-way shard | see §09 §1 |

## How to run things (the short list)

Python is **always** `~/Desktop/Original/.venv/bin/python` (absolute; worktrees
have no `.venv`). The full suite takes 11–14 minutes with Postgres up and
`--cov-branch` on; never run it on a 600 s tool timeout.

```bash
# fast local loop — one file, 1–2 s
~/Desktop/Original/.venv/bin/python -m pytest tests/quantum/test_scoring.py -q
```

```bash
# the exact CI command (needs local Postgres: make db-up)
DATABASE_URL=$(bash scripts/local_postgres.sh url) ~/Desktop/Original/.venv/bin/python -m pytest tests/ validation/test_tier10_optional.py -q --cov=original --cov-branch --cov-fail-under=98
```

```bash
# postgres-marked tests only (~10 s once the container is up)
make test-postgres
```

```bash
# gate battery — cite nothing that did not come from --strict
~/Desktop/Original/.venv/bin/python -m validation.calibration_gate --strict
```

```bash
# browser e2e against a server you started with: make run
cd demo/bluebook && npx playwright test
```

## Principles this strategy holds

1. **A test must be able to fail.** The repo already enforces this for gates
   (`tests/test_gate_falsifiability.py`). Extend the discipline: every new
   behavioural test in this plan names the input that would fail it.
2. **Pilot-shaped, not corpus-shaped.** Certify at N=3 baselines, 300-word
   submissions, mixed genres, one tenant of eight peers. That is what the
   product sees.
3. **Three-valued honesty.** `pass` / `fail` / `uninformative`, everywhere a
   sample-size floor exists. Never let a floor-guaranteed outcome read as a
   pass.
4. **Byte-identity for every default-off flag.** If a flag is off, output is
   bit-for-bit the same as before the flag existed. The suite proves this for
   some flags; §08 makes it a matrix over all of them.
5. **Prefer a fake at the transport seam to a mock at the method seam.** The
   Canvas `httpx.MockTransport` pattern is the model; the Bbook hand-rolled
   client fake is the anti-pattern.
6. **Don't automate what needs a real Canvas.** Two smoke-test items stay
   manual; say so instead of faking them.

## Relationship to prior work

- `docs/implementation/WS-5-test-depth.md` and `WS-9-e2e-release-hygiene.md`
  are done; this supersedes their "what next" sections.
- `docs/superpowers/plans/2026-08-17-branch-coverage-*.md` closed the coverage
  axis; this plan starts where its completion report's "what remains open"
  section stops.
- `docs/superpowers/plans/2026-08-26-codex-campaign-0{1,2,4}` own gate repair,
  corpus regeneration, and TermSim. Plan 01's fix and weekly workflow and
  Plan 04's harness are merged on local `main` as of 2026-09-07; §06 here
  *consumes* those and records what is still open (a post-fix committed
  report, and a battery job that cannot finish inside its cap).
- The 2026-09-02 architecture review (private artifact; summary in §01 §6) is
  the source of the security and saturation findings.
