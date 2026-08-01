"""
quantum/scoring.py — Born-rule deviation scoring + Layer 7 output.

Core equations
──────────────
  Born probability:  P = ξᵀ ρ ξ         ∈ (0, 1]
  Raw deviation:     D_raw = 1 − P

Trajectory adjustment
─────────────────────
  cos_sim = (δψ · ξ) / (‖δψ‖ ‖ξ‖)
  growth    (cos > +0.25) → D_adj = D_raw × 0.75   (dampened)
  lateral   (|cos| < 0.25) → D_adj = D_raw × 1.0
  regressive(cos < −0.20) → D_adj = D_raw × 1.15   (amplified)

Interference decomposition
──────────────────────────
  Contribution of feature i to Born probability:
      c_i = (ρ ξ)[i] × ξ[i]        (sums to P)

  Expected contribution per feature if uniform: P / D
  Constructive: c_i > P/D (co-varying as expected)
  Destructive:  c_i < P/D (breaking expected pattern)

  Cross-feature entanglement anomaly for pair (i, j):
      expected = ρ[i,j]         (baseline co-variance)
      observed = ξ[i] × ξ[j]   (submission product)
      anomaly  = |expected − observed| × max(|ρ[i,j]|, 0.01)
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from original.ai_likelihood import AiLikelihoodResult
    from original.tension_arc import TensionArcResult

import numpy as np

from ..constants import (
    ACTION_THRESHOLDS,
    ALL_FEATURE_CODES,
    FEATURE_DIM,
    FEATURE_NAMES,
    FEATURE_TIER,
    LENGTH_BUCKETS_BY_TOKENS,
    LENGTH_WEIGHT_SCHEDULE,
    TIER_WEIGHTS,
    TRAJECTORY_GROWTH_THRESHOLD,
    TRAJECTORY_REGRESSIVE_THRESHOLD,
)
from .state import StudentState, _unit

log = logging.getLogger(__name__)

# Submissions under this many words get a provisional-confidence note in the
# recommendation rationale and the professor confidence note. Chosen from the
# length-stability study (validation/stability/): feature discriminability
# degrades sharply below ~300 words. Prose only — never changes the action.
SHORT_SUBMISSION_TOKENS = 300

# Pre-built per-feature tier-weight vector (shape D,) — applied to z-scores
# so that high-identity tiers (6=idiosyncratic, 11=error ecology, 4=char/punct)
# dominate the deviation score over noisier tiers (3=rhetorical, 9=argument).
_TIER_WEIGHT_VECTOR = np.array(
    [TIER_WEIGHTS.get(FEATURE_TIER[code], 1.0) for code in ALL_FEATURE_CODES],
    dtype=np.float64,
)


# ── Length-adaptive scaling (Phase 2 of length-stability work) ───────────────
#
# When LENGTH_ADAPTIVE_WEIGHTS=1, the deviation-score weight vector is
# multiplied by a per-tier factor chosen from the bucket that contains the
# submission's n_tokens. The buckets + factors live in
# original/constants.py:LENGTH_WEIGHT_SCHEDULE; this module just plumbs
# them into the score() math.
#
# Pre-build one length-scale vector per bucket so the per-call cost is a
# single np multiply, not a 103-feature Python loop.
def _build_length_scale_vector(bucket: str) -> np.ndarray:
    factors = LENGTH_WEIGHT_SCHEDULE[bucket]
    return np.array(
        [factors.get(FEATURE_TIER.get(code, 0), 1.0) for code in ALL_FEATURE_CODES],
        dtype=np.float64,
    )


_LENGTH_SCALE_VECTORS: dict[str, np.ndarray] = {
    b: _build_length_scale_vector(b) for b in LENGTH_WEIGHT_SCHEDULE
}


def _length_bucket_for(n_tokens: int) -> str:
    """Map a word count to the matching LENGTH_BUCKETS_BY_TOKENS key."""
    for name, (lo, hi) in LENGTH_BUCKETS_BY_TOKENS.items():
        if lo <= n_tokens < hi:
            return name
    return "long"  # safety net: anything past the last bucket reads as 'long'


# ── Output dataclasses ────────────────────────────────────────────────────────


@dataclass
class FeatureContribution:
    code: str
    name: str
    tier: int
    contribution: float  # normalised contribution to Born prob, can be negative
    direction: str  # "constructive" | "destructive" | "neutral"
    baseline_value: float  # mean feature value in baseline
    submission_value: float  # feature value in submission
    delta: float  # submission − baseline


@dataclass
class EntanglementAnomaly:
    feature_a: str
    feature_b: str
    tier_a: int
    tier_b: int
    expected_correlation: float
    observed_product: float
    anomaly_score: float
    label: str  # human-readable e.g. "T2–T3 discourse-rhetorical"


@dataclass
class InterferenceDecomposition:
    total_probability: float
    constructive_features: list[FeatureContribution]  # top 5
    destructive_features: list[FeatureContribution]  # top 5
    broken_entanglements: list[EntanglementAnomaly]  # top 3
    tier_breakdown: dict[str, float]  # fraction of prob by tier


@dataclass
class AuthorshipSignal:
    authorship_probability: float
    deviation_score: float
    # ── Production Phase 6: amplitude-based signals ───────────────────────────
    # Both default to 0.0/None so existing callers see byte-identical output
    # when AMPLITUDE_SCORING_ENABLED is off.
    quantum_fidelity: float = field(default=0.0)
    # |⟨ψ_b|ψ_s⟩|² ∈ [0,1]; 1.0 = perfectly authentic, 0.0 = anomalous.
    fidelity_conformal_pvalue: float | None = field(default=None)
    # Conformal p-value from corrections feedback loop.
    # None when calibration set is empty (no historical authentic fidelities).
    # ── Rank-and-null work: explicit likelihood-ratio deviation ──────────────
    # None unless NULL_MODEL=impostor is set AND the caller supplied
    # impostor_stats to score(). deviation_score above answers "how far is
    # this from the claimed author's baseline?" (absolute distance).
    # llr_deviation_score answers "how much MORE like the claimed author is
    # this than like a typical OTHER author?" (relative distance — a proper
    # log-likelihood-ratio proxy). 0.5 = as consistent with one as the
    # other; → 1.0 = fits the impostor pool much better than the claimed
    # author (suspicious); → 0.0 = fits the claimed author much better
    # (genuine). See _llr_deviation() for the derivation.
    llr_deviation_score: float | None = field(default=None)


@dataclass
class TrajectoryConformance:
    direction: str
    alignment: float
    confidence: float
    adjustment_factor: float


@dataclass
class BaselineConfidence:
    purity: float
    sample_count: int
    authenticated_count: int
    effective_sample_count: float
    trajectory_confidence: float
    # Von Neumann entropy S = −Tr(ρ log ρ)/log(D) ∈ [0,1].
    # 0 = pure state (consistent baseline, high confidence).
    # 1 = maximally mixed (variable baseline, low confidence).
    von_neumann_entropy: float = field(default=0.0)


@dataclass
class DomainSignal:
    theological_register_score: float
    register_anomaly: bool
    confessional_balance: str  # "confessional" | "critical" | "balanced"


@dataclass
class RecommendedAction:
    action: str  # "no_action"|"monitor"|"schedule_conversation"|"escalate"
    confidence: float
    rationale: str


@dataclass(frozen=True)
class ScoringConfig:
    """
    Every input to ``score()`` that used to be read live from ``os.environ``
    or fetched from ``store`` inside the function body (WS-7 step 1). This is
    the ONE place those six env vars are read (via :meth:`from_env`) — the
    scoring math itself is now a pure function of its arguments.

    ``ScoringConfig()`` (all defaults) reproduces the flags-OFF, no-calibration-
    data Phase 1 behaviour exactly, so a no-arg ``score()`` call stays
    byte-identical. Callers that need live env/store state must build one
    explicitly with :meth:`from_env` and pass persistence lookups in — this
    module never imports ``store`` itself.
    """

    # ── formerly os.environ.get() reads inside score() ────────────────────────
    bayesian_prior_enabled: bool = False  # was BAYESIAN_PRIOR_ENABLED, :512
    prior_weight: float = 3.0  # was PRIOR_WEIGHT, :524
    length_adaptive_weights: bool = False  # was LENGTH_ADAPTIVE_WEIGHTS, :553
    null_model: str = "none"  # was NULL_MODEL, :586
    amplitude_scoring_enabled: bool = False  # was AMPLITUDE_SCORING_ENABLED, :597
    secret_key: str = ""  # was SECRET_KEY, :602
    # How llr_deviation_score (NULL_MODEL=impostor) is allowed to influence
    # the recommended action. "shadow" (default) preserves the attach-only
    # contract byte-for-byte — it only logs what "gate"/"trigger"/"blend"
    # would have decided, never changes `recommendation`. A 2026-08 leave-
    # one-genre-out study (C.S. Lewis corpus vs a Chesterton impostor pool,
    # see validation/genre_crossgenre_2026-08/) found the raw deviation_score
    # alone WORSE than chance (mean AUC 0.39) at telling a genuine cross-
    # genre submission from a different author's writing, while
    # llr_deviation_score alone scored 0.86 — this flag is how that signal
    # graduates from observation to actually changing a verdict, one mode
    # at a time, each independently measurable against real data first.
    #   "shadow"  — log-only, action unchanged (default, current behaviour)
    #   "gate"    — llr may only DOWNGRADE an action one severity step
    #               (targets the genre-driven false-positive failure mode)
    #   "trigger" — llr may only UPGRADE no_action→monitor (adds sensitivity;
    #               not yet validated against a real impostor population)
    #   "blend"   — action tier is re-derived from a 50/50 blend of
    #               deviation_score and llr_deviation_score
    llr_action_mode: str = "shadow"  # was LLR_ACTION_MODE

    # ── formerly call-time `from ..store import ...` ──────────────────────────
    # Confirmed-authentic fidelity scores for this student, for the conformal
    # p-value (was ``store.get_authentic_fidelities(student_id)``).
    authentic_fidelities: list[float] | None = None
    # Cross-student genre prior {"mean": ndarray, "std": ndarray, "n_samples": int}
    # already resolved for the CURRENT submission's genre (was
    # ``store.get_genre_stats(genre, tenant, exclude_student_id)``) — the caller must do the genre
    # and tenant lookups since only it knows which genre applies and which
    # student is being scored before calling score().
    genre_stats: dict | None = None

    @classmethod
    def from_env(cls) -> ScoringConfig:
        """Build a config from the current environment. The ONE place these six vars are read."""
        return cls(
            bayesian_prior_enabled=os.environ.get("BAYESIAN_PRIOR_ENABLED", "0") == "1",
            prior_weight=float(os.environ.get("PRIOR_WEIGHT", "3.0")),
            length_adaptive_weights=os.environ.get("LENGTH_ADAPTIVE_WEIGHTS", "0") == "1",
            null_model=os.environ.get("NULL_MODEL", "none"),
            amplitude_scoring_enabled=os.environ.get("AMPLITUDE_SCORING_ENABLED", "0") == "1",
            secret_key=os.environ.get("SECRET_KEY", ""),
            llr_action_mode=os.environ.get("LLR_ACTION_MODE", "shadow"),
        )


@dataclass
class Layer7Output:
    student_id: str
    submission_id: str

    authorship: AuthorshipSignal
    trajectory: TrajectoryConformance
    interference: InterferenceDecomposition
    baseline_confidence: BaselineConfidence
    domain: DomainSignal
    recommendation: RecommendedAction

    # Raw feature values for UI visualisation
    feature_vector: dict[str, float]  # submission (normalised 0–1)
    baseline_vector: dict[str, float]  # baseline mean (normalised 0–1)

    # ── Item 100: Catastrophic Drift Alert ────────────────────────────────────
    # Fires when RMS z-score across all features exceeds 3 SDs from baseline,
    # overriding the normal action threshold regardless of the deviation score.
    # Signals a submission so unlike prior authentic work that immediate review
    # is warranted independent of any AI-detection signal.
    catastrophic_drift: bool = field(default=False)
    catastrophic_drift_rms_z: float = field(default=0.0)  # raw RMS z-score

    # Tension arc (orthogonal signal, set at API layer after quantum score)
    tension_arc: TensionArcResult | None = field(default=None)

    # Phase 3+: auditable adaptive-context manifest, attached at the API layer
    # after scoring when CONTEXT_MANIFEST_ENABLED=1. Stored as a plain dict
    # (not the dataclass) to keep this module free of an `original.context`
    # import cycle. None when the manifest flag is off — preserves byte-
    # identical Phase 1 responses by default.
    context_manifest: dict[str, object] | None = field(default=None)

    # Corpus-level AI-likelihood (orthogonal signal, set at the API layer
    # after quantum score when AI_LIKELIHOOD_ENABLED=1). Report-only: never
    # feeds the deviation score or the recommended action. None when the
    # flag is off — preserves byte-identical responses by default.
    ai_likelihood: AiLikelihoodResult | None = field(default=None)


# ── Amplitude scoring helper ──────────────────────────────────────────────────


def _amplitude_score(
    state: StudentState,
    z: np.ndarray,
    weight_vec: np.ndarray,
    active: np.ndarray,
    student_id: str,
    submission_id: str,
    n_tokens: int,
    secret_key: str = "",
    baseline_mean_override: np.ndarray | None = None,
    baseline_std_override: np.ndarray | None = None,
    authentic_fidelities: list[float] | None = None,
) -> tuple[float, float | None, dict]:
    """
    Compute quantum fidelity, conformal p-value, and 3-way interference.

    Called inside ``score()`` when AMPLITUDE_SCORING_ENABLED=1.  All imports
    are local so this module has no hard dependency on amplitude/conformal
    modules when the flag is off.

    Parameters
    ----------
    state                  : StudentState with baseline samples
    z                      : shape (D,), already-computed z-scores
    weight_vec             : shape (D,), tier-weight vector
    active                 : shape (D,), bool active-feature mask
    student_id             : used for keyed unitary seed
    submission_id          : used for keyed unitary seed
    n_tokens               : word count of submission text
    secret_key             : HMAC secret (empty → skip unitary projection)
    baseline_mean_override : when set (e.g. Bayesian prior blend), replaces
                             state.baseline_mean inside build_superposition_baseline
    baseline_std_override  : same for state.baseline_std
    authentic_fidelities   : confirmed-authentic fidelity calibration set for
                             this student (``ScoringConfig.authentic_fidelities``),
                             resolved by the caller — this module no longer
                             reaches into ``store`` for it.

    Returns
    -------
    (fidelity, conformal_pvalue_or_None, interference_dict)
    """
    from .amplitude import (
        apply_keyed_projection,
        build_superposition_baseline,
        encode_amplitudes,
        interference_components,
        quantum_fidelity,
    )
    from .conformal import conformal_pvalue

    contributing = [s for s in state.samples if s.auth_weight > 0]

    psi_s = encode_amplitudes(z, weight_vec, active, n_tokens)
    _bsl_mean = (
        baseline_mean_override if baseline_mean_override is not None else state.baseline_mean
    )
    _bsl_std = baseline_std_override if baseline_std_override is not None else state.baseline_std
    psi_b = build_superposition_baseline(
        contributing,
        weight_vec,
        active,
        _bsl_mean,
        _bsl_std,
        n_tokens,
    )

    if secret_key:
        psi_b, psi_s = apply_keyed_projection(psi_b, psi_s, secret_key, student_id, submission_id)

    F = quantum_fidelity(psi_b, psi_s)

    # Conformal p-value — caller-supplied confirmed-authentic fidelities
    # (WS-7 step 1: this module no longer reaches into store directly).
    p_val: float | None = None
    try:
        if authentic_fidelities:
            p_val = conformal_pvalue(F, authentic_fidelities)
    except Exception as exc:
        log.debug("conformal p-value skipped for %s: %s", submission_id, exc)

    components = interference_components(psi_b, psi_s)
    return F, p_val, components


def _llr_deviation(
    sub_raw: np.ndarray,
    impostor_stats: tuple[np.ndarray, np.ndarray],
    weight_vec: np.ndarray,
    active: np.ndarray,
    n_active: int,
    rms_z: float,
) -> float:
    """
    Relative (claimed-author vs impostor-pool) deviation — a bounded,
    monotonic proxy for the log-likelihood ratio

        Λ(X, A) = log P(ξ | H₁, baseline_A) − log P(ξ | H₀, impostor_pool)

    ``rms_z`` (the caller's already-computed distance from the CLAIMED
    author's baseline) plays the role of −2·log P(ξ|H₁) up to a constant.
    This function computes the analogous ``rms_z_null`` — distance from
    the IMPOSTOR POOL's per-feature mean/std, using the exact same
    weighting/capping/active-mask machinery as the primary computation so
    the two numbers are on the same footing — which plays the role of
    −2·log P(ξ|H₀).

    We report a bounded transform of the RMS DIFFERENCE (not the squared
    difference the exact LLR would use) because it reuses the existing
    tanh/1.5 calibration exactly, keeping the well-tested primary
    deviation_score untouched and this new score interpretable on the
    same scale:

        llr_deviation = 0.5 + 0.5·tanh( (rms_z − rms_z_null) / 1.5 )

    0.5   → as consistent with the claimed author as with the impostor
            pool (no information either way)
    → 1.0 → fits the impostor pool much better than the claimed author
            (this text looks like "generic other-author" writing —
            suspicious)
    → 0.0 → fits the claimed author much better than the impostor pool
            (genuinely this author's voice, not just "unremarkable")

    Args:
        sub_raw: raw normalised [0,1] submission feature vector, shape (D,).
        impostor_stats: (mu_null, sigma_null), each shape (D,) — per-feature
            mean/std fit from a cohort of OTHER authors' baseline vectors.
        weight_vec, active, n_active: identical to the values already
            computed for the primary rms_z, so both distances use the same
            tier weighting and the same active-feature mask.
        rms_z: the caller's already-computed distance from the claimed
            author's baseline.
    """
    mu_null, sigma_null = impostor_stats
    sigma_null_floored = np.maximum(sigma_null, 0.005)  # same floor as state.baseline_std
    z_null = (sub_raw - mu_null) / sigma_null_floored
    z_null_capped = np.clip(z_null, -4.0, 4.0)
    z_null_weighted = z_null_capped * weight_vec * active.astype(np.float64)

    if n_active > 0:
        rms_z_null = float(np.sqrt(np.sum(z_null_weighted**2) / n_active))
    else:
        rms_z_null = 0.0

    delta = rms_z - rms_z_null
    return float(np.clip(0.5 + 0.5 * np.tanh(delta / 1.5), 0.0, 1.0))


# ── Main scoring function ─────────────────────────────────────────────────────


def score(
    state: StudentState,
    submission_vector: np.ndarray,
    feature_dict: dict[str, float],
    submission_id: str = "",
    adaptive_weights: np.ndarray | None = None,
    manifest: dict | None = None,
    n_tokens: int = 300,
    impostor_stats: tuple[np.ndarray, np.ndarray] | None = None,
    scoring_config: ScoringConfig | None = None,
) -> Layer7Output:
    """
    Score a submission against a student's current quantum state.

    Parameters
    ----------
    state              : StudentState with at least one authenticated sample
    submission_vector  : normalised feature vector, shape (D,)
    feature_dict       : {code: normalised_value} for all 34 features
    submission_id      : identifier for this submission
    adaptive_weights   : optional per-feature weight vector, shape (FEATURE_DIM,).
                         When supplied, replaces the static ``_TIER_WEIGHT_VECTOR``
                         in the deviation-score computation. Phase 5 builds this
                         from the ContextManifest. None preserves Phase 1.
    manifest           : optional context manifest dict (audit trail). Attached
                         to ``Layer7Output.context_manifest`` for inspection;
                         does not influence scoring math itself — that's the
                         job of ``adaptive_weights``.
    n_tokens           : word count of the submission text. Threads into the
                         Gaussian wave packet reliability factor inside
                         encode_amplitudes so short texts produce proportionally
                         smaller amplitudes — reducing overconfident fidelity
                         scores. Defaults to 300 (≈ median essay length) when
                         not supplied by the caller.
    impostor_stats     : optional (mu_null, sigma_null) per-feature Gaussian,
                         each shape (FEATURE_DIM,), fit from a cohort of
                         OTHER authors' baseline vectors (see
                         validation/verify/null_models.py). Only used when
                         both this is supplied AND NULL_MODEL=impostor is
                         set — populates
                         ``Layer7Output.authorship.llr_deviation_score``, a
                         relative (claimed-author vs impostor-pool)
                         deviation measure alongside the existing absolute
                         ``deviation_score``. None preserves Phase 1
                         byte-identical behaviour; the primary
                         deviation_score / action / recommendation are
                         never touched by this parameter.
    scoring_config     : optional ``ScoringConfig`` (WS-7 step 1). Carries the six
                         flags that used to be read from ``os.environ`` inside this
                         function (bayesian/length-adaptive/null-model/amplitude/
                         secret-key) plus persistence-derived inputs (confirmed-
                         authentic fidelities for the conformal p-value, the
                         resolved genre prior for the Bayesian cold-start blend)
                         that the caller fetches from store. This module never
                         reads ``os.environ`` or imports ``store`` itself; omitting
                         it is exactly the flags-OFF, no-calibration-data Phase 1
                         path (``ScoringConfig()`` defaults).
    """
    config = scoring_config or ScoringConfig()

    xi = _unit(submission_vector)  # ξ  (unit-normalised submission vector)
    rho = state.density_matrix  # ρ

    # ── Born probability (used for interference decomposition) ────────────────
    rho_xi = rho @ xi  # shape (D,)
    P = float(np.clip(float(xi @ rho_xi), 1e-6, 1.0))

    # ── Variance-weighted deviation (primary score) ───────────────────────────
    # 1. Standardise: z = (submission − baseline_mean) / baseline_std
    #    baseline_std is floored at 0.005 (down from 0.05) so tight identity
    #    markers generate proportionally larger z-scores when violated.
    #
    # 2. Active-feature mask: exclude features stuck at 0.5 (no-data placeholder)
    #    from the density matrix.  Dead dimensions (Tier 17 without keystroke
    #    data, Tier 10 without sentence-transformers, etc.) contribute only noise.
    #
    # 3. Tier-weight vector: multiply z by per-tier weights so that high-identity
    #    tiers (6=idiosyncratic 1.4×, 11=error ecology 1.4×, 4=char/punct 1.3×)
    #    dominate over noisier tiers (3=rhetorical 0.8×, 9=argument 0.9×).
    #    The weights already exist in TIER_WEIGHTS; previously only used for
    #    sorting destructive features — now applied to the deviation score itself.
    #
    # 4. tanh divisor reduced 2.5 → 1.0 to spread the usable score range.
    #    Old calibration: rms_z=1.5 → 0.54, rms_z=2.5 → 0.76 (usable band 0.22)
    #    New calibration: rms_z=1.0 → 0.76, rms_z=2.0 → 0.96 (full range used)
    mu = state.baseline_mean  # shape (D,)
    sigma = state.baseline_std  # shape (D,), floored at 0.005
    active = state.active_feature_mask  # shape (D,), bool

    # ── Hierarchical Bayesian prior (cold-start) ──────────────────────────────
    # When a student has few baseline samples, blend their personal mu/sigma
    # with the cross-student genre prior so cold-start z-scores are computed
    # against a less noisy reference distribution.
    #
    # Blend formula:  mu_eff = α·mu_student + (1−α)·mu_prior
    #                 α = N / (N + prior_weight)   (N = student sample count)
    # α → 1 as N grows, so the prior is washed out once enough personal data
    # accumulates. Default prior_weight=3 means 3 authentic baselines = 50%
    # personal / 50% genre prior; 10 baselines = 77% personal / 23% prior.
    #
    # Gated by config.bayesian_prior_enabled (default OFF) to preserve
    # Phase 1 byte-identical behaviour for existing callers.
    if config.bayesian_prior_enabled and state.sample_count < 10:
        try:
            _genre = (
                state.samples[-1].genre
                if state.samples and getattr(state.samples[-1], "genre", None)
                else None
            )
            # Caller resolves the genre-stats lookup (WS-7 step 1: this
            # module no longer imports store directly).
            _prior = config.genre_stats
            if _genre and _prior is not None:
                # The prior mean is itself an estimate, drawn from n_students
                # peers. Treating it as worth a flat `prior_weight` virtual
                # observations is only valid as n_students → ∞; for a small
                # cohort it imports peer-group noise faster than it removes
                # cold-start noise, and it does so at exactly the pool sizes
                # where the estimate deserves least trust. Damp the virtual
                # weight by pool size: self-normalising against prior_weight
                # (no new tuning constant), monotone in n_students, and
                # asymptotically the undamped blend.
                #
                #   n=3  → w = 0.50·prior_weight     n=30 → w = 0.91·prior_weight
                #   n=10 → w = 0.77·prior_weight     n→∞  → w = prior_weight
                #
                # n_students is absent from hand-built or pre-WS-7 genre_stats
                # dicts; fall back to the undamped weight there rather than
                # guessing a cohort size.
                _n_students = _prior.get("n_students")
                _weight = config.prior_weight
                if _n_students:
                    _weight *= _n_students / (_n_students + config.prior_weight)
                _alpha = state.sample_count / (state.sample_count + _weight)
                mu = _alpha * mu + (1.0 - _alpha) * _prior["mean"]
                sigma = _alpha * sigma + (1.0 - _alpha) * _prior["std"]
                log.debug(
                    "Bayesian prior blend: alpha=%.3f genre=%s n_prior=%d n_students=%s",
                    _alpha,
                    _genre,
                    _prior["n_samples"],
                    _n_students,
                )
        except Exception as _exc:
            log.debug("Bayesian prior blend skipped: %s", _exc)

    sub_raw = submission_vector  # raw normalised [0,1] vector
    z = (sub_raw - mu) / sigma  # standardised deviation, shape (D,)

    # Apply tier weights then zero out inactive (no-data) features.
    # Phase 5: when an adaptive weight vector is supplied (built from the
    # ContextManifest), it replaces the static _TIER_WEIGHT_VECTOR. The
    # static vector is the unconditional fallback so Phase 1 callers see
    # byte-identical results.
    weight_vec = adaptive_weights if adaptive_weights is not None else _TIER_WEIGHT_VECTOR

    # ── Length-adaptive tier scaling ─────────────────────────────────────────
    # When config.length_adaptive_weights, scale the per-feature weight vector
    # by a per-tier factor that depends on the submission's word count. Tiers
    # that the stability study (validation/stability/) showed COLLAPSE on
    # short inputs get attenuated; tiers that HOLD get amplified. Default
    # OFF preserves byte-identical Phase 1 behaviour.
    if config.length_adaptive_weights:
        _bucket = _length_bucket_for(int(n_tokens))
        weight_vec = weight_vec * _LENGTH_SCALE_VECTORS[_bucket]

    # Winsorise individual feature z-scores before weighting.
    # A single feature with |z| > 4 contributes 16× to the rms_z² sum —
    # far more than any neighbouring feature, regardless of tier weight.
    # This turns legitimate multi-feature drift (e.g. 20 features each at
    # z=2) invisible behind one noisy outlier (clausulae_consistency,
    # paragraph_topic_position, etc.) whose binary or discrete nature makes
    # it easy to produce extreme single-text values.
    #
    # Cap rationale: z=4 (4σ) is already an extreme per-feature deviation.
    # Capping here does NOT reduce sensitivity to AI text — ghostwritten
    # text typically pushes many features simultaneously above the cap, so
    # rms_z stays high.  It DOES prevent a single unlucky sentence-ending
    # coincidence from escalating a student's own writing.
    z_capped = np.clip(z, -4.0, 4.0)
    z_weighted = z_capped * weight_vec * active.astype(np.float64)

    n_active = int(active.sum())
    if n_active > 0:
        rms_z = float(np.sqrt(np.sum(z_weighted**2) / n_active))
    else:
        rms_z = 0.0

    # ── Explicit null model (rank-and-null work) ──────────────────────────────
    # Gated by config.null_model == "impostor" AND the caller supplying
    # impostor_stats — both must be true, so this can never fire from an
    # existing call site that doesn't know about it. Computes a relative
    # (claimed-author vs impostor-pool) deviation alongside the absolute
    # one; does not modify rms_z, D_raw, or anything downstream of them.
    llr_deviation_score: float | None = None
    if config.null_model == "impostor" and impostor_stats is not None:
        llr_deviation_score = _llr_deviation(
            sub_raw,
            impostor_stats,
            weight_vec,
            active,
            n_active,
            rms_z,
        )

    # ── Amplitude scoring (Production Phase 6) ────────────────────────────────
    # Gated by config.amplitude_scoring_enabled (default OFF).
    # When OFF: fidelity=0.0, conformal_p=None — all downstream consumers
    # treat these as "no amplitude data" and fall back to deviation_score only.
    # n_tokens is threaded in from the caller so Gaussian wave packet
    # attenuation is proportional to the actual submission length.
    # Falls back to the parameter default (300) when not supplied.
    _n_tokens = n_tokens
    _secret_key = config.secret_key
    if config.amplitude_scoring_enabled:
        try:
            _fidelity, _conformal_p, _amp_components = _amplitude_score(
                state,
                z,
                weight_vec,
                active,
                state.student_id,
                submission_id,
                _n_tokens,
                _secret_key,
                baseline_mean_override=mu,
                baseline_std_override=sigma,
                authentic_fidelities=config.authentic_fidelities,
            )
        except Exception as _exc:
            log.warning(
                "amplitude scoring failed for %s: %s — fidelity set to 0",
                submission_id,
                _exc,
            )
            _fidelity, _conformal_p, _amp_components = 0.0, None, {}
    else:
        _fidelity, _conformal_p, _amp_components = 0.0, None, {}

    # Map to [0,1] via tanh.
    #
    # Divisor calibration history
    # ───────────────────────────
    #   2.5  (original)  : rms_z 1.5→0.54, 2.5→0.76  (narrow band)
    #   1.0  (v2)        : rms_z 1.0→0.76, 2.0→0.96  (too aggressive —
    #                       with adaptive baseline_std ≈ 0.067 (N=5),
    #                       same-author holdouts hit rms_z ≈ 0.6 → D 0.54,
    #                       landing in 'schedule_conversation' — false alarm)
    #   1.5  (current)   : rms_z 0.6→0.38 (no_action ✓), 1.7→0.75 (sched.),
    #                       3.0→0.96 (escalate ✓). Properly separates same-
    #                       author variance from genuine cross-author drift.
    D_raw = float(np.tanh(rms_z / 1.5))

    # ── Trajectory adjustment ─────────────────────────────────────────────────
    traj = state.trajectory
    direction = "insufficient_data"
    alignment = 0.0
    adj_factor = 1.0
    traj_confidence = traj.confidence

    if traj.vector is not None:
        alignment = float(np.dot(xi, traj.vector))  # cos sim (both unit-normalised)
        if alignment > TRAJECTORY_GROWTH_THRESHOLD:
            direction = "growth"
            adj_factor = 0.75
        elif alignment < TRAJECTORY_REGRESSIVE_THRESHOLD:
            direction = "regressive"
            adj_factor = 1.15
        else:
            direction = "lateral"
            adj_factor = 1.0

    D_adjusted = float(np.clip(D_raw * adj_factor, 0.0, 1.0))

    # ── Interference decomposition ────────────────────────────────────────────
    # Use local `mu` (potentially Bayesian-blended) so interference deltas
    # are computed against the same reference distribution as the z-scores.
    interference = _decompose(xi, rho_xi, P, feature_dict, mu, z)

    # ── Baseline confidence ───────────────────────────────────────────────────
    bc = BaselineConfidence(
        purity=state.purity,
        von_neumann_entropy=state.von_neumann_entropy,
        sample_count=state.sample_count,
        authenticated_count=state.authenticated_count,
        effective_sample_count=state.effective_sample_count,
        trajectory_confidence=traj_confidence,
    )

    # ── Domain signal ─────────────────────────────────────────────────────────
    theol_sub = feature_dict.get("theological_register_score", 0.0)
    theol_base = state.baseline_mean[ALL_FEATURE_CODES.index("theological_register_score")]
    delta_theol = theol_sub - theol_base
    if theol_base > 0.5:
        balance = "confessional"
    elif theol_base < 0.25:
        balance = "critical"
    else:
        balance = "balanced"

    domain = DomainSignal(
        theological_register_score=theol_sub,
        register_anomaly=abs(delta_theol) > 0.25,
        confessional_balance=balance,
    )

    # ── Item 100: Catastrophic Drift Alert ───────────────────────────────────
    # Fire if RMS z-score across all features exceeds 3 SDs.  This catches
    # submissions so globally unlike the baseline that immediate review is
    # warranted even if individual feature scores appear borderline.
    CATASTROPHIC_DRIFT_THRESHOLD = 3.0
    catastrophic_drift = bool(rms_z >= CATASTROPHIC_DRIFT_THRESHOLD)

    # ── Recommended action ────────────────────────────────────────────────────
    recommendation = _recommend(
        P,
        D_adjusted,
        interference,
        domain,
        bc,
        fidelity=_fidelity,
        conformal_p=_conformal_p,
        n_tokens=n_tokens,
    )

    # ── LLR-informed action mode (2026-08 cross-genre study) ──────────────────
    # Gated the same way llr_deviation_score itself is: null_model=="impostor"
    # AND a real llr_deviation_score. config.llr_action_mode defaults to
    # "shadow" (log-only, recommendation unchanged) so this is a no-op unless
    # a caller explicitly opts into "gate"/"trigger"/"blend".
    if config.null_model == "impostor" and llr_deviation_score is not None:
        recommendation = _apply_llr_action_mode(
            recommendation,
            D_adjusted,
            llr_deviation_score,
            config.llr_action_mode,
        )

    # Override to escalate on catastrophic drift regardless of scored action
    if catastrophic_drift and recommendation.action != "escalate":
        recommendation = RecommendedAction(
            action="escalate",
            confidence=min(recommendation.confidence + 0.15, 1.0),
            rationale=(
                f"Catastrophic drift detected: overall feature deviation is "
                f"{rms_z:.1f} SDs from baseline (threshold: "
                f"{CATASTROPHIC_DRIFT_THRESHOLD} SDs). Immediate review required."
            ),
        )

    # ── Build output ──────────────────────────────────────────────────────────
    baseline_dict = {
        code: float(state.baseline_mean[i]) for i, code in enumerate(ALL_FEATURE_CODES)
    }

    return Layer7Output(
        student_id=state.student_id,
        submission_id=submission_id,
        authorship=AuthorshipSignal(
            authorship_probability=P,
            deviation_score=D_adjusted,
            quantum_fidelity=_fidelity,
            fidelity_conformal_pvalue=_conformal_p,
            llr_deviation_score=llr_deviation_score,
        ),
        trajectory=TrajectoryConformance(
            direction=direction,
            alignment=alignment,
            confidence=traj_confidence,
            adjustment_factor=adj_factor,
        ),
        interference=interference,
        baseline_confidence=bc,
        domain=domain,
        recommendation=recommendation,
        feature_vector=feature_dict,
        baseline_vector=baseline_dict,
        catastrophic_drift=catastrophic_drift,
        catastrophic_drift_rms_z=rms_z,
        # Phase 3+: attach the adaptive context manifest (if any) for audit.
        # Stored as a plain dict so this module needs no original.context import.
        context_manifest=manifest,
    )


# ── Interference decomposition ────────────────────────────────────────────────


def _decompose(
    xi: np.ndarray,
    rho_xi: np.ndarray,
    P: float,
    feature_dict: dict[str, float],
    baseline_mean: np.ndarray,
    z_scores: np.ndarray | None = None,
) -> InterferenceDecomposition:
    # Per-feature contribution: use z-score magnitude as the contribution signal.
    # Born contributions are preserved but z-score drives constructive/destructive.
    born_contribs = xi * rho_xi  # shape (D,)
    if z_scores is None:
        z_scores = np.zeros(FEATURE_DIM)

    feature_contribs: list[FeatureContribution] = []
    for i, code in enumerate(ALL_FEATURE_CODES):
        c = float(born_contribs[i])
        z = float(z_scores[i])
        sub_val = feature_dict.get(code, float(xi[i]))
        base_val = float(baseline_mean[i])
        delta = sub_val - base_val

        # Direction based on z-score magnitude (more intuitive than Born contribution)
        if z < -1.0 or z > 1.0:
            direction = "destructive"  # significantly outside baseline range
        elif abs(z) < 0.5:
            direction = "constructive"  # well within baseline range
        else:
            direction = "neutral"

        feature_contribs.append(
            FeatureContribution(
                code=code,
                name=FEATURE_NAMES[code],
                tier=FEATURE_TIER[code],
                contribution=c,
                direction=direction,
                baseline_value=base_val,
                submission_value=sub_val,
                delta=delta,
            )
        )

    constructive = sorted(
        [f for f in feature_contribs if f.direction == "constructive"],
        key=lambda f: f.contribution,
        reverse=True,
    )[:5]

    # Sort destructive by weighted absolute delta — tier weights amplify
    # features that are more edit-resistant or person-specific.
    #
    # NOTE (Phase 5): the static TIER_WEIGHTS are intentionally retained here
    # rather than swapping in `adaptive_weights`. This ranking is about
    # *persistent identity* importance (which tiers are most diagnostic of
    # who the author is in general), not about contextual reliability for
    # this particular submission. Don't "fix" this to use adaptive weights —
    # it would surface contextually-attenuated features as top destructive
    # contributions, which is the opposite of what reviewers want to see.
    destructive = sorted(
        [f for f in feature_contribs if f.direction == "destructive"],
        key=lambda f: abs(f.delta) * TIER_WEIGHTS.get(f.tier, 1.0),
        reverse=True,
    )[:5]

    # Cross-feature entanglement anomalies (top off-diagonal terms)
    entanglements = _find_entanglement_anomalies(xi, feature_contribs)

    # Tier breakdown: fraction of total Born probability from each tier
    tier_totals: dict[int, float] = {}
    for fc in feature_contribs:
        tier_totals[fc.tier] = tier_totals.get(fc.tier, 0.0) + max(fc.contribution, 0.0)
    total_positive = sum(tier_totals.values()) + 1e-9
    tier_breakdown = {f"T{t}": v / total_positive for t, v in sorted(tier_totals.items())}

    return InterferenceDecomposition(
        total_probability=P,
        constructive_features=constructive,
        destructive_features=destructive,
        broken_entanglements=entanglements,
        tier_breakdown=tier_breakdown,
    )


def _find_entanglement_anomalies(
    xi: np.ndarray,
    feature_contribs: list[FeatureContribution],
) -> list[EntanglementAnomaly]:
    """
    Identify the most anomalous feature-pair co-variations.

    For each pair (i, j) where |ρ[i,j]| > 0.05:
        expected = ρ[i, j]
        observed = ξ[i] × ξ[j]
        anomaly  = (expected − observed)² × |expected|
    """
    # We don't have ρ here directly, but we can approximate the
    # cross-feature expected correlation from the contribution structure.
    # Use the product of per-feature deviations as a proxy.
    anomalies: list[EntanglementAnomaly] = []

    # Informative cross-tier pairs — where correlated baseline patterns should
    # hold but break under AI ghostwriting or stylistic fraud.
    # Expanded to include Tiers 8–12 "musical" relationships.
    _INFORMATIVE_TIER_PAIRS = {
        (2, 3),  # discourse structure ↔ rhetorical register
        (4, 6),  # char/punct fingerprint ↔ idiosyncratic patterns
        (1, 7),  # surface stylometrics ↔ AI detection markers
        (4, 7),  # char/punct ↔ AI detection
        (5, 6),  # POS/syntax ↔ idiosyncratic
        (2, 7),  # discourse ↔ AI detection
        (3, 7),  # rhetorical ↔ AI detection
        (1, 11),  # surface vocab ↔ error ecology (ghostwriting signal)
        (6, 11),  # idiosyncratic ↔ error ecology (should co-vary)
        (7, 12),  # AI markers ↔ tension arc (should co-vary for AI text)
        (8, 12),  # prosodic rhythm ↔ tension arc (rhythmic coherence)
    }
    cross_tier_pairs = [
        (a, b)
        for a in feature_contribs
        for b in feature_contribs
        if a.tier < b.tier and a.tier >= 1 and (a.tier, b.tier) in _INFORMATIVE_TIER_PAIRS
    ]

    for a, b in cross_tier_pairs[:80]:  # cap search for performance
        # Proxy: if both are destructive and highly correlated in baseline,
        # that's the strongest signal
        if a.direction == "destructive" and b.direction == "destructive":
            a_dev = abs(a.delta)
            b_dev = abs(b.delta)
            if a_dev > 0.15 and b_dev > 0.15:
                score = a_dev * b_dev * 2.0  # interaction term
                tier_label = f"T{a.tier}–T{b.tier}"
                name_a = a.name.split()[0].lower()
                name_b = b.name.split()[0].lower()
                anomalies.append(
                    EntanglementAnomaly(
                        feature_a=a.code,
                        feature_b=b.code,
                        tier_a=a.tier,
                        tier_b=b.tier,
                        expected_correlation=0.0,  # would come from ρ[i,j]
                        observed_product=float(
                            xi[ALL_FEATURE_CODES.index(a.code)]
                            * xi[ALL_FEATURE_CODES.index(b.code)]
                        ),
                        anomaly_score=float(np.clip(score, 0.0, 1.0)),
                        label=f"{tier_label} {name_a}–{name_b} entanglement",
                    )
                )

    # ── Special case: T1↔T11 vocabulary-spike + error-vanish ────────────────
    # If Tier 1 vocab features are CONSTRUCTIVE (rich vocabulary, within baseline)
    # but Tier 11 error features are DESTRUCTIVE (error fingerprint has vanished),
    # this is a strong indicator of AI ghostwriting — the ghostwriter replicated
    # the student's vocabulary range but not their error ecology.
    t1_vocab_codes = {"type_token_ratio", "hapax_legomena_rate"}
    t11_error_codes = {"error_kl_divergence", "stumble_rate_consistency"}
    # Magnitude thresholds (on delta, not Born direction) prevent noise (±0.04)
    # from triggering this signal. "Constructive"/"destructive" Born direction
    # is unreliable for this check because Born contributions cluster tightly;
    # the raw feature delta (submission − baseline) is the correct signal here.
    # AI ghostwriting produces large, unambiguous deltas; authentic variance does not.
    _TTR_SPIKE_THRESHOLD = 0.15  # TTR must be ≥ 0.15 above baseline mean
    _ERR_VANISH_THRESHOLD = -0.10  # error fingerprint ≥ 0.10 below baseline mean
    t1_constructive = any(
        f.code in t1_vocab_codes
        and f.delta >= _TTR_SPIKE_THRESHOLD  # delta only — no Born-direction filter
        for f in feature_contribs
    )
    t11_destructive = any(
        f.code in t11_error_codes and f.delta <= _ERR_VANISH_THRESHOLD for f in feature_contribs
    )
    if t1_constructive and t11_destructive:
        anomalies.insert(
            0,
            EntanglementAnomaly(
                feature_a="type_token_ratio",
                feature_b="error_kl_divergence",
                tier_a=1,
                tier_b=11,
                # Baseline co-variance: richer vocabulary typically co-occurs with
                # a richer, more idiosyncratic error fingerprint (r ≈ 0.6)
                expected_correlation=0.6,
                observed_product=float(
                    xi[ALL_FEATURE_CODES.index("type_token_ratio")]
                    * xi[ALL_FEATURE_CODES.index("error_kl_divergence")]
                ),
                anomaly_score=0.85,
                label="T1–T11 vocabulary-spike + error-vanish (AI ghostwriting signal)",
            ),
        )

    anomalies.sort(key=lambda x: x.anomaly_score, reverse=True)
    return anomalies[:3]


# ── Recommended action ────────────────────────────────────────────────────────


def _recommend(
    born_prob: float,
    deviation: float,
    interference: InterferenceDecomposition,
    domain: DomainSignal,
    bc: BaselineConfidence,
    fidelity: float = 0.0,
    conformal_p: float | None = None,
    n_tokens: int | None = None,
) -> RecommendedAction:
    """Derive recommended action from the full probability object.

    Primary verdict signal: ``deviation`` (Mahalanobis-like RMS z-score
    passed through tanh).  Feature-specific z-scores correctly separate
    same-author variance from genuine cross-author drift.

    ``born_prob`` (ξᵀρξ) is retained as a secondary diagnostic.  It
    measures how well the submission vector *aligns* with the density matrix
    principal directions, but in high-dimensional [0,1]-normalised feature
    space all positive vectors cluster near the same angular neighbourhood,
    so it cannot serve as the primary verdict signal.  It IS useful as a
    consistency check: large gaps between the Born signal and the deviation
    signal flag edge cases worth human review.
    """

    # Primary signal: deviation score (higher = more suspicious / anomalous)
    action = "no_action"
    for act, (lo, hi) in ACTION_THRESHOLDS.items():
        if lo <= deviation < hi:
            action = act
            break
    if deviation >= 1.0:
        action = "escalate"

    # ── Entanglement override ─────────────────────────────────────────────────
    # The T1–T11 vocabulary-spike + error-vanish pattern is a high-specificity
    # AI ghostwriting signal. The detector now requires minimum delta magnitudes
    # (TTR ≥ +0.15, error ≤ −0.10) before labelling it, so noise won't trigger
    # it. We add a second magnitude guard here as defence in depth: check that
    # the actual feature values in the destructive/constructive feature lists
    # confirm large deltas before escalating.
    _GHOSTWRITING_LABEL = "T1–T11 vocabulary-spike + error-vanish (AI ghostwriting signal)"
    ghostwriting_detected = any(
        e.label == _GHOSTWRITING_LABEL for e in interference.broken_entanglements
    )
    # Defence-in-depth magnitude guard — use delta not Born direction
    # (Born contributions cluster tightly; delta is the reliable magnitude signal)
    _all_top_feats = interference.constructive_features + interference.destructive_features
    _ttr_spiked = any(f.code == "type_token_ratio" and f.delta >= 0.15 for f in _all_top_feats)
    _err_vanished = any(
        f.code == "error_kl_divergence" and f.delta <= -0.10 for f in _all_top_feats
    )
    ghostwriting_confirmed = ghostwriting_detected and _ttr_spiked and _err_vanished
    if ghostwriting_confirmed and action != "escalate":
        action = "escalate"

    # ── Conformal signal (when amplitude scoring is enabled + calibrated) ─────
    # conformal_p is a p-value: low = anomalous vs authentic calibration set.
    # We use it as a secondary signal to nudge action up or add rationale.
    # It NEVER overrides a higher-severity action and NEVER acts alone without
    # evidence from the deviation score (to avoid false positives on day 0).
    _conformal_nudge_note: str | None = None
    if conformal_p is not None:
        from .conformal import verdict_from_pvalue

        _conformal_verdict = verdict_from_pvalue(conformal_p)
        # Nudge up if conformal is more alarmed than deviation score
        _action_severity = {
            "no_action": 0,
            "monitor": 1,
            "schedule_conversation": 2,
            "escalate": 3,
        }
        if (
            _action_severity.get(_conformal_verdict, 0) > _action_severity.get(action, 0)
            and action != "escalate"
        ):
            action = _conformal_verdict
            _conformal_nudge_note = (
                f"Conformal calibration (p={conformal_p:.3f}) suggests "
                f"'{_conformal_verdict}' — action raised from deviation-score verdict."
            )
        elif conformal_p > 0.20 and action == "escalate" and not ghostwriting_confirmed:
            # Conformal calibration disagrees — add a note but keep action
            _conformal_nudge_note = (
                f"Note: conformal calibration (p={conformal_p:.3f}) suggests "
                "this fidelity is within the range of authentic submissions — "
                "verify manually before acting."
            )

    # Confidence: lower if baseline is thin or trajectory uncertain
    base_confidence = min(
        1.0,
        bc.effective_sample_count / 5.0,  # saturates at 5 effective samples
    )
    confidence = float(np.clip(base_confidence * (0.7 + 0.3 * bc.purity), 0.0, 1.0))
    if ghostwriting_confirmed:
        confidence = min(confidence, 0.80)  # cap: entanglement is high-specificity
        # but confirmation via baseline still helps

    # Secondary consistency check: if Born probability (cosine-alignment signal)
    # strongly disagrees with deviation score, reduce confidence and note it.
    # born_suspicion = 1 - born_prob  maps to same 0..1 scale as deviation.
    born_suspicion = 1.0 - born_prob
    signal_gap = abs(born_suspicion - min(deviation, 1.0))
    if signal_gap > 0.25:
        confidence = float(np.clip(confidence * 0.85, 0.0, 1.0))

    # Build rationale
    n_destructive = len(interference.destructive_features)
    top_destructive = (
        interference.destructive_features[0].name
        if interference.destructive_features
        else "unknown feature"
    )
    top_entanglement = (
        interference.broken_entanglements[0].label if interference.broken_entanglements else None
    )

    rationale_parts = [
        f"Deviation score {deviation:.3f} (primary verdict signal).",
        f"Born authorship probability {born_prob:.3f} (secondary alignment check).",
        f"{n_destructive} destructive interference features detected.",
        f"Primary anomaly: {top_destructive}.",
    ]
    if ghostwriting_confirmed:
        rationale_parts.append(
            "AI ghostwriting signal detected: vocabulary-spike + error-vanish "
            "entanglement broken (T1–T11). Action escalated regardless of deviation score."
        )
    if signal_gap > 0.25:
        rationale_parts.append(
            f"Born and deviation signals diverge by {signal_gap:.2f} — "
            "confidence reduced; manual review advised."
        )
    if top_entanglement and not ghostwriting_confirmed:
        rationale_parts.append(f"Broken entanglement: {top_entanglement}.")
    if domain.register_anomaly:
        rationale_parts.append("Theological register anomaly detected.")
    if bc.effective_sample_count < 3:
        rationale_parts.append(
            f"Note: baseline built on {bc.effective_sample_count:.1f} effective samples — "
            "confidence is limited."
        )
    # Length-stability work measured feature reliability degrading sharply
    # below ~300 words. Prose-only caution (mirrors the thin-baseline note
    # above): the action itself is never changed by submission length.
    if n_tokens is not None and n_tokens < SHORT_SUBMISSION_TOKENS:
        rationale_parts.append(
            f"Note: submission is only {n_tokens} words — short submissions "
            "reduce stylometric confidence; treat this result as provisional."
        )
    if _conformal_nudge_note:
        rationale_parts.append(_conformal_nudge_note)

    return RecommendedAction(
        action=action,
        confidence=confidence,
        rationale=" ".join(rationale_parts),
    )


# ── LLR-informed action modes (2026-08 cross-genre study) ────────────────────
#
# validation/genre_crossgenre_2026-08/ leave-one-genre-out study: build a
# baseline from an author's OTHER genres, score a held-out genre against it.
# The raw deviation_score alone scored WORSE than chance (mean AUC 0.39) at
# telling that genuine cross-genre submission apart from a different author's
# writing — genre shift alone can inflate rms_z enough to look more
# "anomalous" than an impostor. llr_deviation_score (relative to an impostor
# pool, NULL_MODEL=impostor) alone scored 0.86 on the same data. These modes
# let that signal graduate from "attached for display" to "changes the
# verdict" — one asymmetric step at a time, gated behind ScoringConfig.
# llr_action_mode so nothing here fires unless explicitly opted into.

_ACTION_SEVERITY = ["no_action", "monitor", "schedule_conversation", "escalate"]

# Symmetric around llr_deviation_score's documented 0.5 midpoint ("as
# consistent with one as the other") — see AuthorshipSignal.llr_deviation_score.
LLR_ACTION_GENUINE_THRESHOLD = 0.35  # below → confidently more like the claimed author
LLR_ACTION_IMPOSTOR_THRESHOLD = 0.65  # above → confidently more like the impostor pool


def _llr_action_candidates(
    action: str,
    deviation: float,
    llr_deviation_score: float,
) -> dict[str, str]:
    """What each llr_action_mode WOULD produce, for the current action/scores.

    Pure function of (action, deviation, llr_deviation_score) — no I/O, no
    config — so shadow mode can log all three candidates regardless of which
    mode (if any) is actually applied.
    """
    idx = _ACTION_SEVERITY.index(action)

    gate_action = action
    if llr_deviation_score <= LLR_ACTION_GENUINE_THRESHOLD and idx > 0:
        gate_action = _ACTION_SEVERITY[idx - 1]

    trigger_action = action
    if llr_deviation_score >= LLR_ACTION_IMPOSTOR_THRESHOLD and idx == 0:
        trigger_action = _ACTION_SEVERITY[idx + 1]

    blended = 0.5 * deviation + 0.5 * llr_deviation_score
    blend_action = "no_action"
    for act, (lo, hi) in ACTION_THRESHOLDS.items():
        if lo <= blended < hi:
            blend_action = act
    if blended >= 1.0:
        blend_action = "escalate"

    return {"gate": gate_action, "trigger": trigger_action, "blend": blend_action}


def _apply_llr_action_mode(
    recommendation: RecommendedAction,
    deviation: float,
    llr_deviation_score: float,
    mode: str,
) -> RecommendedAction:
    """Let llr_deviation_score influence the recommended action, per `mode`.

    "shadow" (default) NEVER changes `recommendation` — it only logs what
    "gate"/"trigger"/"blend" would have decided, so the NULL_MODEL=impostor
    attach-only contract holds unless a caller explicitly opts into a mode
    that changes verdicts. See module comment above for what motivated this.
    """
    candidates = _llr_action_candidates(recommendation.action, deviation, llr_deviation_score)

    if mode == "shadow":
        log.info(
            "llr_action_shadow live=%s gate_would=%s trigger_would=%s blend_would=%s "
            "llr=%.3f deviation=%.3f",
            recommendation.action,
            candidates["gate"],
            candidates["trigger"],
            candidates["blend"],
            llr_deviation_score,
            deviation,
        )
        return recommendation

    if mode not in candidates:
        raise ValueError(f"unknown llr_action_mode: {mode!r}")

    new_action = candidates[mode]
    if new_action == recommendation.action:
        return recommendation

    _verbs = {"gate": "downgraded", "trigger": "raised", "blend": "re-derived"}
    _reasons = {
        "gate": (
            f"llr_deviation_score={llr_deviation_score:.3f} indicates this is more "
            "consistent with the claimed author than the impostor pool."
        ),
        "trigger": (
            f"llr_deviation_score={llr_deviation_score:.3f} indicates this is more "
            "consistent with the impostor pool than the claimed author."
        ),
        "blend": (
            f"action tier re-derived from a 50/50 blend of deviation_score and "
            f"llr_deviation_score={llr_deviation_score:.3f}."
        ),
    }
    return RecommendedAction(
        action=new_action,
        confidence=recommendation.confidence,
        rationale=(
            f"{recommendation.rationale} [LLR {mode}: {_verbs[mode]} from "
            f"'{recommendation.action}' to '{new_action}' — {_reasons[mode]}]"
        ),
    )
