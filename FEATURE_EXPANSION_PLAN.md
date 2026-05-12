# Original — Feature Expansion Plan

## Executive Summary

Original currently extracts 34 features across 3 tiers (surface stylometrics, discourse structure, rhetorical fingerprint). The research literature identifies several high-value feature families that we don't cover at all — most critically **character n-grams**, **POS n-grams**, **punctuation/whitespace habits**, and **idiosyncratic error patterns**. These families are specifically chosen because they survive light-to-moderate editing, resist topic confounds, and work well at seminary-paper lengths (1000–5000 words).

This plan adds **4 new tiers** (Tiers 4–7) containing approximately **28–35 new features**, bringing the total to ~62–69. The expansion is phased so that each tier can ship independently, existing baselines can be rebuilt using the `rebuild-baselines` CLI, and the density matrix dimensions scale gracefully.

---

## Gap Analysis: What We Have vs. What the Literature Recommends

| Feature Family | Literature Signal Strength | Current Coverage | Gap |
|---|---|---|---|
| Lexical (TTR, hapax, word length) | High | 5 features (Tier 1) | Adequate |
| Function words / stop words | Very High (most edit-resistant) | 2 features (ratio only) | **Missing individual function-word profile** |
| Sentence-level syntax | High | 4 features (length, variance, passive, modal) | **Missing POS n-grams entirely** |
| Character n-grams | Very High (language-agnostic, edit-resistant) | **None** | **Critical gap** |
| Punctuation & spacing habits | High (unconscious, stable) | **None** | **Critical gap** |
| Discourse / cohesion | Medium-High | 13 features (Tier 2) | Good |
| Rhetorical / register | Medium | 12 features (Tier 3) | Good for domain |
| Structural / layout | Medium | 2 features (paragraph length, topic position) | Partial — **missing list/heading/citation-layout patterns** |
| Idiosyncratic (errors, misspellings) | High (very person-specific) | **None** | **Significant gap** |
| AI-vs-human markers | High (for LLM detection) | **None** | **Strategic gap** |

The three **critical gaps** — character n-grams, punctuation habits, and POS n-grams — are exactly the features that Writeprints, the 446-feature system, and AI-detection research identify as most robust under editing and most discriminating across authors.

---

## Architecture Constraint: Density Matrix Dimensionality

The quantum scoring system builds a density matrix ρ ∈ ℝ^(D×D) where D = `FEATURE_DIM`. Currently D = 34, so ρ is a 34×34 matrix. Increasing to D = 65 means a 65×65 matrix — still trivially small for computation, but every stored `feature_vector` JSON in the database becomes stale because the vector length changes.

**Migration strategy** (already solved):

1. We store `raw_text` in `baseline_samples` (migration 002, just shipped).
2. When a new tier ships, bump `MODEL_VERSION`, add new codes to `ALL_FEATURE_CODES`, add `NORM_BOUNDS`.
3. Run `python -m original.cli rebuild-baselines` to re-extract all stored samples.
4. Any sample without `raw_text` (pre-migration-002) is skipped; instructors are prompted to re-submit.

This means we can add features incrementally without a flag day.

---

## Proposed Tiers

### Tier 4 — Character & Punctuation Fingerprint (8 features, no new dependencies)

These are the single highest-value additions. Character n-grams and punctuation patterns are unconscious habits, highly author-specific, and survive vocabulary substitution (the primary attack vector for both human editors and AI paraphrasers).

| Code | Name | What It Measures | Why It Matters |
|---|---|---|---|
| `char_trigram_entropy` | Character Trigram Entropy | Shannon entropy of the character 3-gram frequency distribution | Captures spelling patterns, morphological habits, whitespace preferences at a sub-word level. High entropy = diverse character sequences. Extremely stable across topics. |
| `char_trigram_profile_divergence` | Char Trigram Profile Divergence | KL-divergence between submission's top-200 char trigram profile and baseline's | Direct "distance" metric for character-level habits. The Writeprints core feature. |
| `punctuation_diversity` | Punctuation Diversity | Entropy of punctuation mark distribution (.,;:!?—–""''()/) | Captures habitual punctuation choices. Some writers never use semicolons; others use them constantly. |
| `comma_rate` | Comma Rate | Commas per 100 words | Comma usage is one of the most author-specific measurable habits in English prose. |
| `semicolon_colon_rate` | Semicolon+Colon Rate | Semicolons + colons per 100 words | Semicolon and colon usage is rare enough to be highly discriminating; their presence or absence is stylistically meaningful. |
| `parenthetical_rate` | Parenthetical Rate | Parentheses pairs per 100 words | Parenthetical asides are a strong stylistic marker; some writers use them heavily, others almost never. |
| `dash_rate` | Dash Rate | Em-dashes + en-dashes + hyphens-as-dashes per 100 words | Dash usage patterns (em-dash vs. parenthetical vs. comma) are deeply habitual. |
| `quote_rate` | Quotation Rate | Quotation mark pairs per 100 words | Frequency of direct quotation vs. paraphrase is a discourse-level habit tied to how the author integrates sources. |

**Implementation notes:**

- All pure Python + `collections.Counter`. No NLP dependencies.
- `char_trigram_entropy`: iterate over `doc.clean` as a character sequence, build Counter of all 3-char windows, compute Shannon entropy. Normalize against theoretical max (log2 of unique trigram count).
- `char_trigram_profile_divergence`: this is a **comparison feature** — it requires the baseline's stored trigram profile, not just the submission text. Two options:
  - (a) Store a top-200 trigram frequency dict in the baseline alongside `feature_vector`. More data in DB but cleaner.
  - (b) Compute divergence at scoring time from baseline `raw_text`. More compute but no schema change.
  - **Recommend (b)** for now — `raw_text` is already stored, and scoring already loads all baseline samples. Extract the profile on-the-fly during `build_student_state()`.
- Punctuation features: simple regex counts on `doc.clean`, divided by word count × 100.

**Estimated effort:** 1–2 days. No dependencies, no NLP, pure counting.

---

### Tier 5 — POS & Shallow Syntax (7 features, adds spaCy dependency)

POS n-grams capture grammatical rhythm independent of vocabulary. When an editor swaps content words (nouns, verbs) but leaves sentence structure intact, POS patterns persist. This tier requires a POS tagger — we'll add spaCy with the small English model (`en_core_web_sm`, 12MB).

| Code | Name | What It Measures |
|---|---|---|
| `pos_bigram_entropy` | POS Bigram Entropy | Shannon entropy of POS tag bigram distribution |
| `pos_trigram_entropy` | POS Trigram Entropy | Shannon entropy of POS tag trigram distribution |
| `noun_verb_ratio` | Noun-Verb Ratio | NOUN count / VERB count — captures nominal vs. verbal style |
| `adjective_rate` | Adjective Rate | ADJ tags per 100 words — measures descriptive density |
| `adverb_rate` | Adverb Rate | ADV tags per 100 words — measures qualification tendency |
| `subordination_ratio` | Subordination Ratio | Subordinating conjunctions (SCONJ) per clause — measures syntactic complexity |
| `clause_depth_mean` | Mean Clause Depth | Average depth of dependency parse tree — captures syntactic embedding habits |

**Implementation notes:**

- **New dependency: spaCy + `en_core_web_sm`**. This is the biggest architectural decision in the plan.
  - Pros: POS tagging accuracy is ~97%, dependency parsing enables `clause_depth_mean`, and it opens the door to future features (NER, constituency parsing).
  - Cons: 12MB model download, ~50ms per document inference time (acceptable for 1000–5000 word papers), and it adds a build step.
  - **Alternative (no spaCy):** Use a rule-based POS approximation. Not recommended — accuracy drops to ~85% and dependency parsing becomes impossible.
- Add `spacy` and `en_core_web_sm` to `requirements.txt`. Load the model lazily (first call to `extract_tier5()` loads it; subsequent calls reuse the singleton).
- `clause_depth_mean`: for each sentence, compute max depth of the dependency tree. Average across sentences. This is the only feature here that requires dependency parsing beyond POS tags.

**Estimated effort:** 2–3 days (including Docker/CI changes for spaCy model download).

---

### Tier 6 — Idiosyncratic & Error Patterns (6 features, no new dependencies)

Idiosyncratic features are the most person-specific category in the Writeprints taxonomy. Spelling errors, grammatical mistakes, and formatting habits are largely unconscious and extremely difficult to fake consistently.

| Code | Name | What It Measures |
|---|---|---|
| `contraction_rate` | Contraction Rate | Contractions per 100 words (don't, it's, they're, etc.) |
| `sentence_initial_conjunction_rate` | Sentence-Initial Conjunction Rate | Sentences starting with And/But/So/Or per total sentences |
| `that_which_ratio` | That/Which Ratio | Uses of "that" vs. "which" in relative clauses — a strong habitual preference |
| `citation_style_consistency` | Citation Style Consistency | Entropy of citation format variants (Author (Year), Author Year, parenthetical, footnote) — low entropy = consistent habit |
| `list_marker_preference` | List Marker Preference | Categorical: which list/enumeration style the author defaults to (numbered, lettered, roman, bullet, inline) |
| `abbreviation_tendency` | Abbreviation Tendency | Ratio of abbreviations used vs. full forms available (e.g., "NT" vs. "New Testament", "cf." vs. "compare") — normalized against a domain abbreviation dictionary |

**Implementation notes:**

- `contraction_rate`: regex for common contractions (`\b\w+'(t|s|re|ve|ll|d|m)\b`).
- `sentence_initial_conjunction_rate`: check first token of each sentence against {and, but, so, or, yet, for, nor}. This is a strong register marker — formal academic writing avoids it; casual writers do it constantly.
- `that_which_ratio`: regex for relative clause patterns. Count "that" vs. "which" in non-quotation contexts.
- `citation_style_consistency`: build a classifier for citation formats using regex (APA parenthetical, Turabian footnote, inline, etc.), compute entropy of the format distribution. A writer who always uses Turabian has entropy ≈ 0; one who mixes styles has high entropy.
- `abbreviation_tendency`: maintain a domain-specific dict of abbreviation ↔ expansion pairs (theological terms). Count how often the author uses the short form vs. the long form.

**Estimated effort:** 2 days. Pure regex, no NLP dependencies.

---

### Tier 7 — AI Detection Markers (7 features, no new dependencies beyond Tier 5)

These features specifically target the statistical signatures of LLM-generated text. The research shows that function word distributions, POS patterns, and lexical diversity behave differently in AI text vs. human text — even when the AI is prompted to "write like" a specific person.

| Code | Name | What It Measures |
|---|---|---|
| `burstiness` | Burstiness | Variance-to-mean ratio of sentence lengths. Human writing is bursty (short punchy sentences mixed with long complex ones); LLM text tends toward uniform length. |
| `perplexity_proxy` | Perplexity Proxy | Average log-frequency of word choices (using a precomputed word frequency table). Low perplexity = very predictable word choices = LLM-like. |
| `repetition_gap_entropy` | Repetition Gap Entropy | For repeated content words, entropy of the gap distances between occurrences. Humans repeat words in clustered, topic-driven bursts; LLMs space repetitions more uniformly. |
| `function_word_profile_divergence` | Function Word Profile Divergence | KL-divergence of the 30 most common function words vs. baseline profile. Similar to char_trigram_profile_divergence but at the function-word level. |
| `transition_predictability` | Transition Predictability | How predictable paragraph-to-paragraph topic shifts are, measured by cosine similarity of adjacent paragraph bag-of-words vectors. LLMs produce more uniform transitions. |
| `vocabulary_introduction_rate` | Vocabulary Introduction Rate | Rate at which new unique words appear as the text progresses (a curve, summarized as area-under-curve). Humans front-load vocabulary; LLMs introduce new words more uniformly. |
| `filler_hedge_cluster_rate` | Filler/Hedge Clustering | Whether hedging language clusters in specific locations (human) or distributes uniformly (LLM). Measured as Gini coefficient of hedge positions. |

**Implementation notes:**

- `burstiness`: `variance(sentence_lengths) / mean(sentence_lengths)`. Classic index of dispersion.
- `perplexity_proxy`: requires a precomputed word-frequency table. Ship a compressed JSON of the top 50,000 English words by frequency (from a public corpus like Google n-grams or COCA). ~500KB. For each word in the text, look up log-frequency; average across all words. Rare/unknown words get a floor frequency.
- `function_word_profile_divergence`: same approach as `char_trigram_profile_divergence` but over the 30 most common function words. This is a comparison feature — needs baseline profile at scoring time.
- `vocabulary_introduction_rate`: divide text into 10 equal segments, compute cumulative unique-word count at each segment boundary, fit a curve, report the AUC normalized to [0,1].
- `filler_hedge_cluster_rate`: reuse the existing `HEDGE_WORDS` lexicon from constants.py. Record the position (as fraction of document length) of each hedge word. Compute Gini coefficient of positions. Uniform → Gini ≈ 0 (LLM-like); clustered → Gini > 0 (human-like).

**Estimated effort:** 2–3 days. Requires shipping the word-frequency table for `perplexity_proxy`; everything else is pure Python.

---

## Phased Rollout

| Phase | Tier(s) | New Features | Total D | Dependencies Added | Priority |
|---|---|---|---|---|---|
| **Phase 1** | Tier 4 (Char & Punctuation) | +8 | 42 | None | **Highest — ship first** |
| **Phase 2** | Tier 6 (Idiosyncratic) | +6 | 48 | None | High — no new deps |
| **Phase 3** | Tier 7 (AI Detection) | +7 | 55 | Word frequency table (~500KB) | High — strategic value |
| **Phase 4** | Tier 5 (POS & Syntax) | +7 | 62 | spaCy + en_core_web_sm | Medium — biggest infra change |

Rationale for this ordering: Tiers 4 and 6 are pure Python with no new dependencies, meaning they can ship without any Docker/CI changes. Tier 7 is nearly dependency-free (just a static JSON file). Tier 5 requires spaCy, which affects the Docker image size, CI pipeline, and cold-start time, so it ships last even though POS features are very valuable.

---

## Implementation Checklist Per Tier

Each new tier follows the same 8-step process:

1. **Create `features/tierN.py`** with `extract_tierN(doc: TextDoc) → Dict[str, float]`.
2. **Add feature codes** to `constants.py`: new `TIERN_CODES` list, append to `ALL_FEATURE_CODES`, add to `FEATURE_TIER`, `FEATURE_NAMES`.
3. **Add `NORM_BOUNDS`** — initially set wide (P01/P99 estimates), then calibrate on the 20-text corpus.
4. **Update `pipeline.py`** — import and call `extract_tierN(doc)`, merge into `raw` dict.
5. **Update frontend** — add new features to the `FEATURES` array in each HTML page so the UI displays them.
6. **Bump `MODEL_VERSION`** in settings.
7. **Run `rebuild-baselines --dry-run`** to verify extraction works on stored samples, then run without `--dry-run`.
8. **Calibrate `NORM_BOUNDS`** — run the calibration corpus script, update bounds to P05/P95.

---

## Comparison Features: Architectural Decision

Two features (`char_trigram_profile_divergence` and `function_word_profile_divergence`) are **comparison features** — they measure the distance between the submission and the baseline, rather than a property of the submission text alone. This is a new concept in the pipeline.

**Current architecture:** `extract_features(text)` takes a single text string and returns 34 scalar features. The comparison happens later in the quantum scoring layer (density matrix + z-scores).

**Options for comparison features:**

**(A) Compute at extraction time (requires passing baseline context)**
Change `extract_features(text, baseline_texts=None)` to optionally accept baseline texts. When baseline is provided, compute divergence features; when not (e.g., during baseline ingestion), store the raw profile and set divergence = 0.0.

- Pro: Feature vector is self-contained; density matrix math works unchanged.
- Con: Changes the extraction API; baseline samples' divergence-from-self is meaningless.

**(B) Compute at scoring time (separate from extraction)**
Keep `extract_features(text)` pure. Store the raw profile (char trigram frequencies, function word frequencies) as additional metadata in `feature_vector` JSON. Compute divergence in `quantum/scoring.py` during the scoring pass, where baseline texts are already loaded.

- Pro: Clean separation; extraction remains stateless; no API change.
- Con: Divergence features live outside the density matrix; need separate handling in the scoring output.

**(C) Hybrid — extract profiles, compute divergence in a post-processing step**
`extract_features(text)` returns the 62+ scalar features plus a `_profiles` dict containing raw frequency distributions. `pipeline.py` exposes a second function: `compute_comparison_features(submission_profiles, baseline_profiles) → Dict[str, float]`. The scoring layer calls both, then concatenates.

- Pro: Clean API, profiles are reusable, divergence is still a scalar in the final vector.
- Con: Two-step extraction; `FEATURE_DIM` now includes features that only exist in the scoring context.

**Recommendation: Option C.** It keeps extraction stateless, avoids polluting the density matrix with meaningless self-divergence values for baselines, and lets the scoring layer compose the full vector right before building ρ. The density matrix dimensions will be `FEATURE_DIM_BASE + len(COMPARISON_CODES)`, and baselines store only `FEATURE_DIM_BASE`-length vectors. The comparison features get their own z-score computation in the scoring layer.

---

## Scoring Layer Changes

### Density Matrix Dimensionality

With ~62 features, the density matrix becomes 62×62 = 3,844 entries. Still trivially small (< 32KB). No performance concern.

### Interference Decomposition

The current top-5 constructive / top-5 destructive feature selection should be updated to weight by tier. Specifically, Tier 4 (character n-grams) features should have slightly higher weight in the "destructive" ranking because they are the most edit-resistant — a large deviation on a character n-gram feature is more suspicious than the same deviation on a content-sensitive feature.

Proposed tier weights for destructive feature ranking:

| Tier | Weight | Rationale |
|---|---|---|
| Tier 1 (Surface) | 1.0 | Baseline |
| Tier 2 (Discourse) | 1.0 | Moderate edit resistance |
| Tier 3 (Rhetorical) | 0.8 | More topic-sensitive |
| Tier 4 (Char/Punct) | 1.3 | Most edit-resistant |
| Tier 5 (POS/Syntax) | 1.2 | Good edit resistance |
| Tier 6 (Idiosyncratic) | 1.4 | Highest person-specificity |
| Tier 7 (AI Detection) | 1.1 | Strategic but noisier |

### Entanglement Anomalies

Currently limited to Tier 2 ↔ Tier 3 cross-pairs. Expand to include Tier 4 ↔ Tier 6 (character habits should correlate with idiosyncratic patterns) and Tier 1 ↔ Tier 7 (surface metrics should correlate with AI detection markers).

---

## Calibration Strategy

The current 20-text corpus is a good start but needs expansion to calibrate 62+ features reliably. Target: **50 texts** spanning:

- 20 seminary student papers (existing corpus)
- 10 published theological articles (to anchor the "expert" end)
- 10 AI-generated theological essays (GPT-4, Claude, Gemini — to establish AI baseline)
- 10 non-native English speaker papers (to understand NNE feature distributions)

For each new tier, run the calibration script, compute P05/P95, and verify no CLIP_HI > 10% of the corpus and no HI_TOO_LOOSE features (spread < 20% of the [0,1] range).

---

## Risk Register

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| spaCy model download fails in air-gapped seminary environments | Medium | High (Tier 5 unusable) | Ship model as a Docker layer; provide offline install instructions |
| Character n-gram features overfit to specific keyboard/OS encoding | Low | Medium | Normalize all text to NFC Unicode before extraction |
| AI detection markers become unreliable as LLMs improve | High | Medium | Treat Tier 7 as advisory, not authoritative; weight it lower in action thresholds; plan annual recalibration |
| Feature expansion causes existing baselines to be discarded | Low | High | Already mitigated: `raw_text` column + `rebuild-baselines` CLI |
| POS tagger accuracy drops on theological jargon | Medium | Low | Evaluate spaCy accuracy on a theological test set before shipping; consider fine-tuning if accuracy < 93% |
| Comparison features (divergence) are undefined for students with < 2 baseline samples | Certain | Medium | Default divergence to 0.5 (neutral) when baseline is insufficient; require minimum 3 samples before enabling divergence features |

---

## Dependency Summary

| Phase | New Python Dependencies | New Data Files | Docker Image Impact |
|---|---|---|---|
| Phase 1 (Tier 4) | None | None | None |
| Phase 2 (Tier 6) | None | `data/abbreviation_dict.json` (~5KB) | Negligible |
| Phase 3 (Tier 7) | None | `data/word_frequencies.json` (~500KB) | Negligible |
| Phase 4 (Tier 5) | `spacy>=3.7`, `en_core_web_sm` | None | +12MB model in Docker layer |

---

## Timeline Estimate

| Phase | Effort | Elapsed (with review + testing) |
|---|---|---|
| Phase 1 — Tier 4 | 2 days dev | 1 week |
| Phase 2 — Tier 6 | 2 days dev | 1 week |
| Phase 3 — Tier 7 | 3 days dev | 1.5 weeks |
| Phase 4 — Tier 5 | 3 days dev + 1 day infra | 2 weeks |
| Calibration corpus expansion | 2 days | Can run in parallel |
| Frontend updates (all tiers) | 1 day per tier | Parallel with backend |
| **Total** | **~15 days dev** | **~6 weeks** |

---

## Summary

The current 34-feature, 3-tier system covers lexical, discourse, and rhetorical families well. The critical gaps are character-level patterns (n-grams, punctuation), syntactic patterns (POS n-grams), idiosyncratic habits (errors, formatting preferences), and AI-specific markers. Adding these 4 tiers roughly doubles the feature space to ~62 dimensions, which the quantum scoring infrastructure handles without modification (density matrices scale linearly, `rebuild-baselines` handles migration).

Phase 1 (character & punctuation fingerprint) should ship first because it adds the highest-value, most edit-resistant features with zero new dependencies. The full expansion is achievable in approximately 6 weeks of development time.
