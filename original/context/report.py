"""
context/report.py — Phase 6: Auditable scoring report assembly.

Combines a `Layer7Output` (Phase 1 quantum score) with its `ContextManifest`
(Phase 3 directives) and the student's `StudentState` (sample provenance)
into a `ScoringReport` — a single auditable record that answers "what was
the verdict, why those weights, and which baseline samples drove the
comparison?"

The narrative is **template-based, no LLM call**. Fragments live in
`_TEMPLATE_FRAGMENTS` keyed by the manifest condition that triggers them
(software_mediated, code_switched, topic_novelty_high, anchor_only,
length_micro, ...). The narrative builder selects fragments based on the
manifest's flags + length regime + baseline_match state and joins them
into one paragraph.

Verdict mapping uses divergence-score thresholds so the report stays
informative even if the action threshold table is later retuned:

    divergence < 0.30                     → "authentic"
    0.30 ≤ divergence < 0.75              → "uncertain"
    divergence ≥ 0.75                     → "anomalous"

Confidence levels:

    anchor_only fallback                  → "insufficient_data"
    effective_sample_count < 3            → "low"
    effective_sample_count < 6            → "medium"
    otherwise                             → "high"

Both threshold tables are exposed as module constants at the top of the
file so calibration tweaks land in one place.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional

from ..constants import FEATURE_TIER
from ..quantum.professor_narrative import build_professor_explanation


# ── Tunable thresholds ───────────────────────────────────────────────────────

# Divergence-score → verdict thresholds. The 0.30 boundary is conservative
# — well below the current `monitor` action threshold (0.55) — so the
# narrative leans toward "authentic" even when the raw probability is mid-
# range. We treat the report as a human-facing summary: "anomalous" should
# only fire when the math is unambiguous.
VERDICT_AUTHENTIC_BELOW: float = 0.30
VERDICT_ANOMALOUS_AT_OR_ABOVE: float = 0.75

# Confidence-level boundaries on `effective_sample_count`. Aligns with the
# baseline-confidence saturation threshold in `scoring.py:bc.effective`
# (saturates at 5).
CONFIDENCE_LOW_UNDER: int = 3
CONFIDENCE_MEDIUM_UNDER: int = 6


# ── Tier label table — used for human-readable narrative phrasing ────────────

_TIER_LABELS: Dict[int, str] = {
    1:  "lexical-density",
    2:  "syntactic",
    3:  "rhetorical",
    4:  "char/punctuation",
    5:  "perplexity",
    6:  "idiosyncratic",
    7:  "distributional",
    8:  "tension-arc",
    9:  "argumentative",
    10: "semantic",
    11: "error-ecology",
    12: "catastrophe",
    13: "prosodic-depth",
    14: "error-topology",
    15: "register",
    16: "citation-fingerprint",
    17: "behavioural-biometric",
}


# ══════════════════════════════════════════════════════════════════════════════
# Narrative template fragments
# ══════════════════════════════════════════════════════════════════════════════

# Keyed by a string token derived from manifest state. The narrative builder
# walks the keys in declaration order so the output reads consistently.
# Fragments use Python str.format placeholders filled from the report.
_TEMPLATE_FRAGMENTS: Dict[str, str] = {
    # Opening — always emitted
    "opening_with_cluster":
        "Submission {submission_id} scores {divergence:.3f} ({verdict}) against "
        "a context-matched cluster of {n_cluster} baseline sample(s).",
    "opening_anchor_only":
        "Submission {submission_id} scores {divergence:.3f} ({verdict}) under "
        "anchor-only fallback (no contextually-similar baseline samples found).",

    # Anchor-tier consistency — always emitted when anchors exist
    "anchor_summary_uniform":
        "All {n_anchors} anchor tier(s) show consistency above {min_anchor:.2f}.",
    "anchor_summary_split":
        "Anchor tier consistency ranges from {min_anchor:.2f} ({weakest_label}) "
        "to {max_anchor:.2f} ({strongest_label}).",

    # Manifest flag fragments — appended when the flag is set
    "software_mediated":
        "Tool-cleaning signals are present (T11/T14 attenuated); "
        "the prose error topology has been treated as less reliable.",
    "code_switched":
        "Multilingual segments detected (>5% non-primary language).",
    "topic_novelty_high":
        "The topic is unusually novel relative to the baseline corpus "
        "(T10/T15 attenuated).",

    # Length-regime fragments
    "length_micro":
        "The submission is in the `micro` length regime (<150 tokens); "
        "most distributional tiers were muted.",
    "length_short":
        "The submission is in the `short` length regime; T7 distributional "
        "features were muted and T1.type_token_ratio attenuated.",

    # Citation fragments
    "citations_present":
        "Citations are present, so T16 (citation fingerprint) was promoted "
        "to anchor status.",
    "citations_absent":
        "No citations detected; T16 was muted.",

    # Confidence
    "confidence_insufficient":
        "Confidence in this verdict is `insufficient_data` — anchor-only "
        "fallback engaged; treat the divergence score as indicative only.",
    "confidence_low":
        "Confidence is `low` (effective sample count < {low_under}).",
    "confidence_medium":
        "Confidence is `medium`.",
    "confidence_high":
        "Confidence is `high`.",
}


# ══════════════════════════════════════════════════════════════════════════════
# ScoringReport dataclass
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class ScoringReport:
    """
    Auditable scoring summary built from a Layer7Output + ContextManifest.

    Returned alongside the standard Layer7OutputResponse when a manifest
    was built (i.e. CONTEXT_MANIFEST_ENABLED=1). All fields are JSON-safe.
    """
    submission_id: str
    divergence_score: float
    verdict: str                                 # "authentic" | "uncertain" | "anomalous"
    confidence: str                              # "high" | "medium" | "low" | "insufficient_data"
    context_manifest: Dict[str, Any]
    anchor_tier_scores: Dict[int, float]         # tier → consistency in [0, 1]
    narrative: str
    flags: List[str]
    baseline_cluster: List[str]                  # assignment labels (or "sample_<i>" fallback)
    professor_explanation: Optional[Dict[str, Any]] = field(default=None)

    def to_dict(self) -> Dict[str, Any]:
        # asdict() handles nested dataclasses naturally; we ensure the
        # tier-keyed dict's keys are JSON-friendly strings.
        d = asdict(self)
        d["anchor_tier_scores"] = {str(k): v for k, v in self.anchor_tier_scores.items()}
        return d


# ══════════════════════════════════════════════════════════════════════════════
# Internal helpers
# ══════════════════════════════════════════════════════════════════════════════

def _verdict_for(divergence: float) -> str:
    """Map divergence_score → verdict label."""
    if divergence < VERDICT_AUTHENTIC_BELOW:
        return "authentic"
    if divergence >= VERDICT_ANOMALOUS_AT_OR_ABOVE:
        return "anomalous"
    return "uncertain"


def _confidence_for(layer7: "object", anchor_only: bool) -> str:
    """Map effective_sample_count + anchor_only flag → confidence label."""
    if anchor_only:
        return "insufficient_data"
    bc = getattr(layer7, "baseline_confidence", None)
    eff = getattr(bc, "effective_sample_count", 0.0) if bc is not None else 0.0
    if eff < CONFIDENCE_LOW_UNDER:
        return "low"
    if eff < CONFIDENCE_MEDIUM_UNDER:
        return "medium"
    return "high"


def _anchor_consistency(
    layer7: "object",
    anchor_tiers: List[int],
) -> Dict[int, float]:
    """
    Per-anchor-tier consistency score in [0, 1].

    For each anchor tier, average ``1 − |sub_i − base_i|`` over the codes in
    that tier. ``feature_vector`` and ``baseline_vector`` on Layer7Output are
    already normalised to [0, 1], so the difference is in [0, 1] and the
    consistency score is in [0, 1] (1 = perfect match; 0 = orthogonal).

    Tiers with no codes in the feature vector (e.g. tier 17 when keystroke
    data is absent) are silently skipped rather than reported as 0 — that
    would conflate "no signal" with "anomalous".
    """
    feat = getattr(layer7, "feature_vector", {}) or {}
    base = getattr(layer7, "baseline_vector", {}) or {}

    # Build tier → list of codes lookup once.
    tier_codes: Dict[int, List[str]] = {}
    for code, tier in FEATURE_TIER.items():
        tier_codes.setdefault(tier, []).append(code)

    out: Dict[int, float] = {}
    for tier in anchor_tiers:
        codes = tier_codes.get(tier, [])
        deltas: List[float] = []
        for code in codes:
            if code in feat and code in base:
                deltas.append(abs(float(feat[code]) - float(base[code])))
        if deltas:
            out[tier] = round(1.0 - sum(deltas) / len(deltas), 4)
    return out


def _baseline_cluster_labels(manifest: "object", state: "object") -> List[str]:
    """Resolve manifest.baseline_match.cluster_indices → assignment labels."""
    # manifest may be ContextManifest or its to_dict()
    if isinstance(manifest, dict):
        bm = manifest.get("baseline_match") or {}
    else:
        bm = getattr(manifest, "baseline_match", None) or {}
    indices = bm.get("cluster_indices") or []
    samples = getattr(state, "samples", None) or []
    out: List[str] = []
    for i in indices:
        if 0 <= i < len(samples):
            label = (samples[i].assignment or "").strip()
            out.append(label if label else f"sample_{i}")
    return out


def _flatten_flags(manifest: "object") -> List[str]:
    if isinstance(manifest, dict):
        return list(manifest.get("flags") or [])
    return list(getattr(manifest, "flags", None) or [])


# ══════════════════════════════════════════════════════════════════════════════
# Narrative builder
# ══════════════════════════════════════════════════════════════════════════════

def generate_narrative(
    manifest: "object",
    layer7: "object",
    *,
    anchor_tier_scores: Optional[Dict[int, float]] = None,
    baseline_cluster: Optional[List[str]] = None,
    confidence: Optional[str] = None,
    verdict: Optional[str] = None,
) -> str:
    """
    Compose a human-readable narrative paragraph from manifest + Layer7Output.

    Pure template assembly — no LLM, no randomness, deterministic for a
    given input. Optional precomputed slots can be passed in to avoid
    duplicating work when called from `build_report`.
    """
    # ── Pull out manifest pieces (tolerating dict OR dataclass) ──────────────
    if isinstance(manifest, dict):
        manifest_dict = manifest
    else:
        manifest_dict = manifest.to_dict() if hasattr(manifest, "to_dict") \
                        else getattr(manifest, "__dict__", {})

    flags = manifest_dict.get("flags") or []
    length_regime = manifest_dict.get("length_regime") or ""
    citations = manifest_dict.get("citations") or {}
    baseline_match = manifest_dict.get("baseline_match") or {}
    anchor_tiers = manifest_dict.get("anchor_tiers") or []

    # Submission identity + score
    submission_id = (
        manifest_dict.get("submission_id")
        or getattr(layer7, "submission_id", "unknown")
    )
    divergence = float(getattr(layer7.authorship, "deviation_score", 0.0))
    verdict = verdict or _verdict_for(divergence)
    anchor_only = bool(baseline_match.get("anchor_only"))
    n_cluster = int(baseline_match.get("n_samples") or 0)

    parts: List[str] = []

    # ── Opening sentence ─────────────────────────────────────────────────────
    if anchor_only:
        parts.append(_TEMPLATE_FRAGMENTS["opening_anchor_only"].format(
            submission_id=submission_id, divergence=divergence, verdict=verdict,
        ))
    else:
        parts.append(_TEMPLATE_FRAGMENTS["opening_with_cluster"].format(
            submission_id=submission_id, divergence=divergence, verdict=verdict,
            n_cluster=n_cluster,
        ))

    # ── Anchor-tier consistency summary ──────────────────────────────────────
    scores = anchor_tier_scores or _anchor_consistency(layer7, anchor_tiers)
    if scores:
        vals = list(scores.values())
        n_anchors = len(vals)
        min_v = min(vals)
        max_v = max(vals)
        # If they're tightly clustered, use the "uniform" template; otherwise
        # the "split" template highlights the weakest + strongest tier.
        if max_v - min_v < 0.10:
            parts.append(_TEMPLATE_FRAGMENTS["anchor_summary_uniform"].format(
                n_anchors=n_anchors, min_anchor=min_v,
            ))
        else:
            weakest_tier = min(scores, key=scores.get)
            strongest_tier = max(scores, key=scores.get)
            parts.append(_TEMPLATE_FRAGMENTS["anchor_summary_split"].format(
                min_anchor=min_v, max_anchor=max_v,
                weakest_label=_TIER_LABELS.get(weakest_tier, f"tier{weakest_tier}"),
                strongest_label=_TIER_LABELS.get(strongest_tier, f"tier{strongest_tier}"),
            ))

    # ── Length regime (only emit non-default regimes) ────────────────────────
    if length_regime == "micro":
        parts.append(_TEMPLATE_FRAGMENTS["length_micro"])
    elif length_regime == "short":
        parts.append(_TEMPLATE_FRAGMENTS["length_short"])

    # ── Citations ────────────────────────────────────────────────────────────
    if citations.get("citations_present") is True:
        parts.append(_TEMPLATE_FRAGMENTS["citations_present"])
    elif citations.get("citations_present") is False:
        parts.append(_TEMPLATE_FRAGMENTS["citations_absent"])

    # ── Manifest flags ───────────────────────────────────────────────────────
    # Walk a fixed order so the narrative reads consistently.
    for flag in ("software_mediated", "code_switched", "topic_novelty_high"):
        if flag in flags and flag in _TEMPLATE_FRAGMENTS:
            parts.append(_TEMPLATE_FRAGMENTS[flag])

    # ── Confidence statement (always last) ───────────────────────────────────
    conf = confidence or _confidence_for(layer7, anchor_only)
    if conf == "insufficient_data":
        parts.append(_TEMPLATE_FRAGMENTS["confidence_insufficient"])
    elif conf == "low":
        parts.append(_TEMPLATE_FRAGMENTS["confidence_low"].format(
            low_under=CONFIDENCE_LOW_UNDER,
        ))
    elif conf == "medium":
        parts.append(_TEMPLATE_FRAGMENTS["confidence_medium"])
    else:
        parts.append(_TEMPLATE_FRAGMENTS["confidence_high"])

    return " ".join(parts)


# ══════════════════════════════════════════════════════════════════════════════
# Public builder
# ══════════════════════════════════════════════════════════════════════════════

def build_report(
    layer7: "object",
    manifest: "object",
    state: "object",
    n_tokens: Optional[int] = None,
) -> ScoringReport:
    """
    Assemble a `ScoringReport` from a Layer7Output + ContextManifest + StudentState.

    The manifest's directives drive which anchor tiers are scored, which
    flags are surfaced, and which baseline-cluster labels appear in the
    report. Layer7Output supplies the divergence score and per-feature
    deltas; StudentState is consulted only for resolving the cluster's
    sample assignment labels.
    """
    # Normalise the manifest input to a dict for stable downstream handling.
    if hasattr(manifest, "to_dict"):
        manifest_dict = manifest.to_dict()
    elif isinstance(manifest, dict):
        manifest_dict = manifest
    else:
        manifest_dict = {}

    submission_id = manifest_dict.get("submission_id") or \
                    getattr(layer7, "submission_id", "unknown")
    divergence = float(getattr(layer7.authorship, "deviation_score", 0.0))
    anchor_tiers = manifest_dict.get("anchor_tiers") or []
    flags = manifest_dict.get("flags") or []
    baseline_match = manifest_dict.get("baseline_match") or {}
    anchor_only = bool(baseline_match.get("anchor_only"))

    verdict = _verdict_for(divergence)
    confidence = _confidence_for(layer7, anchor_only)
    anchor_scores = _anchor_consistency(layer7, anchor_tiers)
    cluster_labels = _baseline_cluster_labels(manifest_dict, state)

    narrative = generate_narrative(
        manifest_dict, layer7,
        anchor_tier_scores=anchor_scores,
        baseline_cluster=cluster_labels,
        confidence=confidence,
        verdict=verdict,
    )

    # Professor-facing explanation — deterministic template assembly, no LLM.
    # Catch any exception so a narrative bug never breaks the scoring pipeline.
    professor_explanation: Optional[Dict[str, Any]] = None
    try:
        from dataclasses import asdict as _asdict
        prof_expl = build_professor_explanation(layer7, student_name="this student",
                                                n_tokens=n_tokens)
        professor_explanation = _asdict(prof_expl)
    except Exception:
        pass

    return ScoringReport(
        submission_id=submission_id,
        divergence_score=round(divergence, 4),
        verdict=verdict,
        confidence=confidence,
        context_manifest=manifest_dict,
        anchor_tier_scores=anchor_scores,
        narrative=narrative,
        flags=list(flags),
        baseline_cluster=cluster_labels,
        professor_explanation=professor_explanation,
    )


__all__ = [
    "ScoringReport",
    "build_report",
    "generate_narrative",
    "VERDICT_AUTHENTIC_BELOW",
    "VERDICT_ANOMALOUS_AT_OR_ABOVE",
    "CONFIDENCE_LOW_UNDER",
    "CONFIDENCE_MEDIUM_UNDER",
]
