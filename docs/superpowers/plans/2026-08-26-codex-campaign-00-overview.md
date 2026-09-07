# Codex Campaign 2026-08-26 — Overview: what Original needs next, and who does what

**Audience:** the founder, and any agent (Codex or otherwise) being handed one of the
five plans in this series. This document is the map; the plans are the territory.

**The one-paragraph state of the system.** The core pipeline (109 features → per-student
baseline statistics → weighted deviation → action tier, with a per-tenant impostor-pool
LLR guard on the action) is built, heavily tested (3,275+ tests, 99.6% branch coverage
on `original/`, 0 failures), and calibrated on public-domain corpora plus a small
seminary corpus. Around it sits an unusually honest validation layer — three-valued
gates with registered failure witnesses — and a ring of shipped-but-dark mechanisms
(topic inflation, characteristic weights, genre resolver v2, fused score, AI-likelihood,
Bayesian prior), each default-off behind a named gate or a required pilot measurement.
The debt is not code quality; it is **evidence**: two gates can't currently run at all
(machinery breakage with the fix stranded on an unmerged branch), three mechanisms are
blocked on one regenerable-but-uncommitted corpus, five need shadow data only a live
pilot can produce, and every number so far comes from one-shot corpus benchmarks that
structurally cannot see deployment-shaped failures — several of which have already
happened (see Plan 04's motivation).

**The campaign in one sentence:** repair the gate battery, feed it the corpora it's
missing, make the pilot soak turn-key, build a term-shaped simulator so flags are
certified the way the product is actually used, and stop losing finished work on
stranded branches.

---

## The five plans

| # | File | What it delivers | Blocked on |
|---|------|------------------|-----------|
| 01 | `2026-08-26-codex-campaign-01-gate-repair.md` | G5/G6 run again (land stranded fix); AI-likelihood doc contradiction resolved; G8's silent sklearn degrade fixed; `TYPICALITY_POOLED_CALIBRATION` documented + exchangeability audit; fresh committed G1–G8 battery report; weekly non-blocking CI battery run | nothing |
| 02 | `2026-08-26-codex-campaign-02-corpus-regeneration.md` | Cross-genre corpus regenerated locally; **G7 and G-P3 return first-ever verdicts**; genre-invariant tier set finally measured (criterion 3); PD analogue corpus (committable); sermon corpus + taxonomy decision; public_authors deepened (G3 informative); PAN cache restored; nondeterminism killed; topic-sensitivity re-derivation | Plan 01 G1 (the `.gitignore` rules) |
| 03 | `2026-08-26-codex-campaign-03-shadow-telemetry.md` | One-command soak report (genre/topic/characteristic/fused/AI + prior scope); fused C1 confound regression ready; `CHARACTERISTIC_WEIGHTS` shadow latency measured/mitigated; `docs/SHADOW_SOAK_RUNBOOK.md` | tooling: nothing; **live data: ops O4 + O6 (human)** |
| 04 | `2026-08-26-codex-campaign-04-ecological-validation-harness.md` | **TermSim** — seeded term simulator through the real API: honest-term flag probability, time-to-detection, baseline-growth drift, cold-start parity; scorecards per flag config; new gates T-1…T-4 registered | corpora from Plan 02 enrich it, but a first cut runs on committed corpora alone |
| 05 | `2026-08-26-codex-campaign-05-merge-and-docs-debt.md` | Verify-and-land queue emptied (consent-retention spec, admin-health gate, Bluebook UI, PR #160); branch audit; Dependabot policy + sklearn tripwire; `.env.example` rewritten to the live surface; verification floor wired-or-labeled; three human-decision ADR memos | nothing |

**Dependency order:** 01 → 02 → (04 full-strength); 03 and 05 any time. If running
agents in parallel: 01, 03, 05 immediately in separate worktrees; 02 starts after 01's
G1 lands; 04 can start immediately on T1–T3 scaffolding and consumes 02's corpora as
they arrive. The plans note their overlaps explicitly (05-M1 defers two items to 01;
04's HYBRID scenario consumes 02-C10's output).

## How to dispatch an agent onto a plan

Hand the agent exactly one plan file plus this overview. Non-negotiables that live in
every plan's Global Constraints and got violated by past sessions, restated once:

- Python is `~/Desktop/Original/.venv/bin/python`, absolute path (worktrees have no
  `.venv`). The full suite takes 11–12 minutes — never on a 600 s timeout. Postgres
  marker tests run via `make test-postgres` and are mandatory for persistence changes.
- CI enforces `--cov-branch --cov-fail-under=98` with ~1.6 points of margin: code
  without tests fails CI even when green.
- Gate results are three-valued; `--strict` before quoting any pass. New gates need
  failure witnesses in `validation/gate_contracts.py`.
- The cross-genre corpus is **never committed** (copyright). Local DBs are fixtures —
  measurements against them are meaningless for pilot claims; real pilot data is
  Postgres on Render and no DSN exists locally.
- `score()` does not read `os.environ` — every benchmark builds a `ScoringConfig`
  explicitly or goes through the API.
- Needs explicit human approval: `constants.py` feature ordering / `NORM_BOUNDS`
  changes, file deletion, branch deletion, pushing to main, killing servers.
- One logical change per commit; `Fix …`/`Add …`/`Refactor …`; PR to `main` on
  `pathosbuilder895/Orig`; co-author trailer per repo convention.

## What "done" looks like for the campaign

1. `python -m validation.calibration_gate --strict` runs **all** gates to real
   verdicts on a fresh checkout + one documented local regeneration step — nothing
   `ERROR`, nothing `uninformative` for machinery-or-missing-corpus reasons (honest
   uninformatives, e.g. sample-size floors awaiting pilot data, are fine and say so).
2. Every shipped-but-dark mechanism has, in its CLAUDE.md row: its corpus-gate
   verdict, its TermSim scorecard reference, and either its soak result or the exact
   soak command awaiting pilot data. No flag row says "never measured" anymore.
3. The pilot soak is one page and two commands for a human operator.
4. TermSim's standard matrix runs in ≤15 minutes and its four gates sit in the
   battery.
5. Zero stranded one-commit fixes; zero doc-vs-doc contradictions about gate
   verdicts; `.env.example` describes the product that exists.

## The human-only track (no agent should attempt these)

From the pilot-launch master plan's ops items O1–O9, all still open, plus standing
items. These gate the *pilot*, not the campaign — every plan above is executable
without them, and Plan 03 exists to make their payoff immediate:

- **O6 — DPA signed.** Hard gate before any real student data. Everything below it
  in this list is sequenced after it for real-data purposes.
- **O4 — Postgres cutover on Render.** The keystone infrastructure blocker: Tier-17
  readiness, all shadow reads, drift re-checks, and the prior-scope measurement wait
  on it. (O5 restore drill follows immediately.)
- O1 go-live check, O2 Canvas admin request, O3 uptime monitoring, O7 LTI bind,
  O8 sandbox-course verification, O9 tenant/professor provisioning.
- **Bbook secrets** (`BBOOK_API_URL`/`BBOOK_EXTERNAL_SECRET`) are unset — blueprint
  syncs don't prompt for `sync: false` vars; set them by hand or baseline-request
  endpoints stay 503 and Tier 17 has no data source.
- **Secret hygiene:** keys rotated 2026-08-07; a prior session printed
  `SECRET_KEY`/`MAINTENANCE_TOKEN` into a transcript — if not already rotated
  after 2026-08-13, rotate again.
- Decisions requested by Plan 05 M8's ADR memos: `AUTH_WEIGHTS` dead arms, dormant
  v1 pruning, Mark-Reviewed schema change. Plus sign-off gates the plans surface:
  C8's NCD pre-registration, any `genre_model_v2` taxonomy change, any flag default
  flip (none is proposed anywhere in this campaign).

## Why the testing strategy is shaped this way

Three layers, because each answers a question the others cannot:

1. **Corpus gates (exists, being repaired/fed — Plans 01–02):** *Is the mechanism
   sound on known-answer data?* Fast, reproducible, falsifiable — but one-shot: fixed
   baselines, no time axis, no cohorts, no actions.
2. **TermSim (new — Plan 04):** *Does the mechanism behave over a term, in a cohort,
   through the real API, measured in actions?* This is the layer Turnitin-style
   AUC benchmarking cannot provide, and where this repo's worst late surprises
   (baseline-growth drift, inert-at-pilot-N typicality, cold-start prior regression,
   cross-genre inversion, drift-gate over-holding) would all have been caught early.
   Still synthetic — its absolute rates don't transfer; its config *diffs* do.
3. **Shadow soak (tooling now, data at pilot — Plan 03):** *Does real student traffic
   look anything like our corpora?* The only layer that can answer abstention rates,
   topic-distance mass, sermon prevalence, and real FPR. Slow, unrepeatable,
   precious — which is why the other two layers must wring out everything they can
   first, and why the soak is pre-built to waste none of it.

A flag graduates by clearing all three, in that order. That is the whole strategy.
