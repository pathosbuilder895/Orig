# Model Card — Original Stylometric Scorer v1.0.0

This document describes the feature pipeline, scoring model, output actions, known limitations, and intended use of the Original authorship detection system.

---

## Intended use

Original is designed for academic integrity review at theological seminaries.  Given a set of authenticated writing samples (baseline) and a new submission, it outputs a deviation score and a recommended action for instructor review.  **Original is a decision-support tool, not a decision-making system.**  All outputs require human review before any institutional action is taken.

---

## Input

- **Baseline samples** — 3 or more authenticated writing samples by the same student (proctored exam essays, verified in-class writing).  Minimum 3 samples to produce a score; minimum 5 to allow an "escalate" recommendation.
- **Submission** — A new text of at least 50 characters.

---

## Feature pipeline — 34 features across three tiers

### Tier 1 — Surface stylometry (9 features)

These measure low-level lexical and syntactic patterns that are consistent across long texts and robust to topic change.

| Code | Description |
|------|-------------|
| `type_token_ratio` | Proportion of unique words to total words — measures lexical diversity |
| `hapax_legomena_rate` | Proportion of words appearing exactly once — a fine-grained diversity signal |
| `mean_sentence_length` | Average number of words per sentence |
| `sentence_length_variance` | Variance in sentence length — rhythmic consistency |
| `function_word_ratio` | Proportion of closed-class words (prepositions, determiners, conjunctions) |
| `passive_voice_ratio` | Proportion of passive voice constructions |
| `modal_verb_ratio` | Proportion of modal verbs (can, should, must, …) |
| `stop_word_ratio` | Proportion of high-frequency stop words |
| `avg_word_length` | Mean character length of content words |

### Tier 2 — Discourse structure (13 features)

These measure how ideas are connected and organised across sentences and paragraphs.

| Code | Description |
|------|-------------|
| `discourse_marker_density` | Overall density of discourse-marking expressions |
| `additive_ratio` | Frequency of additive connectives (furthermore, also, …) |
| `adversative_ratio` | Frequency of contrastive connectives (however, nevertheless, …) |
| `causal_ratio` | Frequency of causal connectives (because, therefore, …) |
| `temporal_ratio` | Frequency of temporal connectives (then, subsequently, …) |
| `thematic_progression_score` | Consistency of topic-comment structure across sentences |
| `pronoun_reference_density` | Density of anaphoric pronouns — a cohesion indicator |
| `lexical_chain_density` | Co-occurrence of semantically related words across paragraphs |
| `paragraph_topic_position` | Tendency to place topic sentences at paragraph start vs. end |
| `avg_paragraph_length` | Average word count per paragraph |
| `sentence_opener_variety` | Variety of syntactic structures used to open sentences |
| `cohesion_device_ratio` | Overall proportion of cohesive devices |
| `transition_density` | Frequency of paragraph-level transition expressions |

### Tier 3 — Rhetorical & register (12 features)

These capture argumentation strategy, epistemic stance, and domain register — the hardest features to consciously mimic.

| Code | Description |
|------|-------------|
| `epistemic_certainty_ratio` | Proportion of high-certainty epistemic expressions (clearly, obviously) |
| `hedging_density` | Density of hedging language (might, perhaps, it seems) |
| `assertion_density` | Ratio of declarative sentences making direct claims |
| `source_integration_style` | Pattern of citation and attribution (integral vs. non-integral) |
| `counter_argument_ratio` | Proportion of text devoted to counter-argument acknowledgement |
| `claim_density` | Density of argument-claim statements |
| `question_ratio` | Frequency of rhetorical or pedagogical questions |
| `imperative_density` | Frequency of imperative mood constructions |
| `first_person_ratio` | Use of first-person stance markers (I argue, we see) |
| `appeal_to_authority_density` | Frequency of named authority references |
| `conclusion_strategy_score` | Pattern of conclusion-signalling expressions |
| `theological_register_score` | Domain-specific theological vocabulary density |

---

## Quantum scoring model

Each student's authenticated baseline samples are used to build a **density matrix** ρ — a weighted sum of outer products of normalised feature vectors, weighted by the provenance authentication weight of each sample.

A new submission is scored by projecting its feature vector ξ onto ρ:

```
P = ξᵀ ρ ξ          (Born probability — how "consistent" ξ is with ρ)
D = 1 − P            (raw deviation)
deviation_score = clip(D_adjusted, 0, 1)
```

The purity `tr(ρ²)` measures how much agreement exists across the baseline samples.  A low-purity baseline (inconsistent baseline writing) reduces the model's confidence and is reflected in the `baseline_confidence` output field.

---

## Output actions

| Action | Deviation range | Baseline condition | Meaning |
|--------|-----------------|--------------------|---------|
| `no_action` | < 0.30 | Any | Submission is stylistically consistent |
| `monitor` | 0.30 – 0.55 | Any | Mild anomaly; flag for passive monitoring |
| `schedule_conversation` | 0.55 – 0.75 | Any | Significant anomaly; recommend 1:1 review |
| `escalate` | > 0.75 | ≥ 5 baseline samples | Strong anomaly; refer for formal review |

The `escalate` action is suppressed and capped to `schedule_conversation` when fewer than 5 baseline samples are available, because low-sample states produce less reliable density matrices.

---

## Confidence and reliability

| Condition | Effect |
|-----------|--------|
| < 3 baseline samples | Scoring blocked — `InsufficientBaselineError` returned |
| 3–4 baseline samples | Scored but `escalate` suppressed |
| Unverified samples (auth_weight = 0) | Excluded from density matrix |
| Low purity (inconsistent baseline) | `baseline_confidence.purity` < 0.5; treat results with caution |

---

## Known limitations

- **Topic dependency** — Tier 1 and 2 features assume the submission and baseline cover broadly similar subject matter.  Cross-domain scoring (theology essay vs. science lab report) is not supported and will produce unreliable results.
- **Length sensitivity** — Texts under ~200 words produce unstable feature estimates.  The 50-character minimum is a hard floor; practical reliability begins around 300 words.
- **Calibration** — The deviation thresholds (0.30, 0.55, 0.75) are set analytically, not empirically calibrated against labelled ground truth.  Institutions are encouraged to log instructor decisions and re-calibrate thresholds against their own population.
- **Bias** — The model has not been formally audited for differential accuracy across demographic or linguistic subgroups.  Non-native English speakers may show systematically higher Tier 1 deviation scores independent of authorship.  A bias audit is listed as a priority future work item.
- **Adversarial robustness** — A sophisticated actor who knows the feature set could potentially manipulate Tier 1 surface features while preserving the actual meaning of a generated text.  Tier 3 rhetorical features are harder to game.

---

## FERPA compliance

All instructor decisions are recorded in an immutable `InstructorDecisions` table (insert-only).  No student text is stored — only its SHA-256 hash and extracted feature vectors.  Institutions are responsible for implementing data retention policies appropriate to their jurisdiction.

---

## Version history

| Version | Date | Changes |
|---------|------|---------|
| 1.0.0 | 2026-03-17 | Initial release — 34-feature pipeline, quantum density matrix scorer |
