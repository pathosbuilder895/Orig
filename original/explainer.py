"""
explainer.py — Convert Layer7Output scoring results to plain-English explanations.

Transforms quantitative authorship signals into human-readable verdicts
for professors and instructors, emphasizing the "why" behind the score.
"""

from .quantum.scoring import Layer7Output

# ── Feature code → plain English name (comprehensive) ──────────────────────────

FEATURE_PLAIN_NAMES: dict[str, str] = {
    # Tier 1 — Surface stylometry
    "type_token_ratio": "vocabulary range",
    "hapax_legomena_rate": "words used only once",
    "mean_sentence_length": "typical sentence length",
    "sentence_length_variance": "variation in sentence length",
    "function_word_ratio": "small everyday words (the, of)",
    "passive_voice_ratio": "use of passive voice",
    "modal_verb_ratio": "use of might, could, must",
    "stop_word_ratio": "very common words (a, is, at)",
    "avg_word_length": "average word length",
    # Tier 2 — Discourse structure
    "discourse_marker_density": "linking words (therefore, also)",
    "additive_ratio": "add-on words (also, moreover)",
    "adversative_ratio": "contrast words (but, however)",
    "causal_ratio": "cause-and-effect words (because, so)",
    "temporal_ratio": "sequence words (first, then)",
    "thematic_progression_score": "building on the previous sentence",
    "pronoun_reference_density": "pronouns like it and this",
    "lexical_chain_density": "word overlap between sentences",
    "paragraph_topic_position": "content-heavy paragraph openings",
    "avg_paragraph_length": "average paragraph length",
    "sentence_opener_variety": "variety in sentence starters",
    "cohesion_device_ratio": "words tying the text together",
    "transition_density": "transition phrases (for example, in fact)",
    # Tier 3 — Rhetorical & register
    "epistemic_certainty_ratio": "certainty versus hedging",
    "hedging_density": "use of hedging words",
    "assertion_density": "certainty words (clearly, obviously)",
    "source_integration_style": "commenting on sources",
    "counter_argument_ratio": "sentences that concede or contrast",
    "claim_density": "claim words (therefore, this shows)",
    "question_ratio": "use of questions",
    "imperative_density": "direct commands (consider, note)",
    "first_person_ratio": "share of I and we",
    "appeal_to_authority_density": "appeals to authority",
    "conclusion_strategy_score": "how the conclusion is built",
    "theological_register_score": "theological vocabulary",
    # Tier 4 — Character & Punctuation
    "char_trigram_entropy": "variety of letter combinations",
    "punctuation_diversity": "punctuation variety",
    "comma_rate": "comma usage",
    "semicolon_colon_rate": "semicolon and colon usage",
    "parenthetical_rate": "use of parentheses",
    "dash_rate": "use of dashes",
    "quote_rate": "use of quotation marks",
    # Tier 5 — POS & Syntax
    "pos_bigram_entropy": "variety of grammar patterns",
    "pos_trigram_entropy": "variety of longer grammar patterns",
    "noun_verb_ratio": "noun-to-verb balance",
    "adjective_rate": "adjective frequency",
    "adverb_rate": "adverb frequency",
    "subordination_ratio": "subordinate clauses per sentence",
    "clause_depth_mean": "depth of sentence structure",
    # Tier 6 — Idiosyncratic
    "contraction_rate": "use of contractions (don't, it's)",
    "sentence_initial_conjunction_rate": "sentences opening with and/but",
    "that_which_ratio": "that vs. which usage",
    "citation_style_consistency": "mix of citation formats",
    "list_marker_preference": "list style (numbers, bullets)",
    "abbreviation_tendency": "abbreviation usage",
    # Tier 7 — AI Detection
    "burstiness": "mix of short and long sentences",
    "perplexity_proxy": "rarity of word choices",
    "repetition_gap_entropy": "spacing of repeated words",
    "transition_predictability": "word overlap between paragraphs",
    "vocabulary_introduction_rate": "how early new words appear",
    "filler_hedge_cluster_rate": "bunching of hedge words",
    # Tier 8 — Prosodic Rhythm
    "stress_entropy_unigram": "balance of stressed syllables",
    "stress_entropy_bigram": "variety in syllable rhythm",
    "clausulae_consistency": "steady final-syllable stress",
    "breath_group_variance": "variation in syllables per sentence",
    # Tier 9 — Cognitive Sequencing
    "structural_centrist_penalty": "repetitive argument steps",
    "argument_sequence_likelihood": "usual order of argument steps",
    # Tier 10 — Semantic
    "semantic_field_dispersion": "spread of ideas across sentences",
    "semantic_centroid_proximity": "closeness to usual topics",
    # Tier 11 — Error Ecology
    "error_kl_divergence": "mix of mistake types",
    "stumble_rate_consistency": "overall mistake rate",
    "punctuation_error_ratio": "doubled punctuation marks",
    # Tier 12 — Tension Arc
    "catastrophe_index": "loose ends across paragraphs",
    # Tier 13 — Prosodic Depth
    "clausula_type_consistency": "same rhythm at sentence ends",
    "breath_group_regularity": "even spacing between pauses",
    "vowel_sonority_ratio": "share of long vowel sounds",
    "arc_resolution_score": "shorter sentences toward the end",
    "metric_flatness_score": "rhythm evenness across paragraphs",
    "clausula_shape_preference": "light or heavy sentence endings",
    # Tier 14 — Error Topology
    "error_topology_consistency": "where comma splices fall",
    "article_omission_rate": "likely missing a, an, the",
    "pronoun_ambiguity_rate": "possibly unclear pronouns",
    "comma_splice_rate": "comma splice frequency",
    # Tier 15 — Lexical Architecture
    "semantic_field_concentration": "how related the main nouns are",
    "polysyndeton_ratio": "and-chains vs. comma lists",
    "chiasmus_rate": "mirrored sentence patterns (A-B-B-A)",
    "latinate_ratio": "words with Latin endings (-ous, -ive)",
    "nominalization_density": "abstract nouns (-tion, -ness)",
    # Tier 16 — Citation Fingerprint
    "signal_verb_entropy": "variety of citing verbs",
    "signal_verb_assertiveness": "strength of citing verbs",
    "source_loyalty_index": "returning to the same authors",
    "block_quote_rate": "use of block quotes",
    "citation_density_cv": "bunching of citations",
    "ibid_usage_rate": "use of ibid. and op. cit.",
    "citation_position_pref": "where citations sit in sentences",
    "paraphrase_density": "paraphrases credited to sources",
    # Tier 17 — Behavioral Biometrics
    "typing_speed_cv": "variation in typing speed",
    "burst_ratio": "rapid typing patterns",
    "deletion_rate": "deletion and revision frequency",
    "pause_density": "pauses while typing",
    "paste_event_rate": "pasting in text",
    "revision_depth": "depth of revisions",
    # Tier 18 — Uniformity (second moments, read against the student's own spread)
    "sentence_length_dispersion_ratio": "variety in sentence length",
    "window_feature_variance_ratio": "variety across the paper's sections",
    "function_word_burstiness_ratio": "unevenness of everyday word usage",
    "punctuation_dispersion_ratio": "variety in punctuation habits",
    "vocab_introduction_flatness": "evenness of new-vocabulary introduction",
    "clause_depth_variance_ratio": "variety in sentence complexity",
    # Comparison features
    "char_trigram_profile_divergence": "drift in letter patterns",
    "function_word_profile_divergence": "drift in small everyday words",
}


def _delta_intensity(delta: float) -> str:
    """Convert feature delta (submission - baseline) to intensity description."""
    abs_delta = abs(delta)

    if abs_delta > 0.3:
        intensity = "dramatically"
    elif abs_delta > 0.15:
        intensity = "notably"
    elif abs_delta > 0.05:
        intensity = "slightly"
    else:
        intensity = "marginally"

    direction = "higher" if delta > 0 else "lower"
    return f"{intensity} {direction} than usual"


def explain(result: Layer7Output) -> dict:
    """
    Convert a Layer7Output scoring result to a professor-friendly explanation.

    Parameters
    ----------
    result : Layer7Output
        The full quantum scoring result.

    Returns
    -------
    dict
        {
            "verdict": str,           # one plain-English sentence
            "severity": str,          # "clear" | "watch" | "concern" | "serious"
            "confidence_note": str,   # note on reliability
            "top_reasons": list[str], # 2-4 reasons in plain English
            "ghostwriting_signal": bool,
            "summary": str,           # 2-3 sentence paragraph
        }
    """

    # ── 1. Action → verdict + severity mapping ────────────────────────────────

    action_verdicts = {
        "no_action": {
            "verdict": "This submission appears authentic.",
            "severity": "clear",
        },
        "monitor": {
            "verdict": "This submission shows minor variation from the student's baseline.",
            "severity": "watch",
        },
        "schedule_conversation": {
            "verdict": "This submission shows notable differences worth discussing with the student.",
            "severity": "concern",
        },
        "escalate": {
            "verdict": "This submission shows significant authorship concerns requiring review.",
            "severity": "serious",
        },
    }

    action = result.recommendation.action
    verdict_data = action_verdicts.get(
        action,
        {
            "verdict": "Assessment inconclusive.",
            "severity": "watch",
        },
    )
    verdict = verdict_data["verdict"]
    severity = verdict_data["severity"]

    # ── 2. Top reasons from destructive features ──────────────────────────────

    top_reasons: list[str] = []

    # Sort destructive features by absolute delta, take top 3
    destructive = sorted(
        result.interference.destructive_features,
        key=lambda f: abs(f.delta),
        reverse=True,
    )[:3]

    for feature in destructive:
        plain_name = FEATURE_PLAIN_NAMES.get(
            feature.code,
            feature.name.lower(),
        )
        intensity = _delta_intensity(feature.delta)
        reason = f"{plain_name} is {intensity}"
        top_reasons.append(reason)

    # If no destructive features, add score-based reason
    if not top_reasons:
        score = result.authorship.deviation_score
        if score < 0.4:
            top_reasons.append("deviation score is in the authentic range")
        elif score < 0.55:
            top_reasons.append("deviation score shows minor variation")
        elif score < 0.75:
            top_reasons.append("deviation score shows notable deviation")
        else:
            top_reasons.append("deviation score indicates significant deviation")

    # Corpus-level AI-likelihood (second scoring mode, report-only): when the
    # band is elevated or strong, name the top indicator in plain language.
    # Never touches verdict/severity — those stay per-student identity signals.
    ai_like = getattr(result, "ai_likelihood", None)
    if ai_like is not None and getattr(ai_like, "band", "low") in ("elevated", "strong"):
        indicators = getattr(ai_like, "top_indicators", []) or []
        if indicators:
            lead = indicators[0]
            top_reasons.append(
                f"{lead.label.lower()} is unusually "
                f"{'high' if lead.direction == 'higher' else 'low'} — a pattern "
                f"common in AI-generated text"
            )
        else:
            top_reasons.append(
                "overall statistical patterns resemble those common in AI-generated text"
            )

    # ── 3. Ghostwriting signal ────────────────────────────────────────────────

    ghostwriting_signal = any(
        "ghostwriting" in entanglement.label.lower()
        for entanglement in result.interference.broken_entanglements
    )

    # ── 4. Confidence note based on effective_sample_count ───────────────────

    esc = result.baseline_confidence.effective_sample_count
    if esc < 2:
        confidence_note = "Assessment is tentative — only 1 writing sample in the baseline."
    elif esc < 5:
        confidence_note = (
            f"Assessment is based on a small baseline ({int(esc)} samples). "
            "More samples would improve accuracy."
        )
    else:
        confidence_note = f"Assessment based on {int(esc)} verified writing samples."

    # ── 5. Summary paragraph ──────────────────────────────────────────────────

    # Build a 2-3 sentence paragraph for professors
    score_pct = int(result.authorship.deviation_score * 100)

    if severity == "clear":
        summary = (
            f"This submission's stylometry closely matches the student's established baseline "
            f"(deviation score: {score_pct}%). "
            f"No significant anomalies detected in vocabulary range, sentence structure, "
            f"or writing patterns."
        )
    elif severity == "watch":
        summary = (
            f"This submission shows minor stylistic variations from the baseline "
            f"(deviation score: {score_pct}%), which may reflect topic differences or "
            f"natural writing variation. "
            f"No immediate action required, but continued monitoring is recommended."
        )
    elif severity == "concern":
        summary = (
            f"This submission exhibits notable stylistic differences from the student's baseline "
            f"(deviation score: {score_pct}%), particularly in {_format_reason(top_reasons[0] if top_reasons else 'writing patterns')}. "
            f"A conversation with the student is recommended to understand the source of these differences."
        )
    else:  # serious
        summary = (
            f"This submission shows significant authorship concerns (deviation score: {score_pct}%). "
            f"Multiple features deviate substantially from the baseline, particularly {_format_reason(top_reasons[0] if top_reasons else 'writing patterns')}. "
            f"Detailed review by the instructor is warranted."
        )

    if ghostwriting_signal:
        summary += " (Note: Potential ghostwriting signal detected in feature entanglements.)"

    return {
        "verdict": verdict,
        "severity": severity,
        "confidence_note": confidence_note,
        "top_reasons": top_reasons[:4],  # Cap at 4 reasons
        "ghostwriting_signal": ghostwriting_signal,
        "summary": summary,
    }


def _format_reason(reason: str) -> str:
    """Format a reason for inline insertion into summary."""
    # Remove trailing punctuation if present
    reason = reason.rstrip(".")
    # Convert to lowercase for inline use
    return reason.lower()
