"""
constants.py — Feature codes, lexicons, and normalization bounds.

All feature codes mirror the frontend FEATURES array exactly.
Normalization bounds are calibrated to seminary-level academic prose
(1000–5000 word essays, formal theological register).

Tiers 1–18 plus comparison/profile dimensions form the current FEATURE_DIM-dimensional
feature space. Legacy profiles with older dimensions are padded on load.
"""


# ── Feature registry ────────────────────────────────────────────────────────

TIER1_CODES = [
    "type_token_ratio",
    "hapax_legomena_rate",
    "mean_sentence_length",
    "sentence_length_variance",
    "function_word_ratio",
    "passive_voice_ratio",
    "modal_verb_ratio",
    "stop_word_ratio",
    "avg_word_length",
]

TIER2_CODES = [
    "discourse_marker_density",
    "additive_ratio",
    "adversative_ratio",
    "causal_ratio",
    "temporal_ratio",
    "thematic_progression_score",
    "pronoun_reference_density",
    "lexical_chain_density",
    "paragraph_topic_position",
    "avg_paragraph_length",
    "sentence_opener_variety",
    "cohesion_device_ratio",
    "transition_density",
]

TIER3_CODES = [
    "epistemic_certainty_ratio",
    "hedging_density",
    "assertion_density",
    "source_integration_style",
    "counter_argument_ratio",
    "claim_density",
    "question_ratio",
    "imperative_density",
    "first_person_ratio",
    "appeal_to_authority_density",
    "conclusion_strategy_score",
    "theological_register_score",
]

TIER4_CODES = [
    "char_trigram_entropy",
    "punctuation_diversity",
    "comma_rate",
    "semicolon_colon_rate",
    "parenthetical_rate",
    "dash_rate",
    "quote_rate",
]

TIER5_CODES = [
    "pos_bigram_entropy",
    "pos_trigram_entropy",
    "noun_verb_ratio",
    "adjective_rate",
    "adverb_rate",
    "subordination_ratio",
    "clause_depth_mean",
]

TIER6_CODES = [
    "contraction_rate",
    "sentence_initial_conjunction_rate",
    "that_which_ratio",
    "citation_style_consistency",
    "list_marker_preference",
    "abbreviation_tendency",
]

TIER7_CODES = [
    "burstiness",
    "perplexity_proxy",
    "repetition_gap_entropy",
    "transition_predictability",
    "vocabulary_introduction_rate",
    "filler_hedge_cluster_rate",
]

# ── Tiers 8–12: Musical / Cognitive layers ──────────────────────────────────

TIER8_CODES = [
    "stress_entropy_unigram",   # Shannon entropy of syllabic stress unigrams
    "stress_entropy_bigram",    # Shannon entropy of syllabic stress bigrams
    "clausulae_consistency",    # Sentence-final stress pattern consistency
    "breath_group_variance",    # Coefficient of variation of stress-group lengths
]

TIER9_CODES = [
    "structural_centrist_penalty",   # standalone: bigram-diversity vs. AI Q→C→E pattern
    "argument_sequence_likelihood",  # comparison: Markov log-likelihood vs. baseline
]

TIER10_CODES = [
    "semantic_field_dispersion",    # standalone: variance of pairwise embedding distances
    "semantic_centroid_proximity",  # comparison: mean min-dist to baseline centroids
]

TIER11_CODES = [
    "error_kl_divergence",         # comparison: KL-div of error profile vs. baseline
    "stumble_rate_consistency",    # comparison: total error-rate similarity to baseline
    "punctuation_error_ratio",     # comparison: punctuation error rate similarity
]

TIER12_CODES = [
    "catastrophe_index",   # standalone: κ = σ(ρ)·(1−μ(ρ)) from tension arc
]

# ── Tiers 13–15: Deep Prosodic & Lexical Architecture ───────────────────────

TIER13_CODES = [
    "clausula_type_consistency",  # 1 − entropy of sentence-final rhythmic types
    "breath_group_regularity",    # 1/(1+CV) of pause-delimited span lengths
    "vowel_sonority_ratio",       # heavy vowel clusters / total vowel clusters
    "arc_resolution_score",       # whether sentence-length arc resolves at end
    "metric_flatness_score",      # 1−CV of stress density per paragraph (high=AI)
    "clausula_shape_preference",  # dactylic→trochaic→spondaic on [0, 1]
]

TIER14_CODES = [
    "error_topology_consistency", # positional entropy of comma splices
    "article_omission_rate",      # DET-less NPs before nouns per 100 words
    "pronoun_ambiguity_rate",     # fraction of pronouns with ambiguous antecedent
    "comma_splice_rate",          # comma splices per 100 sentences (norm'd)
]

TIER15_CODES = [
    "semantic_field_concentration", # mean pairwise cosine sim of top-20 nouns
    "polysyndeton_ratio",           # poly/(poly+asyndeton) list ratio
    "chiasmus_rate",                # A-B-B-A POS reversals per 100 sent. (norm'd)
    "latinate_ratio",               # Latinate-suffix words / content words
    "nominalization_density",       # -tion/-ment/-ness/-ity per 100 words (norm'd)
]

# ── Tier 17: Behavioral Biometrics ───────────────────────────────────────────
# Derived from live keystroke capture during Bbook proctored exams.
# Only meaningful when keystroke_data is supplied; defaults to 0.5 (neutral)
# when absent (uploaded papers, Canvas imports).  Stored in the same FEATURE_DIM-wide
# feature vector so existing density matrix math requires no changes.
TIER17_CODES = [
    "typing_speed_cv",    # CV of inter-keystroke intervals (rhythm consistency)
    "burst_ratio",        # fraction of keystrokes in rapid bursts (< 150 ms)
    "deletion_rate",      # Backspace/Delete / total keystrokes
    "pause_density",      # long pauses (>3s) per 100 words
    "paste_event_rate",   # paste events per 100 words
    "revision_depth",     # mean chars affected per deletion event
]

# ── Tier 16: Citation Fingerprint ─────────────────────────────────────────────
# Derived from *how* the student uses sources — signal verb variety, source
# loyalty, block-quote habit, footnote style, paraphrase preference.
# Computed from CitationData (extracted in preprocess.py before prose stripping).
TIER16_CODES = [
    "signal_verb_entropy",       # Shannon entropy of signal verb distribution (bits)
    "signal_verb_assertiveness", # Mean assertiveness of signal verbs [0, 1]
    "source_loyalty_index",      # Fraction of citations that are repeat authors
    "block_quote_rate",          # Block-quote words per 1000 prose words
    "citation_density_cv",       # CV of citations per paragraph (clustering)
    "ibid_usage_rate",           # ibid./op.cit. / total citations
    "citation_position_pref",    # Mean relative citation position in sentence [0=start, 1=end]
    "paraphrase_density",        # Paraphrase-attribution phrases per 100 prose words
]

# ── Tier 18: Uniformity (second-moment) ──────────────────────────────────────
# Generation-artifact detector: current features are per-document MEANS;
# LLM/ghostwritten text is often unusually uniform in its WITHIN-document
# spread. Four comparison features (need a baseline), two standalone.
# Disabled by default pending gates G2b (paraphrase-resistance) and G6
# (native_english fairness parity) — see design spec §8.
TIER18_CODES = [
    "sentence_length_dispersion_ratio",
    "window_feature_variance_ratio",
    "function_word_burstiness_ratio",
    "punctuation_dispersion_ratio",
    "vocab_introduction_flatness",
    "clause_depth_variance_ratio",
]

# Musical comparison features — require baseline profiles (like COMPARISON_CODES)
MUSICAL_COMPARISON_CODES = [
    "argument_sequence_likelihood",
    "semantic_centroid_proximity",
    "error_kl_divergence",
    "stumble_rate_consistency",
    "punctuation_error_ratio",
]

# Comparison features — computed at scoring time, not during extraction.
# They require both submission and baseline profiles.
COMPARISON_CODES = [
    "char_trigram_profile_divergence",
    "function_word_profile_divergence",
]

ALL_FEATURE_CODES = (
    TIER1_CODES + TIER2_CODES + TIER3_CODES
    + TIER4_CODES + TIER5_CODES + TIER6_CODES + TIER7_CODES
    + TIER8_CODES + TIER9_CODES + TIER10_CODES + TIER11_CODES + TIER12_CODES
    + TIER13_CODES + TIER14_CODES + TIER15_CODES
    + TIER16_CODES
    + TIER17_CODES
    + TIER18_CODES
    + COMPARISON_CODES
)
FEATURE_DIM = len(ALL_FEATURE_CODES)  # 109

# Base features (extracted from text alone or keystroke data; stored in baseline samples).
# Tier 17 features default to 0.5 when keystroke data is absent — they are included
# in BASE_FEATURE_CODES so the density matrix dimension stays fixed at 96 base dims.
BASE_FEATURE_CODES = (
    TIER1_CODES + TIER2_CODES + TIER3_CODES
    + TIER4_CODES + TIER5_CODES + TIER6_CODES + TIER7_CODES
    + TIER8_CODES
    + ["structural_centrist_penalty"]   # Tier 9 standalone
    + ["semantic_field_dispersion"]     # Tier 10 standalone
    + TIER12_CODES
    + TIER13_CODES + TIER14_CODES + TIER15_CODES  # all Tier 13–15 are standalone
    + TIER16_CODES                                # Tier 16 — all standalone
    + TIER17_CODES                                # Tier 17 — keystroke (0.5 when absent)
    + TIER18_CODES                                # Tier 18 — uniformity (0.5 when disabled)
)
BASE_FEATURE_DIM = len(BASE_FEATURE_CODES)  # 102 (was 96 before Tier 18)

FEATURE_TIER: dict[str, int] = (
    {c: 1  for c in TIER1_CODES}
    | {c: 2  for c in TIER2_CODES}
    | {c: 3  for c in TIER3_CODES}
    | {c: 4  for c in TIER4_CODES}
    | {c: 5  for c in TIER5_CODES}
    | {c: 6  for c in TIER6_CODES}
    | {c: 7  for c in TIER7_CODES}
    | {c: 8  for c in TIER8_CODES}
    | {c: 9  for c in TIER9_CODES}
    | {c: 10 for c in TIER10_CODES}
    | {c: 11 for c in TIER11_CODES}
    | {c: 12 for c in TIER12_CODES}
    | {c: 13 for c in TIER13_CODES}
    | {c: 14 for c in TIER14_CODES}
    | {c: 15 for c in TIER15_CODES}
    | {c: 16 for c in TIER16_CODES}
    | {c: 17 for c in TIER17_CODES}
    | {c: 18 for c in TIER18_CODES}
    | {c: 0  for c in COMPARISON_CODES}  # tier 0 = comparison (meta)
)

# Tier weights for destructive feature ranking in interference decomposition.
# Higher = more suspicious when deviating.
TIER_WEIGHTS: dict[int, float] = {
    0:  1.2,   # comparison features (meta)
    1:  1.0,   # surface stylometrics (baseline)
    2:  0.6,   # discourse structure — down from 1.0; topic-sensitive features
               #            (discourse markers, pronoun density, transitions) shift with
               #            topic even within same-author writing → rms_z=55 on legit holdouts.
               #            Phase 3 resolver will context-normalize further when genre matches.
    3:  0.8,   # rhetorical/register (more topic-sensitive)
    4:  1.3,   # char/punct fingerprint (most edit-resistant)
    5:  1.2,   # POS/syntax (good edit resistance)
    6:  1.4,   # idiosyncratic (highest person-specificity)
    7:  1.1,   # AI detection (strategic but noisier)
    8:  1.1,   # prosodic rhythm (edit-resistant rhythmic fingerprint)
    9:  0.9,   # argument topology (partially topic-sensitive)
    10: 1.0,   # semantic gravity wells (conceptual fingerprint)
    11: 1.4,   # error ecology (highest proof-of-life value, matches Tier 6)
    12: 1.2,   # tension arc (structural AI signal)
    13: 1.3,   # prosodic depth (clausula patterns — highly edit-resistant)
    14: 1.3,   # error topology (consistent personal error placement)
    15: 1.2,   # lexical architecture (Latinate/nominalization fingerprint)
    16: 1.4,   # citation fingerprint (highly unconscious — matches Tier 6/11)
    17: 1.5,   # behavioral biometrics (live keystroke — highest tamper-resistance)
    18: 1.3,   # uniformity (second-moment generation-artifact signal)
}


# ── Length-adaptive tier weighting (Phase 2 of length-stability work) ─────────
#
# Derived from the per-tier Fisher-ratio stability study in
# validation/stability/2026-08-01/per_tier_summary.csv — the re-run on the
# DECONTAMINATED public-author corpus (the 2026-06-30 study this schedule
# was first derived from had a French novel standing in for edwards and
# ~32k words of index/footnote back-matter in james; see
# validation/stability/2026-08-01/COMPARISON_vs_2026-06-30.md). On short
# inputs (≤ ~750 words) most tiers' features stop discriminating between
# authors — their between-author variance only opens up once enough text
# is available. On the clean corpus the strongest short-window tiers are
# 8 (prosodic rhythm), 1 (surface), 4 (char/punct), and 15 (lexical
# architecture); tiers 6 and 9 collapse, and the old marquee tiers 5/7
# (amplified 1.56 in the contaminated derivation) turn out to be below-
# median at 500 words — burstiness/POS/function-word stats were mostly
# doing language ID against the French text.
#
# Re-derive with:
#   .venv/bin/python -m validation.stability.derive_schedule \
#       validation/stability/2026-08-01/per_tier_summary.csv
#
# When LENGTH_ADAPTIVE_WEIGHTS=1, scoring.py multiplies _TIER_WEIGHT_VECTOR
# by the per-tier factor from the bucket matching the submission's word
# count. "short" factors are F(500,tier)/median over the measurable tiers
# (clipped, then rescaled — see below); "medium" is the midpoint of the
# clipped short factor and 1.0; tiers with no measurable text-only
# features (11, 12) take the 0.5 floor and tiers absent from the study
# (0 comparison, 17 behavioral) are neutral. Identity at "long" preserves
# existing behaviour on full essays.
#
# Bucket cutoffs match the stability-study lengths so a reviewer can map
# a feature's behaviour at L back to the factor here:
#   short   : ≤ 750 words   (covers the 250 + 500 stability rows)
#   medium  : 750 - 2500    (covers the 1000 + 2000 rows)
#   long    : > 2500 words  (covers the 5000 row + everything beyond)
LENGTH_BUCKETS_BY_TOKENS: dict[str, tuple] = {
    "short":  (0,     750),
    "medium": (750,   2500),
    "long":   (2500,  10**9),
}

LENGTH_WEIGHT_SCHEDULE: dict[str, dict[int, float]] = {
    # "short" factors are F(500, tier) / median(F(500, ·)), clipped to
    # [0.5, 2.0], THEN rescaled so that sum((TIER_WEIGHTS × factor)²)
    # across the FEATURE_DIM features equals sum(TIER_WEIGHTS²) — the
    # baseline. Preserving Σ(w²) means the length-adaptive flag can't
    # inflate or deflate the tanh-calibrated rms_z on average; it just
    # RE-DISTRIBUTES weight across tiers.
    #
    # The naive "mean factor = 1.0" normalisation was NOT enough — a
    # schedule with high variance across tiers still increases Σ(w²)
    # (variance adds to the sum-of-squares). At N=717 on the seminary
    # corpus that first fix left mean deviation elevated 0.796 → 0.893
    # and collapsed threshold-based classification. See
    # validation/stability/lift_seminary_normalized_2026-06-30.json — the
    # Σ(w²) rescale absorbs any such uniform normalisation, so the raw
    # clipped factors are rescaled directly.
    #
    # Rescale factor for short: 1 / 1.2251 (Σ(w²)-preserving).
    # F(500) values below are the clean 2026-08-01 per-tier means.
    "short": {
        0:  0.82,   # comparison — not in the study, neutral 1.0 raw
        1:  1.63,   # surface stylometrics: F(500)=0.600, capped 2.0
        2:  0.75,   # discourse: F(500)=0.261
        3:  0.83,   # rhetorical: F(500)=0.290
        4:  1.61,   # char/punct: F(500)=0.558
        5:  0.83,   # POS/syntax: F(500)=0.288 (was 2.81 contaminated → capped)
        6:  0.85,   # idiosyncratic: F(500)=0.297
        7:  0.66,   # AI/burstiness: F(500)=0.228 (was 6.22 contaminated → capped)
        8:  1.63,   # prosodic rhythm: F(500)=1.067 (highest), capped
        9:  0.41,   # argument: F(500)=0.104, floored 0.5
        10: 0.41,   # semantic gravity: F(500)=0.046 (lowest), floored
        11: 0.41,   # error ecology — F=0 on text-only inputs
        12: 0.41,   # tension arc — F=0 on text-only inputs
        13: 0.80,   # prosodic depth: F(500)=0.279
        14: 0.63,   # error topology: F(500)=0.219
        15: 1.47,   # lexical architecture: F(500)=0.511
        16: 0.41,   # citation: F(500)=0.097, floored
        17: 0.82,   # behavioral — text-length-independent, neutral 1.0 raw
    },
    "medium": {
        # Midpoint of clipped short raw factor and 1.0, then rescaled
        # by 1 / 1.0870 (Σ(w²)-preserving).
        0:  0.92, 1:  1.38, 2:  0.88, 3:  0.93, 4:  1.37,
        5:  0.93, 6:  0.94, 7:  0.83, 8:  1.38, 9:  0.69,
        10: 0.69, 11: 0.69, 12: 0.69, 13: 0.91, 14: 0.82,
        15: 1.29, 16: 0.69, 17: 0.92,
    },
    "long":  {t: 1.0 for t in range(18)},   # identity — preserve existing behaviour
}

# ── Feature group toggles ────────────────────────────────────────────────────
# Groups of features that require specific capabilities to produce real values.
# When a group is in DISABLED_FEATURE_GROUPS, or its capability is unavailable,
# features return 0.5 (neutral) and are automatically excluded from the density
# matrix by the active_feature_mask in state.py.
#
# Modify at runtime to enable/disable groups as capabilities become available:
#   from original.constants import DISABLED_FEATURE_GROUPS
#   DISABLED_FEATURE_GROUPS.discard("behavioral")  # enable when keystroke data flows
#   DISABLED_FEATURE_GROUPS.add("semantic")        # disable if ST unavailable
#
FEATURE_GROUPS: dict[str, list] = {
    "behavioral": TIER17_CODES,
    "uniformity": TIER18_CODES,
    "semantic":   ["semantic_field_dispersion", "semantic_centroid_proximity"],
    "pos_syntax": TIER5_CODES,
}

# Disabled by default — remove entries as capabilities come online.
DISABLED_FEATURE_GROUPS: set = {
    "behavioral",   # requires live keystroke data from Bbook exam environment
    "uniformity",   # pending gates G2b (paraphrase-resistance) and G6 (fairness parity)
}

FEATURE_NAMES: dict[str, str] = {
    "type_token_ratio":           "Type-Token Ratio",
    "hapax_legomena_rate":        "Hapax Legomena Rate",
    "mean_sentence_length":       "Mean Sentence Length",
    "sentence_length_variance":   "Sentence Length Variance",
    "function_word_ratio":        "Function Word Ratio",
    "passive_voice_ratio":        "Passive Voice Ratio",
    "modal_verb_ratio":           "Modal Verb Ratio",
    "stop_word_ratio":            "Stop Word Ratio",
    "avg_word_length":            "Avg Word Length",
    "discourse_marker_density":   "Discourse Marker Density",
    "additive_ratio":             "Additive Ratio",
    "adversative_ratio":          "Adversative Ratio",
    "causal_ratio":               "Causal Ratio",
    "temporal_ratio":             "Temporal Ratio",
    "thematic_progression_score": "Thematic Progression",
    "pronoun_reference_density":  "Pronoun Ref. Density",
    "lexical_chain_density":      "Lexical Chain Density",
    "paragraph_topic_position":   "Paragraph Topic Pos.",
    "avg_paragraph_length":       "Avg Paragraph Length",
    "sentence_opener_variety":    "Sentence Opener Variety",
    "cohesion_device_ratio":      "Cohesion Device Ratio",
    "transition_density":         "Transition Density",
    "epistemic_certainty_ratio":  "Epistemic Certainty",
    "hedging_density":            "Hedging Density",
    "assertion_density":          "Assertion Density",
    "source_integration_style":   "Source Integration Style",
    "counter_argument_ratio":     "Counter-Argument Ratio",
    "claim_density":              "Claim Density",
    "question_ratio":             "Question Ratio",
    "imperative_density":         "Imperative Density",
    "first_person_ratio":         "First-Person Ratio",
    "appeal_to_authority_density":"Authority Appeal Density",
    "conclusion_strategy_score":  "Conclusion Strategy",
    "theological_register_score": "Theological Register",
    # Tier 4 — Character & Punctuation
    "char_trigram_entropy":       "Char Trigram Entropy",
    "punctuation_diversity":      "Punctuation Diversity",
    "comma_rate":                 "Comma Rate",
    "semicolon_colon_rate":       "Semicolon+Colon Rate",
    "parenthetical_rate":         "Parenthetical Rate",
    "dash_rate":                  "Dash Rate",
    "quote_rate":                 "Quotation Rate",
    # Tier 5 — POS & Syntax
    "pos_bigram_entropy":         "POS Bigram Entropy",
    "pos_trigram_entropy":        "POS Trigram Entropy",
    "noun_verb_ratio":            "Noun-Verb Ratio",
    "adjective_rate":             "Adjective Rate",
    "adverb_rate":                "Adverb Rate",
    "subordination_ratio":        "Subordination Ratio",
    "clause_depth_mean":          "Mean Clause Depth",
    # Tier 6 — Idiosyncratic
    "contraction_rate":                 "Contraction Rate",
    "sentence_initial_conjunction_rate": "Sent-Initial Conj Rate",
    "that_which_ratio":                 "That/Which Ratio",
    "citation_style_consistency":       "Citation Consistency",
    "list_marker_preference":           "List Marker Pref.",
    "abbreviation_tendency":            "Abbreviation Tendency",
    # Tier 7 — AI Detection
    "burstiness":                   "Burstiness",
    "perplexity_proxy":             "Perplexity Proxy",
    "repetition_gap_entropy":       "Repetition Gap Entropy",
    "transition_predictability":    "Transition Predictability",
    "vocabulary_introduction_rate": "Vocab Introduction Rate",
    "filler_hedge_cluster_rate":    "Hedge Clustering",
    # Tier 8 — Prosodic Rhythm
    "stress_entropy_unigram":       "Stress Entropy (Unigram)",
    "stress_entropy_bigram":        "Stress Entropy (Bigram)",
    "clausulae_consistency":        "Clausulae Consistency",
    "breath_group_variance":        "Breath-Group Variance",
    # Tier 9 — Cognitive Sequencing
    "structural_centrist_penalty":  "Structural Centrist Penalty",
    "argument_sequence_likelihood": "Argument Sequence Likelihood",
    # Tier 10 — Semantic Gravity Wells
    "semantic_field_dispersion":    "Semantic Field Dispersion",
    "semantic_centroid_proximity":  "Semantic Centroid Proximity",
    # Tier 11 — Error Ecology
    "error_kl_divergence":          "Error Profile KL-Divergence",
    "stumble_rate_consistency":     "Stumble-Rate Consistency",
    "punctuation_error_ratio":      "Punctuation-Error Ratio",
    # Tier 12 — Tension Arc
    "catastrophe_index":            "Catastrophe Index (κ)",
    # Tier 13 — Prosodic Depth
    "clausula_type_consistency":  "Clausula Type Consistency",
    "breath_group_regularity":    "Breath-Group Regularity",
    "vowel_sonority_ratio":       "Vowel Sonority Ratio",
    "arc_resolution_score":       "Arc Resolution Score",
    "metric_flatness_score":      "Metric Flatness (AI Signal)",
    "clausula_shape_preference":  "Clausula Shape Preference",
    # Tier 14 — Error Topology & Syntax
    "error_topology_consistency": "Error Topology Consistency",
    "article_omission_rate":      "Article Omission Rate",
    "pronoun_ambiguity_rate":     "Pronoun Ambiguity Rate",
    "comma_splice_rate":          "Comma Splice Rate",
    # Tier 15 — Lexical Architecture
    "semantic_field_concentration": "Semantic Field Concentration",
    "polysyndeton_ratio":           "Polysyndeton Ratio",
    "chiasmus_rate":                "Chiasmus/Antithesis Rate",
    "latinate_ratio":               "Latinate Vocabulary Ratio",
    "nominalization_density":       "Nominalization Density",
    # Tier 16 — Citation Fingerprint
    "signal_verb_entropy":       "Signal Verb Entropy",
    "signal_verb_assertiveness": "Signal Verb Assertiveness",
    "source_loyalty_index":      "Source Loyalty Index",
    "block_quote_rate":          "Block-Quote Rate",
    "citation_density_cv":       "Citation Density CV",
    "ibid_usage_rate":           "Ibid. Usage Rate",
    "citation_position_pref":    "Citation Position Preference",
    "paraphrase_density":        "Paraphrase Density",
    # Tier 17 — Behavioral Biometrics
    "typing_speed_cv":   "Typing Rhythm CV",
    "burst_ratio":       "Burst Typing Ratio",
    "deletion_rate":     "Deletion Rate",
    "pause_density":     "Pause Density",
    "paste_event_rate":  "Paste Event Rate",
    "revision_depth":    "Revision Depth",
    # Tier 18 — Uniformity (second-moment)
    "sentence_length_dispersion_ratio": "Sentence-Length Dispersion",
    "window_feature_variance_ratio":    "Window Feature Variance",
    "function_word_burstiness_ratio":   "Function-Word Burstiness",
    "punctuation_dispersion_ratio":     "Punctuation Dispersion",
    "vocab_introduction_flatness":      "Vocab Introduction Flatness",
    "clause_depth_variance_ratio":      "Clause-Depth Variance",
    # Comparison features
    "char_trigram_profile_divergence":    "Char Trigram Divergence",
    "function_word_profile_divergence":   "Func Word Divergence",
}

# ── Normalization bounds (raw → [0, 1]) ─────────────────────────────────────
# (min, max) for each feature in raw units.
# Values outside these bounds are clipped.

NORM_BOUNDS: dict[str, tuple[float, float]] = {
    # Tier 1 — Surface stylometry
    # Empirically calibrated on a 20-text theological essay corpus (2026-03-17).
    # Bounds are set at (P05 − margin, P95 + margin) with manual review.
    # See docs/calibration/norm_bounds_calibration_2026-03-17.md for full report.
    "type_token_ratio":           (0.42, 0.85),   # P05=0.45, P95=0.76
    "hapax_legomena_rate":        (0.15, 0.72),   # unchanged; P05=0.30, P95=0.66 — within range
    "mean_sentence_length":       (4.0,  45.0),   # widened lo: short NNE texts; widened hi: complex academic (P95=41.8)
    "sentence_length_variance":   (0.0,  100.0),  # P95=68.7; 200 was far too loose
    "function_word_ratio":        (0.28, 0.58),   # tightened: P05=0.31, P95=0.52
    "passive_voice_ratio":        (0.00, 0.70),   # CLIP_HI fixed: P95=0.667 (philosophical/systematic theology)
    "modal_verb_ratio":           (0.00, 0.08),   # HI_TOO_LOOSE fixed: P95=0.033; 0.08 gives 2× headroom
    "stop_word_ratio":            (0.28, 0.60),   # tightened: P05=0.31, P95=0.55
    "avg_word_length":            (3.5,  7.0),    # P05=3.7, P95=6.0; kept generous
    # Tier 2 — Discourse structure
    "discourse_marker_density":   (0.0,  6.0),    # HI_TOO_LOOSE fixed: P95=4.1; 14 compressed real range
    "additive_ratio":             (0.0,  0.60),   # P95=0.50; small margin added
    "adversative_ratio":          (0.0,  1.00),   # unchanged; full [0,1] range observed
    "causal_ratio":               (0.0,  0.60),   # P95=0.50; small margin added
    "temporal_ratio":             (0.0,  1.00),   # CLIP_HI fixed: P95=1.0 (historical survey texts)
    "thematic_progression_score": (0.0,  0.30),   # HI_TOO_LOOSE fixed: P95=0.20; 1.0 was 5× too wide
    "pronoun_reference_density":  (0.0,  2.5),    # unchanged; P95=2.17 within range
    "lexical_chain_density":      (0.0,  0.15),   # HI_TOO_LOOSE fixed: P95=0.094; 0.65 compressed all variation
    "paragraph_topic_position":   (0.0,  1.0),    # unchanged; binary feature
    "avg_paragraph_length":       (1.5,  22.0),   # CLIP_HI fixed: P95=19.0 (academic texts with long paragraphs)
    "sentence_opener_variety":    (0.0,  1.0),    # unchanged; full [0,1] range observed
    "cohesion_device_ratio":      (0.0,  0.40),   # CLIP_HI fixed: P95=0.354; 0.30 was too tight
    "transition_density":         (0.0,  6.0),    # tightened: P95=4.7; 7.0 was slightly loose
    # Tier 3 — Rhetorical & register
    # NOTE: counter_argument_ratio, imperative_density, and conclusion_strategy_score
    # all showed degenerate distributions in calibration (single-value output).
    # These extractors require investigation before their scores should be used for
    # flagging. Bounds left at design intent; see bias audit report for details.
    "epistemic_certainty_ratio":  (0.0,  1.0),    # full [0,1] range; unchanged
    "hedging_density":            (0.0,  5.0),    # HI_TOO_LOOSE fixed: P95=2.21; 10.0 was 4.5× too wide
    "assertion_density":          (0.0,  5.0),    # HI_TOO_LOOSE fixed: P95=0.81; 12.0 compressed all variation
    "source_integration_style":   (0.0,  1.0),    # full [0,1] range; unchanged
    "counter_argument_ratio":     (0.0,  1.0),    # ⚠ extractor degenerate (see bias audit); bounds widened to [0,1]
    "claim_density":              (0.0,  5.0),    # HI_TOO_LOOSE fixed: P95=0.75; 12.0 was far too wide
    "question_ratio":             (0.0,  0.35),   # unchanged; P95=0.20 within range
    "imperative_density":         (0.0,  5.0),    # ⚠ extractor degenerate (P95=0); design intent preserved
    "first_person_ratio":         (0.0,  1.0),    # full [0,1] range; unchanged
    "appeal_to_authority_density":(0.0,  5.0),    # HI_TOO_LOOSE fixed: P95=1.47; 12.0 compressed all variation
    "conclusion_strategy_score":  (0.0,  1.0),    # ⚠ extractor degenerate (P95=0); design intent preserved
    "theological_register_score": (0.0,  0.50),   # tightened: P95=0.31; 1.0 too wide for this lexicon
    # Tier 4 — Character & Punctuation Fingerprint
    # Initial bounds set wide (P01/P99 estimates); calibrate on corpus after first run.
    "char_trigram_entropy":       (6.0,  12.0),   # bits; typical prose 8–11 bits
    "punctuation_diversity":      (0.0,   3.5),   # bits; 0=no punct, ~3.5=very diverse
    "comma_rate":                 (0.0,  12.0),   # per 100 words; typical 3–8
    "semicolon_colon_rate":       (0.0,   3.0),   # per 100 words; rare in most writing
    "parenthetical_rate":         (0.0,   3.0),   # per 100 words
    "dash_rate":                  (0.0,   2.0),   # per 100 words
    "quote_rate":                 (0.0,   4.0),   # per 100 words
    # Tier 5 — POS & Shallow Syntax
    "pos_bigram_entropy":         (3.0,   8.0),   # bits
    "pos_trigram_entropy":        (4.0,  11.0),   # bits; higher than bigram
    "noun_verb_ratio":            (0.5,   4.0),   # typical academic prose 1.2–2.5
    "adjective_rate":             (2.0,  12.0),   # per 100 tokens
    "adverb_rate":                (1.0,   8.0),   # per 100 tokens
    "subordination_ratio":        (0.0,   2.0),   # SCONJ per sentence
    "clause_depth_mean":          (2.0,   8.0),   # average tree depth per sentence
    # Tier 6 — Idiosyncratic & Error Patterns
    "contraction_rate":                 (0.0,   5.0),   # per 100 words; 0 in formal, up to 3 in casual
    "sentence_initial_conjunction_rate": (0.0,   0.30),  # fraction of sentences
    "that_which_ratio":                 (0.0,   1.0),   # full [0,1] range
    "citation_style_consistency":       (0.0,   1.0),   # normalized entropy [0,1]
    "list_marker_preference":           (0.0,   1.0),   # categorical encoding [0,1]
    "abbreviation_tendency":            (0.0,   1.0),   # ratio [0,1]
    # Tier 7 — AI Detection Markers
    "burstiness":                   (0.0,  25.0),   # variance/mean; high for bursty human text
    "perplexity_proxy":             (5.0,  15.0),   # bits; higher = more surprising
    "repetition_gap_entropy":       (0.0,   6.0),   # bits
    "transition_predictability":    (0.0,   1.0),   # cosine similarity [0,1]
    "vocabulary_introduction_rate": (0.4,   1.0),   # AUC [0.4, 1.0]; uniform ≈ 0.55
    "filler_hedge_cluster_rate":    (0.0,   1.0),   # Gini coefficient [0,1]
    # Tier 8 — Prosodic Rhythm (all outputs already ∈ [0,1])
    "stress_entropy_unigram":       (0.0, 1.0),
    "stress_entropy_bigram":        (0.0, 1.0),
    "clausulae_consistency":        (0.0, 1.0),
    "breath_group_variance":        (0.0, 1.0),
    # Tier 9 — Cognitive Sequencing
    "structural_centrist_penalty":  (0.0, 1.0),
    "argument_sequence_likelihood": (0.0, 1.0),
    # Tier 10 — Semantic Gravity Wells
    "semantic_field_dispersion":    (0.0, 1.0),
    "semantic_centroid_proximity":  (0.0, 1.0),
    # Tier 11 — Error Ecology
    "error_kl_divergence":          (0.0, 1.0),
    "stumble_rate_consistency":     (0.0, 1.0),
    "punctuation_error_ratio":      (0.0, 1.0),
    # Tier 12 — Tension Arc
    "catastrophe_index":            (0.0, 1.0),
    # Tier 13 — Prosodic Depth (all outputs ∈ [0,1])
    "clausula_type_consistency":  (0.0, 1.0),
    "breath_group_regularity":    (0.0, 1.0),
    "vowel_sonority_ratio":       (0.0, 1.0),
    "arc_resolution_score":       (0.0, 1.0),
    "metric_flatness_score":      (0.0, 1.0),
    "clausula_shape_preference":  (0.0, 1.0),
    # Tier 14 — Error Topology & Syntax (all outputs ∈ [0,1])
    "error_topology_consistency": (0.0, 1.0),
    "article_omission_rate":      (0.0, 1.0),
    "pronoun_ambiguity_rate":     (0.0, 1.0),
    "comma_splice_rate":          (0.0, 1.0),
    # Tier 15 — Lexical Architecture (all outputs ∈ [0,1])
    "semantic_field_concentration": (0.0, 1.0),
    "polysyndeton_ratio":           (0.0, 1.0),
    "chiasmus_rate":                (0.0, 1.0),
    "latinate_ratio":               (0.0, 1.0),
    "nominalization_density":       (0.0, 1.0),
    # Tier 16 — Citation Fingerprint
    # Calibrated on seminary-level academic prose (theological essays 1000–5000 words).
    # signal_verb_entropy: bits; 0=single verb, ~3.5=8 equally used verbs
    "signal_verb_entropy":       (0.0,  3.5),
    # signal_verb_assertiveness: already [0,1] from SIGNAL_VERB_ASSERTIVENESS scores
    "signal_verb_assertiveness": (0.0,  1.0),
    # source_loyalty_index: fraction [0,1]; 0=all unique authors, 1=one author repeated
    "source_loyalty_index":      (0.0,  1.0),
    # block_quote_rate: words per 1000; heavy block-quoters reach 200+
    "block_quote_rate":          (0.0,  200.0),
    # citation_density_cv: coefficient of variation; 0=uniform, 3.0=extreme clustering
    "citation_density_cv":       (0.0,  3.0),
    # ibid_usage_rate: fraction [0,1]; footnote-heavy papers may approach 0.4
    "ibid_usage_rate":           (0.0,  0.4),
    # citation_position_pref: already [0,1]; 0=start, 1=end
    "citation_position_pref":    (0.0,  1.0),
    # paraphrase_density: per 100 words; typical 0–3 markers per 100 words
    "paraphrase_density":        (0.0,  3.0),
    # Tier 17 — Behavioral Biometrics (from Bbook live keystroke capture)
    # Defaults to 0.5 (neutral) when keystroke data is absent.
    "typing_speed_cv":   (0.0,  2.0),   # CV of IKI; 0=perfectly even, 2=highly variable
    "burst_ratio":       (0.0,  1.0),   # fraction of keystrokes < 150 ms apart
    "deletion_rate":     (0.0,  0.5),   # deletions / total keystrokes; >0.4 is unusual
    "pause_density":     (0.0,  20.0),  # long pauses per 100 words; >15 is unusual
    "paste_event_rate":  (0.0,  5.0),   # paste events per 100 words; should be ~0
    "revision_depth":    (0.0,  50.0),  # mean chars per deletion; >30 = bulk rewriting
    # Tier 18 — Uniformity (second-moment generation-artifact signal)
    # Example bounds, to be refreshed by scripts/calibrate_bounds.py once real
    # corpus data exists — see design spec §8. Disabled by default.
    "sentence_length_dispersion_ratio": (0.3, 2.0),
    "window_feature_variance_ratio":    (0.3, 2.0),
    "function_word_burstiness_ratio":   (0.3, 2.0),
    "punctuation_dispersion_ratio":     (0.3, 2.0),
    "vocab_introduction_flatness":      (0.0, 1.0),
    "clause_depth_variance_ratio":      (0.3, 2.0),
    # Comparison features (divergence scores computed at scoring time)
    "char_trigram_profile_divergence":  (0.0,  2.0),   # KL-divergence (bits); 0=identical
    "function_word_profile_divergence": (0.0,  1.5),   # KL-divergence (bits); 0=identical
}

# ── Authentication provenance weights ────────────────────────────────────────

AUTH_WEIGHTS = {
    "proctored":   2.0,   # live Bbook exam — gold-standard, cannot be ghostwritten
    "verified":    1.0,   # instructor-confirmed paper
    "canvas":      0.8,   # LMS-imported (Canvas/Blackboard)
    "unverified":  0.5,   # student self-upload — lowest trust
}

RECENCY_DECAY = 0.85  # λ — weight of sample i = λ^(N-1-i), newest = 1.0

# ── Thresholds ───────────────────────────────────────────────────────────────

TRAJECTORY_GROWTH_THRESHOLD    = 0.25   # cos sim above this → growth
TRAJECTORY_REGRESSIVE_THRESHOLD = -0.20  # cos sim below this → regressive
TRAJECTORY_MIN_SAMPLES          = 3      # need ≥3 samples to estimate trajectory

# Publish-sync: README.md action table, MODEL_CARD.md action table, OWNERS_MANUAL.md — update all three if these boundaries move.
ACTION_THRESHOLDS = {
    "no_action":            (0.00, 0.40),
    "monitor":              (0.40, 0.60),   # raised from 0.55 — absorbs same-author
                                            # natural variance (holdout σ≈0.036,
                                            # observed max 0.554 before this fix)
    "schedule_conversation":(0.60, 0.75),
    "escalate":             (0.75, 1.00),
}

# ── Lexicons ─────────────────────────────────────────────────────────────────

FUNCTION_WORDS = {
    "a", "an", "the", "and", "but", "or", "nor", "for", "yet", "so",
    "at", "by", "from", "in", "into", "of", "on", "to", "up",
    "with", "as", "that", "this", "these", "those", "it", "its",
    "he", "she", "they", "we", "you", "i", "me", "him", "her", "us",
    "them", "my", "your", "his", "our", "their", "which", "who",
    "whom", "whose", "what", "when", "where", "how", "if", "whether",
    "because", "although", "while", "since", "until", "unless", "after",
    "before", "during", "between", "through", "about", "against", "among",
    "around", "without", "within", "along", "following", "across", "behind",
    "beyond", "plus", "except", "out", "than", "there", "been",
    "be", "am", "is", "are", "was", "were", "do", "does", "did",
    "have", "has", "had", "will", "would", "could", "should", "shall",
    "may", "might", "must", "can", "need", "dare", "ought",
}

STOP_WORDS = FUNCTION_WORDS | {
    "also", "just", "even", "only", "very", "quite", "rather", "much",
    "more", "most", "some", "any", "all", "both", "each", "few", "many",
    "other", "such", "no", "not", "same", "then", "so", "too", "here",
    "well", "now", "already", "still", "again", "never", "always", "often",
    "usually", "however", "therefore", "thus", "hence", "indeed", "moreover",
    "furthermore", "nevertheless", "nonetheless", "accordingly",
}

MODAL_VERBS = {
    "can", "cannot", "can't", "could", "couldn't",
    "may", "might", "must", "mustn't",
    "shall", "should", "shouldn't",
    "will", "would", "wouldn't", "won't",
    "ought", "dare", "need",
}

PERSONAL_PRONOUNS = {
    "i", "me", "my", "mine", "myself",
    "we", "us", "our", "ours", "ourselves",
    "he", "him", "his", "himself",
    "she", "her", "hers", "herself",
    "they", "them", "their", "theirs", "themselves",
    "it", "its", "itself",
    "you", "your", "yours", "yourself", "yourselves",
}

FIRST_PERSON = {"i", "me", "my", "mine", "myself", "we", "us", "our", "ours", "ourselves"}

DISCOURSE_MARKERS = {
    # Additive
    "furthermore":    "additive",
    "moreover":       "additive",
    "additionally":   "additive",
    "in addition":    "additive",
    "also":           "additive",
    "likewise":       "additive",
    "similarly":      "additive",
    "in the same way":"additive",
    "as well":        "additive",
    "besides":        "additive",
    # Adversative
    "however":        "adversative",
    "nevertheless":   "adversative",
    "nonetheless":    "adversative",
    "yet":            "adversative",
    "but":            "adversative",
    "on the other hand": "adversative",
    "in contrast":    "adversative",
    "by contrast":    "adversative",
    "conversely":     "adversative",
    "instead":        "adversative",
    "despite":        "adversative",
    "although":       "adversative",
    "even though":    "adversative",
    "while":          "adversative",
    "whereas":        "adversative",
    "though":         "adversative",
    # Causal
    "therefore":      "causal",
    "thus":           "causal",
    "hence":          "causal",
    "consequently":   "causal",
    "as a result":    "causal",
    "because":        "causal",
    "since":          "causal",
    "for this reason":"causal",
    "it follows that":"causal",
    "accordingly":    "causal",
    "so":             "causal",
    # Temporal
    "first":          "temporal",
    "second":         "temporal",
    "third":          "temporal",
    "finally":        "temporal",
    "subsequently":   "temporal",
    "then":           "temporal",
    "next":           "temporal",
    "initially":      "temporal",
    "ultimately":     "temporal",
    "previously":     "temporal",
    "afterward":      "temporal",
    "first of all":   "temporal",
    "to begin":       "temporal",
    "in conclusion":  "temporal",
    "in summary":     "temporal",
    "to summarize":   "temporal",
}

TRANSITION_PHRASES = set(DISCOURSE_MARKERS.keys()) | {
    "that is", "in other words", "for example", "for instance",
    "in particular", "specifically", "to illustrate", "namely",
    "indeed", "in fact", "above all", "of course", "clearly",
    "evidently", "notably", "importantly", "significantly",
}

HEDGE_WORDS = {
    "perhaps", "maybe", "possibly", "probably", "apparently",
    "seemingly", "presumably", "likely", "unlikely", "arguably",
    "generally", "typically", "usually", "often",
    "sometimes", "tends", "tend", "appear", "appears", "seem",
    "seems", "suggest", "suggests", "indicate", "indicates",
    "might", "may", "could", "would", "somewhat", "rather",
    "fairly", "relatively", "approximately", "around", "about",
    "partially", "largely", "broadly", "essentially", "virtually",
    "almost", "nearly", "to some extent", "to a degree",
    "in some ways", "in many respects", "in a sense",
}

ASSERTION_WORDS = {
    "clearly", "obviously", "certainly", "undoubtedly", "undeniably",
    "necessarily", "inevitably", "definitely", "absolutely", "unquestionably",
    "evidently", "plainly", "manifestly", "demonstrably", "conclusively",
    "decisively", "unmistakably", "indisputably", "incontrovertibly",
    "must", "is clear", "is evident", "it is certain", "without doubt",
    "beyond question", "there is no question", "it is obvious",
}

CLAIM_MARKERS = {
    "therefore", "thus", "hence", "consequently", "it follows",
    "this shows", "this demonstrates", "this means", "this indicates",
    "this suggests", "which means", "which shows", "we can conclude",
    "one can conclude", "this proves", "the evidence shows",
    "the data suggests", "this implies", "i argue", "i contend",
    "i submit", "it is argued", "the argument is",
}

AUTHORITY_MARKERS = {
    "according to", "as argued by", "as noted by", "as stated by",
    "as observed by", "as noted", "as suggested", "in the words of",
    "argues", "contends", "claims", "asserts", "maintains", "suggests",
    "notes", "observes", "states", "writes", "explains", "demonstrates",
    "ibid", "op cit", "et al", "cf.", "see also",
}

PASSIVE_PATTERNS = [
    r"\b(is|are|was|were|be|been|being)\s+(\w+ly\s+)?(\w+ed)\b",
    r"\b(is|are|was|were|be|been|being)\s+(\w+en)\b",
]

THEOLOGICAL_TERMS = {
    # Core doctrines
    "justification", "sanctification", "glorification", "regeneration",
    "atonement", "propitiation", "expiation", "redemption", "reconciliation",
    "salvation", "soteriology", "christology", "pneumatology", "ecclesiology",
    "eschatology", "protology", "anthropology", "hamartiology",
    # Trinity and Christology
    "trinitarian", "trinity", "hypostatic", "kenosis", "incarnation",
    "resurrection", "ascension", "parousia", "christological",
    "perichoresis", "immanent", "economic",
    # Hermeneutics
    "hermeneutics", "hermeneutical", "exegesis", "exegetical",
    "eisegesis", "pericope", "intertextual", "canonical",
    "sola scriptura", "perspicuity",
    # Covenant theology
    "covenant", "covenantal", "federal", "imputation", "imputed",
    "forensic", "declarative", "baptism", "eucharist",
    # Baptist / SBTS specific
    "confessional", "baptist faith", "autonomy", "priesthood",
    "believers", "congregationalism", "cessationism", "continuationism",
    # Scripture integration
    "scripture", "scriptural", "biblical", "hermeneutic", "textual",
    "exegete", "text", "passage", "narrative", "theological", "doctrinal", "apostolic", "prophetic",
    "kerygmatic", "didactic", "parenetic", "doxological",
}

SCRIPTURE_PATTERNS = [
    r"\b[1-3]?\s*[A-Z][a-z]+\s+\d+:\d+",          # Gen 1:1, 1 Cor 13:13
    r"\b[1-3]?\s*[A-Z][a-z]+\s+\d+\b",              # John 3
    r"\(cf\.\s*[A-Z][a-z]+",                         # (cf. Romans
    r"\bcf\.\s+[A-Z][a-z]+",
    r"\bsee\s+[A-Z][a-z]+\s+\d+",
    r"\b(Romans|Corinthians|Galatians|Ephesians|Philippians|"
     r"Colossians|Thessalonians|Timothy|Titus|Hebrews|"
     r"Genesis|Exodus|Deuteronomy|Psalms|Proverbs|Isaiah|Jeremiah|"
     r"Matthew|Mark|Luke|John|Acts|Revelation)\s+\d+",
]

CONFESSIONAL_MARKERS = {
    "the scriptures teach", "scripture teaches", "the bible says",
    "as the text says", "as paul writes", "as john writes",
    "as moses writes", "the text demands", "the passage requires",
    "the word of god", "the holy spirit", "divine inspiration",
    "inerrancy", "infallibility", "authority of scripture",
    "the confession states", "we confess", "as we confess",
    "our confession", "as reformed", "as evangelical",
}


# ══════════════════════════════════════════════════════════════════════════════
# Phase 2 — Adaptive Context Resolver constants
# ══════════════════════════════════════════════════════════════════════════════
#
# Used by `original/context/resolvers.py` to classify submission context
# (language, genre, topic novelty, length regime) before scoring. None of these
# affect Phase 1 static-weight scoring; they are consumed only by the adaptive
# pipeline gated behind CONTEXT_MANIFEST_ENABLED / ADAPTIVE_WEIGHTS_ENABLED.

import math as _math

# Eight target classes for the genre resolver (rule-based fallback in Phase 2;
# trained classifier deferred to a follow-up).
# The abstention outcome for the v2 genre resolver (GENRE_RESOLVER_V2).
# APPENDED to GENRE_LABELS rather than replacing anything: the eight labels
# below are persisted on BaselineSample.genre and used as get_genre_stats
# pooling keys, so changing them would force a data migration. v1 sorted 86%
# of all prose into rule 8's terminal `else` ("correspondence") and reported
# it at a hardcoded 0.5 confidence — measured 2026-08-08 over 356 committed
# documents. See docs/superpowers/specs/2026-08-08-genre-resolution-design.md.
GENRE_UNKNOWN = "unknown"

# Added 2026-08-08. Replaces `creative_fiction` + `personal_essay` in the v2
# class set: those two were separated by TRUTH CLAIM ("fiction does not assert
# that its events happened"), which is a fact about the world rather than a
# property of the prose, and was measured to be unlearnable — every hold-out
# error was first-person fiction (Huckleberry Finn) predicted as autobiography,
# which stylometrically it is. The replacement axis is mode of discourse:
# event-and-speech versus claim-and-warrant. ADDITIVE — both old labels stay
# below so stored sample.genre values and pooling keys remain valid; v2 simply
# never emits them. See validation/genre_2026-08/CODEBOOK.md.
GENRE_NARRATIVE_PROSE = "narrative_prose"

# Minimum calibrated probability required to CLAIM a genre; below it the
# resolver abstains. Applied only to the Stage 2 model's output — Stage 1's
# rule hits carry a placeholder confidence and are deliberately NOT
# thresholded, since comparing a placeholder against a real threshold would
# abstain on everything.
GENRE_CONFIDENCE_MIN = 0.55

GENRE_LABELS = [
    "academic_exegesis",
    "scholarly_essay",
    "sermon",
    "personal_essay",
    "creative_fiction",
    "correspondence",
    "blog_post",
    "structured_template",
    GENRE_NARRATIVE_PROSE,
    GENRE_UNKNOWN,
]

# Genre family mapping — used by Phase 4 baseline-cluster matching to award
# partial credit when a submission and a baseline sample share a family but
# not the exact label. Values must be a small fixed set (≤ 5 families).
GENRE_FAMILIES: dict[str, str] = {
    "academic_exegesis":   "academic",
    "scholarly_essay":     "academic",
    "sermon":              "homiletic",
    "personal_essay":      "personal",
    "creative_fiction":    "creative",
    "correspondence":      "personal",
    "blog_post":           "personal",
    "structured_template": "structured",
    # Narrative of events, invented or recounted — the family the two
    # superseded labels ("creative" and "personal") were split across.
    GENRE_NARRATIVE_PROSE: "narrative",
}

# Code-switching threshold: if any non-primary language window-proportion
# exceeds this, the language resolver flags the submission as code-switched.
LANGUAGE_CODE_SWITCH_THRESHOLD = 0.05

# Token-count buckets for the length resolver. Inclusive low, exclusive high.
LENGTH_REGIME_BOUNDS: dict[str, tuple[int, float]] = {
    "micro":    (0, 150),
    "short":    (150, 500),
    "standard": (500, 3000),
    "long":     (3000, _math.inf),
}

# Topic novelty buckets — TF-IDF cosine distance from baseline centroid.
# < low → "low" novelty; between low and medium → "medium"; ≥ medium → "high".
TOPIC_NOVELTY_BOUNDS: dict[str, float] = {
    "low":    0.25,
    "medium": 0.50,
}

# ── Topic-adaptive variance inflation (2026-08 topic-invariance work) ────────
#
# When TOPIC_VARIANCE_INFLATION is on, scoring widens each feature's expected
# band in proportion to how far the submission's topic sits from the student's
# baseline centroid:
#
#     d_eff     = clip((d - TOPIC_NOVELTY_BOUNDS["low"]) / 0.75, 0, 1)
#     sigma_eff = sigma * (1 + TOPIC_INFLATE_GAIN * d_eff * s_norm)
#
# Rationale: baseline_std is estimated from a student's own samples, which
# usually span a narrow topic range, so it encodes "how much this student
# varies WHILE WRITING ABOUT THE SAME THINGS". On a new topic the topic-
# sensitive features move by more than that sigma predicts and rms_z inflates
# — measured at mean AUC 0.387 (INVERTED) on the leave-one-genre-out Lewis
# corpus, validation/genre_crossgenre_2026-08/. See
# docs/superpowers/specs/2026-08-06-topic-invariant-scoring-design.md.
#
# TOPIC_SENSITIVITY holds ALREADY-NORMALISED per-feature sensitivities: the
# derivation script divides by the median over MEASURABLE features and clips
# to [0, TOPIC_INFLATE_MAX] before writing them here, so the scoring path
# needs no measurability lookup (original/ must never import validation/).
# A code absent from this table reads as 1.0 — median sensitivity.
#
# SHIPPED EMPTY ON PURPOSE. An empty table means uniform sensitivity, i.e.
# "inflate every feature in proportion to topic distance". The per-feature
# table is a follow-on: cross_work_manifest.json currently carries 2 works
# per author, and a drift estimate over two work-means cannot support a
# 109-dimensional constant.
TOPIC_SENSITIVITY: dict[str, float] = {}

# Multiplier strength at maximum REACHABLE topic distance. resolve_topic's
# TF-IDF vectors are non-negative, so cosine_sim in [0, 1] and therefore
# baseline_distance = (1 - cosine_sim) / 2 in [0, 0.5] — d = 1.0 is
# unreachable in production; do not calibrate or sweep against it.
# At the real ceiling d = 0.5: d_eff = (0.5 - TOPIC_NOVELTY_BOUNDS["low"])
# / 0.75 = (0.5 - 0.25) / 0.75 = 0.333, so with the shipped GAIN = 1.0 the
# actual maximum multiplier for a median-sensitivity feature is
# 1 + 1.0 * 0.333 = 1.333x, not the 2x that d = 1.0 would have implied.
# Swept on the derivation corpus and fixed before the hold-out is touched —
# see the spec's hold-out discipline.
TOPIC_INFLATE_GAIN: float = 1.0

# Ceiling on normalised per-feature sensitivity, so no single feature can be
# inflated into irrelevance. Unused while TOPIC_SENSITIVITY is empty (every
# lookup returns 1.0), but the clip lives in the derivation script that
# populates the table.
TOPIC_INFLATE_MAX: float = 3.0

# Genre rule-based-fallback thresholds (per 100 words / per sentence as
# appropriate). Tunable here so threshold sweeps don't require code changes.
# NOTE: Phase 2 ships rule-based only; sklearn classifier deferred to a
# follow-up after manifests are collected in production.
GENRE_RULES = {
    # Citation density (citations per 100 prose words) above this → academic
    "academic_citation_density_min":  1.5,
    # First-person ratio (first-person pronouns / all personal pronouns —
    # value in [0, 1] from features.tier3.first_person_ratio). Above this → sermon/personal.
    "sermon_first_person_min":        0.30,
    # Imperative density (per 100 words; from features.tier3.imperative_density).
    # Above this → sermon.
    "sermon_imperative_min":          3.0,
    # Mean sentence length: below this → blog/correspondence; above → academic
    "academic_msl_min":               20.0,
    "informal_msl_max":               14.0,
    # Tier 16 signal-verb total above this contributes to scholarly_essay
    "scholarly_signal_verb_min":      3,
}

# Composition-mode thresholds — feed `resolve_composition_mode`.
COMPOSITION_RULES = {
    # Below these per-100-word rates the text looks Grammarly-cleaned.
    "tool_cleaned_comma_splice_max":      0.001,
    "tool_cleaned_punct_error_max":       0.002,
    # Sentence-length variance below this percentile → "structured"
    "structured_msl_variance_pctile":     0.05,
}

# Citation-format detection cues — used by `resolve_citations` to classify
# the dominant style. Order matters: first match wins.
CITATION_FORMAT_CUES: dict[str, list] = {
    # (Smith, 2020, p. 45) / (Smith and Jones, 2020) — Chicago author-date / Turabian
    "chicago":  [r"\([A-Z][a-z]+,?\s+\d{4}(?:,\s*pp?\.\s*\d)", r"\bibid\.", r"\bop\.\s*cit\."],
    # Footnote superscripts → Chicago notes-bibliography or Turabian
    "turabian": [r"(?<=[a-z.,;:])\^?\d{1,3}(?=[\s,.])"],
    # (Author 2020) without comma → MLA-ish parenthetical
    "mla":      [r"\([A-Z][a-z]+\s+\d{4}\)"],
    # (Author, 2020) with comma but no page → APA
    "apa":      [r"\([A-Z][a-z]+,\s+\d{4}\)"],
}
