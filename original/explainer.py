"""
explainer.py — Convert Layer7Output scoring results to plain-English explanations.

Transforms quantitative authorship signals into human-readable verdicts
for professors and instructors, emphasizing the "why" behind the score.
"""

from typing import Dict, List, Optional
from dataclasses import dataclass

from .quantum.scoring import Layer7Output


# ── Feature code → plain English name (comprehensive) ──────────────────────────

FEATURE_PLAIN_NAMES: Dict[str, str] = {
    # Tier 1 — Surface stylometry
    "type_token_ratio": "vocabulary range",
    "hapax_legomena_rate": "unique word usage",
    "mean_sentence_length": "typical sentence length",
    "sentence_length_variance": "variation in sentence length",
    "function_word_ratio": "function word frequency",
    "passive_voice_ratio": "use of passive voice",
    "modal_verb_ratio": "use of modal verbs",
    "stop_word_ratio": "stop word frequency",
    "avg_word_length": "word complexity",

    # Tier 2 — Discourse structure
    "discourse_marker_density": "use of transition words",
    "additive_ratio": "additive connectors (and, also)",
    "adversative_ratio": "adversative connectors (but, however)",
    "causal_ratio": "causal connectors (because, so)",
    "temporal_ratio": "temporal connectors (then, when)",
    "thematic_progression_score": "topic progression patterns",
    "pronoun_reference_density": "pronoun usage patterns",
    "lexical_chain_density": "lexical chains and cohesion",
    "paragraph_topic_position": "topic position in paragraphs",
    "avg_paragraph_length": "average paragraph length",
    "sentence_opener_variety": "variety in sentence starters",
    "cohesion_device_ratio": "cohesive devices",
    "transition_density": "transition word frequency",

    # Tier 3 — Rhetorical & register
    "epistemic_certainty_ratio": "confident assertion style",
    "hedging_density": "use of hedging words",
    "assertion_density": "frequency of assertions",
    "source_integration_style": "integration of sources",
    "counter_argument_ratio": "counter-argument engagement",
    "claim_density": "density of claims",
    "question_ratio": "use of rhetorical questions",
    "imperative_density": "imperative mood usage",
    "first_person_ratio": "first-person usage",
    "appeal_to_authority_density": "appeals to authority",
    "conclusion_strategy_score": "conclusion strategy",
    "theological_register_score": "theological register",

    # Tier 4 — Character & Punctuation
    "char_trigram_entropy": "character-level writing patterns",
    "punctuation_diversity": "punctuation variety",
    "comma_rate": "comma usage",
    "semicolon_colon_rate": "semicolon and colon usage",
    "parenthetical_rate": "parenthetical usage",
    "dash_rate": "dash usage",
    "quote_rate": "quotation frequency",

    # Tier 5 — POS & Syntax
    "pos_bigram_entropy": "part-of-speech patterns",
    "pos_trigram_entropy": "three-word grammatical patterns",
    "noun_verb_ratio": "noun-to-verb balance",
    "adjective_rate": "adjective frequency",
    "adverb_rate": "adverb frequency",
    "subordination_ratio": "subordination patterns",
    "clause_depth_mean": "clause depth complexity",

    # Tier 6 — Idiosyncratic
    "contraction_rate": "use of contractions (don't, can't, it's)",
    "sentence_initial_conjunction_rate": "sentence-initial conjunctions",
    "that_which_ratio": "that vs. which usage",
    "citation_style_consistency": "consistency of citations",
    "list_marker_preference": "list marker preferences",
    "abbreviation_tendency": "abbreviation usage",

    # Tier 7 — AI Detection
    "burstiness": "vocabulary bursts",
    "perplexity_proxy": "text predictability",
    "repetition_gap_entropy": "repetition patterns",
    "transition_predictability": "transition predictability",
    "vocabulary_introduction_rate": "new vocabulary introduction",
    "filler_hedge_cluster_rate": "pattern of hesitation markers",

    # Tier 8 — Prosodic Rhythm
    "stress_entropy_unigram": "syllabic stress patterns",
    "stress_entropy_bigram": "consecutive stress patterns",
    "clausulae_consistency": "sentence-ending rhythm patterns",
    "breath_group_variance": "breath group patterns",

    # Tier 9 — Cognitive Sequencing
    "structural_centrist_penalty": "argument structure diversity",
    "argument_sequence_likelihood": "argument sequence patterns",

    # Tier 10 — Semantic
    "semantic_field_dispersion": "semantic field diversity",
    "semantic_centroid_proximity": "semantic consistency",

    # Tier 11 — Error Ecology
    "error_kl_divergence": "error fingerprint (spelling/grammar mistakes)",
    "stumble_rate_consistency": "pattern of errors and stumbles",
    "punctuation_error_ratio": "punctuation error patterns",

    # Tier 12 — Tension Arc
    "catastrophe_index": "narrative tension arc structure",

    # Tier 13 — Prosodic Depth
    "clausula_type_consistency": "sentence-ending patterns",
    "breath_group_regularity": "breathing patterns",
    "vowel_sonority_ratio": "vowel sonority patterns",
    "arc_resolution_score": "sentence-arc resolution",
    "metric_flatness_score": "rhythmic flatness (AI marker)",
    "clausula_shape_preference": "sentence-ending shape preference",

    # Tier 14 — Error Topology
    "error_topology_consistency": "error placement patterns",
    "article_omission_rate": "article omission patterns",
    "pronoun_ambiguity_rate": "pronoun ambiguity",
    "comma_splice_rate": "comma splice frequency",

    # Tier 15 — Lexical Architecture
    "semantic_field_concentration": "semantic field concentration",
    "polysyndeton_ratio": "polysyndeton usage",
    "chiasmus_rate": "chiasmus (A-B-B-A) patterns",
    "latinate_ratio": "Latinate vocabulary usage",
    "nominalization_density": "nominalization density",

    # Tier 16 — Citation Fingerprint
    "signal_verb_entropy": "signal verb variety",
    "signal_verb_assertiveness": "signal verb tone",
    "source_loyalty_index": "source loyalty patterns",
    "block_quote_rate": "block quotation usage",
    "citation_density_cv": "citation clustering",
    "ibid_usage_rate": "ibid. usage patterns",
    "citation_position_pref": "citation positioning",
    "paraphrase_density": "paraphrase attribution",

    # Tier 17 — Behavioral Biometrics
    "typing_speed_cv": "typing rhythm consistency",
    "burst_ratio": "rapid typing patterns",
    "deletion_rate": "deletion and revision frequency",
    "pause_density": "pause and thinking patterns",
    "paste_event_rate": "paste/paste-over events",
    "revision_depth": "depth of revisions",

    # Comparison features
    "char_trigram_profile_divergence": "character-level divergence",
    "function_word_profile_divergence": "function word divergence",
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


def explain(result: Layer7Output) -> Dict:
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
    verdict_data = action_verdicts.get(action, {
        "verdict": "Assessment inconclusive.",
        "severity": "watch",
    })
    verdict = verdict_data["verdict"]
    severity = verdict_data["severity"]

    # ── 2. Top reasons from destructive features ──────────────────────────────

    top_reasons: List[str] = []

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
        confidence_note = (
            f"Assessment based on {int(esc)} verified writing samples."
        )

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
    reason = reason.rstrip('.')
    # Convert to lowercase for inline use
    return reason.lower()
