# Topic-Adaptive Variance Inflation — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop a student's own writing from being flagged when they change subject, by widening each feature's expected band in proportion to how far the submission's topic sits from their baseline.

**Architecture:** One new per-feature multiplier applied to `sigma` immediately before z-scoring in `original/quantum/scoring.py`. The multiplier is `1 + GAIN × d_eff × s_norm`, where `d_eff` is topic distance rescaled to be exactly zero at or below the existing `TOPIC_NOVELTY_BOUNDS["low"]` cutoff. That zero is the safety property: below the cutoff the multiplier is exactly 1.0 and output is bit-for-bit unchanged. Everything is gated behind `TOPIC_VARIANCE_INFLATION`, default off, with a shadow stage that computes the corrected score without letting it change a verdict.

**Tech Stack:** Python 3.11, numpy, FastAPI, pytest. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-08-06-topic-invariant-scoring-design.md`

## Global Constraints

- **Python is `/Users/andrew/Desktop/Original/.venv/bin/python`.** Never `python3`. The system interpreter has a broken `pydantic_settings` that breaks conftest import. In a git worktree the relative `.venv/bin/python` does not exist — use the absolute path above.
- **Default OFF must be byte-identical.** `ScoringConfig()` with all defaults reproduces flags-off Phase 1 behaviour exactly. This is an existing contract of the dataclass; do not break it.
- **`d ≤ 0.25` must be byte-identical even with the flag ON.** Guaranteed structurally by returning `None` from the multiplier builder rather than by multiplying by a float that happens to be 1.0.
- **No `original/constants.py` feature-ordering changes.** `ALL_FEATURE_CODES` order and `NORM_BOUNDS` are untouchable without explicit user permission. This plan only *appends* new names.
- **`original/` must never import `validation/`.** `validation/` is an analysis layer that imports `original/`, not the reverse. All measurability filtering and median normalisation happen at derivation time and are baked into the committed constant.
- **A clean test run is `0 failed`.** The 5 `TestAuthEndpoints` rate-limit tests show as XFAIL/XPASS and are not failures.
- **Commit style:** `Add ...` / `Fix ...` / `Refactor ...`, one focused commit per task, trailer `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`.

## Out of Scope (follow-on plan)

Deriving the real per-feature `TOPIC_SENSITIVITY` table, gate G7, and the
cross-corpus hold-out. Blocked on corpus work: `cross_work_manifest.json`
currently has 6 authors × **2 works** × 3 chunks = 36 chunks, and a drift
estimate over two work-means cannot support a 109-dimensional constant. This
plan ships an empty `TOPIC_SENSITIVITY` table, which reads as uniform
sensitivity 1.0 for every feature — a coherent v0 whose only claim is
"inflate in proportion to topic distance." Shadow mode is what makes shipping
it useful: it measures the real distribution of `d` in pilot traffic, which
no public-domain corpus can tell us.

---

### Task 1: Constants and the inflation-vector builder

Pure function, no wiring. Nothing calls it yet.

**Files:**
- Modify: `original/constants.py` (append after `TOPIC_NOVELTY_BOUNDS`, ~line 977)
- Modify: `original/quantum/scoring.py` (append after `_length_bucket_for`, ~line 112)
- Test: `tests/quantum/test_topic_variance_inflation.py` (create)

**Interfaces:**
- Consumes: `ALL_FEATURE_CODES`, `TOPIC_NOVELTY_BOUNDS` from `original/constants.py`
- Produces: `original.quantum.scoring._topic_inflation_vector(manifest: dict | None) -> np.ndarray | None`, returning a `(FEATURE_DIM,)` float64 multiplier or `None` when the multiplier would be exactly 1.0. Also `TOPIC_SENSITIVITY: dict[str, float]`, `TOPIC_INFLATE_GAIN: float`, `TOPIC_INFLATE_MAX: float` in `original/constants.py`.

- [ ] **Step 1: Write the failing test**

Create `tests/quantum/test_topic_variance_inflation.py`:

```python
"""Tests for topic-adaptive variance inflation (TOPIC_VARIANCE_INFLATION)."""

import numpy as np
import pytest

from original.constants import ALL_FEATURE_CODES, FEATURE_DIM, TOPIC_INFLATE_GAIN
from original.quantum.scoring import _topic_inflation_vector


def _manifest(distance):
    return {"topic": {"baseline_distance": distance, "novelty": "high"}}


def test_returns_none_below_novelty_floor():
    # 0.25 is TOPIC_NOVELTY_BOUNDS["low"]; at or below it the multiplier
    # would be exactly 1.0, so the builder signals "skip the multiply".
    assert _topic_inflation_vector(_manifest(0.0)) is None
    assert _topic_inflation_vector(_manifest(0.10)) is None
    assert _topic_inflation_vector(_manifest(0.25)) is None


def test_returns_none_for_unusable_manifest():
    assert _topic_inflation_vector(None) is None
    assert _topic_inflation_vector({}) is None
    assert _topic_inflation_vector({"topic": {}}) is None
    assert _topic_inflation_vector(_manifest(None)) is None
    assert _topic_inflation_vector(_manifest("high")) is None
    assert _topic_inflation_vector(_manifest(float("nan"))) is None


def test_shape_and_dtype_above_floor():
    vec = _topic_inflation_vector(_manifest(0.9))
    assert vec is not None
    assert vec.shape == (FEATURE_DIM,)
    assert vec.dtype == np.float64
    assert len(ALL_FEATURE_CODES) == FEATURE_DIM


def test_multiplier_is_at_least_one_and_monotone():
    lo = _topic_inflation_vector(_manifest(0.5))
    hi = _topic_inflation_vector(_manifest(1.0))
    assert np.all(lo >= 1.0)
    assert np.all(hi >= lo)


def test_uniform_sensitivity_gives_exact_expected_value():
    # With the shipped (empty) TOPIC_SENSITIVITY table every feature reads
    # 1.0, so the multiplier is 1 + GAIN * d_eff everywhere.
    # d = 1.0 -> d_eff = (1.0 - 0.25) / 0.75 = 1.0
    vec = _topic_inflation_vector(_manifest(1.0))
    assert np.allclose(vec, 1.0 + TOPIC_INFLATE_GAIN)


def test_distance_is_clamped_to_unit_interval():
    # A distance above 1.0 must not produce a larger multiplier than d = 1.0.
    assert np.allclose(
        _topic_inflation_vector(_manifest(5.0)),
        _topic_inflation_vector(_manifest(1.0)),
    )
    # A negative distance reads as "no novelty", not as a shrink.
    assert _topic_inflation_vector(_manifest(-3.0)) is None
```

- [ ] **Step 2: Run test to verify it fails**

```bash
/Users/andrew/Desktop/Original/.venv/bin/python -m pytest tests/quantum/test_topic_variance_inflation.py -q
```

Expected: collection error — `ImportError: cannot import name 'TOPIC_INFLATE_GAIN' from 'original.constants'`.

- [ ] **Step 3: Add the constants**

In `original/constants.py`, immediately after the `TOPIC_NOVELTY_BOUNDS` dict (~line 977), append:

```python
# ── Topic-adaptive variance inflation (2026-08 topic-invariance work) ────────
#
# When TOPIC_VARIANCE_INFLATION is on, scoring widens each feature's expected
# band in proportion to how far the submission's topic sits from the student's
# baseline centroid:
#
#     d_eff     = clip((d - TOPIC_NOVELTY_BOUNDS["low"]) / 0.75, 0, 1)
#     sigma_eff = sigma * (1 + TOPIC_INFLATE_GAIN * d_eff * s_norm)
#
# Rationale: baseline_std is estimated from a student's own samples, which
# usually span a narrow topic range, so it encodes "how much this student
# varies WHILE WRITING ABOUT THE SAME THINGS". On a new topic the topic-
# sensitive features move by more than that sigma predicts and rms_z inflates
# — measured at mean AUC 0.387 (INVERTED) on the leave-one-genre-out Lewis
# corpus, validation/genre_crossgenre_2026-08/. See
# docs/superpowers/specs/2026-08-06-topic-invariant-scoring-design.md.
#
# TOPIC_SENSITIVITY holds ALREADY-NORMALISED per-feature sensitivities: the
# derivation script divides by the median over MEASURABLE features and clips
# to [0, TOPIC_INFLATE_MAX] before writing them here, so the scoring path
# needs no measurability lookup (original/ must never import validation/).
# A code absent from this table reads as 1.0 — median sensitivity.
#
# SHIPPED EMPTY ON PURPOSE. An empty table means uniform sensitivity, i.e.
# "inflate every feature in proportion to topic distance". The per-feature
# table is a follow-on: cross_work_manifest.json currently carries 2 works
# per author, and a drift estimate over two work-means cannot support a
# 109-dimensional constant.
TOPIC_SENSITIVITY: dict[str, float] = {}

# Multiplier strength at maximum topic distance. 1.0 doubles sigma for a
# median-sensitivity feature at d = 1.0. Swept on the derivation corpus and
# fixed before the hold-out is touched — see the spec's hold-out discipline.
TOPIC_INFLATE_GAIN: float = 1.0

# Ceiling on normalised per-feature sensitivity, so no single feature can be
# inflated into irrelevance. Unused while TOPIC_SENSITIVITY is empty (every
# lookup returns 1.0), but the clip lives in the derivation script that
# populates the table.
TOPIC_INFLATE_MAX: float = 3.0
```

- [ ] **Step 4: Add the builder to scoring.py**

In `original/quantum/scoring.py`, extend the existing `from ..constants import (...)` block (starts line 52) with these three names, keeping the list alphabetical if it already is:

```python
    TOPIC_INFLATE_GAIN,
    TOPIC_NOVELTY_BOUNDS,
    TOPIC_SENSITIVITY,
```

Then, immediately after `_length_bucket_for` (~line 112) and before the `# ── Output dataclasses ──` banner, add:

```python
# ── Topic-adaptive variance inflation ────────────────────────────────────────
#
# Pre-build the per-feature sensitivity vector once. An absent code reads as
# 1.0 (median sensitivity), so the shipped empty TOPIC_SENSITIVITY table
# yields an all-ones vector and the multiplier reduces to 1 + GAIN * d_eff.
_TOPIC_SENSITIVITY_VECTOR = np.array(
    [TOPIC_SENSITIVITY.get(code, 1.0) for code in ALL_FEATURE_CODES],
    dtype=np.float64,
)

# Below this topic distance the correction is a no-op. Reusing the already-
# calibrated "low novelty" bound rather than inventing a second threshold.
_TOPIC_NOVELTY_FLOOR = float(TOPIC_NOVELTY_BOUNDS["low"])


def _topic_inflation_vector(manifest: dict | None) -> np.ndarray | None:
    """
    Per-feature sigma multiplier derived from the manifest's topic distance.

    Returns None — rather than an all-ones array — whenever the multiplier
    would be exactly 1.0: no manifest, no usable ``baseline_distance``, or a
    distance at or below ``_TOPIC_NOVELTY_FLOOR``. The caller skips the
    multiply entirely on None, which is what makes ``d <= 0.25`` bit-for-bit
    identical to flag-off rather than merely numerically close.
    """
    if not manifest:
        return None
    topic = manifest.get("topic") or {}
    distance = topic.get("baseline_distance")
    # bool is an int subclass; reject it explicitly so True can't read as 1.0.
    if isinstance(distance, bool) or not isinstance(distance, (int, float)):
        return None
    distance = float(distance)
    if not np.isfinite(distance):
        return None
    distance = min(max(distance, 0.0), 1.0)

    d_eff = (distance - _TOPIC_NOVELTY_FLOOR) / (1.0 - _TOPIC_NOVELTY_FLOOR)
    if d_eff <= 0.0:
        return None

    return 1.0 + TOPIC_INFLATE_GAIN * d_eff * _TOPIC_SENSITIVITY_VECTOR
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
/Users/andrew/Desktop/Original/.venv/bin/python -m pytest tests/quantum/test_topic_variance_inflation.py -q
```

Expected: `6 passed`.

- [ ] **Step 6: Commit**

```bash
git add original/constants.py original/quantum/scoring.py tests/quantum/test_topic_variance_inflation.py
git commit -m "$(cat <<'EOF'
Add topic-adaptive variance inflation constants and vector builder

Pure function plus three constants; nothing calls them yet. The builder
returns None rather than an all-ones array below the novelty floor, so the
caller can skip the multiply and keep d <= 0.25 bit-for-bit identical.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: Extract the rms_z computation

Behaviour-preserving refactor. Shadow mode (Task 5) needs to compute `rms_z` a second time under an inflated sigma, and duplicating the winsorise-weight-mask sequence is how the two copies drift apart.

**Files:**
- Modify: `original/quantum/scoring.py:731-738`
- Test: `tests/quantum/test_topic_variance_inflation.py`

**Interfaces:**
- Consumes: nothing from Task 1.
- Produces: `original.quantum.scoring._rms_z_from_z(z: np.ndarray, weight_vec: np.ndarray, active: np.ndarray, n_active: int) -> float`

- [ ] **Step 1: Write the failing test**

Append to `tests/quantum/test_topic_variance_inflation.py`:

```python
from original.quantum.scoring import _rms_z_from_z


def test_rms_z_from_z_matches_inline_formula():
    rng = np.random.default_rng(20260806)
    z = rng.normal(0.0, 2.0, size=FEATURE_DIM)
    weight_vec = rng.uniform(0.5, 1.5, size=FEATURE_DIM)
    active = np.ones(FEATURE_DIM, dtype=bool)
    active[:5] = False
    n_active = int(active.sum())

    z_capped = np.clip(z, -4.0, 4.0)
    z_weighted = z_capped * weight_vec * active.astype(np.float64)
    expected = float(np.sqrt(np.sum(z_weighted**2) / n_active))

    assert _rms_z_from_z(z, weight_vec, active, n_active) == expected


def test_rms_z_from_z_winsorises_at_four_sigma():
    # A feature at z=100 must contribute exactly as much as one at z=4.
    weight_vec = np.ones(FEATURE_DIM)
    active = np.ones(FEATURE_DIM, dtype=bool)

    huge = np.zeros(FEATURE_DIM)
    huge[0] = 100.0
    capped = np.zeros(FEATURE_DIM)
    capped[0] = 4.0

    assert _rms_z_from_z(huge, weight_vec, active, FEATURE_DIM) == _rms_z_from_z(
        capped, weight_vec, active, FEATURE_DIM
    )


def test_rms_z_from_z_returns_zero_when_no_active_features():
    z = np.ones(FEATURE_DIM)
    weight_vec = np.ones(FEATURE_DIM)
    active = np.zeros(FEATURE_DIM, dtype=bool)
    assert _rms_z_from_z(z, weight_vec, active, 0) == 0.0
```

- [ ] **Step 2: Run test to verify it fails**

```bash
/Users/andrew/Desktop/Original/.venv/bin/python -m pytest tests/quantum/test_topic_variance_inflation.py -q -k rms_z
```

Expected: `ImportError: cannot import name '_rms_z_from_z'`.

- [ ] **Step 3: Add the helper**

In `original/quantum/scoring.py`, directly after `_topic_inflation_vector`, add:

```python
def _rms_z_from_z(
    z: np.ndarray,
    weight_vec: np.ndarray,
    active: np.ndarray,
    n_active: int,
) -> float:
    """
    Winsorise, weight, mask, and reduce a z-vector to a single rms_z.

    Extracted so the shadow-mode second pass under an inflated sigma uses
    the identical sequence rather than a copy that can drift. The +-4 cap is
    applied BEFORE weighting — see the block comment at the call site for why
    that ordering matters.
    """
    z_capped = np.clip(z, -4.0, 4.0)
    z_weighted = z_capped * weight_vec * active.astype(np.float64)
    if n_active > 0:
        return float(np.sqrt(np.sum(z_weighted**2) / n_active))
    return 0.0
```

- [ ] **Step 4: Replace the inline computation**

In `original/quantum/scoring.py`, replace lines 731-738 — currently:

```python
    z_capped = np.clip(z, -4.0, 4.0)
    z_weighted = z_capped * weight_vec * active.astype(np.float64)

    n_active = int(active.sum())
    if n_active > 0:
        rms_z = float(np.sqrt(np.sum(z_weighted**2) / n_active))
    else:
        rms_z = 0.0
```

with:

```python
    n_active = int(active.sum())
    rms_z = _rms_z_from_z(z, weight_vec, active, n_active)
```

Leave the long explanatory comment above it (lines 719-730) exactly where it is — it documents the cap rationale and is still accurate.

- [ ] **Step 5: Run the full quantum suite to prove nothing moved**

```bash
/Users/andrew/Desktop/Original/.venv/bin/python -m pytest tests/quantum/ -q
```

Expected: all pass, `0 failed`. This is a pure refactor — any failure here is a real regression, not a flake.

- [ ] **Step 6: Commit**

```bash
git add original/quantum/scoring.py tests/quantum/test_topic_variance_inflation.py
git commit -m "$(cat <<'EOF'
Refactor rms_z computation into _rms_z_from_z helper

Behaviour-preserving. Shadow-mode variance inflation needs a second rms_z
pass under an inflated sigma, and a duplicated winsorise-weight-mask
sequence is how the two copies drift apart.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: ScoringConfig mode

`TOPIC_VARIANCE_INFLATION` is a three-valued mode string, not a bool — the spec's rollout has a shadow stage, and `llr_action_mode` already establishes the string-mode precedent in this dataclass.

**Files:**
- Modify: `original/quantum/scoring.py` (`ScoringConfig` body ~line 232, `from_env` ~line 285)
- Test: `tests/quantum/test_topic_variance_inflation.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `ScoringConfig.topic_variance_inflation: str`, one of `"off"` / `"shadow"` / `"on"`, default `"off"`.

- [ ] **Step 1: Write the failing test**

Append to `tests/quantum/test_topic_variance_inflation.py`:

```python
from original.quantum.scoring import ScoringConfig


def test_default_config_is_off():
    assert ScoringConfig().topic_variance_inflation == "off"


@pytest.mark.parametrize(
    "env_value,expected",
    [
        ("0", "off"),
        ("1", "on"),
        ("on", "on"),
        ("shadow", "shadow"),
        ("", "off"),
        ("nonsense", "off"),
        ("SHADOW", "shadow"),
    ],
)
def test_from_env_parses_mode(monkeypatch, env_value, expected):
    monkeypatch.setenv("TOPIC_VARIANCE_INFLATION", env_value)
    assert ScoringConfig.from_env().topic_variance_inflation == expected


def test_from_env_defaults_off_when_unset(monkeypatch):
    monkeypatch.delenv("TOPIC_VARIANCE_INFLATION", raising=False)
    assert ScoringConfig.from_env().topic_variance_inflation == "off"
```

- [ ] **Step 2: Run test to verify it fails**

```bash
/Users/andrew/Desktop/Original/.venv/bin/python -m pytest tests/quantum/test_topic_variance_inflation.py -q -k "config or from_env"
```

Expected: `AttributeError: 'ScoringConfig' object has no attribute 'topic_variance_inflation'`.

- [ ] **Step 3: Add the field**

In `original/quantum/scoring.py`, inside the `ScoringConfig` dataclass, after `llr_action_mode`'s declaration and its comment block, add:

```python
    # Topic-adaptive variance inflation (see original/constants.py's
    # TOPIC_SENSITIVITY block and the 2026-08 topic-invariance spec).
    #   "off"    — DEFAULT. Byte-identical to Phase 1.
    #   "shadow" — compute the corrected score and attach it as
    #              deviation_score_inflated; deviation_score and
    #              recommendation are untouched. Stage 1 of rollout, and the
    #              only way to learn the real distribution of topic distance
    #              in pilot traffic.
    #   "on"     — inflate sigma for real. CHANGES SCORES. Gated on gate G7
    #              passing in both hold-out directions.
    topic_variance_inflation: str = "off"
```

- [ ] **Step 4: Parse it in from_env**

In `ScoringConfig.from_env`, add as the last keyword argument to the `cls(...)` call:

```python
            topic_variance_inflation=_parse_topic_inflation_mode(
                os.environ.get("TOPIC_VARIANCE_INFLATION", "0")
            ),
```

And add this module-level helper directly above the `ScoringConfig` class definition:

```python
_TOPIC_INFLATION_MODES = frozenset({"off", "shadow", "on"})


def _parse_topic_inflation_mode(raw: str) -> str:
    """
    Map TOPIC_VARIANCE_INFLATION to a mode. "1" is accepted as an alias for
    "on" so the flag reads like every other boolean flag in the table.
    Anything unrecognised falls back to "off" — an unparseable value must
    never silently enable a score-changing correction.
    """
    value = (raw or "").strip().lower()
    if value == "1":
        return "on"
    if value in _TOPIC_INFLATION_MODES:
        return value
    return "off"
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
/Users/andrew/Desktop/Original/.venv/bin/python -m pytest tests/quantum/test_topic_variance_inflation.py -q
```

Expected: `18 passed`.

- [ ] **Step 6: Commit**

```bash
git add original/quantum/scoring.py tests/quantum/test_topic_variance_inflation.py
git commit -m "$(cat <<'EOF'
Add TOPIC_VARIANCE_INFLATION mode to ScoringConfig

Three-valued (off/shadow/on) following the llr_action_mode precedent, since
the rollout has a shadow stage. Unrecognised values fall back to off so a
typo can never silently enable a score-changing correction.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: Wire inflation into score()

The score-changing change. `mode == "on"` only; shadow is Task 5.

**Files:**
- Modify: `original/quantum/scoring.py` (~line 698 sigma site, ~line 751 typicality guard, `Layer7Output` ~line 354, construction ~line 1011)
- Test: `tests/quantum/test_topic_variance_inflation.py`

**Interfaces:**
- Consumes: `_topic_inflation_vector` (Task 1), `ScoringConfig.topic_variance_inflation` (Task 3).
- Produces: `Layer7Output.topic_inflation_applied: bool`, `Layer7Output.topic_distance: float | None`, `Layer7Output.topic_mean_inflation: float | None`.

- [ ] **Step 1: Write the failing test**

Append to `tests/quantum/test_topic_variance_inflation.py`:

```python
from original.quantum.scoring import score
from original.quantum.state import BaselineSample, StudentState


def _state_with_baseline(seed=11):
    """A StudentState with enough authenticated samples to score against."""
    rng = np.random.default_rng(seed)
    state = StudentState(student_id="topic-test")
    for i in range(5):
        state.add_sample(
            BaselineSample(
                text=f"baseline {i}",
                vector=np.clip(rng.normal(0.5, 0.05, size=FEATURE_DIM), 0.0, 1.0),
                provenance="proctored",
                auth_weight=1.0,
                assignment=f"a{i}",
            )
        )
    return state


def _score_with(state, vector, manifest, mode):
    return score(
        state,
        vector,
        {code: float(v) for code, v in zip(ALL_FEATURE_CODES, vector)},
        submission_id="s1",
        manifest=manifest,
        scoring_config=ScoringConfig(topic_variance_inflation=mode),
    )


def test_flag_off_is_unchanged_by_topic_distance():
    state = _state_with_baseline()
    rng = np.random.default_rng(99)
    vec = np.clip(rng.normal(0.62, 0.05, size=FEATURE_DIM), 0.0, 1.0)

    off = _score_with(state, vec, _manifest(0.95), "off")
    assert off.topic_inflation_applied is False
    assert off.topic_mean_inflation is None


def test_below_floor_is_byte_identical_with_flag_on():
    state = _state_with_baseline()
    rng = np.random.default_rng(99)
    vec = np.clip(rng.normal(0.62, 0.05, size=FEATURE_DIM), 0.0, 1.0)

    off = _score_with(state, vec, _manifest(0.10), "off")
    on = _score_with(state, vec, _manifest(0.10), "on")

    assert on.authorship.deviation_score == off.authorship.deviation_score
    assert on.recommendation.action == off.recommendation.action
    assert on.topic_inflation_applied is False


def test_high_topic_distance_lowers_the_deviation_score():
    state = _state_with_baseline()
    rng = np.random.default_rng(99)
    vec = np.clip(rng.normal(0.62, 0.05, size=FEATURE_DIM), 0.0, 1.0)

    off = _score_with(state, vec, _manifest(0.95), "off")
    on = _score_with(state, vec, _manifest(0.95), "on")

    assert on.authorship.deviation_score < off.authorship.deviation_score
    assert on.topic_inflation_applied is True
    assert on.topic_distance == pytest.approx(0.95)
    assert on.topic_mean_inflation > 1.0


def test_typicality_refuses_to_run_under_inflation():
    state = _state_with_baseline()
    rng = np.random.default_rng(99)
    vec = np.clip(rng.normal(0.62, 0.05, size=FEATURE_DIM), 0.0, 1.0)

    result = score(
        state,
        vec,
        {code: float(v) for code, v in zip(ALL_FEATURE_CODES, vec)},
        submission_id="s1",
        manifest=_manifest(0.95),
        scoring_config=ScoringConfig(
            topic_variance_inflation="on", typicality_scoring_enabled=True
        ),
    )
    # loo_distances are computed under an UN-inflated sigma; comparing an
    # inflated rms_z against them is apples-to-oranges, so the band must be
    # withheld rather than reported wrong.
    assert result.typicality_band is None


def test_impostor_pool_sigma_is_not_inflated():
    """
    The spec's highest-risk decision: only the CLAIMED-AUTHOR sigma is
    inflated. The impostor pool's sigma is already fit across many authors
    spanning many topics -- which is why llr_deviation_score survives a genre
    shift (AUC 0.863) while the raw score inverts (0.387) -- so inflating it
    too would re-open the asymmetry this correction exists to close.

    Guard, not a measurement: it pins the intent so a later refactor that
    threads `sigma` into _llr_deviation fails loudly here.
    """
    state = _state_with_baseline()
    rng = np.random.default_rng(99)
    vec = np.clip(rng.normal(0.62, 0.05, size=FEATURE_DIM), 0.0, 1.0)
    impostor_stats = (np.full(FEATURE_DIM, 0.50), np.full(FEATURE_DIM, 0.08))
    feature_dict = {code: float(v) for code, v in zip(ALL_FEATURE_CODES, vec)}

    def _run(mode):
        return score(
            state,
            vec,
            feature_dict,
            submission_id="s1",
            manifest=_manifest(0.95),
            impostor_stats=impostor_stats,
            scoring_config=ScoringConfig(
                topic_variance_inflation=mode, null_model="impostor"
            ),
        )

    off = _run("off")
    on = _run("on")

    # rms_z_null is unchanged, so inflating the claimed-author side alone
    # must move llr DOWN (further toward "genuinely this author").
    assert on.llr_deviation_score is not None
    assert on.llr_deviation_score < off.llr_deviation_score
```

- [ ] **Step 2: Run test to verify it fails**

```bash
/Users/andrew/Desktop/Original/.venv/bin/python -m pytest tests/quantum/test_topic_variance_inflation.py -q -k "byte_identical or lowers or typicality_refuses or flag_off"
```

Expected: `AttributeError: 'Layer7Output' object has no attribute 'topic_inflation_applied'`.

- [ ] **Step 3: Add the output fields**

In `original/quantum/scoring.py`, in the `Layer7Output` dataclass after `context_manifest` (~line 354):

```python
    # ── Topic-adaptive variance inflation (audit trail) ───────────────────────
    # All three stay at their defaults unless
    # config.topic_variance_inflation is "on"/"shadow" AND the manifest
    # carried a topic distance above the novelty floor.
    topic_inflation_applied: bool = field(default=False)
    topic_distance: float | None = field(default=None)
    topic_mean_inflation: float | None = field(default=None)
```

- [ ] **Step 4: Inflate sigma at the z-score site**

In `original/quantum/scoring.py`, find:

```python
    sub_raw = submission_vector  # raw normalised [0,1] vector
    z = (sub_raw - mu) / sigma  # standardised deviation, shape (D,)
```

Replace with:

```python
    # ── Topic-adaptive variance inflation ────────────────────────────────────
    # Placed AFTER the Bayesian-prior blend so it widens the EFFECTIVE sigma
    # rather than racing it. `sigma` also feeds the amplitude path via
    # baseline_std_override, so the correction stays coherent across both
    # scoring routes instead of applying to rms_z alone.
    topic_inflation: np.ndarray | None = None
    if config.topic_variance_inflation in ("on", "shadow"):
        topic_inflation = _topic_inflation_vector(manifest)
    if topic_inflation is not None and config.topic_variance_inflation == "on":
        sigma = sigma * topic_inflation

    sub_raw = submission_vector  # raw normalised [0,1] vector
    z = (sub_raw - mu) / sigma  # standardised deviation, shape (D,)
```

- [ ] **Step 5: Extend the typicality guard**

Find:

```python
    if config.typicality_scoring_enabled and adaptive_weights is None:
```

Replace with:

```python
    # `topic_inflation is None` joins the existing `adaptive_weights is None`
    # guard for the same reason: state.loo_distances is computed under the
    # UNWEIGHTED, UN-INFLATED reference, so comparing a modified rms_z
    # against that distribution is apples-to-oranges. Withhold the band
    # rather than report a wrong one. See the NOTE a few lines below.
    if (
        config.typicality_scoring_enabled
        and adaptive_weights is None
        and topic_inflation is None
    ):
```

Note this guard uses `topic_inflation is None`, so it also withholds the band in **shadow** mode. That is deliberate and conservative: shadow does not change `rms_z`, but a run with a non-None inflation vector is one where the topic has genuinely shifted, and the same hazard is being tracked in Task 5's follow-up. Keeping one condition rather than two avoids a subtle mode-dependent divergence.

- [ ] **Step 6: Populate the audit fields**

Find the `Layer7Output(` construction (~line 1011, the line reading `context_manifest=manifest,`) and add immediately after it:

```python
        topic_inflation_applied=(
            topic_inflation is not None and config.topic_variance_inflation == "on"
        ),
        topic_distance=(
            float(((manifest or {}).get("topic") or {})["baseline_distance"])
            if topic_inflation is not None
            else None
        ),
        topic_mean_inflation=(
            float(np.mean(topic_inflation)) if topic_inflation is not None else None
        ),
```

- [ ] **Step 7: Run the tests**

```bash
/Users/andrew/Desktop/Original/.venv/bin/python -m pytest tests/quantum/test_topic_variance_inflation.py -q
```

Expected: `24 passed`.

- [ ] **Step 8: Run the full suite for regressions**

```bash
/Users/andrew/Desktop/Original/.venv/bin/python -m pytest tests/ -q
```

Expected: `0 failed`. Flag default is `"off"`, so every existing test must be untouched.

- [ ] **Step 9: Commit**

```bash
git add original/quantum/scoring.py tests/quantum/test_topic_variance_inflation.py
git commit -m "$(cat <<'EOF'
Wire topic-adaptive variance inflation into score()

Inflates the effective sigma after the Bayesian-prior blend when
TOPIC_VARIANCE_INFLATION=on, so a submission on an unseen topic is judged
against a wider band rather than a band estimated on too narrow a slice.

Typicality withholds its band under inflation: loo_distances are computed
against an un-inflated reference, so the comparison would be
apples-to-oranges — the same hazard already documented for adaptive weights.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 5: Shadow mode

Computes the corrected score without letting it reach a verdict. This is what ships to the pilot first.

**Files:**
- Modify: `original/quantum/scoring.py` (after the `rms_z` block ~line 736, `Layer7Output`, construction site)
- Test: `tests/quantum/test_topic_variance_inflation.py`

**Interfaces:**
- Consumes: `_rms_z_from_z` (Task 2), `topic_inflation` local (Task 4).
- Produces: `Layer7Output.deviation_score_inflated: float | None`.

- [ ] **Step 1: Write the failing test**

Append to `tests/quantum/test_topic_variance_inflation.py`:

```python
def test_shadow_attaches_score_without_changing_the_verdict():
    state = _state_with_baseline()
    rng = np.random.default_rng(99)
    vec = np.clip(rng.normal(0.62, 0.05, size=FEATURE_DIM), 0.0, 1.0)

    off = _score_with(state, vec, _manifest(0.95), "off")
    shadow = _score_with(state, vec, _manifest(0.95), "shadow")

    # The live verdict is untouched...
    assert shadow.authorship.deviation_score == off.authorship.deviation_score
    assert shadow.recommendation.action == off.recommendation.action
    assert shadow.topic_inflation_applied is False
    # ...but the corrected score is observable.
    assert shadow.deviation_score_inflated is not None
    assert shadow.deviation_score_inflated < off.authorship.deviation_score
    # And the diagnostics are recorded so the pilot d-distribution is
    # measurable from the audit log alone.
    assert shadow.topic_distance == pytest.approx(0.95)
    assert shadow.topic_mean_inflation > 1.0


def test_shadow_score_equals_the_on_mode_score():
    state = _state_with_baseline()
    rng = np.random.default_rng(99)
    vec = np.clip(rng.normal(0.62, 0.05, size=FEATURE_DIM), 0.0, 1.0)

    shadow = _score_with(state, vec, _manifest(0.95), "shadow")
    on = _score_with(state, vec, _manifest(0.95), "on")

    # Shadow must predict exactly what enabling the flag would do, or it is
    # not a preview of anything.
    assert shadow.deviation_score_inflated == pytest.approx(
        on.authorship.deviation_score
    )


def test_no_shadow_score_below_the_floor():
    state = _state_with_baseline()
    rng = np.random.default_rng(99)
    vec = np.clip(rng.normal(0.62, 0.05, size=FEATURE_DIM), 0.0, 1.0)
    shadow = _score_with(state, vec, _manifest(0.10), "shadow")
    assert shadow.deviation_score_inflated is None
```

- [ ] **Step 2: Run test to verify it fails**

```bash
/Users/andrew/Desktop/Original/.venv/bin/python -m pytest tests/quantum/test_topic_variance_inflation.py -q -k shadow
```

Expected: `AttributeError: 'Layer7Output' object has no attribute 'deviation_score_inflated'`.

- [ ] **Step 3: Add the output field**

In `Layer7Output`, directly after `topic_mean_inflation`:

```python
    # Shadow-mode preview: what deviation_score WOULD be under inflation.
    # None unless config.topic_variance_inflation == "shadow" and the topic
    # distance cleared the novelty floor. Never influences `recommendation`.
    deviation_score_inflated: float | None = field(default=None)
```

- [ ] **Step 4: Compute the shadow score**

In `original/quantum/scoring.py`, directly after:

```python
    n_active = int(active.sum())
    rms_z = _rms_z_from_z(z, weight_vec, active, n_active)
```

add:

```python
    # ── Shadow-mode preview ──────────────────────────────────────────────────
    # Recompute rms_z against an inflated sigma and map it through the SAME
    # tanh calibration used for the live D_raw below, so the number attached
    # here is exactly what "on" would produce. Anything less makes shadow a
    # preview of nothing.
    deviation_score_inflated: float | None = None
    if topic_inflation is not None and config.topic_variance_inflation == "shadow":
        _z_inflated = (sub_raw - mu) / (sigma * topic_inflation)
        _rms_z_inflated = _rms_z_from_z(_z_inflated, weight_vec, active, n_active)
        deviation_score_inflated = float(np.tanh(_rms_z_inflated / 1.5))
```

- [ ] **Step 5: Attach it**

In the `Layer7Output(` construction, after `topic_mean_inflation=...`:

```python
        deviation_score_inflated=deviation_score_inflated,
```

- [ ] **Step 6: Run the tests**

```bash
/Users/andrew/Desktop/Original/.venv/bin/python -m pytest tests/quantum/test_topic_variance_inflation.py -q
```

Expected: `26 passed`.

If `test_shadow_score_equals_the_on_mode_score` fails, the live `D_raw` calibration at `original/quantum/scoring.py:863` has diverged from the `np.tanh(rms_z / 1.5)` used here. Read that line and match it exactly — do not adjust the test to accommodate a mismatch.

- [ ] **Step 7: Run the full suite**

```bash
/Users/andrew/Desktop/Original/.venv/bin/python -m pytest tests/ -q
```

Expected: `0 failed`.

- [ ] **Step 8: Commit**

```bash
git add original/quantum/scoring.py tests/quantum/test_topic_variance_inflation.py
git commit -m "$(cat <<'EOF'
Add shadow mode for topic-adaptive variance inflation

TOPIC_VARIANCE_INFLATION=shadow attaches deviation_score_inflated without
touching deviation_score or the recommendation, and is tested to equal what
"on" would produce. This is what makes the pilot topic-distance distribution
measurable before the correction can change a verdict -- the check
GENRE_INVARIANT_WEIGHTS_ENABLED never got, which shipped unable to fire.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 6: Document the flag

**Files:**
- Modify: `CLAUDE.md` (Environment Flags table)

**Interfaces:**
- Consumes: everything above.
- Produces: nothing consumed by later tasks.

- [ ] **Step 1: Add the flag row**

In `CLAUDE.md`, in the Environment Flags table, add directly after the `LENGTH_ADAPTIVE_WEIGHTS` row:

```markdown
| `TOPIC_VARIANCE_INFLATION` | `off` | ⚠️ **`on` changes scores.** Widens each feature's expected band in proportion to the submission's topic distance from the student's baseline centroid (`quantum/scoring.py:_topic_inflation_vector`), targeting the measured cross-topic false-positive failure: raw `deviation_score` AUC is **0.387 — inverted** on the leave-one-genre-out Lewis corpus (`validation/genre_crossgenre_2026-08/`), and `LLR_ACTION_MODE=gate` still leaves 42.4% of genuine cross-topic submissions at schedule_conversation+. `sigma_eff = sigma × (1 + TOPIC_INFLATE_GAIN × d_eff × s_norm)`, where `d_eff` is zero at or below `TOPIC_NOVELTY_BOUNDS["low"]` (0.25) — so **`d ≤ 0.25` is bit-for-bit identical to off**, structurally, not approximately. `shadow` attaches `deviation_score_inflated` and the `topic_distance` / `topic_mean_inflation` diagnostics without touching `deviation_score` or `recommendation`; it is tested to equal exactly what `on` produces. **Run `shadow` first** — if pilot `d` clusters below 0.25 the mechanism is a no-op in production regardless of corpus performance, which is precisely the trap `GENRE_INVARIANT_WEIGHTS_ENABLED` fell into. ⚠️ **`TOPIC_SENSITIVITY` currently ships EMPTY**, meaning uniform per-feature sensitivity — the correction is proportional to topic distance but does not yet distinguish topic-invariant features (`semicolon_colon_rate`) from genre chameleons (`theological_register_score`). Populating it is blocked on corpus work: `validation/public_authors/cross_work_manifest.json` has 2 works per author, and a drift estimate over two work-means cannot support a 109-dim constant. ⚠️ **Not validated against real student submissions** — same accepted risk as `LLR_ACTION_MODE=gate`. Gate G7 (spec §Validation) is not yet implemented; do not set `on` before it passes in both hold-out directions. Typicality withholds its band whenever inflation is active (`loo_distances` are computed against an un-inflated reference). See `docs/superpowers/specs/2026-08-06-topic-invariant-scoring-design.md`. |
| `TOPIC_INFLATE_GAIN` | `1.0` | Multiplier strength at maximum topic distance (`constants.py`). `1.0` doubles sigma for a median-sensitivity feature at `d = 1.0`. Must be swept on the derivation corpus and fixed before the hold-out is touched — tuning it against the hold-out converts the hold-out into a training set. |
```

- [ ] **Step 2: Verify the table renders and the claims match the code**

```bash
grep -n "TOPIC_VARIANCE_INFLATION\|TOPIC_INFLATE_GAIN" CLAUDE.md original/constants.py original/quantum/scoring.py
```

Expected: the default in the `CLAUDE.md` row (`off`) matches `ScoringConfig.topic_variance_inflation`'s default, and `TOPIC_INFLATE_GAIN = 1.0` matches `constants.py`.

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "$(cat <<'EOF'
Document TOPIC_VARIANCE_INFLATION and TOPIC_INFLATE_GAIN

Records both open caveats explicitly rather than in a follow-up: the
sensitivity table ships empty (uniform sensitivity), and gate G7 does not
exist yet, so "on" is not authorised.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
)"
```

---

## Verification

After Task 6, confirm the whole thing from a clean state:

```bash
/Users/andrew/Desktop/Original/.venv/bin/python -m pytest tests/ validation/test_tier10_optional.py -q
```

Expected: `0 failed`. That is the exact CI command.

```bash
TOPIC_VARIANCE_INFLATION=shadow /Users/andrew/Desktop/Original/.venv/bin/python -m pytest tests/quantum/ -q
```

Expected: `0 failed`. Shadow must never change a verdict, so setting it globally cannot break the quantum suite. A failure here means shadow is leaking into scoring — treat it as a real defect, not a test-environment problem.

## Follow-on plan (not this plan)

1. Expand `validation/public_authors/cross_work_manifest.json` to ≥4 works per author (`build_cross_work.py`'s `WORKS` tuple and per-`Work` `chunks` field; the Gutenberg fetch is cached per work, so only genuinely new works hit the network).
2. `validation/topic_sensitivity_2026-08/derive.py` — compute `drift_A / (noise_A + 1e-3)` per author, take the median across authors, divide by the median over MEASURABLE features, clip to `[0, TOPIC_INFLATE_MAX]`, write `TOPIC_SENSITIVITY`.
3. Gate G7 in `validation/calibration_gate.py` plus its mandatory failure witness in `validation/gate_contracts.py` — the three-way conjunction (FP ≤ 25%, catch ≥ 29%, AUC ≥ 0.60) from spec §Validation.
4. The 2×2 joint measurement against `LLR_ACTION_MODE`, since both mechanisms target the same false positive and their gains may not add.
