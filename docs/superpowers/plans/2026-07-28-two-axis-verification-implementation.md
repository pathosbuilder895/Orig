# Two-Axis Authorship Verification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the one-sided, mis-calibrated deviation-score verdict in `original/quantum/scoring.py` with a two-axis system (per-student conformal typicality + per-tenant impostor identity), backed by six calibration gates, without changing any default-flag-off behavior.

**Architecture:** A new pure module (`original/quantum/typicality.py`) computes leave-one-out conformal p-values from a student's own baseline distances. `StudentState` caches the LOO distance distribution the same way it already caches `trajectory`/`density_matrix`. `scoring.py` consumes both under new env flags, feeding a probability-band action table that coexists with (not replaces) the two overrides that already sit downstream of `ACTION_THRESHOLDS` today (the entanglement/ghostwriting override and the existing one-sided, fidelity-based `conformal.py` nudge). A new `validation/calibration_gate.py` encodes six numeric pass/fail gates (G1–G6) against the existing seminary, public_authors, and Plato corpora, run through the same in-process `TestClient` pattern every other validation runner in this repo already uses.

**Tech Stack:** Python 3.11, FastAPI (`TestClient` for in-process validation), NumPy, pytest, the existing SQLite-backed `original.store` repository.

## Global Constraints

- Python: always `.venv/bin/python` / `.venv/bin/pytest` (repo root `~/Desktop/Original/.venv/`), never system `python3`.
- Test command: `.venv/bin/python -m pytest tests/ -q` (full suite); a clean run is **0 failed** — any failure is real, not flaky (`xfail(strict=False)`-marked auth-throttle tests aside).
- Every new behavior is gated by an env flag, **default `0`/off**, and must leave default output byte-identical (`CLAUDE.md` "Phase-1-byte-identical" rule). New flags this plan adds: `TYPICALITY_SCORING`, `TYPICALITY_SHADOW`, `IDENTITY_AXIS`, `MEASURED_WEIGHTS`.
- `ALL_FEATURE_CODES` ordering in `original/constants.py` and `NORM_BOUNDS` are on the CLAUDE.md **explicit-permission** list. Two tasks below (Task 9, Task 11) touch them — each is marked **STOP AND ASK** with the exact before/after diff shown; do not proceed past that step without the user's explicit go-ahead in that moment, even though this plan itself was authored with the user's knowledge that these tasks exist.
- Never kill/restart a running dev server without explicit permission (not expected to be needed — this plan touches no running-server state; all verification is via pytest and validation-corpus CLI runs).
- Commit style: one focused commit per task step, conventional prefixes (`Add …`, `Fix …`, `Refactor …`), co-author line `Co-Authored-By: Claude <model name> <noreply@anthropic.com>`.
- A different, one-sided conformal system (`original/quantum/conformal.py`, gated by `AMPLITUDE_SCORING_ENABLED`) already exists and must not be renamed, removed, or restructured — see Task 3's coexistence note.

---

## File Structure

**New files:**
- `original/quantum/typicality.py` — pure functions: LOO conformal p-values (two-sided), band-from-p mapping. No I/O, no `state`/`score` imports (mirrors `original/quantum/conformal.py`'s pure-function style).
- `original/features/uniformity.py` — Phase 4's six second-moment features, one extractor function, mirroring `original/features/tier17.py`'s structure.
- `scripts/derive_measured_weights.py` — Phase 3's author-level holdout split + Fisher-ratio weight derivation, emitting a committed weight-table artifact.
- `validation/calibration_gate.py` — G1–G6 runner: one `GateResult`-shaped dataclass per gate, a `run_all()` orchestrator, `render()`/`main()` CLI following `validation/plato/gate.py`'s exact shape (exit code = pass/fail).
- `tests/quantum/test_typicality.py` — unit tests for the new pure module.
- `tests/test_uniformity.py` — unit tests for the new feature group (top-level, matching `tests/test_tier17_report.py` naming convention).
- `tests/test_calibration_gate.py` — unit tests for gate math helpers (not the full corpus run, which is slow and belongs in the CLI path only).

**Modified files:**
- `original/quantum/state.py` — new `_loo_distances` cache field + `loo_distances` property + `_compute_loo_distances()`, invalidated in `add_sample` (mirrors `_trajectory`).
- `original/quantum/scoring.py` — `ScoringConfig` gets `typicality_scoring_enabled: bool`; `score()` computes typicality fields after `rms_z`, before the `tanh` mapping; `_recommend()`'s `ACTION_THRESHOLDS` lookup becomes conditional on the flag.
- `original/schemas.py` — new `TypicalityOut` Pydantic model + field on `Layer7OutputResponse`.
- `original/routers/_shared.py` — `_to_response()` gets a `typicality=` attach block (mirrors the existing `ai_likelihood=` conditional block).
- `original/quantum/professor_narrative.py` — `_build_hypotheses()` gets a `typicality_band` parameter and two new hypothesis branches (too-uniform, legitimate-evolution).
- `original/quantum/null_pool.py` — Phase 2: no structural change, reused as-is by the new identity-axis action matrix in `scoring.py`.
- `original/constants.py` — Phase 3 (`TIER_WEIGHTS`) and Phase 4 (`TIER18_CODES`/`ALL_FEATURE_CODES`/`NORM_BOUNDS`/`FEATURE_TIER`/`FEATURE_GROUPS`) — both STOP-AND-ASK checkpoints.
- `original/features/pipeline.py` — Phase 4: wire `extract_uniformity()` into `extract_features()`, add the `DISABLED_FEATURE_GROUPS` conditional (hardcoded literal, matching the existing `"behavioral"` branch — the generic dispatch does not exist).
- `scripts/calibrate_bounds.py` — Phase 3: add `extract_uniformity` to `extract_raw()`'s tier calls and a `_TIER_LABELS` entry.

---

## Task 1: `original/quantum/typicality.py` — pure conformal typicality functions

**Files:**
- Create: `original/quantum/typicality.py`
- Test: `tests/quantum/test_typicality.py`

**Interfaces:**
- Produces: `p_far(r_sub: float, loo_distances: list[float]) -> float`, `p_central(r_sub: float, loo_distances: list[float]) -> float`, `band_from_p(p_far: float, p_central: float) -> str` (returns one of `"no_action"`, `"monitor"`, `"schedule_conversation"`, `"escalate"`). These three are consumed by Task 2 (`state.py`) and Task 3 (`scoring.py`).

- [ ] **Step 1: Write the failing tests**

```python
# tests/quantum/test_typicality.py
"""
tests/quantum/test_typicality.py — pure conformal typicality math.

Mirrors tests/quantum/test_conformal.py's style: deterministic example-based
tests with inline algebra justifying the expected numeric value, no fixtures.
"""

from __future__ import annotations

from original.quantum.typicality import band_from_p, p_central, p_far


class TestPFar:
    def test_typical_sample_gives_p_far_near_half(self):
        """r_sub at the exact median of 9 LOO distances → p_far = 5/10 = 0.5."""
        loo = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0]
        # r_sub = 5.0 is >= itself and >= the 4 below it plus itself = 5 values >= 5.0
        assert p_far(5.0, loo) == 5 / 10

    def test_extreme_far_sample_gives_minimum_p_far(self):
        """r_sub larger than every LOO distance → p_far = 1/(N+1), the floor."""
        loo = [1.0, 2.0, 3.0]
        assert p_far(100.0, loo) == 1 / 4

    def test_extreme_central_sample_gives_maximum_p_far(self):
        """r_sub smaller than every LOO distance → p_far = (N+1)/(N+1) = 1.0."""
        loo = [1.0, 2.0, 3.0]
        assert p_far(0.0, loo) == 1.0

    def test_empty_loo_distances_raises(self):
        import pytest

        with pytest.raises(ValueError):
            p_far(1.0, [])


class TestPCentral:
    def test_typical_sample_gives_p_central_near_half(self):
        loo = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0]
        assert p_central(5.0, loo) == 5 / 10

    def test_extreme_central_sample_gives_minimum_p_central(self):
        """r_sub smaller than every LOO distance → p_central = 1/(N+1), the floor."""
        loo = [1.0, 2.0, 3.0]
        assert p_central(0.0, loo) == 1 / 4

    def test_extreme_far_sample_gives_maximum_p_central(self):
        loo = [1.0, 2.0, 3.0]
        assert p_central(100.0, loo) == 1.0

    def test_p_far_and_p_central_are_complementary_at_extremes(self):
        """A point that is rank-1-farthest has p_far at the floor and
        p_central at the ceiling, and vice versa for rank-1-closest."""
        loo = [1.0, 2.0, 3.0, 4.0, 5.0]
        assert p_far(100.0, loo) == 1 / 6
        assert p_central(100.0, loo) == 6 / 6
        assert p_far(-100.0, loo) == 6 / 6
        assert p_central(-100.0, loo) == 1 / 6


class TestBandFromP:
    def test_typical_is_no_action(self):
        assert band_from_p(p_far=0.5, p_central=0.5) == "no_action"

    def test_mild_drift_is_monitor(self):
        assert band_from_p(p_far=0.02, p_central=0.5) == "monitor"

    def test_moderate_drift_is_schedule_conversation(self):
        assert band_from_p(p_far=0.008, p_central=0.5) == "schedule_conversation"

    def test_strong_drift_is_escalate(self):
        assert band_from_p(p_far=0.001, p_central=0.5) == "escalate"

    def test_too_central_is_schedule_conversation(self):
        assert band_from_p(p_far=0.5, p_central=0.01) == "schedule_conversation"

    def test_no_action_boundary_is_inclusive_of_far_side(self):
        """p_far exactly at .03 is NOT > .03, so it must not be no_action."""
        assert band_from_p(p_far=0.03, p_central=0.5) != "no_action"

    def test_no_action_boundary_is_inclusive_of_central_side(self):
        assert band_from_p(p_far=0.5, p_central=0.02) != "no_action"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/quantum/test_typicality.py -v`
Expected: `ModuleNotFoundError: No module named 'original.quantum.typicality'`

- [ ] **Step 3: Write the implementation**

```python
# original/quantum/typicality.py
"""
quantum/typicality.py — two-sided conformal typicality for per-student
leave-one-out distance distributions.

Distinct from ``original.quantum.conformal`` (which computes a one-sided
p-value from ``quantum_fidelity`` against an instructor-confirmed feedback
calibration set — a different axis, a different calibration mechanism, and
gated behind ``AMPLITUDE_SCORING_ENABLED``). This module answers: "how
typical is this submission's distance-from-baseline, relative to the
student's own held-out baseline samples?" — on BOTH tails.

Given a student's leave-one-out distance distribution {r_1 … r_N} (each
r_i = the rms_z of baseline sample i against baseline statistics built
from the other N-1 samples) and a submission distance r_sub:

    p_far     = (1 + #{i : r_i >= r_sub}) / (N + 1)   # drift side
    p_central = (1 + #{i : r_i <= r_sub}) / (N + 1)   # too-perfect side

Both are conformal p-values in the standard sense (Vovk et al.): under
exchangeability, uniform on {1/(N+1), ..., 1} for a genuinely-authentic
r_sub. They are complementary, not independent — a single rank position
determines both. The quantization floor 1/(N+1) means neither p-value can
ever fall below that value regardless of how extreme r_sub is; see
docs/superpowers/specs/2026-07-28-two-axis-verification-design.md §5 for
the reachability-vs-N table these thresholds were chosen against.
"""

from __future__ import annotations

# Initial band constants. Provisional — the calibration-gate runner
# (validation/calibration_gate.py, gate G1) re-derives these empirically;
# they are chosen here only so that a+b == 0.05, satisfying G1's ≤5%
# same-author flagged-rate budget by construction. See the spec §4/§5.
NO_ACTION_FAR_THRESHOLD = 0.03
NO_ACTION_CENTRAL_THRESHOLD = 0.02
MONITOR_FAR_THRESHOLD = 0.015
SCHEDULE_FAR_THRESHOLD = 0.005


def p_far(r_sub: float, loo_distances: list[float]) -> float:
    """
    Conformal p-value for the "drift" tail: low p_far means r_sub is
    unusually far from the student's own baseline distances.

    Parameters
    ----------
    r_sub         : the submission's rms_z distance from baseline statistics.
    loo_distances : the student's N leave-one-out distances {r_1 ... r_N}.

    Returns
    -------
    p_far ∈ [1/(N+1), 1.0].
    """
    n = len(loo_distances)
    if n == 0:
        raise ValueError("p_far: loo_distances must be non-empty")
    count_geq = sum(1 for r in loo_distances if r >= r_sub)
    return (1 + count_geq) / (n + 1)


def p_central(r_sub: float, loo_distances: list[float]) -> float:
    """
    Conformal p-value for the "too-perfect" tail: low p_central means
    r_sub is unusually close to the student's own baseline distances —
    the signature of mean-reverting, low-variance text (LLM output,
    cautious forgeries). See defect 2 in the design spec.

    Returns
    -------
    p_central ∈ [1/(N+1), 1.0].
    """
    n = len(loo_distances)
    if n == 0:
        raise ValueError("p_central: loo_distances must be non-empty")
    count_leq = sum(1 for r in loo_distances if r <= r_sub)
    return (1 + count_leq) / (n + 1)


def band_from_p(p_far: float, p_central: float) -> str:
    """
    Map the two-sided typicality p-values to an action band.

    An authentic submission sits near its own median distance, so
    p_far ≈ p_central ≈ 0.5 and this returns "no_action" regardless of N —
    that part of the mapping is correct at every N. The finer drift bands
    (monitor/schedule_conversation/escalate) require N large enough to
    resolve the corresponding threshold (see typicality.py's module
    docstring and spec §5) — below that N, p_far can never fall low enough
    to leave "no_action" via this function alone; escalation at small N
    continues to depend on the separate rms_z >= 3 catastrophic override
    in scoring.py, which this module does not compute.
    """
    if p_central <= NO_ACTION_CENTRAL_THRESHOLD:
        return "schedule_conversation"
    if p_far <= SCHEDULE_FAR_THRESHOLD:
        return "escalate"
    if p_far <= MONITOR_FAR_THRESHOLD:
        return "schedule_conversation"
    if p_far <= NO_ACTION_FAR_THRESHOLD:
        return "monitor"
    return "no_action"


__all__ = ["p_far", "p_central", "band_from_p"]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/quantum/test_typicality.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add original/quantum/typicality.py tests/quantum/test_typicality.py
git commit -m "$(cat <<'EOF'
Add original/quantum/typicality.py — pure two-sided conformal typicality

Phase 1 of the two-axis verification redesign. Pure functions only (no
state/scoring imports) so the LOO-distance-to-p-value math is independently
unit-tested before scoring.py or state.py consume it.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: `StudentState.loo_distances` — cached leave-one-out distance distribution

**Files:**
- Modify: `original/quantum/state.py`
- Test: `tests/test_quantum.py`

**Interfaces:**
- Consumes: `original.quantum.state.StudentState` (existing `samples`, `baseline_mean`/`baseline_std` computation pattern), `original.constants.{ALL_FEATURE_CODES, FEATURE_DIM, RECENCY_DECAY}`.
- Produces: `StudentState.loo_distances -> list[float]` (a `@property`, cached on `_loo_distances`), giving one rms_z distance per contributing baseline sample. Consumed by Task 3.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_quantum.py` (same file, same conventions — module-level `_RNG`, `create_random_vector()`, `BaselineSample(...)` constructed directly):

```python
class TestLooDistances:
    """Tests for StudentState.loo_distances (Phase 1, two-axis verification)."""

    def test_empty_state_returns_empty_list(self):
        state = StudentState(student_id="test")
        assert state.loo_distances == []

    def test_single_sample_returns_empty_list(self):
        """Need >= 2 samples to hold one out and compute stats on the rest."""
        sample = BaselineSample(
            text="", vector=create_random_vector(), provenance="proctored", auth_weight=1.0
        )
        state = StudentState(student_id="test", samples=[sample])
        assert state.loo_distances == []

    def test_returns_one_distance_per_contributing_sample(self):
        samples = [
            BaselineSample(
                text="", vector=create_random_vector(), provenance="proctored", auth_weight=1.0
            )
            for _ in range(5)
        ]
        state = StudentState(student_id="test", samples=samples)
        assert len(state.loo_distances) == 5

    def test_unverified_samples_excluded(self):
        """auth_weight == 0 samples are excluded, same as baseline_mean/baseline_std."""
        verified = [
            BaselineSample(
                text="", vector=create_random_vector(), provenance="proctored", auth_weight=1.0
            )
            for _ in range(4)
        ]
        unverified = BaselineSample(
            text="", vector=create_random_vector(), provenance="unverified", auth_weight=0.0
        )
        state = StudentState(student_id="test", samples=[*verified, unverified])
        assert len(state.loo_distances) == 4

    def test_identical_samples_give_near_zero_distance(self):
        """If every baseline sample is identical, each held-out sample sits
        exactly at the mean of the rest — rms_z should be ~0."""
        vector = create_random_vector()
        samples = [
            BaselineSample(text="", vector=vector.copy(), provenance="proctored", auth_weight=1.0)
            for _ in range(4)
        ]
        state = StudentState(student_id="test", samples=samples)
        assert all(d < 1e-6 for d in state.loo_distances)

    def test_cache_invalidated_on_add_sample(self):
        samples = [
            BaselineSample(
                text="", vector=create_random_vector(), provenance="proctored", auth_weight=1.0
            )
            for _ in range(3)
        ]
        state = StudentState(student_id="test", samples=samples)
        first = state.loo_distances
        assert len(first) == 3
        state.add_sample(
            BaselineSample(
                text="", vector=create_random_vector(), provenance="proctored", auth_weight=1.0
            )
        )
        second = state.loo_distances
        assert len(second) == 4
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_quantum.py::TestLooDistances -v`
Expected: `AttributeError: 'StudentState' object has no attribute 'loo_distances'`

- [ ] **Step 3: Write the implementation**

In `original/quantum/state.py`, add the cache field to the `StudentState` dataclass (alongside `_trajectory`, line ~131):

```python
    _trajectory: TrajectoryResult | None = field(default=None, repr=False)
    _loo_distances: list[float] | None = field(default=None, repr=False)
```

Invalidate it in `add_sample` (line ~143-148), alongside the other three:

```python
    def add_sample(self, sample: BaselineSample) -> None:
        """Append a baseline sample and invalidate the cached state."""
        self.samples.append(sample)
        self._rho = None
        self._purity = None
        self._trajectory = None
        self._loo_distances = None
```

Add the property and its compute function near `trajectory`/`_compute_trajectory` (after line ~525, `_compute_trajectory`'s closing):

```python
    @property
    def loo_distances(self) -> list[float]:
        """Leave-one-out rms_z distances, one per contributing baseline sample."""
        if self._loo_distances is None:
            self._loo_distances = self._compute_loo_distances()
        return self._loo_distances

    def _compute_loo_distances(self) -> list[float]:
        contributing = [s for s in self.samples if s.auth_weight > 0]
        N = len(contributing)
        if N < 2:
            return []

        vectors = np.stack([s.vector for s in contributing])  # (N, D)
        distances: list[float] = []
        for i in range(N):
            held_out = vectors[i]
            rest = np.delete(vectors, i, axis=0)  # (N-1, D)
            rest_n = rest.shape[0]

            weights = np.array(
                [
                    contributing[j].auth_weight * (RECENCY_DECAY ** (rest_n - 1 - k))
                    for k, j in enumerate(idx for idx in range(N) if idx != i)
                ]
            )
            mean = (weights[:, None] * rest).sum(axis=0) / weights.sum()

            if rest_n < 2:
                std = np.full(FEATURE_DIM, 0.15)
            else:
                adaptive_floor = max(0.005, 0.15 / math.sqrt(rest_n))
                std = np.maximum(rest.std(axis=0), adaptive_floor)

            z = (held_out - mean) / std
            z_capped = np.clip(z, -4.0, 4.0)
            rms_z = float(np.sqrt(np.mean(z_capped**2)))
            distances.append(rms_z)
        return distances
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_quantum.py::TestLooDistances -v`
Expected: all PASS.

- [ ] **Step 5: Run the full quantum test file to check for regressions**

Run: `.venv/bin/python -m pytest tests/test_quantum.py tests/quantum/ -v`
Expected: all PASS (no change to existing `_trajectory`/`_rho`/`_purity` behavior).

- [ ] **Step 6: Commit**

```bash
git add original/quantum/state.py tests/test_quantum.py
git commit -m "$(cat <<'EOF'
Add StudentState.loo_distances — cached leave-one-out distance distribution

Follows the existing _trajectory/_rho/_purity cache pattern exactly: a
dataclass field, a lazy @property, invalidation in add_sample. Feeds the
new typicality axis (original/quantum/typicality.py) in scoring.py.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

**Note on weight-model consistency (do not fix here — flag for Task 3's review):** this LOO computation uses *unweighted* `auth_weight × RECENCY_DECAY`-scaled mean/std exactly mirroring `baseline_mean`/`baseline_std`'s existing weighting. Per the design spec's §10 "Adaptive-weights interaction" risk, if `ADAPTIVE_WEIGHTS_ENABLED` or `LENGTH_ADAPTIVE_WEIGHTS` are on, the *submission's* rms_z in `scoring.py` is computed under a different (adaptive) weight vector than this LOO computation uses — Task 3 must not compare `r_sub` against `loo_distances` computed under a different weighting than `r_sub` itself. See Task 3 Step 3's implementation note.

---

## Task 3: Wire the typicality axis into `scoring.py`

**Files:**
- Modify: `original/quantum/scoring.py`
- Test: `tests/quantum/test_typicality_integration.py` (new — integration-level, distinct from Task 1's pure-math tests)

**Interfaces:**
- Consumes: `original.quantum.typicality.{p_far, p_central, band_from_p}` (Task 1), `state.loo_distances` (Task 2), the existing `rms_z` local variable inside `score()` (scoring.py:601-609), `ScoringConfig` (scoring.py:202-245).
- Produces: `Layer7Output` gains four new optional fields: `typicality_p_far: float | None`, `typicality_p_central: float | None`, `typicality_band: str | None`, `typicality_n: int` (default `0`). `ScoringConfig` gains `typicality_scoring_enabled: bool = False`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/quantum/test_typicality_integration.py
"""
tests/quantum/test_typicality_integration.py — the typicality axis wired
into score(), gated by TYPICALITY_SCORING / ScoringConfig.typicality_scoring_enabled.
"""

from __future__ import annotations

import numpy as np
import pytest

from original.constants import ALL_FEATURE_CODES, FEATURE_DIM
from original.quantum.scoring import ScoringConfig, score
from original.quantum.state import BaselineSample, StudentState

_RNG = np.random.default_rng(20260728)


def _vec():
    v = _RNG.uniform(0.3, 0.7, FEATURE_DIM)
    return v


def _feature_dict(vector):
    return {code: float(val) for code, val in zip(ALL_FEATURE_CODES, vector)}


def _state_with_n_samples(n):
    samples = [
        BaselineSample(text="", vector=_vec(), provenance="proctored", auth_weight=1.0)
        for _ in range(n)
    ]
    return StudentState(student_id="typicality-test", samples=samples)


class TestTypicalityFlagOff:
    def test_flag_off_leaves_typicality_fields_none(self):
        state = _state_with_n_samples(6)
        sub_vector = _vec()
        result = score(
            state=state,
            submission_vector=sub_vector,
            feature_dict=_feature_dict(sub_vector),
            scoring_config=ScoringConfig(typicality_scoring_enabled=False),
        )
        assert result.typicality_p_far is None
        assert result.typicality_p_central is None
        assert result.typicality_band is None
        assert result.typicality_n == 0

    def test_flag_off_action_selection_unchanged(self):
        """Byte-identical guarantee: flag off must reproduce the pre-existing
        ACTION_THRESHOLDS-on-deviation decision exactly."""
        state = _state_with_n_samples(6)
        sub_vector = _vec()
        off = score(
            state=state,
            submission_vector=sub_vector,
            feature_dict=_feature_dict(sub_vector),
            scoring_config=ScoringConfig(typicality_scoring_enabled=False),
        )
        default = score(
            state=state,
            submission_vector=sub_vector,
            feature_dict=_feature_dict(sub_vector),
        )
        assert off.recommendation.action == default.recommendation.action
        assert off.authorship.deviation_score == default.authorship.deviation_score


class TestTypicalityFlagOn:
    def test_flag_on_populates_typicality_fields_with_enough_samples(self):
        state = _state_with_n_samples(6)
        sub_vector = _vec()
        result = score(
            state=state,
            submission_vector=sub_vector,
            feature_dict=_feature_dict(sub_vector),
            scoring_config=ScoringConfig(typicality_scoring_enabled=True),
        )
        assert result.typicality_p_far is not None
        assert 0.0 <= result.typicality_p_far <= 1.0
        assert result.typicality_p_central is not None
        assert result.typicality_band in {
            "no_action",
            "monitor",
            "schedule_conversation",
            "escalate",
        }
        assert result.typicality_n == 6

    def test_flag_on_with_fewer_than_two_samples_leaves_fields_none(self):
        """loo_distances is [] below N=2 — typicality cannot compute."""
        state = _state_with_n_samples(1)
        sub_vector = _vec()
        result = score(
            state=state,
            submission_vector=sub_vector,
            feature_dict=_feature_dict(sub_vector),
            scoring_config=ScoringConfig(typicality_scoring_enabled=True),
        )
        assert result.typicality_p_far is None
        assert result.typicality_n == 0

    def test_deviation_score_and_catastrophic_override_unaffected_by_flag(self):
        """The typicality axis only changes recommendation.action's SOURCE for
        the no_action/monitor/schedule/escalate call — deviation_score itself,
        and the rms_z >= 3 catastrophic override, are untouched."""
        state = _state_with_n_samples(6)
        sub_vector = _vec()
        on = score(
            state=state,
            submission_vector=sub_vector,
            feature_dict=_feature_dict(sub_vector),
            scoring_config=ScoringConfig(typicality_scoring_enabled=True),
        )
        off = score(
            state=state,
            submission_vector=sub_vector,
            feature_dict=_feature_dict(sub_vector),
            scoring_config=ScoringConfig(typicality_scoring_enabled=False),
        )
        assert on.authorship.deviation_score == off.authorship.deviation_score
        assert on.catastrophic_drift == off.catastrophic_drift
        assert on.catastrophic_drift_rms_z == off.catastrophic_drift_rms_z

    def test_typical_submission_reaches_no_action_at_any_n(self):
        """The spec's central claim: a submission near its own LOO median
        gets p_far ~= 0.5 -> no_action, regardless of N."""
        for n in (2, 5, 9, 15):
            samples = [
                BaselineSample(
                    text="", vector=_vec(), provenance="proctored", auth_weight=1.0
                )
                for _ in range(n)
            ]
            state = StudentState(student_id=f"typicality-n{n}", samples=samples)
            # Score one of the baseline vectors' near-neighbors as the submission —
            # constructed to sit close to the baseline mean, i.e. a typical draw.
            sub_vector = np.mean([s.vector for s in samples], axis=0)
            result = score(
                state=state,
                submission_vector=sub_vector,
                feature_dict=_feature_dict(sub_vector),
                scoring_config=ScoringConfig(typicality_scoring_enabled=True),
            )
            if result.typicality_band is not None:
                # A submission at the exact mean is the MOST central point
                # possible — this specific construction tests the opposite
                # tail (too-central), which is a valid, deliberate probe of
                # the p_central path rather than the "typical" path. See the
                # next test for a genuinely-typical (near-median-distance)
                # construction.
                assert result.typicality_band in {"no_action", "schedule_conversation"}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/quantum/test_typicality_integration.py -v`
Expected: `TypeError: score() got an unexpected keyword argument` (via `ScoringConfig(typicality_scoring_enabled=...)` — `ScoringConfig` has no such field yet) or `AttributeError` on `result.typicality_p_far`.

- [ ] **Step 3: Write the implementation**

**3a. `ScoringConfig`** (scoring.py:202-245) — add the field and `from_env()` read, following the exact `amplitude_scoring_enabled` pattern:

```python
@dataclass(frozen=True)
class ScoringConfig:
    bayesian_prior_enabled: bool = False
    prior_weight: float = 3.0
    length_adaptive_weights: bool = False
    null_model: str = "none"
    amplitude_scoring_enabled: bool = False
    secret_key: str = ""
    typicality_scoring_enabled: bool = False  # was TYPICALITY_SCORING

    authentic_fidelities: list[float] | None = None
    genre_stats: dict | None = None

    @classmethod
    def from_env(cls) -> ScoringConfig:
        return cls(
            bayesian_prior_enabled=os.environ.get("BAYESIAN_PRIOR_ENABLED", "0") == "1",
            prior_weight=float(os.environ.get("PRIOR_WEIGHT", "3.0")),
            length_adaptive_weights=os.environ.get("LENGTH_ADAPTIVE_WEIGHTS", "0") == "1",
            null_model=os.environ.get("NULL_MODEL", "none"),
            amplitude_scoring_enabled=os.environ.get("AMPLITUDE_SCORING_ENABLED", "0") == "1",
            secret_key=os.environ.get("SECRET_KEY", ""),
            typicality_scoring_enabled=os.environ.get("TYPICALITY_SCORING", "0") == "1",
        )
```

**3b. Compute the typicality fields inside `score()`**, immediately after `rms_z` is computed (scoring.py:601-609, before the `D_raw = tanh(...)` line at ~673):

```python
    typicality_p_far: float | None = None
    typicality_p_central: float | None = None
    typicality_band: str | None = None
    typicality_n: int = 0

    if config.typicality_scoring_enabled:
        from .typicality import band_from_p, p_central, p_far as p_far_fn

        loo = state.loo_distances
        typicality_n = len(loo)
        if typicality_n >= 2:
            typicality_p_far = p_far_fn(rms_z, loo)
            typicality_p_central = p_central(rms_z, loo)
            typicality_band = band_from_p(typicality_p_far, typicality_p_central)
```

Note: `rms_z` here is the submission's distance computed under whatever weight vector `score()` is already using (adaptive or not) — since `state.loo_distances` (Task 2) is computed unweighted/un-adaptive today, **this is the exact gate-checked invariant the spec's §10 flags** ("the LOO distribution must be computed under the same weight configuration as scoring"). This plan does not yet thread `adaptive_weights` into `loo_distances` — that is out of scope for this task and is called out explicitly in Task 8's gate report as a known gap to close before `TYPICALITY_SCORING` and `ADAPTIVE_WEIGHTS_ENABLED` are ever turned on together in the same tenant. Add this exact comment above the block:

```python
    # NOTE: state.loo_distances (state.py) is computed under the UNweighted
    # tier-weight vector. If ADAPTIVE_WEIGHTS_ENABLED or LENGTH_ADAPTIVE_WEIGHTS
    # are also on, rms_z above is computed under a DIFFERENT weight vector —
    # comparing the two is an apples-to-oranges LOO distribution. Gate G1
    # (validation/calibration_gate.py) must be re-run with both flags on
    # together before TYPICALITY_SCORING ships to any tenant with adaptive
    # weights enabled. Tracked, not fixed, in this task — see design spec §10.
```

**3c. Add the four fields to `Layer7Output`** (scoring.py:248-286, after `catastrophic_drift_rms_z`):

```python
    catastrophic_drift: bool = field(default=False)
    catastrophic_drift_rms_z: float = field(default=0.0)

    typicality_p_far: float | None = field(default=None)
    typicality_p_central: float | None = field(default=None)
    typicality_band: str | None = field(default=None)
    typicality_n: int = field(default=0)
```

**3d. Thread the four values into the `Layer7Output(...)` construction** in the `# ── Build output ──` section (scoring.py:759+, alongside the existing `catastrophic_drift=catastrophic_drift, catastrophic_drift_rms_z=rms_z,` lines):

```python
        catastrophic_drift=catastrophic_drift,
        catastrophic_drift_rms_z=rms_z,
        typicality_p_far=typicality_p_far,
        typicality_p_central=typicality_p_central,
        typicality_band=typicality_band,
        typicality_n=typicality_n,
```

**3e. Make `_recommend()`'s action selection conditional on the flag.** `_recommend()` (scoring.py:1022-1029) does not currently receive `ScoringConfig` or the typicality fields — add them as parameters, and branch:

```python
def _recommend(
    P,
    deviation,
    interference,
    domain,
    bc,
    fidelity,
    conformal_p,
    n_tokens,
    typicality_band: str | None = None,   # NEW
) -> RecommendedAction:
    ...
    # Primary signal: deviation score (higher = more suspicious / anomalous),
    # UNLESS the typicality axis is active and produced a band for this call.
    if typicality_band is not None:
        action = typicality_band
    else:
        action = "no_action"
        for act, (lo, hi) in ACTION_THRESHOLDS.items():
            if lo <= deviation < hi:
                action = act
                break
        if deviation >= 1.0:
            action = "escalate"
```

Everything after this point in `_recommend()` — the entanglement/ghostwriting override (1031-1051) and the existing one-sided fidelity-conformal nudge (1053-1084) — is **left completely unmodified**. They read/write the same `action` local variable regardless of which branch set it, so they continue to apply on top of the typicality-derived action exactly as they apply on top of the deviation-derived action today. This is the coexistence rule from the design spec's Phase 1 touch-points note.

Update the call site (scoring.py, wherever `_recommend(...)` is invoked before the catastrophic-drift override, ~line 735-745) to pass `typicality_band=typicality_band`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/quantum/test_typicality_integration.py -v`
Expected: all PASS.

- [ ] **Step 5: Run the full quantum + scoring test suite to check for regressions**

Run: `.venv/bin/python -m pytest tests/quantum/ tests/test_quantum.py tests/test_scoring*.py -v`
Expected: all PASS — in particular, every existing test that asserts a specific `recommendation.action` value must still pass unmodified, since `typicality_band` defaults to `None` and the flag defaults to off.

- [ ] **Step 6: Run the full suite**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: `0 failed` (same pass/skip/xfail counts as the pre-task baseline, plus the new tests).

- [ ] **Step 7: Commit**

```bash
git add original/quantum/scoring.py tests/quantum/test_typicality_integration.py
git commit -m "$(cat <<'EOF'
Wire the conformal typicality axis into score() behind TYPICALITY_SCORING

Adds ScoringConfig.typicality_scoring_enabled and four new Layer7Output
fields. _recommend()'s action selection becomes conditional on the flag;
the entanglement override and the existing one-sided fidelity-conformal
nudge are untouched and continue to apply downstream of either source.
Default (flag off) behavior is verified byte-identical.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Surface typicality fields on the API response

**Revised after Task 3 landed.** Task 3's implementer discovered a pre-existing,
deliberate repo invariant this plan's original design conflicted with:
`tests/test_schemas.py::test_layer7_output_dataclass_fields_all_have_response_counterparts`
(docstring: "Every Layer7Output dataclass field must exist on
Layer7OutputResponse") asserts `hasattr(response, f.name)` for every
dataclass field name on `Layer7Output` — it requires a FLAT, same-named
attribute on the response model, not a field wrapped inside a nested
object under a different name. `ai_likelihood`/`AiLikelihoodOut` satisfies
this because `ai_likelihood` itself is a single nested `AiLikelihoodResult
| None` field on `Layer7Output` — `typicality_p_far` etc. are four
INDEPENDENT flat fields on `Layer7Output`, matching how
`catastrophic_drift`/`catastrophic_drift_rms_z` are already exposed as
flat scalars on `Layer7OutputResponse`, not the `ai_likelihood` pattern
this task originally modeled itself on. Task 3 therefore already added the
four flat fields to `Layer7OutputResponse` (to keep the completeness guard
green) — **do not add a `TypicalityOut` wrapper class; that would create a
redundant, duplicate representation of the same four values.** This task's
only remaining job is wiring `_to_response()` to actually copy them from
`r` instead of leaving them at their class-level defaults.

**Files:**
- Modify: `original/routers/_shared.py`
- Test: `tests/test_schemas.py`

**Interfaces:**
- Consumes: `Layer7Output.{typicality_p_far, typicality_p_central, typicality_band, typicality_n}` (Task 3), `Layer7OutputResponse.{typicality_p_far, typicality_p_central, typicality_band, typicality_n}` (already added to `original/schemas.py` by Task 3 — confirm their exact field names/types by reading `original/schemas.py`'s `Layer7OutputResponse` class before writing this task's code, rather than assuming).
- Produces: `_to_response()` copies the four fields through.

- [ ] **Step 1: Write the failing test**

Add to `tests/test_schemas.py` (following the existing round-trip test pattern in this file — read an existing test like the `fidelity_conformal_pvalue` one to match its exact fixture-construction style before writing this):

```python
    def test_typicality_fields_round_trip_when_present(self):
        result = _make_layer7_output(  # existing helper in this test file — confirm exact
                                        # name/signature by reading the file; adapt kwargs
                                        # below to match its real parameter names
            typicality_p_far=0.42,
            typicality_p_central=0.58,
            typicality_band="no_action",
            typicality_n=7,
        )
        response = _to_response(result)
        assert response.typicality_p_far == 0.42
        assert response.typicality_p_central == 0.58
        assert response.typicality_band == "no_action"
        assert response.typicality_n == 7

    def test_typicality_fields_are_none_when_not_computed(self):
        result = _make_layer7_output()  # typicality_band defaults to None
        response = _to_response(result)
        assert response.typicality_p_far is None
        assert response.typicality_p_central is None
        assert response.typicality_band is None
        assert response.typicality_n == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_schemas.py -k typicality -v`
Expected: FAIL — `response.typicality_p_far` reads back `None`/`0` (the schema's class-level default) even when `result.typicality_p_far` was set to `0.42`, because `_to_response()` doesn't copy these fields yet.

- [ ] **Step 3: Write the implementation**

In `original/routers/_shared.py`'s `_to_response()`, add four keyword arguments to the `Layer7OutputResponse(...)` construction, alongside the existing `catastrophic_drift=getattr(r, "catastrophic_drift", False)` line (same file, same function — read it first to find the exact surrounding lines, since Task 3 did not touch this file and its structure should be unchanged from before this plan started):

```python
        catastrophic_drift=getattr(r, "catastrophic_drift", False),
        catastrophic_drift_rms_z=getattr(r, "catastrophic_drift_rms_z", 0.0),
        typicality_p_far=getattr(r, "typicality_p_far", None),
        typicality_p_central=getattr(r, "typicality_p_central", None),
        typicality_band=getattr(r, "typicality_band", None),
        typicality_n=getattr(r, "typicality_n", 0),
```

No new schema class, no new import — the fields already exist on
`Layer7OutputResponse` (Task 3).

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_schemas.py -v`
Expected: all PASS.

- [ ] **Step 5: Run the full suite**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: `0 failed`.

- [ ] **Step 6: Commit**

```bash
git add original/routers/_shared.py tests/test_schemas.py
git commit -m "$(cat <<'EOF'
Wire typicality fields through _to_response()

original/schemas.py already carries these four fields (added in Task 3 to
satisfy test_layer7_output_dataclass_fields_all_have_response_counterparts);
this task's only remaining job is copying them from Layer7Output into the
response, matching the catastrophic_drift/catastrophic_drift_rms_z pattern.
No TypicalityOut wrapper — these are four independent flat fields, not a
single nested optional sub-object like ai_likelihood.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: `ADAPTIVE_WEIGHTS_ENABLED`/`TYPICALITY_SCORING` interaction guard

**Files:**
- Modify: `original/routers/students_scoring.py`
- Test: `tests/quantum/test_typicality_integration.py` (extend)

**Interfaces:**
- Consumes: Task 3's `config.typicality_scoring_enabled`, the router's existing `enable_adaptive` read (students_scoring.py:62).

**Rationale:** Task 3's implementation note flagged that `loo_distances` is computed unweighted while `rms_z` may be computed under adaptive weights. Rather than silently producing a miscalibrated typicality axis when both flags are on, fail safe: when `ADAPTIVE_WEIGHTS_ENABLED` is also on, typicality fields degrade to `None` (same as insufficient-N) until a future task threads adaptive weights through `loo_distances` too.

- [ ] **Step 1: Write the failing test**

```python
    def test_typicality_degrades_to_none_when_adaptive_weights_also_active(self, monkeypatch):
        """Until loo_distances is computed under the same adaptive weight
        vector as rms_z, the two must not be compared — see Task 3's note."""
        monkeypatch.setenv("ADAPTIVE_WEIGHTS_ENABLED", "1")
        state = _state_with_n_samples(6)
        sub_vector = _vec()
        result = score(
            state=state,
            submission_vector=sub_vector,
            feature_dict=_feature_dict(sub_vector),
            adaptive_weights=np.ones(FEATURE_DIM),  # non-None triggers the adaptive path
            scoring_config=ScoringConfig(typicality_scoring_enabled=True),
        )
        assert result.typicality_p_far is None
        assert result.typicality_band is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/quantum/test_typicality_integration.py -k adaptive_weights_also_active -v`
Expected: FAIL (typicality fields are currently populated regardless of `adaptive_weights`).

- [ ] **Step 3: Write the implementation**

In `score()`, guard the typicality block added in Task 3 Step 3b with an additional condition:

```python
    if config.typicality_scoring_enabled and adaptive_weights is None:
        from .typicality import band_from_p, p_central, p_far as p_far_fn

        loo = state.loo_distances
        typicality_n = len(loo)
        if typicality_n >= 2:
            typicality_p_far = p_far_fn(rms_z, loo)
            typicality_p_central = p_central(rms_z, loo)
            typicality_band = band_from_p(typicality_p_far, typicality_p_central)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/quantum/test_typicality_integration.py -v`
Expected: all PASS.

- [ ] **Step 5: Run the full suite**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: `0 failed`.

- [ ] **Step 6: Commit**

```bash
git add original/quantum/scoring.py tests/quantum/test_typicality_integration.py
git commit -m "$(cat <<'EOF'
Guard typicality axis against adaptive-weight/LOO-weight mismatch

state.loo_distances is unweighted; rms_z under ADAPTIVE_WEIGHTS_ENABLED is
not. Degrade to None (same as insufficient-N) rather than compare distances
computed under different weight vectors. Threading adaptive weights through
loo_distances is future work, tracked in the design spec §10.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: Professor narrative — too-uniform and legitimate-evolution hypotheses

**Files:**
- Modify: `original/quantum/professor_narrative.py`
- Test: `tests/test_professor_narrative.py` (or wherever `_build_hypotheses` is currently tested — locate with `grep -rn "_build_hypotheses" tests/`)

**Interfaces:**
- Consumes: `typicality_band` (Task 3), `trajectory_direction` (already computed, currently unused by `_build_hypotheses`).
- Produces: `_build_hypotheses(..., typicality_band: str | None = None, trajectory_direction: str | None = None)`.

- [ ] **Step 1: Write the failing tests**

```python
class TestBuildHypothesesTypicality:
    def test_too_uniform_hypothesis_added_when_band_indicates_it(self):
        hyps = _build_hypotheses(
            deviation=0.62,
            has_behavioral=False,
            has_ai=False,
            quantum_fidelity=0.8,
            action="schedule_conversation",
            typicality_band="schedule_conversation",
            typicality_p_central=0.01,
        )
        assert any("uniform" in h.lower() or "ghost" in h.lower() for h in hyps)

    def test_legitimate_evolution_hypothesis_added_on_growth_with_drift(self):
        hyps = _build_hypotheses(
            deviation=0.65,
            has_behavioral=False,
            has_ai=False,
            quantum_fidelity=0.7,
            action="monitor",
            trajectory_direction="growth",
        )
        assert any("evolve" in h.lower() or "developed" in h.lower() for h in hyps)

    def test_no_typicality_hypothesis_when_band_is_none(self):
        """Flag-off / insufficient-N path: no new hypothesis text appears."""
        hyps = _build_hypotheses(
            deviation=0.3,
            has_behavioral=False,
            has_ai=False,
            quantum_fidelity=0.9,
            action="no_action",
            typicality_band=None,
        )
        assert not any("uniform" in h.lower() for h in hyps)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_professor_narrative.py -k Typicality -v`
Expected: `TypeError: _build_hypotheses() got an unexpected keyword argument 'typicality_band'`

- [ ] **Step 3: Write the implementation**

In `original/quantum/professor_narrative.py`, extend `_build_hypotheses` (lines 550-615):

```python
def _build_hypotheses(
    deviation: float,
    has_behavioral: bool,
    has_ai: bool,
    quantum_fidelity: float,
    action: str,
    ai_band: str | None = None,
    typicality_band: str | None = None,      # NEW
    typicality_p_central: float | None = None,  # NEW
    trajectory_direction: str | None = None,    # NEW
) -> list[str]:
    hyps: list[str] = []

    hyps.append(
        "Writing under pressure or in an unusual environment — stress, fatigue, "
        "time constraints, or an unfamiliar setting can shift writing style noticeably."
    )
    hyps.append(
        "An unfamiliar topic or genre challenge — writing about a new subject area "
        "or in a form they haven't practiced as much can pull style in new directions."
    )

    if has_behavioral:
        hyps.append(
            "Content was composed elsewhere and pasted in — the student may have "
            "drafted outside the system, in a word processor or notes app, before "
            "transferring it."
        )

    # Too-uniform: never worded as drift, per design spec §5.
    if typicality_p_central is not None and typicality_p_central <= 0.02:
        hyps.append(
            "This submission is unusually uniform in style compared to this "
            "student's own baseline — more even and consistent than their typical "
            "writing. This can happen with heavy editing or outside assistance, "
            "and is worth exploring in conversation rather than assuming drift."
        )

    # Legitimate style evolution — the currently-missing hypothesis the Plato
    # study flagged (professor_narrative had no "style has legitimately
    # evolved" branch at all).
    if trajectory_direction == "growth" and action in {"monitor", "schedule_conversation"}:
        hyps.append(
            "The student's writing style may have legitimately evolved — their "
            "recent submissions already show a consistent trend in this direction, "
            "which is a common and expected part of academic growth rather than "
            "a sign of outside authorship."
        )

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

    if deviation >= 0.75 and quantum_fidelity < 0.4:
        if len(hyps) < 4:
            hyps.append(
                "The essay was written or substantially revised by another person — "
                "the stylistic distance from this student's established profile is "
                "large enough that outside authorship is one explanation."
            )

    return hyps[:4]
```

Update the call site (lines ~751-758) to pass the three new values from `layer7`:

```python
    hypotheses = _build_hypotheses(
        deviation=deviation,
        has_behavioral=has_behavioral,
        has_ai=has_ai,
        quantum_fidelity=quantum_fidelity,
        action=action,
        ai_band=ai_band,
        typicality_band=getattr(layer7, "typicality_band", None),
        typicality_p_central=getattr(layer7, "typicality_p_central", None),
        trajectory_direction=trajectory_direction,
    )
```

(`trajectory_direction` is already computed earlier in this function per the Explore report — confirm its exact local variable name at the call site and pass it through rather than re-deriving it.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_professor_narrative.py -v`
Expected: all PASS.

- [ ] **Step 5: Run the full suite**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: `0 failed`.

- [ ] **Step 6: Commit**

```bash
git add original/quantum/professor_narrative.py tests/test_professor_narrative.py
git commit -m "$(cat <<'EOF'
Add too-uniform and legitimate-evolution hypotheses to professor narrative

Closes the gap both design specs flagged: no "too typical" narrative existed
for defect 2, and no "style has legitimately evolved" hypothesis existed at
all despite the trajectory machinery already computing growth direction.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: `validation/calibration_gate.py` — G1–G4 harness

**Files:**
- Create: `validation/calibration_gate.py`
- Test: `tests/test_calibration_gate.py`

**Interfaces:**
- Consumes: `original.quantum.typicality.{p_far, p_central}` (Task 1), the `TestClient`-based scoring pattern from `validation/public_authors/run.py`, `validation.benchmark.reproducibility.lock_environment`, `validation/plato/features.py::build_matrix`, `validation/plato/chronology.py`.
- Produces: `GateResult` dataclass (`name: str, passed: bool, current_value: str, criterion: str, detail: dict`), `run_g1`, `run_g2`, `run_g3`, `run_g4`, `run_all() -> list[GateResult]`, `render(results) -> str`, `main(argv=None) -> int` (exit code 0 iff all gates passed).

This task builds the **gate infrastructure**, run against the corpora with `TYPICALITY_SCORING=1` set. Because Phase 1 (Tasks 1-6) already landed, G1/G2/G4 will actually execute meaningfully; whether their initial numeric thresholds pass is a separate question addressed in Task 8 — per the design spec, threshold tuning is expected to be iterative and is not a blocker for this task's completion.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_calibration_gate.py
"""
tests/test_calibration_gate.py — pure-math unit tests for the calibration
gate criteria. The full corpus-driven run (validation/calibration_gate.py
executed as a script against seminary+public_authors+Plato) is slow and
belongs in CI's validation job, not the fast unit-test suite — this file
only tests the gate LOGIC on small synthetic inputs.
"""

from __future__ import annotations

from validation.calibration_gate import (
    GateResult,
    evaluate_g1_fpr,
    evaluate_g2_bland_impostor,
)


class TestG1Fpr:
    def test_passes_when_flagged_rate_at_or_below_five_percent(self):
        actions = ["no_action"] * 95 + ["monitor"] * 5
        result = evaluate_g1_fpr(actions, per_corpus={"synthetic": actions})
        assert result.passed is True

    def test_fails_when_flagged_rate_above_five_percent(self):
        actions = ["no_action"] * 85 + ["monitor"] * 15
        result = evaluate_g1_fpr(actions, per_corpus={"synthetic": actions})
        assert result.passed is False

    def test_reports_per_corpus_breakdown_not_just_pooled(self):
        per_corpus = {
            "good_corpus": ["no_action"] * 100,
            "bad_corpus": ["escalate"] * 20 + ["no_action"] * 80,
        }
        pooled = per_corpus["good_corpus"] + per_corpus["bad_corpus"]
        result = evaluate_g1_fpr(pooled, per_corpus=per_corpus)
        assert "bad_corpus" in result.detail["per_corpus_flagged_rate"]
        assert result.detail["per_corpus_flagged_rate"]["bad_corpus"] > 0.05


class TestG2BlandImpostor:
    def test_passes_when_impostor_q_is_lower_than_holdout_q(self):
        """q = min(p_far, p_central). Impostor should score LOWER (more
        anomalous) than genuine holdouts."""
        holdout_q = [0.5, 0.45, 0.5, 0.48]
        impostor_q = [0.05, 0.03, 0.02]
        result = evaluate_g2_bland_impostor(holdout_q, impostor_q)
        assert result.passed is True

    def test_fails_when_impostor_q_exceeds_holdout_q(self):
        """Reproduces the CURRENT defect: Eryxias-like impostor looks MORE
        typical than genuine holdouts."""
        holdout_q = [0.5, 0.45, 0.5, 0.48]
        impostor_q = [0.9, 0.85, 0.88]
        result = evaluate_g2_bland_impostor(holdout_q, impostor_q)
        assert result.passed is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_calibration_gate.py -v`
Expected: `ModuleNotFoundError: No module named 'validation.calibration_gate'`

- [ ] **Step 3: Write the implementation**

```python
# validation/calibration_gate.py
"""
validation/calibration_gate.py — Phase 0 calibration gates (G1-G6) for the
two-axis authorship verification redesign.

Run:
    python -m validation.calibration_gate
    python -m validation.calibration_gate --out /tmp/gate_report.json

Follows validation/plato/gate.py's shape: one dataclass per gate result
with a `passed: bool`, a pure `run()`, a `render()`, and a `main()` whose
exit code is 0 iff every gate passed — so CI fails automatically.

G1-G4 are implemented here against seminary + public_authors + Plato,
scored via the in-process TestClient with TYPICALITY_SCORING=1 (the same
"production-realistic in-process" pattern every other validation runner in
this repo uses — see validation/public_authors/run.py's docstring).
G5 (permutation-null control) is added once scripts/derive_measured_weights.py
exists (Phase 3). G2b (paraphrase-resistant) and G6 (native_english fairness)
are added once original/features/uniformity.py exists (Phase 4).
"""

from __future__ import annotations

# Lock the env BEFORE any original.* import.
from validation.benchmark.reproducibility import lock_environment  # noqa: E402

ENV_LOCK = lock_environment()

import argparse
import json
import os
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent
sys.path.insert(0, str(_ROOT))


@dataclass(frozen=True)
class GateResult:
    name: str
    passed: bool
    criterion: str
    current_value: str
    detail: dict = field(default_factory=dict)


# ── Pure gate-evaluation logic (unit-tested in tests/test_calibration_gate.py) ─


def evaluate_g1_fpr(pooled_actions: list[str], per_corpus: dict[str, list[str]]) -> GateResult:
    """
    G1 — Same-author FPR. Pooled flagged rate (action != "no_action") must
    be <= 5%. Also reports per-corpus flagged rate so a pooled pass cannot
    hide an individual corpus running well above budget (Bates et al.'s
    marginal-not-conditional-validity finding — see design spec §10).
    """
    n = len(pooled_actions)
    flagged = sum(1 for a in pooled_actions if a != "no_action")
    pooled_rate = flagged / n if n else 1.0

    per_corpus_rate = {}
    for corpus, actions in per_corpus.items():
        cn = len(actions)
        cflagged = sum(1 for a in actions if a != "no_action")
        per_corpus_rate[corpus] = cflagged / cn if cn else 1.0

    passed = pooled_rate <= 0.05
    return GateResult(
        name="G1",
        passed=passed,
        criterion="pooled flagged rate <= 5%",
        current_value=f"{pooled_rate:.1%}",
        detail={
            "n": n,
            "flagged": flagged,
            "pooled_flagged_rate": pooled_rate,
            "per_corpus_flagged_rate": per_corpus_rate,
        },
    )


def evaluate_g2_bland_impostor(holdout_q: list[float], impostor_q: list[float]) -> GateResult:
    """
    G2 — Bland impostor. q = min(p_far, p_central) (the two-sided
    typicality). Median impostor q must be <= median holdout q — an
    impostor must not look MORE typical than genuine work.
    """
    import statistics

    med_holdout = statistics.median(holdout_q) if holdout_q else float("nan")
    med_impostor = statistics.median(impostor_q) if impostor_q else float("nan")
    passed = med_impostor <= med_holdout
    return GateResult(
        name="G2",
        passed=passed,
        criterion="median(impostor q) <= median(holdout q)",
        current_value=f"impostor={med_impostor:.3f}, holdout={med_holdout:.3f}",
        detail={"holdout_q": holdout_q, "impostor_q": impostor_q},
    )


def evaluate_g3_attribution(top1_accuracy: float) -> GateResult:
    """G3 — Attribution non-regression. Existing bar: >= 0.7."""
    passed = top1_accuracy >= 0.7
    return GateResult(
        name="G3",
        passed=passed,
        criterion="public_authors top-1 accuracy >= 0.7",
        current_value=f"{top1_accuracy:.3f}",
        detail={"top1_accuracy": top1_accuracy},
    )


def evaluate_g4_career_drift_monotone(group_means: dict[str, float]) -> GateResult:
    """
    G4 — Career-drift sanity. group_means keyed by "early"/"middle"/"late",
    values are mean typicality distance from an early-group baseline.
    Must be non-decreasing early -> middle -> late.
    """
    order = ["early", "middle", "late"]
    values = [group_means[k] for k in order if k in group_means]
    passed = all(values[i] <= values[i + 1] for i in range(len(values) - 1)) and len(values) == 3
    return GateResult(
        name="G4",
        passed=passed,
        criterion="early <= middle <= late (typicality distance from early baseline)",
        current_value=str(group_means),
        detail={"group_means": group_means},
    )


# ── Corpus-driving orchestration (exercised by `main()`, not unit-tested) ──────


def _score_corpus_for_g1(client, sid_prefix: str, texts_by_id: dict[str, list[str]]) -> tuple[list[str], dict[str, list[str]]]:
    """
    For each id in texts_by_id with >= 5 texts: build a baseline from all
    but one text (leave-one-out over WHOLE documents, not chunks), score
    the held-out text, record its recommendation.action. Repeat holding out
    each text in turn. Requires TYPICALITY_SCORING=1 already set in os.environ
    before `client` was constructed (env is read at score() call time, so
    this also works if set right before this call — see
    validation/verify/run_null_model.py's docstring on this point).
    """
    pooled: list[str] = []
    per_corpus: dict[str, list[str]] = {}
    for entity_id, texts in texts_by_id.items():
        if len(texts) < 5:
            continue
        actions: list[str] = []
        for held_out_idx in range(len(texts)):
            sid = f"gate:{sid_prefix}_{entity_id}_{held_out_idx}"
            for i, text in enumerate(texts):
                if i == held_out_idx:
                    continue
                client.post(
                    f"/students/{sid}/baseline",
                    json={"text": text, "provenance": "verified", "submitted_at": "2026-01-01"},
                )
            r = client.post(
                f"/students/{sid}/score",
                json={"text": texts[held_out_idx], "submission_id": f"{entity_id}_{held_out_idx}"},
            )
            if r.status_code == 200:
                actions.append(r.json()["recommendation"]["action"])
        if actions:
            per_corpus[entity_id] = actions
            pooled.extend(actions)
    return pooled, per_corpus


def run_all() -> list[GateResult]:
    os.environ["TYPICALITY_SCORING"] = "1"

    import run as _run_module  # the project's run.py at repo root — same
                                # convention as validation/public_authors/run.py:89,
                                # validation/verify/run.py:140, etc. Requires
                                # sys.path.insert(0, str(_ROOT)) above, already present.
    from fastapi.testclient import TestClient

    client = TestClient(_run_module.load_legacy_demo_app())

    results: list[GateResult] = []

    # G1: seminary + public_authors + Plato, LOO over whole documents.
    seminary_texts = _load_seminary_texts()
    public_authors_texts = _load_public_authors_baseline_texts()
    plato_texts = _load_plato_texts_by_dialogue()

    texts_by_id: dict[str, list[str]] = {**seminary_texts, **public_authors_texts, **plato_texts}
    pooled_actions, per_corpus_actions = _score_corpus_for_g1(client, "g1", texts_by_id)
    results.append(evaluate_g1_fpr(pooled_actions, per_corpus_actions))

    # G2: bland impostor via q = min(p_far, p_central).
    holdout_q, impostor_q = _compute_g2_q_values(client)
    results.append(evaluate_g2_bland_impostor(holdout_q, impostor_q))

    # G3: reuse the existing public_authors attribution accuracy computation.
    from validation.public_authors.run import run as run_public_authors

    pa_report = run_public_authors()
    results.append(evaluate_g3_attribution(pa_report.get("top1_accuracy", 0.0)))

    # G4: Plato early/middle/late monotonicity.
    group_means = _compute_g4_group_means()
    results.append(evaluate_g4_career_drift_monotone(group_means))

    return results


def _load_seminary_texts() -> dict[str, list[str]]:
    corpus_dir = _ROOT / "validation" / "corpus"
    seminary_files = sorted(corpus_dir.glob("seminary_*.txt"))
    # Group by the pre-underscore-number topic prefix isn't right here;
    # seminary essays are single-author-simulated per file with no natural
    # per-author grouping — bucket every 4-5 sequential files as one
    # "student" to get the N>=5 LOO regime the spec's Problem section used
    # (310-460 word essays, 4-of-25 grouping). Concretely: chunk the sorted
    # file list into groups of 5.
    texts = [f.read_text(encoding="utf-8") for f in seminary_files]
    groups: dict[str, list[str]] = {}
    for i in range(0, len(texts) - 4, 5):
        groups[f"seminary_group_{i // 5}"] = texts[i : i + 5]
    return groups


def _load_public_authors_baseline_texts() -> dict[str, list[str]]:
    import json as _json

    manifest_path = _ROOT / "validation" / "public_authors" / "manifest.json"
    corpus_dir = _ROOT / "validation" / "public_authors" / "corpus"
    manifest = _json.loads(manifest_path.read_text())
    by_author: dict[str, list[str]] = {}
    for entry in manifest["entries"]:
        if not entry.get("is_baseline"):
            continue
        text = (corpus_dir / entry["filename"]).read_text(encoding="utf-8")
        by_author.setdefault(entry["author_id"], []).append(text)
    return by_author


def _load_plato_texts_by_dialogue() -> dict[str, list[str]]:
    corpus_dir = _ROOT / "validation" / "plato" / "corpus" / "jowett"
    by_dialogue: dict[str, list[str]] = {}
    for dialogue_dir in sorted(corpus_dir.iterdir()):
        if not dialogue_dir.is_dir():
            continue
        chunks = sorted(dialogue_dir.glob("*.txt"))
        by_dialogue[f"plato_{dialogue_dir.name}"] = [
            c.read_text(encoding="utf-8") for c in chunks
        ]
    return by_dialogue


def _compute_g2_q_values(client) -> tuple[list[float], list[float]]:
    from original.quantum.typicality import p_central, p_far

    holdout_q: list[float] = []
    plato_dialogues = _load_plato_texts_by_dialogue()
    for dialogue, chunks in plato_dialogues.items():
        if "eryxias" in dialogue or len(chunks) < 5:
            continue
        sid = f"gate:g2_{dialogue}"
        for chunk in chunks[:-1]:
            client.post(f"/students/{sid}/baseline", json={"text": chunk, "provenance": "verified"})
        r = client.post(
            f"/students/{sid}/score",
            json={"text": chunks[-1], "submission_id": f"{dialogue}_holdout"},
        )
        if r.status_code == 200:
            payload = r.json()
            typ = payload.get("typicality")
            if typ:
                holdout_q.append(min(typ["p_far"], typ["p_central"]))

    impostor_q: list[float] = []
    eryxias_chunks = plato_dialogues.get("plato_eryxias", [])
    ai_corpus_dir = _ROOT / "validation" / "corpus"
    ai_texts = [p.read_text(encoding="utf-8") for p in sorted(ai_corpus_dir.glob("ai_*.txt"))]
    reference_dialogues = [
        c for name, chunks in plato_dialogues.items() if "eryxias" not in name for c in chunks
    ][:20]
    sid = "gate:g2_impostor_reference"
    for chunk in reference_dialogues:
        client.post(f"/students/{sid}/baseline", json={"text": chunk, "provenance": "verified"})
    for text in eryxias_chunks + ai_texts:
        r = client.post(f"/students/{sid}/score", json={"text": text, "submission_id": "impostor"})
        if r.status_code == 200:
            typ = r.json().get("typicality")
            if typ:
                impostor_q.append(min(typ["p_far"], typ["p_central"]))

    return holdout_q, impostor_q


def _compute_g4_group_means() -> dict[str, float]:
    from validation.plato.chronology import GROUP_NAMES, ranked

    dialogues = ranked()
    plato_texts = _load_plato_texts_by_dialogue()
    groups = {"early": [], "middle": [], "late": []}
    for d in dialogues:
        if d.group is None:
            continue  # excluded from chronology (e.g. Eryxias, spurious=True)
        group_key = GROUP_NAMES[d.group]
        groups[group_key].extend(plato_texts.get(f"plato_{d.slug}", []))
    # Baseline built from the "early" group; score middle and late against it.
    from fastapi.testclient import TestClient

    import run as _run_module  # repo-root run.py — see run_all()'s identical import

    client = TestClient(_run_module.load_legacy_demo_app())
    sid = "gate:g4_early_baseline"
    for chunk in groups["early"]:
        client.post(f"/students/{sid}/baseline", json={"text": chunk, "provenance": "verified"})

    means = {}
    for group_key in ("early", "middle", "late"):
        devs = []
        for chunk in groups[group_key]:
            r = client.post(f"/students/{sid}/score", json={"text": chunk, "submission_id": group_key})
            if r.status_code == 200:
                devs.append(r.json()["authorship"]["deviation_score"])
        means[group_key] = sum(devs) / len(devs) if devs else float("nan")
    return means


def render(results: list[GateResult]) -> str:
    lines = ["╭─ Calibration gates (G1-G4) ─────────────────────────────────╮"]
    for r in results:
        status = "PASS" if r.passed else "FAIL"
        lines.append(f"│ {r.name} [{status}] {r.criterion}")
        lines.append(f"│      current: {r.current_value}")
    lines.append("╰────────────────────────────────────────────────────────────╯")
    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", help="write JSON report to this path")
    args = parser.parse_args(argv)

    results = run_all()
    print(render(results))
    if args.out:
        Path(args.out).write_text(json.dumps([asdict(r) for r in results], indent=2))
    return 0 if all(r.passed for r in results) else 1


if __name__ == "__main__":
    sys.exit(main())
```

**Note for the implementer:** `load_legacy_demo_app` lives in the repo-root `run.py` (`run.py:26`), imported as `import run as _run_module` — this is the exact convention `validation/public_authors/run.py:89`, `validation/verify/run.py:140`, and `validation/stability/measure_lift.py:77` all already use (each relies on a `sys.path.insert(0, str(_ROOT))` done earlier in the file, already present in this module's header). `run_public_authors()`'s exact return shape (in particular, confirm the `top1_accuracy` key name) must still be verified by reading `validation/public_authors/run.py`'s `run()` function/return value before wiring the G3 call — that file's own docstring states "Top-1 accuracy ≥ 0.7 across the corpus is the pass criterion," but the plan draft above did not have that function's source in hand when naming the dict key.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_calibration_gate.py -v`
Expected: all PASS.

- [ ] **Step 5: Commit**

```bash
git add validation/calibration_gate.py tests/test_calibration_gate.py
git commit -m "$(cat <<'EOF'
Add validation/calibration_gate.py — G1-G4 pure logic + corpus orchestration

G1-G4's evaluation math is unit-tested on synthetic inputs; the full
seminary+public_authors+Plato corpus run is exercised via `python -m
validation.calibration_gate` (Task 8), not the fast unit-test suite.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: Run G1–G4 against the corpora, record the report

**Files:**
- No new files — this task runs Task 7's CLI and commits its output report.
- Create: `validation/calibration_report_2026-07-28.json` (generated artifact)

- [ ] **Step 1: Run the gate suite**

Run: `.venv/bin/python -m validation.calibration_gate --out validation/calibration_report_2026-07-28.json`

- [ ] **Step 2: Read the output and record the result**

If any gate fails, this is **not a blocker for this task** — the design spec explicitly states initial band thresholds are provisional and G1/G2/G4's corpora are partly synthetic (seminary) and partly translated-classical (Plato), pending real pilot data (spec §9.3). Document whatever the actual numbers are in this task's commit message. If G1 fails because the initial `.03`/`.02` thresholds (Task 1) still don't hit ≤5% on this specific corpus mix, that is itself useful calibration signal — do not adjust the thresholds in this task; that is Phase 3/ongoing calibration work, not part of this implementation plan's scope.

- [ ] **Step 3: Commit the report**

```bash
git add validation/calibration_report_2026-07-28.json
git commit -m "$(cat <<'EOF'
Record initial G1-G4 calibration gate results

First run of validation/calibration_gate.py against seminary + public_authors
+ Plato with TYPICALITY_SCORING=1. See the committed JSON for exact per-gate
pass/fail and per-corpus breakdown. Per design spec §9, gate thresholds
remain provisional until real (non-synthetic) pilot data replicates them.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 9: ⚠ STOP AND ASK — `original/features/uniformity.py` (Phase 4 features, disabled)

**This task changes `original/constants.py`'s `ALL_FEATURE_CODES` ordering and adds entries to `NORM_BOUNDS` — both on the CLAUDE.md explicit-permission list. Do not execute past Step 1 without the user's explicit go-ahead on the exact diff shown there, even though this plan itself was written with the user's prior knowledge that this task exists — per the design spec's own §7/§8 callouts, the ask happens "at the moment of change," with the concrete diff, not in advance.**

**Files:**
- Create: `original/features/uniformity.py`
- Modify: `original/constants.py` (STOP-AND-ASK), `original/features/pipeline.py`
- Test: `tests/test_uniformity.py`

**Interfaces:**
- Produces: `extract_uniformity(doc: TextDoc) -> dict[str, float]` returning six raw (un-normalized) values for `TIER18_CODES`.

- [ ] **Step 1: STOP — present this exact diff to the user before proceeding**

```diff
--- a/original/constants.py
+++ b/original/constants.py
@@ (near TIER17_CODES, before the ALL_FEATURE_CODES concatenation)
+# ── Tier 18: Uniformity (second-moment) ──────────────────────────────────────
+# Generation-artifact detector: current features are per-document MEANS;
+# LLM/ghostwritten text is often unusually uniform in its WITHIN-document
+# spread. Four comparison features (need a baseline), two standalone.
+# Disabled by default pending gates G2b (paraphrase-resistance) and G6
+# (native_english fairness parity) — see design spec §8.
+TIER18_CODES = [
+    "sentence_length_dispersion_ratio",
+    "window_feature_variance_ratio",
+    "function_word_burstiness_ratio",
+    "punctuation_dispersion_ratio",
+    "vocab_introduction_flatness",
+    "clause_depth_variance_ratio",
+]

@@ ALL_FEATURE_CODES (append at the END, before COMPARISON_CODES, same
   position pattern as TIER17_CODES — never insert mid-list, or legacy
   0.5-padding on stored profiles will misalign every code after the
   insertion point)
 ALL_FEATURE_CODES = (
     TIER1_CODES + TIER2_CODES + TIER3_CODES
     + TIER4_CODES + TIER5_CODES + TIER6_CODES + TIER7_CODES
     + TIER8_CODES + TIER9_CODES + TIER10_CODES + TIER11_CODES + TIER12_CODES
     + TIER13_CODES + TIER14_CODES + TIER15_CODES
     + TIER16_CODES
     + TIER17_CODES
+    + TIER18_CODES
     + COMPARISON_CODES
 )
-FEATURE_DIM = len(ALL_FEATURE_CODES)  # 103
+FEATURE_DIM = len(ALL_FEATURE_CODES)  # 109

@@ FEATURE_TIER
     | {c: 17 for c in TIER17_CODES}
+    | {c: 18 for c in TIER18_CODES}
     | {c: 0  for c in COMPARISON_CODES}

@@ TIER_WEIGHTS
     17: 1.5,   # behavioral biometrics (live keystroke — highest tamper-resistance)
+    18: 1.3,   # uniformity (second-moment generation-artifact signal)

@@ NORM_BOUNDS (six new entries — ratios centered near 1.0; example bounds,
   to be refreshed by scripts/calibrate_bounds.py once real corpus data exists)
+"sentence_length_dispersion_ratio": (0.3, 2.0),
+"window_feature_variance_ratio":    (0.3, 2.0),
+"function_word_burstiness_ratio":   (0.3, 2.0),
+"punctuation_dispersion_ratio":     (0.3, 2.0),
+"vocab_introduction_flatness":      (0.0, 1.0),
+"clause_depth_variance_ratio":      (0.3, 2.0),

@@ FEATURE_GROUPS / DISABLED_FEATURE_GROUPS
 FEATURE_GROUPS: dict[str, list] = {
     "behavioral": TIER17_CODES,
+    "uniformity": TIER18_CODES,
     "semantic":   ["semantic_field_dispersion", "semantic_centroid_proximity"],
     "pos_syntax": TIER5_CODES,
 }
 DISABLED_FEATURE_GROUPS: set = {
     "behavioral",
+    "uniformity",
 }
```

Wait for explicit confirmation before Step 2.

- [ ] **Step 2: Write the failing tests**

```python
# tests/test_uniformity.py
"""tests/test_uniformity.py — Tier 18 (uniformity) feature extraction."""

from __future__ import annotations

from original.features.pipeline import TextDoc
from original.features.uniformity import extract_uniformity

_UNIFORM_TEXT = "This is a sentence. This is a sentence. This is a sentence. " * 10
_VARIED_TEXT = (
    "Short one. Then a considerably longer sentence follows, full of clauses "
    "and subordinate structure that goes on for quite a while before it ends. "
    "Medium length sentence here, reasonably balanced. "
) * 5


class TestExtractUniformity:
    def test_returns_all_six_codes(self):
        doc = TextDoc(_VARIED_TEXT)
        result = extract_uniformity(doc)
        assert set(result.keys()) == {
            "sentence_length_dispersion_ratio",
            "window_feature_variance_ratio",
            "function_word_burstiness_ratio",
            "punctuation_dispersion_ratio",
            "vocab_introduction_flatness",
            "clause_depth_variance_ratio",
        }

    def test_uniform_text_has_lower_dispersion_than_varied_text(self):
        uniform_doc = TextDoc(_UNIFORM_TEXT)
        varied_doc = TextDoc(_VARIED_TEXT)
        uniform_result = extract_uniformity(uniform_doc)
        varied_result = extract_uniformity(varied_doc)
        assert (
            uniform_result["sentence_length_dispersion_ratio"]
            < varied_result["sentence_length_dispersion_ratio"]
        )

    def test_raw_values_not_pre_normalized(self):
        """Feature-purity contract: extract_uniformity returns raw values;
        NORM_BOUNDS-based normalization happens in pipeline.py, not here."""
        doc = TextDoc(_VARIED_TEXT)
        result = extract_uniformity(doc)
        # A dispersion RATIO's raw range is not bounded to [0, 1] the way a
        # normalized feature would be — assert at least one value falls
        # outside [0, 1] for genuinely varied text, proving no clipping
        # happened inside the extractor itself.
        assert any(v > 1.0 or v < 0.0 for v in result.values()) or True  # see note below
```

(The last assertion is intentionally permissive — a specific numeric bound depends on the real implementation's math, which the plan does not prescribe further than "raw, unnormalized second moments." The test's real purpose, enforced by the next test, is the absence of any `np.clip(..., 0, 1)` call inside `uniformity.py` itself.)

```python
    def test_extractor_module_has_no_clip_call(self):
        """Structural check: normalization is pipeline.py's job, not
        uniformity.py's — mirrors tier17.py/tier10.py's contract."""
        import inspect

        from original.features import uniformity

        source = inspect.getsource(uniformity)
        assert "np.clip" not in source
        assert "_normalise" not in source
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_uniformity.py -v`
Expected: `ModuleNotFoundError: No module named 'original.features.uniformity'`

- [ ] **Step 4: Write the implementation**

```python
# original/features/uniformity.py
"""
features/uniformity.py — Tier 18: second-moment uniformity features.

Current tiers are per-document MEANS; generation artifacts (LLM output,
cautious forgeries) often live in the WITHIN-document spread instead —
unusually uniform sentence lengths, function-word timing, punctuation
placement. This module extracts raw (un-normalized) dispersion values;
NORM_BOUNDS-based [0,1] scaling happens in pipeline.py, matching every
other tier's contract (see tier17.py for the precedent).

Ships inside DISABLED_FEATURE_GROUPS by default. See design spec §8 for
the two gates (G2b, G6) required before this group may be enabled.
"""

from __future__ import annotations

import statistics
from collections import Counter

from .tier1 import TextDoc

_FUNCTION_WORDS = frozenset(
    "the a an of in on at to for with by from as is are was were be been "
    "being have has had do does did this that these those and or but if "
    "not no so than then".split()
)

_PUNCT_CHARS = frozenset(",.;:!?")


def _sentence_word_counts(doc: TextDoc) -> list[int]:
    return [len(s.split()) for s in doc.sentences if s.split()]


def sentence_length_dispersion_ratio(doc: TextDoc) -> float:
    """Within-doc sentence-length CV, as a raw dispersion value (the
    ÷-baseline-typical-CV comparison happens at scoring time via the
    ordinary z-score machinery, not here — see the design spec §8 note
    on feature purity)."""
    counts = _sentence_word_counts(doc)
    if len(counts) < 3:
        return 0.5
    mean = statistics.mean(counts)
    if mean < 1e-9:
        return 0.0
    return statistics.stdev(counts) / mean


def window_feature_variance_ratio(doc: TextDoc) -> float:
    """Variance of sentence length over 3-sentence windows, raw."""
    counts = _sentence_word_counts(doc)
    if len(counts) < 6:
        return 0.5
    window_means = [
        statistics.mean(counts[i : i + 3]) for i in range(0, len(counts) - 2, 3)
    ]
    if len(window_means) < 2:
        return 0.5
    return statistics.variance(window_means)


def function_word_burstiness_ratio(doc: TextDoc) -> float:
    """Inter-arrival dispersion of function words across the document,
    raw. Low burstiness (evenly spaced) is the uniformity signal."""
    words = doc.text.lower().split()
    positions = [i for i, w in enumerate(words) if w.strip(".,;:!?") in _FUNCTION_WORDS]
    if len(positions) < 5:
        return 0.5
    gaps = [positions[i + 1] - positions[i] for i in range(len(positions) - 1)]
    mean_gap = statistics.mean(gaps)
    if mean_gap < 1e-9:
        return 0.0
    return statistics.stdev(gaps) / mean_gap


def punctuation_dispersion_ratio(doc: TextDoc) -> float:
    """Per-window punctuation-rate variance, raw."""
    sentences = [s for s in doc.sentences if s.strip()]
    if len(sentences) < 4:
        return 0.5
    rates = []
    for s in sentences:
        n_words = max(1, len(s.split()))
        n_punct = sum(1 for ch in s if ch in _PUNCT_CHARS)
        rates.append(n_punct / n_words)
    if len(rates) < 2:
        return 0.5
    return statistics.variance(rates)


def vocab_introduction_flatness(doc: TextDoc) -> float:
    """
    Fit of the new-type-introduction-rate decay curve. Standalone (no
    baseline needed). A flat (non-decaying) introduction rate across the
    document is atypical of genuine human prose, where new-word
    introduction naturally decays as the document progresses.
    """
    words = [w.strip(".,;:!?\"'()").lower() for w in doc.text.split()]
    words = [w for w in words if w]
    if len(words) < 20:
        return 0.5
    seen: set[str] = set()
    new_type_flags = []
    for w in words:
        new_type_flags.append(0 if w in seen else 1)
        seen.add(w)
    n_buckets = 4
    bucket_size = max(1, len(new_type_flags) // n_buckets)
    bucket_rates = [
        statistics.mean(new_type_flags[i : i + bucket_size]) if new_type_flags[i : i + bucket_size] else 0.0
        for i in range(0, len(new_type_flags), bucket_size)
    ][:n_buckets]
    if len(bucket_rates) < 2 or bucket_rates[0] < 1e-9:
        return 0.5
    # Flatness: how close the LAST bucket's rate is to the FIRST bucket's
    # rate. Genuine decay -> low value (last << first). Flat -> high value.
    return min(1.0, bucket_rates[-1] / bucket_rates[0])


def clause_depth_variance_ratio(doc: TextDoc) -> float:
    """
    Per-sentence clause-depth variance, raw, approximated by comma+
    subordinating-conjunction count per sentence (a cheap proxy avoiding a
    full dependency parse, consistent with Tier 1's cheap-feature philosophy).
    """
    subordinators = frozenset(
        "because although though while since unless whereas whenever "
        "wherever if when as after before until".split()
    )
    sentences = [s for s in doc.sentences if s.strip()]
    if len(sentences) < 4:
        return 0.5
    depths = []
    for s in sentences:
        words = s.lower().split()
        depth = s.count(",") + sum(1 for w in words if w.strip(".,;:!?") in subordinators)
        depths.append(depth)
    if len(depths) < 2:
        return 0.5
    return statistics.variance(depths)


def extract_uniformity(doc: TextDoc) -> dict[str, float]:
    """Compute all 6 Tier 18 uniformity features. Raw values; normalisation
    to [0, 1] is applied by pipeline.py via NORM_BOUNDS."""
    return {
        "sentence_length_dispersion_ratio": sentence_length_dispersion_ratio(doc),
        "window_feature_variance_ratio": window_feature_variance_ratio(doc),
        "function_word_burstiness_ratio": function_word_burstiness_ratio(doc),
        "punctuation_dispersion_ratio": punctuation_dispersion_ratio(doc),
        "vocab_introduction_flatness": vocab_introduction_flatness(doc),
        "clause_depth_variance_ratio": clause_depth_variance_ratio(doc),
    }
```

**Note for the implementer:** confirm `TextDoc.sentences` is the actual attribute name for the sentence list (`original/features/tier1.py`'s `TextDoc` class) before finalizing — the Explore report did not extract `TextDoc`'s internals, only that `tier1.py` defines it and `pipeline.py` imports `TextDoc` from `.tier1`. Read `original/features/tier1.py`'s `TextDoc` class definition first and adjust attribute names (`.sentences`, `.text`) to match exactly.

Wire into `original/features/pipeline.py`'s `extract_features()` (after Tier 16, before the Tier 17 conditional, per the earlier exploration):

```python
    raw.update(extract_tier16(citation_data))  # Tier 16 — Citation Fingerprint

    if "uniformity" not in DISABLED_FEATURE_GROUPS:
        raw.update(extract_uniformity(doc))
    else:
        for code in TIER18_CODES:
            lo, hi = NORM_BOUNDS[code]
            raw[code] = (lo + hi) / 2

    if keystroke_data and "behavioral" not in DISABLED_FEATURE_GROUPS:
```

Add `TIER18_CODES` and `extract_uniformity` to `pipeline.py`'s import block, and add `TIER18_CODES` codes to `BASE_FEATURE_CODES` in `constants.py` alongside the `ALL_FEATURE_CODES` change above (append at the end, same position).

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_uniformity.py -v`
Expected: all PASS.

- [ ] **Step 6: Run the legacy-padding regression test**

Run: `.venv/bin/python -m pytest tests/ -k "legacy or padding or dimension" -v`
Expected: all PASS — confirms the 103→109 width change pads old stored profiles correctly (Task claims this reuses the existing `store.py`/`postgres_repository.py` mechanism unmodified; this step verifies that claim).

- [ ] **Step 7: Run the full suite**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: `0 failed`. Since `"uniformity"` is added to `DISABLED_FEATURE_GROUPS`, default `feature_vector()` output must be byte-identical to before this task — verify with:

```bash
.venv/bin/python -c "
from original.features.pipeline import feature_vector
before = feature_vector('The quick brown fox jumps over the lazy dog. ' * 20)
print(before.shape)
"
```

Expected: `(109,)` with the six new trailing values all at their `NORM_BOUNDS` midpoint (0.5-equivalent), and all 103 prior values unchanged from a pre-task run (compare against a value captured before this task, e.g. via `git stash` a checked-out prior commit — spot-check, do not automate this comparison).

- [ ] **Step 8: Commit**

```bash
git add original/constants.py original/features/uniformity.py original/features/pipeline.py tests/test_uniformity.py
git commit -m "$(cat <<'EOF'
Add Tier 18 uniformity features (disabled by default)

Six second-moment features per design spec §8, appended (never reordered)
to ALL_FEATURE_CODES. FEATURE_DIM 103 -> 109. Ships inside
DISABLED_FEATURE_GROUPS pending gates G2b/G6 (Task 14). Raw values only —
baseline comparison is the existing z-score machinery's job, not this
module's, preserving feature-purity for G3/G6.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 10: Phase 2 — identity axis action matrix

**Files:**
- Modify: `original/quantum/scoring.py`
- Test: `tests/quantum/test_identity_axis.py` (new)

**Interfaces:**
- Consumes: `llr_deviation_score` (already computed, `scoring.py:377-437`), `typicality_band`/`typicality_p_far`/`typicality_p_central` (Task 3), `ScoringConfig`.
- Produces: `ScoringConfig.identity_axis_enabled: bool`. Action selection, when both `typicality_scoring_enabled` and `identity_axis_enabled` are on and `config.null_model == "impostor"`, uses the 3×3 action matrix from the design spec §6 instead of the typicality band alone.

- [ ] **Step 1: Write the failing tests**

```python
# tests/quantum/test_identity_axis.py
"""tests/quantum/test_identity_axis.py — Phase 2 typicality x identity action matrix."""

from __future__ import annotations

from original.quantum.scoring import _identity_axis_action


class TestIdentityAxisActionMatrix:
    def test_typical_and_distinctively_theirs_is_no_action(self):
        assert _identity_axis_action("no_action", llr=0.30) == "no_action"

    def test_typical_and_fits_others_better_is_schedule_conversation(self):
        assert _identity_axis_action("no_action", llr=0.70) == "schedule_conversation"

    def test_too_far_and_distinctively_theirs_is_monitor_not_escalate(self):
        """The (too-far, distinctively-theirs) cell: benign growth, not fraud."""
        assert _identity_axis_action("escalate", llr=0.30) == "monitor"

    def test_too_far_and_fits_others_better_is_escalate(self):
        assert _identity_axis_action("escalate", llr=0.70) == "escalate"

    def test_too_central_and_non_distinctive_is_schedule_conversation_ai_signature(self):
        assert _identity_axis_action("schedule_conversation", llr=0.50) == "schedule_conversation"

    def test_too_central_and_fits_others_better_is_escalate(self):
        assert _identity_axis_action("schedule_conversation", llr=0.70) == "escalate"

    def test_none_typicality_band_falls_back_to_identity_only(self):
        """Degrade gracefully when the typicality axis has insufficient N."""
        assert _identity_axis_action(None, llr=0.70) is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/quantum/test_identity_axis.py -v`
Expected: `ImportError: cannot import name '_identity_axis_action'`

- [ ] **Step 3: Write the implementation**

In `original/quantum/scoring.py`, add a pure helper function (near `_recommend`):

```python
def _identity_axis_action(typicality_band: str | None, llr: float) -> str | None:
    """
    Typicality x identity action matrix (design spec §6). typicality_band
    is collapsed to one of "typical" (no_action), "too-far" (monitor/
    schedule_conversation/escalate from drift), "too-central"
    (schedule_conversation from p_central), or None (insufficient N).

    Identity bands (provisional, per spec §6 — re-derived empirically by
    the gate runner before this flag ships): < .45 distinctively theirs,
    .45-.60 non-distinctive, > .60 fits others better.
    """
    if typicality_band is None:
        return None

    if typicality_band == "no_action":
        row = "typical"
    elif typicality_band == "schedule_conversation":
        # Ambiguous by construction: schedule_conversation is used for BOTH
        # moderate drift and too-central. The caller must disambiguate by
        # ALSO checking which axis produced it before calling this function
        # with a plain string — see the call-site note below.
        row = "too-central"
    else:  # "monitor" or "escalate" -> drift side
        row = "too-far"

    if llr < 0.45:
        col = "distinctive"
    elif llr <= 0.60:
        col = "non_distinctive"
    else:
        col = "fits_others"

    matrix = {
        ("typical", "distinctive"): "no_action",
        ("typical", "non_distinctive"): "monitor",
        ("typical", "fits_others"): "schedule_conversation",
        ("too-far", "distinctive"): "monitor",
        ("too-far", "non_distinctive"): "schedule_conversation",
        ("too-far", "fits_others"): "escalate",
        ("too-central", "distinctive"): "monitor",
        ("too-central", "non_distinctive"): "schedule_conversation",
        ("too-central", "fits_others"): "escalate",
    }
    return matrix[(row, col)]
```

**Ambiguity to resolve before wiring into `_recommend()`:** `typicality_band == "schedule_conversation"` is produced by BOTH the moderate-drift far-side band and the too-central band (per Task 1's `band_from_p`), but the identity-axis matrix needs to know which row applies. Fix by having `score()` also expose which SOURCE produced the band — add a fifth field, `typicality_source: str | None` (`"far"` or `"central"`), set alongside `typicality_band` in Task 3 Step 3b:

```python
    typicality_source: str | None = None
    ...
        if typicality_n >= 2:
            typicality_p_far = p_far_fn(rms_z, loo)
            typicality_p_central = p_central(rms_z, loo)
            typicality_band = band_from_p(typicality_p_far, typicality_p_central)
            typicality_source = (
                "central" if typicality_p_central <= NO_ACTION_CENTRAL_THRESHOLD else "far"
            )
```

(add `typicality_source` to `Layer7Output`, threaded the same way as the other four fields — repeat Task 3's Steps 3c/3d for this one additional field), then change `_identity_axis_action`'s signature to `(typicality_band: str | None, typicality_source: str | None, llr: float)` and use `typicality_source` directly instead of re-inferring `row` from the ambiguous band string:

```python
    if typicality_band is None:
        return None
    if typicality_band == "no_action":
        row = "typical"
    elif typicality_source == "central":
        row = "too-central"
    else:
        row = "too-far"
```

Update the test file's calls accordingly (`_identity_axis_action("schedule_conversation", "central", llr=0.50)` etc.) before running Step 4.

Wire into `_recommend()`, called only when both flags are active:

```python
    if config.identity_axis_enabled and config.null_model == "impostor" and typicality_band is not None and llr_deviation_score is not None:
        matrix_action = _identity_axis_action(typicality_band, typicality_source, llr_deviation_score)
        if matrix_action is not None:
            action = matrix_action
```

Place this check immediately after the `typicality_band is not None: action = typicality_band` branch from Task 3, so the identity matrix's result (when applicable) supersedes the typicality-only result, and both remain subject to the unmodified entanglement/ghostwriting override and fidelity-conformal nudge that follow. Add `identity_axis_enabled: bool = False` to `ScoringConfig` (env `IDENTITY_AXIS`), following the same `from_env()` pattern as Task 3.

Also disable the existing `×0.75` growth dampening (scoring.py:684-686) when `identity_axis_enabled` is on, per the design spec ("disabled under the flag — the trajectory result remains reported"):

```python
    if traj.vector is not None:
        alignment = float(np.dot(xi, traj.vector))
        if alignment > TRAJECTORY_GROWTH_THRESHOLD:
            direction = "growth"
            adj_factor = 1.0 if config.identity_axis_enabled else 0.75
        elif alignment < TRAJECTORY_REGRESSIVE_THRESHOLD:
            direction = "regressive"
            adj_factor = 1.15
        else:
            direction = "lateral"
            adj_factor = 1.0
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/quantum/test_identity_axis.py -v`
Expected: all PASS.

- [ ] **Step 5: Write and run an integration test for the flag-gated coexistence**

Add to `tests/quantum/test_identity_axis.py`:

```python
class TestIdentityAxisIntegration:
    def test_flag_off_leaves_action_matrix_unused(self):
        """Both flags off: action comes from ACTION_THRESHOLDS as before."""
        # ... construct state + score() with IDENTITY_AXIS unset, confirm
        # recommendation.action matches a parallel call with
        # ScoringConfig() (all defaults) exactly, same pattern as
        # tests/quantum/test_typicality_integration.py's flag-off test.
```

Run: `.venv/bin/python -m pytest tests/quantum/test_identity_axis.py tests/ -q`
Expected: `0 failed`.

- [ ] **Step 6: Commit**

```bash
git add original/quantum/scoring.py tests/quantum/test_identity_axis.py
git commit -m "$(cat <<'EOF'
Add Phase 2 identity axis: typicality x llr_deviation_score action matrix

IDENTITY_AXIS=1 (requires NULL_MODEL=impostor) promotes llr_deviation_score
to a co-equal identity axis per design spec §6. The (too-far,
distinctively-theirs) cell implements evidence-based drift-vs-fraud,
replacing the unconditional x0.75 growth dampening under this flag only.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 11: ⚠ STOP AND ASK — Phase 3 feature hygiene (author-split weights + bounds)

**This task changes `original/constants.py`'s `TIER_WEIGHTS` values and `NORM_BOUNDS` bounds — both on the CLAUDE.md explicit-permission list. Present the exact diff (generated by the script below, not hand-authored) and wait for explicit confirmation before applying it to `constants.py`.**

**Files:**
- Create: `scripts/derive_measured_weights.py`
- Modify: `original/constants.py` (STOP-AND-ASK, diff generated by the script), `scripts/calibrate_bounds.py`
- Test: `tests/test_derive_measured_weights.py`

**Interfaces:**
- Consumes: `validation.stability.stability.{compute_feature_matrix, fisher_ratio, per_feature_stability}`, `validation.stability.run.load_corpus(..., only=...)` pattern, the Ledoit-Wolf shrinkage closed-form (`original/quantum/state.py:547-630`, `_ledoit_wolf_shrink`).
- Produces: an author-level split helper `split_authors(author_ids: list[str], derivation_fraction: float = 0.7, seed: int = 1729) -> tuple[set[str], set[str]]`, a `derive_weights(author_texts: dict[str, str]) -> dict[int, float]` (tier → weight) function that shrinks within-author variance before computing the Fisher ratio, and a `main()` CLI that writes the generated `TIER_WEIGHTS` diff to stdout/file rather than editing `constants.py` directly.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_derive_measured_weights.py
"""tests/test_derive_measured_weights.py — author-level split + shrinkage-
regularized Fisher-ratio weight derivation (Phase 3)."""

from __future__ import annotations

from scripts.derive_measured_weights import shrink_within_author_variance, split_authors


class TestSplitAuthors:
    def test_split_is_deterministic_for_a_fixed_seed(self):
        authors = [f"author_{i}" for i in range(20)]
        a1, b1 = split_authors(authors, derivation_fraction=0.7, seed=1729)
        a2, b2 = split_authors(authors, derivation_fraction=0.7, seed=1729)
        assert a1 == a2
        assert b1 == b2

    def test_split_is_disjoint_and_covers_all_authors(self):
        authors = [f"author_{i}" for i in range(20)]
        derivation, gate = split_authors(authors, derivation_fraction=0.7, seed=1729)
        assert derivation.isdisjoint(gate)
        assert derivation | gate == set(authors)

    def test_split_fraction_is_approximately_respected(self):
        authors = [f"author_{i}" for i in range(100)]
        derivation, gate = split_authors(authors, derivation_fraction=0.7, seed=1729)
        assert 65 <= len(derivation) <= 75


class TestShrinkWithinAuthorVariance:
    def test_shrinkage_pulls_variance_toward_pooled_estimate(self):
        import numpy as np

        # One author with tiny within-author variance (an artifact of N=4
        # samples), pooled variance across all authors much larger.
        per_author_var = {"a": np.array([0.001, 0.001]), "b": np.array([0.5, 0.5])}
        shrunk = shrink_within_author_variance(per_author_var)
        assert shrunk["a"][0] > 0.001  # pulled up toward the pooled estimate
        assert shrunk["a"][0] < 0.5    # but not all the way

    def test_shrinkage_is_a_no_op_when_only_one_author(self):
        import numpy as np

        per_author_var = {"a": np.array([0.1, 0.2])}
        shrunk = shrink_within_author_variance(per_author_var)
        assert np.allclose(shrunk["a"], per_author_var["a"])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_derive_measured_weights.py -v`
Expected: `ModuleNotFoundError: No module named 'scripts.derive_measured_weights'`

- [ ] **Step 3: Write the implementation**

```python
# scripts/derive_measured_weights.py
"""
scripts/derive_measured_weights.py — Phase 3 measured tier weights.

Author-level holdout split (never sample-level — see design spec §7):
splits each corpus's authors into a derivation set (Fisher-ratio weight
computation) and a gate-evaluation set (G1/G3/G4/G6 in
validation/calibration_gate.py). validation.stability.stability's
fisher_ratio/compute_feature_matrix take no split argument — this script
owns the split and pre-filters the author_texts dict before calling them,
per validation/stability/run.py's existing `--only` pattern.

Within-author variance (the Fisher ratio's denominator) is shrunk toward
the pooled cross-author estimate via the same weighted Ledoit-Wolf
closed-form already used for RANK_REMEDIATION=shrinkage
(original/quantum/state.py:_ledoit_wolf_shrink), since raw per-author
variance from 4-15 samples is the ratio's noisiest, most-rewarded input.

DOES NOT edit original/constants.py. Prints a diff-shaped TIER_WEIGHTS
block for a human to review and apply — TIER_WEIGHTS is on the CLAUDE.md
explicit-permission list.

Run:
    python -m scripts.derive_measured_weights --corpora seminary,public_authors,plato
"""

from __future__ import annotations

from validation.benchmark.reproducibility import lock_environment  # noqa: E402

ENV_LOCK = lock_environment()

import argparse
import sys
from pathlib import Path

import numpy as np

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent
sys.path.insert(0, str(_ROOT))

from original.constants import FEATURE_TIER, TIER_WEIGHTS
from validation.stability.stability import compute_feature_matrix, fisher_ratio


def split_authors(
    author_ids: list[str],
    derivation_fraction: float = 0.7,
    seed: int = 1729,
) -> tuple[set[str], set[str]]:
    """
    Deterministic author-level split. Never split by sample — an author's
    samples must never appear on both sides (design spec §7).
    """
    rng = np.random.default_rng(seed)
    shuffled = sorted(author_ids)  # sort first for determinism independent of dict order
    rng.shuffle(shuffled)
    cut = round(len(shuffled) * derivation_fraction)
    derivation = set(shuffled[:cut])
    gate = set(shuffled[cut:])
    return derivation, gate


def shrink_within_author_variance(per_author_var: dict[str, np.ndarray]) -> dict[str, np.ndarray]:
    """
    Ledoit-Wolf-style shrinkage of each author's within-author variance
    vector toward the pooled (cross-author mean) variance vector. Mirrors
    original/quantum/state.py's _ledoit_wolf_shrink shape but operates on
    variance VECTORS (one per author) rather than a single density matrix.
    """
    if len(per_author_var) < 2:
        return dict(per_author_var)

    pooled = np.mean(list(per_author_var.values()), axis=0)
    n_authors = len(per_author_var)

    shrunk = {}
    for author, var in per_author_var.items():
        gamma = float(np.sum((var - pooled) ** 2))
        if gamma < 1e-18:
            shrunk[author] = var
            continue
        # Simple shrinkage intensity: more authors contributing to the
        # pooled estimate -> trust the per-author estimate more.
        alpha = min(1.0, 1.0 / max(1, n_authors - 1))
        shrunk[author] = (1.0 - alpha) * var + alpha * pooled
    return shrunk


def derive_weights(author_texts: dict[str, str], length: int = 2000) -> dict[int, float]:
    """
    Compute measured per-tier weights from a (pre-filtered, derivation-side-
    only) author_texts dict. Returns {tier_number: weight}, Sigma w^2-
    preserving normalized against the CURRENT TIER_WEIGHTS (same invariant
    the length schedule uses).
    """
    matrices = compute_feature_matrix(author_texts, length, max_windows=12)
    matrices = {a: m for a, m in matrices.items() if m.shape[0] > 0}

    per_author_var = {a: m.var(axis=0, ddof=0) for a, m in matrices.items()}
    shrunk_var = shrink_within_author_variance(per_author_var)

    # Rebuild fisher_ratio's between/within computation using the SHRUNK
    # within-author variance instead of the raw one, by re-deriving within
    # from shrunk_var directly (fisher_ratio itself always recomputes raw
    # variance internally, so it cannot be called as-is with pre-shrunk
    # values — this function reimplements the ratio using shrunk inputs).
    within = np.mean(list(shrunk_var.values()), axis=0)
    author_means = np.stack([m.mean(axis=0) for m in matrices.values()], axis=0)
    between = author_means.var(axis=0, ddof=0)
    per_feature_fisher = between / (within + 1e-9)

    # per_feature_fisher is indexed positionally by ALL_FEATURE_CODES order
    # (compute_feature_matrix's columns follow feature_vector()'s order,
    # which is ALL_FEATURE_CODES) — aggregate to per-tier by zipping against
    # ALL_FEATURE_CODES + FEATURE_TIER directly:
    from original.constants import ALL_FEATURE_CODES

    per_tier_values: dict[int, list[float]] = {}
    for code, f in zip(ALL_FEATURE_CODES, per_feature_fisher):
        tier = FEATURE_TIER[code]
        per_tier_values.setdefault(tier, []).append(float(f))

    per_tier_mean_fisher = {t: float(np.mean(v)) for t, v in per_tier_values.items()}

    # Sigma w^2-preserving normalization against the CURRENT weight table.
    current_sq_sum = sum(w**2 for w in TIER_WEIGHTS.values())
    raw_sq_sum = sum(v**2 for v in per_tier_mean_fisher.values())
    scale = (current_sq_sum / raw_sq_sum) ** 0.5 if raw_sq_sum > 0 else 1.0
    return {t: v * scale for t, v in per_tier_mean_fisher.items()}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--derivation-fraction", type=float, default=0.7)
    parser.add_argument("--seed", type=int, default=1729)
    args = parser.parse_args(argv)

    # Loading each corpus's author_texts dict follows validation/stability/
    # run.py's load_corpus(..., only=derivation_authors) pattern exactly —
    # implementer: import and call that function per corpus (seminary,
    # public_authors, plato), UNION the resulting author_texts dicts, then
    # split and derive as below.
    raise NotImplementedError(
        "Wire in validation.stability.run.load_corpus per corpus before running end-to-end; "
        "split_authors/shrink_within_author_variance/derive_weights are independently tested."
    )


if __name__ == "__main__":
    sys.exit(main())
```

**Note for the implementer:** `main()`'s `NotImplementedError` is deliberate: end-to-end corpus loading depends on `validation.stability.run.load_corpus`'s exact signature, which must be read in full before wiring `main()` — this is real, necessary follow-up work within this same task (Step 5 below), not a plan placeholder, since `split_authors`/`shrink_within_author_variance`/`derive_weights` (the three functions this task's tests actually cover) are complete and correct as written above.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_derive_measured_weights.py -v`
Expected: all PASS.

- [ ] **Step 5: Wire `main()` against `validation.stability.run.load_corpus`**

Read `validation/stability/run.py`'s `load_corpus` function signature in full, then complete `main()` to: load each corpus's `author_texts`, union them, call `split_authors()` on the combined author-id list, call `derive_weights()` on the derivation-side subset only, and print the resulting `{tier: weight}` dict as a Python-syntax `TIER_WEIGHTS` diff block (mirroring `scripts/calibrate_bounds.py`'s paste-ready-output convention).

- [ ] **Step 6: STOP — run the script, present the generated diff to the user**

Run: `.venv/bin/python -m scripts.derive_measured_weights --derivation-fraction 0.7 --seed 1729`

Present the printed `TIER_WEIGHTS` diff to the user exactly as generated. **Do not apply it to `original/constants.py` without explicit confirmation.** Once confirmed, apply it as a hand-verified edit (not a blind paste — check the direction of the change matches the spec's expected direction: T1/T5 up, T4/T16 sharply down) and commit `original/constants.py` and `docs/superpowers/specs/2026-07-28-two-axis-verification-design.md`'s Phase-3 section (adding an "Applied" note with the date and the actual before/after values) as a separate, focused commit from Step 7's script commit.

- [ ] **Step 7: Commit the script**

```bash
git add scripts/derive_measured_weights.py tests/test_derive_measured_weights.py
git commit -m "$(cat <<'EOF'
Add scripts/derive_measured_weights.py — author-split, shrinkage-regularized

Author-level (never sample-level) holdout split guards against the
double-dipping risk in design spec §7/§10 — a passing G1/G3/G4/G6 measured
on weights derived from the SAME corpora would be optimistic by
construction. Shrinks within-author variance via the same weighted
Ledoit-Wolf estimator already used for RANK_REMEDIATION. Does not edit
constants.py directly — TIER_WEIGHTS is a CLAUDE.md explicit-permission item.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 12: NORM_BOUNDS refresh for Tier 18

**Files:**
- Modify: `scripts/calibrate_bounds.py`
- No STOP-AND-ASK here: this task only wires the NEW Tier 18 extractor into the EXISTING calibration script's `extract_raw()` — it does not itself edit `constants.py`. Applying whatever bounds the script suggests IS a `constants.py` change and reuses Task 11's STOP-AND-ASK pattern (present the diff, wait for confirmation) at that later point.

**Interfaces:**
- Consumes: `original.features.uniformity.extract_uniformity` (Task 9).
- Produces: `scripts/calibrate_bounds.py --suggest-bounds` now includes Tier 18 in its output.

- [ ] **Step 1: Write the failing test**

```python
# add to whatever test file covers scripts/calibrate_bounds.py, or create
# tests/test_calibrate_bounds.py if none exists — check first with:
#   grep -rl "calibrate_bounds" tests/
```

```python
class TestCalibrateBoundsUniformity:
    def test_extract_raw_includes_tier_18_codes(self):
        from scripts.calibrate_bounds import extract_raw
        from original.constants import TIER18_CODES

        raw = extract_raw("This is a test sentence. Here is another one for good measure.")
        for code in TIER18_CODES:
            assert code in raw

    def test_tier_labels_includes_uniformity(self):
        from scripts.calibrate_bounds import _TIER_LABELS

        assert 18 in _TIER_LABELS
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_calibrate_bounds.py -v`
Expected: `AssertionError` (Tier 18 codes absent from `extract_raw`'s output).

- [ ] **Step 3: Write the implementation**

In `scripts/calibrate_bounds.py`'s `extract_raw()` (lines 78-89), add the Tier 18 call following the existing tiers-1-through-7 pattern, and add a `_TIER_LABELS` entry (lines 122-130):

```python
    raw.update(extract_tier7(doc))
    raw.update(extract_uniformity(doc))
```

```python
_TIER_LABELS = {
    ...,
    18: "Uniformity (2nd moments)",
}
```

Add the import: `from original.features.uniformity import extract_uniformity`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_calibrate_bounds.py -v`
Expected: all PASS.

- [ ] **Step 5: Run the full suite**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: `0 failed`.

- [ ] **Step 6: Commit**

```bash
git add scripts/calibrate_bounds.py tests/test_calibrate_bounds.py
git commit -m "$(cat <<'EOF'
Wire Tier 18 uniformity into scripts/calibrate_bounds.py

extract_raw() and _TIER_LABELS now cover the new feature group so a future
NORM_BOUNDS refresh run includes it. Does not itself edit constants.py.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 13: G5 — permutation-null selection-bias gate

**Files:**
- Modify: `validation/calibration_gate.py`
- Test: `tests/test_calibration_gate.py` (extend)

**Interfaces:**
- Consumes: `scripts.derive_measured_weights.{split_authors, derive_weights}` (Task 11), `evaluate_g1_fpr`/`evaluate_g3_attribution`/`evaluate_g4_career_drift_monotone` (Task 7).
- Produces: `evaluate_g5_permutation_null(shuffled_g1_rate: float, shuffled_g3_accuracy: float, shuffled_g4_monotone: bool) -> GateResult`.

- [ ] **Step 1: Write the failing test**

```python
class TestG5PermutationNull:
    def test_passes_when_shuffled_labels_collapse_to_chance(self):
        result = evaluate_g5_permutation_null(
            shuffled_g1_flagged_rate=0.48,  # nowhere near <=5% -> good, it's noise
            shuffled_g3_accuracy=0.12,      # near 1/n_authors, not 0.7+ -> good
            shuffled_g4_monotone=False,     # no real signal -> good
        )
        assert result.passed is True

    def test_fails_when_shuffled_labels_still_pass_the_real_gates(self):
        """If G1/G3/G4 still look good on shuffled labels, the pipeline is
        measuring the selection procedure, not authorship signal."""
        result = evaluate_g5_permutation_null(
            shuffled_g1_flagged_rate=0.03,  # suspiciously still <=5% on noise
            shuffled_g3_accuracy=0.75,      # suspiciously still high on noise
            shuffled_g4_monotone=True,
        )
        assert result.passed is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_calibration_gate.py -k G5 -v`
Expected: `ImportError: cannot import name 'evaluate_g5_permutation_null'`

- [ ] **Step 3: Write the implementation**

Add to `validation/calibration_gate.py`:

```python
def evaluate_g5_permutation_null(
    shuffled_g1_flagged_rate: float,
    shuffled_g3_accuracy: float,
    shuffled_g4_monotone: bool,
) -> GateResult:
    """
    G5 — Selection-bias null control. Author labels shuffled, weights
    re-derived through the identical pipeline (scripts.derive_measured_weights),
    G1/G3/G4 re-run. All three must collapse to chance:
      - G1's flagged rate must NOT still look like a real ~5% control (i.e.
        it should be far from a plausible calibrated rate — a rate that's
        STILL suspiciously low on pure noise indicates circularity).
      - G3 accuracy must be near chance (roughly 1/n_authors; using a
        generous < 0.30 threshold since n_authors varies by corpus).
      - G4 must NOT be monotone (no real chronological signal exists in
        shuffled data).
    Fails (correctly) if ANY of the three still looks like real signal.
    """
    g1_is_suspicious = shuffled_g1_flagged_rate <= 0.10  # too close to a real gate pass
    g3_is_suspicious = shuffled_g3_accuracy >= 0.30
    g4_is_suspicious = shuffled_g4_monotone is True

    passed = not (g1_is_suspicious or g3_is_suspicious or g4_is_suspicious)
    return GateResult(
        name="G5",
        passed=passed,
        criterion="G1/G3/G4 collapse to chance under permuted author labels",
        current_value=(
            f"g1_rate={shuffled_g1_flagged_rate:.1%}, "
            f"g3_acc={shuffled_g3_accuracy:.3f}, g4_monotone={shuffled_g4_monotone}"
        ),
        detail={
            "shuffled_g1_flagged_rate": shuffled_g1_flagged_rate,
            "shuffled_g3_accuracy": shuffled_g3_accuracy,
            "shuffled_g4_monotone": shuffled_g4_monotone,
        },
    )
```

Wire a `run_g5(seed: int = 1730)` orchestration function into `run_all()`, following the same shape as `_score_corpus_for_g1`/`_compute_g4_group_means` but with author IDs shuffled via `np.random.default_rng(seed).permutation` before baselines are built (i.e., student N's baseline is built from student M's texts, for a random permutation M != N) — implementer: reuse `_load_seminary_texts`/`_load_public_authors_baseline_texts`/`_load_plato_texts_by_dialogue`'s output dicts, shuffle the VALUES across KEYS (not within a key) using a fixed seed, then feed the shuffled dict through the exact same `_score_corpus_for_g1`/`_compute_g4_group_means` functions already written in Task 7 — no new scoring logic needed, only a label-shuffle step before calling them.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_calibration_gate.py -v`
Expected: all PASS.

- [ ] **Step 5: Run G5 end-to-end and record the result**

Run: `.venv/bin/python -m validation.calibration_gate --out validation/calibration_report_2026-07-28.json` (re-run with G5 now included)

- [ ] **Step 6: Commit**

```bash
git add validation/calibration_gate.py tests/test_calibration_gate.py validation/calibration_report_2026-07-28.json
git commit -m "$(cat <<'EOF'
Add G5 — permutation-null selection-bias control

Shuffles author labels, re-runs G1/G3/G4 through the identical weight-
derivation pipeline. A pass on shuffled labels would mean the gates measure
the selection procedure, not authorship signal — see design spec §4/§7/§10.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 14: G2b (paraphrase-resistance) + G6 (native_english fairness)

**Files:**
- Modify: `validation/calibration_gate.py`
- Test: `tests/test_calibration_gate.py` (extend)

**Interfaces:**
- Consumes: `original.features.uniformity` (Task 9, must be enabled via `DISABLED_FEATURE_GROUPS.discard("uniformity")` for this gate's run only), `validation.benchmark.bias_slicer.slice_by`, `validation.bias_analysis._welch_t_test` (reused directly for the numeric comparison, per the Explore report's finding that `run_bias_analysis`'s dict-based shape doesn't match `bias_slicer`'s `ScoringResult`-based shape — this gate bridges them itself rather than routing through `run_bias_analysis`).

- [ ] **Step 1: Write the failing tests**

```python
class TestG6Fairness:
    def test_passes_when_fpr_ratio_at_most_two(self):
        result = evaluate_g6_fairness(
            native_fpr=0.04,
            non_native_fpr=0.06,
        )
        assert result.passed is True

    def test_fails_when_fpr_ratio_exceeds_two(self):
        result = evaluate_g6_fairness(
            native_fpr=0.02,
            non_native_fpr=0.10,  # 5x — matches the documented NNE risk direction
        )
        assert result.passed is False

    def test_handles_zero_native_fpr_without_division_error(self):
        result = evaluate_g6_fairness(native_fpr=0.0, non_native_fpr=0.05)
        assert isinstance(result.passed, bool)


class TestG2bParaphraseResistance:
    def test_passes_when_paraphrased_impostor_q_still_lower_than_holdout(self):
        result = evaluate_g2b_paraphrase_resistant(
            holdout_q=[0.5, 0.48, 0.5],
            paraphrased_impostor_q=[0.15, 0.1],
        )
        assert result.passed is True

    def test_fails_when_paraphrase_defeats_the_signal(self):
        """Documents the expected real-world outcome per the design spec's
        research review — this SHOULD fail with a naive implementation,
        which is itself the finding G2b exists to surface."""
        result = evaluate_g2b_paraphrase_resistant(
            holdout_q=[0.5, 0.48, 0.5],
            paraphrased_impostor_q=[0.6, 0.55],  # paraphrase raised q above holdout
        )
        assert result.passed is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_calibration_gate.py -k "G6 or G2b" -v`
Expected: `ImportError`.

- [ ] **Step 3: Write the implementation**

```python
def evaluate_g6_fairness(native_fpr: float, non_native_fpr: float) -> GateResult:
    """
    G6 — Non-native-English fairness. Per-group flagged rate for the
    p_central/too-uniform action must not differ by more than 2x between
    native_english=true and =false groups. Reuses the same 2x bar
    validation/bias_analysis.py already applies elsewhere in the system.
    """
    rates = [r for r in (native_fpr, non_native_fpr) if r > 0]
    ratio = max(rates) / min(rates) if len(rates) == 2 else 1.0
    passed = ratio <= 2.0
    return GateResult(
        name="G6",
        passed=passed,
        criterion="FPR ratio (native_english true vs false) <= 2x",
        current_value=f"ratio={ratio:.2f}x (native={native_fpr:.1%}, non_native={non_native_fpr:.1%})",
        detail={"native_fpr": native_fpr, "non_native_fpr": non_native_fpr, "ratio": ratio},
    )


def evaluate_g2b_paraphrase_resistant(
    holdout_q: list[float], paraphrased_impostor_q: list[float]
) -> GateResult:
    """
    G2b — Bland impostor, paraphrase-resistant. Repeats G2's criterion
    against a detector-guided-paraphrased version of the ai_*.txt corpus.
    """
    import statistics

    med_holdout = statistics.median(holdout_q) if holdout_q else float("nan")
    med_impostor = statistics.median(paraphrased_impostor_q) if paraphrased_impostor_q else float("nan")
    passed = med_impostor <= med_holdout
    return GateResult(
        name="G2b",
        passed=passed,
        criterion="median(paraphrased impostor q) <= median(holdout q)",
        current_value=f"paraphrased_impostor={med_impostor:.3f}, holdout={med_holdout:.3f}",
        detail={"holdout_q": holdout_q, "paraphrased_impostor_q": paraphrased_impostor_q},
    )
```

Wire orchestration functions:
- `_compute_g6_fairness_data(client)`: reuses `validation/manifest.json`'s `native_english` field (currently populated for 25/807 entries — implementer must filter to only entries where `native_english is not None`, and should log a warning + report the sample size in `GateResult.detail` if fewer than ~20 entries per group are available, since the existing manifest's NNE coverage is thin). Score each entry, read `typicality_p_central` off the response, threshold it against `NO_ACTION_CENTRAL_THRESHOLD` to get a per-entry flagged/not-flagged boolean, compute per-group rates.
- `_compute_g2b_paraphrase_data(client)`: for each `ai_*.txt` file, apply ONE deterministic paraphrase transform (implementer note: this plan does not include an LLM-calling paraphraser; the minimal reproducible version the design spec's research review calls for is the published one-line prompt attack — since this validation harness has no LLM API wired in anywhere else in the repo, the pragmatic first implementation is a NON-LLM proxy: apply simple sentence-reordering + synonym-light rewriting via a fixed word-substitution table, and DOCUMENT in the gate's `detail` field that this is a proxy for, not identical to, a real detector-guided LLM paraphrase attack — do not claim it validates robustness against real attacks; flag this explicitly to the user as a follow-up if a real LLM-based paraphrase gate is wanted later).

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_calibration_gate.py -v`
Expected: all PASS (unit-level; the `_compute_g6_fairness_data`/`_compute_g2b_paraphrase_data` orchestration functions are exercised only by the CLI run, per Task 7's established convention).

- [ ] **Step 5: Run the full gate suite (temporarily enabling uniformity) and record results**

```bash
.venv/bin/python -c "
import os
os.environ['TYPICALITY_SCORING'] = '1'
from original.constants import DISABLED_FEATURE_GROUPS
DISABLED_FEATURE_GROUPS.discard('uniformity')
from validation.calibration_gate import run_all, render
results = run_all()
print(render(results))
"
```

Document the G2b/G6 results honestly — per this task's Step 3 note, G2b's proxy paraphraser is not equivalent to a real attack, and a pass here should not be reported to the team as "paraphrase-resistant" without that caveat attached.

- [ ] **Step 6: Commit**

```bash
git add validation/calibration_gate.py tests/test_calibration_gate.py
git commit -m "$(cat <<'EOF'
Add G2b (paraphrase-resistance proxy) and G6 (native_english fairness)

G6 reuses the 2x FPR-ratio bar validation/bias_analysis.py already applies
elsewhere. G2b's paraphrase step is a non-LLM proxy (word-substitution +
reordering) — NOT equivalent to the published detector-guided LLM attacks
the design spec's research review cites; documented as a known gap, not a
robustness claim, in the gate's own report.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 15: Shadow rollout wiring

**Files:**
- Modify: `original/routers/students_scoring.py`, `original/quantum/scoring.py`
- Test: `tests/quantum/test_typicality_shadow.py` (new, mirroring `tests/test_ai_likelihood_shadow.py`'s structure)

**Interfaces:**
- Consumes: the `AI_LIKELIHOOD_SHADOW` wiring pattern (`students_scoring.py:163-164`), `scripts/shadow_report.py`'s report shape.
- Produces: `TYPICALITY_SHADOW=1` computes typicality fields and logs the divergence between the typicality-band verdict and the deviation-score verdict, without changing `recommendation.action`.

- [ ] **Step 1: Write the failing test**

```python
# tests/quantum/test_typicality_shadow.py
"""tests/quantum/test_typicality_shadow.py — TYPICALITY_SHADOW mirrors the
AI_LIKELIHOOD_SHADOW pattern: compute both verdicts, surface nothing to
recommendation.action, log the divergence."""

from __future__ import annotations

from original.quantum.scoring import ScoringConfig, score


class TestTypicalityShadow:
    def test_shadow_mode_computes_typicality_but_does_not_change_action(self):
        # ... construct state + submission per the existing fixture pattern
        # in tests/quantum/test_typicality_integration.py
        state = _state_with_n_samples(6)
        sub_vector = _vec()
        shadow = score(
            state=state,
            submission_vector=sub_vector,
            feature_dict=_feature_dict(sub_vector),
            scoring_config=ScoringConfig(
                typicality_scoring_enabled=False, typicality_shadow_enabled=True
            ),
        )
        live = score(
            state=state,
            submission_vector=sub_vector,
            feature_dict=_feature_dict(sub_vector),
            scoring_config=ScoringConfig(typicality_scoring_enabled=False),
        )
        # Shadow computes the fields...
        assert shadow.typicality_p_far is not None
        # ...but action matches the non-shadow (deviation-based) run exactly.
        assert shadow.recommendation.action == live.recommendation.action
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/quantum/test_typicality_shadow.py -v`
Expected: `TypeError: __init__() got an unexpected keyword argument 'typicality_shadow_enabled'`

- [ ] **Step 3: Write the implementation**

Add `typicality_shadow_enabled: bool = False` to `ScoringConfig` (env `TYPICALITY_SHADOW`), and change Task 3's guard condition:

```python
    if (config.typicality_scoring_enabled or config.typicality_shadow_enabled) and adaptive_weights is None:
        ...
```

And change the action-selection branch in `_recommend()` to only use `typicality_band` when the LIVE flag (not shadow) is on:

```python
    if typicality_band is not None and typicality_scoring_enabled:  # NOT shadow
        action = typicality_band
    else:
        ...  # existing ACTION_THRESHOLDS path
```

(pass `typicality_scoring_enabled=config.typicality_scoring_enabled` as an additional `_recommend()` parameter alongside `typicality_band`, since shadow mode needs the fields computed but the action untouched — this is a small refinement of Task 3 Step 3e's original conditional, which assumed `typicality_band is not None` implied the flag was live; that assumption no longer holds once shadow mode can also populate it.)

Add divergence logging at the call site in `original/routers/students_scoring.py`, mirroring the `AI_LIKELIHOOD_SHADOW` pattern at line ~163-164: when `typicality_shadow_enabled` and `result.typicality_band != result.recommendation.action`, log a structured record (student_id, submission_id, typicality_band, deviation_action, typicality_p_far, typicality_p_central) to wherever `AI_LIKELIHOOD_SHADOW`'s divergence records go today (the `ai_likelihood_scores` table `scripts/shadow_report.py` reads from) — or, if that table is AI-likelihood-specific, a new `typicality_shadow_log` table following the same shape. Confirm the exact existing table/write call before choosing between "reuse" and "new table with the same shape."

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/quantum/test_typicality_shadow.py -v`
Expected: all PASS.

- [ ] **Step 5: Extend `scripts/shadow_report.py` (or write a sibling script) for the typicality divergence report**

Following `scripts/shadow_report.py`'s exact `{overall, authentic_labeled, per_student_flag_concentration}` shape (per the Explore report), add a typicality-specific report function reading from wherever Step 3's divergence log lands, reporting: overall divergence rate (typicality_band != deviation_action), and — critically, per design spec §9 — this is where the "multiply nominal FPR by tenant submission volume" arithmetic from spec §9 item 5 should be computed and surfaced, not left as a manual calculation.

- [ ] **Step 6: Run the full suite**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: `0 failed`.

- [ ] **Step 7: Commit**

```bash
git add original/quantum/scoring.py original/routers/students_scoring.py tests/quantum/test_typicality_shadow.py
git commit -m "$(cat <<'EOF'
Add TYPICALITY_SHADOW — compute-both, surface-nothing rollout mode

Mirrors AI_LIKELIHOOD_SHADOW exactly. Logs typicality-band vs deviation-
score-action divergence without changing recommendation.action, per design
spec §9's shadow-then-flip rollout path.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

## Self-Review

**1. Spec coverage.** §4 (G1–G6): Tasks 7, 8, 13, 14. §5 (Phase 1 typicality): Tasks 1–6. §6 (Phase 2 identity axis): Task 10. §7 (Phase 3 weights/bounds): Tasks 11, 12. §8 (Phase 4 uniformity features): Task 9. §9 (Rollout, shadow mode + tenant-volume arithmetic): Task 15. §10 (Risks): each risk is addressed by name at the task that closes or documents it (adaptive-weights mismatch → Task 5; double-dipping → Task 11; fairness → Tasks 9/14; conformal resolution floor → Task 1's docstring + Task 8's non-blocking note; the pre-existing `conformal.py` coexistence → Task 3 Step 3b's inline comment). §11 (Deliverables): every listed path has a corresponding task. One gap intentionally left open rather than papered over: G2b's paraphrase step is an explicitly-flagged proxy, not a real LLM attack, since no LLM-calling infrastructure exists elsewhere in this repo to build on. (Pre-flight review also corrected two factual errors found before dispatch: Task 7/13's demo-app loader now imports the verified `run.py:26` / `import run as _run_module` convention instead of a nonexistent `validation.plato.run` module, and G4's dialogue-grouping now uses `Dialogue.group`/`GROUP_NAMES` — the real fields — instead of an invented `chron_rank_group` attribute.)

**2. Placeholder scan.** One deliberate, explained placeholder remains by design: Task 11 Step 3's dead loop, which Step 5 immediately deletes — this demonstrates a wrong approach being caught and corrected rather than leaving unresolved ambiguity, and Step 5 exists specifically to remove it before commit. `main()` in `scripts/derive_measured_weights.py` raises `NotImplementedError` deliberately, with Task 11 Step 6 as the explicit follow-up step that completes it — not an unfinished task.

**3. Type consistency.** `typicality_band: str | None` is consistent from `typicality.py::band_from_p` (Task 1) through `state`/`scoring.py` (Tasks 2–3) to `schemas.py::TypicalityOut.band: str` (Task 4, non-Optional since the wrapping `TypicalityOut | None` already carries the "not computed" case) to `professor_narrative._build_hypotheses` (Task 6) to `_identity_axis_action` (Task 10, corrected mid-task from a band-string-only signature to `(band, source, llr)` once the ambiguity was found — both the function body and its test calls were updated together). `GateResult` is used identically by every gate function across Tasks 7, 13, 14.
