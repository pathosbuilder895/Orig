// GENERATED FILE — DO NOT EDIT.
// Sources: original/constants.py + original/explainer.py
// Regenerate: .venv/bin/python demo/prototypes/generate-feature-registry.py

const FEATURE_ROWS = Object.freeze([
  [
    "type_token_ratio",
    "Type-Token Ratio",
    "vocabulary range",
    1,
    "document"
  ],
  [
    "hapax_legomena_rate",
    "Hapax Legomena Rate",
    "words used only once",
    1,
    "token"
  ],
  [
    "mean_sentence_length",
    "Mean Sentence Length",
    "typical sentence length",
    1,
    "sentence"
  ],
  [
    "sentence_length_variance",
    "Sentence Length Variance",
    "variation in sentence length",
    1,
    "sentence"
  ],
  [
    "function_word_ratio",
    "Function Word Ratio",
    "small everyday words (the, of)",
    1,
    "token"
  ],
  [
    "passive_voice_ratio",
    "Passive Voice Ratio",
    "use of passive voice",
    1,
    "sentence"
  ],
  [
    "modal_verb_ratio",
    "Modal Verb Ratio",
    "use of might, could, must",
    1,
    "token"
  ],
  [
    "stop_word_ratio",
    "Stop Word Ratio",
    "very common words (a, is, at)",
    1,
    "token"
  ],
  [
    "avg_word_length",
    "Avg Word Length",
    "average word length",
    1,
    "document"
  ],
  [
    "discourse_marker_density",
    "Discourse Marker Density",
    "linking words (therefore, also)",
    2,
    "token"
  ],
  [
    "additive_ratio",
    "Additive Ratio",
    "add-on words (also, moreover)",
    2,
    "token"
  ],
  [
    "adversative_ratio",
    "Adversative Ratio",
    "contrast words (but, however)",
    2,
    "token"
  ],
  [
    "causal_ratio",
    "Causal Ratio",
    "cause-and-effect words (because, so)",
    2,
    "token"
  ],
  [
    "temporal_ratio",
    "Temporal Ratio",
    "sequence words (first, then)",
    2,
    "token"
  ],
  [
    "thematic_progression_score",
    "Thematic Progression",
    "building on the previous sentence",
    2,
    "paragraph"
  ],
  [
    "pronoun_reference_density",
    "Pronoun Ref. Density",
    "pronouns like it and this",
    2,
    "token"
  ],
  [
    "lexical_chain_density",
    "Lexical Chain Density",
    "word overlap between sentences",
    2,
    "token"
  ],
  [
    "paragraph_topic_position",
    "Paragraph Topic Pos.",
    "content-heavy paragraph openings",
    2,
    "paragraph"
  ],
  [
    "avg_paragraph_length",
    "Avg Paragraph Length",
    "average paragraph length",
    2,
    "paragraph"
  ],
  [
    "sentence_opener_variety",
    "Sentence Opener Variety",
    "variety in sentence starters",
    2,
    "sentence"
  ],
  [
    "cohesion_device_ratio",
    "Cohesion Device Ratio",
    "words tying the text together",
    2,
    "token"
  ],
  [
    "transition_density",
    "Transition Density",
    "transition phrases (for example, in fact)",
    2,
    "token"
  ],
  [
    "epistemic_certainty_ratio",
    "Epistemic Certainty",
    "certainty versus hedging",
    3,
    "token"
  ],
  [
    "hedging_density",
    "Hedging Density",
    "use of hedging words",
    3,
    "token"
  ],
  [
    "assertion_density",
    "Assertion Density",
    "certainty words (clearly, obviously)",
    3,
    "sentence"
  ],
  [
    "source_integration_style",
    "Source Integration Style",
    "commenting on sources",
    3,
    "sentence"
  ],
  [
    "counter_argument_ratio",
    "Counter-Argument Ratio",
    "sentences that concede or contrast",
    3,
    "sentence"
  ],
  [
    "claim_density",
    "Claim Density",
    "claim words (therefore, this shows)",
    3,
    "sentence"
  ],
  [
    "question_ratio",
    "Question Ratio",
    "use of questions",
    3,
    "sentence"
  ],
  [
    "imperative_density",
    "Imperative Density",
    "direct commands (consider, note)",
    3,
    "sentence"
  ],
  [
    "first_person_ratio",
    "First-Person Ratio",
    "share of I and we",
    3,
    "token"
  ],
  [
    "appeal_to_authority_density",
    "Authority Appeal Density",
    "appeals to authority",
    3,
    "sentence"
  ],
  [
    "conclusion_strategy_score",
    "Conclusion Strategy",
    "how the conclusion is built",
    3,
    "paragraph"
  ],
  [
    "theological_register_score",
    "Theological Register",
    "theological vocabulary",
    3,
    "token"
  ],
  [
    "char_trigram_entropy",
    "Char Trigram Entropy",
    "variety of letter combinations",
    4,
    "character"
  ],
  [
    "punctuation_diversity",
    "Punctuation Diversity",
    "punctuation variety",
    4,
    "character"
  ],
  [
    "comma_rate",
    "Comma Rate",
    "comma usage",
    4,
    "character"
  ],
  [
    "semicolon_colon_rate",
    "Semicolon+Colon Rate",
    "semicolon and colon usage",
    4,
    "character"
  ],
  [
    "parenthetical_rate",
    "Parenthetical Rate",
    "use of parentheses",
    4,
    "character"
  ],
  [
    "dash_rate",
    "Dash Rate",
    "use of dashes",
    4,
    "character"
  ],
  [
    "quote_rate",
    "Quotation Rate",
    "use of quotation marks",
    4,
    "character"
  ],
  [
    "pos_bigram_entropy",
    "POS Bigram Entropy",
    "variety of grammar patterns",
    5,
    "sentence"
  ],
  [
    "pos_trigram_entropy",
    "POS Trigram Entropy",
    "variety of longer grammar patterns",
    5,
    "sentence"
  ],
  [
    "noun_verb_ratio",
    "Noun-Verb Ratio",
    "noun-to-verb balance",
    5,
    "token"
  ],
  [
    "adjective_rate",
    "Adjective Rate",
    "adjective frequency",
    5,
    "token"
  ],
  [
    "adverb_rate",
    "Adverb Rate",
    "adverb frequency",
    5,
    "token"
  ],
  [
    "subordination_ratio",
    "Subordination Ratio",
    "subordinate clauses per sentence",
    5,
    "sentence"
  ],
  [
    "clause_depth_mean",
    "Mean Clause Depth",
    "depth of sentence structure",
    5,
    "sentence"
  ],
  [
    "contraction_rate",
    "Contraction Rate",
    "use of contractions (don't, it's)",
    6,
    "token"
  ],
  [
    "sentence_initial_conjunction_rate",
    "Sent-Initial Conj Rate",
    "sentences opening with and/but",
    6,
    "sentence"
  ],
  [
    "that_which_ratio",
    "That/Which Ratio",
    "that vs. which usage",
    6,
    "token"
  ],
  [
    "citation_style_consistency",
    "Citation Consistency",
    "mix of citation formats",
    6,
    "document"
  ],
  [
    "list_marker_preference",
    "List Marker Pref.",
    "list style (numbers, bullets)",
    6,
    "token"
  ],
  [
    "abbreviation_tendency",
    "Abbreviation Tendency",
    "abbreviation usage",
    6,
    "token"
  ],
  [
    "burstiness",
    "Burstiness",
    "mix of short and long sentences",
    7,
    "document"
  ],
  [
    "perplexity_proxy",
    "Perplexity Proxy",
    "rarity of word choices",
    7,
    "document"
  ],
  [
    "repetition_gap_entropy",
    "Repetition Gap Entropy",
    "spacing of repeated words",
    7,
    "document"
  ],
  [
    "transition_predictability",
    "Transition Predictability",
    "word overlap between paragraphs",
    7,
    "paragraph"
  ],
  [
    "vocabulary_introduction_rate",
    "Vocab Introduction Rate",
    "how early new words appear",
    7,
    "paragraph"
  ],
  [
    "filler_hedge_cluster_rate",
    "Hedge Clustering",
    "bunching of hedge words",
    7,
    "token"
  ],
  [
    "stress_entropy_unigram",
    "Stress Entropy (Unigram)",
    "balance of stressed syllables",
    8,
    "sentence"
  ],
  [
    "stress_entropy_bigram",
    "Stress Entropy (Bigram)",
    "variety in syllable rhythm",
    8,
    "sentence"
  ],
  [
    "clausulae_consistency",
    "Clausulae Consistency",
    "steady final-syllable stress",
    8,
    "sentence"
  ],
  [
    "breath_group_variance",
    "Breath-Group Variance",
    "variation in syllables per sentence",
    8,
    "sentence"
  ],
  [
    "structural_centrist_penalty",
    "Structural Centrist Penalty",
    "repetitive argument steps",
    9,
    "paragraph"
  ],
  [
    "argument_sequence_likelihood",
    "Argument Sequence Likelihood",
    "usual order of argument steps",
    9,
    "paragraph"
  ],
  [
    "semantic_field_dispersion",
    "Semantic Field Dispersion",
    "spread of ideas across sentences",
    10,
    "document"
  ],
  [
    "semantic_centroid_proximity",
    "Semantic Centroid Proximity",
    "closeness to usual topics",
    10,
    "document"
  ],
  [
    "error_kl_divergence",
    "Error Profile KL-Divergence",
    "mix of mistake types",
    11,
    "document"
  ],
  [
    "stumble_rate_consistency",
    "Stumble-Rate Consistency",
    "overall mistake rate",
    11,
    "document"
  ],
  [
    "punctuation_error_ratio",
    "Punctuation-Error Ratio",
    "doubled punctuation marks",
    11,
    "character"
  ],
  [
    "catastrophe_index",
    "Catastrophe Index (κ)",
    "loose ends across paragraphs",
    12,
    "paragraph"
  ],
  [
    "clausula_type_consistency",
    "Clausula Type Consistency",
    "same rhythm at sentence ends",
    13,
    "sentence"
  ],
  [
    "breath_group_regularity",
    "Breath-Group Regularity",
    "even spacing between pauses",
    13,
    "sentence"
  ],
  [
    "vowel_sonority_ratio",
    "Vowel Sonority Ratio",
    "share of long vowel sounds",
    13,
    "sentence"
  ],
  [
    "arc_resolution_score",
    "Arc Resolution Score",
    "shorter sentences toward the end",
    13,
    "paragraph"
  ],
  [
    "metric_flatness_score",
    "Metric Flatness (AI Signal)",
    "rhythm evenness across paragraphs",
    13,
    "paragraph"
  ],
  [
    "clausula_shape_preference",
    "Clausula Shape Preference",
    "light or heavy sentence endings",
    13,
    "sentence"
  ],
  [
    "error_topology_consistency",
    "Error Topology Consistency",
    "where comma splices fall",
    14,
    "sentence"
  ],
  [
    "article_omission_rate",
    "Article Omission Rate",
    "likely missing a, an, the",
    14,
    "sentence"
  ],
  [
    "pronoun_ambiguity_rate",
    "Pronoun Ambiguity Rate",
    "possibly unclear pronouns",
    14,
    "sentence"
  ],
  [
    "comma_splice_rate",
    "Comma Splice Rate",
    "comma splice frequency",
    14,
    "sentence"
  ],
  [
    "semantic_field_concentration",
    "Semantic Field Concentration",
    "how related the main nouns are",
    15,
    "document"
  ],
  [
    "polysyndeton_ratio",
    "Polysyndeton Ratio",
    "and-chains vs. comma lists",
    15,
    "token"
  ],
  [
    "chiasmus_rate",
    "Chiasmus/Antithesis Rate",
    "mirrored sentence patterns (A-B-B-A)",
    15,
    "sentence"
  ],
  [
    "latinate_ratio",
    "Latinate Vocabulary Ratio",
    "words with Latin endings (-ous, -ive)",
    15,
    "token"
  ],
  [
    "nominalization_density",
    "Nominalization Density",
    "abstract nouns (-tion, -ness)",
    15,
    "token"
  ],
  [
    "signal_verb_entropy",
    "Signal Verb Entropy",
    "variety of citing verbs",
    16,
    "token"
  ],
  [
    "signal_verb_assertiveness",
    "Signal Verb Assertiveness",
    "strength of citing verbs",
    16,
    "token"
  ],
  [
    "source_loyalty_index",
    "Source Loyalty Index",
    "returning to the same authors",
    16,
    "document"
  ],
  [
    "block_quote_rate",
    "Block-Quote Rate",
    "use of block quotes",
    16,
    "paragraph"
  ],
  [
    "citation_density_cv",
    "Citation Density CV",
    "bunching of citations",
    16,
    "paragraph"
  ],
  [
    "ibid_usage_rate",
    "Ibid. Usage Rate",
    "use of ibid. and op. cit.",
    16,
    "token"
  ],
  [
    "citation_position_pref",
    "Citation Position Preference",
    "where citations sit in sentences",
    16,
    "sentence"
  ],
  [
    "paraphrase_density",
    "Paraphrase Density",
    "paraphrases credited to sources",
    16,
    "sentence"
  ],
  [
    "typing_speed_cv",
    "Typing Rhythm CV",
    "variation in typing speed",
    17,
    "behavioral"
  ],
  [
    "burst_ratio",
    "Burst Typing Ratio",
    "rapid typing patterns",
    17,
    "behavioral"
  ],
  [
    "deletion_rate",
    "Deletion Rate",
    "deletion and revision frequency",
    17,
    "behavioral"
  ],
  [
    "pause_density",
    "Pause Density",
    "pauses while typing",
    17,
    "behavioral"
  ],
  [
    "paste_event_rate",
    "Paste Event Rate",
    "pasting in text",
    17,
    "behavioral"
  ],
  [
    "revision_depth",
    "Revision Depth",
    "depth of revisions",
    17,
    "behavioral"
  ],
  [
    "sentence_length_dispersion_ratio",
    "Sentence-Length Dispersion",
    "variety in sentence length",
    18,
    "document"
  ],
  [
    "window_feature_variance_ratio",
    "Window Feature Variance",
    "variety across the paper's sections",
    18,
    "document"
  ],
  [
    "function_word_burstiness_ratio",
    "Function-Word Burstiness",
    "unevenness of everyday word usage",
    18,
    "document"
  ],
  [
    "punctuation_dispersion_ratio",
    "Punctuation Dispersion",
    "variety in punctuation habits",
    18,
    "document"
  ],
  [
    "vocab_introduction_flatness",
    "Vocab Introduction Flatness",
    "evenness of new-vocabulary introduction",
    18,
    "document"
  ],
  [
    "clause_depth_variance_ratio",
    "Clause-Depth Variance",
    "variety in sentence complexity",
    18,
    "document"
  ],
  [
    "char_trigram_profile_divergence",
    "Char Trigram Divergence",
    "drift in letter patterns",
    0,
    "document"
  ],
  [
    "function_word_profile_divergence",
    "Func Word Divergence",
    "drift in small everyday words",
    0,
    "document"
  ]
]);

export const LOCALIZATION_KINDS = Object.freeze({
  character: Object.freeze({
    label: 'Exact character marks',
    guidance: 'Highlight only the exact character or short character sequence '
      + 'returned by trusted evidence offsets.',
    supportsInlineHighlight: true
  }),
  token: Object.freeze({
    label: 'Exact words or phrases',
    guidance: 'Highlight exact word or phrase occurrences; explain that the paper-level '
      + 'value aggregates those occurrences.',
    supportsInlineHighlight: true
  }),
  sentence: Object.freeze({
    label: 'Sentence-level evidence',
    guidance: 'Highlight the complete sentence needed to interpret the grammatical, '
      + 'rhetorical, or rhythmic pattern.',
    supportsInlineHighlight: true
  }),
  paragraph: Object.freeze({
    label: 'Paragraph-level evidence',
    guidance: 'Highlight a complete paragraph or adjacent paragraph sequence; do not '
      + 'reduce the pattern to a single word.',
    supportsInlineHighlight: true
  }),
  document: Object.freeze({
    label: 'Whole-document measure',
    guidance: 'Present a document-level summary or distribution. Do not manufacture an '
      + 'inline highlight for this aggregate signal.',
    supportsInlineHighlight: false
  }),
  behavioral: Object.freeze({
    label: 'Live drafting behavior',
    guidance: 'Present a timeline or event range from captured drafting telemetry; this '
      + 'signal is not derivable from uploaded prose.',
    supportsInlineHighlight: false
  })
});

export const CODES = Object.freeze(FEATURE_ROWS.map(([code]) => code));

export const FEATURES = Object.freeze(Object.fromEntries(FEATURE_ROWS.map(
  ([code, name, plain, tier, localizationKind]) => {
    const localization = LOCALIZATION_KINDS[localizationKind];
    return [code, Object.freeze({
      name,
      plain,
      tier,
      localizationKind,
      localizationLabel: localization.label,
      localizationGuidance: localization.guidance,
      supportsInlineHighlight: localization.supportsInlineHighlight
    })];
  }
)));

export const TIER_META = Object.freeze({
  "0": "Comparison",
  "1": "Surface Stylometrics",
  "2": "Discourse Analysis",
  "3": "Rhetorical Register",
  "4": "Char & Punctuation",
  "5": "POS & Syntax",
  "6": "Idiosyncratic Patterns",
  "7": "Voice Authenticity",
  "8": "Prosodic Rhythm",
  "9": "Cognitive Sequencing",
  "10": "Semantic Gravity",
  "11": "Error Ecology",
  "12": "Tension Arc",
  "13": "Prosodic Depth",
  "14": "Error Topology",
  "15": "Lexical Architecture",
  "16": "Citation Fingerprint",
  "17": "Behavioral Biometrics",
  "18": "Uniformity"
});

export const FEATURE_REGISTRY_SOURCE = Object.freeze({
  schemaVersion: 1,
  totalCount: FEATURE_ROWS.length,
  canonicalSources: Object.freeze(['original/constants.py', 'original/explainer.py']),
  generatedBy: 'demo/prototypes/generate-feature-registry.py'
});
