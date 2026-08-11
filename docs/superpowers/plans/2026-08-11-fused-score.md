# Fused Stylometric Score Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship `original/fusion/` — a report-only, shadow-persisting expert that fuses peer-centered diagonal z, LZMA conditional compression, and a function-word adjacency network into one calibrated evidence weight, so the fusion measured at AUC 0.889 on corpora can be measured on pilot traffic.

**Architecture:** Four small modules with one responsibility each (`channels` = pure distance functions, `peers` = deterministic reference selection + cache, `artifact` = fail-closed weights loader, `expert` = orchestration). Peer-centering is one generic function applied to all three channels. Inference is `(x − mu)/sd · w + b` — a dot product, no sklearn at runtime. Wired at the `students_scoring.py` call site only; `quantum/scoring.py` stays unaware the component exists.

**Tech Stack:** Python 3.12, numpy, stdlib `lzma`, FastAPI, SQLite + SQLAlchemy/Postgres, alembic, pytest.

**Spec:** `docs/superpowers/specs/2026-08-11-fused-score-design.md`

## Global Constraints

- **Python:** always `/Users/andrew/Desktop/Original/.venv/bin/python` — never system `python3` (broken `pydantic_settings` causes conftest import errors). Test command: `.venv/bin/python -m pytest <path> -q`.
- **Report-only invariant:** nothing in this plan may change `deviation_score`, `quantum_fidelity`, or `recommendation`. Task 7 enforces this by test.
- **No runtime sklearn.** The artifact is JSON; inference is numpy only. (`scripts/train_fused_score.py` may use sklearn — it runs offline.)
- **Flags default OFF.** `FUSED_SCORE_ENABLED=0`, `FUSED_SCORE_SHADOW=0`. Both off ⇒ the `original.fusion` package is never imported.
- **Abstain, never raise.** Every failure path returns `None` and logs one WARNING. No partial results.
- **Determinism.** Same inputs ⇒ same output. Peer references are ordered by `sha256(student_id)`, never shuffled.
- **Reference count is fixed at 8.** Below 8 eligible peers the expert abstains; above 8 it uses exactly the first 8.
- **`FEATURE_DIM = 103`** on this branch (`original/constants.py:205`, `len(ALL_FEATURE_CODES)`).
  Never reorder `ALL_FEATURE_CODES`. Note the three channels each reduce to a scalar, so the
  artifact is dimension-independent — but `.benchmark_cache/features/feature_vectors.npz` was
  built at 109 dims on another branch and its keys will all miss here, so Task 5 re-extracts
  from scratch. That is expected, not a fault.
- **Tenant isolation.** Peers come only from `tenant_of(student_id)` matches. Legacy flat ids (`tenant_of → None`) are their own cohort.
- **Commit style:** `Add ...` / `Fix ...` / `Refactor ...`, one focused commit per task, co-author line `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`.

---

## File Structure

| Path | Responsibility | Task |
|---|---|---|
| `original/fusion/__init__.py` | Package marker; re-export `predict_fused_score`, `FusedScoreResult` | 4 |
| `original/fusion/channels.py` | Three pure distance functions + cacheable profile builders | 1 |
| `original/fusion/peers.py` | Deterministic same-tenant reference selection + profile cache | 2 |
| `original/fusion/artifact.py` | Load/validate committed JSON weights; fail closed | 3 |
| `original/fusion/expert.py` | Orchestrate profile → center → fuse → abstain | 4 |
| `original/data/fused_score_v1.json` | Committed calibrated artifact | 5 |
| `scripts/train_fused_score.py` | Regenerate the artifact from PAN development authors | 5 |
| `original/store.py` | `fused_scores` DDL, put/get, FERPA purge, inventory | 6 |
| `original/repository.py` | Protocol entry, SQLite delegate, `_WRITE_METHODS` | 6 |
| `original/postgres_repository.py` | Postgres upsert + read | 6 |
| `original/db/models/live.py` | `FusedScore` ORM model | 6 |
| `alembic/versions/<rev>_fused_scores.py` | Postgres migration | 6 |
| `original/quantum/scoring.py` | `Layer7Output.fused_score` field **only** | 7 |
| `original/routers/students_scoring.py` | Two-mode call site | 7 |
| `tests/fusion/test_channels.py` | Task 1 tests | 1 |
| `tests/fusion/test_peers.py` | Task 2 tests | 2 |
| `tests/fusion/test_artifact.py` | Task 3 tests | 3 |
| `tests/fusion/test_expert.py` | Task 4 tests | 4 |
| `tests/fusion/test_persistence.py` | Task 6 tests | 6 |
| `tests/fusion/test_wiring.py` | Task 7 tests incl. the invariant | 7 |

**Dependencies:** 1 → 2 → 4; 3 → 4; (1,2,3,4) → 5; 6 independent; (4,6) → 7.

---

## Task 1: Channels — three pure distance functions

**Files:**
- Create: `original/fusion/__init__.py` (empty for now)
- Create: `original/fusion/channels.py`
- Test: `tests/fusion/__init__.py` (empty), `tests/fusion/test_channels.py`

**Interfaces:**
- Consumes: nothing (leaf module).
- Produces:
  - `CHANNEL_NAMES: tuple[str, ...]` = `("peer_centered_z", "compression", "function_word_network")`
  - `diagonal_z_distance(probe_vec: np.ndarray, baseline_mean: np.ndarray, baseline_std: np.ndarray) -> float`
  - `compressed_size(payload: bytes) -> int`
  - `compression_distance(baseline_text: str, probe_text: str, *, baseline_size: int | None = None) -> float`
  - `function_word_matrix(text: str) -> np.ndarray` (unit-norm, flattened)
  - `function_word_distance(baseline_matrix: np.ndarray, probe_matrix: np.ndarray) -> float`

- [ ] **Step 1: Write the failing tests**

Create `tests/fusion/__init__.py` as an empty file, then `tests/fusion/test_channels.py`:

```python
"""Pure-function tests for the three fusion channels.

Each channel maps (baseline, probe) -> float where LARGER means MORE
different. These tests pin the direction, the identity property, and
determinism; the absolute values are pinned only where they are exactly
derivable, so a refactor that changes calibration fails loudly.
"""

from __future__ import annotations

import numpy as np
import pytest

from original.constants import FEATURE_DIM
from original.fusion.channels import (
    CHANNEL_NAMES,
    compressed_size,
    compression_distance,
    diagonal_z_distance,
    function_word_distance,
    function_word_matrix,
)

_PROSE_A = (
    "However, a reader might ask why these claims have been made; therefore we reply "
    "that the argument is careful, and that it is also sound. "
) * 40

_PROSE_B = (
    "The cat sat. Rain fell. Dogs ran fast! Birds sing loud songs. "
    "Short bursts everywhere. No subordination here. "
) * 40


def test_channel_names_are_the_documented_three():
    assert CHANNEL_NAMES == ("peer_centered_z", "compression", "function_word_network")


def test_diagonal_z_is_zero_when_probe_equals_baseline_mean():
    mean = np.full(FEATURE_DIM, 0.5)
    std = np.full(FEATURE_DIM, 0.1)
    assert diagonal_z_distance(mean.copy(), mean, std) == pytest.approx(0.0)


def test_diagonal_z_matches_the_production_tanh_formula():
    # Every feature exactly 2 sigma away -> rms_z == 2.0 -> tanh(2/1.5).
    mean = np.full(FEATURE_DIM, 0.5)
    std = np.full(FEATURE_DIM, 0.1)
    probe = mean + 2.0 * std
    assert diagonal_z_distance(probe, mean, std) == pytest.approx(np.tanh(2.0 / 1.5))


def test_diagonal_z_winsorizes_at_four_sigma():
    mean = np.full(FEATURE_DIM, 0.5)
    std = np.full(FEATURE_DIM, 0.1)
    at_cap = diagonal_z_distance(mean + 4.0 * std, mean, std)
    way_past = diagonal_z_distance(mean + 400.0 * std, mean, std)
    assert at_cap == pytest.approx(way_past)


def test_diagonal_z_floors_degenerate_sigma():
    mean = np.full(FEATURE_DIM, 0.5)
    std = np.zeros(FEATURE_DIM)
    value = diagonal_z_distance(np.full(FEATURE_DIM, 0.6), mean, std)
    assert np.isfinite(value)
    assert 0.0 <= value <= 1.0


def test_compression_distance_is_smaller_for_same_style():
    same = compression_distance(_PROSE_A, _PROSE_A[:600])
    different = compression_distance(_PROSE_A, _PROSE_B[:600])
    assert same < different


def test_compression_distance_accepts_precomputed_baseline_size():
    size = compressed_size(_PROSE_A.encode("utf-8"))
    with_cache = compression_distance(_PROSE_A, _PROSE_B[:600], baseline_size=size)
    without = compression_distance(_PROSE_A, _PROSE_B[:600])
    assert with_cache == pytest.approx(without)


def test_compression_distance_handles_empty_probe():
    assert compression_distance(_PROSE_A, "") == pytest.approx(1.0)


def test_function_word_matrix_is_unit_norm():
    matrix = function_word_matrix(_PROSE_A)
    assert float(np.linalg.norm(matrix)) == pytest.approx(1.0)


def test_function_word_distance_is_zero_against_itself():
    matrix = function_word_matrix(_PROSE_A)
    assert function_word_distance(matrix, matrix) == pytest.approx(0.0, abs=1e-9)


def test_function_word_distance_separates_styles():
    a = function_word_matrix(_PROSE_A)
    b = function_word_matrix(_PROSE_B)
    assert function_word_distance(a, b) > function_word_distance(a, a)


def test_function_word_matrix_handles_empty_text():
    matrix = function_word_matrix("")
    assert np.all(np.isfinite(matrix))
    assert float(np.linalg.norm(matrix)) == pytest.approx(1.0)


def test_all_channels_are_deterministic():
    mean = np.full(FEATURE_DIM, 0.5)
    std = np.full(FEATURE_DIM, 0.1)
    probe = np.linspace(0.2, 0.8, FEATURE_DIM)
    assert diagonal_z_distance(probe, mean, std) == diagonal_z_distance(probe, mean, std)
    assert compression_distance(_PROSE_A, _PROSE_B[:600]) == compression_distance(
        _PROSE_A, _PROSE_B[:600]
    )
    first = function_word_matrix(_PROSE_A)
    second = function_word_matrix(_PROSE_A)
    assert np.array_equal(first, second)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/fusion/test_channels.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'original.fusion'`

- [ ] **Step 3: Create the package marker**

Create `original/fusion/__init__.py` containing exactly:

```python
"""Report-only fused stylometric score (see docs/superpowers/specs/2026-08-11-fused-score-design.md)."""
```

- [ ] **Step 4: Implement the channels**

Create `original/fusion/channels.py`:

```python
"""Three pure distance functions for the fused score.

Each maps (baseline, probe) -> float where LARGER means MORE different.
No state, no I/O, no logging: everything here is a deterministic function
of its arguments so it can be tested with fixed inputs.

The expensive halves (compressed baseline size, function-word matrix)
are exposed as separate builders so ``peers.py`` can cache them per
profile instead of recomputing them for every submission.
"""

from __future__ import annotations

import lzma
import re

import numpy as np

from ..style_authorship import FUNCTION_WORDS

CHANNEL_NAMES: tuple[str, ...] = (
    "peer_centered_z",
    "compression",
    "function_word_network",
)

# ── Channel 1: diagonal z ─────────────────────────────────────────────────────
# Same shape as quantum/scoring.py's primary formulation — winsorize |z| at
# 4 sigma, RMS across features, tanh(rms / 1.5) — but deliberately WITHOUT the
# tier weight vector and the active-feature mask. This channel is peer-centered
# downstream, so a per-feature prior that applies equally to the claimed author
# and to all eight references would cancel out; leaving it off keeps the channel
# a plain distance. Callers pass baseline_mean / baseline_std straight from
# StudentState so the moments can never drift from production.
_Z_CAP = 4.0
_TANH_DIVISOR = 1.5
_SIGMA_HARD_FLOOR = 0.005

# ── Channel 2: compression ────────────────────────────────────────────────────
# FORMAT_RAW + preset 1 is the configuration measured in the 2026-08 paths
# experiment. preset 1 keeps the dictionary small enough that a ~700-word probe
# actually shifts the compressed size; higher presets wash the signal out.
_LZMA_FILTERS = [{"id": lzma.FILTER_LZMA2, "preset": 1}]

# ── Channel 3: function-word adjacency network ────────────────────────────────
# First 100 function words become states; everything else collapses to OTHER.
# A transition is recorded between two function words separated by <= 3
# non-function tokens, so the network captures local syntactic habit rather
# than raw adjacency.
_FW_STATES: tuple[str, ...] = tuple(FUNCTION_WORDS)[:100]
_FW_INDEX: dict[str, int] = {word: i for i, word in enumerate(_FW_STATES)}
_OTHER_STATE = len(_FW_STATES)
_N_STATES = _OTHER_STATE + 1
_MAX_GAP = 3
_SMOOTHING = 0.05
_TOKEN_RE = re.compile(r"[a-z']+")


def diagonal_z_distance(
    probe_vec: np.ndarray,
    baseline_mean: np.ndarray,
    baseline_std: np.ndarray,
) -> float:
    """Winsorized RMS z-distance in [0, 1]; 0.0 means identical to the mean."""
    sigma = np.maximum(np.asarray(baseline_std, dtype=np.float64), _SIGMA_HARD_FLOOR)
    z = (np.asarray(probe_vec, dtype=np.float64) - np.asarray(baseline_mean, dtype=np.float64)) / sigma
    z_capped = np.clip(z, -_Z_CAP, _Z_CAP)
    rms_z = float(np.sqrt(np.mean(z_capped**2)))
    return float(np.tanh(rms_z / _TANH_DIVISOR))


def compressed_size(payload: bytes) -> int:
    """Compressed length of ``payload`` under the pinned LZMA configuration."""
    return len(lzma.compress(payload, format=lzma.FORMAT_RAW, filters=_LZMA_FILTERS))


def compression_distance(
    baseline_text: str,
    probe_text: str,
    *,
    baseline_size: int | None = None,
) -> float:
    """Conditional compression cost of ``probe_text`` given ``baseline_text``.

    ``(C(base + probe) - C(base)) / C(probe)`` — near 0 when the baseline
    already "explains" the probe, near or above 1 when it does not. Pass
    ``baseline_size`` to reuse a cached ``C(base)``.
    """
    base_bytes = baseline_text.encode("utf-8", "ignore")
    probe_bytes = probe_text.encode("utf-8", "ignore")
    if not probe_bytes:
        return 1.0
    base_size = compressed_size(base_bytes) if baseline_size is None else int(baseline_size)
    joint = compressed_size(base_bytes + probe_bytes)
    return float((joint - base_size) / max(1, compressed_size(probe_bytes)))


def function_word_matrix(text: str) -> np.ndarray:
    """Row-normalized function-word transition matrix, flattened to unit norm."""
    tokens = _TOKEN_RE.findall(text.lower())
    counts = np.full((_N_STATES, _N_STATES), _SMOOTHING, dtype=np.float64)
    previous: int | None = None
    gap = 0
    for token in tokens:
        state = _FW_INDEX.get(token, _OTHER_STATE)
        if state == _OTHER_STATE:
            gap += 1
            if gap > _MAX_GAP:
                previous = None
            continue
        if previous is not None:
            counts[previous, state] += 1.0
        previous = state
        gap = 0
    probabilities = counts / counts.sum(axis=1, keepdims=True)
    flat = probabilities.reshape(-1)
    return flat / max(float(np.linalg.norm(flat)), 1e-12)


def function_word_distance(baseline_matrix: np.ndarray, probe_matrix: np.ndarray) -> float:
    """Cosine distance in [0, 2] between two unit-norm transition matrices."""
    return float(1.0 - float(np.dot(baseline_matrix, probe_matrix)))
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/fusion/test_channels.py -q`
Expected: PASS — 13 passed

- [ ] **Step 6: Commit**

```bash
git add original/fusion/__init__.py original/fusion/channels.py tests/fusion/__init__.py tests/fusion/test_channels.py
git commit -m "Add fusion channel distance functions

Three pure functions: winsorized diagonal z (mirrors scoring.py's
tanh(rms/1.5)), LZMA conditional compression, and a 101-state
function-word adjacency network. Expensive halves are exposed as
separate builders so peer profiles can cache them.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 2: Peers — deterministic reference selection and profile cache

**Files:**
- Create: `original/fusion/peers.py`
- Test: `tests/fusion/test_peers.py`

**Interfaces:**
- Consumes: `channels.compressed_size`, `channels.function_word_matrix` (Task 1).
- Produces:
  - `N_REFERENCES: int = 8`
  - `MIN_WORDS: int = 300`
  - `MIN_BASELINES: int = 3`
  - `@dataclass(frozen=True) Profile` with fields `text: str`, `compressed_size: int`, `fw_matrix: np.ndarray`, `baseline_mean: np.ndarray`, `baseline_std: np.ndarray`, `sample_count: int`
  - `build_profile(state: StudentState) -> Profile | None`
  - `select_references(claimed_state: StudentState, states: Iterable[StudentState]) -> list[Profile]`
  - `reset_cache_for_tests() -> None`
  - `cache_build_count() -> int`

- [ ] **Step 1: Write the failing tests**

Create `tests/fusion/test_peers.py`:

```python
"""Reference selection: deterministic, tenant-isolated, self-excluding, floored."""

from __future__ import annotations

import numpy as np
import pytest

from original.constants import FEATURE_DIM
from original.fusion import peers
from original.quantum.state import BaselineSample, StudentState

_LONG = (
    "However, a reader might ask why these claims have been made; therefore we reply "
    "that the argument is careful and that it is also sound. "
) * 40  # ~1000 words


def _state(student_id: str, *, samples: int = 3, words: str = _LONG) -> StudentState:
    state = StudentState(student_id=student_id)
    rng = np.random.default_rng(abs(hash(student_id)) % (2**32))
    for index in range(samples):
        state.add_sample(
            BaselineSample(
                text=words,
                vector=rng.uniform(0.3, 0.7, FEATURE_DIM),
                provenance="proctored",
                auth_weight=1.0,
                assignment=f"{student_id}-{index}",
            )
        )
    return state


@pytest.fixture(autouse=True)
def _clear_cache():
    peers.reset_cache_for_tests()
    yield
    peers.reset_cache_for_tests()


def test_build_profile_returns_none_below_baseline_floor():
    assert peers.build_profile(_state("t1:alice", samples=2)) is None


def test_build_profile_returns_none_when_text_is_too_short():
    assert peers.build_profile(_state("t1:alice", words="too short")) is None


def test_build_profile_populates_every_field():
    profile = peers.build_profile(_state("t1:alice"))
    assert profile is not None
    assert profile.sample_count == 3
    assert profile.compressed_size > 0
    assert profile.baseline_mean.shape == (FEATURE_DIM,)
    assert profile.baseline_std.shape == (FEATURE_DIM,)
    assert float(np.linalg.norm(profile.fw_matrix)) == pytest.approx(1.0)


def test_selection_abstains_below_eight_eligible_peers():
    claimed = _state("t1:alice")
    cohort = [claimed] + [_state(f"t1:peer{i}") for i in range(7)]
    assert peers.select_references(claimed, cohort) == []


def test_selection_returns_exactly_eight_when_more_are_available():
    claimed = _state("t1:alice")
    cohort = [claimed] + [_state(f"t1:peer{i}") for i in range(20)]
    assert len(peers.select_references(claimed, cohort)) == peers.N_REFERENCES


def test_selection_never_includes_the_claimed_student():
    claimed = _state("t1:alice")
    cohort = [claimed] + [_state(f"t1:peer{i}") for i in range(12)]
    selected = peers.select_references(claimed, cohort)
    assert all(profile.text is not None for profile in selected)
    assert len(selected) == 8
    # Self-exclusion is observable through the cache: 8 peers built, not 9.
    assert peers.cache_build_count() == 8


def test_selection_never_crosses_a_tenant_boundary():
    claimed = _state("t1:alice")
    cohort = [claimed] + [_state(f"t2:peer{i}") for i in range(20)]
    assert peers.select_references(claimed, cohort) == []


def test_selection_is_deterministic_across_input_order():
    claimed = _state("t1:alice")
    cohort = [_state(f"t1:peer{i}") for i in range(20)]
    forward = peers.select_references(claimed, [claimed] + cohort)
    peers.reset_cache_for_tests()
    backward = peers.select_references(claimed, list(reversed(cohort)) + [claimed])
    assert [p.compressed_size for p in forward] == [p.compressed_size for p in backward]
    assert [p.sample_count for p in forward] == [p.sample_count for p in backward]


def test_profiles_are_cached_not_rebuilt():
    claimed = _state("t1:alice")
    cohort = [claimed] + [_state(f"t1:peer{i}") for i in range(12)]
    peers.select_references(claimed, cohort)
    first_builds = peers.cache_build_count()
    peers.select_references(claimed, cohort)
    assert peers.cache_build_count() == first_builds


def test_ineligible_peers_do_not_count_toward_the_floor():
    claimed = _state("t1:alice")
    cohort = [claimed] + [_state(f"t1:ok{i}") for i in range(5)]
    cohort += [_state(f"t1:short{i}", words="tiny") for i in range(10)]
    assert peers.select_references(claimed, cohort) == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/fusion/test_peers.py -q`
Expected: FAIL — `ImportError: cannot import name 'peers' from 'original.fusion'`

- [ ] **Step 3: Implement peer selection**

Create `original/fusion/peers.py`:

```python
"""Deterministic same-tenant reference selection for the fused score.

Two jobs: turn a StudentState into a cached Profile (the expensive halves
of the compression and function-word channels), and pick a stable set of
reference profiles for a claimed student.

Determinism matters here in a way it did not in the offline experiment.
References are ordered by sha256(student_id), never shuffled, so the same
student scored twice gets the same references and the resulting number is
reproducible and explainable.
"""

from __future__ import annotations

import hashlib
import threading
from collections.abc import Iterable
from dataclasses import dataclass

import numpy as np

from ..principal import tenant_of
from ..quantum.state import StudentState
from .channels import compressed_size, function_word_matrix

# The artifact is calibrated at exactly this many references. Using fewer
# would evaluate off-calibration, so the expert abstains instead.
N_REFERENCES = 8

# Matches style_authorship.MIN_WORDS / MIN_BASELINES: below these the
# channels are reading noise.
MIN_WORDS = 300
MIN_BASELINES = 3


@dataclass(frozen=True)
class Profile:
    """Everything the channels need from one author, computed once."""

    text: str
    compressed_size: int
    fw_matrix: np.ndarray
    baseline_mean: np.ndarray
    baseline_std: np.ndarray
    sample_count: int


_cache: dict[str, Profile] = {}
_cache_builds = 0
_lock = threading.Lock()


def reset_cache_for_tests() -> None:
    global _cache_builds
    with _lock:
        _cache.clear()
        _cache_builds = 0


def cache_build_count() -> int:
    return _cache_builds


def _authenticated_texts(state: StudentState) -> list[str]:
    return [
        sample.text
        for sample in state.samples
        if sample.auth_weight > 0
        and isinstance(sample.text, str)
        and len(sample.text.split()) >= MIN_WORDS
    ]


def _fingerprint(student_id: str, texts: list[str]) -> str:
    digest = hashlib.sha256()
    digest.update(student_id.encode("utf-8"))
    for text in texts:
        digest.update(b"\x00")
        digest.update(text.encode("utf-8", "ignore"))
    return digest.hexdigest()


def build_profile(state: StudentState) -> Profile | None:
    """Cached Profile for ``state``, or None when it is below the floors."""
    global _cache_builds
    texts = _authenticated_texts(state)
    if len(texts) < MIN_BASELINES:
        return None
    key = _fingerprint(state.student_id, texts)
    cached = _cache.get(key)
    if cached is not None:
        return cached
    joined = "\n".join(texts)
    profile = Profile(
        text=joined,
        compressed_size=compressed_size(joined.encode("utf-8", "ignore")),
        fw_matrix=function_word_matrix(joined),
        baseline_mean=state.baseline_mean,
        baseline_std=state.baseline_std,
        sample_count=len(texts),
    )
    with _lock:
        _cache[key] = profile
        _cache_builds += 1
    return profile


def _order_key(student_id: str) -> str:
    return hashlib.sha256(student_id.encode("utf-8")).hexdigest()


def select_references(
    claimed_state: StudentState,
    states: Iterable[StudentState],
) -> list[Profile]:
    """Exactly ``N_REFERENCES`` same-tenant peer profiles, or ``[]``.

    Returns an empty list — never a short list — when fewer than
    ``N_REFERENCES`` eligible peers exist, because the artifact cannot be
    evaluated at a reference count it was not calibrated at.
    """
    claimed_tenant = tenant_of(claimed_state.student_id)
    candidates = [
        state
        for state in states
        if state.student_id != claimed_state.student_id
        and tenant_of(state.student_id) == claimed_tenant
    ]
    candidates.sort(key=lambda state: _order_key(state.student_id))

    selected: list[Profile] = []
    for state in candidates:
        profile = build_profile(state)
        if profile is None:
            continue
        selected.append(profile)
        if len(selected) == N_REFERENCES:
            return selected
    return []
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/fusion/test_peers.py -q`
Expected: PASS — 10 passed

- [ ] **Step 5: Commit**

```bash
git add original/fusion/peers.py tests/fusion/test_peers.py
git commit -m "Add deterministic peer reference selection for fused score

Orders eligible same-tenant peers by sha256(student_id) and takes exactly
8 — never a short list, because the artifact is calibrated at 8 references.
Profiles are cached by content fingerprint so a submission does not
re-compress nine baselines.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 3: Artifact — fail-closed weights loader

**Files:**
- Create: `original/fusion/artifact.py`
- Test: `tests/fusion/test_artifact.py`

**Interfaces:**
- Consumes: `channels.CHANNEL_NAMES` (Task 1).
- Produces:
  - `@dataclass(frozen=True) FusedArtifact` with `channel_order: tuple[str, ...]`, `mu: np.ndarray`, `sd: np.ndarray`, `weights: np.ndarray`, `intercept: float`, `threshold_fa5: float`, `threshold_fa1: float`, `model_version: str`, `trained_on: str`
  - `FusedArtifact.log_odds(values: np.ndarray) -> float`
  - `FusedArtifact.band(log_odds: float) -> str`
  - `load_artifact() -> FusedArtifact | None`
  - `reset_for_tests() -> None`
  - `DEFAULT_ARTIFACT_PATH: Path`
  - `EXPECTED_SCHEMA_VERSION: int = 1`

- [ ] **Step 1: Write the failing tests**

Create `tests/fusion/test_artifact.py`:

```python
"""The loader must fail closed: a partially-trusted model is worse than none."""

from __future__ import annotations

import json

import numpy as np
import pytest

from original.fusion import artifact as artifact_module


def _valid_payload() -> dict:
    mu = [0.0, 0.0, 0.0]
    sd = [1.0, 1.0, 1.0]
    weights = [1.0, 2.0, -0.5]
    intercept = 0.25
    reference_inputs = [[0.1, 0.2, 0.3], [-0.4, 0.5, 0.0]]
    reference_outputs = [
        float(np.dot((np.array(x) - mu) / np.array(sd), weights) + intercept)
        for x in reference_inputs
    ]
    return {
        "schema_version": 1,
        "channel_order": ["peer_centered_z", "compression", "function_word_network"],
        "mu": mu,
        "sd": sd,
        "weights": weights,
        "intercept": intercept,
        "threshold_fa5": 0.5,
        "threshold_fa1": 1.5,
        "reference_inputs": reference_inputs,
        "reference_outputs": reference_outputs,
        "provenance": {"dataset": "unit-test", "n_development_authors": 120},
    }


@pytest.fixture()
def write_artifact(tmp_path, monkeypatch):
    def _write(payload):
        path = tmp_path / "fused.json"
        path.write_text(json.dumps(payload))
        monkeypatch.setenv("FUSED_SCORE_MODEL_PATH", str(path))
        artifact_module.reset_for_tests()
        return path

    artifact_module.reset_for_tests()
    yield _write
    artifact_module.reset_for_tests()


def test_valid_artifact_loads(write_artifact):
    write_artifact(_valid_payload())
    loaded = artifact_module.load_artifact()
    assert loaded is not None
    assert loaded.channel_order == ("peer_centered_z", "compression", "function_word_network")
    assert loaded.intercept == pytest.approx(0.25)


def test_log_odds_is_the_standardized_dot_product(write_artifact):
    write_artifact(_valid_payload())
    loaded = artifact_module.load_artifact()
    values = np.array([0.1, 0.2, 0.3])
    expected = float(np.dot(values, [1.0, 2.0, -0.5]) + 0.25)
    assert loaded.log_odds(values) == pytest.approx(expected)


def test_band_boundaries_follow_the_thresholds(write_artifact):
    write_artifact(_valid_payload())
    loaded = artifact_module.load_artifact()
    assert loaded.band(0.4) == "consistent"
    assert loaded.band(0.5) == "inconclusive"
    assert loaded.band(1.4) == "inconclusive"
    assert loaded.band(1.5) == "divergent"


def test_missing_file_fails_closed(tmp_path, monkeypatch):
    monkeypatch.setenv("FUSED_SCORE_MODEL_PATH", str(tmp_path / "absent.json"))
    artifact_module.reset_for_tests()
    assert artifact_module.load_artifact() is None


def test_schema_version_drift_fails_closed(write_artifact):
    payload = _valid_payload()
    payload["schema_version"] = 2
    write_artifact(payload)
    assert artifact_module.load_artifact() is None


def test_unknown_channel_name_fails_closed(write_artifact):
    payload = _valid_payload()
    payload["channel_order"] = ["peer_centered_z", "compression", "astrology"]
    write_artifact(payload)
    assert artifact_module.load_artifact() is None


def test_weight_length_mismatch_fails_closed(write_artifact):
    payload = _valid_payload()
    payload["weights"] = [1.0, 2.0]
    write_artifact(payload)
    assert artifact_module.load_artifact() is None


def test_reference_prediction_drift_fails_closed(write_artifact):
    payload = _valid_payload()
    payload["reference_outputs"] = [value + 0.01 for value in payload["reference_outputs"]]
    write_artifact(payload)
    assert artifact_module.load_artifact() is None


def test_non_monotone_thresholds_fail_closed(write_artifact):
    payload = _valid_payload()
    payload["threshold_fa5"], payload["threshold_fa1"] = 1.5, 0.5
    write_artifact(payload)
    assert artifact_module.load_artifact() is None


def test_two_channel_artifact_is_accepted(write_artifact):
    payload = _valid_payload()
    payload["channel_order"] = ["peer_centered_z", "compression"]
    payload["mu"], payload["sd"], payload["weights"] = [0.0, 0.0], [1.0, 1.0], [1.0, 2.0]
    payload["reference_inputs"] = [[0.1, 0.2], [-0.4, 0.5]]
    payload["reference_outputs"] = [
        float(np.dot(x, [1.0, 2.0]) + payload["intercept"]) for x in payload["reference_inputs"]
    ]
    write_artifact(payload)
    loaded = artifact_module.load_artifact()
    assert loaded is not None
    assert loaded.channel_order == ("peer_centered_z", "compression")


def test_result_is_cached_after_first_load(write_artifact):
    path = write_artifact(_valid_payload())
    first = artifact_module.load_artifact()
    path.unlink()
    assert artifact_module.load_artifact() is first
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/fusion/test_artifact.py -q`
Expected: FAIL — `ImportError: cannot import name 'artifact' from 'original.fusion'`

- [ ] **Step 3: Implement the loader**

Create `original/fusion/artifact.py`:

```python
"""Load and validate the committed fused-score weights.

Deliberately JSON, not joblib: inference is a dot product, so there is no
reason to carry a pickled sklearn estimator and the version-drift failure
mode that has already made the AI-likelihood detector inert.

Every validation failure logs one WARNING and returns None. A partially
trusted model is worse than no model — the caller treats None exactly like
the flag being off.
"""

from __future__ import annotations

import json
import logging
import os
import threading
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .channels import CHANNEL_NAMES

log = logging.getLogger(__name__)

DEFAULT_ARTIFACT_PATH = Path(__file__).parent.parent / "data" / "fused_score_v1.json"
EXPECTED_SCHEMA_VERSION = 1
_REFERENCE_TOLERANCE = 1e-9


@dataclass(frozen=True)
class FusedArtifact:
    channel_order: tuple[str, ...]
    mu: np.ndarray
    sd: np.ndarray
    weights: np.ndarray
    intercept: float
    threshold_fa5: float
    threshold_fa1: float
    model_version: str
    trained_on: str

    def log_odds(self, values: np.ndarray) -> float:
        """Standardize then apply the linear model. Higher = more impostor-like."""
        standardized = (np.asarray(values, dtype=np.float64) - self.mu) / self.sd
        return float(np.dot(standardized, self.weights) + self.intercept)

    def band(self, log_odds: float) -> str:
        if log_odds >= self.threshold_fa1:
            return "divergent"
        if log_odds >= self.threshold_fa5:
            return "inconclusive"
        return "consistent"


_UNLOADED, _READY, _FAILED = 0, 1, 2
_state = _UNLOADED
_artifact: FusedArtifact | None = None
_lock = threading.Lock()


def _artifact_path() -> Path:
    override = os.environ.get("FUSED_SCORE_MODEL_PATH", "").strip()
    return Path(override) if override else DEFAULT_ARTIFACT_PATH


def reset_for_tests() -> None:
    global _state, _artifact
    with _lock:
        _state, _artifact = _UNLOADED, None


def _fail(reason: str) -> None:
    global _state, _artifact
    log.warning("Fused score disabled: %s (path=%s)", reason, _artifact_path())
    _state, _artifact = _FAILED, None


def _parse(payload: dict) -> FusedArtifact | None:
    if payload.get("schema_version") != EXPECTED_SCHEMA_VERSION:
        _fail("artifact schema mismatch")
        return None

    channel_order = tuple(payload.get("channel_order") or ())
    if not channel_order or any(name not in CHANNEL_NAMES for name in channel_order):
        _fail("unknown channel in channel_order")
        return None

    mu = np.asarray(payload.get("mu", []), dtype=np.float64)
    sd = np.asarray(payload.get("sd", []), dtype=np.float64)
    weights = np.asarray(payload.get("weights", []), dtype=np.float64)
    if not (mu.shape == sd.shape == weights.shape == (len(channel_order),)):
        _fail("mu/sd/weights length does not match channel_order")
        return None
    if not np.all(sd > 0):
        _fail("non-positive standardizer scale")
        return None

    threshold_fa5 = float(payload.get("threshold_fa5", 0.0))
    threshold_fa1 = float(payload.get("threshold_fa1", 0.0))
    if not threshold_fa5 < threshold_fa1:
        _fail("thresholds are not monotone (fa5 must be below fa1)")
        return None

    provenance = payload.get("provenance") or {}
    candidate = FusedArtifact(
        channel_order=channel_order,
        mu=mu,
        sd=sd,
        weights=weights,
        intercept=float(payload.get("intercept", 0.0)),
        threshold_fa5=threshold_fa5,
        threshold_fa1=threshold_fa1,
        model_version=f"v{EXPECTED_SCHEMA_VERSION}",
        trained_on=str(provenance.get("dataset", "unknown")),
    )

    reference_inputs = np.asarray(payload.get("reference_inputs", []), dtype=np.float64)
    expected = np.asarray(payload.get("reference_outputs", []), dtype=np.float64)
    if reference_inputs.ndim != 2 or reference_inputs.shape[0] != expected.shape[0]:
        _fail("reference inputs/outputs are missing or misshapen")
        return None
    got = np.asarray([candidate.log_odds(row) for row in reference_inputs])
    if float(np.max(np.abs(got - expected))) > _REFERENCE_TOLERANCE:
        _fail("reference prediction drift")
        return None
    return candidate


def _load() -> None:
    global _state, _artifact
    try:
        path = _artifact_path()
        if not path.exists():
            _fail("artifact not found")
            return
        parsed = _parse(json.loads(path.read_text()))
        if parsed is None:
            return
        _artifact, _state = parsed, _READY
    except Exception as exc:  # noqa: BLE001
        _fail(f"{type(exc).__name__}: {exc}")


def load_artifact() -> FusedArtifact | None:
    """The validated artifact, or None. Result is cached after the first call."""
    if _state == _READY:
        return _artifact
    if _state == _FAILED:
        return None
    with _lock:
        if _state == _UNLOADED:
            _load()
    return _artifact
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/fusion/test_artifact.py -q`
Expected: PASS — 11 passed

- [ ] **Step 5: Commit**

```bash
git add original/fusion/artifact.py tests/fusion/test_artifact.py
git commit -m "Add fail-closed loader for the fused-score artifact

JSON rather than joblib: inference is a dot product, so there is no
pickled estimator and no sklearn version-drift failure mode. Validates
schema version, channel names, vector lengths, threshold monotonicity,
and recomputes reference predictions; any mismatch returns None.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 4: Expert — orchestration and abstain logic

**Files:**
- Modify: `original/fusion/__init__.py`
- Create: `original/fusion/expert.py`
- Test: `tests/fusion/test_expert.py`

**Interfaces:**
- Consumes: `channels.*` (Task 1), `peers.select_references` / `peers.build_profile` / `peers.Profile` (Task 2), `artifact.load_artifact` (Task 3).
- Produces:
  - `@dataclass(frozen=True) FusedScoreResult` with `fused_log_odds: float`, `probability_different_author: float`, `band: str`, `channels: dict[str, float]`, `reference_profiles: int`, `baseline_samples: int`, `model_version: str`, `trained_on: str`
  - `predict_fused_score(text: str, claimed_state: StudentState, states: Iterable[StudentState], *, probe_vector: np.ndarray | None = None) -> FusedScoreResult | None`
  - `reset_for_tests() -> None`

- [ ] **Step 1: Write the failing tests**

Create `tests/fusion/test_expert.py`:

```python
"""Orchestration: centering, fusion, and every abstain path."""

from __future__ import annotations

import json

import numpy as np
import pytest

from original.constants import FEATURE_DIM
from original.fusion import artifact as artifact_module
from original.fusion import peers
from original.fusion.expert import FusedScoreResult, predict_fused_score
from original.quantum.state import BaselineSample, StudentState

_LONG = (
    "However, a reader might ask why these claims have been made; therefore we reply "
    "that the argument is careful and that it is also sound. "
) * 40

_OTHER = (
    "The cat sat. Rain fell. Dogs ran fast! Birds sing loud songs. "
    "Short bursts everywhere. No subordination here at all. "
) * 40


def _state(student_id: str, *, samples: int = 3, words: str = _LONG) -> StudentState:
    state = StudentState(student_id=student_id)
    rng = np.random.default_rng(abs(hash(student_id)) % (2**32))
    for index in range(samples):
        state.add_sample(
            BaselineSample(
                text=words,
                vector=rng.uniform(0.3, 0.7, FEATURE_DIM),
                provenance="proctored",
                auth_weight=1.0,
                assignment=f"{student_id}-{index}",
            )
        )
    return state


@pytest.fixture()
def fixture_artifact(tmp_path, monkeypatch):
    mu, sd, weights = [0.0, 0.0, 0.0], [1.0, 1.0, 1.0], [1.0, 1.0, 1.0]
    reference_inputs = [[0.1, 0.2, 0.3]]
    payload = {
        "schema_version": 1,
        "channel_order": ["peer_centered_z", "compression", "function_word_network"],
        "mu": mu,
        "sd": sd,
        "weights": weights,
        "intercept": 0.0,
        "threshold_fa5": 0.5,
        "threshold_fa1": 1.5,
        "reference_inputs": reference_inputs,
        "reference_outputs": [float(np.dot(reference_inputs[0], weights))],
        "provenance": {"dataset": "unit-test"},
    }
    path = tmp_path / "fused.json"
    path.write_text(json.dumps(payload))
    monkeypatch.setenv("FUSED_SCORE_MODEL_PATH", str(path))
    artifact_module.reset_for_tests()
    peers.reset_cache_for_tests()
    yield path
    artifact_module.reset_for_tests()
    peers.reset_cache_for_tests()


def _cohort(n: int = 12) -> list[StudentState]:
    return [_state(f"t1:peer{i}") for i in range(n)]


def test_returns_a_populated_result_when_everything_is_available(fixture_artifact):
    claimed = _state("t1:alice")
    result = predict_fused_score(_LONG[:4000], claimed, [claimed] + _cohort())
    assert isinstance(result, FusedScoreResult)
    assert result.reference_profiles == 8
    assert result.baseline_samples == 3
    assert set(result.channels) == {"peer_centered_z", "compression", "function_word_network"}
    assert 0.0 <= result.probability_different_author <= 1.0
    assert result.band in {"consistent", "inconclusive", "divergent"}
    assert result.model_version == "v1"
    assert result.trained_on == "unit-test"


def test_probability_is_the_sigmoid_of_the_log_odds(fixture_artifact):
    claimed = _state("t1:alice")
    result = predict_fused_score(_LONG[:4000], claimed, [claimed] + _cohort())
    expected = 1.0 / (1.0 + np.exp(-result.fused_log_odds))
    assert result.probability_different_author == pytest.approx(expected, abs=1e-6)


def test_channel_values_are_peer_centered(fixture_artifact):
    """A probe in the claimed author's own style scores below the peer mean."""
    claimed = _state("t1:alice")
    cohort = [_state(f"t1:peer{i}", words=_OTHER) for i in range(12)]
    result = predict_fused_score(_LONG[:4000], claimed, [claimed] + cohort)
    assert result is not None
    assert result.channels["compression"] < 0.0


def test_result_is_deterministic(fixture_artifact):
    claimed = _state("t1:alice")
    cohort = [claimed] + _cohort()
    first = predict_fused_score(_LONG[:4000], claimed, cohort)
    second = predict_fused_score(_LONG[:4000], claimed, cohort)
    assert first == second


def test_supplied_probe_vector_avoids_re_extraction(fixture_artifact, monkeypatch):
    """The scoring path hands over the vector it already has; we must use it."""
    import original.features.pipeline as pipeline

    calls = {"n": 0}
    real = pipeline.feature_vector

    def counting(text):
        calls["n"] += 1
        return real(text)

    monkeypatch.setattr(pipeline, "feature_vector", counting)
    claimed = _state("t1:alice")
    supplied = np.asarray(real(_LONG[:4000]), dtype=np.float64)
    calls["n"] = 0
    result = predict_fused_score(
        _LONG[:4000], claimed, [claimed] + _cohort(), probe_vector=supplied
    )
    assert result is not None
    assert calls["n"] == 0, "probe_vector was ignored and features were re-extracted"


def test_supplied_and_extracted_vectors_agree(fixture_artifact):
    from original.features.pipeline import feature_vector

    claimed = _state("t1:alice")
    cohort = [claimed] + _cohort()
    supplied = np.asarray(feature_vector(_LONG[:4000]), dtype=np.float64)
    with_vector = predict_fused_score(_LONG[:4000], claimed, cohort, probe_vector=supplied)
    without = predict_fused_score(_LONG[:4000], claimed, cohort)
    assert with_vector == without


def test_abstains_on_short_probe(fixture_artifact):
    claimed = _state("t1:alice")
    assert predict_fused_score("too short", claimed, [claimed] + _cohort()) is None


def test_abstains_below_three_text_carrying_baselines(fixture_artifact):
    claimed = _state("t1:alice", samples=2)
    assert predict_fused_score(_LONG[:4000], claimed, [claimed] + _cohort()) is None


def test_abstains_below_eight_peers(fixture_artifact):
    claimed = _state("t1:alice")
    assert predict_fused_score(_LONG[:4000], claimed, [claimed] + _cohort(5)) is None


def test_abstains_when_the_artifact_is_unavailable(tmp_path, monkeypatch):
    monkeypatch.setenv("FUSED_SCORE_MODEL_PATH", str(tmp_path / "absent.json"))
    artifact_module.reset_for_tests()
    peers.reset_cache_for_tests()
    claimed = _state("t1:alice")
    assert predict_fused_score(_LONG[:4000], claimed, [claimed] + _cohort()) is None


def test_never_raises_when_a_channel_explodes(fixture_artifact, monkeypatch):
    monkeypatch.setattr(
        "original.fusion.expert.compression_distance",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")),
    )
    claimed = _state("t1:alice")
    assert predict_fused_score(_LONG[:4000], claimed, [claimed] + _cohort()) is None


def test_honours_a_two_channel_artifact(tmp_path, monkeypatch):
    mu, sd, weights = [0.0, 0.0], [1.0, 1.0], [1.0, 1.0]
    payload = {
        "schema_version": 1,
        "channel_order": ["peer_centered_z", "compression"],
        "mu": mu,
        "sd": sd,
        "weights": weights,
        "intercept": 0.0,
        "threshold_fa5": 0.5,
        "threshold_fa1": 1.5,
        "reference_inputs": [[0.1, 0.2]],
        "reference_outputs": [float(np.dot([0.1, 0.2], weights))],
        "provenance": {"dataset": "unit-test-2ch"},
    }
    path = tmp_path / "fused2.json"
    path.write_text(json.dumps(payload))
    monkeypatch.setenv("FUSED_SCORE_MODEL_PATH", str(path))
    artifact_module.reset_for_tests()
    peers.reset_cache_for_tests()
    claimed = _state("t1:alice")
    result = predict_fused_score(_LONG[:4000], claimed, [claimed] + _cohort())
    assert result is not None
    assert set(result.channels) == {"peer_centered_z", "compression"}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/fusion/test_expert.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'original.fusion.expert'`

- [ ] **Step 3: Implement the expert**

Create `original/fusion/expert.py`:

```python
"""Orchestrate the fused score: profile -> center -> fuse -> abstain.

Report-only by construction. This module receives no mutable scoring state
and returns a frozen dataclass; it cannot reach deviation_score,
quantum_fidelity, or the recommended action even by accident.

Peer-centering is one generic step applied identically to all three
channels: each channel's raw distance to the claimed author, minus the mean
of its raw distances to the eight references. A negative value means the
probe sits closer to the claimed author than to a typical classmate.
"""

from __future__ import annotations

import logging
import math
from collections.abc import Iterable
from dataclasses import dataclass

import numpy as np

from ..quantum.state import StudentState
from .artifact import load_artifact
from .channels import (
    compression_distance,
    diagonal_z_distance,
    function_word_distance,
    function_word_matrix,
)
from .peers import MIN_WORDS, Profile, build_profile, select_references

log = logging.getLogger(__name__)


@dataclass(frozen=True, eq=True)
class FusedScoreResult:
    """Report-only evidence weight. Higher log-odds = more impostor-like.

    ``eq=True`` gives value equality (the determinism test relies on it);
    the dict field makes instances unhashable, which is correct — these are
    per-submission observations, never dictionary keys.
    """

    fused_log_odds: float
    probability_different_author: float
    band: str
    channels: dict[str, float]
    reference_profiles: int
    baseline_samples: int
    model_version: str
    trained_on: str


def reset_for_tests() -> None:
    from . import artifact, peers

    artifact.reset_for_tests()
    peers.reset_cache_for_tests()


def _raw_distances(
    profile: Profile,
    probe_vec: np.ndarray,
    probe_text: str,
    probe_fw: np.ndarray,
) -> dict[str, float]:
    return {
        "peer_centered_z": diagonal_z_distance(
            probe_vec, profile.baseline_mean, profile.baseline_std
        ),
        "compression": compression_distance(
            profile.text, probe_text, baseline_size=profile.compressed_size
        ),
        "function_word_network": function_word_distance(profile.fw_matrix, probe_fw),
    }


def predict_fused_score(
    text: str,
    claimed_state: StudentState,
    states: Iterable[StudentState],
    *,
    probe_vector: np.ndarray | None = None,
) -> FusedScoreResult | None:
    """Fused, peer-centered evidence weight — or ``None`` when unavailable.

    ``probe_vector`` lets the scoring path hand over the feature vector it
    has already extracted. Feature extraction is the most expensive step in
    scoring, and re-running it here would double that cost for every
    submission; omit the argument only in tests and offline tools.

    Returns None (never raises, never a partial result) when the probe is
    too short, the claimed baseline carries fewer than three text samples,
    fewer than eight eligible same-tenant peers exist, the artifact is
    missing or invalid, or any channel fails.
    """
    try:
        # Cheapest checks first: a short probe or a missing artifact must not
        # pay for eight peer profiles before abstaining.
        if len(text.split()) < MIN_WORDS:
            return None

        model = load_artifact()
        if model is None:
            return None

        claimed_profile = build_profile(claimed_state)
        if claimed_profile is None:
            return None

        references = select_references(claimed_state, states)
        if not references:
            return None

        probe_vec = _probe_vector(text, claimed_state, probe_vector)
        if probe_vec is None:
            return None
        probe_fw = function_word_matrix(text)

        own = _raw_distances(claimed_profile, probe_vec, text, probe_fw)
        peer_rows = [
            _raw_distances(reference, probe_vec, text, probe_fw) for reference in references
        ]
        centered = {
            name: float(own[name] - np.mean([row[name] for row in peer_rows]))
            for name in own
        }

        values = np.asarray([centered[name] for name in model.channel_order], dtype=np.float64)
        log_odds = model.log_odds(values)
        return FusedScoreResult(
            fused_log_odds=round(log_odds, 6),
            probability_different_author=round(1.0 / (1.0 + math.exp(-log_odds)), 6),
            band=model.band(log_odds),
            channels={name: round(centered[name], 6) for name in model.channel_order},
            reference_profiles=len(references),
            baseline_samples=claimed_profile.sample_count,
            model_version=model.model_version,
            trained_on=model.trained_on,
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("Fused score failed (%s: %s); returning None", type(exc).__name__, exc)
        return None


def _probe_vector(
    text: str,
    claimed_state: StudentState,
    supplied: np.ndarray | None,
) -> np.ndarray | None:
    """The probe's feature vector: the caller's if given, else extracted here."""
    if supplied is not None:
        vector = np.asarray(supplied, dtype=np.float64)
    else:
        from ..features.pipeline import feature_vector

        vector = np.asarray(feature_vector(text), dtype=np.float64)
    if vector.shape != claimed_state.baseline_mean.shape:
        log.warning(
            "Fused score: probe vector shape %s != baseline %s",
            vector.shape,
            claimed_state.baseline_mean.shape,
        )
        return None
    return vector
```

Then replace `original/fusion/__init__.py` with:

```python
"""Report-only fused stylometric score.

See docs/superpowers/specs/2026-08-11-fused-score-design.md. Never changes
deviation_score, quantum_fidelity, or the recommended action.
"""

from .expert import FusedScoreResult, predict_fused_score, reset_for_tests

__all__ = ["FusedScoreResult", "predict_fused_score", "reset_for_tests"]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/fusion/test_expert.py -q`
Expected: PASS — 12 passed

- [ ] **Step 5: Run the whole fusion suite**

Run: `.venv/bin/python -m pytest tests/fusion/ -q`
Expected: PASS — 46 passed

- [ ] **Step 6: Commit**

```bash
git add original/fusion/expert.py original/fusion/__init__.py tests/fusion/test_expert.py
git commit -m "Add fused score expert orchestration

Peer-centering is one generic step applied to all three channels: each
channel's distance to the claimed author minus the mean of its distances
to the eight references. Abstains with None on short probes, thin
baselines, too few peers, a missing artifact, or any channel failure.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 5: Training script and committed artifact

**Files:**
- Create: `scripts/train_fused_score.py`
- Create: `original/data/fused_score_v1.json` (generated by running the script)
- Test: `tests/fusion/test_shipped_artifact.py`

**Interfaces:**
- Consumes: `channels.*` (Task 1), `artifact.load_artifact` / `EXPECTED_SCHEMA_VERSION` (Task 3), `validation.verify.pan_style_expert.load_author_partitions`.
- Produces: `original/data/fused_score_v1.json` conforming to the Task 3 schema.

- [ ] **Step 1: Write the failing test**

Create `tests/fusion/test_shipped_artifact.py`:

```python
"""The committed artifact must load under the production loader."""

from __future__ import annotations

import json

from original.fusion.artifact import (
    DEFAULT_ARTIFACT_PATH,
    EXPECTED_SCHEMA_VERSION,
    load_artifact,
    reset_for_tests,
)
from original.fusion.channels import CHANNEL_NAMES


def test_shipped_artifact_exists():
    assert DEFAULT_ARTIFACT_PATH.exists(), f"missing {DEFAULT_ARTIFACT_PATH}"


def test_shipped_artifact_loads_under_the_production_loader(monkeypatch):
    monkeypatch.delenv("FUSED_SCORE_MODEL_PATH", raising=False)
    reset_for_tests()
    loaded = load_artifact()
    reset_for_tests()
    assert loaded is not None, "committed artifact failed validation"
    assert all(name in CHANNEL_NAMES for name in loaded.channel_order)
    assert loaded.threshold_fa5 < loaded.threshold_fa1


def test_shipped_artifact_records_its_provenance():
    payload = json.loads(DEFAULT_ARTIFACT_PATH.read_text())
    assert payload["schema_version"] == EXPECTED_SCHEMA_VERSION
    provenance = payload["provenance"]
    assert provenance["n_references"] == 8
    assert provenance["n_development_authors"] >= 100
    assert provenance["dataset"]
    assert provenance["trained"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/fusion/test_shipped_artifact.py -q`
Expected: FAIL — `assert False, missing .../original/data/fused_score_v1.json`

- [ ] **Step 3: Write the training script**

Create `scripts/train_fused_score.py`:

```python
"""Regenerate original/data/fused_score_v1.json from PAN development authors.

Offline only — may use sklearn; the runtime loader never does. Run:

    .venv/bin/python scripts/train_fused_score.py

Fits the standardizer and logistic on the 120 development authors, runs a
per-channel ablation to decide whether the function-word network ships,
selects the 5%/1% false-alarm thresholds on development genuine trials, and
prints held-out metrics on the 52 locked authors for the record. Nothing
about the held-out authors influences any fitted value.
"""

from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import numpy as np
from sklearn.linear_model import LogisticRegression

from original.features.pipeline import feature_vector
from original.fusion.channels import (
    CHANNEL_NAMES,
    compressed_size,
    compression_distance,
    diagonal_z_distance,
    function_word_distance,
    function_word_matrix,
)
from validation.verify.pan_style_expert import load_author_partitions

SEED = 20260807
N_REFERENCES = 8
PAN_CACHE = ROOT / ".benchmark_cache" / "pan" / "2020"
OUT_PATH = ROOT / "original" / "data" / "fused_score_v1.json"
ABLATION_MIN_AUC_GAIN = 0.002  # below this a channel is noise and is dropped


def _profile(texts: list[str]) -> dict:
    joined = "\n".join(texts)
    vectors = np.stack([np.asarray(feature_vector(t), dtype=np.float64) for t in texts])
    return {
        "text": joined,
        "size": compressed_size(joined.encode("utf-8", "ignore")),
        "fw": function_word_matrix(joined),
        "mean": vectors.mean(axis=0),
        "std": np.maximum(vectors.std(axis=0), max(0.005, 0.15 / np.sqrt(len(texts)))),
    }


def _raw(profile: dict, probe_vec, probe_text, probe_fw) -> list[float]:
    return [
        diagonal_z_distance(probe_vec, profile["mean"], profile["std"]),
        compression_distance(profile["text"], probe_text, baseline_size=profile["size"]),
        function_word_distance(profile["fw"], probe_fw),
    ]


def _trials(authors, reference_pool, rng):
    """(X, y) with y=1 meaning impostor. Ring assignment for impostor probes."""
    profiles = [_profile(list(a.baselines)) for a in authors]
    ref_profiles = [_profile(list(a.baselines)) for a in reference_pool[:N_REFERENCES]]
    order = list(range(len(authors)))
    rng.shuffle(order)
    impostor_of = {order[i]: order[(i + 1) % len(order)] for i in range(len(order))}

    rows, labels = [], []
    for index, author in enumerate(authors):
        probes = [(t, 0) for t in author.probes]
        probes += [(t, 1) for t in authors[impostor_of[index]].probes]
        for text, label in probes:
            vec = np.asarray(feature_vector(text), dtype=np.float64)
            fw = function_word_matrix(text)
            own = _raw(profiles[index], vec, text, fw)
            peer = np.mean([_raw(p, vec, text, fw) for p in ref_profiles], axis=0)
            rows.append(list(np.asarray(own) - peer))
            labels.append(label)
    return np.asarray(rows), np.asarray(labels)


def _auc(scores, labels) -> float:
    scores, labels = np.asarray(scores, float), np.asarray(labels)
    pos, neg = scores[labels == 1], scores[labels == 0]
    if not len(pos) or not len(neg):
        return float("nan")
    diff = pos[:, None] - neg[None, :]
    return float(((diff > 0).sum() + 0.5 * (diff == 0).sum()) / diff.size)


def _fit(X, y):
    mu, sd = X.mean(axis=0), X.std(axis=0) + 1e-12
    model = LogisticRegression(C=1e6, max_iter=5000).fit((X - mu) / sd, y)
    return mu, sd, model


def main() -> None:
    rng = np.random.default_rng(SEED)
    partitions = load_author_partitions(cache_dir=PAN_CACHE)
    development = partitions["development"]
    held_out = partitions["calibration"] + partitions["locked"]
    print(f"development={len(development)} held_out={len(held_out)}", flush=True)

    X_dev, y_dev = _trials(development, development, np.random.default_rng(SEED + 1))
    X_eval, y_eval = _trials(held_out, development, np.random.default_rng(SEED + 2))

    # Ablation: keep a channel only if dropping it costs more than the floor.
    mu, sd, model = _fit(X_dev, y_dev)
    full_auc = _auc(model.decision_function((X_dev - mu) / sd), y_dev)
    keep = []
    for index, name in enumerate(CHANNEL_NAMES):
        columns = [i for i in range(len(CHANNEL_NAMES)) if i != index]
        m2, s2, reduced = _fit(X_dev[:, columns], y_dev)
        without = _auc(reduced.decision_function((X_dev[:, columns] - m2) / s2), y_dev)
        gain = full_auc - without
        print(f"ablation {name:24s} dev AUC without = {without:.4f}  gain = {gain:+.4f}")
        if gain >= ABLATION_MIN_AUC_GAIN:
            keep.append(index)
    if not keep:
        raise SystemExit("ablation dropped every channel — refusing to write an empty model")
    channel_order = [CHANNEL_NAMES[i] for i in keep]
    print(f"shipping channels: {channel_order}", flush=True)

    mu, sd, model = _fit(X_dev[:, keep], y_dev)
    weights = model.coef_[0]
    intercept = float(model.intercept_[0])

    dev_scores = ((X_dev[:, keep] - mu) / sd) @ weights + intercept
    genuine = np.sort(dev_scores[y_dev == 0])
    threshold_fa5 = float(genuine[int(round(0.95 * (len(genuine) - 1)))])
    threshold_fa1 = float(genuine[int(round(0.99 * (len(genuine) - 1)))])
    if not threshold_fa5 < threshold_fa1:
        threshold_fa1 = threshold_fa5 + 1e-6

    eval_scores = ((X_eval[:, keep] - mu) / sd) @ weights + intercept
    print(f"\nHELD-OUT AUC  = {_auc(eval_scores, y_eval):.4f}")
    for name, bar in (("fa5", threshold_fa5), ("fa1", threshold_fa1)):
        caught = float(np.mean(eval_scores[y_eval == 1] >= bar))
        false_alarm = float(np.mean(eval_scores[y_eval == 0] >= bar))
        print(f"  at {name}: catch = {caught:.3f}  false alarms = {false_alarm:.3f}")

    reference_inputs = X_dev[:5, keep]
    reference_outputs = [
        float(np.dot((row - mu) / sd, weights) + intercept) for row in reference_inputs
    ]
    payload = {
        "schema_version": 1,
        "channel_order": channel_order,
        "mu": [float(v) for v in mu],
        "sd": [float(v) for v in sd],
        "weights": [float(v) for v in weights],
        "intercept": intercept,
        "threshold_fa5": threshold_fa5,
        "threshold_fa1": threshold_fa1,
        "reference_inputs": [[float(v) for v in row] for row in reference_inputs],
        "reference_outputs": reference_outputs,
        "provenance": {
            "dataset": "PAN 2020 cross-fandom authorship verification",
            "n_development_authors": len(development),
            "n_references": N_REFERENCES,
            "trained": date.today().isoformat(),
            "seed": SEED,
        },
    }
    OUT_PATH.write_text(json.dumps(payload, indent=2) + "\n")
    print(f"\nwrote {OUT_PATH}", flush=True)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run the training script**

Run: `.venv/bin/python scripts/train_fused_score.py`
Expected: ablation lines for all three channels, a `shipping channels: [...]` line, `HELD-OUT AUC = 0.8x`, and `wrote .../original/data/fused_score_v1.json`.

This takes several minutes (feature extraction over ~1,000 texts). If the PAN cache is absent the loader raises `RuntimeError: need N eligible authors` — the corpus must exist at `.benchmark_cache/pan/2020/`.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/fusion/test_shipped_artifact.py -q`
Expected: PASS — 3 passed

- [ ] **Step 6: Commit**

```bash
git add scripts/train_fused_score.py original/data/fused_score_v1.json tests/fusion/test_shipped_artifact.py
git commit -m "Add fused-score training script and committed artifact

Fits the standardizer and logistic on 120 PAN development authors, runs a
per-channel ablation that decides whether the function-word network ships,
and selects the 5%/1% false-alarm thresholds on development genuine trials.
Held-out metrics on the 52 locked authors are printed, never fitted on.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 6: Persistence — table, repository seam, migration, FERPA surfaces

**Files:**
- Modify: `original/store.py` (DDL near line 215; `put_fused_score` / `get_fused_scores` near line 1019; `delete_student` purge near line 1266; data inventory near line 2621 and 2665)
- Modify: `original/repository.py` (protocol near line 102; SQLite delegate near line 401; `_WRITE_METHODS` near line 735)
- Modify: `original/db/models/live.py` (new `FusedScore` model after `AiLikelihoodScore` at line 287)
- Modify: `original/db/models/__init__.py` (import + `__all__`)
- Modify: `original/postgres_repository.py` (import + methods after `get_ai_likelihood_scores`)
- Create: `alembic/versions/9f2c7a1b4d63_fused_scores.py`
- Test: `tests/fusion/test_persistence.py`

**Interfaces:**
- Consumes: nothing from Tasks 1–5 (independent).
- Produces:
  - `store.put_fused_score(submission_id, student_id, fused_log_odds, probability, band, channels, model_version="") -> None`
  - `store.get_fused_scores(student_id=None, limit=500) -> list[dict]` (each dict has keys `submission_id`, `student_id`, `fused_log_odds`, `probability`, `band`, `channels`, `model_version`, `created_at`)
  - The same two names on `Repository`, `SqliteRepository`, and `PostgresRepository`.

- [ ] **Step 1: Write the failing tests**

Create `tests/fusion/test_persistence.py`:

```python
"""fused_scores: round-trip, idempotency, FERPA purge, inventory."""

from __future__ import annotations

import uuid

import original.store as store


def _sid() -> str:
    return f"persist-test:{uuid.uuid4().hex[:8]}"


def test_put_and_get_round_trip():
    student_id = _sid()
    submission_id = uuid.uuid4().hex
    store.put_fused_score(
        submission_id,
        student_id,
        fused_log_odds=1.25,
        probability=0.777,
        band="divergent",
        channels={"peer_centered_z": -0.1, "compression": 0.4},
        model_version="v1",
    )
    rows = store.get_fused_scores(student_id)
    assert len(rows) == 1
    row = rows[0]
    assert row["submission_id"] == submission_id
    assert row["fused_log_odds"] == 1.25
    assert row["probability"] == 0.777
    assert row["band"] == "divergent"
    assert row["channels"] == {"peer_centered_z": -0.1, "compression": 0.4}
    assert row["model_version"] == "v1"


def test_rewriting_the_same_submission_keeps_one_row():
    student_id = _sid()
    submission_id = uuid.uuid4().hex
    for probability in (0.10, 0.90):
        store.put_fused_score(
            submission_id,
            student_id,
            fused_log_odds=0.0,
            probability=probability,
            band="consistent",
            channels={},
        )
    rows = store.get_fused_scores(student_id)
    assert len(rows) == 1
    assert rows[0]["probability"] == 0.90


def test_channels_survive_as_structured_data_not_a_string():
    """The refit path depends on reading per-channel values back as numbers."""
    student_id = _sid()
    store.put_fused_score(
        uuid.uuid4().hex,
        student_id,
        fused_log_odds=0.0,
        probability=0.5,
        band="consistent",
        channels={"compression": -0.25},
    )
    value = store.get_fused_scores(student_id)[0]["channels"]["compression"]
    assert isinstance(value, float)
    assert value == -0.25


def test_persistence_failure_does_not_raise(monkeypatch):
    monkeypatch.setattr(
        store, "_get_conn", lambda: (_ for _ in ()).throw(RuntimeError("db down"))
    )
    store.put_fused_score(
        uuid.uuid4().hex, _sid(), fused_log_odds=0.0, probability=0.5, band="consistent",
        channels={},
    )  # must not raise


def test_delete_student_purges_fused_rows():
    student_id = _sid()
    store.get_or_create(student_id)
    store.put_fused_score(
        uuid.uuid4().hex, student_id, fused_log_odds=0.0, probability=0.5,
        band="consistent", channels={},
    )
    assert store.get_fused_scores(student_id)
    store.delete_student(student_id)
    assert store.get_fused_scores(student_id) == []


def test_data_inventory_reports_the_count():
    student_id = _sid()
    store.get_or_create(student_id)
    store.put_fused_score(
        uuid.uuid4().hex, student_id, fused_log_odds=0.0, probability=0.5,
        band="consistent", channels={},
    )
    inventory = store.data_inventory(student_id)
    assert inventory["records"]["fused_scores"]["count"] == 1


def test_repository_exposes_the_write_and_marks_it_a_write_method():
    from original.repository import _WRITE_METHODS, SqliteRepository

    assert "put_fused_score" in _WRITE_METHODS
    repo = SqliteRepository()
    student_id = _sid()
    repo.put_fused_score(
        uuid.uuid4().hex, student_id, fused_log_odds=0.5, probability=0.6,
        band="inconclusive", channels={"compression": 0.1}, model_version="v1",
    )
    assert repo.get_fused_scores(student_id)[0]["band"] == "inconclusive"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/fusion/test_persistence.py -q`
Expected: FAIL — `AttributeError: module 'original.store' has no attribute 'put_fused_score'`

- [ ] **Step 3: Add the SQLite DDL**

In `original/store.py`, immediately after the `idx_ai_likelihood_student` index block (ends ~line 227), insert:

```python
    # Fused stylometric score (report-only, see original/fusion/). One row per
    # scored submission when FUSED_SCORE_SHADOW=1 or FUSED_SCORE_ENABLED=1.
    # channels_json holds the peer-centered per-channel values so the fusion
    # weights can be refit on real traffic without re-extracting features.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS fused_scores (
            submission_id   TEXT PRIMARY KEY,
            student_id      TEXT NOT NULL,
            fused_log_odds  REAL NOT NULL,
            probability     REAL NOT NULL,
            band            TEXT NOT NULL,
            channels_json   TEXT NOT NULL DEFAULT '{}',
            model_version   TEXT NOT NULL DEFAULT '',
            created_at      TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_fused_scores_student
            ON fused_scores(student_id, created_at)
    """)
```

- [ ] **Step 4: Add the store read/write functions**

In `original/store.py`, immediately after `get_ai_likelihood_scores` ends (~line 1065), insert:

```python
def put_fused_score(
    submission_id: str,
    student_id: str,
    fused_log_odds: float,
    probability: float,
    band: str,
    channels: dict[str, float],
    model_version: str = "",
) -> None:
    """Upsert one fused-score row. Never raises — persistence must never
    break the scoring endpoint (same contract as put_ai_likelihood_score)."""
    import datetime
    import json as _json

    created_at = datetime.datetime.utcnow().isoformat()
    try:
        with _get_conn() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO fused_scores
                    (submission_id, student_id, fused_log_odds, probability,
                     band, channels_json, model_version, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    submission_id,
                    student_id,
                    float(fused_log_odds),
                    float(probability),
                    str(band),
                    _json.dumps({k: float(v) for k, v in (channels or {}).items()}),
                    str(model_version),
                    created_at,
                ),
            )
            conn.commit()
    except Exception:
        log.exception("put_fused_score failed for %s", submission_id)


def get_fused_scores(student_id: str | None = None, limit: int = 500) -> list[dict]:
    """Fused-score rows, newest first. Empty list on any failure."""
    import json as _json

    try:
        with _get_conn() as conn:
            if student_id is not None:
                rows = conn.execute(
                    """
                    SELECT submission_id, student_id, fused_log_odds, probability,
                           band, channels_json, model_version, created_at
                    FROM fused_scores WHERE student_id = ?
                    ORDER BY created_at DESC LIMIT ?
                    """,
                    (student_id, int(limit)),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT submission_id, student_id, fused_log_odds, probability,
                           band, channels_json, model_version, created_at
                    FROM fused_scores
                    ORDER BY created_at DESC LIMIT ?
                    """,
                    (int(limit),),
                ).fetchall()
        out = []
        for row in rows:
            try:
                channels = _json.loads(row[5])
            except Exception:
                channels = {}
            out.append(
                {
                    "submission_id": row[0],
                    "student_id": row[1],
                    "fused_log_odds": row[2],
                    "probability": row[3],
                    "band": row[4],
                    "channels": {k: float(v) for k, v in channels.items()},
                    "model_version": row[6],
                    "created_at": row[7],
                }
            )
        return out
    except Exception:
        log.exception("get_fused_scores failed")
        return []
```

- [ ] **Step 5: Add the FERPA purge and inventory count**

In `original/store.py` `delete_student`, immediately after the `DELETE FROM ai_likelihood_scores` line (~1266), add:

```python
            conn.execute("DELETE FROM fused_scores WHERE student_id = ?", (student_id,))
```

In the same function's docstring table (~line 1237), after the `ai_likelihood_scores` bullet, add:

```
    - fused_scores          (SQLite — report-only fused score rows)
```

In `data_inventory`, after the `ai_likelihood_count` query (~line 2622), add:

```python
            fused_count = conn.execute(
                "SELECT COUNT(*) FROM fused_scores WHERE student_id = ?",
                (student_id,),
            ).fetchone()[0]
```

In the same function's `except` fallback (~line 2633) add `fused_count = 0`, and in the returned `records` dict after the `ai_likelihood_scores` entry (~line 2667) add:

```python
            "fused_scores": {
                "count": int(fused_count),
            },
```

- [ ] **Step 6: Wire the repository seam**

In `original/repository.py`, in the `Repository` protocol after `get_ai_likelihood_scores` (~line 114):

```python
    def put_fused_score(
        self,
        submission_id: str,
        student_id: str,
        fused_log_odds: float,
        probability: float,
        band: str,
        channels: dict[str, float],
        model_version: str = "",
    ) -> None: ...
    def get_fused_scores(
        self,
        student_id: str | None = None,
        limit: int = 500,
    ) -> list[dict]: ...
```

In `SqliteRepository` after its `get_ai_likelihood_scores` delegate (~line 420):

```python
    def put_fused_score(
        self,
        submission_id: str,
        student_id: str,
        fused_log_odds: float,
        probability: float,
        band: str,
        channels: dict[str, float],
        model_version: str = "",
    ) -> None:
        store.put_fused_score(
            submission_id,
            student_id,
            fused_log_odds,
            probability,
            band,
            channels,
            model_version=model_version,
        )

    def get_fused_scores(
        self,
        student_id: str | None = None,
        limit: int = 500,
    ) -> list[dict]:
        return store.get_fused_scores(student_id, limit=limit)
```

In `_WRITE_METHODS` (~line 735), after `"put_ai_likelihood_score",` add:

```python
        "put_fused_score",
```

- [ ] **Step 7: Add the ORM model**

In `original/db/models/live.py`, immediately after the `AiLikelihoodScore` class (ends ~line 312):

```python
class FusedScore(LiveBase):
    """Report-only fused stylometric score (``fused_scores``).

    One row per scored submission when FUSED_SCORE_SHADOW=1 or
    FUSED_SCORE_ENABLED=1. ``channels_json`` carries the peer-centered
    per-channel values so weights can be refit without re-extraction.
    """

    __tablename__ = "fused_scores"
    __table_args__ = (
        Index(
            "idx_fused_scores_tenant_student",
            "tenant_id",
            "student_id",
            "created_at",
        ),
    )

    submission_id: Mapped[str] = mapped_column(Text, primary_key=True)
    tenant_id: Mapped[str] = mapped_column(Text, ForeignKey("tenants.tenant_id"), nullable=False)
    student_id: Mapped[str] = mapped_column(Text, nullable=False)
    fused_log_odds: Mapped[float] = mapped_column(Float, nullable=False)
    probability: Mapped[float] = mapped_column(Float, nullable=False)
    band: Mapped[str] = mapped_column(Text, nullable=False)
    channels_json: Mapped[str] = mapped_column(Text, nullable=False, server_default="{}")
    model_version: Mapped[str] = mapped_column(Text, nullable=False, server_default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
```

Add `FusedScore` to the `__all__`-style export list at the bottom of `live.py` (~line 647, where `AiLikelihoodScore` appears), and to both the import block (~line 28) and `__all__` (~line 82) of `original/db/models/__init__.py`.

- [ ] **Step 8: Add the Postgres methods**

In `original/postgres_repository.py`, add `FusedScore` to the `from .db.models.live import (...)` block (~line 33), then after `get_ai_likelihood_scores` (~line 897):

```python
    def put_fused_score(
        self,
        submission_id,
        student_id,
        fused_log_odds,
        probability,
        band,
        channels,
        model_version="",
    ):
        try:
            channels_json = json.dumps({k: float(v) for k, v in (channels or {}).items()})
            with session_scope() as session:
                tenant_id, local_id = split_scoped_id(student_id)
                self._ensure_tenant_exists(session, tenant_id)
                values = {
                    "tenant_id": tenant_id,
                    "student_id": local_id,
                    "fused_log_odds": float(fused_log_odds),
                    "probability": float(probability),
                    "band": str(band),
                    "channels_json": channels_json,
                    "model_version": str(model_version),
                    "created_at": datetime.now(UTC),
                }
                stmt = (
                    pg_insert(FusedScore)
                    .values(submission_id=submission_id, **values)
                    .on_conflict_do_update(index_elements=["submission_id"], set_=values)
                )
                session.execute(stmt)
        except Exception:
            log.exception("put_fused_score failed for %s", submission_id)

    def get_fused_scores(self, student_id=None, limit=500):
        try:
            with session_scope() as session:
                stmt = select(FusedScore)
                if student_id is not None:
                    tenant_id, local_id = split_scoped_id(student_id)
                    stmt = stmt.where(
                        FusedScore.tenant_id == tenant_id,
                        FusedScore.student_id == local_id,
                    )
                stmt = stmt.order_by(FusedScore.created_at.desc()).limit(int(limit))
                rows = session.execute(stmt).scalars().all()
                out = []
                for row in rows:
                    try:
                        channels = json.loads(row.channels_json)
                    except Exception:
                        channels = {}
                    out.append(
                        {
                            "submission_id": row.submission_id,
                            "student_id": join_scoped_id(row.tenant_id, row.student_id),
                            "fused_log_odds": row.fused_log_odds,
                            "probability": row.probability,
                            "band": row.band,
                            "channels": {k: float(v) for k, v in channels.items()},
                            "model_version": row.model_version,
                            "created_at": row.created_at.isoformat() if row.created_at else "",
                        }
                    )
                return out
        except Exception:
            log.exception("get_fused_scores failed")
            return []
```

Also extend the table census near line 565. Find the block that computes `ai_likelihood_count`, add this line immediately beside it:

```python
                fused_count = session.scalar(select(func.count()).select_from(FusedScore)) or 0
```

and add this entry to the returned dict immediately after the `"ai_likelihood_scores"` entry:

```python
                    "fused_scores": {"count": int(fused_count)},
```

- [ ] **Step 9: Add the alembic migration**

Create `alembic/versions/9f2c7a1b4d63_fused_scores.py`:

```python
"""fused_scores table for the report-only fused stylometric score

Revision ID: 9f2c7a1b4d63
Revises: 7c4d1e88a3b5
Create Date: 2026-08-11
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision: str = "9f2c7a1b4d63"
down_revision: str | None = "7c4d1e88a3b5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "fused_scores",
        sa.Column("submission_id", sa.Text(), nullable=False),
        sa.Column("tenant_id", sa.Text(), nullable=False),
        sa.Column("student_id", sa.Text(), nullable=False),
        sa.Column("fused_log_odds", sa.Float(), nullable=False),
        sa.Column("probability", sa.Float(), nullable=False),
        sa.Column("band", sa.Text(), nullable=False),
        sa.Column("channels_json", sa.Text(), server_default="{}", nullable=False),
        sa.Column("model_version", sa.Text(), server_default="", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["tenants.tenant_id"],
            name=op.f("fk_fused_scores_tenant_id_tenants"),
        ),
        sa.PrimaryKeyConstraint("submission_id", name=op.f("pk_fused_scores")),
    )
    op.create_index(
        "idx_fused_scores_tenant_student",
        "fused_scores",
        ["tenant_id", "student_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("idx_fused_scores_tenant_student", table_name="fused_scores")
    op.drop_table("fused_scores")
```

- [ ] **Step 10: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/fusion/test_persistence.py -q`
Expected: PASS — 7 passed

- [ ] **Step 11: Verify the migration and Postgres parity**

The repository already has the SQLite/Postgres parity mechanism; these suites exercise
the ORM metadata, the migration chain, and the cutover path. `FusedScore` must appear in
the model registry and the new revision must be the single head.

Run: `.venv/bin/python -m pytest tests/test_db_models.py tests/test_migration.py tests/test_cutover.py -q`
Expected: PASS — existing counts unchanged, no new failures.

Run: `.venv/bin/python -m alembic heads`
Expected: exactly one head — `9f2c7a1b4d63`. If two heads print, the `down_revision`
is wrong; set it to whatever `.venv/bin/python -m alembic heads` reported *before* this
task and re-run.

Run: `.venv/bin/python -c "from original.db.models import FusedScore; print(FusedScore.__tablename__)"`
Expected: `fused_scores`

If the Postgres suites skip for want of a live database, that is the repository's
existing behaviour — do not stand up a database for this task; the ORM-metadata and
alembic checks above are what gate the migration.

- [ ] **Step 12: Commit**

```bash
git add original/store.py original/repository.py original/postgres_repository.py original/db/models/live.py original/db/models/__init__.py alembic/versions/9f2c7a1b4d63_fused_scores.py tests/fusion/test_persistence.py
git commit -m "Add fused_scores persistence across SQLite and Postgres

Mirrors ai_likelihood_scores: table, repository seam, ORM model, alembic
migration, FERPA purge in delete_student, and a data-inventory count.
channels_json stores peer-centered per-channel values so the fusion can be
refit on real traffic without re-extracting features.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 7: Wiring — two-mode call site and the report-only invariant

**Files:**
- Modify: `original/quantum/scoring.py` (`Layer7Output`, after `style_authorship` at line 325)
- Modify: `original/routers/students_scoring.py` (after the `STYLE_AUTHORSHIP_ENABLED` block ending line 263)
- Modify: `CLAUDE.md` (environment-flag table)
- Test: `tests/fusion/test_wiring.py`

**Interfaces:**
- Consumes: `expert.predict_fused_score` / `FusedScoreResult` (Task 4), `store.put_fused_score` (Task 6).
- Produces: `Layer7Output.fused_score: FusedScoreResult | None`.

- [ ] **Step 1: Write the failing tests**

Create `tests/fusion/test_wiring.py`:

```python
"""The two-mode call site, and the invariant that makes it safe.

Contract:
  both flags off        -> field null, no row
  FUSED_SCORE_SHADOW=1  -> row persisted, field STILL null
  FUSED_SCORE_ENABLED=1 -> row persisted AND field populated
In all three states deviation_score, quantum_fidelity, and the recommended
action are byte-identical.
"""

from __future__ import annotations

import json
import uuid

import numpy as np
import pytest
from fastapi.testclient import TestClient

import original.store as store
import run
from original.constants import FEATURE_DIM

client = TestClient(run.load_legacy_demo_app())

_LONG = (
    "However, a reader might ask why these claims have been made; therefore we reply "
    "that the argument is careful and that it is also sound. "
) * 40


@pytest.fixture()
def fixture_artifact(tmp_path, monkeypatch):
    mu, sd, weights = [0.0, 0.0, 0.0], [1.0, 1.0, 1.0], [1.0, 1.0, 1.0]
    payload = {
        "schema_version": 1,
        "channel_order": ["peer_centered_z", "compression", "function_word_network"],
        "mu": mu, "sd": sd, "weights": weights, "intercept": 0.0,
        "threshold_fa5": 0.5, "threshold_fa1": 1.5,
        "reference_inputs": [[0.1, 0.2, 0.3]],
        "reference_outputs": [float(np.dot([0.1, 0.2, 0.3], weights))],
        "provenance": {"dataset": "unit-test"},
    }
    path = tmp_path / "fused.json"
    path.write_text(json.dumps(payload))
    monkeypatch.setenv("FUSED_SCORE_MODEL_PATH", str(path))
    from original.fusion import reset_for_tests

    reset_for_tests()
    yield
    reset_for_tests()


def _seed_cohort(tenant: str) -> str:
    """One claimed student plus twelve peers, each with three long baselines."""
    claimed = f"{tenant}:alice"
    for name in ["alice"] + [f"peer{i}" for i in range(12)]:
        student_id = f"{tenant}:{name}"
        for index in range(3):
            client.post(
                f"/students/{student_id}/baseline",
                json={"text": _LONG, "provenance": "proctored",
                      "assignment": f"{name}-{index}"},
            )
    return claimed


def _score(student_id: str) -> dict:
    response = client.post(
        f"/students/{student_id}/score",
        json={"text": _LONG, "submission_id": uuid.uuid4().hex},
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_flags_off_means_no_field_and_no_row(fixture_artifact, monkeypatch):
    monkeypatch.delenv("FUSED_SCORE_ENABLED", raising=False)
    monkeypatch.delenv("FUSED_SCORE_SHADOW", raising=False)
    student_id = _seed_cohort(f"wire{uuid.uuid4().hex[:6]}")
    body = _score(student_id)
    assert body.get("fused_score") is None
    assert store.get_fused_scores(student_id) == []


def test_shadow_persists_without_attaching(fixture_artifact, monkeypatch):
    monkeypatch.delenv("FUSED_SCORE_ENABLED", raising=False)
    monkeypatch.setenv("FUSED_SCORE_SHADOW", "1")
    student_id = _seed_cohort(f"wire{uuid.uuid4().hex[:6]}")
    body = _score(student_id)
    assert body.get("fused_score") is None
    rows = store.get_fused_scores(student_id)
    assert len(rows) == 1
    assert rows[0]["band"] in {"consistent", "inconclusive", "divergent"}
    assert rows[0]["channels"]


def test_enabled_persists_and_attaches(fixture_artifact, monkeypatch):
    monkeypatch.setenv("FUSED_SCORE_ENABLED", "1")
    monkeypatch.delenv("FUSED_SCORE_SHADOW", raising=False)
    student_id = _seed_cohort(f"wire{uuid.uuid4().hex[:6]}")
    body = _score(student_id)
    attached = body.get("fused_score")
    assert attached is not None
    assert attached["band"] in {"consistent", "inconclusive", "divergent"}
    assert len(store.get_fused_scores(student_id)) == 1


def test_report_only_invariant_across_all_three_flag_states(fixture_artifact, monkeypatch):
    """THE load-bearing test: the primary score never moves."""
    student_id = _seed_cohort(f"wire{uuid.uuid4().hex[:6]}")
    observed = []
    for enabled, shadow in (("0", "0"), ("0", "1"), ("1", "0")):
        monkeypatch.setenv("FUSED_SCORE_ENABLED", enabled)
        monkeypatch.setenv("FUSED_SCORE_SHADOW", shadow)
        body = _score(student_id)
        observed.append(
            (
                body["deviation_score"],
                body["quantum_fidelity"],
                body["recommended_action"],
            )
        )
    assert observed[0] == observed[1] == observed[2], (
        f"fused score changed the primary result: {observed}"
    )


def test_a_persistence_failure_does_not_break_scoring(fixture_artifact, monkeypatch):
    monkeypatch.setenv("FUSED_SCORE_SHADOW", "1")
    monkeypatch.setattr(
        store, "put_fused_score",
        lambda *a, **k: (_ for _ in ()).throw(RuntimeError("db down")),
    )
    student_id = _seed_cohort(f"wire{uuid.uuid4().hex[:6]}")
    body = _score(student_id)
    assert "deviation_score" in body


def test_abstention_persists_nothing(fixture_artifact, monkeypatch):
    """A lone student has no peers, so the expert abstains and writes no row."""
    monkeypatch.setenv("FUSED_SCORE_SHADOW", "1")
    tenant = f"wire{uuid.uuid4().hex[:6]}"
    student_id = f"{tenant}:solo"
    for index in range(3):
        client.post(
            f"/students/{student_id}/baseline",
            json={"text": _LONG, "provenance": "proctored", "assignment": f"solo-{index}"},
        )
    _score(student_id)
    assert store.get_fused_scores(student_id) == []
```

Before running, confirm the response field names used above (`deviation_score`, `quantum_fidelity`, `recommended_action`) against the live schema:

Run: `.venv/bin/python -c "import run; from fastapi.testclient import TestClient; c=TestClient(run.load_legacy_demo_app()); print(sorted(c.get('/openapi.json').json()['components']['schemas']['ScoreResponse']['properties']))"`

If a name differs, use the actual key — do not change the endpoint.

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/fusion/test_wiring.py -q`
Expected: FAIL — `assert body.get("fused_score") is not None` fails (field does not exist yet)

- [ ] **Step 3: Add the Layer7Output field**

In `original/quantum/scoring.py`, at the top-level `if TYPE_CHECKING:` import block (~line 41, beside `StyleAuthorshipResult`), add:

```python
    from original.fusion.expert import FusedScoreResult
```

Then in `Layer7Output`, immediately after the `style_authorship` field (~line 325):

```python
    # Report-only fused stylometric score (original/fusion/). Set at the
    # students_scoring call site, never here — this module must stay unaware
    # the component exists, which is what makes the invariant testable.
    fused_score: FusedScoreResult | None = field(default=None)
```

- [ ] **Step 4: Add the two-mode call site**

In `original/routers/students_scoring.py`, immediately after the `STYLE_AUTHORSHIP_ENABLED` block (ends ~line 263), insert:

```python
    # ── Fused stylometric score (report-only, two modes) ──────────────────────
    #   FUSED_SCORE_SHADOW=1  → compute + persist ONLY; result.fused_score stays
    #     None, so narrative/explainer/response never see it. This is how the
    #     pilot false-alarm rate gets measured before the score is trusted.
    #   FUSED_SCORE_ENABLED=1 → attach AND persist (strict superset).
    # Never touches deviation_score, quantum_fidelity, or the recommendation;
    # tests/fusion/test_wiring.py holds that invariant.
    _fused_enabled = os.environ.get("FUSED_SCORE_ENABLED") == "1"
    _fused_shadow = os.environ.get("FUSED_SCORE_SHADOW") == "1"
    if _fused_enabled or _fused_shadow:
        try:
            from ..fusion import predict_fused_score

            # `vec` is the probe's already-extracted feature vector; passing it
            # keeps this signal from re-running the most expensive step in scoring.
            _fused = predict_fused_score(
                req.text, state, _repo().all_states(), probe_vector=vec
            )
        except Exception:
            logging.getLogger(__name__).exception(
                "fused score inference failed for %s — signal skipped", submission_id
            )
            _fused = None
        if _fused is not None:
            if _fused_enabled:
                result.fused_score = _fused
            try:
                _repo().put_fused_score(
                    submission_id=submission_id,
                    student_id=student_id,
                    fused_log_odds=_fused.fused_log_odds,
                    probability=_fused.probability_different_author,
                    band=_fused.band,
                    channels=_fused.channels,
                    model_version=_fused.model_version,
                )
            except Exception:
                logging.getLogger(__name__).exception(
                    "fused score persistence failed for %s", submission_id
                )
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/fusion/test_wiring.py -q`
Expected: PASS — 6 passed

- [ ] **Step 6: Document the flags**

In `CLAUDE.md`, in the environment-flag table immediately after the `AI_LIKELIHOOD_MODEL_PATH` row, add:

```markdown
| `FUSED_SCORE_ENABLED` | `0` | Attaches the report-only fused stylometric score (`original/fusion/`) — peer-centered diagonal z + LZMA conditional compression + function-word adjacency network, logistic-fused into one calibrated evidence weight. Requires retained raw text, 3 authenticated baselines, and **exactly 8** eligible same-tenant peers (the artifact is calibrated at 8 references; below that it abstains rather than extrapolate). Never changes `deviation_score`, `quantum_fidelity`, or the recommended action — held by `tests/fusion/test_wiring.py`. Measured on the PAN cross-fandom hold-out at AUC 0.889 vs 0.798 for the production score (2026-08-10 gate audit, 52 held-out authors, 103-dim features); **not yet validated against real student submissions** — run `FUSED_SCORE_SHADOW=1` first. |
| `FUSED_SCORE_SHADOW` | `0` | Computes and persists the fused score to `fused_scores` without attaching it (`result.fused_score` stays `None`). `channels_json` stores the peer-centered per-channel values so the fusion weights can be refit on real traffic without re-extracting features. Enablement is then one env flip with unbroken data continuity. |
| `FUSED_SCORE_MODEL_PATH` | unset | Path override for the committed `original/data/fused_score_v1.json`. The loader fails closed (→ `None`, identical to flag-off) on schema-version, channel-name, vector-length, threshold-monotonicity, or reference-prediction drift. Regenerate with `.venv/bin/python scripts/train_fused_score.py`. |
```

- [ ] **Step 7: Run the full fusion suite and the flag matrix**

Run: `.venv/bin/python -m pytest tests/fusion/ tests/test_flag_matrix.py -q`
Expected: PASS — all fusion tests plus the existing flag-matrix tests.

- [ ] **Step 8: Run the full suite**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: 0 failed. (Takes 5–12 minutes — do not interrupt. XFAIL/XPASS on `TestAuthEndpoints` is expected and is not a failure.)

- [ ] **Step 9: Commit**

```bash
git add original/quantum/scoring.py original/routers/students_scoring.py CLAUDE.md tests/fusion/test_wiring.py
git commit -m "Wire the fused score into scoring as a report-only signal

Two modes mirroring ai_likelihood: FUSED_SCORE_SHADOW persists without
attaching, FUSED_SCORE_ENABLED attaches and persists. quantum/scoring.py
gains only the Layer7Output field — the call site lives in the router, so
the report-only invariant is structural rather than conventional, and
tests/fusion/test_wiring.py asserts deviation_score, quantum_fidelity, and
the recommended action are byte-identical across all three flag states.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Verification checklist

Run after Task 7. Every line must pass before the branch is considered done.

- [ ] `.venv/bin/python -m pytest tests/fusion/ -q` → all pass (~59 tests)
- [ ] `.venv/bin/python -m pytest tests/ -q` → **0 failed**
- [ ] `.venv/bin/python -c "import original.quantum.scoring"` with both flags unset → no `original.fusion` import (verify with `python -X importtime` or `sys.modules` check)
- [ ] `git grep -n "fused" original/quantum/scoring.py` → only the `Layer7Output` field and its comment; no call into `original.fusion`
- [ ] `.venv/bin/python scripts/train_fused_score.py` reproduces the committed artifact byte-for-byte apart from the `trained` date
- [ ] **Latency budget (§7 of the spec): measure, do not assert.** A wall-clock
      assertion in CI is flaky and would be a worse test than none. Measure it once by
      hand and record the number in the PR description:

```bash
.venv/bin/python -c "
import time, statistics, numpy as np
from original.fusion import predict_fused_score
from original.fusion import peers
from original.quantum.state import BaselineSample, StudentState
from original.constants import FEATURE_DIM
LONG = ('However, a reader might ask why these claims have been made; therefore we reply '
        'that the argument is careful and that it is also sound. ') * 40
def st(sid):
    s = StudentState(student_id=sid)
    rng = np.random.default_rng(abs(hash(sid)) % (2**32))
    for i in range(3):
        s.add_sample(BaselineSample(text=LONG, vector=rng.uniform(.3,.7,FEATURE_DIM),
                     provenance='proctored', auth_weight=1.0, assignment=f'{sid}-{i}'))
    return s
claimed = st('t1:alice'); cohort = [claimed] + [st(f't1:p{i}') for i in range(12)]
predict_fused_score(LONG, claimed, cohort)          # warm the peer cache
times = []
for _ in range(10):
    t0 = time.perf_counter(); predict_fused_score(LONG, claimed, cohort)
    times.append((time.perf_counter()-t0)*1000)
print(f'warm p50={statistics.median(times):.0f}ms max={max(times):.0f}ms  (budget 250ms)')
"
```

      If the warm median exceeds 250 ms, do not ship — the peer cache is not being hit;
      check `peers.cache_build_count()` before and after.
