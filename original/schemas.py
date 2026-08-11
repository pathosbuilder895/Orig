"""
schemas.py — Pydantic request/response models for the FastAPI layer.

The API surface mirrors the Layer 7 output exactly so the frontend
can deserialise with a single fetch() call and no transformation.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

# ── Request models ────────────────────────────────────────────────────────────


class AddSampleRequest(BaseModel):
    """Add an authenticated baseline sample for a student."""

    text: str = Field(..., description="Raw essay text")
    provenance: str = Field(
        "verified", description="'proctored' | 'verified' | 'canvas' | 'unverified'"
    )
    assignment: str = Field("", description="Assignment name/label")
    submitted_at: str = Field("", description="ISO date string e.g. 2025-09-01")
    keystroke_data: dict | None = Field(
        None,
        description="Bbook stylemetry JSON (keystrokes, pauses, revisions, deletionRate, wordCount). "
        "When provided, Tier 17 behavioral biometric features are extracted. "
        "Absent for uploaded papers — Tier 17 defaults to 0.5 (neutral).",
    )
    submission_uuid: str | None = Field(
        None,
        description="Bluebook seal id: when present, an identical text already in the "
        "profile is skipped instead of re-ingested (retried-seal replay guard).",
    )


class ScoreSubmissionRequest(BaseModel):
    """Score a new submission against a student's current baseline."""

    text: str = Field(..., description="Raw essay text of the submission")
    submission_id: str = Field("", description="Optional external ID")
    assignment: str = Field("", description="Assignment name/label")
    submitted_at: str = Field(
        "",
        description="Optional ISO submission date used only by report-only longitudinal analysis.",
    )
    keystroke_data: dict | None = Field(
        None, description="Bbook stylemetry JSON for Tier 17 behavioral biometric scoring."
    )


# ── WS-7 step 2: request models for the former `body: dict` endpoints ─────────
# Each model documents the shape FastAPI already expected implicitly (the
# handlers read the same keys via body.get(...)). Fields that were only
# loosely checked at runtime (e.g. "role must be professor/admin/operator")
# stay as explicit HTTPException(422, ...) checks in the handler — this pass
# is about making the shape itself part of the OpenAPI schema and auto-422
# on missing/mistyped fields, not rewriting business rules.


class AuthLoginRequest(BaseModel):
    """POST /auth/login."""

    email: str = Field(..., description="Staff account email")
    password: str = Field(..., description="Staff account password")


class AuthRegisterRequest(BaseModel):
    """POST /auth/register. Privileged — see _require_guard."""

    email: str = Field(..., description="New staff account email")
    password: str = Field(..., description="New staff account password (min 8 chars)")
    tenant_id: str = Field(..., description="Institution slug this account belongs to")
    role: str = Field("professor", description="'professor' | 'admin' | 'operator'")
    name: str = Field("", description="Display name")


class BluebookCreateExamRequest(BaseModel):
    """POST /bluebook/exams."""

    title: str = Field(..., description="Exam title")
    course: str = Field("", description="Course label")
    # Numeric fields are Optional: the pre-typed dict contract accepted
    # explicit nulls (e2e fixtures and older clients send maxWords: null for
    # "no limit"), and the handler already coerces via _int_or(..., default).
    duration: int | None = Field(90, description="Exam duration in minutes")
    # camelCase mirrors the JSON keys the Bluebook frontend already sends
    # (same rationale as the file-wide N815 ignore for bbook_client.py).
    minWords: int | None = Field(0, description="Minimum required word count")  # noqa: N815
    maxWords: int | None = Field(0, description="Maximum allowed word count (0/null = unlimited)")  # noqa: N815
    prompt: str = Field("", description="Exam prompt text")
    conditions: dict = Field(default_factory=dict, description="Arbitrary exam-condition metadata")
    status: str = Field("DRAFT", description="Exam status label")


class BluebookRecordSubmissionRequest(BaseModel):
    """POST /bluebook/submissions."""

    exam_id: str | None = Field(None, description="Associated exam id, if any")
    student_id: str = Field("", description="Bluebook student identifier")
    candidate: str = Field("", description="Candidate display name")
    exam_title: str = Field("", description="Denormalised exam title for the Results view")
    course: str = Field("", description="Course label")
    # Optional for the same null-tolerance reason as the exam model above;
    # the handler coerces via _int_or(..., 0).
    word_count: int | None = Field(0, description="Submission word count")
    time_min: int | None = Field(0, description="Time taken, in minutes")
    stylometric: int | None = Field(None, description="Stylometric integrity score, 0-100")
    ai_score: int | None = Field(None, description="AI-likelihood score, 0-100")
    status: str = Field("SUBMITTED", description="Submission status label")
    submission_uuid: str | None = Field(
        None, description="Client seal id; replays return the prior result instead of re-writing"
    )


class BluebookStartSessionRequest(BaseModel):
    """POST /bluebook/exams/{exam_id}/session — begin (or resume) a sitting."""

    student_id: str = Field("", description="Resolved Original student id, when known")
    candidate: str = Field("", description="Candidate email/label fallback for demo sittings")


class BluebookSessionResponse(BaseModel):
    exam_id: str
    started_at: str
    deadline_at: str
    server_now: str
    duration_seconds: int


class BluebookCreateCourseRequest(BaseModel):
    """POST /bluebook/courses."""

    name: str = Field(..., description="Course name")
    code: str = Field("", description="Course code")
    term: str = Field("", description="Academic term label")
    status: str = Field("ACTIVE", description="Course status label")


class CreateTenantRequest(BaseModel):
    """POST /tenants. See create_tenant() for the downgrade-protection business rule."""

    tenant_id: str = Field(..., description="Stable slug, e.g. 'seminary-of-dallas'")
    name: str = Field(..., description="Human-readable institution name")
    environment: str = Field("demo", description="'demo' | 'pilot' | 'production'")
    meta: dict | None = Field(
        None,
        description="Arbitrary metadata (contact email, LMS URL, etc.) — capped at 10 keys, "
        "values coerced to strings ≤ 500 chars.",
    )


class StudentLoginRequest(BaseModel):
    """POST /student-auth/login."""

    email: str = Field(..., description="Student email")
    institution: str = Field(..., description="Institution name")
    name: str = Field("", description="Display name")


class DemoLoginRequest(BaseModel):
    """POST /api/v1/auth/login. Demo-only — 404s on real deploys."""

    email: str = Field("", description="Demo email (role inferred from substring)")
    username: str = Field("", description="Alternate to email")
    password: str = Field("", description="Compared against MAINTENANCE_TOKEN for admin escalation")


# ── T8: QR phone-park (proctoring deterrence) ────────────────────────────────
#
# PRIVACY: the request bodies below are the *complete* set of fields the
# phone-park surface accepts. There is no field for an IP, a user-agent, a
# location, a device fingerprint, or any roster identifier, and the handlers in
# routers/proctor.py never read one off the request either.


class ParkOpenRequest(BaseModel):
    """POST /proctor/park/open — a professor opens a phone-park for one sitting."""

    exam_session_id: str = Field(
        ...,
        description="The professor's own label for this exam sitting, e.g. 'ST501-final-2026'. "
        "Not a roster id and not derived from one.",
    )


class ParkBeatRequest(BaseModel):
    """POST /proctor/park/beat — one heartbeat from a parked phone.

    Posted by an unauthenticated phone: the ``park_token`` (scanned from the
    QR code) is the capability, which is why it is a 128-bit
    ``secrets.token_urlsafe`` value rather than a guessable id.
    """

    park_token: str = Field(..., description="Opaque token scanned from the QR code")
    student_hint: str = Field(
        ...,
        description="Free text the STUDENT types on their own phone (initials, a nickname) so a "
        "proctor can tell one tile from another. Never one of our student ids, never an "
        "email. Trimmed; max 64 chars; empty is rejected.",
    )
    state: str = Field(
        ...,
        description="'parked' | 'foreground_lost' | 'resumed' — page-visibility, nothing more",
    )


# ── PR 7: admin / dashboard / playground / corrections ───────────────────────


class ManifestListItem(BaseModel):
    """One row in the admin manifest audit log."""

    submission_id: str
    student_id: str
    created_at: str
    divergence_score: float | None = None
    action: str | None = None
    flags: list[str]
    anchor_tiers: list[int]
    length_regime: str


class ManifestListResponse(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[ManifestListItem]


class ManifestStatsResponse(BaseModel):
    """Aggregate roll-ups for the admin context dashboard summary cards."""

    total: int
    by_action: dict[str, int]  # e.g. {"no_action": 312, "monitor": 47, ...}
    by_flag: dict[str, int]  # {"software_mediated": 12, "code_switched": 3, ...}
    by_length_regime: dict[str, int]  # {"micro": 4, "short": 18, ...}
    mean_divergence: float | None = None
    since: str | None = None
    until: str | None = None


class CorrectionRequest(BaseModel):
    """Instructor feedback on a scoring verdict (PR 7 → drives PR 8 retraining)."""

    is_correct: bool = Field(
        ...,
        description="True if the original verdict was correct; False if it should be changed.",
    )
    corrected_verdict: str | None = Field(
        None,
        description='Optional: "authentic" | "uncertain" | "anomalous"',
    )
    corrected_action: str | None = Field(
        None,
        description='Optional: "no_action" | "monitor" | "schedule_conversation" | "escalate"',
    )
    reviewer: str | None = Field(None, description="Reviewer identity (e.g. instructor user id)")
    notes: str | None = Field(None, description="Free-text rationale for the correction")


class CorrectionResponse(BaseModel):
    id: int
    submission_id: str
    student_id: str | None = None
    original_verdict: str | None = None
    original_action: str | None = None
    original_divergence_score: float | None = None
    corrected_verdict: str | None = None
    corrected_action: str | None = None
    is_correct: bool
    reviewer: str | None = None
    notes: str | None = None
    created_at: str


class CorrectionListResponse(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[CorrectionResponse]


# ── PR 8: calibration lab ────────────────────────────────────────────────────


class DatasetInfo(BaseModel):
    """One row in the dataset registry exposed to the lab UI."""

    label: str
    name: str
    description: str
    author_filter: list[str]
    requires_build: bool = False
    build_cmd: str = ""


class CalibrationRunRequest(BaseModel):
    """Body of POST /admin/calibration/run."""

    dataset_label: str = Field(
        ...,
        description="One of the labels returned by /admin/lab/datasets",
    )
    run_label: str | None = Field(
        None,
        description="Optional human-readable name for this run (shown in the runs table).",
    )
    max_scoring: int | None = Field(
        None,
        ge=1,
        le=500,
        description="Cap scoring entries per author (smaller = faster). None = no cap.",
    )
    thresholds: dict[str, float] | None = Field(
        None,
        description="Override action thresholds. Defaults to no_action=0.4, monitor=0.55, escalate=0.75.",
    )


class CalibrationRunSummary(BaseModel):
    """Lightweight row for the runs-list table."""

    id: int
    run_label: str | None = None
    dataset_label: str
    started_at: str
    completed_at: str | None = None
    status: str
    auc: float | None = None
    n_essays_scored: int | None = None
    n_authors: int | None = None
    error: str | None = None


class CalibrationRunDetail(BaseModel):
    """Full run with the heavy report JSON."""

    id: int
    run_label: str | None = None
    dataset_label: str
    started_at: str
    completed_at: str | None = None
    status: str
    auc: float | None = None
    n_essays_scored: int | None = None
    n_authors: int | None = None
    config: dict[str, Any]
    error: str | None = None
    report: dict[str, Any] | None = None


class CalibrationRunListResponse(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[CalibrationRunSummary]


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
    target: str | None = None
    current_value: float | None = None
    suggested_value: float | None = None
    expected_improvement: dict[str, Any] | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class SuggestionsResponse(BaseModel):
    suggestions: list[SuggestionItem]
    summary: dict[str, Any]


class ApplyThresholdsRequest(BaseModel):
    """Body of POST /admin/calibration/runs/{id}/apply."""

    no_action: float = Field(..., ge=0.0, le=1.0)
    monitor: float = Field(..., ge=0.0, le=1.0)
    escalate: float = Field(..., ge=0.0, le=1.0)
    verdict_authentic_below: float | None = Field(None, ge=0.0, le=1.0)
    verdict_anomalous_at_or_above: float | None = Field(None, ge=0.0, le=1.0)
    notes: str | None = None


class TunedThresholdsRecord(BaseModel):
    id: int
    created_at: str
    source: str
    source_run_id: int | None = None
    no_action: float
    monitor: float
    escalate: float
    verdict_authentic_below: float | None = None
    verdict_anomalous_at_or_above: float | None = None
    notes: str | None = None
    provenance: dict[str, Any] | None = None


class TunedThresholdsListResponse(BaseModel):
    total: int
    limit: int
    offset: int
    items: list[TunedThresholdsRecord]


class TestScoreRequest(BaseModel):
    """
    Playground request — runs the full adaptive pipeline against an inline
    submission + inline baselines, with no DB persistence. The flags
    default to `True` so callers see the full output regardless of the
    server's env-var configuration.
    """

    text: str = Field(..., description="Submission text")
    baseline_texts: list[str] = Field(
        default_factory=list,
        description="Inline baseline texts (1–10). Synthetic StudentState built from these.",
    )
    keystroke_data: dict | None = Field(
        None, description="Optional Bbook stylemetry JSON for Tier 17."
    )
    enable_manifest: bool = Field(True, description="Run resolvers + build manifest.")
    enable_adaptive_weights: bool = Field(
        True,
        description="Build adaptive weight vector and use it in scoring.",
    )
    enable_blend: bool = Field(
        False,
        description="Also run sliding-window blend detection on the submission.",
    )
    submission_id: str = Field("playground", description="Audit identity (not persisted).")


class TestScoreResponse(BaseModel):
    """
    Playground response — bundles everything the adaptive pipeline produces
    on a single request. Optional fields stay None when their respective
    enable flag was False.
    """

    layer7: Layer7OutputResponse
    blend: BlendResultOut | None = None  # forward-ref OK; defined later in this file


class DriftResultOut(BaseModel):
    """
    Phase 8: per-sample drift assessment returned by baseline-ingestion
    endpoints when a candidate sample's anchor-tier deviation exceeds the
    threshold. The endpoint returns 202 (flag_for_review) or 409
    (rebaseline) carrying this body so the caller can decide what to do.
    """

    drift_detected: bool
    drift_magnitude: float
    anchor_tier_deviations: dict[str, float]  # str-keyed for JSON safety
    recommendation: str  # "accept" | "flag_for_review" | "rebaseline"
    consecutive_drift_count: int


class DriftPendingResponse(BaseModel):
    """202 response — sample held for instructor review (NOT added to state)."""

    status: str  # "pending_review"
    student_id: str
    drift: DriftResultOut


class DriftRebaselineResponse(BaseModel):
    """409 response — consecutive drift suggests the baseline is stale."""

    status: str  # "rebaseline_required"
    student_id: str
    drift: DriftResultOut


class BlendDetectionRequest(BaseModel):
    """Sliding-window blend detection on a single submission."""

    text: str = Field(..., description="Raw essay text of the submission")
    submission_id: str = Field("", description="Optional external ID")
    window_tokens: int = Field(
        300,
        ge=50,
        le=2000,
        description="Token budget per window. Default 300 (small enough to "
        "localise mid-document shifts; T7 features are 'low' "
        "confidence below 500-token windows).",
    )
    overlap: float = Field(
        0.5,
        ge=0.0,
        lt=1.0,
        description="Fraction of overlap between consecutive windows in [0, 1).",
    )


class WindowScoreOut(BaseModel):
    """One sliding-window deviation score (Phase 7)."""

    start: int  # token offset (inclusive)
    end: int  # token offset (exclusive)
    score: float  # authorship deviation_score in [0, 1]
    confidence: str  # "low" | "medium"


class BlendResultOut(BaseModel):
    """Aggregated blend-detection result for a single submission (Phase 7)."""

    blend_detected: bool
    blend_index: float  # 0.0 uniform → 1.0 maximally blended
    shift_positions: list[int]  # token offsets of detected transitions
    per_section: list[WindowScoreOut]
    n_tokens: int = 0
    fallback_reason: str | None = None  # e.g. "text_too_short"


# ── Layer 7 response models ───────────────────────────────────────────────────


class AuthorshipSignalOut(BaseModel):
    authorship_probability: float
    deviation_score: float
    # Phase 6 amplitude-based signals — present on
    # quantum.scoring.AuthorshipSignal but NOT currently copied by api.py's
    # _to_response() (WS-7 S9 completeness gap: these are silently dropped
    # today). Added here so this model fully covers the source dataclass;
    # defaults match AuthorshipSignal's own so existing _to_response call
    # sites (which don't pass them) stay valid.
    quantum_fidelity: float = 0.0  # |⟨ψ_b|ψ_s⟩|² ∈ [0,1]; 1.0 = perfectly authentic
    fidelity_conformal_pvalue: float | None = None  # conformal p-value from corrections feedback
    # Relative (claimed-student vs same-tenant impostor pool) deviation.
    # 0.5 = fits either equally; → 0 = distinctly this student's voice;
    # → 1 = fits the peer pool better (suspicious). None unless
    # NULL_MODEL=impostor is set AND the tenant has enough peers with
    # authenticated baselines to fit a pool (see quantum/null_pool.py).
    llr_deviation_score: float | None = None


class TrajectoryConformanceOut(BaseModel):
    direction: str
    alignment: float
    confidence: float
    adjustment_factor: float


class DriftAnalysisOut(BaseModel):
    """Report-only longitudinal analysis; never changes the recommendation."""

    model_config = {"protected_namespaces": ()}

    eligible: bool
    reason: str | None
    selected_model: str
    historical_deviation: float | None
    predicted_current_deviation: float | None
    drift_relief: float | None
    trend_confidence: float
    predictive_improvement: float | None
    sample_count: int
    dated_sample_count: int
    span_days: int
    extrapolation_days: int | None
    change_point_index: int | None
    change_point_evidence: float | None
    interpretation: str
    feature_count: int
    model_version: str


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
    # Present on quantum.scoring.EntanglementAnomaly but NOT currently copied
    # by api.py's _to_response() (WS-7 S9 completeness gap: silently dropped
    # today). Defaults of 0.0 keep existing _to_response call sites (which
    # construct this model without these two kwargs) valid.
    expected_correlation: float = 0.0
    observed_product: float = 0.0
    anomaly_score: float
    label: str


class InterferenceDecompositionOut(BaseModel):
    total_probability: float
    constructive_features: list[FeatureContributionOut]
    destructive_features: list[FeatureContributionOut]
    broken_entanglements: list[EntanglementAnomalyOut]
    tier_breakdown: dict[str, float]


class BaselineConfidenceOut(BaseModel):
    purity: float
    sample_count: int
    authenticated_count: int
    effective_sample_count: float
    trajectory_confidence: float
    # Present on quantum.scoring.BaselineConfidence but NOT currently copied
    # by _to_response() (WS-7 S9 completeness gap: silently dropped today).
    # Von Neumann entropy S = −Tr(ρ log ρ)/log(D) ∈ [0,1]; 0 = pure/consistent
    # baseline, 1 = maximally mixed/low confidence.
    von_neumann_entropy: float = 0.0


class DomainSignalOut(BaseModel):
    theological_register_score: float
    register_anomaly: bool
    confessional_balance: str


class RecommendedActionOut(BaseModel):
    action: str
    confidence: float
    rationale: str


class SentenceTensionOut(BaseModel):
    """One sentence's tension components (mirrors tension_arc.SentenceTension)."""

    index: int
    text: str
    syntactic: float  # S(i)
    logical: float  # L(i)
    cohesion: float  # C(i)
    total: float  # T(i) = α·S + β·L + γ·C
    move_type: str  # Q / C / E / K / R / N


class ParagraphArcOut(BaseModel):
    """One paragraph's tension arc (mirrors tension_arc.ParagraphArc)."""

    index: int
    sentences: list[SentenceTensionOut]
    peak_count: int
    resolved_peaks: int
    resolution_ratio: float  # ρ for this paragraph
    mean_tension: float
    max_tension: float


class TensionArcOut(BaseModel):
    """Catastrophe/eucatastrophe stylometric fingerprint."""

    catastrophe_index: float  # κ = σ(ρ)·(1−μ(ρ))
    resolution_ratio_mean: float  # μ(ρ)
    resolution_ratio_std: float  # σ(ρ)
    mean_tension: float  # μ(T) — AI writing is characteristically flat
    max_tension: float  # max T(i) — AI rarely exceeds 0.22
    authenticity_signal: float | None  # None if no baseline yet
    arc_flag: str  # "authentic" | "ai_typical" | "review" | "insufficient_length"
    arc_flag_reason: str
    tension_series: list[float]  # per-sentence T(i) for chart rendering
    # Present on tension_arc.TensionArcResult but NOT currently copied by
    # api.py's _to_response() (only the summary scalars above are surfaced
    # today — WS-7 S9 completeness gap). Default [] keeps existing
    # _to_response call sites (which don't pass this) valid.
    paragraph_arcs: list[ParagraphArcOut] = []


class ContextManifestOut(BaseModel):
    """
    Phase 3+: auditable record of a submission's resolved context plus the
    derived directives the adaptive layer applies to scoring. Returned only
    when the CONTEXT_MANIFEST_ENABLED env flag is set; absent otherwise so
    the response is byte-identical to Phase 1 by default.
    """

    submission_id: str
    language: dict[str, Any]
    genre: dict[str, Any]
    topic: dict[str, Any]
    length_regime: str
    citations: dict[str, Any]
    composition_mode: dict[str, Any]
    weight_modifications: dict[str, list[str]]
    anchor_tiers: list[int]
    baseline_match: dict[str, Any]
    flags: list[str]
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
    verdict: str  # "authentic" | "uncertain" | "anomalous"
    confidence: str  # "high" | "medium" | "low" | "insufficient_data"
    context_manifest: dict[str, Any]
    anchor_tier_scores: dict[str, float]  # tier index (str-keyed) → consistency
    narrative: str
    flags: list[str]
    baseline_cluster: list[str]


class AiIndicatorOut(BaseModel):
    """One professor-explainable feature driving the AI-likelihood signal."""

    code: str
    label: str
    z: float
    direction: str  # "higher" | "lower"


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

    probability: float  # calibrated p(AI-generated)
    band: str  # "low" | "elevated" | "strong"
    model_version: str
    trained_on: str
    top_indicators: list[AiIndicatorOut] = []


class StyleAuthorshipOut(BaseModel):
    """Peer-aligned same-author evidence; report-only and abstention-capable."""

    model_config = {"protected_namespaces": ()}

    probability_same_author: float
    band: str  # "consistent" | "inconclusive"
    consistent_at_strict_threshold: bool
    strict_threshold: float
    peer_profiles: int
    baseline_samples: int
    model_version: str
    trained_on: str


class FusedScoreOut(BaseModel):
    """Report-only fused stylometric score (original/fusion/); never feeds
    deviation_score, quantum_fidelity, or the recommended action.

    Populated only when FUSED_SCORE_ENABLED=1 AND the expert produced a
    result (not an abstention); null otherwise — preserves the flag-off
    byte-identical contract.
    """

    model_config = {"protected_namespaces": ()}

    fused_log_odds: float
    probability_different_author: float
    band: str  # "consistent" | "inconclusive" | "divergent"
    channels: dict[str, float]
    reference_profiles: int
    baseline_samples: int
    model_version: str
    trained_on: str


class Layer7OutputResponse(BaseModel):
    student_id: str
    submission_id: str
    authorship: AuthorshipSignalOut
    trajectory: TrajectoryConformanceOut
    interference: InterferenceDecompositionOut
    baseline_confidence: BaselineConfidenceOut
    domain: DomainSignalOut
    recommendation: RecommendedActionOut
    tension_arc: TensionArcOut | None
    feature_vector: dict[str, float]
    baseline_vector: dict[str, float]
    catastrophic_drift: bool = False
    catastrophic_drift_rms_z: float = 0.0
    # Phase 3 — populated only when CONTEXT_MANIFEST_ENABLED=1; null otherwise.
    context_manifest: ContextManifestOut | None = None
    # Phase 6 — same gate as context_manifest; report is the human-readable
    # surface, manifest is the structured directive trail.
    report: ScoringReportOut | None = None
    # AI-likelihood — populated only when AI_LIKELIHOOD_ENABLED=1; null otherwise.
    ai_likelihood: AiLikelihoodOut | None = None
    # Modern peer-aligned authorship expert — default-off and action-blind.
    style_authorship: StyleAuthorshipOut | None = None
    # Longitudinal drift — default-off, report-only, and action-blind.
    drift_analysis: DriftAnalysisOut | None = None
    # Report-only fused stylometric score (original/fusion/) — default-off
    # and action-blind; populated only when FUSED_SCORE_ENABLED=1.
    fused_score: FusedScoreOut | None = None
    # Plain-English explanation for professors/instructors
    human_explanation: dict[str, Any] | None = None


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
    baseline_vector: dict[str, float]
    samples: list[SampleSummary]


class BaselineWordStats(BaseModel):
    """Word-count spread across a student's baseline samples."""

    min: int
    median: int
    mean: float
    max: int
    n_below_300: int


class ReadinessResponse(BaseModel):
    """
    Pilot-facing baseline-readiness check (GET /students/{id}/readiness).

    verdict: "ready" (>= 5 authenticated samples AND >= 3 effective),
    "developing" (>= 2 authenticated), else "insufficient". Pure read —
    computed from the same StudentState the score endpoint uses.
    """

    student_id: str
    sample_count: int
    authenticated_count: int
    effective_sample_count: float
    purity: float
    provenance_mix: dict[str, int]
    word_stats: BaselineWordStats | None = None
    verdict: str
    recommendations: list[str]


# ── Student read-model (ADR-005): the redacting VoiceView ─────────────────────
# Every field here is already display-ready and formation-register. The forbidden
# internals (feature codes, raw divergence/deviation, purity, sample counts,
# action enums, thresholds) are projected away server-side in original/voice.py
# and must never appear in these models. tests/test_voice_leak.py is the gate.


class VoiceDimensionOut(BaseModel):
    """One blended, named axis of the Fingerprint radar (never a raw feature)."""

    name: str  # "Cadence", "Diction", …
    value: float = Field(..., ge=0.0, le=1.0)  # blended 0–1, not a feature value


class ArcPointOut(BaseModel):
    """One point on the Voice Arc — resolved fidelity only, no raw math."""

    period: str  # bare date label, client formats it
    fidelity: int = Field(..., ge=0, le=100)  # resolved display metric
    attention: bool  # server decided this is a review opportunity


class VoiceNoteOut(BaseModel):
    """A finished prose note from a tutor — scores/verdicts stripped."""

    note: str
    reviewer: str
    date: str


class ReviewOpportunityOut(BaseModel):
    """A gentle invitation to a conversation — no score, threshold, or enum."""

    invitation_prose: str
    locator: str | None = None


class MilestoneOut(BaseModel):
    """A positive credential as a named milestone — no raw counts."""

    label: str  # "Voice Established"
    state: str  # "reached" | "upcoming"
    blurb: str


class FormationStateOut(BaseModel):
    """Restorative formation state — the pathway 'reason' is never sent."""

    active: bool
    status: str  # "open" | "completed"
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
    fingerprint: list[VoiceDimensionOut]
    arc: list[ArcPointOut]
    voice_notes: list[VoiceNoteOut]
    review_opportunities: list[ReviewOpportunityOut]
    milestones: list[MilestoneOut]
    formation: FormationStateOut | None = None


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
    steady: list[str]
    review_opportunity: bool


# ── Health ────────────────────────────────────────────────────────────────────


class HealthResponse(BaseModel):
    status: str
    feature_dim: int
    students_in_store: int
    # Deployment environment label (demo | pilot | staging | production).
    # Frontends use it to hide demo-only affordances on real deploys.
    environment: str = "demo"
    # Deployed commit SHA. Render injects RENDER_GIT_COMMIT at runtime; "dev"
    # off-platform (local/CI) where no such env var exists.
    commit: str = "dev"
    # Active persistence backend: "sqlite" | "sqlite+shadow" | "postgres".
    # Lets an operator confirm the WS-6 P5 cutover took effect (and roll back
    # by env var if it didn't). See repository.backend_name().
    backend: str = "sqlite"
