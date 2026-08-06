// feature-names.js — GENERATED display-only copy of the feature registry.
//
// Sources: original/constants.py (ALL_FEATURE_CODES order, FEATURE_TIER,
// FEATURE_NAMES) + original/explainer.py (FEATURE_PLAIN_NAMES). Never edit
// constants.py to suit this file. Regenerate after backend feature changes:
//   .venv/bin/python <the snippet in git history for this file> > demo/app/feature-names.js
// Tier display names were moved here from Analyze.jsx (single shared copy).

// Ordered feature codes — index i matches baseline_vector/feature_vector keys.
export const CODES = [ "type_token_ratio", "hapax_legomena_rate", "mean_sentence_length", "sentence_length_variance", "function_word_ratio", "passive_voice_ratio", "modal_verb_ratio", "stop_word_ratio", "avg_word_length", "discourse_marker_density", "additive_ratio", "adversative_ratio", "causal_ratio", "temporal_ratio", "thematic_progression_score", "pronoun_reference_density", "lexical_chain_density", "paragraph_topic_position", "avg_paragraph_length", "sentence_opener_variety", "cohesion_device_ratio", "transition_density", "epistemic_certainty_ratio", "hedging_density", "assertion_density", "source_integration_style", "counter_argument_ratio", "claim_density", "question_ratio", "imperative_density", "first_person_ratio", "appeal_to_authority_density", "conclusion_strategy_score", "theological_register_score", "char_trigram_entropy", "punctuation_diversity", "comma_rate", "semicolon_colon_rate", "parenthetical_rate", "dash_rate", "quote_rate", "pos_bigram_entropy", "pos_trigram_entropy", "noun_verb_ratio", "adjective_rate", "adverb_rate", "subordination_ratio", "clause_depth_mean", "contraction_rate", "sentence_initial_conjunction_rate", "that_which_ratio", "citation_style_consistency", "list_marker_preference", "abbreviation_tendency", "burstiness", "perplexity_proxy", "repetition_gap_entropy", "transition_predictability", "vocabulary_introduction_rate", "filler_hedge_cluster_rate", "stress_entropy_unigram", "stress_entropy_bigram", "clausulae_consistency", "breath_group_variance", "structural_centrist_penalty", "argument_sequence_likelihood", "semantic_field_dispersion", "semantic_centroid_proximity", "error_kl_divergence", "stumble_rate_consistency", "punctuation_error_ratio", "catastrophe_index", "clausula_type_consistency", "breath_group_regularity", "vowel_sonority_ratio", "arc_resolution_score", "metric_flatness_score", "clausula_shape_preference", "error_topology_consistency", "article_omission_rate", "pronoun_ambiguity_rate", "comma_splice_rate", "semantic_field_concentration", "polysyndeton_ratio", "chiasmus_rate", "latinate_ratio", "nominalization_density", "signal_verb_entropy", "signal_verb_assertiveness", "source_loyalty_index", "block_quote_rate", "citation_density_cv", "ibid_usage_rate", "citation_position_pref", "paraphrase_density", "typing_speed_cv", "burst_ratio", "deletion_rate", "pause_density", "paste_event_rate", "revision_depth", "char_trigram_profile_divergence", "function_word_profile_divergence" ];

// code -> { name: short label, plain: professor-facing phrase, tier: 0-17 }
export const FEATURES = {
  "type_token_ratio": {"name": "Type-Token Ratio", "plain": "vocabulary range", "tier": 1},
  "hapax_legomena_rate": {"name": "Hapax Legomena Rate", "plain": "unique word usage", "tier": 1},
  "mean_sentence_length": {"name": "Mean Sentence Length", "plain": "typical sentence length", "tier": 1},
  "sentence_length_variance": {"name": "Sentence Length Variance", "plain": "variation in sentence length", "tier": 1},
  "function_word_ratio": {"name": "Function Word Ratio", "plain": "function word frequency", "tier": 1},
  "passive_voice_ratio": {"name": "Passive Voice Ratio", "plain": "use of passive voice", "tier": 1},
  "modal_verb_ratio": {"name": "Modal Verb Ratio", "plain": "use of modal verbs", "tier": 1},
  "stop_word_ratio": {"name": "Stop Word Ratio", "plain": "stop word frequency", "tier": 1},
  "avg_word_length": {"name": "Avg Word Length", "plain": "word complexity", "tier": 1},
  "discourse_marker_density": {"name": "Discourse Marker Density", "plain": "use of transition words", "tier": 2},
  "additive_ratio": {"name": "Additive Ratio", "plain": "additive connectors (and, also)", "tier": 2},
  "adversative_ratio": {"name": "Adversative Ratio", "plain": "adversative connectors (but, however)", "tier": 2},
  "causal_ratio": {"name": "Causal Ratio", "plain": "causal connectors (because, so)", "tier": 2},
  "temporal_ratio": {"name": "Temporal Ratio", "plain": "temporal connectors (then, when)", "tier": 2},
  "thematic_progression_score": {"name": "Thematic Progression", "plain": "topic progression patterns", "tier": 2},
  "pronoun_reference_density": {"name": "Pronoun Ref. Density", "plain": "pronoun usage patterns", "tier": 2},
  "lexical_chain_density": {"name": "Lexical Chain Density", "plain": "lexical chains and cohesion", "tier": 2},
  "paragraph_topic_position": {"name": "Paragraph Topic Pos.", "plain": "topic position in paragraphs", "tier": 2},
  "avg_paragraph_length": {"name": "Avg Paragraph Length", "plain": "average paragraph length", "tier": 2},
  "sentence_opener_variety": {"name": "Sentence Opener Variety", "plain": "variety in sentence starters", "tier": 2},
  "cohesion_device_ratio": {"name": "Cohesion Device Ratio", "plain": "cohesive devices", "tier": 2},
  "transition_density": {"name": "Transition Density", "plain": "transition word frequency", "tier": 2},
  "epistemic_certainty_ratio": {"name": "Epistemic Certainty", "plain": "confident assertion style", "tier": 3},
  "hedging_density": {"name": "Hedging Density", "plain": "use of hedging words", "tier": 3},
  "assertion_density": {"name": "Assertion Density", "plain": "frequency of assertions", "tier": 3},
  "source_integration_style": {"name": "Source Integration Style", "plain": "integration of sources", "tier": 3},
  "counter_argument_ratio": {"name": "Counter-Argument Ratio", "plain": "counter-argument engagement", "tier": 3},
  "claim_density": {"name": "Claim Density", "plain": "density of claims", "tier": 3},
  "question_ratio": {"name": "Question Ratio", "plain": "use of rhetorical questions", "tier": 3},
  "imperative_density": {"name": "Imperative Density", "plain": "imperative mood usage", "tier": 3},
  "first_person_ratio": {"name": "First-Person Ratio", "plain": "first-person usage", "tier": 3},
  "appeal_to_authority_density": {"name": "Authority Appeal Density", "plain": "appeals to authority", "tier": 3},
  "conclusion_strategy_score": {"name": "Conclusion Strategy", "plain": "conclusion strategy", "tier": 3},
  "theological_register_score": {"name": "Theological Register", "plain": "theological register", "tier": 3},
  "char_trigram_entropy": {"name": "Char Trigram Entropy", "plain": "character-level writing patterns", "tier": 4},
  "punctuation_diversity": {"name": "Punctuation Diversity", "plain": "punctuation variety", "tier": 4},
  "comma_rate": {"name": "Comma Rate", "plain": "comma usage", "tier": 4},
  "semicolon_colon_rate": {"name": "Semicolon+Colon Rate", "plain": "semicolon and colon usage", "tier": 4},
  "parenthetical_rate": {"name": "Parenthetical Rate", "plain": "parenthetical usage", "tier": 4},
  "dash_rate": {"name": "Dash Rate", "plain": "dash usage", "tier": 4},
  "quote_rate": {"name": "Quotation Rate", "plain": "quotation frequency", "tier": 4},
  "pos_bigram_entropy": {"name": "POS Bigram Entropy", "plain": "part-of-speech patterns", "tier": 5},
  "pos_trigram_entropy": {"name": "POS Trigram Entropy", "plain": "three-word grammatical patterns", "tier": 5},
  "noun_verb_ratio": {"name": "Noun-Verb Ratio", "plain": "noun-to-verb balance", "tier": 5},
  "adjective_rate": {"name": "Adjective Rate", "plain": "adjective frequency", "tier": 5},
  "adverb_rate": {"name": "Adverb Rate", "plain": "adverb frequency", "tier": 5},
  "subordination_ratio": {"name": "Subordination Ratio", "plain": "subordination patterns", "tier": 5},
  "clause_depth_mean": {"name": "Mean Clause Depth", "plain": "clause depth complexity", "tier": 5},
  "contraction_rate": {"name": "Contraction Rate", "plain": "use of contractions (don't, can't, it's)", "tier": 6},
  "sentence_initial_conjunction_rate": {"name": "Sent-Initial Conj Rate", "plain": "sentence-initial conjunctions", "tier": 6},
  "that_which_ratio": {"name": "That/Which Ratio", "plain": "that vs. which usage", "tier": 6},
  "citation_style_consistency": {"name": "Citation Consistency", "plain": "consistency of citations", "tier": 6},
  "list_marker_preference": {"name": "List Marker Pref.", "plain": "list marker preferences", "tier": 6},
  "abbreviation_tendency": {"name": "Abbreviation Tendency", "plain": "abbreviation usage", "tier": 6},
  "burstiness": {"name": "Burstiness", "plain": "vocabulary bursts", "tier": 7},
  "perplexity_proxy": {"name": "Perplexity Proxy", "plain": "text predictability", "tier": 7},
  "repetition_gap_entropy": {"name": "Repetition Gap Entropy", "plain": "repetition patterns", "tier": 7},
  "transition_predictability": {"name": "Transition Predictability", "plain": "transition predictability", "tier": 7},
  "vocabulary_introduction_rate": {"name": "Vocab Introduction Rate", "plain": "new vocabulary introduction", "tier": 7},
  "filler_hedge_cluster_rate": {"name": "Hedge Clustering", "plain": "pattern of hesitation markers", "tier": 7},
  "stress_entropy_unigram": {"name": "Stress Entropy (Unigram)", "plain": "syllabic stress patterns", "tier": 8},
  "stress_entropy_bigram": {"name": "Stress Entropy (Bigram)", "plain": "consecutive stress patterns", "tier": 8},
  "clausulae_consistency": {"name": "Clausulae Consistency", "plain": "sentence-ending rhythm patterns", "tier": 8},
  "breath_group_variance": {"name": "Breath-Group Variance", "plain": "breath group patterns", "tier": 8},
  "structural_centrist_penalty": {"name": "Structural Centrist Penalty", "plain": "argument structure diversity", "tier": 9},
  "argument_sequence_likelihood": {"name": "Argument Sequence Likelihood", "plain": "argument sequence patterns", "tier": 9},
  "semantic_field_dispersion": {"name": "Semantic Field Dispersion", "plain": "semantic field diversity", "tier": 10},
  "semantic_centroid_proximity": {"name": "Semantic Centroid Proximity", "plain": "semantic consistency", "tier": 10},
  "error_kl_divergence": {"name": "Error Profile KL-Divergence", "plain": "error fingerprint (spelling/grammar mistakes)", "tier": 11},
  "stumble_rate_consistency": {"name": "Stumble-Rate Consistency", "plain": "pattern of errors and stumbles", "tier": 11},
  "punctuation_error_ratio": {"name": "Punctuation-Error Ratio", "plain": "punctuation error patterns", "tier": 11},
  "catastrophe_index": {"name": "Catastrophe Index (\u03ba)", "plain": "narrative tension arc structure", "tier": 12},
  "clausula_type_consistency": {"name": "Clausula Type Consistency", "plain": "sentence-ending patterns", "tier": 13},
  "breath_group_regularity": {"name": "Breath-Group Regularity", "plain": "breathing patterns", "tier": 13},
  "vowel_sonority_ratio": {"name": "Vowel Sonority Ratio", "plain": "vowel sonority patterns", "tier": 13},
  "arc_resolution_score": {"name": "Arc Resolution Score", "plain": "sentence-arc resolution", "tier": 13},
  "metric_flatness_score": {"name": "Metric Flatness (AI Signal)", "plain": "rhythmic flatness (AI marker)", "tier": 13},
  "clausula_shape_preference": {"name": "Clausula Shape Preference", "plain": "sentence-ending shape preference", "tier": 13},
  "error_topology_consistency": {"name": "Error Topology Consistency", "plain": "error placement patterns", "tier": 14},
  "article_omission_rate": {"name": "Article Omission Rate", "plain": "article omission patterns", "tier": 14},
  "pronoun_ambiguity_rate": {"name": "Pronoun Ambiguity Rate", "plain": "pronoun ambiguity", "tier": 14},
  "comma_splice_rate": {"name": "Comma Splice Rate", "plain": "comma splice frequency", "tier": 14},
  "semantic_field_concentration": {"name": "Semantic Field Concentration", "plain": "semantic field concentration", "tier": 15},
  "polysyndeton_ratio": {"name": "Polysyndeton Ratio", "plain": "polysyndeton usage", "tier": 15},
  "chiasmus_rate": {"name": "Chiasmus/Antithesis Rate", "plain": "chiasmus (A-B-B-A) patterns", "tier": 15},
  "latinate_ratio": {"name": "Latinate Vocabulary Ratio", "plain": "Latinate vocabulary usage", "tier": 15},
  "nominalization_density": {"name": "Nominalization Density", "plain": "nominalization density", "tier": 15},
  "signal_verb_entropy": {"name": "Signal Verb Entropy", "plain": "signal verb variety", "tier": 16},
  "signal_verb_assertiveness": {"name": "Signal Verb Assertiveness", "plain": "signal verb tone", "tier": 16},
  "source_loyalty_index": {"name": "Source Loyalty Index", "plain": "source loyalty patterns", "tier": 16},
  "block_quote_rate": {"name": "Block-Quote Rate", "plain": "block quotation usage", "tier": 16},
  "citation_density_cv": {"name": "Citation Density CV", "plain": "citation clustering", "tier": 16},
  "ibid_usage_rate": {"name": "Ibid. Usage Rate", "plain": "ibid. usage patterns", "tier": 16},
  "citation_position_pref": {"name": "Citation Position Preference", "plain": "citation positioning", "tier": 16},
  "paraphrase_density": {"name": "Paraphrase Density", "plain": "paraphrase attribution", "tier": 16},
  "typing_speed_cv": {"name": "Typing Rhythm CV", "plain": "typing rhythm consistency", "tier": 17},
  "burst_ratio": {"name": "Burst Typing Ratio", "plain": "rapid typing patterns", "tier": 17},
  "deletion_rate": {"name": "Deletion Rate", "plain": "deletion and revision frequency", "tier": 17},
  "pause_density": {"name": "Pause Density", "plain": "pause and thinking patterns", "tier": 17},
  "paste_event_rate": {"name": "Paste Event Rate", "plain": "paste/paste-over events", "tier": 17},
  "revision_depth": {"name": "Revision Depth", "plain": "depth of revisions", "tier": 17},
  "char_trigram_profile_divergence": {"name": "Char Trigram Divergence", "plain": "character-level divergence", "tier": 0},
  "function_word_profile_divergence": {"name": "Func Word Divergence", "plain": "function word divergence", "tier": 0},
};

// tier number -> display name (tier 0 = cross-profile comparison meta-features)
export const TIER_META = {
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
  "17": "Behavioral Biometrics"
};

// Group a 103-key vector { code: value } into ordered tiers:
// [{ tier, name, features: [{ code, name, plain, value }] }]
export function groupByTier(vec) {
  const groups = new Map();
  for (const code of CODES) {
    const meta = FEATURES[code];
    if (!meta) continue;
    if (!groups.has(meta.tier)) {
      groups.set(meta.tier, { tier: meta.tier, name: TIER_META[String(meta.tier)] || `Tier ${meta.tier}`, features: [] });
    }
    groups.get(meta.tier).features.push({ code, name: meta.name, plain: meta.plain, value: vec ? vec[code] : undefined });
  }
  // Tiers 1..17 in order, comparison meta (tier 0) last.
  return [...groups.values()].sort((a, b) => (a.tier === 0 ? 99 : a.tier) - (b.tier === 0 ? 99 : b.tier));
}

// Mean value per tier for a vector — the radar/heatmap aggregation.
export function tierAverages(vec) {
  return groupByTier(vec).map((g) => {
    const vals = g.features.map((f) => f.value).filter((v) => typeof v === 'number');
    return { tier: g.tier, name: g.name, avg: vals.length ? vals.reduce((a, b) => a + b, 0) / vals.length : null, count: g.features.length };
  });
}
