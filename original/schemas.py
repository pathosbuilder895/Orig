"""
schemas.py — Pydantic request/response models for the FastAPI layer.

The API surface mirrors the Layer 7 output exactly so the frontend
can deserialise with a single fetch() call and no transformation.
"""

from __future__ import annotations
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


# ── Request models ────────────────────────────────────────────────────────────

class AddSampleRequest(BaseModel):
    """Add an authenticated baseline sample for a student."""
    text: str = Field(..., description="Raw essay text")
    provenance: str = Field(
        "verified",
        description="'proctored' | 'verified' | 'canvas' | 'unverified'"
    )
    assignment: str = Field("", description="Assignment name/label")
    submitted_at: str = Field("", description="ISO date string e.g. 2025-09-01")
    keystroke_data: Optional[Dict] = Field(
        None,
        description="Bbook stylemetry JSON (keystrokes, pauses, revisions, deletionRate, wordCount). "
                    "When provided, Tier 17 behavioral biometric features are extracted. "
                    "Absent for uploaded papers — Tier 17 defaults to 0.5 (neutral)."
    )


class ScoreSubmissionRequest(BaseModel):
    """Score a new submission against a student's current baseline."""
    text: str = Field(..., description="Raw essay text of the submission")
    submission_id: str = Field("", description="Optional external ID")
    assignment: str = Field("", description="Assignment name/label")
    keystroke_data: Optional[Dict] = Field(
        None,
        description="Bbook stylemetry JSON for Tier 17 behavioral biometric scoring."
    )


# ── PR 7: admin / dashboard / playground / corrections ───────────────────────

class ManifestListItem(BaseModel):
    """One row in the admin manifest audit log."""
    submission_id: str
    student_id: str
    created_at: str
    divergence_score: Optional[float] = None
    action: Optional[str] = None
    flags: List[str]
    anchor_tiers: List[int]
    length_regime: str


class ManifestListResponse(BaseModel):
    total: int
    limit: int
    offset: int
    items: List[ManifestListItem]


class ManifestStatsResponse(BaseModel):
    """Aggregate roll-ups for the admin context dashboard summary cards."""
    total: int
    by_action: Dict[str, int]                 # e.g. {"no_action": 312, "monitor": 47, ...}
    by_flag: Dict[str, int]                   # {"software_mediated": 12, "code_switched": 3, ...}
    by_length_regime: Dict[str, int]          # {"micro": 4, "short": 18, ...}
    mean_divergence: Optional[float] = None
    since: Optional[str] = None
    until: Optional[str] = None


class CorrectionRequest(BaseModel):
    """Instructor feedback on a scoring verdict (PR 7 → drives PR 8 retraining)."""
    is_correct: bool = Field(
        ...,
        description="True if the original verdict was correct; False if it should be changed.",
    )
    corrected_verdict: Optional[str] = Field(
        None, description='Optional: "authentic" | "uncertain" | "anomalous"',
    )
    corrected_action: Optional[str] = Field(
        None, description='Optional: "no_action" | "monitor" | "schedule_conversation" | "escalate"',
    )
    reviewer: Optional[str] = Field(None, description="Reviewer identity (e.g. instructor user id)")
    notes: Optional[str] = Field(None, description="Free-text rationale for the correction")


class CorrectionResponse(BaseModel):
    id: int
    submission_id: str
    student_id: Optional[str] = None
    original_verdict: Optional[str] = None
    original_action: Optional[str] = None
    original_divergence_score: Optional[float] = None
    corrected_verdict: Optional[str] = None
    corrected_action: Optional[str] = None
    is_correct: bool
    reviewer: Optional[str] = None
    notes: Optional[str] = None
    created_at: str


class CorrectionListResponse(BaseModel):
    total: int
    limit: int
    offset: int
    items: List[CorrectionResponse]


# ── PR 8: calibration lab ────────────────────────────────────────────────────

class DatasetInfo(BaseModel):
    """One row in the dataset registry exposed to the lab UI."""
    label: str
    name: str
    description: str
    author_filter: List[str]
    requires_build: bool = False
    build_cmd: str = ""


class CalibrationRunRequest(BaseModel):
    """Body of POST /admin/calibration/run."""
    dataset_label: str = Field(
        ..., description="One of the labels returned by /admin/lab/datasets",
    )
    run_label: Optional[str] = Field(
        None, description="Optional human-readable name for this run (shown in the runs table).",
    )
    max_scoring: Optional[int] = Field(
        None, ge=1, le=500,
        description="Cap scoring entries per author (smaller = faster). None = no cap.",
    )
    thresholds: Optional[Dict[str, float]] = Field(
        None, description="Override action thresholds. Defaults to no_action=0.4, monitor=0.55, escalate=0.75.",
    )


class CalibrationRunSummary(BaseModel):
    """Lightweight row for the runs-list table."""
    id: int
    run_label: Optional[str] = None
    dataset_label: str
    started_at: str
    completed_at: Optional[str] = None
    status: str
    auc: Optional[float] = None
    n_essays_scored: Optional[int] = None
    n_authors: Optional[int] = None
    error: Optional[str] = None


class CalibrationRunDetail(BaseModel):
    """Full run with the heavy report JSON."""
    id: int
    run_label: Optional[str] = None
    dataset_label: str
    started_at: str
    completed_at: Optional[str] = None
    status: str
    auc: Optional[float] = None
    n_essays_scored: Optional[int] = None
    n_authors: Optional[int] = None
    config: Dict[str, Any]
    error: Optional[str] = None
    report: Optional[Dict[str, Any]] = None


class CalibrationRunListResponse(BaseModel):
    total: int
    limit: int
    offset: int
    items: List[CalibrationRunSummary]


class CalibrationRunCreatedResponse(BaseModel):
    run_id: int
    status: str
    dataset_label: str


class SuggestionItem(BaseModel):
    """One actionable recommendation from the suggestion engine."""
    type: str
    title: str
    rationale: str
    confidence: float
    target: Optional[str] = None
    current_value: Optional[float] = None
    suggested_value: Optional[float] = None
    expected_improvement: Optional[Dict[str, Any]] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class SuggestionsResponse(BaseModel):
    suggestions: List[SuggestionItem]
    summary: Dict[str, Any]


class ApplyThresholdsRequest(BaseModel):
    """Body of POST /admin/calibration/runs/{id}/apply."""
    no_action: float = Field(..., ge=0.0, le=1.0)
    monitor: float = Field(..., ge=0.0, le=1.0)
    escalate: float = Field(..., ge=0.0, le=1.0)
    verdict_authentic_below: Optional[float] = Field(None, ge=0.0, le=1.0)
    verdict_anomalous_at_or_above: Optional[float] = Field(None, ge=0.0, le=1.0)
    notes: Optional[str] = None


class TunedThresholdsRecord(BaseModel):
    id: int
    created_at: str
    source: str
    source_run_id: Optional[int] = None
    no_action: float
    monitor: float
    escalate: float
    verdict_authentic_below: Optional[float] = None
    verdict_anomalous_at_or_above: Optional[float] = None
    notes: Optional[str] = None
    provenance: Optional[Dict[str, Any]] = None


class TunedThresholdsListResponse(BaseModel):
    total: int
    limit: int
    offset: int
    items: List[TunedThresholdsRecord]


class TestScoreRequest(BaseModel):
    """
    Playground request — runs the full adaptive pipeline against an inline
    submission + inline baselines, with no DB persistence. The flags
    default to `True` so callers see the full output regardless of the
    server's env-var configuration.
    """
    text: str = Field(..., description="Submission text")
    baseline_texts: List[str] = Field(
        default_factory=list,
        description="Inline baseline texts (1–10). Synthetic StudentState built from these.",
    )
    keystroke_data: Optional[Dict] = Field(
        None, description="Optional Bbook stylemetry JSON for Tier 17."
    )
    enable_manifest: bool = Field(True, description="Run resolvers + build manifest.")
    enable_adaptive_weights: bool = Field(
        True, description="Build adaptive weight vector and use it in scoring.",
    )
    enable_blend: bool = Field(
        False, description="Also run sliding-window blend detection on the submission.",
    )
    submission_id: str = Field("playground", description="Audit identity (not persisted).")


class TestScoreResponse(BaseModel):
    """
    Playground response — bundles everything the adaptive pipeline produces
    on a single request. Optional fields stay None when their respective
    enable flag was False.
    """
    layer7: Layer7OutputResponse
    blend: Optional[BlendResultOut] = None        # forward-ref OK; defined later in this file


class DriftResultOut(BaseModel):
    """
    Phase 8: per-sample drift assessment returned by baseline-ingestion
    endpoints when a candidate sample's anchor-tier deviation exceeds the
    threshold. The endpoint returns 202 (flag_for_review) or 409
    (rebaseline) carrying this body so the caller can decide what to do.
    """
    drift_detected: bool
    drift_magnitude: float
    anchor_tier_deviations: Dict[str, float]    # str-keyed for JSON safety
    recommendation: str                         # "accept" | "flag_for_review" | "rebaseline"
    consecutive_drift_count: int


class DriftPendingResponse(BaseModel):
    """202 response — sample held for instructor review (NOT added to state)."""
    status: str                                  # "pending_review"
    student_id: str
    drift: DriftResultOut


class DriftRebaselineResponse(BaseModel):
    """409 response — consecutive drift suggests the baseline is stale."""
    status: str                                  # "rebaseline_required"
    student_id: str
    drift: DriftResultOut


class BlendDetectionRequest(BaseModel):
    """Sliding-window blend detection on a single submission."""
    text: str = Field(..., description="Raw essay text of the submission")
    submission_id: str = Field("", description="Optional external ID")
    window_tokens: int = Field(
        300, ge=50, le=2000,
        description="Token budget per window. Default 300 (small enough to "
                    "localise mid-document shifts; T7 features are 'low' "
                    "confidence below 500-token windows).",
    )
    overlap: float = Field(
        0.5, ge=0.0, lt=1.0,
        description="Fraction of overlap between consecutive windows in [0, 1).",
    )


class WindowScoreOut(BaseModel):
    """One sliding-window deviation score (Phase 7)."""
    start: int                                # token offset (inclusive)
    end: int                                  # token offset (exclusive)
    score: float                              # authorship deviation_score in [0, 1]
    confidence: str                           # "low" | "medium"


class BlendResultOut(BaseModel):
    """Aggregated blend-detection result for a single submission (Phase 7)."""
    blend_detected: bool
    blend_index: float                        # 0.0 uniform → 1.0 maximally blended
    shift_positions: List[int]                # token offsets of detected transitions
    per_section: List[WindowScoreOut]
    n_tokens: int = 0
    fallback_reason: Optional[str] = None     # e.g. "text_too_short"


# ── Layer 7 response models ───────────────────────────────────────────────────

class AuthorshipSignalOut(BaseModel):
    authorship_probability: float
    deviation_score: float


class TrajectoryConformanceOut(BaseModel):
    direction: str
    alignment: float
    confidence: float
    adjustment_factor: float


class FeatureContributionOut(BaseModel):
    code: str
    name: str
    tier: int
    contribution: float
    direction: str
    baseline_value: float
    submission_value: float
    delta: float


class EntanglementAnomalyOut(BaseModel):
    feature_a: str
    feature_b: str
    tier_a: int
    tier_b: int
    anomaly_score: float
    label: str


class InterferenceDecompositionOut(BaseModel):
    total_probability: float
    constructive_features: List[FeatureContributionOut]
    destructive_features: List[FeatureContributionOut]
    broken_entanglements: List[EntanglementAnomalyOut]
    tier_breakdown: Dict[str, float]


class BaselineConfidenceOut(BaseModel):
    purity: float
    sample_count: int
    authenticated_count: int
    effective_sample_count: float
    trajectory_confidence: float


class DomainSignalOut(BaseModel):
    theological_register_score: float
    register_anomaly: bool
    confessional_balance: str


class RecommendedActionOut(BaseModel):
    action: str
    confidence: float
    rationale: str


class TensionArcOut(BaseModel):
    """Catastrophe/eucatastrophe stylometric fingerprint."""
    catastrophe_index: float           # κ = σ(ρ)·(1−μ(ρ))
    resolution_ratio_mean: float       # μ(ρ)
    resolution_ratio_std: float        # σ(ρ)
    mean_tension: float                # μ(T) — AI writing is characteristically flat
    max_tension: float                 # max T(i) — AI rarely exceeds 0.22
    authenticity_signal: Optional[float]  # None if no baseline yet
    arc_flag: str                      # "authentic" | "ai_typical" | "review" | "insufficient_length"
    arc_flag_reason: str
    tension_series: List[float]        # per-sentence T(i) for chart rendering


class ContextManifestOut(BaseModel):
    """
    Phase 3+: auditable record of a submission's resolved context plus the
    derived directives the adaptive layer applies to scoring. Returned only
    when the CONTEXT_MANIFEST_ENABLED env flag is set; absent otherwise so
    the response is byte-identical to Phase 1 by default.
    """
    submission_id: str
    language: Dict[str, Any]
    genre: Dict[str, Any]
    topic: Dict[str, Any]
    length_regime: str
    citations: Dict[str, Any]
    composition_mode: Dict[str, Any]
    weight_modifications: Dict[str, List[str]]
    anchor_tiers: List[int]
    baseline_match: Dict[str, Any]
    flags: List[str]
    created_at: str


class ScoringReportOut(BaseModel):
    """
    Phase 6: auditable human-facing scoring summary.

    Built when a context manifest exists (i.e. CONTEXT_MANIFEST_ENABLED=1).
    Provides verdict + confidence labels + per-anchor-tier consistency +
    template-based narrative + the baseline-cluster sample labels used for
    comparison. None when no manifest was built — preserves Phase 1 contract.
    """
    submission_id: str
    divergence_score: float
    verdict: str                                   # "authentic" | "uncertain" | "anomalous"
    confidence: str                                # "high" | "medium" | "low" | "insufficient_data"
    context_manifest: Dict[str, Any]
    anchor_tier_scores: Dict[str, float]           # tier index (str-keyed) → consistency
    narrative: str
    flags: List[str]
    baseline_cluster: List[str]


class AiIndicatorOut(BaseModel):
    """One professor-explainable feature driving the AI-likelihood signal."""
    code: str
    label: str
    z: float
    direction: str                                 # "higher" | "lower"


class AiLikelihoodOut(BaseModel):
    """
    Corpus-level AI-likelihood (second scoring mode). Report-only: never
    feeds the deviation score or the recommended action.

    Populated only when AI_LIKELIHOOD_ENABLED=1 AND the committed detector
    artifact loaded and validated cleanly; null otherwise — preserves the
    flag-off byte-identical contract. The calibrated probability lives here
    (the auditable structured surface); professor-facing prose stays
    band-only by design.
    """
    probability: float                             # calibrated p(AI-generated)
    band: str                                      # "low" | "elevated" | "strong"
    model_version: str
    trained_on: str
    top_indicators: List[AiIndicatorOut] = []


class Layer7OutputResponse(BaseModel):
    student_id: str
    submission_id: str
    authorship: AuthorshipSignalOut
    trajectory: TrajectoryConformanceOut
    interference: InterferenceDecompositionOut
    baseline_confidence: BaselineConfidenceOut
    domain: DomainSignalOut
    recommendation: RecommendedActionOut
    tension_arc: Optional[TensionArcOut]
    feature_vector: Dict[str, float]
    baseline_vector: Dict[str, float]
    catastrophic_drift: bool = False
    catastrophic_drift_rms_z: float = 0.0
    # Phase 3 — populated only when CONTEXT_MANIFEST_ENABLED=1; null otherwise.
    context_manifest: Optional[ContextManifestOut] = None
    # Phase 6 — same gate as context_manifest; report is the human-readable
    # surface, manifest is the structured directive trail.
    report: Optional[ScoringReportOut] = None
    # AI-likelihood — populated only when AI_LIKELIHOOD_ENABLED=1; null otherwise.
    ai_likelihood: Optional[AiLikelihoodOut] = None
    # Plain-English explanation for professors/instructors
    human_explanation: Optional[Dict[str, Any]] = None


# ── Student state summary ─────────────────────────────────────────────────────

class SampleSummary(BaseModel):
    index: int
    assignment: str
    provenance: str
    submitted_at: str
    auth_weight: float


class StudentStateResponse(BaseModel):
    student_id: str
    sample_count: int
    authenticated_count: int
    purity: float
    effective_sample_count: float
    trajectory_direction: str
    trajectory_confidence: float
    baseline_vector: Dict[str, float]
    samples: List[SampleSummary]


# ── Student read-model (ADR-005): the redacting VoiceView ─────────────────────
# Every field here is already display-ready and formation-register. The forbidden
# internals (feature codes, raw divergence/deviation, purity, sample counts,
# action enums, thresholds) are projected away server-side in original/voice.py
# and must never appear in these models. tests/test_voice_leak.py is the gate.

class VoiceDimensionOut(BaseModel):
    """One blended, named axis of the Fingerprint radar (never a raw feature)."""
    name: str                                    # "Cadence", "Diction", …
    value: float = Field(..., ge=0.0, le=1.0)    # blended 0–1, not a feature value


class ArcPointOut(BaseModel):
    """One point on the Voice Arc — resolved fidelity only, no raw math."""
    period: str                                  # bare date label, client formats it
    fidelity: int = Field(..., ge=0, le=100)     # resolved display metric
    attention: bool                              # server decided this is a review opportunity


class VoiceNoteOut(BaseModel):
    """A finished prose note from a tutor — scores/verdicts stripped."""
    note: str
    reviewer: str
    date: str


class ReviewOpportunityOut(BaseModel):
    """A gentle invitation to a conversation — no score, threshold, or enum."""
    invitation_prose: str
    locator: Optional[str] = None


class MilestoneOut(BaseModel):
    """A positive credential as a named milestone — no raw counts."""
    label: str                                   # "Voice Established"
    state: str                                   # "reached" | "upcoming"
    blurb: str


class FormationStateOut(BaseModel):
    """Restorative formation state — the pathway 'reason' is never sent."""
    active: bool
    status: str                                  # "open" | "completed"
    current_step: int
    total_steps: int
    step_label: str
    supportive_copy: str


class VoiceView(BaseModel):
    """
    The complete student-facing read-model returned by ``GET /me/voice``.

    Resolved entirely server-side by ``original.voice.project_voice_view``. The
    student client renders this directly — it never touches ``/students/{id}``,
    ``/admin/*``, or the raw ``/score`` payload.
    """
    name: str
    headline: str
    subhead: str
    fingerprint: List[VoiceDimensionOut]
    arc: List[ArcPointOut]
    voice_notes: List[VoiceNoteOut]
    review_opportunities: List[ReviewOpportunityOut]
    milestones: List[MilestoneOut]
    formation: Optional[FormationStateOut] = None


class VoiceSubmitRequest(BaseModel):
    """Body of ``POST /me/work`` — the student submits a piece of writing."""
    text: str = Field(..., description="Raw essay text")
    title: str = Field("", description="Assignment title/label")


class VoiceSubmitResult(BaseModel):
    """
    Redacted scoring result returned by ``POST /me/work``.

    Built by ``original.voice.project_submission_result`` from the internal
    Layer-7 output. Carries no deviation score, no action enum, no feature
    vectors, and not the technical ``human_explanation``.
    """
    headline: str
    summary: str
    steady: List[str]
    review_opportunity: bool


# ── Health ────────────────────────────────────────────────────────────────────

class HealthResponse(BaseModel):
    status: str
    feature_dim: int
    students_in_store: int
