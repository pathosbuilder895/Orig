"""
quantum/state.py — Student quantum state: density matrix + trajectory.

The student's writing identity is a mixed state described by a density
matrix ρ ∈ ℝ^(D×D) built from weighted outer products of normalised
feature vectors drawn from authenticated baseline samples.

Mathematics
───────────
Given N baseline samples with normalised feature vectors v₁…vₙ ∈ ℝᴰ
and composite weights w₁…wₙ (auth_weight × recency_decay):

    ρ = Σᵢ wᵢ vᵢ vᵢᵀ / Σᵢ wᵢ          (density matrix, tr(ρ) = 1)

Purity  = tr(ρ²)  ∈ [1/D, 1.0]
  → 1.0  for a single proctored sample (pure state)
  → 1/D  for maximally mixed state (D independent samples)

The trajectory vector δψ is the slope of a linear fit through the
sequence of normalised state vectors, giving the direction in which
the student's writing identity is evolving.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np

from ..constants import (
    ALL_FEATURE_CODES, FEATURE_DIM, AUTH_WEIGHTS, RECENCY_DECAY,
    TRAJECTORY_MIN_SAMPLES,
)


@dataclass
class BaselineSample:
    """One authenticated writing sample."""
    text: str
    vector: np.ndarray          # normalised feature vector, shape (D,)
    provenance: str             # "proctored" | "verified" | "unverified"
    auth_weight: float          # AUTH_WEIGHTS[provenance]
    assignment: str = ""
    submitted_at: str = ""      # ISO date string

    # ── Phase 4 context metadata (additive — None for legacy samples) ─────────
    # Lazily backfilled by ensure_sample_context_metadata() on first adaptive
    # scoring call against a student. None = "not yet computed"; empty
    # string / array indicates the value has been computed and is empty.
    genre: Optional[str] = None                       # rule-based genre label
    topic_centroid: Optional[np.ndarray] = None       # TF-IDF centroid, shape (K,)
    context_manifest: Optional[Dict] = None           # captured at the time of ingestion


@dataclass
class TrajectoryResult:
    direction: str              # "growth" | "lateral" | "regressive" | "insufficient_data"
    alignment: float            # cosine similarity of submission with trajectory, −1…1
    confidence: float           # R² of linear fit, 0…1
    vector: Optional[np.ndarray] = None  # normalised trajectory direction, shape (D,)
    adjustment_factor: float = 1.0


# ── Phase 8: Baseline Drift Detection ────────────────────────────────────────

@dataclass
class DriftResult:
    """
    Outcome of comparing a new baseline sample against the existing baseline.

    Returned by ``StudentState.check_drift()`` when a sample is being
    considered for ingestion. The instructor / API uses ``recommendation``
    to decide whether to add the sample, hold it for review, or trigger a
    rebaseline workflow.

    Recommendation semantics
    ------------------------
    accept           — drift below threshold (or first sample); add sample
    flag_for_review  — first outlier; HOLD the sample, request review
    rebaseline       — consecutive outliers exceed the threshold; the
                       student's writing has genuinely shifted, the existing
                       baseline is no longer valid
    """
    drift_detected: bool
    drift_magnitude: float                      # mean abs deviation across anchor tiers
    anchor_tier_deviations: Dict[int, float]    # per-tier mean |delta|
    recommendation: str                         # "accept" | "flag_for_review" | "rebaseline"
    consecutive_drift_count: int                # state's counter AFTER this check

    def to_dict(self) -> Dict:
        # Tier-keyed dict needs str keys for JSON safety.
        return {
            "drift_detected":         self.drift_detected,
            "drift_magnitude":        self.drift_magnitude,
            "anchor_tier_deviations": {str(k): v for k, v in self.anchor_tier_deviations.items()},
            "recommendation":         self.recommendation,
            "consecutive_drift_count": self.consecutive_drift_count,
        }


@dataclass
class StudentState:
    """
    Full quantum state of a student's writing identity.

    Maintains the density matrix, trajectory, and the ordered list
    of baseline samples. Unverified submissions are excluded from
    the density matrix update (auth_weight == 0).

    Also maintains the Tension Arc baseline: a running mean of the
    catastrophe index κ across all verified submissions.
    """
    student_id: str
    samples: List[BaselineSample] = field(default_factory=list)

    # Tension Arc baseline — updated when a submission is marked authentic
    baseline_kappa: Optional[float] = field(default=None)
    kappa_log: List[float]          = field(default_factory=list)

    # Cached computed values — invalidated on each update
    _rho: Optional[np.ndarray]         = field(default=None, repr=False)
    _purity: Optional[float]           = field(default=None, repr=False)
    _trajectory: Optional[TrajectoryResult] = field(default=None, repr=False)

    # Phase 8: drift detection — running count of consecutive baseline
    # ingestion attempts whose anchor-tier deviation exceeded the threshold.
    # Reset to 0 on the first accept. Persisted via store._serialize so the
    # workflow survives restarts (a single outlier today + a single outlier
    # next week should still trigger rebaseline). Underscore prefix matches
    # the convention used for cached values; check_drift mutates it.
    _consecutive_drift_count: int      = field(default=0, repr=False)

    # ── Mutation ─────────────────────────────────────────────────────────────

    def add_sample(self, sample: BaselineSample) -> None:
        """Append a baseline sample and invalidate the cached state."""
        self.samples.append(sample)
        self._rho = None
        self._purity = None
        self._trajectory = None

    # ── Density matrix ───────────────────────────────────────────────────────

    @property
    def density_matrix(self) -> np.ndarray:
        if self._rho is None:
            self._rho = self._build_density_matrix()
        return self._rho

    def _build_density_matrix(self) -> np.ndarray:
        """
        Build ρ from all samples with auth_weight > 0 (contributing samples).

        Each sample i gets composite weight:
            composite_i = auth_weight_i × recency_decay^(N-1-i)
        where i is the index in the contributing-samples list (oldest → 0).
        """
        contributing = [s for s in self.samples if s.auth_weight > 0]
        N = len(contributing)

        if N == 0:
            # No authenticated samples — return uniform prior (identity/D)
            return np.eye(FEATURE_DIM, dtype=np.float64) / FEATURE_DIM

        weights = np.array([
            s.auth_weight * (RECENCY_DECAY ** (N - 1 - i))
            for i, s in enumerate(contributing)
        ], dtype=np.float64)

        rho = np.zeros((FEATURE_DIM, FEATURE_DIM), dtype=np.float64)
        for i, s in enumerate(contributing):
            v = _unit(s.vector)
            rho += weights[i] * np.outer(v, v)

        rho /= weights.sum()
        return rho

    # ── Purity ───────────────────────────────────────────────────────────────

    @property
    def purity(self) -> float:
        """tr(ρ²) — measures how concentrated the identity state is."""
        if self._purity is None:
            rho = self.density_matrix
            self._purity = float(np.trace(rho @ rho))
        return self._purity

    @property
    def baseline_std(self) -> np.ndarray:
        """
        Per-feature standard deviation across baseline samples (shape D,).

        Floor scales with baseline size: floor = 0.15 / sqrt(N).
        Rationale: with N=3 docs, almost every feature has σ≈0 (floored),
        which drove z-scores of 100–240 and tanh saturation at 1.0 on every
        submission. Scaling the floor with N means:
            N=3  → floor ≈ 0.087  (permissive — we don't know the variance yet)
            N=8  → floor ≈ 0.053
            N=15 → floor ≈ 0.039
            N=30 → floor ≈ 0.027  (tight — genuine identity signal)
        This lets the system get progressively stricter as the baseline matures,
        which matches the intuition that a 3-doc baseline should not fire
        z=200 on any deviation.

        Hard minimum: 0.005 (prevents division-by-zero regardless of N).
        """
        contributing = [s for s in self.samples if s.auth_weight > 0]
        N = len(contributing)
        if N < 2:
            return np.full(FEATURE_DIM, 0.15)   # flat uncertainty prior
        V = np.stack([s.vector for s in contributing])
        adaptive_floor = max(0.005, 0.15 / math.sqrt(N))
        return np.maximum(V.std(axis=0), adaptive_floor)

    @property
    def active_feature_mask(self) -> np.ndarray:
        """
        Boolean mask (shape D,) — True for features with genuine variance
        in the baseline, False for features that are uninformative.

        Excluded dimensions:
          1. Stuck-neutral (≈0.5): features that cannot be computed return 0.5
             as a placeholder (Tier 17 behavioral, Tier 10 without torch, etc.)
          2. Zero-baseline: features where every baseline doc returns 0.0.
             These produce unbounded z-scores (z=200) if ANY test doc produces
             a non-zero value — chiasmus_rate, structural_centrist_penalty, etc.
             A feature never observed in baseline is not an identity marker;
             its presence in a test doc tells us nothing about authorship.

        Note: we exclude zero-frequency features (all-zero baseline) but NOT
        features with low positive values — those may be genuine identity markers
        (e.g. comma_splice_rate=0.01 ± 0.005 is informative, chiasmus=0.00 is not).
        """
        contributing = [s for s in self.samples if s.auth_weight > 0]
        if len(contributing) < 2:
            return np.ones(FEATURE_DIM, dtype=bool)
        V = np.stack([s.vector for s in contributing])   # (N, D)

        # Condition 1: stuck at neutral placeholder
        stuck_at_neutral = np.all(np.abs(V - 0.5) < 0.002, axis=0)

        # Condition 2: zero-frequency (all baseline values are exactly 0.0)
        # Use a small epsilon to catch near-zero values from rounding
        zero_frequency = np.all(V < 0.005, axis=0)

        # Condition 3: constant-at-any-value — features that return the same
        # value across every baseline sample contribute zero discriminative signal
        # and generate unbounded z-scores (sigma=0 → floor) against any test
        # document that differs even slightly.  Threshold: std < 0.008, which
        # is well below the adaptive sigma floor (min ~0.005 for large N) but
        # above float rounding noise.  Examples caught: that_which_ratio=1.0 for
        # all samples, source_integration_style=0.0, arc_resolution_score=0.51.
        constant_value = V.std(axis=0) < 0.008

        return ~(stuck_at_neutral | zero_frequency | constant_value)

    @property
    def effective_sample_count(self) -> float:
        """
        Kish effective sample size: (Σwᵢ)² / Σwᵢ².
        Accounts for authentication-weight and recency-decay skew.
        """
        contributing = [s for s in self.samples if s.auth_weight > 0]
        N = len(contributing)
        if N == 0:
            return 0.0
        weights = np.array([
            s.auth_weight * (RECENCY_DECAY ** (N - 1 - i))
            for i, s in enumerate(contributing)
        ])
        return float(weights.sum() ** 2 / (weights ** 2).sum())

    @property
    def baseline_mean(self) -> np.ndarray:
        """Weighted mean feature vector of the baseline (shape D,)."""
        contributing = [s for s in self.samples if s.auth_weight > 0]
        if not contributing:
            return np.full(FEATURE_DIM, 0.5)
        N = len(contributing)
        weights = np.array([
            s.auth_weight * (RECENCY_DECAY ** (N - 1 - i))
            for i, s in enumerate(contributing)
        ])
        vectors = np.stack([s.vector for s in contributing])  # (N, D)
        return (weights[:, None] * vectors).sum(axis=0) / weights.sum()

    # ── Phase 8: drift detection ─────────────────────────────────────────────

    def check_drift(
        self,
        new_sample: "BaselineSample",
        threshold: float = 0.25,
        consecutive_required: int = 2,
    ) -> "DriftResult":
        """
        Compare ``new_sample`` against the existing baseline on anchor tiers
        and decide whether to accept, flag, or rebaseline.

        Parameters
        ----------
        new_sample : BaselineSample
            The candidate sample being considered for ingestion.
        threshold : float
            Drift magnitude above which a sample is treated as an outlier.
            ``0.25`` is conservative (anchor features are normalised to
            [0, 1] so 0.25 = 25 % mean deviation across the anchor codes).
        consecutive_required : int
            How many consecutive outliers it takes to flip the
            recommendation from ``flag_for_review`` to ``rebaseline``.
            Default 2: one outlier could be a fluke, two in a row is a
            shift.

        Returns
        -------
        DriftResult
            Always populated; ``recommendation`` is the actionable field.

        Anchor tier selection
        ---------------------
        T4 (char/punctuation) and T6 (idiosyncratic) are ALWAYS treated as
        anchor tiers — they're cross-genre stable identity signals. T8
        (tension-arc) and T13 (prosodic-depth) are added when the new
        sample's ``context_manifest`` was tagged as an academic/exegesis/
        sermon genre at ingestion time, matching the manifest derivation
        rules from Phase 3. Falling back to {4, 6} alone is fine for legacy
        samples that never went through the manifest pipeline.

        Bootstrap behaviour
        -------------------
        The first authenticated sample (no prior baseline to compare to)
        cannot be checked — there's no baseline_mean yet. We return
        ``accept`` with magnitude 0 and ``drift_detected=False``. The
        counter is NOT incremented on accept; it's reset.

        Side effects
        ------------
        Mutates ``self._consecutive_drift_count``:
            - increments by 1 on outlier
            - resets to 0 on accept
        Does NOT add the sample to ``self.samples`` — that's the caller's
        responsibility, gated on ``recommendation``.
        """
        from ..constants import (
            TIER4_CODES, TIER6_CODES, TIER8_CODES, TIER13_CODES,
            ALL_FEATURE_CODES,
        )

        # ── Bootstrap: nothing to compare against → accept ───────────────────
        contributing = [s for s in self.samples if s.auth_weight > 0]
        if not contributing:
            self._consecutive_drift_count = 0
            return DriftResult(
                drift_detected=False, drift_magnitude=0.0,
                anchor_tier_deviations={}, recommendation="accept",
                consecutive_drift_count=0,
            )

        # ── Anchor tier selection ────────────────────────────────────────────
        anchor_tiers: List[int] = [4, 6]
        manifest = getattr(new_sample, "context_manifest", None) or {}
        # Manifest may be stored as the dataclass dict; check the genre that
        # was assigned at ingestion time (matches Phase 3's derivation rules).
        new_genre = (manifest.get("genre") or {}).get("primary") if isinstance(manifest, dict) else None
        if new_genre in {"academic_exegesis", "scholarly_essay", "sermon"}:
            anchor_tiers.extend([8, 13])

        # Collect (tier, list-of-feature-indices) for each anchor tier.
        # Build the index list once from ALL_FEATURE_CODES so vector access
        # is positional and matches everywhere else in the codebase.
        tier_codes: Dict[int, List[str]] = {
            4: list(TIER4_CODES), 6: list(TIER6_CODES),
            8: list(TIER8_CODES), 13: list(TIER13_CODES),
        }
        code_to_index = {c: i for i, c in enumerate(ALL_FEATURE_CODES)}

        # ── Compute per-tier mean |delta| against baseline mean ──────────────
        mu = self.baseline_mean   # already weighted (shape D,)
        per_tier: Dict[int, float] = {}
        for tier in anchor_tiers:
            indices = [code_to_index[c] for c in tier_codes[tier]
                        if c in code_to_index]
            if not indices:
                continue
            delta = np.abs(new_sample.vector[indices] - mu[indices])
            per_tier[tier] = round(float(delta.mean()), 4)

        if not per_tier:
            # No anchor tier had any codes (shouldn't happen with the
            # default {4, 6} but defensive). Treat as accept.
            self._consecutive_drift_count = 0
            return DriftResult(
                drift_detected=False, drift_magnitude=0.0,
                anchor_tier_deviations={}, recommendation="accept",
                consecutive_drift_count=0,
            )

        magnitude = float(np.mean(list(per_tier.values())))

        # ── Decision: accept / flag_for_review / rebaseline ──────────────────
        if magnitude <= threshold:
            # Sample looks like the existing baseline — accept and reset.
            self._consecutive_drift_count = 0
            return DriftResult(
                drift_detected=False,
                drift_magnitude=round(magnitude, 4),
                anchor_tier_deviations=per_tier,
                recommendation="accept",
                consecutive_drift_count=0,
            )

        # Outlier: bump the counter and decide review vs rebaseline.
        self._consecutive_drift_count += 1
        if self._consecutive_drift_count >= consecutive_required:
            recommendation = "rebaseline"
        else:
            recommendation = "flag_for_review"

        return DriftResult(
            drift_detected=True,
            drift_magnitude=round(magnitude, 4),
            anchor_tier_deviations=per_tier,
            recommendation=recommendation,
            consecutive_drift_count=self._consecutive_drift_count,
        )

    # ── Trajectory ───────────────────────────────────────────────────────────

    @property
    def trajectory(self) -> TrajectoryResult:
        if self._trajectory is None:
            self._trajectory = self._compute_trajectory()
        return self._trajectory

    def _compute_trajectory(self) -> TrajectoryResult:
        contributing = [s for s in self.samples if s.auth_weight > 0]
        if len(contributing) < TRAJECTORY_MIN_SAMPLES:
            return TrajectoryResult(
                direction="insufficient_data",
                alignment=0.0,
                confidence=0.0,
                vector=None,
                adjustment_factor=1.0,
            )

        # Stack vectors chronologically (oldest first)
        V = np.stack([_unit(s.vector) for s in contributing])  # (N, D)
        N = len(contributing)
        t = np.arange(N, dtype=np.float64)

        # Per-dimension linear fit: slope = δψ[d]
        t_mean = t.mean()
        t_var  = ((t - t_mean) ** 2).sum()
        if t_var < 1e-12:
            delta = np.zeros(FEATURE_DIM)
            r2 = 0.0
        else:
            slopes = ((t - t_mean)[:, None] * V).sum(axis=0) / t_var  # (D,)
            delta = slopes

            # R² averaged across dimensions (confidence in the trajectory)
            ss_tot = np.var(V, axis=0).mean()
            predicted = t[:, None] * slopes[None, :] + (V.mean(axis=0) - t_mean * slopes)[None, :]
            ss_res = ((V - predicted) ** 2).mean()
            r2 = max(0.0, 1.0 - ss_res / (ss_tot + 1e-9))

        return TrajectoryResult(
            direction="computed",
            alignment=0.0,      # filled in by scoring.py when a submission arrives
            confidence=float(np.clip(r2, 0.0, 1.0)),
            vector=_unit(delta) if np.linalg.norm(delta) > 1e-12 else None,
            adjustment_factor=1.0,
        )

    # ── State summary ─────────────────────────────────────────────────────────

    @property
    def sample_count(self) -> int:
        return len(self.samples)

    @property
    def authenticated_count(self) -> int:
        return sum(1 for s in self.samples if s.auth_weight > 0)


# ── Utilities ─────────────────────────────────────────────────────────────────

def _unit(v: np.ndarray) -> np.ndarray:
    """Return L2-unit normalised vector; return v unchanged if near-zero."""
    norm = np.linalg.norm(v)
    return v / norm if norm > 1e-12 else v
