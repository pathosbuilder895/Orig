"""
quantum/professor_narrative.py — Professor-facing plain-English explanations.

Translates a Layer7Output into language professors actually understand:
no z-scores, no tier labels, no quantum jargon. Pure deterministic template
assembly — no LLM calls, no randomness.

Tone rules:
- NEVER say "cheating", "fraud", "plagiarism" — say "outside help",
  "another voice", "AI assistance"
- NEVER present it as a verdict — frame as "observations that may warrant
  a conversation"
- Acknowledge innocent explanations first in the hypotheses list
- Use "this student" or the student_name throughout
- No numbers (deviation scores, z-scores) in the professor-facing text
- Give concrete parenthetical examples of what features mean
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional


# ── Feature plain-language mapping ────────────────────────────────────────────
# Each entry:
#   label       — professor-friendly feature name
#   more        — what "higher than baseline" means in plain English
#   less        — what "lower than baseline" means
#   ai_signal   — True if anomaly here is especially relevant as an AI-writing signal
#   behavioral  — True for Tier 17 keystroke/paste features

_FEATURE_PLAIN: Dict[str, Dict[str, Any]] = {
    # Tier 1 — Surface stylometry
    "passive_voice_ratio": {
        "label": "use of passive voice",
        "more": "used passive constructions more often than usual (e.g., 'it was argued' rather than 'I argue')",
        "less": "used passive voice less often than usual, writing in a more direct, active style",
        "ai_signal": False,
        "behavioral": False,
    },
    "first_person_ratio": {
        "label": "first-person voice",
        "more": "used first-person language more often than usual (e.g., 'I argue', 'we see')",
        "less": "used first-person language less often than usual, adopting a more distant, third-person voice",
        "ai_signal": False,
        "behavioral": False,
    },
    "mean_sentence_length": {
        "label": "sentence length",
        "more": "wrote noticeably longer sentences than usual",
        "less": "wrote noticeably shorter sentences than usual",
        "ai_signal": False,
        "behavioral": False,
    },
    "sentence_length_variance": {
        "label": "variation in sentence length",
        "more": "showed more variation in sentence length than usual — mixing very short and very long sentences",
        "less": "wrote sentences of unusually uniform length, with little variation",
        "ai_signal": True,
        "behavioral": False,
    },
    "type_token_ratio": {
        "label": "vocabulary variety",
        "more": "used a wider range of different words than usual",
        "less": "used a narrower vocabulary range than usual, repeating words more frequently",
        "ai_signal": False,
        "behavioral": False,
    },
    "avg_word_length": {
        "label": "word complexity",
        "more": "used longer, more complex words than usual",
        "less": "used shorter, simpler words than usual",
        "ai_signal": False,
        "behavioral": False,
    },
    "hapax_legomena_rate": {
        "label": "use of unique words",
        "more": "used more words that appear only once — a broader working vocabulary",
        "less": "repeated words more than usual, with fewer unique word choices",
        "ai_signal": False,
        "behavioral": False,
    },
    "modal_verb_ratio": {
        "label": "use of modal verbs",
        "more": "used more modal verbs than usual (e.g., 'might', 'could', 'should')",
        "less": "used fewer modal verbs than usual, making more direct claims",
        "ai_signal": False,
        "behavioral": False,
    },
    "function_word_ratio": {
        "label": "function word patterns",
        "more": "used function words (e.g., 'the', 'of', 'in') at a higher rate than usual",
        "less": "used function words at a lower rate than usual",
        "ai_signal": False,
        "behavioral": False,
    },
    # Tier 2 — Discourse structure
    "transition_density": {
        "label": "use of transition phrases",
        "more": "used significantly more transitional phrases than usual (e.g., 'furthermore', 'however', 'therefore')",
        "less": "used fewer transitional phrases than usual",
        "ai_signal": False,
        "behavioral": False,
    },
    "avg_paragraph_length": {
        "label": "paragraph length",
        "more": "wrote longer paragraphs than usual",
        "less": "wrote shorter paragraphs than usual",
        "ai_signal": False,
        "behavioral": False,
    },
    "sentence_opener_variety": {
        "label": "sentence opener variety",
        "more": "varied sentence beginnings more than usual",
        "less": "started sentences in more repetitive ways than usual",
        "ai_signal": False,
        "behavioral": False,
    },
    # Tier 3 — Rhetorical & register
    "hedging_density": {
        "label": "use of hedging language",
        "more": "used more uncertain or cautious language than usual (e.g., 'perhaps', 'might', 'seems')",
        "less": "used less hedging language than usual, making more direct claims",
        "ai_signal": False,
        "behavioral": False,
    },
    "assertion_density": {
        "label": "use of assertive language",
        "more": "made claims more assertively than usual (e.g., 'clearly', 'certainly', 'it is evident')",
        "less": "made fewer direct assertions than usual",
        "ai_signal": False,
        "behavioral": False,
    },
    "claim_density": {
        "label": "frequency of explicit claims",
        "more": "made explicit arguments more frequently than usual (e.g., 'therefore', 'this shows', 'I argue')",
        "less": "made fewer explicit argumentative claims than usual",
        "ai_signal": False,
        "behavioral": False,
    },
    "counter_argument_ratio": {
        "label": "engagement with opposing views",
        "more": "engaged with counterarguments more than usual",
        "less": "addressed opposing views less than usual",
        "ai_signal": False,
        "behavioral": False,
    },
    "question_ratio": {
        "label": "use of rhetorical questions",
        "more": "used questions more often than usual",
        "less": "used fewer questions than usual",
        "ai_signal": False,
        "behavioral": False,
    },
    "theological_register_score": {
        "label": "theological vocabulary",
        "more": "used more specialized theological language than usual (e.g., 'soteriology', 'hermeneutic', 'pneumatology')",
        "less": "used less specialized theological vocabulary than usual",
        "ai_signal": False,
        "behavioral": False,
    },
    "source_integration_style": {
        "label": "how sources are woven into the text",
        "more": "integrated sources more directly into the text than usual",
        "less": "relied less on source integration than usual",
        "ai_signal": False,
        "behavioral": False,
    },
    # Tier 6 — Idiosyncratic
    "contraction_rate": {
        "label": "use of contractions",
        "more": "used contractions more than usual (e.g., 'it's', 'they're', 'don't')",
        "less": "used fewer contractions than usual, maintaining a more formal register",
        "ai_signal": False,
        "behavioral": False,
    },
    "sentence_initial_conjunction_rate": {
        "label": "sentence-starting conjunctions",
        "more": "started sentences with conjunctions more often than usual (e.g., 'And', 'But', 'So')",
        "less": "rarely started sentences with conjunctions in this submission",
        "ai_signal": False,
        "behavioral": False,
    },
    "that_which_ratio": {
        "label": "that/which usage",
        "more": "used 'that' more often than 'which' relative to their baseline pattern",
        "less": "used 'which' more often than 'that' relative to their baseline pattern",
        "ai_signal": False,
        "behavioral": False,
    },
    "citation_style_consistency": {
        "label": "citation format consistency",
        "more": "cited sources with greater consistency than usual",
        "less": "cited sources with less consistency than usual — mixing formats",
        "ai_signal": False,
        "behavioral": False,
    },
    "abbreviation_tendency": {
        "label": "use of abbreviations",
        "more": "used abbreviations more than usual (e.g., 'i.e.', 'e.g.', 'cf.')",
        "less": "used fewer abbreviations than usual",
        "ai_signal": False,
        "behavioral": False,
    },
    # Tier 7 — AI detection
    "burstiness": {
        "label": "rhythm of vocabulary introduction",
        "more": "introduced new vocabulary in more irregular bursts than usual — a human-writing pattern",
        "less": "introduced vocabulary at an unusually uniform, steady rate — which can indicate AI-generated text",
        "ai_signal": True,
        "behavioral": False,
    },
    "perplexity_proxy": {
        "label": "predictability of word choices",
        "more": "made more surprising or unexpected word choices than usual",
        "less": "chose words in unusually predictable patterns — which can be a signal of AI-generated text",
        "ai_signal": True,
        "behavioral": False,
    },
    "transition_predictability": {
        "label": "predictability of transitions between ideas",
        "more": "moved between ideas in more varied, less predictable ways than usual",
        "less": "moved between ideas in unusually predictable, formulaic ways — common in AI-generated text",
        "ai_signal": True,
        "behavioral": False,
    },
    # Tier 11 — Error ecology
    "error_kl_divergence": {
        "label": "personal error patterns",
        "more": "the specific types of writing errors in this submission differ from this student's usual error signature",
        "less": "the writing errors closely match this student's typical error patterns",
        "ai_signal": False,
        "behavioral": False,
    },
    "stumble_rate_consistency": {
        "label": "overall error rate",
        "more": "made fewer errors overall than usual — unusually clean writing",
        "less": "made more errors overall than usual",
        "ai_signal": False,
        "behavioral": False,
    },
    "punctuation_error_ratio": {
        "label": "punctuation error patterns",
        "more": "had more punctuation errors than usual",
        "less": "had fewer punctuation errors than usual — unusually clean punctuation",
        "ai_signal": False,
        "behavioral": False,
    },
    # Tier 13 — Prosodic depth
    "metric_flatness_score": {
        "label": "rhythmic consistency across the essay",
        "more": "the rhythmic pattern of sentences was unusually uniform across paragraphs — a common pattern in AI-generated text",
        "less": "sentence rhythm varied naturally across paragraphs, as human writing typically does",
        "ai_signal": True,
        "behavioral": False,
    },
    # Tier 14 — Error topology
    "comma_splice_rate": {
        "label": "comma splices",
        "more": "used more comma splices than usual (joining two full sentences with only a comma)",
        "less": "used fewer comma splices than usual",
        "ai_signal": False,
        "behavioral": False,
    },
    # Tier 15 — Lexical architecture
    "latinate_ratio": {
        "label": "use of Latinate vocabulary",
        "more": "used more Latinate vocabulary than usual (words ending in '-tion', '-ment', '-ity')",
        "less": "used less Latinate vocabulary than usual, preferring simpler Germanic word roots",
        "ai_signal": False,
        "behavioral": False,
    },
    "nominalization_density": {
        "label": "use of nominalizations",
        "more": "converted verbs to nouns more than usual (e.g., 'the consideration of' rather than 'considering')",
        "less": "used fewer nominalizations than usual",
        "ai_signal": False,
        "behavioral": False,
    },
    # Tier 16 — Citation fingerprint
    "signal_verb_assertiveness": {
        "label": "how assertively sources are introduced",
        "more": "introduced sources more assertively than usual (e.g., 'argues', 'demonstrates', 'proves')",
        "less": "introduced sources more tentatively than usual (e.g., 'notes', 'suggests', 'mentions')",
        "ai_signal": False,
        "behavioral": False,
    },
    "block_quote_rate": {
        "label": "use of block quotations",
        "more": "used longer block quotations more than usual",
        "less": "used fewer block quotations than usual",
        "ai_signal": False,
        "behavioral": False,
    },
    "paraphrase_density": {
        "label": "how often ideas are paraphrased",
        "more": "paraphrased source material more than usual",
        "less": "paraphrased source material less than usual",
        "ai_signal": False,
        "behavioral": False,
    },
    # Tier 17 — Behavioral biometrics
    "paste_event_rate": {
        "label": "content pasting during writing",
        "more": "pasted text into the document more often than is typical for their own writing sessions",
        "less": "pasted less text than usual — content was primarily typed directly",
        "ai_signal": False,
        "behavioral": True,
    },
    "typing_speed_cv": {
        "label": "typing rhythm",
        "more": "typed with more irregular rhythm than usual — consistent with composing from scratch",
        "less": "typed with unusually regular, even rhythm — which may indicate copying from elsewhere",
        "ai_signal": False,
        "behavioral": True,
    },
    "deletion_rate": {
        "label": "revision while typing",
        "more": "deleted and revised text more than usual while typing",
        "less": "deleted text less than usual while typing — fewer in-process revisions",
        "ai_signal": False,
        "behavioral": True,
    },
    "pause_density": {
        "label": "pauses during writing",
        "more": "paused more often than usual while writing — consistent with thinking through the material",
        "less": "paused less than usual — typed more continuously than in prior sessions",
        "ai_signal": False,
        "behavioral": True,
    },
    "burst_ratio": {
        "label": "rapid typing bursts",
        "more": "typed in more rapid bursts than usual — possibly transcribing pre-composed text",
        "less": "typed with fewer rapid bursts than usual",
        "ai_signal": False,
        "behavioral": True,
    },
    # Additional features
    "subordination_ratio": {
        "label": "sentence complexity",
        "more": "used more complex, subordinate clauses than usual (nested phrases within sentences)",
        "less": "wrote simpler sentences than usual, with less subordination",
        "ai_signal": False,
        "behavioral": False,
    },
    "char_trigram_entropy": {
        "label": "character-level writing fingerprint",
        "more": "showed a different character-level pattern than usual — the way letters are combined differs",
        "less": "showed a character-level pattern closer to baseline than usual",
        "ai_signal": False,
        "behavioral": False,
    },
}

# ── Magnitude qualifier ────────────────────────────────────────────────────────

def _magnitude(delta: float) -> Optional[str]:
    """Return a magnitude adverb, or None if the delta is too small to mention."""
    abs_d = abs(delta)
    if abs_d < 0.10:
        return None
    if abs_d < 0.20:
        return "somewhat"
    if abs_d < 0.32:
        return "notably"
    if abs_d < 0.45:
        return "significantly"
    return "markedly"


# ── Output dataclass ───────────────────────────────────────────────────────────

@dataclass
class ProfessorExplanation:
    headline: str                  # one-sentence verdict in plain English
    summary: str                   # 2-3 sentence opening paragraph
    observations: List[str]        # 3-5 specific observations, each a complete sentence
    hypotheses: List[str]          # 2-4 non-accusatory possible explanations
    suggested_action: str          # concrete next step the professor can take
    confidence_note: str           # plain language about reliability of comparison
    has_behavioral_signals: bool   # True if keystroke/paste data contributed
    has_ai_signals: bool           # True if AI-detection features were anomalous
    # Corpus-level AI-likelihood band ("low"/"elevated"/"strong") when the
    # AI_LIKELIHOOD_ENABLED detector produced a signal; None otherwise.
    # Defaults keep existing consumers byte-stable when the flag is off.
    ai_likelihood_band: Optional[str] = None


# ── Headline logic ─────────────────────────────────────────────────────────────

def _build_headline(deviation: float, student_name: str) -> str:
    """
    Lead with what was CONFIRMED, not what deviated.
    Same math — opposite emotion. Teachers are defenders, not prosecutors.
    """
    # Express as voice-match confidence (what we confirmed)
    confidence_pct = max(0, int(round((1.0 - min(deviation, 1.0)) * 100)))
    name = student_name

    if deviation < 0.30:
        return (
            f"{name}'s writing is {confidence_pct}% consistent with their "
            f"established voice — this submission is confirmed authentic."
        )
    if deviation < 0.55:
        return (
            f"{name}'s writing is {confidence_pct}% consistent with their "
            f"established voice, with a few areas worth a closer look."
        )
    if deviation < 0.75:
        return (
            f"This submission is {confidence_pct}% consistent with {name}'s "
            f"established voice — notable differences are present."
        )
    return (
        f"This submission is {confidence_pct}% consistent with {name}'s "
        f"established voice — the difference is substantial enough to warrant "
        f"a conversation."
    )


# ── Summary paragraph ──────────────────────────────────────────────────────────

def _build_summary(
    deviation: float,
    action: str,
    student_name: str,
    n_destructive: int,
    trajectory_direction: str,
) -> str:
    name = student_name

    if deviation < 0.30:
        base = (
            f"The system compared this submission against {name}'s established "
            f"writing profile and found a strong match across stylistic patterns — "
            f"sentence structure, vocabulary habits, rhetorical choices, and "
            f"argument pacing are all consistent with prior authenticated work. "
            f"This is a healthy result."
        )
        if trajectory_direction == "growth":
            base += (
                f" There are also signs of continued writing development, "
                f"which is an encouraging trend."
            )
        return base

    if deviation < 0.55:
        # Build the area count phrase — "some" when n_destructive is unavailable (0/None)
        _area_phrase = (
            f"{n_destructive} area{'s' if n_destructive != 1 else ''}"
            if n_destructive
            else "some areas"
        )
        return (
            f"The system confirmed most of {name}'s established writing patterns "
            f"in this submission — the stylistic foundation looks like their work. "
            f"There are {_area_phrase} where this submission differs from prior "
            f"work. Differences at this level are common: topic demands, genre "
            f"shifts, time pressure, or simply having an unusual writing day. "
            f"A brief check-in is one option, though not required."
        )

    if deviation < 0.75:
        return (
            f"The system confirmed some of {name}'s stylistic patterns in this "
            f"submission, but also found a pattern of differences across several "
            f"markers — the kind that tend to stay consistent even when topic and "
            f"genre change. Before drawing any conclusions, a conversation with "
            f"{name} about their writing process for this assignment would help "
            f"clarify what happened."
        )

    return (
        f"The system found the majority of stylistic markers in this submission "
        f"to differ from {name}'s established voice — things like sentence rhythm, "
        f"vocabulary habits, and argument structure. These features tend to stay "
        f"consistent in a writer's work regardless of topic. The differences here "
        f"go beyond typical variation. A direct conversation with {name} before "
        f"returning this paper is the recommended path."
    )


# ── Observation builder ────────────────────────────────────────────────────────

def _build_observations(
    destructive_features: list,
    constructive_features: list,
    student_name: str,
) -> List[str]:
    """
    Build 3-5 observation sentences from the interference decomposition.
    Destructive features (anomalous) are primary; constructive (consistent)
    are added as reassuring context if there are few destructive ones.
    """
    name = student_name
    observations: List[str] = []

    for fc in destructive_features:
        entry = _FEATURE_PLAIN.get(fc.code)
        if not entry:
            continue
        mag = _magnitude(fc.delta)
        if mag is None:
            continue
        # Pick more/less based on direction of delta
        direction_text = entry["more"] if fc.delta > 0 else entry["less"]
        obs = (
            f"In terms of {entry['label']}, {name} {direction_text} "
            f"compared to their prior work."
        )
        observations.append(obs)
        if len(observations) >= 4:
            break

    # If we have few anomalous observations, add a reassuring constructive one
    if len(observations) < 3 and constructive_features:
        for fc in constructive_features[:2]:
            entry = _FEATURE_PLAIN.get(fc.code)
            if not entry:
                continue
            obs = (
                f"{name}'s {entry['label']} is consistent with their established "
                f"writing — this aspect of the submission matches prior work well."
            )
            observations.append(obs)
            if len(observations) >= 3:
                break

    # If still no observations (all deltas too small or unmapped features),
    # give a generic note
    if not observations:
        observations.append(
            f"No individual writing feature stands out as dramatically different "
            f"from {name}'s established pattern, though the overall profile "
            f"shows some variation."
        )

    return observations[:5]


# ── Hypothesis builder ────────────────────────────────────────────────────────

def _build_hypotheses(
    deviation: float,
    has_behavioral: bool,
    has_ai: bool,
    quantum_fidelity: float,
    action: str,
    ai_band: Optional[str] = None,
) -> List[str]:
    hyps: List[str] = []

    # Always first: innocent situational explanation
    hyps.append(
        "Writing under pressure or in an unusual environment — stress, fatigue, "
        "time constraints, or an unfamiliar setting can shift writing style noticeably."
    )

    # Unfamiliar topic or genre — always include
    hyps.append(
        "An unfamiliar topic or genre challenge — writing about a new subject area "
        "or in a form they haven't practiced as much can pull style in new directions."
    )

    # Behavioral signal: pasting
    if has_behavioral:
        hyps.append(
            "Content was composed elsewhere and pasted in — the student may have "
            "drafted outside the system, in a word processor or notes app, before "
            "transferring it."
        )

    # AI signal — the corpus-level detector's band takes precedence over the
    # per-feature heuristic when both fire (same hypothesis, better evidence).
    # Band-only, frequency-framed prose; the calibrated probability lives in
    # the structured API field, never in a sentence (tone rule: no numbers).
    if ai_band == "strong":
        hyps.append(
            "Several statistical patterns in this submission resemble those "
            "common in AI-generated text, at a level seen in fewer than one in "
            "a hundred authentic essays in our calibration corpora — this can "
            "also reflect heavy editing tools or an unusually formal register, "
            "and is worth exploring in conversation."
        )
    elif ai_band == "elevated":
        hyps.append(
            "Some statistical patterns in this submission resemble those "
            "common in AI-generated text — this can also reflect heavy "
            "editing tools or an unusually formal register, and is worth "
            "exploring in conversation."
        )
    elif has_ai:
        hyps.append(
            "AI writing assistance was used — one or more patterns in this "
            "submission are consistent with AI-generated or AI-assisted text."
        )

    # Very high deviation + low fidelity: ghost-writing
    if deviation >= 0.75 and quantum_fidelity < 0.4:
        # Only add if we haven't already hit 4
        if len(hyps) < 4:
            hyps.append(
                "The essay was written or substantially revised by another person — "
                "the stylistic distance from this student's established profile is "
                "large enough that outside authorship is one explanation."
            )

    return hyps[:4]


# ── Suggested action ──────────────────────────────────────────────────────────

def _build_suggested_action(action: str, student_name: str) -> str:
    name = student_name
    if action == "no_action":
        return (
            f"Voice confirmed — no action needed. This submission is consistent with "
            f"{name}'s established writing. Return it with confidence."
        )
    if action == "monitor":
        return (
            f"Keep this result in context as you read {name}'s next submission. "
            f"If a pattern develops, a brief open-ended check-in can surface "
            f"useful information. No urgency now."
        )
    if action == "schedule_conversation":
        return (
            f"A brief, curious conversation with {name} about their writing "
            f"process for this assignment is the most useful next step — not an "
            f"interrogation, just 10 minutes of open questions. In most cases "
            f"this resolves the question quickly."
        )
    # escalate
    return (
        f"Speak with {name} before returning this submission. Approach it as a "
        f"conversation about their process: where they wrote, how long it took, "
        f"what sources they consulted. That context, combined with this result, "
        f"will clarify the picture."
    )


# ── Confidence note ───────────────────────────────────────────────────────────

def _build_confidence_note(sample_count: int) -> str:
    if sample_count >= 8:
        return (
            f"This comparison is based on {sample_count} authenticated writing "
            f"samples — the profile is well-established and reliable."
        )
    if sample_count >= 4:
        return (
            f"This comparison is based on {sample_count} writing samples. The "
            f"profile is developing; adding more baselines will improve reliability."
        )
    return (
        f"This comparison is based on only {sample_count} writing sample(s). "
        f"The profile is limited — treat this result as preliminary and weight "
        f"the conversation more than the score."
    )


# ══════════════════════════════════════════════════════════════════════════════
# Public builder
# ══════════════════════════════════════════════════════════════════════════════

def build_professor_explanation(
    layer7: "object",
    student_name: str = "this student",
) -> ProfessorExplanation:
    """
    Translate a Layer7Output into professor-facing plain-English explanation.

    Pure template assembly — deterministic, no LLM calls. Safe to call even
    when layer7 fields are partially populated; defaults gracefully.
    """
    # ── Pull fields off layer7 safely ─────────────────────────────────────────
    auth = getattr(layer7, "authorship", None)
    deviation = float(getattr(auth, "deviation_score", 0.0))
    quantum_fidelity = float(getattr(auth, "quantum_fidelity", 0.0))

    rec = getattr(layer7, "recommendation", None)
    action = getattr(rec, "action", "no_action") or "no_action"

    traj = getattr(layer7, "trajectory", None)
    trajectory_direction = getattr(traj, "direction", "insufficient_data") or "insufficient_data"

    bc = getattr(layer7, "baseline_confidence", None)
    sample_count = int(getattr(bc, "sample_count", 0))

    interference = getattr(layer7, "interference", None)
    destructive_features = list(getattr(interference, "destructive_features", []) or [])
    constructive_features = list(getattr(interference, "constructive_features", []) or [])

    # ── Detect behavioral and AI signals in destructive features ─────────────
    has_behavioral = False
    has_ai = False
    for fc in destructive_features:
        if _magnitude(fc.delta) is None:
            continue
        entry = _FEATURE_PLAIN.get(fc.code)
        if entry is None:
            continue
        if entry.get("behavioral"):
            has_behavioral = True
        if entry.get("ai_signal"):
            has_ai = True

    # ── Corpus-level AI-likelihood (second scoring mode, report-only) ─────────
    ai_like = getattr(layer7, "ai_likelihood", None)
    ai_band = getattr(ai_like, "band", None) if ai_like is not None else None
    if ai_band == "strong":
        has_ai = True

    # ── Build components ──────────────────────────────────────────────────────
    headline = _build_headline(deviation, student_name)

    summary = _build_summary(
        deviation=deviation,
        action=action,
        student_name=student_name,
        n_destructive=len(destructive_features),
        trajectory_direction=trajectory_direction,
    )

    observations = _build_observations(
        destructive_features=destructive_features,
        constructive_features=constructive_features,
        student_name=student_name,
    )

    hypotheses = _build_hypotheses(
        deviation=deviation,
        has_behavioral=has_behavioral,
        has_ai=has_ai,
        quantum_fidelity=quantum_fidelity,
        action=action,
        ai_band=ai_band,
    )

    suggested_action = _build_suggested_action(action, student_name)

    confidence_note = _build_confidence_note(sample_count)

    return ProfessorExplanation(
        headline=headline,
        summary=summary,
        observations=observations,
        hypotheses=hypotheses,
        suggested_action=suggested_action,
        confidence_note=confidence_note,
        has_behavioral_signals=has_behavioral,
        has_ai_signals=has_ai,
        ai_likelihood_band=ai_band,
    )


__all__ = [
    "ProfessorExplanation",
    "build_professor_explanation",
]
