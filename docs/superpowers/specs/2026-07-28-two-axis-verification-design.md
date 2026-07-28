# Two-Axis Authorship Verification — scoring-layer redesign

**Status:** Approved design, pre-implementation
**Date:** 2026-07-28
**Prior work:** `docs/superpowers/specs/2026-07-27-plato-chronology-design.md` (the
Plato study that produced the diagnosis), `validation/plato/` (corpus, probes,
and measurements cited below).

---

## 1. Problem

The Plato chronology study surfaced three defects in the scoring layer. All
three were verified by direct measurement against the real
`original.quantum.scoring.score()` path (reimplementation cross-checked to
max |Δ| = 0.015 on 25 scored essays).

### Defect 1 — the deviation scale assumes a statistical impossibility

```
deviation = tanh(rms_z / 1.5),   rms_z = sqrt(Σ(clip(z,±4)·w·active)² / n_active)
```

A submission genuinely drawn from the author's own distribution has E[z²] = 1
by definition, so its expected rms_z is the RMS tier weight — **≈ 1.07** for
the current feature set. The calibration comment at
`original/quantum/scoring.py:670` assumes same-author holdouts land at
rms_z ≈ 0.6. Measured same-author leave-one-out rms_z:

| corpus | same-author LOO rms_z | flagged (≠ no_action) |
|---|---|---|
| assumed in the code comment | 0.6 | — |
| Plato, 2000-word chunks, own work as baseline | 1.03 | 99% (n=199) |
| Seminary essays (repo's own corpus, 310–460 words) | 1.18 | **100%** (n=25) |

`no_action` requires rms_z < 0.635 — an authentic sample would need to be
~40% closer to the baseline mean than baseline samples themselves are. The
band is mathematically unreachable for honest work. A student scored against
four of their own essays never receives `no_action`; 3 of 25 escalate.

### Defect 2 — one-sided distance rewards blandness

Distance-from-centroid treats "closest to the mean" as "most authentic". Real
same-author samples live in an annulus (rms_z ≈ 1) around the centroid, not at
the center. Text at the center is anomalous in the too-perfect direction — and
that is where mean-reverting, low-variance text lives: LLM output and cautious
forgeries.

Measured: **Eryxias** — near-universally judged spurious; Gutenberg's own
title page reads "By a Platonic Imitator" — scores as the *most authentic*
non-baseline text in the Plato corpus (mean |z| 0.67 / deviation 0.571),
beating all nine genuine early dialogues. It is more central than the median
genuine dialogue on 53 of 76 active features. There is no "too typical" test
anywhere in the pipeline.

### Defect 3 — weights and bounds were never validated for discrimination

`TIER_WEIGHTS` are hand-set. Measured discrimination (translator-vs-chronology
tier decomposition, `validation/plato/diagnostics.py`):

- T1 (surface) and T5 (POS/syntax) carry the authorial/career signal
  (career Δ|z| +0.8 and +0.5) — weighted 1.0 and 1.2.
- T4 (char/punct) and T16 (citation) carry edition/format noise (T4 = 27% of
  the translator gap; both dead flat across Plato's career) — weighted 1.3
  and 1.4, i.e. the noisiest tiers get the highest weights.
- 27 of 103 features sat saturated at their `NORM_BOUNDS` clip on real prose,
  contributing masked noise or nothing.

### Why the existing suite never caught this

Validation reports AUC (`validation/verify/`: median per-author AUC 1.0). AUC
is invariant to monotone rescaling — ranking stays perfect while every
absolute threshold is wrong. Nothing measures same-author false-positive rate
at the action bands, and nothing tests a bland impostor.

---

## 2. Goals and non-goals

**Goals**

1. Authentic same-author work reaches `no_action` at a controlled rate
   (target ≥ 95% under leave-one-out on validation corpora).
2. Bland/AI-like text stops scoring as maximally authentic; "too uniform"
   becomes a first-class, separately-narrated signal.
3. Distinguish benign drift (growth) from identity mismatch, using evidence
   rather than the current unconditional ×0.75 dampening.
4. Feature weights and bounds derived from measured discrimination.
5. A calibration CI gate so these regressions cannot ship silently again.

**Non-goals**

- No change to default behavior: every phase is env-flagged, default OFF,
  Phase-1-byte-identical (CLAUDE.md rule).
- Not replacing the 103-feature pipeline or `StudentState` — both measured
  sound (T1/T2/T5/T15 carry real signal; ρ machinery kept).
- Not an AI-detector: the AI-likelihood scorer (`AI_LIKELIHOOD_*`) remains a
  separate, corpus-level system. This work fixes the *verification* metric.

---

## 3. Architecture

```
                     ┌─ Axis 1: TYPICALITY (conformal, per-student) ──┐
submission ──rms_z──►│ percentile within the student's own LOO        │──┐
                     │ distance distribution; TWO-SIDED               │  │
                     └────────────────────────────────────────────────┘  ├─► action
                     ┌─ Axis 2: IDENTITY (impostor LLR, per-tenant) ──┐  │   matrix
                     │ fits claimed author vs peer pool               │──┘
                     │ (existing llr_deviation_score, promoted)       │
                     └────────────────────────────────────────────────┘
                     ┌─ UNIFORMITY feature group (2nd moments) ───────┐
                     │ within-document spread vs baseline spread      │──► feeds both axes
                     └────────────────────────────────────────────────┘
```

Build order: **gates → Phase 1 → Phase 4 (features, disabled) → Phase 2 →
Phase 3 → shadow rollout.** Each phase lands independently behind its flag.

---

## 4. Phase 0 — Calibration gates (built first)

New `validation/calibration_gate.py`, runnable standalone and from CI. Four
numeric gates, each emitting pass/fail + a report row:

| # | gate | criterion | current value |
|---|---|---|---|
| G1 | Same-author FPR | LOO across seminary + public_authors + Plato: ≤ 5% of held-out authentic samples flagged (≠ no_action) | 98–100% |
| G2 | Bland impostor | Eryxias chunks and `validation/corpus/ai_*.txt` essays must NOT out-rank same-author holdouts on the authenticity ordering (specifically: median impostor typicality < median same-author holdout typicality) | Eryxias ranks #1 most-authentic |
| G3 | Attribution non-regression | `validation/public_authors` top-1 accuracy ≥ 0.7 (existing bar) | 1.0 (passes) |
| G4 | Career-drift sanity | Plato early→middle→late remains monotone on the typicality (p_far) axis | monotone (passes on raw features) |

Notes: G1's corpora are partly synthetic (seminary) and partly
translated-classical (Plato) — the 5% target is provisional until real pilot
data replicates it (see §9 Rollout). Gates run with `lock_environment()` and
compare flag-on vs flag-off so every phase shows its delta.

## 5. Phase 1 — Conformal typicality (`TYPICALITY_SCORING=1`)

**Mechanics.** For a `StudentState` with N contributing baseline samples:

1. For each baseline sample i: compute rms_z of sample i against baseline
   statistics (mean, adaptive-floored std, active mask) built from the other
   N−1 samples. This yields the student's empirical LOO distance distribution
   {r₁…r_N}. Cached on the state; recomputed on sample add (O(N·D)).
2. For a submission with distance r_sub:

```
p_far     = (1 + #{i : r_i ≥ r_sub}) / (N + 1)      # drift side
p_central = (1 + #{i : r_i ≤ r_sub}) / (N + 1)      # too-perfect side
```

3. Action from probability bands (replaces `ACTION_THRESHOLDS`-on-deviation
   only when the flag is on):

| condition | action | narrative branch |
|---|---|---|
| p_far > .10 and p_central > .05 | no_action | typical of this student |
| p_far ∈ (.05, .10] | monitor | mild drift |
| p_far ∈ (.01, .05] | schedule_conversation | drift |
| p_far ≤ .01 | escalate | strong drift |
| p_central ≤ .05 | schedule_conversation | **atypically uniform — possible ghost/AI**; never worded as drift |

An authentic submission sits near its own median → p_far ≈ 0.5 → `no_action`
by construction, on any corpus, any weights, any length. Both defects 1 and 2
are fixed structurally rather than by re-tuning a constant.

**Cold start, stated honestly.** Conformal p is quantized at 1/(N+1): at N=5
the minimum reachable p_far is 0.167, so the typicality axis cannot escalate.
Behavior: N < 5 → legacy scale + low-confidence note (current behavior);
5 ≤ N < 9 → typicality drives no_action/monitor only, escalation still
requires the legacy catastrophic-drift override (rms_z ≥ 3 retained
unchanged); N ≥ 9 → full band table. This replaces fake precision at N=3 with
explicit uncertainty.

**API surface.** `deviation_score` continues to be computed and returned
unchanged (downstream consumers, trend charts). New response fields:
`typicality_p_far`, `typicality_p_central`, `typicality_band`,
`typicality_n` (the N behind the p-values). `recommendation.action` switches
source only under the flag.

**Touch points.** `original/quantum/scoring.py` (after rms_z, before tanh);
`original/quantum/state.py` (LOO cache); `original/schemas.py` +
`api.py::_to_response()` (new fields); `original/quantum/professor_narrative.py`
(too-uniform branch, plus adding the currently-missing "style has legitimately
evolved" hypothesis); `ScoringConfig.from_env()` (flag plumbing).

## 6. Phase 2 — Identity axis (`IDENTITY_AXIS=1`, requires `NULL_MODEL=impostor`)

`llr_deviation_score` (`scoring.py:377`, `null_pool.py`) already computes the
right quantity and is attach-only. Semantics: ≈ 0 fits the claimed author
better; ≈ 0.5 indistinguishable from peers; ≈ 1 fits peers better. Bland/AI
text fits everyone → lands ≈ 0.5+, which is the tell axis 1 alone cannot see.

**Action matrix** (typicality × identity):

| | identity < .45 distinctively theirs | .45–.60 non-distinctive | > .60 fits others better |
|---|---|---|---|
| **typical** | no_action | monitor | schedule_conversation |
| **too-far** | monitor — *genuine drift, likely benign growth* | schedule_conversation | escalate |
| **too-central** | monitor | **schedule_conversation — AI/ghost signature** | escalate |

The (too-far, distinctively-theirs) cell finally implements drift-vs-fraud on
evidence, replacing the unconditional trajectory ×0.75 dampening — which is
disabled under the flag (the trajectory result remains reported).

Identity band cut-points (.45/.60) are provisional; Phase 0's gate runner
re-derives them empirically from peer-pool LOO before the flag ships.
Degrades to axis-1-only when the pool is below the existing floors
(3 students / 5 vectors). Pool remains per-tenant (no cross-tenant leakage —
existing `null_pool.py` scoping).

## 7. Phase 3 — Feature hygiene (`MEASURED_WEIGHTS=1`; bounds refresh)

1. **Measured weights.** Per-feature Fisher ratio (between-author /
   within-author variance) computed across `public_authors` + seminary +
   Plato via the existing `validation/stability/stability.py` machinery;
   aggregated per tier; Σw²-preserving normalization (same invariant the
   length schedule uses). Expected direction from measurement: T1/T5 up,
   T4/T16 sharply down. Weight table committed as a generated artifact with
   its derivation script, not hand-edited.
2. **NORM_BOUNDS refresh.** `scripts/calibrate_bounds.py` percentile table on
   the pooled corpora; target < 5% saturation per feature (27/103 currently
   saturate). Requires `scripts/reextract_baselines.py` for stored profiles.
   Interim, lower-risk step: winsorize-then-squash at the bounds instead of
   hard clipping, no stored-profile impact.

⚠ Both items touch `original/constants.py` (`TIER_WEIGHTS` semantics /
`NORM_BOUNDS`), which is on the CLAUDE.md explicit-permission list —
implementation asks separately, with the concrete before/after diff, at the
moment of change.

## 8. Phase 4 — Uniformity feature group (second moments)

Current features are per-document means; generation artifacts live in the
spread. New group `uniformity` (~6 features, appended — never reordered — to
`ALL_FEATURE_CODES`; FEATURE_DIM 103 → 109):

| code | measures |
|---|---|
| `sentence_length_dispersion_ratio` | within-doc sentence-length CV ÷ baseline typical CV |
| `window_feature_variance_ratio` | variance of cheap T1 features over 3-sentence windows ÷ baseline |
| `function_word_burstiness_ratio` | function-word inter-arrival dispersion ÷ baseline |
| `punctuation_dispersion_ratio` | per-window punctuation-rate variance ÷ baseline |
| `vocab_introduction_flatness` | decay-curve fit of new-type introduction rate |
| `clause_depth_variance_ratio` | per-sentence clause-depth variance ÷ baseline |

Ratios < 1 ⇒ suspiciously uniform. Four are comparison features (need a
baseline), two standalone. Ships inside `DISABLED_FEATURE_GROUPS` by default —
the proven tier-17 pattern — so default output is byte-identical until gates
pass. Legacy-width profile loading already pads (74/89 → current); the
103 → 109 path uses the same mechanism.

⚠ `constants.py` feature-ordering change: explicit permission asked at
implementation time, per CLAUDE.md.

---

## 9. Rollout

1. Gates green on flag-on config, all four, in CI.
2. **Shadow mode** (`TYPICALITY_SHADOW=1`, mirroring the existing
   `AI_LIKELIHOOD_SHADOW` pattern): pilot computes both verdicts, logs
   divergence, surfaces nothing. Existing `scripts/shadow_report.py` shape
   reused for the divergence report.
3. Flip `TYPICALITY_SCORING` in demo first, then pilot tenants, only after
   real (non-synthetic) student data confirms the same-author FPR — the
   seminary corpus is synthetic and the Plato corpus is translated classical
   prose; neither is the deployment distribution.
4. Identity axis and measured weights follow the same shadow-then-flip path
   independently.

## 10. Risks and open questions

- **Exchangeability.** Conformal p-values assume baseline samples are
  exchangeable. Genre-mixed baselines widen the LOO distribution (lower
  sensitivity, not false positives — the safe failure direction). Genre
  stratification via the context manifest is a later refinement.
- **N inflation.** Recency weighting (`RECENCY_DECAY`) is not applied inside
  the LOO distribution in Phase 1 (samples treated equally). Whether decay
  belongs in the typicality axis is deliberately deferred — it is the same
  open question the Plato study raised about drift absorption.
- **Adaptive-weights interaction.** `ADAPTIVE_WEIGHTS_ENABLED` and
  `LENGTH_ADAPTIVE_WEIGHTS` change rms_z; the LOO distribution must be
  computed under the same weight configuration as scoring (implementation
  invariant, gate-checked).
- **Synthetic validation data.** G1/G2 numbers are provisional until pilot
  replication (§9.3).
- **Threshold provenance.** The .05/.10/.01 typicality bands and .45/.60
  identity bands are initial choices to be re-derived by the gate runner;
  the spec commits to the *mechanism* (probability units, empirical
  calibration), not to these constants.

## 11. Deliverables

| path | content |
|---|---|
| `validation/calibration_gate.py` | Phase 0 gates G1–G4 |
| `original/quantum/typicality.py` | LOO distribution + conformal p (pure, unit-tested) |
| `original/quantum/scoring.py` | flag-gated integration, action matrix |
| `original/quantum/state.py` | LOO cache |
| `original/schemas.py`, `original/api.py` | new response fields |
| `original/quantum/professor_narrative.py` | too-uniform + legitimate-evolution branches |
| `original/features/uniformity.py` | Phase 4 feature group (disabled by default) |
| `scripts/derive_measured_weights.py` | Phase 3 weight derivation (emits committed artifact) |
| `tests/quantum/test_typicality.py` + gate tests | coverage for all of the above |

Env flags added: `TYPICALITY_SCORING`, `TYPICALITY_SHADOW`, `IDENTITY_AXIS`,
`MEASURED_WEIGHTS` — all default `0`, documented in CLAUDE.md's flag table as
part of implementation.
