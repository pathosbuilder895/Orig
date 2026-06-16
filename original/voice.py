"""
voice.py — the student-facing *redacting* projection layer (ADR-005).

This module is the single, server-side choke point that turns the rich internal
state (the 103-feature baseline vector, raw divergence scores, action enums,
sample counts, formation reasons) into the *display-ready, formation-register*
view the student dashboard consumes via ``GET /me/voice`` and ``POST /me/work``.

Why this lives on the server
────────────────────────────
"Formation over surveillance" is only true if it is true *on the wire*. The old
``student.html`` reframed raw data in client-side JavaScript — any student with
devtools open saw the feature taxonomy, exact deviation numbers, the action
enum, and sample counts. This module *projects those fields away before
serialization*, so they are never sent. The "DO NOT EXPOSE" list becomes a
code-level guarantee, not a copy convention.

The forbidden values (feature codes, ``divergence``/``deviation`` numbers,
``purity``, sample counts, action enums, thresholds) must never appear in any
value this module returns. ``tests/test_voice_leak.py`` is the permanent gate.

The voice-dimension taxonomy below (``VOICE_DIMENSIONS``) is deliberately a
*blend* of several underlying features per dimension, and the mapping is kept
here on the server — it is never shipped to the client, so the visualization is
personal and real without being a lookup table back to the 103 features.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional


# ── The voice-dimension taxonomy (server-side only) ──────────────────────────
# Each named dimension is a blend of several feature codes. A student (or a
# motivated cheater) seeing "Cadence = 0.62" cannot reverse it to any single
# tracked feature, and this mapping never crosses the wire.
VOICE_DIMENSIONS: List[tuple] = [
    ("Cadence", [
        "mean_sentence_length", "sentence_length_variance", "burstiness",
        "breath_group_variance", "breath_group_regularity", "arc_resolution_score",
    ]),
    ("Diction", [
        "type_token_ratio", "hapax_legomena_rate", "avg_word_length",
        "latinate_ratio", "nominalization_density", "vocabulary_introduction_rate",
    ]),
    ("Texture", [
        "punctuation_diversity", "comma_rate", "semicolon_colon_rate",
        "dash_rate", "parenthetical_rate", "subordination_ratio", "clause_depth_mean",
    ]),
    ("Register", [
        "theological_register_score", "function_word_ratio", "contraction_rate",
        "stop_word_ratio", "epistemic_certainty_ratio",
    ]),
    ("Restraint", [
        "hedging_density", "assertion_density", "modal_verb_ratio",
        "claim_density", "counter_argument_ratio", "question_ratio",
    ]),
    ("Architecture", [
        "transition_density", "discourse_marker_density", "cohesion_device_ratio",
        "thematic_progression_score", "lexical_chain_density", "conclusion_strategy_score",
    ]),
    ("Resonance", [
        "stress_entropy_unigram", "clausulae_consistency", "clausula_type_consistency",
        "vowel_sonority_ratio", "metric_flatness_score", "polysyndeton_ratio",
    ]),
]


def _clamp01(x: float) -> float:
    if x < 0.0:
        return 0.0
    if x > 1.0:
        return 1.0
    return x


def project_fingerprint(baseline_vector: Optional[Dict[str, float]]) -> List[Dict[str, Any]]:
    """Blend the raw 103-feature baseline vector into named voice dimensions.

    Returns ``[{name, value}]`` where value ∈ [0, 1] is the mean of the
    dimension's constituent features. The feature codes themselves never appear
    in the output. An empty/None baseline yields neutral 0.5 dimensions so the
    radar still renders a (centred) shape for a brand-new student.
    """
    vec = baseline_vector or {}
    out: List[Dict[str, Any]] = []
    for name, codes in VOICE_DIMENSIONS:
        vals = [float(vec[c]) for c in codes if c in vec and vec[c] is not None]
        value = sum(vals) / len(vals) if vals else 0.5
        out.append({"name": name, "value": round(_clamp01(value), 3)})
    return out


def _fidelity(divergence: Optional[float]) -> int:
    """Resolve a raw divergence score into a display-ready fidelity (0–100).

    This is the *only* place the divergence→fidelity transform happens. The
    client never sees the divergence; it receives the resolved fidelity, which
    is the metric the Arc is drawn from.
    """
    d = float(divergence or 0.0)
    f = round((1.0 - d) * 100.0)
    return max(0, min(100, int(f)))


def _short_period(created_at: Optional[str]) -> str:
    """A bare 'YYYY-MM-DD' (or '') — the client formats it for display."""
    if not created_at:
        return ""
    return str(created_at)[:10]


def project_arc(manifests: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Manifests (newest-first) → an ascending fidelity series for the Arc.

    Each point carries only the *resolved* fidelity, a period label, and an
    ``attention`` boolean the server decided (whether this piece is a review
    opportunity). The raw ``divergence_score`` and ``action`` enum are dropped.
    """
    # list_manifests returns newest-first; the Arc reads left→right oldest→newest.
    ordered = list(reversed(manifests or []))
    series: List[Dict[str, Any]] = []
    for m in ordered:
        action = (m.get("action") or "no_action")
        series.append({
            "period": _short_period(m.get("created_at")),
            "fidelity": _fidelity(m.get("divergence_score")),
            "attention": action != "no_action",
        })
    return series


def project_voice_notes(corrections: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Instructor corrections → finished prose voice notes.

    Only the human-written ``notes`` prose, the reviewer, and the date cross the
    wire. The scores/verdicts/actions that generated each correction are stripped.
    """
    out: List[Dict[str, Any]] = []
    for c in corrections or []:
        note = (c.get("notes") or "").strip()
        if not note:
            continue
        out.append({
            "note": note,
            "reviewer": (c.get("reviewer") or "Your tutor").strip() or "Your tutor",
            "date": _short_period(c.get("created_at")),
        })
    return out


def project_review_opportunities(manifests: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """The most recent flagged submission → a single gentle invitation.

    Server-side decides *what qualifies* (action ≠ no_action). The student
    receives an invitation in prose plus a locator — never the score, the
    threshold, or the action enum.
    """
    for m in (manifests or []):  # newest-first
        action = (m.get("action") or "no_action")
        if action == "no_action":
            continue
        locator = _short_period(m.get("created_at"))
        return [{
            "invitation_prose": (
                "A passage in your recent work reads a little differently from your "
                "established voice. This happens to every writer — it is worth a brief "
                "conversation with your tutor, not a cause for worry."
            ),
            "locator": locator,
        }]
    return []


def project_milestones(
    sample_count: int,
    authenticated_count: int,
    formation_completed: bool,
) -> List[Dict[str, Any]]:
    """Sample counts → a positive credential as named milestones.

    Never sends the raw counts or "3 of 5 samples" — only whether each named
    milestone has been *reached* or is *upcoming*, with affirming copy.
    """
    reached_established = sample_count >= 3
    reached_sampled = sample_count >= 1
    reached_affirmed = authenticated_count >= 1 or formation_completed

    def state(reached: bool) -> str:
        return "reached" if reached else "upcoming"

    return [
        {
            "label": "Voice Sampled",
            "state": state(reached_sampled),
            "blurb": "Your writing has entered your formation record.",
        },
        {
            "label": "Voice Established",
            "state": state(reached_established),
            "blurb": "Enough of your writing is on file to recognise your voice.",
        },
        {
            "label": "Voice Affirmed",
            "state": state(reached_affirmed),
            "blurb": "A verified piece confirms this voice is genuinely yours.",
        },
    ]


_FORMATION_STEP_LABELS = {
    0: "Ready to begin",
    1: "Baseline Session",
    2: "Formation Session",
    3: "Verification Session",
}


def project_formation(pathway: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Formation pathway → a restorative state, with the *reason* stripped.

    The pathway's ``reason`` (which can read "voice divergence") and the
    triggering ``submission_id`` never cross the wire. The student sees only the
    developmental step they are on and supportive copy.
    """
    if not pathway:
        return None
    current = int(pathway.get("current_step") or 0)
    total = int(pathway.get("total_steps") or 3)
    status = str(pathway.get("status") or "open")
    completed = status == "completed" or current >= total
    return {
        "active": status == "open" and current < total,
        "status": "completed" if completed else "open",
        "current_step": current,
        "total_steps": total,
        "step_label": _FORMATION_STEP_LABELS.get(min(current + 1, total), "Verification Session")
        if not completed else "Complete",
        "supportive_copy": (
            "Formation complete. Your record reflects the work you put in."
            if completed else
            "A structured, developmental path — three short sessions, each one to "
            "strengthen your writing, not to assess it."
        ),
    }


def project_headline(name: str, arc: List[Dict[str, Any]]) -> Dict[str, str]:
    """A name-addressed, formation-register headline + subhead.

    Derived from the resolved fidelity trend only. No raw numbers other than the
    resolved fidelity already present in the Arc.
    """
    first = (name or "Your").split(" ")[0] or "Your"
    if not arc:
        return {
            "headline": f"{first}, your voice is finding its shape.",
            "subhead": "Submit your first piece of work to reveal your voice profile.",
        }
    latest = arc[-1]["fidelity"]
    grew_by = (arc[-1]["fidelity"] - arc[0]["fidelity"]) if len(arc) >= 2 else 0
    if grew_by >= 8:
        headline = f"{first}, your voice strengthened across this term."
    elif grew_by <= -8:
        headline = f"{first}, your voice is finding its footing."
    else:
        headline = f"{first}, your voice is settling into itself."
    sub = f"Voice fidelity {latest} on your latest piece"
    if grew_by > 0:
        sub += f" — up {grew_by} since the start of term"
    return {"headline": headline, "subhead": sub + "."}


def project_voice_view(
    *,
    name: str,
    baseline_vector: Optional[Dict[str, float]],
    sample_count: int,
    authenticated_count: int,
    manifests: List[Dict[str, Any]],
    corrections: List[Dict[str, Any]],
    pathway: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """Assemble the complete, display-ready VoiceView document.

    This is the only function the ``/me/voice`` endpoint calls. Everything it
    returns is already redacted and formation-register; nothing forbidden by the
    ADR-005 contract is present.
    """
    arc = project_arc(manifests)
    formation = project_formation(pathway)
    formation_completed = bool(formation and formation["status"] == "completed")
    head = project_headline(name, arc)
    return {
        "name": name,
        "headline": head["headline"],
        "subhead": head["subhead"],
        "fingerprint": project_fingerprint(baseline_vector),
        "arc": arc,
        "voice_notes": project_voice_notes(corrections),
        "review_opportunities": project_review_opportunities(manifests),
        "milestones": project_milestones(sample_count, authenticated_count, formation_completed),
        "formation": formation,
    }


# ── POST /me/work : redacted scoring result ──────────────────────────────────

def project_submission_result(layer7: Any, name: str) -> Dict[str, Any]:
    """Project a raw Layer-7 scoring result into the student's formation view.

    Accepts either the Pydantic ``Layer7OutputResponse`` or a plain dict with
    the same shape. Returns only: a headline, supportive summary prose, a few
    "held steady" voice-dimension affirmations (mapped *up* from constructive
    features so no feature name leaks), and whether a review opportunity opened.
    The raw deviation score, action enum, feature vectors, and the technical
    ``human_explanation`` never cross the wire.
    """
    def _get(obj: Any, key: str, default: Any = None) -> Any:
        if obj is None:
            return default
        if isinstance(obj, dict):
            return obj.get(key, default)
        return getattr(obj, key, default)

    recommendation = _get(layer7, "recommendation")
    action = _get(recommendation, "action", "no_action") or "no_action"
    diverges = action != "no_action"

    if not diverges:
        headline = "This reads like you."
        summary = (
            "Your established voice comes through clearly here — in your sentence "
            "rhythm, your vocabulary, the way you build an argument. This piece sits "
            "comfortably within your body of work."
        )
    elif action == "monitor":
        headline = "Mostly your voice, with a few new notes."
        summary = (
            "Most of this reads like your established writing. A few passages stretch "
            "in new directions — often a sign of growth, sometimes just a different "
            "day at the desk."
        )
    else:
        headline = "Some passages here read differently from your voice."
        summary = (
            "Parts of this piece diverge from your established voice. That is worth "
            "revisiting — not a verdict, an invitation to look again. A formation "
            "pathway is available if you would like a structured way through it."
        )

    # Map the constructive (steady) features up into voice-dimension language so
    # the affirmation is personal without naming any tracked feature. We invert
    # VOICE_DIMENSIONS into code→dimension and report the distinct dimensions
    # that held steady.
    code_to_dim: Dict[str, str] = {}
    for dim, codes in VOICE_DIMENSIONS:
        for c in codes:
            code_to_dim.setdefault(c, dim)

    interference = _get(layer7, "interference")
    constructive = _get(interference, "constructive_features", []) or []
    steady_dims: List[str] = []
    for fc in constructive:
        code = _get(fc, "code")
        dim = code_to_dim.get(code)
        if dim and dim not in steady_dims:
            steady_dims.append(dim)
        if len(steady_dims) >= 3:
            break
    steady = [f"Your {d.lower()} is consistent with your established voice." for d in steady_dims]

    return {
        "headline": headline,
        "summary": summary,
        "steady": steady,
        "review_opportunity": diverges,
    }
