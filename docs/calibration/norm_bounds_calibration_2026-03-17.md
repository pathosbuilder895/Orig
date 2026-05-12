# NORM_BOUNDS Calibration Report & Bias Audit
**Date:** 2026-03-17
**Version:** 1.0.0 → 1.1.0
**Author:** Calibration pipeline (automated) + manual review

---

## 1. Purpose

`NORM_BOUNDS` maps each raw feature value to the unit interval [0, 1] by clipping to `[lo, hi]` and then scaling linearly. If these bounds are set incorrectly the scoring model misbehaves in two distinct ways:

- **Bounds too tight (hi too low):** legitimate text values are clipped to 1.0, causing all high-value texts to look identical on that feature. Real intra-student variation is erased and genuine submissions from students who write in a formal, passive, or long-paragraph style will score anomalously high deviation.
- **Bounds too loose (hi too high):** real variation is compressed into a very small slice of [0, 1]. The density matrix sees negligible spread across that feature and the Born-rule projection is dominated by the few features where variation is not compressed. Discrimination power is wasted.

---

## 2. Calibration Method

A corpus of 20 theological essay texts was constructed to span the likely range of student writing styles at a theological seminary. The corpus was designed to include:

| Dimension | Low end | High end |
|-----------|---------|----------|
| Hedging level | None (assertive style) | High (tentative, academic) |
| First-person use | None (third-person survey) | High (personal reflection) |
| Sentence length | Short (pastoral, NNE-sim) | Long (systematic theology) |
| Passive voice | None | Heavy (philosophical theology) |
| Discourse markers | Sparse | Dense (well-argued academic) |
| Vocabulary | Simple (student-level, NNE-sim) | Technical (doctoral-level) |
| Genre | Devotional, confessional | Exegetical, systematic, apologetic |

Raw (un-normalised) feature values were extracted for each text using the live Tier 1/2/3 extractors. Per-feature 5th and 95th percentiles were computed. The proposed new bounds are set at P05 − 5% margin for `lo` and P95 + 5% margin for `hi`, with manual override where the corpus is clearly too small to set the tail reliably.

**Caveat:** a 20-text corpus is sufficient for identifying gross misfits but not for precise threshold calibration. The findings here are directionally reliable; institutions are encouraged to accumulate their own submission data and re-run this calibration annually.

---

## 3. Calibration Findings by Feature

### 3.1 Tier 1 — Surface Stylometry

| Feature | Old lo | Old hi | P05 | P95 | New hi | Action |
|---------|--------|--------|-----|-----|--------|--------|
| `type_token_ratio` | 0.25 | 0.85 | 0.45 | 0.76 | 0.85 | tightened lo (0.42) |
| `hapax_legomena_rate` | 0.15 | 0.72 | 0.30 | 0.66 | 0.72 | unchanged |
| `mean_sentence_length` | 6.0 | 38.0 | 4.5 | 41.8 | **45.0** | widened both ends |
| `sentence_length_variance` | 4.0 | 200.0 | 1.9 | 68.7 | **100.0** | halved hi; P95 far below 200 |
| `function_word_ratio` | 0.22 | 0.62 | 0.31 | 0.52 | 0.58 | tightened both |
| `passive_voice_ratio` | 0.00 | **0.45** | 0.00 | **0.667** | **0.70** | **CLIP_HI fixed** |
| `modal_verb_ratio` | 0.00 | **0.18** | 0.00 | 0.033 | **0.08** | **hi too loose fixed** |
| `stop_word_ratio` | 0.18 | 0.65 | 0.31 | 0.55 | 0.60 | tightened both |
| `avg_word_length` | 3.2 | 7.8 | 3.7 | 6.0 | 7.0 | tightened slightly |

**Key finding:** `passive_voice_ratio` was clipping 10 % of the corpus. Systematic theology and philosophical theology prose regularly uses passive constructions at a 60–70 % rate. Texts with high passive voice were landing at the clipped maximum, making them look artificially identical on this feature and suppressing legitimate student-baseline variation.

`modal_verb_ratio` was set 5× too high (0.18 vs. P95 of 0.033). This compressed all real modal-verb variation into the bottom 18 % of the normalised range, reducing its discriminative weight in the density matrix to near zero.

### 3.2 Tier 2 — Discourse Structure

| Feature | Old hi | P95 | New hi | Action |
|---------|--------|-----|--------|--------|
| `discourse_marker_density` | **14.0** | 4.1 | **6.0** | hi compressed variation into <30 % of range |
| `temporal_ratio` | **0.55** | **1.0** | **1.0** | CLIP_HI fixed; historical-survey texts hit 100 % |
| `thematic_progression_score` | **1.0** | 0.20 | **0.30** | hi too loose; P95 only 20 % of range |
| `lexical_chain_density` | **0.65** | 0.094 | **0.15** | hi too loose; P95 only 14 % of range |
| `avg_paragraph_length` | **12.0** | **19.0** | **22.0** | CLIP_HI fixed; academic paragraphs routinely exceed 12 sentences |
| `cohesion_device_ratio` | **0.30** | 0.354 | **0.40** | CLIP_HI fixed; slightly too tight |

### 3.3 Tier 3 — Rhetorical & Register

| Feature | Old hi | P95 | New hi | Action |
|---------|--------|-----|--------|--------|
| `hedging_density` | **10.0** | 2.21 | **5.0** | 4.5× too loose |
| `assertion_density` | **12.0** | 0.81 | **5.0** | 15× too loose |
| `claim_density` | **12.0** | 0.75 | **5.0** | 16× too loose |
| `appeal_to_authority_density` | **12.0** | 1.47 | **5.0** | 8× too loose |
| `theological_register_score` | 1.0 | 0.31 | **0.50** | tightened to improve discrimination |
| `counter_argument_ratio` | 0.55 | ⚠ 1.0 (degenerate) | 1.0 | **extractor bug — see §4** |
| `imperative_density` | 5.0 | ⚠ 0 (degenerate) | 5.0 | **extractor bug — see §4** |
| `conclusion_strategy_score` | 1.0 | ⚠ 0 (degenerate) | 1.0 | **extractor bug — see §4** |

---

## 4. Degenerate Extractor Findings (Priority Bugs)

Three Tier 3 features produced degenerate distributions in the calibration corpus — every text returned the same value regardless of content. These features contribute no discriminative information to the density matrix in their current state, and they may silently inflate or deflate deviation scores when a future extractor fix changes their output.

### 4.1 `counter_argument_ratio`

All 20 corpus texts returned a value of 1.0. The extractor appears to count all sentences as "counter-argument" sentences, or the sentence classifier is always returning true. This means the feature is always normalised to `clip((1.0 - 0.0) / (0.55 - 0.0), 0, 1) = 1.0` (with the old bound) or `1.0` (with the new bound).

**Impact:** A column of all-1.0s in the density matrix contributes a rank-1 component that is identical for every student. This does not cause incorrect flagging on its own but wastes one of 34 feature dimensions. If the extractor is fixed in a future release, historical density matrices built with the broken extractor will be inconsistent with new ones built with the fixed extractor. Operators should be aware that a fix will require rebuilding all density matrices.

**Recommendation:** investigate the sentence-level classifier. The feature should count sentences containing explicit counter-argument signal words (however, by contrast, critics argue, on the other hand) as a proportion of total sentences.

### 4.2 `imperative_density`

All 20 corpus texts returned 0.0, including the homiletical text (text 10) that was specifically written with imperative constructions ("Consider what it means…", "Receive it.", "Let it go deep."). The extractor is not detecting imperative sentences.

**Impact:** same as above — zero-variance column. **Additionally**, because the homiletical text is correctly distinguished from academic texts on this feature but the extractor returns 0 for both, real style variation is not captured.

**Recommendation:** the imperative detector likely relies on a part-of-speech tagger that is not present or not functioning. Verify that the dependency used for imperative detection (spaCy or similar) is installed and that the root-verb + no-subject heuristic is working.

### 4.3 `conclusion_strategy_score`

All 20 corpus texts returned 0.0. The feature is intended to detect summary-signalling language (in conclusion, therefore, to summarise, in sum). Several corpus texts contained such language; all returned 0.

**Recommendation:** check the lexicon lookup for conclusion markers. The score likely has an off-by-one or empty-intersection bug.

---

## 5. Bias Audit

### 5.1 Non-Native English Speaker (NNE) Risk — Tier 1

The Tier 1 surface features are the most sensitive to the global properties of English usage rather than to theological content. Calibration results confirm the following systematic patterns in NNE-simulated texts:

| Feature | Native trend | NNE-sim trend | Direction of bias |
|---------|-------------|--------------|-------------------|
| `type_token_ratio` | 0.64–0.76 | 0.45–0.61 | NNE texts score lower (less lexical diversity) |
| `hapax_legomena_rate` | higher | lower | same direction |
| `mean_sentence_length` | 8–23 words | 5–8 words | NNE texts tend shorter |
| `function_word_ratio` | 0.38–0.49 | 0.40–0.53 | slight NNE high bias (more function words) |
| `avg_word_length` | 5.0–6.0 | 3.7–4.5 | NNE texts use shorter words |

A student who writes authentic but simple English — because English is their second language — will produce a Tier 1 feature vector that differs systematically from a native-English baseline, regardless of authorship. If their baseline samples reflect this simpler register and a later submission also does, the model will correctly see consistency. **The critical risk is the reverse:** a student whose baseline was collected under proctored conditions in which they used a simpler register, but whose un-proctored submission is closer to a native-English norm (perhaps with assistance from a native-English editor), will score a *lower* deviation than a native-English student who used an AI tool.

Conversely, a student whose baseline was collected from richer writing (e.g., a take-home portfolio marked VERIFIED) but whose proctored submission is simpler due to exam stress will score higher deviation. **This asymmetry should be acknowledged to instructors** in any flagging explanation.

**Recommendation:** the `baseline_confidence.purity` field already signals when the baseline is internally inconsistent. Institutions should be advised to use consistent assessment conditions for all baseline samples (same modality: all proctored, or all take-home) to avoid between-condition variation inflating deviation scores.

### 5.2 Theological Register Inflation (Tier 3)

`theological_register_score` is domain-specific vocabulary density. Students from non-English-language theological traditions (e.g., graduates of German-language or Korean-language seminaries enrolled in English-language programs) may use a narrower set of English theological terms, producing lower scores. If their baseline samples also show lower scores, the model will see consistency. If the model is used across institutions with different theological vocabularies (e.g., Catholic seminaries vs. Calvinist seminaries vs. Pentecostal colleges), the `theological_register_score` lexicon may not represent all traditions equally.

**Recommendation:** publish the theological register lexicon as a configurable constant so institutions can extend it with tradition-specific terminology.

### 5.3 Writing-Style Drift over Degree Programme

Students develop their academic writing style over the course of a degree. A Tier 1 feature profile from a first-year essay may differ significantly from a third-year essay even for the same authentic student. The density matrix will show this as lower purity (reflecting genuine development), not as anomalous authorship. However, if the model is used to compare a senior thesis against freshman baseline essays, legitimate drift could produce elevated deviation scores.

**Recommendation:** weight baseline samples by recency (the `RECENCY_DECAY` constant already does this) and require institutions to refresh baseline samples at least once per academic year for students with more than two years of historical samples.

### 5.4 Differential Impact Summary

| Population | Primary risk | Severity | Mitigation |
|-----------|-------------|----------|------------|
| Non-native English speakers | Tier 1 deviation inflation from register mismatch | **High** | Consistent baseline conditions; instructor training |
| Students who develop significantly over time | Purity degradation misread as anomaly | Medium | Recency weighting (already implemented); annual baseline refresh |
| Homiletical/pastoral writers vs academic context | Tier 3 extractor gaps (imperative, conclusion) | Low | Fix degenerate extractors; don't rely on those three features |
| Students from non-Western theological traditions | Theological register undercount | Low | Extend lexicon; flag as known limitation in UI |

---

## 6. Action Items

| Priority | Item | Owner |
|----------|------|-------|
| P0 | Fix `imperative_density` extractor (not detecting imperative verbs) | Engineering |
| P0 | Fix `conclusion_strategy_score` extractor (returning 0 always) | Engineering |
| P1 | Fix `counter_argument_ratio` extractor (returning 1.0 always) | Engineering |
| P1 | Collect 50+ additional corpus texts from real seminary writing | Research |
| P1 | Run calibration on the expanded corpus and validate updated NORM_BOUNDS | Research |
| P2 | Expose `theological_register_score` lexicon as configurable list | Engineering |
| P2 | Add NNE risk warning to instructor-facing UI when `purity < 0.5` and dominant deviation is Tier 1 | Product |
| P2 | Empirical threshold calibration against labelled instructor decisions | Research |
| P3 | Annual re-calibration protocol; document in runbook | Research |

---

## 7. Updated NORM_BOUNDS Summary

The updated `NORM_BOUNDS` dictionary has been applied to `original/constants.py`. The net effect of the changes:

- 5 features had bounds that were **clipping legitimate text** (passive voice, temporal ratio, avg paragraph length, cohesion device ratio, mean sentence length). These are now fixed and will reduce spurious deviation for formal academic texts.
- 7 features had bounds **so loose that real variation was compressed** into less than 20 % of the normalised range (modal verb ratio, discourse marker density, thematic progression, lexical chain density, hedging density, assertion density, claim/authority density). Tightening these bounds will improve the density matrix's ability to discriminate between students on these features.
- 3 features have **degenerate extractor output** and contribute no discriminative information until the extractors are fixed. They have been noted with `⚠` warnings in the code.
