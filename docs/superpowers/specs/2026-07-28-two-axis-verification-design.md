# Two-Axis Authorship Verification — scoring-layer redesign

**Status:** Approved design, pre-implementation
**Date:** 2026-07-28
**Amended:** 2026-07-28 — pre-implementation research review (conformal-prediction,
impostors-method/PAN, AI-detector-bias, and selection-bias literature) surfaced
three internal defects in the original draft (§4 G1/G2, §5 band reachability)
and two missing gates (§4 G5, G6). Fixed below; no phase's flag or rollout
order changed.
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

New `validation/calibration_gate.py`, runnable standalone and from CI. Six
numeric gates, each emitting pass/fail + a report row:

| # | gate | criterion | current value |
|---|---|---|---|
| G1 | Same-author FPR | LOO across seminary + public_authors + Plato: pooled flagged rate (≠ no_action) ≤ 5%, **and** the per-corpus / per-N-stratum flagged-rate reported alongside the pooled figure — a pooled 5% can hide individual students or corpora running well above it | 98–100% pooled |
| G2 | Bland impostor | Let `q = min(p_far, p_central)` (the two-sided typicality; q ≈ 0.5 for a squarely-typical sample, q → 0 as either tail becomes extreme). Median `q` for {Eryxias chunks, `validation/corpus/ai_*.txt`} must be **≤** median `q` for same-author holdouts — an impostor must not look *more* typical (higher q) than genuine work | Eryxias ranks #1 most-authentic under the current one-sided metric — i.e. the inequality currently fails in the wrong direction |
| G2b | Bland impostor, paraphrase-resistant | Phase-4 dependency (§8): repeat G2 against `ai_*.txt` essays run through one round of detector-guided paraphrase/self-edit ("elevate the language," per the published attack). Uniformity/too-central features must not be trivially defeated by a single prompt before they leave `DISABLED_FEATURE_GROUPS` | not yet run (new) |
| G3 | Attribution non-regression | `validation/public_authors` top-1 accuracy ≥ 0.7 (existing bar) on impostor-calibrated attribution (`validation/public_authors/run.py`), with raw argmin reported alongside, measured on the author-holdout split defined in §7 (never the split used to derive Fisher weights) | **0.727 — PASSES** (calibrated; raw argmin 0.364, mean rank 1.64; see footnote for how this number was reached) |
| G4 | Career-drift sanity | Plato early→middle→late remains monotone on the typicality (p_far) axis | monotone (passes on raw features) |
| G5 | Selection-bias null control | Shuffle author labels across the pooled corpora, re-derive Fisher-ratio weights (§7) and Phase-4 feature thresholds through the identical pipeline, then re-run G1/G3/G4 on the shuffled assignment. All three must collapse to chance (G1's flagged rate becomes uninformative noise, not ≤5%; G3 → ~1/n_authors; G4 → non-monotone). If the gates still pass on shuffled labels, they are measuring the selection procedure, not authorship signal | not yet run (new) |
| G6 | Non-native-English fairness | Using the existing `native_english` manifest field and `validation/benchmark/bias_slicer.py` / `validation/bias_analysis.py` (same ≤2× FPR-ratio bar those modules already apply elsewhere): per-group flagged rate for the p_central/too-uniform action and the Phase-4 uniformity features must not differ by more than 2× between `native_english=true` and `=false` authentic samples | not yet run (new); `docs/calibration/norm_bounds_calibration_2026-03-17.md` already found a same-direction Tier-1 risk (NNE lexical-diversity 0.45–0.61 vs native 0.64–0.76) |

**G3 baseline footnote.** The original "1.0" in this row was
`median_per_author_auc` from the 2026-07-01 `verify_public_authors_N3`
benchmark (`validation/benchmarks/2026-07-01/verify_public_authors_N3/report.json`)
— a same-author-vs-different-author *verification* metric (pooled AUC 0.855),
not attribution accuracy, and attribution had never actually been measured
before 2026-07-29. That first real attribution run scored 0.455 raw argmin,
which was traced to two instrument defects: TOC-stub corpus entries for
kempis/mill (fixed in 9a4a27b5) and per-author-normalized deviations being
compared across authors, which raw argmin cannot do validly (fixed in
697444ba — G3 now uses impostor-calibrated attribution and reports raw argmin
alongside). With both fixes applied, the 2026-07-30 re-run scored 0.727
calibrated, clearing the bar. The raw-argmin number recorded alongside it —
0.364, *lower* than the original 0.455 — is the more informative of the two:
repairing kempis/mill turned two table-of-contents stubs into genuine
competitors, which made the scale-blind rule worse while the calibrated rule
improved, confirming the diagnosis rather than merely fixing the corpus.

**Why G1 and G2 changed.** Conformal p-values are uniform on their support
under the exchangeable-null hypothesis, so for a same-author holdout
`P(p_far ≤ a) ≈ a` and `P(p_central ≤ b) ≈ b`, and a submission cannot be both
in the top-`a` farthest and the bottom-`b` closest at once. That makes
`P(¬no_action | exchangeable authentic) ≈ a + b` an identity, not a tuning
knob — the original draft's `a=.10, b=.05` therefore flagged ≈15% of
authentic holdouts *by construction*, three times over its own G1 budget.
§5 fixes the band constants to respect `a + b ≤ 0.05`. G2's original wording
("median impostor typicality") was ambiguous between the two tails; a bland
impostor sits at the *central* extreme (p_central → 0, p_far → 1), so a
one-sided reading of "typicality" as p_far alone would have silently passed
Eryxias. `q = min(p_far, p_central)` is low on either tail and is what the
gate must actually threshold.

Notes: G1/G2/G4's corpora are partly synthetic (seminary) and partly
translated-classical (Plato) — targets are provisional until real pilot data
replicates them (see §9 Rollout). G5 and G6 are new gates this amendment adds;
they run once G1–G4 are green and block Phase 3/4 flags independently (a
weight-derivation or feature change that breaks G5 or G6 does not block
Phase 1/2). Gates run with `lock_environment()` and compare flag-on vs
flag-off so every phase shows its delta.

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
   only when the flag is on). Initial constants, chosen so the no_action
   boundary's two tails sum to the G1 budget (.03 + .02 = .05 — see §4):

| condition | action | narrative branch |
|---|---|---|
| p_far > .03 and p_central > .02 | no_action | typical of this student |
| p_far ∈ (.015, .03] | monitor | mild drift |
| p_far ∈ (.005, .015] | schedule_conversation | drift |
| p_far ≤ .005 | escalate | strong drift |
| p_central ≤ .02 | schedule_conversation | **atypically uniform — possible ghost/AI**; never worded as drift |

An authentic submission sits near its own median → p_far ≈ 0.5 → `no_action`
by construction, on any corpus, any weights, any length, **at any N ≥ 2**.
That part of defects 1 and 2 is fixed structurally rather than by re-tuning a
constant, and does not depend on the table above being reachable.

**Reachability is a separate property from correctness, and satisfying G1
makes it worse, not better.** A conformal p-value is quantized at 1/(N+1); a
band boundary at threshold `t` is reachable at all only once N ≥ 1/t − 1
(below that N, *no* possible ranking can produce a p-value that small, and
the condition is either always true or always false). Tightening the
no_action boundary to satisfy G1 (`.10/.05` → `.03/.02`) raises that floor:

| band boundary | old threshold (pre-amendment) | min N to reach it | new threshold | min N to reach it |
|---|---|---|---|---|
| leave no_action (far side) | .10 | 9 | .03 | 33 |
| leave no_action (central side) | .05 | 19 | .02 | 49 |
| escalate (far side) | .01 | 99 | .005 | 199 |

With per-student baselines of 4–15 samples (the modal case this redesign
targets — see the Problem §1 seminary numbers), **none of these boundaries
are reachable in the pilot's normal operating range, before or after this
amendment.** Fixing G1 cannot also make the conformal axis discriminating at
small N; the two goals trade off directly through the same 1/(N+1) floor, and
no choice of constants resolves both. This is a structural property of
finite-sample conformal p-values, not an implementation gap to close later.

**What this means for the design.** Phase 1 alone delivers Goal 1 (authentic
work reaches `no_action`) at every N, because that claim rests on the
*typical rank* of a genuine sample, not on resolving small p-values. It does
**not** deliver fine-grained drift escalation at pilot-typical N — that
continues to depend on the retained catastrophic override (below) until a
student's baseline grows past the reachability floor, which for most
students will be months to years away, if ever. Escalation-relevant signal
at small N is therefore Phase 2's (identity axis, a continuous LLR — no
quantization floor) and Phase 4's (uniformity ratios feed the ordinary
z-score machinery — same) job, not Phase 1's. The band table above matters
for the large-N validation corpora (Plato n=199, public_authors) where G1/G4
are actually measured, and for whichever students eventually accumulate
enough baseline history to resolve it.

**Cold start, stated honestly.** Behavior: N < 5 → legacy scale + low-confidence
note (current behavior); 5 ≤ N < 33 → typicality drives no_action only
(monitor/schedule/escalate via p_far are unreachable at these thresholds
until N ≈ 33, per the table above); N ≥ 33 → full band table, still subject
to each band's own reachability floor. **The legacy catastrophic-drift
override (rms_z ≥ 3) is retained unconditionally at every N**, including
N ≥ 33 — it is the only escalation path available below each band's
reachability floor, and Phase 1 must not narrow it to a specific N-tier.
This replaces fake precision at N=3 with explicit uncertainty, and replaces
an implicit "N ≥ 9 solves it" claim with the actual number.

**API surface.** `deviation_score` continues to be computed and returned
unchanged (downstream consumers, trend charts). New response fields:
`typicality_p_far`, `typicality_p_central`, `typicality_band`,
`typicality_n` (the N behind the p-values). `recommendation.action` switches
source only under the flag.

**Touch points.** `original/quantum/scoring.py` (after rms_z, before tanh);
`original/quantum/state.py` (LOO cache); `original/schemas.py` +
`_shared.py::_to_response()` (new fields — this function actually lives in
`original/routers/_shared.py`, re-exported from `api.py` for compatibility);
`original/quantum/professor_narrative.py` (too-uniform branch, plus adding
the currently-missing "style has legitimately evolved" hypothesis);
`ScoringConfig.from_env()` (flag plumbing, following the wiring pattern of
`ADAPTIVE_WEIGHTS_ENABLED`/`AI_LIKELIHOOD_ENABLED`: env read in
`original/routers/students_scoring.py`, computed value threaded into
`score()` as a new argument, result attached onto `Layer7Output` for
`_to_response()` to surface).

**A different, one-sided conformal system already exists and is live — this
is a coexistence point, not a naming coincidence.** `original/quantum/conformal.py`
(`conformal_pvalue`, `verdict_from_pvalue`) computes a p-value from
`quantum_fidelity` against a per-student calibration set of
instructor-confirmed-authentic fidelities (`store.get_authentic_fidelities`,
populated by `put_fidelity_score`) — a fundamentally different axis (fidelity,
not rms_z-distance) and calibration mechanism (accumulated feedback, not LOO
over baseline samples) from this phase's typicality axis. It only activates
under `AMPLITUDE_SCORING_ENABLED=1` with a non-empty calibration set, and
today only *nudges the action severity up* (`scoring.py:1053-1084`, inside
`_recommend`) — it never lowers it, and never fires alone. It is also
one-sided in exactly defect 2's sense (only "unusually low fidelity" is
anomalous; a bland/maximally-central submission scores p≈1 and is invisible
to it) — this phase's `p_central` axis is not redundant with it. Coexistence
rule: Phase 1's band table replaces only the `ACTION_THRESHOLDS`-on-deviation
step (`scoring.py:1022-1029`); the entanglement/ghostwriting override
(`1031-1051`) and this existing fidelity-conformal nudge (`1053-1084`)
continue to apply, unmodified, on top of whatever action the typicality
bands produce — the same way they already layer on top of the deviation-score
action today. Do not rename or restructure `conformal.py`; the new module is
`original/quantum/typicality.py`, a distinct file for a distinct axis.

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

**Caveats carried over from the impostors-method literature this axis
descends from.** (1) A raw score against a comparison pool is not a
calibrated likelihood ratio by construction — the forensic-comparison
standard for this is Cllr (discrimination + calibration loss), and the
gate runner's job above should report it, not just re-fit two cut-points.
(2) Fixed cut-points transfer poorly across pools of different size and
composition (documented instability in the PAN impostors literature); small
or skewed per-tenant pools should prefer the pool's own rank statistics over
the global .45/.60 constants, and the degrade-to-axis-1 floor exists for
exactly this reason. (3) The method's original validation regime is
2000+-word documents; 300–500-word student essays are well outside it, so
the identity axis should be expected to be noisier per-submission than the
Plato-corpus numbers in §1 suggest, and (4) "fits peers better than the
claimed author" cannot, by itself, name an author outside the tenant's
pool — an outside ghostwriter is invisible to this axis unless their style
also happens to resemble a pool member. The action matrix below treats
`> .60` as a signal to investigate, not a positive identification.

## 7. Phase 3 — Feature hygiene (`MEASURED_WEIGHTS=1`; bounds refresh)

**Author-level holdout split, required before either step below.** Deriving
weights and bounds on the same corpora that G1/G3/G4/G6 then gate against is
circular: the selection statistic (Fisher ratio) and the gate statistics
(FPR, attribution accuracy) share the same between/within-author variance
structure, so gate results measured this way are optimistic by construction,
not merely at risk of it — this is the textbook selection-bias failure mode
(feature selection on the full dataset before cross-validation), and it is
large in practice, not a rounding error. Fix: split each corpus (public_authors,
seminary, Plato) into a weight-derivation set and a gate-evaluation set **at
the author level** (an author's samples never appear on both sides), before
either step runs. `validation/stability/stability.py`'s `fisher_ratio` takes
no split argument today — `scripts/derive_measured_weights.py` owns the split
and passes only the derivation-side authors in. G5 (§4) is the runnable check
that this split is actually enforced, not just intended.

1. **Measured weights.** Per-feature Fisher ratio (between-author /
   within-author variance) computed on the derivation split via the existing
   `validation/stability/stability.py` machinery; aggregated per tier;
   Σw²-preserving normalization (same invariant the length schedule uses).
   Expected direction from measurement: T1/T5 up, T4/T16 sharply down. Weight
   table committed as a generated artifact with its derivation script, not
   hand-edited. Raw within-author variance is unreliable at n=4–15 samples
   per author (the Fisher ratio's own denominator, noisiest on exactly the
   low-variance features the ratio rewards most) — shrink it with the same
   Ledoit-Wolf machinery already used for `RANK_REMEDIATION=shrinkage`
   (`quantum/state.py:190`) rather than using the raw per-author estimate.
2. **NORM_BOUNDS refresh.** `scripts/calibrate_bounds.py` percentile table on
   the derivation split; target < 5% saturation per feature (27/103 currently
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

**Store raw second moments, not baked-in ratios.** The four comparison
features must extract as raw per-document dispersion values in
`feature_vector()` (ordinary feature-purity contract, like every other
feature) and let the existing z-score/`NORM_BOUNDS` machinery do the
baseline comparison — not compute `÷ baseline` at extraction time. Baking
the ratio in breaks feature purity, makes G3's attribution comparison and
G6's fairness slicing (§4) undefined for this group (there is no raw value
to slice by group), and duplicates normalization logic the rest of the
pipeline already owns.

**This group carries a documented fairness risk, not just a measurement
one.** The same low-linguistic-variability signature these features target
is also the mechanism behind measured AI-detector bias against non-native
English writers (population false-positive rates over 50% in published
audits, versus near-zero for native writers) — uniformity is a proficiency
proxy before it is an authorship signal. Accordingly this group has two
gate dependencies before it may leave `DISABLED_FEATURE_GROUPS`, both new
in this amendment: **G6** (§4 — per-group FPR parity by `native_english`)
and **G2b** (§4 — the bland-impostor gate must still hold after a single
round of detector-guided paraphrase, since that is a published, low-effort
attack against exactly this feature family). Neither gate existed in the
original draft; this group should not ship enabled without both green.

⚠ `constants.py` feature-ordering change: explicit permission asked at
implementation time, per CLAUDE.md.

---

## 9. Rollout

1. Gates green on flag-on config, all six (G1–G6), in CI.
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
5. **Before any tenant flip, multiply the nominal FPR by that tenant's
   submission volume, not just the per-submission rate.** A 5% per-submission
   FPR across a term's worth of submissions is a per-population false-accusation
   count, and that count — not the percentage — is what a pilot institution
   will judge the feature against (this is the same arithmetic that led
   Vanderbilt to disable a vendor AI-detector advertising a 1% FPR after
   computing it implied ~750 false flags at their submission volume). Report
   this number to each pilot tenant before flipping their flag, not just the
   nominal gate percentage.

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
- **Threshold provenance.** The typicality bands (§5) and .45/.60 identity
  bands are initial choices to be re-derived by the gate runner; the spec
  commits to the *mechanism* (probability units, empirical calibration), not
  to these constants.
- **Conformal resolution floor.** The 1/(N+1) quantization means the drift
  and too-central bands in §5 are unreachable for the pilot's modal N (4–15)
  regardless of threshold choice, and tightening thresholds to satisfy G1
  raises the reachability floor further, not lower. This is inherent to
  finite-sample conformal p-values, not a bug to be tuned away; it is why
  the retained rms_z ≥ 3 override, the identity axis, and the uniformity
  features (none of which share this floor) carry escalation at small N.
- **Marginal, not per-student, validity.** Conformal coverage guarantees are
  marginal — averaged over calibration-set draws — not conditional on one
  fixed student's baseline. A pooled 5% FPR (G1) can coexist with a
  meaningful fraction of individual students running well above it purely
  from small-calibration-set variance, independent of any real drift. G1 now
  reports the per-corpus/per-N distribution, not just the pooled mean, for
  this reason (§4), but the underlying variance does not disappear.
- **Selection bias in Phase 3.** Deriving Fisher-ratio weights on the same
  corpora the calibration gates score against is circular and measurably
  optimistic in comparable feature-selection settings. §7's author-level
  holdout split and G5's permutation-null control (§4) are the guard; without
  them, a passing gate battery would not establish the claimed error rates.
- **Uniformity-feature fairness and robustness.** The "too central/uniform"
  signal (p_central, Phase 4 features) is mechanistically the same signal
  documented to misfire against non-native English writers in published
  AI-detector bias audits, and is defeated by a single round of
  detector-guided paraphrase in published attacks against the same feature
  family. G6 and G2b (§4) gate this before Phase 4 leaves
  `DISABLED_FEATURE_GROUPS`; absent real pilot L2/proficiency data, treat
  any p_central-driven action as a low-confidence tripwire, not a finding.
- **Identity-axis calibration.** `llr_deviation_score` is a raw comparison
  score, not a forensically calibrated likelihood ratio; the .45/.60 cut-points
  are provisional in the same sense the impostors-method literature warns
  fixed thresholds are pool-dependent (§6). Treat Phase 2's action-matrix
  cells as investigative triggers, not evidentiary conclusions — this is
  also why `> .60` cannot be read as "identifies an outside ghostwriter"
  (§6): the identity axis can only compare against tenants actually in the
  pool.

## 11. Deliverables

| path | content |
|---|---|
| `validation/calibration_gate.py` | Phase 0 gates G1–G6 (G1/G2 corrected, G2b/G5/G6 new) |
| `original/quantum/typicality.py` | LOO distribution + conformal p (pure, unit-tested) |
| `original/quantum/scoring.py` | flag-gated integration, action matrix |
| `original/quantum/state.py` | LOO cache |
| `original/schemas.py`, `original/api.py` | new response fields |
| `original/quantum/professor_narrative.py` | too-uniform + legitimate-evolution branches |
| `original/features/uniformity.py` | Phase 4 feature group (disabled by default; raw second moments, not baked-in ratios — §8) |
| `scripts/derive_measured_weights.py` | Phase 3 weight derivation, owns the author-level holdout split (§7), emits committed artifact |
| `tests/quantum/test_typicality.py` + gate tests | coverage for all of the above, including G5's permutation-null control |

Env flags added: `TYPICALITY_SCORING`, `TYPICALITY_SHADOW`, `IDENTITY_AXIS`,
`MEASURED_WEIGHTS` — all default `0`, documented in CLAUDE.md's flag table as
part of implementation.
