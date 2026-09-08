# TermSim first light — 2026-08-27

> Corpus-derived synthetic students (public-domain 19th-century prose, the
> committed seminary-analogue corpus, and Plato/Jowett), not real student
> data. Absolute rates in this report do not transfer to real students.
> Only same-script differences between configurations are interpretable —
> and even those are qualified below where the campaign's own seeding bug
> weakens that claim. This report complements, and cannot replace, the
> pilot shadow soak (Plan 03).

## Provenance

Standard matrix (`baseline`, `baseline-frozen`, `llr-shadow`, `no-context`,
`topic-inflation`, `characteristic-weights`, `genre-v2`), 3 cohorts
(3/8/25 students, one tenant each, scenarios mixed per `SCENARIO_PATTERN`),
15 weeks, 3 seeds:

| Seed | Manifest sha256 | Script sha256 | Wall clock (max cell) |
|---|---|---|---|
| 20260826 | `17540565cc49ae6c…` | `03d4979e163358e8…` | 2063s (34.4 min — heavy contention from an unrelated concurrent process) |
| 20260827 | `17540565cc49ae6c…` | `a807db1933a540cd…` | 1235s (20.6 min) |
| 20260828 | `17540565cc49ae6c…` | `8cdd73afbcb3f616…` | 1062s (17.7 min) |

36 personas, median 49 docs/persona, 23 multi-work (manifest built from
`public_authors`, `genre_2026-08`, the seminary corpus, and Plato). Cells run
concurrently (7 workers), so wall clock ≈ the slowest cell, not the sum —
seed 20260828's 17.7 min is close to the plan's ≤15 min target; seed
20260826 nearly doubled it under contention from an unrelated audit process
sharing the same 12-core machine, not from the harness itself. Every JSON in
this report is a byte-identical read of a committed scorecard under
`.benchmark_cache/termsim/seed-<seed>/<cell>.json` — not recomputed for this
document.

Every cell's `diff_checks.json` passed on all 3 seeds: `LLR_ACTION_MODE=gate`
never exceeded `llr-shadow`'s TRANSFER term-flag probability at any
threshold, on every seed. The one directional guarantee this campaign can
mechanically verify held every time.

## A limitation discovered mid-campaign — read this before the numbers below

Building this report surfaced a real bug in the script generator: persona
assignment was `meta[(cohort_size + index) % len(meta)]` — a pure function
of cohort size and student index, not the seeded RNG. Only the GHOST
substitute persona and the GHOST/AI/HYBRID onset week actually varied by
seed. Confirmed directly: seed 20260826 and 20260827's HONEST
`baseline_growth_slope.per_student` lists matched to 15 decimal places, and
every honest-term rate in every cell was bit-identical across all three
seeds (checked explicitly for all 7 cells).

**Consequence:** for HONEST, COLDSTART, and TRANSFER — the scenarios T-1,
T-3, and T-4 gate on — this was not a 3-seed campaign. It was one script run
three times. `gate-evidence`'s cross-seed pooling (namespacing students by
seed before merging) faithfully did its job, but the "informativeness"
floors it crossed did so by tripling identical data, not by adding
independent draws: T-3's pooled N (12) is exactly 4×3, T-4's (18) is exactly
6×3. The verdicts below are real given the numbers, but their true
confidence is that of the single-seed N, not the pooled N.

**Fixed for future runs** (commit `53d59279`): persona assignment now draws
via `rng.randrange`, verified by a new regression test that two seeds
produce different HONEST persona assignments. This campaign's 3 seeds
predate the fix and are reported as-is rather than discarded — the
saturation finding below does not depend on cross-seed persona diversity to
be real (it reproduces identically inside a single seed, and was independently
confirmed by hand-probing the live API outside the harness before any of
this campaign ran). Re-running the standard matrix at 3 seeds under the
fixed generator is the natural next step, flagged in Recommendations.

## The headline finding: honest submissions saturate at every configuration, including flags-off

| Cell | monitor+ | schedule+ | escalate | n |
|---|---|---|---|---|
| `no-context` (Phase-1 core, everything off) | 100.0% | 100.0% | 84.6% | 13 |
| `baseline` (pilot defaults) | 100.0% | 100.0% | 92.3% | 13 |
| `baseline-frozen` | 100.0% | 100.0% | 92.3% | 13 |
| `llr-shadow` | 100.0% | 100.0% | 92.3% | 13 |
| `topic-inflation` | 100.0% | 100.0% | 92.3% | 13 |
| `genre-v2` | 100.0% | 100.0% | 92.3% | 13 |
| `characteristic-weights` | 100.0% | 100.0% | **100.0%** | 13 |

Every configuration puts every honest student's term at `monitor` or above
at least once, and at `schedule_conversation` or above at least once.
`no-context` — every Phase 3/5/6 mechanism disabled, `NULL_MODEL=none` — is
only 8 points better at `escalate` than the full pilot stack. **The
saturation is in the core deviation-score calibration at pilot-realistic
onboarding (2–3 baselines), not caused by the advanced mechanisms.** This
matches a hand-probe run before the harness existed: same-author holdouts
scored deviation 0.65–0.83 at 3 baselines across seminary and 19th-century
registers, homogeneous and diverse onboarding sets, whole documents and
chunks, flags on and off — and even at 10 baselines one author (Edwards)
still scored 0.61 against a 0.60 `schedule_conversation` floor. The
committed `validation/calibration_report.json` corroborates from a third
angle: `authentic.mean_deviation = 0.9566`, `threshold_metrics.*.fpr = 1.0`.
G1 passes today only because its LOO harness gives authors 10–60 baseline
documents; the pilot's modal onboarding is 3.

**`characteristic-weights` makes it strictly worse** (100% vs 92.3% at
escalate) — consistent with the flag's own CLAUDE.md caveat that it is an
unvalidated uniform upward bias (+0.023–0.033 measured on a synthetic
profile). This is the flag behaving exactly as documented, now confirmed at
the deployment-outcome level rather than only in a single synthetic-profile
measurement.

## Detection numbers are not what they look like

| Scenario | Caught by term end (monitor+) | n |
|---|---|---|
| GHOST | 100.0% | 7 |
| AI | 100.0% | 3 |
| HYBRID (mechanical-paraphrase proxy — not an LLM-paraphrase claim) | 100.0% | 2 |

100% detection reads as a win until set beside tier precision — among ALL
submissions flagged at `escalate`, only **38.1%** (48/126) belong to a
misconduct scenario; at `monitor`, only **19.7%** (48/244); at
`schedule_conversation`, only **20.8%** (48/231). The system is not
detecting impostors distinctively — it is flagging nearly everyone, honest
and impostor alike, and every impostor happens to be caught inside that
blanket. GHOST's median detection delay is 0 weeks in every seed, which is
the same signature: the very first post-onset submission is already flagged,
because the pre-onset submissions were too. **T-2's "pass" below is hollow
for the same reason.**

## T-gates (pooled evidence, `validation/termsim/reports/latest.json`)

| Gate | Verdict | Read this way |
|---|---|---|
| T-1 (honest-term budget: schedule ≤10%, escalate ≤2%) | **FAIL** | Measured 100% / 92.3% against a 10% / 2% bar. Not close; not sensitive to the pooling caveat above — single-seed N=13 already fails outright. |
| T-2 (GHOST caught ≥60%) | PASS (hollow) | 100% caught, n=7×3 pooled (single-seed n=7 already clears the n≥5 floor). Passes because everyone is caught, honest included — see Detection section above. |
| T-3 (\|growth slope\| < 0.001) | **FAIL** | Measured slope 0.0375, ~37× the bound and larger in magnitude than the fused-channel confound (-0.0016/baseline) the bound was calibrated against. Pooled n=12 is 4×3 identical draws (see limitation above) — true confidence is n=4, which is itself below the gate's own n≥5 floor. Read this FAIL as "consistent with a real problem, under-powered to certify," not as a clean fail.  |
| T-4 (coldstart ≤2× honest) | PASS (hollow) | Both COLDSTART and HONEST are at 100% schedule_conversation, so `1.0 ≤ 2×1.0` holds by construction — this formula cannot fail once HONEST is already at ceiling. Pooled n=18 is 6×3 identical draws; true confidence is n=6, at the gate's own n≥8 floor (would be uninformative unpooled). |

Two of four gates pass, but both passes are artifacts of the same
saturation the FAILs are reporting — a pass here is not evidence the
mechanism it nominally certifies (impostor detection, cold-start fairness)
actually works. This is precisely the "score-changing flag enablement
requires a scorecard diff *and* pilot shadow soak evidence" posture
CLAUDE.md's flag table asks for, not a substitute for it.

## Other surprises

- **`topic-inflation` fired on 0 of 252 scored submissions**, in every
  cell it ran in. This is exactly the trap CLAUDE.md's own row for
  `TOPIC_VARIANCE_INFLATION` names: "if pilot `d` clusters below 0.25 the
  mechanism is a no-op in production regardless of corpus performance." On
  this corpus, at this baseline size, it is a no-op.
- **`genre-v2` produced no measurable difference** from `baseline` on any
  metric. Consistent with v2's own measured 33% abstention rate on
  historical-prose hold-outs — this corpus mostly resolves to genres v1 and
  v2 agree on, or to `unknown`.
- **`baseline` vs `baseline-frozen` (no accretion) showed no difference** in
  honest-term flag probability, but baseline's upload log shows 21 accrete
  events actually landed (119 vs 98 baseline+accrete rows). At this
  saturation level almost every submission is at or above
  `schedule_conversation`, and the runner only accretes submissions at
  `no_action`/`monitor` — so the accrete-vs-frozen mechanism itself is
  barely exercised. This campaign cannot speak to the fused-score-style
  drift the plan named that mechanism to catch; it needs an honest cohort
  that isn't itself saturated.
- **Growth slope (0.0375/baseline) is an order of magnitude larger than the
  fused compression channel's measured confound (-0.0016/baseline)** that
  T-3's bound was calibrated against — in the opposite direction (positive,
  not negative). The core scoring path may have its own baseline-count
  confound distinct from the fused channel's; worth its own investigation
  independent of the fused-score work.
- **`null_abstain` = 8.3%**, meaning the impostor null pool succeeded
  (had ≥3 students, ≥5 vectors) for 91.7% of scored submissions even at the
  smallest (3-student) cohort shape — the per-tenant floor is not the
  binding constraint in this campaign's cohort design.
- **`typicality_abstain` = 100.0%** and **`fused_abstain` = 100.0%** in
  every cell — expected: `baseline_count` never exceeds the modal 3, below
  typicality's LOO minimum, and `FUSED_SCORE_ENABLED` is off in every
  standard-matrix cell by design.

## Recommendations

1. **Do not treat any T-gate pass in this report as certifying GHOST
   detection or cold-start fairness.** Both passes are saturation artifacts.
2. **Re-run the standard matrix at 3 seeds under the persona-assignment fix**
   (`53d59279`) before citing T-3/T-4 pooled evidence anywhere — this
   campaign's pooled N for those two gates is not real independent
   replication.
3. **The core deviation-score/threshold calibration needs its own
   TermSim-scale investigation independent of any Phase 3/5/6 flag** — the
   `no-context` cell shows the saturation is structural, not a
   context-manifest or adaptive-weight side effect. This is squarely in
   scope for whatever plan owns `ACTION_THRESHOLDS` and the pilot's
   3-baseline onboarding assumption.
4. **Design an accretion-sensitive cohort** (or lower the honest-population
   saturation enough that accepted submissions exist to accrete) before
   using TermSim to evaluate baseline-growth drift — the current campaign's
   honest population is too saturated for the accrete/frozen contrast to
   engage.
5. Postgres-backend parity (`--backend postgres`) is implemented and
   test-covered but not exercised in this campaign — Docker was unavailable
   in this environment. Run it once `scripts/local_postgres.sh up` is
   available, per `validation/README.md`.
