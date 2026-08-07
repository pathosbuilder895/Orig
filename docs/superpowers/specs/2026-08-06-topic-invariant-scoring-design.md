# Topic-Invariant Scoring via Variance Inflation — Design

**Date:** 2026-08-06
**Status:** Approved, not yet implemented
**Owner:** scoring / validation
**Flag:** `TOPIC_VARIANCE_INFLATION` (default `0`)

Continues `2026-07-27-genre-shift-harness-design.md`, which built the harness
that measured the problem this spec fixes.

---

## Problem

A student who writes three papers on Pauline soteriology and then one on
patristic ecclesiology must not be flagged for it. Today they often are.

The failure is in the z-score denominator. Scoring standardises with

```
z = (submission − baseline_mean) / baseline_std
```

(`original/quantum/scoring.py:699`), where `baseline_std` is estimated from
that student's own authenticated samples. Those samples usually span a narrow
topic range, so `sigma` encodes *"how much this student varies while writing
about the same things."* Hand them a new topic and the topic-sensitive
features move several sigma — not because the author changed, but because
sigma was estimated on too narrow a slice. `rms_z` inflates, the deviation
score climbs, the recommended action escalates.

This is measured, not inferred. `validation/genre_crossgenre_2026-08/`
ran leave-one-genre-out over 13 C.S. Lewis works in 6 genre buckets against a
G.K. Chesterton impostor pool:

| genre | raw `deviation_score` AUC |
|---|---|
| Narnia | 0.076 |
| Space Trilogy | 0.397 |
| Theology | 0.374 |
| Memoir | 0.350 |
| Essays | 0.518 |
| Satire | 0.608 |
| **mean** | **0.387** |

AUC below 0.5 means the ranking is **inverted**: genuine Lewis writing in an
unseen register scores *more* anomalous than a different author entirely.

### Why the three existing mitigations are not enough

1. **`topic.novelty == "high"`** (`original/context/manifest.py:245`)
   attenuates tiers 10 and 15 only — two tiers of eighteen, on a hard
   threshold.
2. **The tier 2/3/9/10 attenuation** that the tier ablation actually found
   helpful is gated on `genre_covered_by_baseline`, which is **inert**:
   `resolve_genre` puts 84% of real prose into rule 8's terminal `else`
   (`correspondence`), so the gate essentially never fires. Documented at
   `original/context/weighting.py:78`.
3. **`LLR_ACTION_MODE=gate`** (today's default) cuts genuine-Lewis false
   positives at `schedule_conversation+` from 50.1% to 42.4%.

**42.4% of genuine cross-topic submissions still trigger a conversation.**
That is the number this work moves.

---

## Approach

Do not delete features when the topic shifts. **Widen the band.**

Scale each feature's sigma as a function of how far the submission's topic sits
from the student's baseline, multiplied by how much that particular feature is
known to drift when *the same author* changes subject. The model then says:
"we have never seen this student write about this, so we are genuinely less
certain what their adjective rate should be" — rather than "ignore adjective
rate."

### Alternatives rejected

**Rewire the dead gate only.** Give the existing, already-tested tier 2/3/9/10
attenuation a gate that fires, by swapping broken genre classification for the
working topic-distance signal. Cheapest path, and it remains a reasonable
fallback if this design fails validation. Rejected as the primary approach on
two grounds: that tier set is explicitly unvalidated
(`original/context/weighting.py:88`), and tier granularity is too coarse —
`lexical_chain_density` is a **tier 2** feature ranked near the top of the
DNA invariance table, so attenuating tier 2 wholesale discards one of the most
topic-invariant signals available.

**Topic-matched reference set.** Score against the topically nearest subset of
the student's baseline via the existing `match_baseline_cluster`. Most
principled, but blocked by data: a pilot student with 3–5 baseline samples has
no topically near subset, and the `anchor_only` fallback already fires in
exactly that case.

**Per-feature "DNA" reweighting.** Already tried and already failed to
generalise — see the interaction note below.

### Why this is not the DNA vector that failed

`validation/genre_crossgenre_2026-08/dna_analysis.py` computes

```
dna(f) = separation(f) / (genre_drift(f) + within_noise(f))
```

and `original/context/weighting.py:66` records that this vector "does NOT
generalize as a blanket replacement — it actively hurts same-genre
discrimination."

The non-generalising component is the **numerator**. `separation` is
`|mean_lewis − mean_chesterton|`, measured against exactly one contrast
author; `dna_analysis.py` prints that caveat itself.

This design uses only `genre_drift / within_noise` — a purely *within-author*
quantity with no contrast author in it. The specific reason the DNA
reweighting failed does not apply. That is an argument for trying it, not a
guarantee it works, which is what §"Validation" is for.

---

## Mechanism

```
d         = manifest["topic"]["baseline_distance"]          # ∈[0,1], already computed
d_eff     = clip((d − 0.25) / 0.75, 0, 1)                   # 0.25 = TOPIC_NOVELTY_BOUNDS["low"]
s_norm    = clip(TOPIC_SENSITIVITY / median(TOPIC_SENSITIVITY), 0, TOPIC_INFLATE_MAX)
sigma_eff = sigma × (1 + TOPIC_INFLATE_GAIN × d_eff × s_norm)
```

`d` requires no new computation: `resolve_topic`
(`original/context/resolvers.py:265`) already produces it as TF-IDF cosine
distance from the submission to the student's baseline centroid.

The median in `s_norm` is taken over MEASURABLE features only, per
`validation/measurability.py` — blank, scoring-only, and disabled columns are
excluded, and aggregating over them would raise `MeasurabilityError`.

### Properties

- **`d ≤ 0.25` → exact identity.** `d_eff` is zero, so the multiplier is
  exactly 1.0 and output is bit-for-bit unchanged. Ordinary same-topic
  submissions are untouched *by construction*, not by threshold luck. Reuses
  the already-calibrated `TOPIC_NOVELTY_BOUNDS["low"]`.
- **Monotone in `d`.** No cliff — the brittleness of the current
  `novelty == "high"` rule.
- **Per-feature, not per-tier.** `semicolon_colon_rate` (lowest drift in the
  DNA table) barely inflates; `theological_register_score` (a genre chameleon
  at the bottom) inflates most.
- **Bounded.** `TOPIC_INFLATE_MAX` caps `s_norm`, so no feature is ever
  effectively deleted — unlike `mute`, and unlike attenuation's fixed 0.6.

### Why sigma rather than weights

For a feature not at the winsorisation cap, inflating sigma by *k* is
algebraically equivalent to attenuating that feature's weight by *1/k* inside
`rms_z`. Stated plainly so nobody rediscovers it mid-implementation and
concludes the design is confused.

Sigma is still the correct lever, for three concrete reasons:

1. **The ±4 cap.** `z` is winsorised before weighting
   (`original/quantum/scoring.py:733`). Under a topic shift, topic-sensitive
   features saturate that cap, where further deviation is invisible and only
   weight remains. Inflating sigma pulls them back under the cap where they
   discriminate again. Weight attenuation cannot do this — this is where the
   two stop being equivalent.
2. **Propagation.** `sigma` feeds the amplitude/fidelity path via
   `baseline_std_override` (`original/quantum/scoring.py:838`), keeping the
   correction coherent across both scoring routes rather than applying to
   `rms_z` alone.
3. It states the actual claim, which the professor narrative has to say out
   loud: *less certain*, not *less important*.

---

## Deriving `TOPIC_SENSITIVITY`

New: `validation/topic_sensitivity_2026-08/derive.py`, following the
`LENGTH_WEIGHT_SCHEDULE` precedent — offline derivation, committed vector,
re-derivation command in the docstring.

Per author *A* with ≥2 works:

```
drift_A(f) = std over per-work means of f
noise_A(f) = pooled within-work std of f
s_A(f)     = drift_A(f) / (noise_A(f) + eps)

TOPIC_SENSITIVITY(f) = median over authors of s_A(f)
```

Median rather than mean: robust to one author with an idiosyncratic corpus.

### Corpora

Both already exist and are already chunked.

- **`validation/public_authors/cross_work_manifest.json`** — six authors
  (Dickens, Chesterton, Christie, Emerson, Mill, Thoreau), per-chunk `work_id`
  labels, and a strict "a work appears in exactly one of baseline or probe"
  split rule.
- **`validation/genre_crossgenre_2026-08/`** — C.S. Lewis, 6 hand-labelled
  genre buckets. Raw text is not committed (still under US/UK copyright);
  `clean_corpus.py`'s `MANIFEST` has the fetch URLs, and
  `extract_vectors.py` regenerates `vectors.npy` in ~10 min for 560 chunks.

### Hold-out discipline

Derive on the six-author corpus, validate on Lewis. Then derive on Lewis,
validate on the six. **Both directions must clear G7.**

Deriving and evaluating on Lewis alone is precisely how the DNA vector came to
look excellent and then fail. One direction is not evidence.

`TOPIC_INFLATE_GAIN` and `TOPIC_INFLATE_MAX` are swept on the derivation
corpus and then **fixed** before the hold-out is touched. Tuning gain against
the hold-out silently converts it into a training set.

Sweep grid: `GAIN ∈ {0.25, 0.5, 1.0, 1.5, 2.0}` × `MAX ∈ {2.0, 3.0, 5.0}`.

**Grid must be sized against the reachable range, `d ≤ 0.5`, not `d ≤ 1.0`.**
`resolve_topic`'s TF-IDF vectors are non-negative, so `cosine_sim ∈ [0, 1]`
and `baseline_distance = (1 − cosine_sim) / 2 ∈ [0, 0.5]` — `d = 1.0` is a
regime production can never enter. A synthetic sweep or ablation that draws
`d ∈ [0, 1]` (uniformly or otherwise) measures multiplier behavior over a
range twice as wide as what will ever reach `_topic_inflation_vector`, and
any headline number quoted from it (e.g. "the multiplier reaches Nx") is
not a claim about production unless it is re-derived at `d ≤ 0.5`.

`GAIN = 1.0`, `MAX = 3.0` is the starting point — at the real maximum
*reachable* topic distance (`d = 0.5`, giving `d_eff = (0.5 − 0.25) / 0.75 =
0.333`) that yields a `1.333×` multiplier for a median-sensitivity feature
(`s_norm = 1.0`) and `2×` for a feature at the `s_norm = MAX = 3.0` ceiling
(`1 + 1.0 × 0.333 × 3.0 ≈ 2.0`), while leaving the most topic-invariant
features nearly untouched. (At `d = 1.0`, if it were reachable, the same
arithmetic would give `2×`/`4×` respectively — those numbers describe a
regime this system cannot enter and must not be quoted as the correction's
real strength.) `eps = 1e-3` in the `s_A(f)` denominator, matching
`dna_analysis.py:35`'s existing `EPS` guard.

---

## Integration points

| Where | Change |
|---|---|
| `original/constants.py` | Add `TOPIC_SENSITIVITY` (109-vector), `TOPIC_INFLATE_GAIN`, `TOPIC_INFLATE_MAX`. **Additive only** — no `ALL_FEATURE_CODES` reordering, no `NORM_BOUNDS` change, so no permission gate is tripped |
| `ScoringConfig` | `topic_variance_inflation: bool = False`; read once in `from_env`. Defaults reproduce flags-off behaviour exactly, per the dataclass's existing contract |
| `original/quantum/scoring.py:698` | One insertion between the Bayesian-prior blend and `z = (sub_raw − mu)/sigma`, so it inflates the **blended** sigma rather than racing it |
| Typicality guard | Extend the existing `adaptive_weights is None` condition to also exclude inflation. `state.loo_distances` is computed under un-inflated sigma; comparing an inflated `rms_z` against it is the same apples-to-oranges hazard already documented at `original/quantum/scoring.py:781`. Refuse rather than repeat it |
| `_llr_deviation` | `sigma_null` stays **un-inflated** — see below |
| Manifest / report | Record `topic_distance`, `topic_inflation_applied`, `mean_inflation` for audit trail and professor narrative |
| `validation/gate_contracts.py` | Register G7's failure witness. Mandatory — `tests/test_gate_falsifiability.py` fails the suite without it |

### The asymmetry decision

`sigma_null` in `_llr_deviation` is **not** inflated.

Rationale: the impostor pool's sigma is fit across many authors' baselines
spanning many topics, so it already carries cross-topic variance. That is
*why* `llr_deviation_score` survives a genre shift (mean AUC 0.863) while the
raw score inverts (0.387). Inflating only the claimed-author side closes that
asymmetry rather than introducing a new one.

This is the highest-risk decision in the design. Inflating one side of a
difference biases `delta = rms_z − rms_z_null` downward, which reads as "more
like the claimed author" — and systematically biasing that direction for
*everyone* is exactly how `LLR_ACTION_MODE=blend` destroyed the catch rate. The
theoretical argument above is not sufficient. G7's catch-rate leg is what
decides it.

---

## Validation

The bar is set by how `blend` failed: it looked excellent on false-positive
rate alone, and was caught only because someone also checked the catch rate at
a matched severity bar. The acceptance criterion is therefore a
**conjunction**, never a single number.

### Gate G7 — cross-topic same-author FPR

Added to `validation/calibration_gate.py`, measured on the existing
`sweep_harness.py` / `action_mode_sweep.py` leave-one-out harness. Passes only
if **all three** hold:

| | Current | G7 requires |
|---|---|---|
| Genuine cross-topic FP @ `schedule_conversation+` | 42.4% | ≤ 25% |
| Impostor catch @ `schedule_conversation+` | 31.9% | ≥ 29% (≤3pt drop) |
| Mean raw `deviation_score` AUC, cross-genre | 0.387 | ≥ 0.60 |

The third row distinguishes a real fix from score compression. An inverted AUC
*is* the defect; if inflation merely squashes everything toward the middle, FP
falls while AUC stays inverted. Requiring AUC above chance forces the
correction to be discriminative rather than merely lenient — the check `blend`
would have failed.

G7 is three-valued like every other gate. If the corpus cannot support the
criterion at current size it returns `uninformative`, which `--strict` folds
into `fail`. An uninformative G7 is never quotable as a pass.

### Also verified

1. **Byte-identity below threshold.** Unit test asserting `score()` output is
   bit-for-bit unchanged for any submission with `d ≤ 0.25`, flag ON. This is a
   provable property of the `d_eff` construction, and it is what makes G1
   (same-author FPR) safe by inspection rather than by measurement.
2. **No G1/G3/G6 regression.** Full suite via
   `python -m validation.calibration_gate --strict`.
3. **Cross-corpus hold-out, both directions** (see above).
4. **Joint measurement with `LLR_ACTION_MODE`.** A 2×2: inflation on/off ×
   llr `gate`/`shadow`. Both mechanisms target the same false positive, so
   their gains may not add. If inflation alone recovers what `gate` recovers,
   that is worth knowing before shipping two overlapping corrections.

---

## Rollout

Flag `TOPIC_VARIANCE_INFLATION`, default `0`. Two stages, following the
`AI_LIKELIHOOD_SHADOW` and `LLR_ACTION_MODE=shadow` precedents.

**Stage 1 — shadow.** Compute the inflation vector; attach `topic_distance`,
`mean_inflation`, and a shadow `deviation_score_inflated` to the manifest.
`deviation_score` and `recommendation` are untouched.

Shadow answers a question no corpus can: **what is the real distribution of
topic distance in pilot submissions?** If pilot `d` clusters below 0.25, the
mechanism is a no-op in production no matter how well it performs on Lewis.
That is exactly the trap `GENRE_INVARIANT_WEIGHTS_ENABLED` fell into — built,
tested, and unable to fire. Shadow catches it before shipping rather than
after.

**Stage 2 — enabled.** Only after G7 passes in both hold-out directions **and**
shadow confirms non-trivial `d` in real traffic.

### Documented limitations

Both belong in the `CLAUDE.md` flag table entry, not in a follow-up:

- **Validated against public-domain authors, not student writing.** The same
  accepted risk already recorded for `LLR_ACTION_MODE=gate` — a known gap,
  taken deliberately. Nothing local substitutes: every SQLite file in the repo
  is a fixture, so a measurement against `profiles.db` would look plausible
  and mean nothing.
- **Register shift in published authors is a rough proxy.** Narnia vs.
  theology is a wider gap than Romans vs. Christology within one course. The
  proxy likely *overstates* drift, which errs toward a conservative gain.

---

## Out of scope

- Fixing `resolve_genre`. It stays broken and
  `GENRE_INVARIANT_WEIGHTS_ENABLED` stays inert. This design deliberately
  routes around it by using the topic signal that already works, rather than
  taking on classifier repair as a dependency.
- Extrinsic detection — corpus matching, fingerprinting, shingling. Original
  has none today and this design adds none. That is a separate product
  surface with its own storage, FERPA, and UI implications.
- Per-student topic-sensitivity estimation. The natural extension is a hybrid:
  global prior shrunk toward a per-student estimate as baseline samples
  accumulate, damped by sample count the way `PRIOR_WEIGHT` already damps the
  Bayesian prior. It is unvalidatable until real pilot baselines are deeper
  and broader, so it is noted and deferred rather than designed here.
