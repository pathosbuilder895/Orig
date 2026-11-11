# Comparison measurements not compared: measured impact

**Date:** 2026-10-25 · **Branch:** `fix/comparison-placeholders` · **Approved by:** Andrew (2026-10-25, "Fix the placeholders")
**Code:** `original/features/baseline_scope.py`, `quantum/state.py` (`active_feature_mask`), `quantum/scoring.py` (`score`, `_decompose`), `evidence.py`, `evidence_features.py`
**NORM_BOUNDS / constants:** unchanged. **Decision record:** ADR-013, "Comparison measurements".

## What changed

The 7 comparison codes (`MUSICAL_COMPARISON_CODES` + `COMPARISON_CODES`) are never computed for a past paper: every stored vector comes from `extract_features`, which writes a 0.5 stand-in for them. Only the scored paper gets real values, and only when the context pipeline runs (`CONTEXT_MANIFEST_ENABLED=1` or `ADAPTIVE_WEIGHTS_ENABLED=1`; the demo server sets both, the pilot's `render.yaml` sets both to 0, the batch scorer locks them off). They are now left out of the comparison by code: not in rms_z for any baseline size, z = 0 there, not in the unit vector / Born probability / trajectory alignment, not in the top lists, entanglement pairs or `tier_breakdown`, and `not_compared` on the evidence pages.

## Where a number can move, and where it cannot

| Path | Before the fix | Effect |
|---|---|---|
| Context pipeline off (pilot, batch scorer, `score_documents.py`), 2+ past papers | Scored paper also holds 0.5; the value check (`stuck_at_neutral`) already dropped the 7 from rms_z | Deviation, action, Born probability: identical. Lists: comparison codes leave the constructive list; entanglement pairs can change (see below); tiers 0 and 11 leave `tier_breakdown`. |
| Context pipeline on (demo server), 2+ past papers | Scored paper real, past papers 0.5; rms_z already excluded them by value, but they entered xi, the Born probability, the trajectory alignment and the top lists | Deviation and action unchanged on every case measured below; Born probability moves; the two "high = close to baseline" codes leave the top of the destructive list |
| One past paper (unit callers only; the API needs 3) | All dimensions active, so the 7 entered rms_z | Excluded now |
| Ghostwriting override (`ghostwriting_confirmed`) | Could fire on `error_kl_divergence` real vs 0.5 | Cannot fire until past papers have values |

Entanglement pairs: `_find_entanglement_anomalies` only searches the first 80 cross-tier pairs (a performance cap). Taking the tier-11 codes out frees slots in that window, so pairs such as T2-T3 can now be found. These are report-only (rationale text) and do not change an action.

## Snapshots (`tests/snapshots/`, regenerated with `scripts/update_score_snapshot.py`)

| Snapshot | deviation | action | Born P | rms_z | top destructive list |
|---|---|---|---|---|---|
| API (`score_default_api.json`, real extraction, pipeline off) | 0.5679 → 0.5679 | monitor → monitor | 0.8915 → 0.8915 | 1.5144 → 1.5144 | unchanged; only `tier_breakdown` changes (T0 and T11 removed, the rest renormalised) |
| Unit (`score_default.json`, seeded random vectors) | 0.5566 → 0.5587 | monitor → monitor | 0.9296 → 0.9311 | 1.4755 → 1.4828 | `char_trigram_profile_divergence` (5th) replaced by `revision_depth` |

The unit snapshot's past papers are seeded random vectors that, unlike any real past paper, vary on the 7 comparison codes, so the value check kept them active. Excluding them by code is the intended change; that is the whole shift.

## Chesterton/Mill fixture (3 Mill past papers; the e2e fixture and the alpha toy export)

Live `POST /students/{id}/score` through the in-process app, fresh database per run.

| Paper | Pipeline | deviation before → after | action | Born P before → after | top destructive, before | after |
|---|---|---|---|---|---|---|
| Chesterton | off | 0.5972 → 0.5972 | monitor | 0.8769 → 0.8769 | catastrophe_index, comma_rate, first_person_ratio, source_integration_style, burstiness | same |
| Mill (held out) | off | 0.5500 → 0.5500 | monitor | 0.9106 → 0.9106 | passive_voice_ratio, source_integration_style, sentence_initial_conjunction_rate, pronoun_ambiguity_rate, paragraph_topic_position | same |
| Chesterton | on | 0.6085 → 0.6085 | schedule_conversation | 0.8558 → 0.8769 | **punctuation_error_ratio, error_kl_divergence**, catastrophe_index, comma_rate, first_person_ratio | catastrophe_index, comma_rate, first_person_ratio, source_integration_style, burstiness |
| Mill (held out) | on | 0.5660 → 0.5660 | monitor | 0.8897 → 0.9106 | **punctuation_error_ratio, error_kl_divergence**, passive_voice_ratio, source_integration_style, sentence_initial_conjunction_rate | passive_voice_ratio, source_integration_style, sentence_initial_conjunction_rate, pronoun_ambiguity_rate, paragraph_topic_position |

With the pipeline on, the scored papers' comparison values were Chesterton 0.757 / 0.251 / 0.955 / 0.693 / 1.0 / 0.502 / 0.771 and Mill 0.451 / 0.265 / 0.982 / 0.704 / 1.0 / 0.337 / 0.183 (argument_sequence, semantic_centroid, error_kl, stumble_rate, punctuation_error, char_trigram, function_word). The top two "differences" for both papers, the paper the student wrote included, were two scores that mean "close to the past papers". Before the fix, all three entanglement pairs reported for each paper involved a comparison code; after it, none do. The alpha batch scorer (`batch_score_alpha.py`, pipeline locked off) gives 0.5500 / 0.5972, monitor / monitor, on both sides.

## Seminary proxy (own vs other)

Same proxy as `quote_block_fix_2026-10-25.md`: 139 seminary essays in 27 groups of 5 sequential files, 4 past papers plus a held-out paper; each group scored on its own held-out paper ("self") and on the next group's ("other"); 26 of 27 groups score.

**Alpha batch scorer (pipeline off), main vs this branch:**

| | main | this branch |
|---|---|---|
| self flagged (schedule_conversation / escalate) | 1 / 26 (3.8%) | 1 / 26 (3.8%) |
| other flagged | 4 / 26 (15.4%) | 4 / 26 (15.4%) |
| mean deviation, self / other | 0.490 / 0.539 | 0.490 / 0.539 |
| actions changed | | 0 of 52; all 52 deviations identical |

**Demo server path (pipeline on: `CONTEXT_MANIFEST_ENABLED=1`, `ADAPTIVE_WEIGHTS_ENABLED=1`, live score route in process, one fresh database per side):**

| | main | this branch |
|---|---|---|
| self flagged | 1 / 26 (3.8%) | 1 / 26 (3.8%) |
| other flagged | 6 / 26 (23%) | 6 / 26 (23%) |
| mean deviation, self / other | 0.488 / 0.537 | 0.488 / 0.537 |
| actions changed | | 0 of 52; all 52 deviations identical |
| papers with a comparison code in the top 5 differences | 19 self, 19 other | 0, 0 |
| papers whose #1 difference was a comparison code | 4 self, 3 other | 0, 0 |
| papers with the T1-T11 error-vanish pair | 2 self, 2 other (none forced an escalate) | 0, 0 |

So on this proxy the fix changes no score and no action. What changes is the explanation: before, 38 of 52 papers had a stand-in comparison among their top five "differences".

Both sides fail the alpha's pre-registered bar (≤5% false flags and ≥75% caught) on this proxy, as before. The proxy's "students" are sequential 5-file groups, not verified single authors, so it is only directional.

## Not done here

- **Leave-one-out values for past papers** (see ADR-013): would let these 7 be compared honestly, but needs every stored vector recomputed whenever a past paper is added or removed, is undefined for one past paper, compares N-1 against N papers, and needs its own calibration.
- Zero-frequency and constant measurements (for example `catastrophe_index`) are already out of rms_z by the value check but still reach the top destructive list. Same kind of mismatch, separate change.
- Other consumers of the raw submission vector behind off-by-default flags (fused score, style-authorship, AI-likelihood, longitudinal drift) were not changed.
