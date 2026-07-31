# Instrumentation & Validation Layer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the instrumentation layer the 2026-07-30 Instrument Report calls for: measurability-as-data, statistical-power-aware gate verdicts, experiment specs embedded in every report, corpus policy enforcement, two independent attribution engines with an ensemble, and a falsifiability test suite for gates.

**Architecture:** Five small modules under `validation/` (`measurability.py`, `power.py`, `experiment.py`, `corpus_policy.py`, `attribution/`) consumed by the existing runners (`validation/calibration_gate.py`, `scripts/derive_measured_weights.py`, `validation/public_authors/run.py`, `validation/stability/stability.py`), plus contract-based gate tests. No product code changes; everything lands in `validation/`, `scripts/`, `tests/`.

**Tech Stack:** Python 3 (venv at `/Users/andrew/Desktop/Original/.venv/`), numpy 1.26.4, hypothesis 6.112.2, pydantic (manifest models), pytest. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-07-31-instrumentation-validation-layer-design.md`

## Global Constraints

- **Never edit `original/constants.py`** feature ordering, NORM_BOUNDS, or TIER_WEIGHTS (explicit-permission list; weights are HELD per the Instrument Report).
- **No product-code changes**: `original/quantum/`, `original/features/` are read-only for this plan (imports fine).
- Python is **always** `/Users/andrew/Desktop/Original/.venv/bin/python` (the worktree has no `.venv`; system python3 has a broken pydantic_settings).
- Full fast suite must be green after every task: `/Users/andrew/Desktop/Original/.venv/bin/python -m pytest tests/ -q` → `0 failed` (XFAIL/XPASS on `TestAuthEndpoints` are fine).
- Commit style: `Add ...` / `Fix ...` / `Refactor ...`, one focused commit per task, ending with `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.
- **⚠ Moving dependency:** `claude/plato-works-dating-analysis-b05b1a` was receiving commits as recently as minutes before this plan was written (tip at planning time: `34d8ceb6`). Task 1 must re-check the tip at execution time, and Tasks 6 and 12 must re-verify `calibration_gate.py` symbol signatures before editing — anchor on symbols, never line numbers.
- Corpus-driven runners (`calibration_gate`, `public_authors/run`, `derive_measured_weights`) are **manual/CI-validation jobs**, not fast-suite tests. This plan only adds fast unit tests; never invoke the corpus runners from the fast suite.
- Local DBs are fixtures — never treat numbers computed from local SQLite as pilot evidence.

---

### Task 1: Merge the instrument branch (Phase 0)

**Files:**
- Modify: none (pure git merge)

**Interfaces:**
- Produces: `validation/calibration_gate.py` (gates G1–G6, `GateResult`), `scripts/derive_measured_weights.py` (`structurally_excluded_codes()`, `zero_variance_feature_indices()`, `compute_tier_weights_from_matrices`), `validation/public_authors/` (manifest + `run.py` with `calibrated_attribution()`), `validation/benchmark/reproducibility.py` (`lock_environment()`), `original/quantum/typicality.py` (`NO_ACTION_FAR_THRESHOLD = 0.03`, conformal `p_far`/`p_central`) — everything later tasks import.

- [ ] **Step 1: Check the dependency branch is quiescent**

```bash
git fetch origin 2>/dev/null; git log --oneline -3 claude/plato-works-dating-analysis-b05b1a
```

If the tip has moved within the last ~30 minutes, another session may still be committing — pause and ask the user before merging.

- [ ] **Step 2: Merge**

```bash
git merge claude/plato-works-dating-analysis-b05b1a --no-edit
```

Expected: clean merge (`git merge-tree` showed zero textual conflicts at planning time; overlap is only `original/quantum/scoring.py` and `original/store.py`). If conflicts appear (new commits since planning), resolve keeping BOTH the genre-prior changes (this branch) and the typicality wiring (theirs) — they touch different functions.

- [ ] **Step 3: Full suite — semantic-conflict check**

Run: `/Users/andrew/Desktop/Original/.venv/bin/python -m pytest tests/ -q`
Expected: `0 failed`. Pay attention to `tests/quantum/` (scoring.py hosts both branches' features) and `tests/test_calibration_gate.py` (newly arrived).

- [ ] **Step 4: Commit is the merge commit** — nothing further; verify `git status` is clean.

---

### Task 2: Measurability registry

**Files:**
- Create: `validation/measurability.py`
- Test: `tests/test_measurability.py`

**Interfaces:**
- Consumes: `original.constants` — `ALL_FEATURE_CODES`, `COMPARISON_CODES`, `MUSICAL_COMPARISON_CODES`, `DISABLED_FEATURE_GROUPS`, `FEATURE_GROUPS`, `TIER16_CODES`.
- Produces (used by Tasks 3, 4, 9, 11):
  - `MeasurabilityStatus` (str Enum: `MEASURABLE`, `SCORING_ONLY`, `STRUCTURALLY_BLANK`, `DISABLED`, `CORPUS_LIMITED`)
  - `status(code: str, corpus: str | None = None) -> MeasurabilityStatus`
  - `measurable_codes(corpus: str | None = None) -> list[str]`
  - `measurable_indices(corpus: str | None = None) -> list[int]`
  - `disabled_feature_indices() -> list[int]`
  - `structurally_excluded_codes() -> set[str]`
  - `assert_aggregatable(codes: Sequence[str], corpus: str | None = None) -> None` (raises `MeasurabilityError`)

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_measurability.py
"""
tests/test_measurability.py — the measurability registry is the single
source of truth for which feature columns can carry corpus-sweep evidence.
"""
from __future__ import annotations

import pytest

from original.constants import (
    ALL_FEATURE_CODES,
    COMPARISON_CODES,
    MUSICAL_COMPARISON_CODES,
    TIER1_CODES,
    TIER16_CODES,
    TIER17_CODES,
    TIER18_CODES,
)
from validation.measurability import (
    MeasurabilityError,
    MeasurabilityStatus,
    assert_aggregatable,
    disabled_feature_indices,
    measurable_codes,
    measurable_indices,
    status,
    structurally_excluded_codes,
)


class TestStatus:
    def test_every_feature_code_has_a_status(self):
        for code in ALL_FEATURE_CODES:
            assert isinstance(status(code), MeasurabilityStatus)

    def test_unknown_code_raises(self):
        with pytest.raises(KeyError):
            status("not_a_feature")

    def test_comparison_codes_are_scoring_only(self):
        for code in list(COMPARISON_CODES) + list(MUSICAL_COMPARISON_CODES):
            assert status(code) is MeasurabilityStatus.SCORING_ONLY

    def test_catastrophe_index_is_structurally_blank(self):
        assert status("catastrophe_index") is MeasurabilityStatus.STRUCTURALLY_BLANK

    def test_disabled_groups_tracked_live_from_constants(self):
        # tier 17 (behavioral) and tier 18 (uniformity) are in
        # DISABLED_FEATURE_GROUPS today; DISABLED must outrank every
        # other status for those codes.
        for code in TIER17_CODES + TIER18_CODES:
            assert status(code) is MeasurabilityStatus.DISABLED

    def test_tier16_corpus_limited_on_non_academic_corpora(self):
        for code in TIER16_CODES:
            assert status(code, corpus="plato") is MeasurabilityStatus.CORPUS_LIMITED
            assert status(code, corpus="public_authors") is MeasurabilityStatus.CORPUS_LIMITED
            # seminary essays DO contain citation behavior
            assert status(code, corpus="seminary") is MeasurabilityStatus.MEASURABLE
            assert status(code) is MeasurabilityStatus.MEASURABLE

    def test_surface_stylometrics_measurable(self):
        for code in TIER1_CODES:
            assert status(code) is MeasurabilityStatus.MEASURABLE


class TestDerivedSets:
    def test_measurable_codes_excludes_all_non_measurable(self):
        codes = set(measurable_codes())
        assert codes.isdisjoint(structurally_excluded_codes())

    def test_measurable_indices_parallel_to_all_feature_codes(self):
        idx = measurable_indices()
        assert [ALL_FEATURE_CODES[i] for i in idx] == measurable_codes()

    def test_corpus_argument_shrinks_the_measurable_set(self):
        assert set(measurable_codes("plato")) == set(measurable_codes()) - set(TIER16_CODES)

    def test_disabled_indices_cover_tier17_and_18(self):
        codes = {ALL_FEATURE_CODES[i] for i in disabled_feature_indices()}
        assert codes == set(TIER17_CODES) | set(TIER18_CODES)


class TestAssertAggregatable:
    def test_accepts_measurable(self):
        assert_aggregatable(TIER1_CODES)  # no raise

    def test_refuses_scoring_only_and_names_offenders(self):
        with pytest.raises(MeasurabilityError) as exc:
            assert_aggregatable(TIER1_CODES + list(COMPARISON_CODES))
        for code in COMPARISON_CODES:
            assert code in str(exc.value)
        assert "scoring_only" in str(exc.value)

    def test_refuses_corpus_limited_on_named_corpus(self):
        with pytest.raises(MeasurabilityError):
            assert_aggregatable(TIER16_CODES, corpus="plato")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `/Users/andrew/Desktop/Original/.venv/bin/python -m pytest tests/test_measurability.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'validation.measurability'`

- [ ] **Step 3: Implement the registry**

```python
# validation/measurability.py
"""
validation/measurability.py — single source of truth for which feature
columns can, in principle, carry evidence in a corpus sweep.

The 2026-07-30 Instrument Report's root failure mode: structurally-blank
columns (comparison-shaped features hardwired to 0.5 outside scoring,
disabled groups, fallback constants) were read as "measured zero" by the
first weight derivation and would have driven wrong re-weighting. This
module makes that class of error structural to prevent: aggregation code
calls assert_aggregatable() and REFUSES non-measurable columns instead of
silently averaging them.

Statuses:
  MEASURABLE          varies in a corpus sweep; eligible for aggregation
  SCORING_ONLY        comparison-shaped; computed only against a baseline at
                      scoring time; extract_features() hardwires 0.5
                      (COMPARISON_CODES + MUSICAL_COMPARISON_CODES —
                      original/features/pipeline.py)
  STRUCTURALLY_BLANK  constant via a fallback path regardless of corpus
                      (tier 12's catastrophe_index)
  DISABLED            group is in DISABLED_FEATURE_GROUPS (live view — if a
                      group is enabled later this module tracks it with no
                      code change)
  CORPUS_LIMITED      measurable in principle but known-blank on named
                      corpora (tier 16 citation fingerprint on Plato /
                      Gutenberg literary prose, which has no academic
                      citation behavior)

Precedence (highest first): DISABLED > SCORING_ONLY > STRUCTURALLY_BLANK
> CORPUS_LIMITED > MEASURABLE. A disabled group is blank no matter what
else is true of its codes.
"""
from __future__ import annotations

from enum import Enum
from typing import Sequence

from original.constants import (
    ALL_FEATURE_CODES,
    COMPARISON_CODES,
    DISABLED_FEATURE_GROUPS,
    FEATURE_GROUPS,
    MUSICAL_COMPARISON_CODES,
    TIER16_CODES,
)


class MeasurabilityStatus(str, Enum):
    MEASURABLE = "measurable"
    SCORING_ONLY = "scoring_only"
    STRUCTURALLY_BLANK = "structurally_blank"
    DISABLED = "disabled"
    CORPUS_LIMITED = "corpus_limited"


class MeasurabilityError(ValueError):
    """Raised when aggregation is attempted over non-measurable columns."""


_ALL_CODES = set(ALL_FEATURE_CODES)
_SCORING_ONLY = set(COMPARISON_CODES) | set(MUSICAL_COMPARISON_CODES)
_STRUCTURALLY_BLANK = {"catastrophe_index"}
# Corpora with essentially no academic citation behavior — tier 16 measured
# "near zero" there is a corpus artifact, not a finding (Instrument Report,
# Ledger A, T16 row).
_CORPUS_LIMITED: dict[str, frozenset[str]] = {
    code: frozenset({"plato", "public_authors"}) for code in TIER16_CODES
}


def _disabled_codes() -> set[str]:
    # Read live so behavior tracks runtime state (same convention as
    # scripts/derive_measured_weights.structurally_excluded_codes).
    out: set[str] = set()
    for group in DISABLED_FEATURE_GROUPS:
        out.update(FEATURE_GROUPS.get(group, []))
    return out


def status(code: str, corpus: str | None = None) -> MeasurabilityStatus:
    if code not in _ALL_CODES:
        raise KeyError(f"unknown feature code: {code!r}")
    if code in _disabled_codes():
        return MeasurabilityStatus.DISABLED
    if code in _SCORING_ONLY:
        return MeasurabilityStatus.SCORING_ONLY
    if code in _STRUCTURALLY_BLANK:
        return MeasurabilityStatus.STRUCTURALLY_BLANK
    if corpus is not None and corpus in _CORPUS_LIMITED.get(code, frozenset()):
        return MeasurabilityStatus.CORPUS_LIMITED
    return MeasurabilityStatus.MEASURABLE


def measurable_codes(corpus: str | None = None) -> list[str]:
    return [
        c for c in ALL_FEATURE_CODES if status(c, corpus) is MeasurabilityStatus.MEASURABLE
    ]


def measurable_indices(corpus: str | None = None) -> list[int]:
    return [
        i
        for i, c in enumerate(ALL_FEATURE_CODES)
        if status(c, corpus) is MeasurabilityStatus.MEASURABLE
    ]


def disabled_feature_indices() -> list[int]:
    disabled = _disabled_codes()
    return [i for i, c in enumerate(ALL_FEATURE_CODES) if c in disabled]


def structurally_excluded_codes() -> set[str]:
    """
    Codes that can never carry corpus-sweep signal regardless of corpus:
    disabled + scoring-only + structurally blank. (CORPUS_LIMITED codes are
    NOT here — they are measurable on the right corpus.)
    """
    return _disabled_codes() | _SCORING_ONLY | set(_STRUCTURALLY_BLANK)


def assert_aggregatable(codes: Sequence[str], corpus: str | None = None) -> None:
    offending = [
        (c, status(c, corpus).value)
        for c in codes
        if status(c, corpus) is not MeasurabilityStatus.MEASURABLE
    ]
    if offending:
        raise MeasurabilityError(
            "refusing to aggregate over non-measurable columns "
            f"(corpus={corpus!r}): {offending}"
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `/Users/andrew/Desktop/Original/.venv/bin/python -m pytest tests/test_measurability.py -q`
Expected: all PASS.

- [ ] **Step 5: Full suite, then commit**

```bash
/Users/andrew/Desktop/Original/.venv/bin/python -m pytest tests/ -q
git add validation/measurability.py tests/test_measurability.py
git commit -m "Add validation/measurability.py — feature measurability registry

Single source of truth for measurable / scoring-only / structurally-blank
/ disabled / corpus-limited feature columns, with assert_aggregatable()
refusing to aggregate over anything non-measurable.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 3: Empirical self-consistency canary

**Files:**
- Modify: `tests/test_measurability.py` (append a class)

**Interfaces:**
- Consumes: `validation.stability.stability.compute_feature_matrix(author_texts: Dict[str, str], length: int, *, max_windows=None) -> Dict[str, np.ndarray]`; registry from Task 2.

The registry must not be able to drift from pipeline reality — "blank read as
zero" happened precisely because the declared and actual behavior diverged.
This test extracts real features over a tiny two-author fixture and checks
the declared statuses against observed variance. Runtime ≈ 3–4 s (4
`feature_vector` calls at ~650 ms) — acceptable in the ~70 s fast suite.

- [ ] **Step 1: Append the failing test**

```python
# append to tests/test_measurability.py
import numpy as np

from original.constants import ALL_FEATURE_CODES as _CODES


def _fixture_author_texts() -> dict[str, str]:
    """
    Two deliberately style-distinct ~500-word texts (2 windows each at
    length=250). Constant columns are judged on POOLED variance across all
    4 windows, so cross-author style differences are what matters.
    """
    plain = (
        "The dog ran home. It was late. The boy called out. He heard nothing. "
        "The road was dark and wet. He walked on. A light shone ahead. "
        "It was the farm. He knew the gate. The latch was old. It stuck fast. "
        "He pushed hard. The gate swung wide. The yard was still. "
    )
    ornate = (
        "Whosoever contemplates the manifold operations of providence — "
        "observing, as it were, the intricate concatenation of causes and "
        "consequences that governs our mortal estate — must thereby confess, "
        "with no inconsiderable astonishment, that the arrangement of human "
        "affairs surpasses our poor understanding; for what philosopher, "
        "however sagacious, has ever circumscribed the boundless? "
    )
    return {"plain": plain * 12, "ornate": ornate * 9}


class TestRegistryMatchesPipelineReality:
    """The declared statuses must agree with what extraction actually does."""

    @classmethod
    def setup_class(cls):
        from validation.stability.stability import compute_feature_matrix

        matrices = compute_feature_matrix(_fixture_author_texts(), length=250)
        cls.pooled = np.vstack([m for m in matrices.values() if m.shape[0] > 0])

    def test_every_structurally_excluded_code_is_constant_in_extraction(self):
        variances = self.pooled.var(axis=0)
        broken = [
            code
            for i, code in enumerate(_CODES)
            if code in structurally_excluded_codes() and variances[i] > 1e-12
        ]
        # If this fires, a declared-blank feature started varying — the
        # registry is stale and MUST be updated (good news, not noise).
        assert broken == [], f"declared-blank features now vary: {broken}"

    def test_surface_stylometrics_actually_vary(self):
        variances = self.pooled.var(axis=0)
        constant_t1 = [
            code
            for i, code in enumerate(_CODES)
            if code in TIER1_CODES and variances[i] <= 1e-12
        ]
        assert constant_t1 == [], f"tier-1 features constant on distinct styles: {constant_t1}"

    def test_most_measurable_features_vary_on_distinct_styles(self):
        variances = self.pooled.var(axis=0)
        measurable = set(measurable_codes())
        varying = sum(
            1
            for i, code in enumerate(_CODES)
            if code in measurable and variances[i] > 1e-12
        )
        # Not all measurable codes fire on a 500-word citation-free fixture
        # (e.g. chiasmus, block quotes) — 60% is the canary floor, not a claim.
        assert varying >= 0.6 * len(measurable)
```

- [ ] **Step 2: Run to verify current behavior**

Run: `/Users/andrew/Desktop/Original/.venv/bin/python -m pytest tests/test_measurability.py::TestRegistryMatchesPipelineReality -q`
Expected: PASS if the registry matches reality (it should, per the Instrument Report's empirical sweep). If `test_every_structurally_excluded_code_is_constant_in_extraction` fails, the registry declaration in Task 2 is wrong — fix the declaration, don't weaken the test. If `test_most_measurable_features_vary...` fails, enrich the fixture texts (more sentences, more punctuation variety), don't lower 0.6.

- [ ] **Step 3: Commit**

```bash
git add tests/test_measurability.py
git commit -m "Add registry-vs-pipeline self-consistency canary for measurability

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 4: Refactor existing consumers onto the registry

**Files:**
- Modify: `scripts/derive_measured_weights.py` (`structurally_excluded_codes()` delegates; `compute_tier_weights_from_matrices` guards)
- Modify: `validation/stability/stability.py` (`_FEATURE_INDICES_SKIPPED` delegates)
- Test: extend `tests/test_measurability.py`

**Interfaces:**
- Consumes: Task 2's `structurally_excluded_codes()`, `disabled_feature_indices()`, `assert_aggregatable()`.
- Produces: unchanged public signatures — `scripts.derive_measured_weights.structurally_excluded_codes() -> set[str]` now returns the registry's (strictly larger) a-priori set.

- [ ] **Step 1: Write the failing delegation tests**

```python
# append to tests/test_measurability.py
class TestConsumersDelegateToRegistry:
    def test_derive_weights_exclusions_come_from_registry(self):
        from scripts.derive_measured_weights import (
            structurally_excluded_codes as script_excluded,
        )

        assert script_excluded() == structurally_excluded_codes()

    def test_stability_skips_exactly_the_disabled_indices(self):
        from validation.stability.stability import _FEATURE_INDICES_SKIPPED

        assert sorted(_FEATURE_INDICES_SKIPPED) == disabled_feature_indices()
```

- [ ] **Step 2: Run to verify failure**

Run: `/Users/andrew/Desktop/Original/.venv/bin/python -m pytest tests/test_measurability.py::TestConsumersDelegateToRegistry -q`
Expected: FAIL — the script's set lacks `MUSICAL_COMPARISON_CODES` + `catastrophe_index` (it caught those only empirically via `zero_variance_feature_indices`), and stability skips only tier 17.

- [ ] **Step 3: Delegate in `derive_measured_weights.py`**

Replace the body of `structurally_excluded_codes()` (keep the name and docstring intent; note the delegation):

```python
def structurally_excluded_codes() -> set[str]:
    """
    Feature codes that can never carry a Fisher signal through this
    pipeline. Delegates to validation.measurability — the single source of
    truth (this function previously listed COMPARISON_CODES + disabled
    groups itself and relied on zero_variance_feature_indices to catch the
    rest empirically; the registry names all of them a-priori).
    """
    from validation.measurability import structurally_excluded_codes as _registry

    return _registry()
```

In `compute_tier_weights_from_matrices`, immediately before the tier
aggregation over surviving codes, add the structural guard (find the point
where the surviving/measured code list is final — after structural + zero-
variance exclusion):

```python
    from validation.measurability import assert_aggregatable

    # Structural guard: aggregation over a non-measurable column is the
    # Instrument Report's root failure mode — refuse loudly, never average.
    assert_aggregatable(surviving_codes)
```

(`surviving_codes` = whatever local name holds the post-exclusion code list;
read the function and use its actual variable.)

- [ ] **Step 4: Delegate in `stability.py`**

Replace the `_FEATURE_INDICES_MEASURED` / `_FEATURE_INDICES_SKIPPED` definitions
(exact names as of `stability.py:51,54`; `_FEATURE_INDICES_MEASURED` is consumed
at `stability.py:189`, `_FEATURE_INDICES_SKIPPED` at `:194,196,207` — keep both
names or those call sites break):

```python
from validation.measurability import disabled_feature_indices

_FEATURE_INDICES_SKIPPED: List[int] = disabled_feature_indices()
_FEATURE_INDICES_MEASURED: List[int] = [
    i for i in range(len(ALL_FEATURE_CODES)) if i not in set(_FEATURE_INDICES_SKIPPED)
]
```

The module-level `KEYSTROKE_TIER = 17` constant becomes unused by these two
definitions — leave it if anything else references it, delete it if not
(`grep -n KEYSTROKE_TIER validation/stability/stability.py`).

**Behavior change, deliberate:** stability previously skipped only tier 17
(`KEYSTROKE_TIER`); the registry also skips tier 18 (uniformity), which is
in `DISABLED_FEATURE_GROUPS` and therefore constant in extraction — its
rows were degenerate anyway. Update the `notes.append(...)` string in
`per_feature_stability` from "tier-17 (keystroke) features" to name the
disabled groups generically:

```python
        notes.append(
            f"{len(_FEATURE_INDICES_SKIPPED)} features in disabled groups "
            f"({sorted(DISABLED_FEATURE_GROUPS)}) were excluded — text-only "
            f"input gives them constant placeholders, so F is undefined."
        )
```

(Import `DISABLED_FEATURE_GROUPS` from `original.constants` if not already.)

- [ ] **Step 5: Run tests + full suite**

Run: `/Users/andrew/Desktop/Original/.venv/bin/python -m pytest tests/test_measurability.py tests/ -q`
Expected: `0 failed`. If any stability test pinned the old tier-17-only skip
list, update it to the registry expectation (that's the point of the change).

- [ ] **Step 6: Commit**

```bash
git add scripts/derive_measured_weights.py validation/stability/stability.py tests/test_measurability.py
git commit -m "Refactor weight-derivation and stability exclusions onto the measurability registry

structurally_excluded_codes() and _FEATURE_INDICES_SKIPPED now delegate to
validation/measurability; tier aggregation guards with assert_aggregatable.
Stability now also skips disabled tier-18 rows (previously tier-17 only).

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 5: Statistical power module

**Files:**
- Create: `validation/power.py`
- Test: `tests/test_power.py`

**Interfaces:**
- Produces (used by Tasks 6, 8, 11, 13):
  - `conformal_p_floor(n: int) -> float`
  - `band_reachable(n: int, threshold: float) -> bool`
  - `min_docs_for_band(threshold: float) -> int`
  - `rule_of_three_upper(n: int) -> float`
  - `wilson_interval(successes: int, n: int, z: float = 1.96) -> tuple[float, float]`
  - `bar_decidable(successes: int, n: int, bar: float) -> str` — `"above"` /
    `"below"` / `"undecided"`

**Why `wilson_interval` is here:** G1's defect (a criterion unreachable at
current N) has a sampling-uncertainty twin that the first draft of this plan
missed. G3 compares top-1 accuracy against a 0.7 bar on **22** held-out
essays. Measured with this module: the observed 0.455 has a 95% Wilson CI of
[0.269, 0.653] — genuinely below the bar, so **that failure is real**. But
the 0.818 diagnostic's CI is [0.615, 0.927], straddling 0.7; even a
hypothetical 0.727 gives [0.518, 0.868]. **A G3 pass cannot be evidence at
N=22** — it would take ~306 held-out essays for a 0.75 point estimate to sit
entirely above the bar. Same failure class as G1, different mechanism.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_power.py
"""
tests/test_power.py — statistical floors/ceilings for gate informativeness.
The Instrument Report's G1 finding in numbers: with 12 baseline docs the
smallest reachable conformal p is 1/13 ≈ 0.077, while the no-action band
needs <= 0.03 — the gate cannot flag, so 0.0% flagged proves nothing.
"""
from __future__ import annotations

import pytest

from validation.power import (
    band_reachable,
    bar_decidable,
    conformal_p_floor,
    min_docs_for_band,
    rule_of_three_upper,
    wilson_interval,
)


class TestConformalFloor:
    def test_twelve_docs_floor_matches_instrument_report(self):
        assert conformal_p_floor(12) == pytest.approx(1 / 13)

    def test_floor_decreases_with_n(self):
        assert conformal_p_floor(200) < conformal_p_floor(12)

    def test_nonpositive_n_raises(self):
        with pytest.raises(ValueError):
            conformal_p_floor(0)


class TestBandReachable:
    def test_unreachable_at_pilot_scale(self):
        assert band_reachable(12, 0.03) is False

    def test_reachable_at_scale(self):
        assert band_reachable(199, 0.005) is True
        assert band_reachable(33, 0.03) is True

    def test_boundary_is_inclusive(self):
        # floor(33) = 1/34 ≈ 0.0294 <= 0.03 → reachable; floor(32) = 1/33 ≈ 0.0303 → not
        assert band_reachable(33, 0.03) is True
        assert band_reachable(32, 0.03) is False


class TestMinDocsForBand:
    def test_escalation_band_needs_199(self):
        # Instrument Report: "Escalation needs roughly 199 samples"
        # (SCHEDULE_FAR_THRESHOLD = 0.005 → ceil(1/0.005) - 1 = 199)
        assert min_docs_for_band(0.005) == 199

    def test_no_action_band_needs_33(self):
        assert min_docs_for_band(0.03) == 33

    def test_returned_n_is_minimal(self):
        for t in (0.005, 0.02, 0.03, 0.05):
            n = min_docs_for_band(t)
            assert band_reachable(n, t) and not band_reachable(n - 1, t)


class TestRuleOfThree:
    def test_216_samples_bounds_fpr_at_1_4_percent(self):
        # G1's 0/216 flagged: cannot demonstrate FPR below ~1.4%
        assert rule_of_three_upper(216) == pytest.approx(3 / 216)

    def test_nonpositive_n_raises(self):
        with pytest.raises(ValueError):
            rule_of_three_upper(0)


class TestWilsonInterval:
    def test_matches_known_values_for_g3(self):
        lo, hi = wilson_interval(10, 22)  # the measured 0.455
        assert lo == pytest.approx(0.269, abs=0.002)
        assert hi == pytest.approx(0.653, abs=0.002)

    def test_interval_contains_the_point_estimate(self):
        for k, n in [(0, 10), (5, 10), (10, 10), (18, 22)]:
            lo, hi = wilson_interval(k, n)
            assert lo <= k / n <= hi

    def test_interval_narrows_as_n_grows(self):
        narrow = wilson_interval(150, 200)
        wide = wilson_interval(15, 20)
        assert (narrow[1] - narrow[0]) < (wide[1] - wide[0])

    def test_bounds_stay_within_zero_one(self):
        for k, n in [(0, 5), (5, 5)]:
            lo, hi = wilson_interval(k, n)
            assert 0.0 <= lo <= hi <= 1.0

    def test_rejects_impossible_counts(self):
        with pytest.raises(ValueError):
            wilson_interval(11, 10)
        with pytest.raises(ValueError):
            wilson_interval(-1, 10)


class TestBarDecidable:
    def test_g3_observed_failure_is_genuinely_below(self):
        # 10/22 = 0.455, CI upper 0.653 < 0.7 — a real finding
        assert bar_decidable(10, 22, bar=0.7) == "below"

    def test_g3_diagnostic_is_undecided_at_n22(self):
        # 18/22 = 0.818, CI [0.615, 0.927] straddles 0.7 — cannot prove a pass
        assert bar_decidable(18, 22, bar=0.7) == "undecided"

    def test_barely_over_the_bar_is_undecided(self):
        assert bar_decidable(16, 22, bar=0.7) == "undecided"

    def test_large_n_can_decide_above(self):
        assert bar_decidable(230, 306, bar=0.7) == "above"
```

- [ ] **Step 2: Run to verify failure**

Run: `/Users/andrew/Desktop/Original/.venv/bin/python -m pytest tests/test_power.py -q`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement**

```python
# validation/power.py
"""
validation/power.py — statistical floors and ceilings for gate verdicts.

Every reported validation number is a statistical quantity with a known
floor/ceiling given N. A gate that "passes" because its criterion is
arithmetically unreachable at the current corpus size is UNINFORMATIVE,
not passing — these helpers let gate code tell the difference and print
the limitation instead of the flattering number.

Conformal p-values (original/quantum/typicality.py) are ranks over N
leave-one-out distances: p ∈ {1/(N+1), ..., 1}. Nothing can produce a
p below 1/(N+1), so an action band at threshold t is reachable only when
1/(N+1) <= t.
"""
from __future__ import annotations

import math


def conformal_p_floor(n: int) -> float:
    """Smallest conformal p-value reachable with n calibration samples."""
    if n <= 0:
        raise ValueError(f"n must be positive, got {n}")
    return 1.0 / (n + 1)


def band_reachable(n: int, threshold: float) -> bool:
    """Can a conformal p-value computed from n samples ever be <= threshold?"""
    return conformal_p_floor(n) <= threshold


def min_docs_for_band(threshold: float) -> int:
    """Smallest n for which band_reachable(n, threshold) holds."""
    if threshold <= 0:
        raise ValueError(f"threshold must be positive, got {threshold}")
    return math.ceil(1.0 / threshold) - 1


def rule_of_three_upper(n: int) -> float:
    """
    95% upper confidence bound on a true rate when 0 events were observed
    in n trials (the rule of three). An observed 0/n flagged rate can never
    demonstrate an FPR below this.
    """
    if n <= 0:
        raise ValueError(f"n must be positive, got {n}")
    return 3.0 / n


def wilson_interval(successes: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """
    Wilson score interval for a binomial proportion (default 95%).

    Preferred over the normal approximation because it stays inside [0, 1]
    and behaves at the extremes — both of which matter at the corpus sizes
    this project actually has (n = 22 held-out essays for G3).

    The closed form is analytically within [0, 1] but not numerically: at
    successes=0 the lower bound evaluates to ≈ -3.1e-17 (verified), so the
    result is clamped. Without the clamp a caller checking `lo >= 0` — or
    formatting the bound for a report — sees a negative probability.
    """
    if n <= 0:
        raise ValueError(f"n must be positive, got {n}")
    if not 0 <= successes <= n:
        raise ValueError(f"successes must be in [0, {n}], got {successes}")
    p = successes / n
    denom = 1 + z * z / n
    center = p + z * z / (2 * n)
    margin = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    lo = max(0.0, (center - margin) / denom)
    hi = min(1.0, (center + margin) / denom)
    return (lo, hi)


def bar_decidable(successes: int, n: int, bar: float, z: float = 1.96) -> str:
    """
    Can this many trials decide whether the true rate clears `bar`?

    Returns "above" (whole CI above the bar), "below" (whole CI below), or
    "undecided" (CI straddles it — the observation is compatible with both
    sides, so neither a pass nor a fail is evidence).

    This is the sampling-uncertainty analogue of band_reachable(): G1 cannot
    flag because of an arithmetic floor; G3 cannot demonstrate a pass at
    n=22 because the interval is wider than the distance to the bar.
    """
    lo, hi = wilson_interval(successes, n, z)
    if lo > bar:
        return "above"
    if hi < bar:
        return "below"
    return "undecided"
```

- [ ] **Step 4: Run tests, then full suite**

Run: `/Users/andrew/Desktop/Original/.venv/bin/python -m pytest tests/test_power.py tests/ -q`
Expected: `0 failed`.

- [ ] **Step 5: Commit**

```bash
git add validation/power.py tests/test_power.py
git commit -m "Add validation/power.py — conformal floors and rule-of-three bounds

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 6: Three-valued gate verdicts + uninformative G1 and G3

**Files:**
- Modify: `validation/calibration_gate.py` (`GateResult`, `evaluate_g1_fpr`, `evaluate_g3_attribution`, `render`, `main`, the G1/G3 legs of `run_all`; audit insufficient-data constructors)
- Test: extend `tests/test_calibration_gate.py`

**Interfaces:**
- Consumes: Task 5's power functions; `original.quantum.typicality.NO_ACTION_FAR_THRESHOLD`.
- Produces (used by Tasks 12, 13):
  - `GateResult.verdict: str` — `"pass" | "fail" | "uninformative"`; defaults from `passed` when not given, so every existing constructor keeps working.
  - `evaluate_g1_fpr(pooled_actions, per_corpus, entity_baseline_counts: dict[str, int] | None = None, band_threshold: float | None = None) -> GateResult`
  - `evaluate_g3_attribution(top1_accuracy, top1_accuracy_raw_argmin=None, n_essays: int | None = None) -> GateResult`
  - `main` gains `--strict` (uninformative counts as failure for the exit code).

**⚠ Re-verify first:** this file is under active development on the plato
branch. Before editing, re-read `GateResult`, `evaluate_g1_fpr`, `render`,
`main`, and any `_*_insufficient_data_result` / "cannot fail" helpers as
they exist post-merge. Anchor every edit on symbols.

- [ ] **Step 1: Write the failing tests**

```python
# append to tests/test_calibration_gate.py
from validation.power import conformal_p_floor


class TestGateVerdicts:
    def test_verdict_defaults_from_passed(self):
        r = GateResult(name="X", passed=True, criterion="c", current_value="v")
        assert r.verdict == "pass"
        r = GateResult(name="X", passed=False, criterion="c", current_value="v")
        assert r.verdict == "fail"

    def test_explicit_uninformative_verdict_sticks(self):
        r = GateResult(
            name="X", passed=False, criterion="c", current_value="v",
            verdict="uninformative",
        )
        assert r.verdict == "uninformative"
        assert r.passed is False


class TestG1Informativeness:
    def test_unreachable_band_turns_clean_pass_into_uninformative(self):
        actions = ["no_action"] * 216
        result = evaluate_g1_fpr(
            actions,
            per_corpus={"seminary": actions},
            entity_baseline_counts={"s1": 12, "s2": 8},
            band_threshold=0.03,
        )
        assert result.verdict == "uninformative"
        assert result.passed is False
        power = result.detail["power"]
        assert power["min_conformal_p_at_max_n"] == conformal_p_floor(12)
        assert power["entities_reachable"] == 0
        assert power["rule_of_three_fpr_upper"] == 3 / 216

    def test_reachable_entities_keep_a_clean_pass_informative(self):
        actions = ["no_action"] * 216
        result = evaluate_g1_fpr(
            actions,
            per_corpus={"seminary": actions},
            entity_baseline_counts={"s1": 40},
            band_threshold=0.03,
        )
        assert result.verdict == "pass"

    def test_a_real_failure_is_never_downgraded_to_uninformative(self):
        actions = ["monitor"] * 30 + ["no_action"] * 70
        result = evaluate_g1_fpr(
            actions,
            per_corpus={"seminary": actions},
            entity_baseline_counts={"s1": 12},
        )
        assert result.verdict == "fail"

    def test_omitting_counts_preserves_legacy_behavior(self):
        actions = ["no_action"] * 95 + ["monitor"] * 5
        result = evaluate_g1_fpr(actions, per_corpus={"synthetic": actions})
        assert result.verdict == "pass"
        assert result.passed is True


class TestG3Informativeness:
    """
    G1's arithmetic floor has a sampling-uncertainty twin. At n=22 held-out
    essays a G3 FAIL is real (CI upper 0.653 < 0.7) but a G3 PASS is not
    evidence (0.818 → CI [0.615, 0.927], straddling the bar).
    """

    def test_measured_failure_stays_a_real_failure(self):
        result = evaluate_g3_attribution(0.455, n_essays=22)
        assert result.verdict == "fail"
        assert result.detail["power"]["bar_decidable"] == "below"

    def test_pass_above_the_bar_is_uninformative_at_n22(self):
        result = evaluate_g3_attribution(18 / 22, n_essays=22)
        assert result.verdict == "uninformative"
        assert result.passed is False
        ci = result.detail["power"]["wilson_ci"]
        assert ci[0] < 0.7 < ci[1]

    def test_pass_is_informative_when_n_supports_it(self):
        result = evaluate_g3_attribution(230 / 306, n_essays=306)
        assert result.verdict == "pass"

    def test_omitting_n_preserves_legacy_behavior(self):
        assert evaluate_g3_attribution(0.9).verdict == "pass"
        assert evaluate_g3_attribution(0.455).verdict == "fail"
```

- [ ] **Step 2: Run to verify failure**

Run: `/Users/andrew/Desktop/Original/.venv/bin/python -m pytest tests/test_calibration_gate.py -q`
Expected: new tests FAIL (`verdict` unknown / unexpected kwargs). Existing tests must still pass.

- [ ] **Step 3: Implement `GateResult.verdict`**

```python
@dataclass(frozen=True)
class GateResult:
    name: str
    passed: bool
    criterion: str
    current_value: str
    detail: dict = field(default_factory=dict)
    verdict: str = ""  # "pass" | "fail" | "uninformative"

    def __post_init__(self):
        if not self.verdict:
            object.__setattr__(self, "verdict", "pass" if self.passed else "fail")
        if self.verdict not in ("pass", "fail", "uninformative"):
            raise ValueError(f"invalid verdict: {self.verdict!r}")
        if self.verdict == "uninformative" and self.passed:
            raise ValueError("an uninformative gate cannot claim passed=True")
```

- [ ] **Step 4: Implement informativeness in `evaluate_g1_fpr`**

Extend the existing function — keep the current rate computation and
per-corpus breakdown untouched, add the optional kwargs and power block:

```python
def evaluate_g1_fpr(
    pooled_actions: list[str],
    per_corpus: dict[str, list[str]],
    entity_baseline_counts: dict[str, int] | None = None,
    band_threshold: float | None = None,
) -> GateResult:
    # ... existing n / flagged / pooled_rate / per_corpus_rate computation ...

    verdict = "pass" if pooled_rate <= 0.05 else "fail"
    detail = {
        "n": n,
        "flagged": flagged,
        "pooled_flagged_rate": pooled_rate,
        "per_corpus_flagged_rate": per_corpus_rate,
    }

    if entity_baseline_counts:
        from validation.power import (
            band_reachable,
            conformal_p_floor,
            min_docs_for_band,
            rule_of_three_upper,
        )

        if band_threshold is None:
            from original.quantum.typicality import NO_ACTION_FAR_THRESHOLD

            band_threshold = NO_ACTION_FAR_THRESHOLD
        reachable = {
            e: band_reachable(cnt, band_threshold)
            for e, cnt in entity_baseline_counts.items()
        }
        max_n = max(entity_baseline_counts.values())
        detail["power"] = {
            "band_threshold": band_threshold,
            "max_entity_n": max_n,
            "min_conformal_p_at_max_n": conformal_p_floor(max_n),
            "entities_reachable": sum(reachable.values()),
            "entities_total": len(reachable),
            "min_docs_for_band": min_docs_for_band(band_threshold),
            "rule_of_three_fpr_upper": rule_of_three_upper(n) if flagged == 0 and n else None,
        }
        if verdict == "pass" and not any(reachable.values()):
            # The band is arithmetically unreachable for every entity: the
            # clean rate is arithmetic, not evidence (Instrument Report, G1).
            verdict = "uninformative"

    return GateResult(
        name="G1",
        passed=verdict == "pass",
        verdict=verdict,
        criterion="pooled flagged rate <= 5%",
        current_value=f"{pooled_rate:.1%}",
        detail=detail,
    )
```

- [ ] **Step 4b: Implement informativeness in `evaluate_g3_attribution`**

```python
def evaluate_g3_attribution(
    top1_accuracy: float,
    top1_accuracy_raw_argmin: float | None = None,
    n_essays: int | None = None,
) -> GateResult:
    # ... existing passed / detail construction ...
    verdict = "pass" if top1_accuracy >= 0.7 else "fail"

    if n_essays:
        from validation.power import bar_decidable, wilson_interval

        successes = round(top1_accuracy * n_essays)
        lo, hi = wilson_interval(successes, n_essays)
        decision = bar_decidable(successes, n_essays, bar=0.7)
        detail["power"] = {
            "n_essays": n_essays,
            "wilson_ci": [lo, hi],
            "bar": 0.7,
            "bar_decidable": decision,
        }
        if verdict == "pass" and decision != "above":
            # Point estimate clears the bar but the interval straddles it:
            # this corpus cannot demonstrate the claim (see Task 5 notes).
            verdict = "uninformative"

    return GateResult(
        name="G3",
        passed=verdict == "pass",
        verdict=verdict,
        criterion="public_authors top-1 accuracy >= 0.7 (impostor-calibrated attribution)",
        current_value=f"{top1_accuracy:.3f}",
        detail=detail,
    )
```

Thread `n_essays` at the existing `run_all` call site (anchor: the
`pa_summary = pa_report.get("summary", {})` block, ~line 810 at tip
`34d8ceb6`). `run()`'s summary must expose the held-out essay count — use
its existing count key if present, else add one:

```python
    results.append(
        evaluate_g3_attribution(
            top1_accuracy,
            top1_accuracy_raw_argmin=pa_summary.get("top1_accuracy_raw_argmin"),
            n_essays=pa_summary.get("n_scored_essays"),
        )
    )
```

Extend `render`'s uninformative branch to handle the G3 shape (it has
`wilson_ci`, not `max_entity_n`) — branch on which key is present:

```python
        if r.verdict == "uninformative" and power:
            if "wilson_ci" in power:
                lo, hi = power["wilson_ci"]
                lines.append(
                    f"        n={power['n_essays']} → 95% CI [{lo:.3f}, {hi:.3f}] "
                    f"straddles the {power['bar']} bar; this corpus cannot "
                    f"demonstrate a pass."
                )
            else:
                # ... the G1 conformal-floor line from Step 6 ...
```

- [ ] **Step 5: Thread entity counts through the G1 leg of `run_all`**

`run_all` builds the G1 corpora from `_load_seminary_texts()`,
`_load_public_authors_baseline_texts()`, `_load_plato_texts_by_dialogue()`
(each `dict[str, list[str]]`) before calling `_score_corpus_for_g1`. At the
point where those dicts are in scope, collect counts and pass them:

```python
    entity_baseline_counts = {
        sid: len(texts)
        for corpus_texts in (seminary_texts, public_texts, plato_texts)
        for sid, texts in corpus_texts.items()
    }
    # then, at the existing evaluate_g1_fpr call:
    results.append(
        evaluate_g1_fpr(
            pooled_actions,
            per_corpus,
            entity_baseline_counts=entity_baseline_counts,
        )
    )
```

(Adapt local names to the actual `run_all` body — anchor on the three
loader calls and the existing `evaluate_g1_fpr` call site.)

- [ ] **Step 6: Verdict-aware `render` and `--strict` in `main`**

In `render`, replace the pass/fail tag derivation with `r.verdict.upper()`
and append the power line for uninformative results:

```python
        tag = r.verdict.upper()
        lines.append(f"[{tag}] {r.name}: {r.criterion} — {r.current_value}")
        power = r.detail.get("power")
        if r.verdict == "uninformative" and power:
            lines.append(
                f"        max entity N={power['max_entity_n']} → min conformal "
                f"p={power['min_conformal_p_at_max_n']:.3f} > band "
                f"{power['band_threshold']}; needs N >= {power['min_docs_for_band']}. "
                f"Observed 0-rate bounds FPR only above "
                f"{power['rule_of_three_fpr_upper']:.1%} (rule of three)."
            )
```

In `main`, add `--strict` and change the exit-code rule from
`all(r.passed)` to verdict-based:

```python
    parser.add_argument(
        "--strict",
        action="store_true",
        help="treat uninformative gates as failures (use before quoting results)",
    )
    # ...
    failing = [r for r in results if r.verdict == "fail"]
    uninformative = [r for r in results if r.verdict == "uninformative"]
    if args.strict:
        failing = failing + uninformative
    return 1 if failing else 0
```

- [ ] **Step 7: Audit insufficient-data constructors**

Search the file for helpers that construct results for
insufficient/undecidable data (`_g6_insufficient_data_result`, the G6
both-rates-zero / reachability-guard paths from commit `34d8ceb6`, and any
`_machinery_error_result` — machinery errors stay `fail`, they are bugs).
Convert genuinely can't-know results to `verdict="uninformative"`,
`passed=False`. Update any tests pinning those to `passed` semantics.

- [ ] **Step 8: Run gate tests + full suite**

Run: `/Users/andrew/Desktop/Original/.venv/bin/python -m pytest tests/test_calibration_gate.py tests/ -q`
Expected: `0 failed`.

- [ ] **Step 9: Commit**

```bash
git add validation/calibration_gate.py tests/test_calibration_gate.py
git commit -m "Add three-valued gate verdicts: pass / fail / uninformative

G1 now computes conformal-band reachability per entity and reports a clean
0.0% at unreachable N as UNINFORMATIVE with the power math printed, instead
of a pass. main() gains --strict to fail on uninformative gates.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 7: Experiment spec embedded in every report

**Files:**
- Create: `validation/experiment.py`
- Modify: `validation/calibration_gate.py` (`main` embeds spec), `scripts/derive_measured_weights.py` (report embeds spec), `validation/public_authors/run.py` (summary embeds spec)
- Test: `tests/test_experiment.py`

**Interfaces:**
- Consumes: `validation.benchmark.reproducibility` (`BENCHMARK_SEED`, `_SCORING_FLAG_DEFAULTS`), Task 2's registry.
- Produces (used by Task 8's runners and any report reader):
  - `ExperimentSpec` frozen dataclass; `build_spec(task, corpora, windowing, aggregation, thresholds) -> ExperimentSpec`
  - `summarize_author_docs(author_docs: dict[str, list[str]], provenance: str) -> dict`
  - `spec_to_dict(spec) -> dict`; `diff_specs(a: dict, b: dict) -> list[str]` (raises `ValueError` on task mismatch)
  - `VALID_TASKS = {"verification", "attribution", "drift", "weight_derivation", "calibration_suite"}`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_experiment.py
"""
tests/test_experiment.py — every validation report must carry a
machine-readable record of what was measured. The mandatory task label is
the structural fix for "a verification number wore an attribution label".
"""
from __future__ import annotations

import pytest

from validation.experiment import (
    VALID_TASKS,
    build_spec,
    diff_specs,
    spec_to_dict,
    summarize_author_docs,
)


def _spec(task="verification", **over):
    kwargs = dict(
        task=task,
        corpora={"seminary": summarize_author_docs({"a": ["one two three"] * 3}, "student_pilot")},
        windowing={"length": 800, "overlap": 0.0},
        aggregation={"tier_rule": "median"},
        thresholds={"g1_flagged_rate": 0.05},
    )
    kwargs.update(over)
    return build_spec(**kwargs)


class TestBuildSpec:
    def test_rejects_unknown_task(self):
        with pytest.raises(ValueError):
            _spec(task="benchmarking")

    def test_valid_tasks_cover_the_design_set(self):
        assert VALID_TASKS == {
            "verification", "attribution", "drift",
            "weight_derivation", "calibration_suite",
        }

    def test_captures_git_sha_seed_and_env_lock(self):
        d = spec_to_dict(_spec())
        assert len(d["git_sha"]) == 40
        assert d["seed"] == 1729
        assert d["env_lock"]["ADAPTIVE_WEIGHTS_ENABLED"] == "0"

    def test_feature_statuses_summarized(self):
        d = spec_to_dict(_spec())
        counts = d["features"]["status_counts"]
        assert counts["measurable"] > 0
        assert sum(counts.values()) == d["features"]["total"]


class TestSummarize:
    def test_author_docs_summary(self):
        s = summarize_author_docs(
            {"a": ["w " * 400, "w " * 300], "b": ["w " * 500]}, "real_historical"
        )
        assert s["n_authors"] == 2
        assert s["n_documents"] == 3
        assert s["total_words"] == 1200
        assert s["provenance"] == "real_historical"


class TestDiff:
    def test_diff_lists_changed_fields(self):
        a = spec_to_dict(_spec())
        b = spec_to_dict(_spec(windowing={"length": 250, "overlap": 0.0}))
        changes = diff_specs(a, b)
        assert any("windowing.length: 800 != 250" in c for c in changes)

    def test_diff_refuses_cross_task_comparison(self):
        a = spec_to_dict(_spec(task="verification"))
        b = spec_to_dict(_spec(task="attribution"))
        with pytest.raises(ValueError, match="different tasks"):
            diff_specs(a, b)
```

- [ ] **Step 2: Run to verify failure**

Run: `/Users/andrew/Desktop/Original/.venv/bin/python -m pytest tests/test_experiment.py -q`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement**

```python
# validation/experiment.py
"""
validation/experiment.py — config-as-data for validation runs.

A number detached from what it measured is how "1.0 (passes)" migrated
from a verification benchmark into an attribution gate table. Every runner
builds an ExperimentSpec at startup and embeds it under an "experiment"
key in its report JSON; diff_specs() explains why two runs disagree, and
refuses to compare runs that answer different questions.
"""
from __future__ import annotations

import subprocess
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

from validation.benchmark.reproducibility import BENCHMARK_SEED, _SCORING_FLAG_DEFAULTS

VALID_TASKS = {
    "verification",      # is this typical for this author?
    "attribution",       # which of N candidate authors?
    "drift",             # is change over time plausibly evolution?
    "weight_derivation", # Fisher-ratio tier weights
    "calibration_suite", # the G1-G6 gate battery (mixed tasks, one run)
}


@dataclass(frozen=True)
class ExperimentSpec:
    task: str
    git_sha: str
    seed: int
    env_lock: dict[str, str]
    corpora: dict[str, dict]
    windowing: dict
    features: dict
    aggregation: dict
    thresholds: dict
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds")
    )


def _git_sha() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True, text=True, check=True, timeout=10,
        ).stdout.strip()
    except Exception:
        return "unknown"


def _feature_summary() -> dict:
    from original.constants import ALL_FEATURE_CODES
    from validation.measurability import status

    counts: dict[str, int] = {}
    for code in ALL_FEATURE_CODES:
        counts[status(code).value] = counts.get(status(code).value, 0) + 1
    return {"total": len(ALL_FEATURE_CODES), "status_counts": counts}


def summarize_author_docs(author_docs: dict[str, list[str]], provenance: str) -> dict:
    docs = [d for ds in author_docs.values() for d in ds]
    return {
        "n_authors": len(author_docs),
        "n_documents": len(docs),
        "total_words": sum(len(d.split()) for d in docs),
        "docs_per_author": {a: len(ds) for a, ds in sorted(author_docs.items())},
        "provenance": provenance,
    }


def build_spec(
    task: str,
    corpora: dict[str, dict],
    windowing: dict,
    aggregation: dict,
    thresholds: dict,
) -> ExperimentSpec:
    if task not in VALID_TASKS:
        raise ValueError(f"unknown task {task!r}; must be one of {sorted(VALID_TASKS)}")
    return ExperimentSpec(
        task=task,
        git_sha=_git_sha(),
        seed=BENCHMARK_SEED,
        env_lock=dict(_SCORING_FLAG_DEFAULTS),
        corpora=corpora,
        windowing=windowing,
        features=_feature_summary(),
        aggregation=aggregation,
        thresholds=thresholds,
    )


def spec_to_dict(spec: ExperimentSpec) -> dict:
    return asdict(spec)


def _flatten(d: Any, prefix: str = "") -> dict[str, Any]:
    out: dict[str, Any] = {}
    if isinstance(d, dict):
        for k, v in d.items():
            out.update(_flatten(v, f"{prefix}{k}."))
    else:
        out[prefix[:-1]] = d
    return out


def diff_specs(a: dict, b: dict) -> list[str]:
    if a.get("task") != b.get("task"):
        raise ValueError(
            f"refusing to compare different tasks: {a.get('task')!r} vs {b.get('task')!r} "
            "— these runs answer different questions"
        )
    fa, fb = _flatten(a), _flatten(b)
    changes = []
    for key in sorted(set(fa) | set(fb)):
        if key == "created_at" or key == "git_sha":
            continue
        va, vb = fa.get(key, "<absent>"), fb.get(key, "<absent>")
        if va != vb:
            changes.append(f"{key}: {va} != {vb}")
    return changes
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `/Users/andrew/Desktop/Original/.venv/bin/python -m pytest tests/test_experiment.py -q`
Expected: PASS.

- [ ] **Step 5: Embed in the three runners**

Each runner builds its spec where its corpora are in scope and attaches it
under `"experiment"` in whatever JSON payload it already writes:

1. `validation/calibration_gate.py` `main` (or `run_all` returning it
   alongside results): `task="calibration_suite"`, corpora from the three
   loader dicts via `summarize_author_docs` (provenance: seminary
   `"student_pilot"` — fixture-derived, note it; public_authors and plato
   `"real_historical"`), thresholds `{"g1_flagged_rate": 0.05, "g3_top1": 0.7,
   "g6_ratio": 2.0}` plus the typicality band constants, windowing
   `{"source": "corpus documents as-is"}`.
2. `scripts/derive_measured_weights.py`: `task="weight_derivation"`,
   windowing `{"length": args.length, "max_windows": ...}`, aggregation
   `{"tier_rule": "median", "variance_floor_percentile": args.floor_percentile,
   "derivation_fraction": args.derivation_fraction}`. Attach to its JSON/
   printed report dict.
3. `validation/public_authors/run.py`: `task="attribution"`, corpora from
   the manifest's baseline/scored doc lists, thresholds
   `{"g3_top1": 0.7}`. Attach to the summary dict it writes.

Anchor on each runner's existing report-assembly code; do not restructure
the runners.

- [ ] **Step 6: Full suite, commit**

```bash
/Users/andrew/Desktop/Original/.venv/bin/python -m pytest tests/ -q
git add validation/experiment.py tests/test_experiment.py validation/calibration_gate.py scripts/derive_measured_weights.py validation/public_authors/run.py
git commit -m "Add experiment specs: every validation report records what it measured

Mandatory task label (verification/attribution/drift/weight_derivation/
calibration_suite), git SHA, seed, env lock, corpus composition, windowing,
feature statuses, aggregation rules and thresholds, embedded under
'experiment' in each runner's report. diff_specs() refuses cross-task
comparison.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 8: Corpus policy + manifest v2

**Files:**
- Create: `validation/corpus_policy.py`
- Modify: `validation/manifest_schema.py` (v2 fields), `validation/public_authors/run.py` (enforce attribution policy)
- Test: `tests/test_corpus_policy.py`

**Interfaces:**
- Consumes: Task 5's `band_reachable`.
- Produces (used by Task 11's benchmark and future corpus builds):
  - `PolicyViolation(kind: str, subject: str, detail: str)` frozen dataclass
  - `check_verification_pool(word_counts: dict[str, int], min_words: int = 300) -> list[PolicyViolation]`
  - `check_attribution_pool(word_counts: dict[str, int], baseline_counts: dict[str, int], min_words: int = 500, min_baseline_docs: int = 3) -> list[PolicyViolation]`
  - `conformal_informative_authors(baseline_counts: dict[str, int], band_threshold: float) -> dict[str, bool]`
  - `check_genre_balance(genre_word_counts: dict[str, int], max_share: float = 0.6) -> list[PolicyViolation]`
  - `manifest_schema.Provenance` enum + `CorpusEntry.genre/register/provenance` + `CorpusEntry.effective_provenance`

**Why `check_genre_balance` is here:** the advisory's lead complaint is that
weights are derived on a corpus "21 parts Plato to 2 parts student-like
prose". The ExperimentSpec (Task 7) *records* composition, but recording is
not checking — `derive_measured_weights.py` currently carries that caveat as
a hand-written CAUTION string in its module docstring, which cannot go stale
loudly. This turns it into a computed, printed violation whose threshold
lives in the spec.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_corpus_policy.py
"""
tests/test_corpus_policy.py — corpus floors are policy, enforced at load
time. Short texts are verification-only, never attribution candidates; an
attribution candidate needs >= 3 baseline docs (the TOC-chunk failure made
2 of 9 public-author profiles out of 6-17-word stubs — this makes that
class of corpus impossible to load silently).
"""
from __future__ import annotations

from validation.corpus_policy import (
    PolicyViolation,
    check_attribution_pool,
    check_genre_balance,
    check_verification_pool,
    conformal_informative_authors,
)
from validation.manifest_schema import (
    AuthorshipLabel,
    CorpusEntry,
    Provenance,
)


class TestVerificationPool:
    def test_clean_pool_passes(self):
        assert check_verification_pool({"d1": 400, "d2": 300}) == []

    def test_short_documents_flagged(self):
        violations = check_verification_pool({"d1": 400, "toc_stub": 17})
        assert len(violations) == 1
        v = violations[0]
        assert v.kind == "short_document" and v.subject == "toc_stub"


class TestAttributionPool:
    def test_stricter_floor_than_verification(self):
        # 400 words passes verification but NOT attribution
        assert check_verification_pool({"d": 400}) == []
        kinds = [v.kind for v in check_attribution_pool({"d": 400}, {"a": 3})]
        assert kinds == ["short_document"]

    def test_thin_baseline_flagged(self):
        violations = check_attribution_pool({"d": 900}, {"kempis": 2, "mill": 5})
        assert [(v.kind, v.subject) for v in violations] == [("thin_baseline", "kempis")]


class TestConformalInformative:
    def test_pilot_scale_counts_are_uninformative(self):
        result = conformal_informative_authors({"s1": 12, "s2": 40}, band_threshold=0.03)
        assert result == {"s1": False, "s2": True}


class TestGenreBalance:
    def test_the_actual_derivation_corpus_skew_is_flagged(self):
        # "21 parts Plato to 2 parts student-like prose" (Instrument Report)
        violations = check_genre_balance({"philosophy": 21000, "student_essay": 2000})
        assert len(violations) == 1
        v = violations[0]
        assert v.kind == "genre_dominance" and v.subject == "philosophy"
        assert "91" in v.detail  # 21000/23000 = 91.3%

    def test_balanced_corpus_passes(self):
        assert check_genre_balance(
            {"philosophy": 4000, "sermon": 3500, "student_essay": 3000}
        ) == []

    def test_threshold_is_caller_controlled(self):
        counts = {"philosophy": 7000, "student_essay": 3000}  # 70%
        assert check_genre_balance(counts, max_share=0.75) == []
        assert len(check_genre_balance(counts, max_share=0.6)) == 1

    def test_empty_corpus_is_not_a_violation(self):
        assert check_genre_balance({}) == []


class TestManifestV2:
    def _entry(self, **over):
        kwargs = dict(
            filename="x.txt", author_id="a", label=AuthorshipLabel.AUTHENTIC,
            prompt="p", word_count=500,
        )
        kwargs.update(over)
        return CorpusEntry(**kwargs)

    def test_v1_manifests_still_load(self):
        e = self._entry()
        assert e.genre is None and e.provenance is None

    def test_effective_provenance_defaults_by_label(self):
        assert self._entry().effective_provenance is Provenance.REAL_HISTORICAL
        assert (
            self._entry(label=AuthorshipLabel.AI_GENERATED).effective_provenance
            is Provenance.SYNTHETIC_AI
        )
        assert (
            self._entry(label=AuthorshipLabel.PARAPHRASED).effective_provenance
            is Provenance.SYNTHETIC_AI
        )
        assert (
            self._entry(label=AuthorshipLabel.GHOSTWRITTEN).effective_provenance
            is Provenance.REAL_HISTORICAL
        )

    def test_explicit_provenance_wins(self):
        e = self._entry(provenance=Provenance.STUDENT_PILOT)
        assert e.effective_provenance is Provenance.STUDENT_PILOT
```

- [ ] **Step 2: Run to verify failure**

Run: `/Users/andrew/Desktop/Original/.venv/bin/python -m pytest tests/test_corpus_policy.py -q`
Expected: FAIL — module and fields missing.

- [ ] **Step 3: Implement `corpus_policy.py`**

```python
# validation/corpus_policy.py
"""
validation/corpus_policy.py — enforced corpus floors, per task.

Policy (design spec C4): short texts are verification-only, never
attribution candidates. Floors are arguments with defaults — runners
record the values they used in their ExperimentSpec, so a floor change is
visible in every report diff.
"""
from __future__ import annotations

from dataclasses import dataclass

VERIFICATION_MIN_WORDS = 300  # matches the public_authors chunker floor
ATTRIBUTION_MIN_WORDS = 500   # stricter; open decision #2 in the design spec
ATTRIBUTION_MIN_BASELINE_DOCS = 3


@dataclass(frozen=True)
class PolicyViolation:
    kind: str     # "short_document" | "thin_baseline"
    subject: str  # document id or author id
    detail: str


def check_verification_pool(
    word_counts: dict[str, int],
    min_words: int = VERIFICATION_MIN_WORDS,
) -> list[PolicyViolation]:
    return [
        PolicyViolation(
            kind="short_document",
            subject=doc_id,
            detail=f"{count} words < verification floor {min_words}",
        )
        for doc_id, count in sorted(word_counts.items())
        if count < min_words
    ]


def check_attribution_pool(
    word_counts: dict[str, int],
    baseline_counts: dict[str, int],
    min_words: int = ATTRIBUTION_MIN_WORDS,
    min_baseline_docs: int = ATTRIBUTION_MIN_BASELINE_DOCS,
) -> list[PolicyViolation]:
    violations = [
        PolicyViolation(
            kind="short_document",
            subject=doc_id,
            detail=f"{count} words < attribution floor {min_words} "
            "(verification-only; never an attribution candidate)",
        )
        for doc_id, count in sorted(word_counts.items())
        if count < min_words
    ]
    violations += [
        PolicyViolation(
            kind="thin_baseline",
            subject=author,
            detail=f"{count} baseline docs < required {min_baseline_docs}",
        )
        for author, count in sorted(baseline_counts.items())
        if count < min_baseline_docs
    ]
    return violations


def conformal_informative_authors(
    baseline_counts: dict[str, int],
    band_threshold: float,
) -> dict[str, bool]:
    """Which authors have enough baseline docs for the typicality band to
    be reachable at all? Feeds gate informativeness (validation/power.py)."""
    from validation.power import band_reachable

    return {a: band_reachable(n, band_threshold) for a, n in baseline_counts.items()}


MAX_GENRE_SHARE = 0.6


def check_genre_balance(
    genre_word_counts: dict[str, int],
    max_share: float = MAX_GENRE_SHARE,
) -> list[PolicyViolation]:
    """
    Flag a derivation corpus dominated by one genre.

    Weights derived on a corpus that is overwhelmingly one register say
    more about that register than about the target task — the Instrument
    Report's standing caveat ("21 parts Plato to 2 parts student-like
    prose") made computable, so it cannot rot into a stale docstring.
    """
    total = sum(genre_word_counts.values())
    if total == 0:
        return []
    return [
        PolicyViolation(
            kind="genre_dominance",
            subject=genre,
            detail=f"{count / total:.1%} of corpus words ({count}/{total}) "
            f"exceeds the {max_share:.0%} single-genre ceiling — derived "
            "quantities describe this genre more than the target task",
        )
        for genre, count in sorted(genre_word_counts.items())
        if count / total > max_share
    ]
```

- [ ] **Step 4: Extend `manifest_schema.py`**

Add after `AIProvider`:

```python
class Provenance(str, Enum):
    """Where a corpus document actually came from — never inferred silently."""

    REAL_HISTORICAL = "real_historical"  # published human prose (Gutenberg etc.)
    SYNTHETIC_AI = "synthetic_ai"        # AI-generated or AI-transformed
    STUDENT_PILOT = "student_pilot"      # consented student writing
```

Add to `CorpusEntry`:

```python
    genre: Optional[str] = Field(
        None, description="Genre/register tag (e.g. 'philosophy', 'sermon', 'student_essay')."
    )
    register: Optional[str] = None
    provenance: Optional[Provenance] = Field(
        None,
        description="Document provenance; if unset, effective_provenance derives it from label.",
    )

    @property
    def effective_provenance(self) -> Provenance:
        if self.provenance is not None:
            return self.provenance
        if self.label in (
            AuthorshipLabel.AI_GENERATED,
            AuthorshipLabel.MIXED,
            AuthorshipLabel.PARAPHRASED,
        ):
            return Provenance.SYNTHETIC_AI
        return Provenance.REAL_HISTORICAL
```

- [ ] **Step 5: Enforce in `validation/public_authors/run.py`**

In `run()`, after the manifest is loaded and `by_author` is built (anchor:
the loop over `manifest["entries"]`), compute the pools and refuse thin
baselines; short scored essays are dropped to verification-only with a loud
line, not scored for attribution:

```python
    from validation.corpus_policy import check_attribution_pool

    word_counts = {e["filename"]: e["word_count"] for e in manifest["entries"]}
    baseline_counts = {a: len(by_author[a]["baseline"]) for a in by_author}
    violations = check_attribution_pool(word_counts, baseline_counts)
    for v in violations:
        print(f"  ⚠ corpus policy: {v.kind} — {v.subject}: {v.detail}", file=sys.stderr)
    thin = {v.subject for v in violations if v.kind == "thin_baseline"}
    if thin:
        raise SystemExit(
            f"attribution refused: authors with thin baselines {sorted(thin)} "
            "(fix the corpus; do not attribute against stub profiles)"
        )
    short_docs = {v.subject for v in violations if v.kind == "short_document"}
    # drop short docs from the scored pool (verification-only policy)
```

(Adapt dict-key names — `by_author[a]["baseline"]` / `["scored"]` — to the
actual structure in `run()`; record dropped docs in the summary dict.)

- [ ] **Step 5b: Wire the balance check into `scripts/derive_measured_weights.py`**

The script's module docstring carries a hand-written CAUTION about Plato
dominance. Replace the *enforcement* half with a computed check at the point
where the derivation-side corpora are assembled (anchor: after the
`drop_short_authors` call, where the surviving per-author texts are known):

```python
    from validation.corpus_policy import check_genre_balance

    # Genre is per-corpus here (seminary=student_essay, plato=philosophy,
    # public_authors=literary_essay); manifest-level genre tags refine this
    # once corpora carry them (validation/manifest_schema.py v2).
    genre_words = {
        "student_essay": _words_in(seminary_texts),
        "philosophy": _words_in(plato_texts),
        "literary_essay": _words_in(public_texts),
    }
    for v in check_genre_balance(genre_words):
        print(f"  ⚠ CORPUS BALANCE: {v.subject} — {v.detail}", file=sys.stderr)
```

with `_words_in(d) = sum(len(t.split()) for ts in d.values() for t in ts)`.
Record `genre_words` and the violation list in the run's ExperimentSpec
`corpora` block (Task 7) so the skew travels with every number derived from
it. **Keep the docstring CAUTION** — it explains *why*; the check enforces.

- [ ] **Step 6: Run tests + full suite, commit**

```bash
/Users/andrew/Desktop/Original/.venv/bin/python -m pytest tests/test_corpus_policy.py tests/ -q
git add validation/corpus_policy.py validation/manifest_schema.py validation/public_authors/run.py scripts/derive_measured_weights.py tests/test_corpus_policy.py
git commit -m "Add corpus policy floors, genre-balance check, manifest v2 fields

Verification floor 300 words; attribution floor 500 words + >=3 baseline
docs, enforced in public_authors/run.py (thin baselines refuse the run;
short docs become verification-only). check_genre_balance turns the
Plato-dominance caveat into a computed warning in the weight derivation.
Manifest entries gain genre/register/provenance with label-derived defaults.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 9: Cosine-delta attribution engine

**Files:**
- Create: `validation/attribution/__init__.py` (empty), `validation/attribution/delta.py`
- Test: `tests/test_attribution_delta.py`

**Interfaces:**
- Consumes: Task 2's `measurable_indices(corpus)`.
- Produces (used by Task 11):
  - `cosine_delta_attribution(baseline_matrices: dict[str, np.ndarray], test_vector: np.ndarray, feature_indices: Sequence[int]) -> tuple[str, dict[str, float]]` — returns (predicted author, per-author cosine distance); lower = closer.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_attribution_delta.py
"""
tests/test_attribution_delta.py — distance-based attribution engines.

The raw argmin of per-author z-scores let the author with the loosest
baseline absorb 11 of 12 misattributions (Instrument Report). These
engines normalize at POOL level, so per-author variance scales cannot
create a black hole — the scale-invariance tests below pin exactly that
property.
"""
from __future__ import annotations

import numpy as np
import pytest

from validation.attribution.delta import cosine_delta_attribution


def _matrices():
    rng = np.random.default_rng(1729)
    # Three authors with distinct 6-dim signatures, 5 baseline docs each.
    centers = {
        "alpha": np.array([0.2, 0.8, 0.4, 0.6, 0.3, 0.7]),
        "beta": np.array([0.7, 0.2, 0.6, 0.3, 0.8, 0.2]),
        "gamma": np.array([0.5, 0.5, 0.9, 0.1, 0.5, 0.5]),
    }
    return {
        a: c + rng.normal(0, 0.02, size=(5, 6)) for a, c in centers.items()
    }, centers


class TestCosineDelta:
    def test_recovers_true_author(self):
        matrices, centers = _matrices()
        for author, center in centers.items():
            test_vec = center + 0.01
            predicted, dists = cosine_delta_attribution(
                matrices, test_vec, feature_indices=list(range(6))
            )
            assert predicted == author
            assert set(dists) == set(centers)

    def test_loose_baseline_cannot_become_a_black_hole(self):
        # Inflate ONE author's within-baseline spread 50x. Under the old
        # own-z argmin this makes them absorb everything; pool-level
        # normalization must not care about within-author spread.
        matrices, centers = _matrices()
        rng = np.random.default_rng(7)
        matrices["gamma"] = centers["gamma"] + rng.normal(0, 1.0, size=(5, 6))
        test_vec = centers["alpha"] + 0.01
        predicted, _ = cosine_delta_attribution(
            matrices, test_vec, feature_indices=list(range(6))
        )
        assert predicted == "alpha"

    def test_restricts_to_given_feature_indices(self):
        matrices, centers = _matrices()
        # Make dims 3..5 pure noise for the test vector; dims 0..2 decide.
        test_vec = np.concatenate([centers["beta"][:3], np.array([9.0, 9.0, 9.0])])
        predicted, _ = cosine_delta_attribution(
            matrices, test_vec, feature_indices=[0, 1, 2]
        )
        assert predicted == "beta"

    def test_empty_author_matrix_is_skipped(self):
        matrices, centers = _matrices()
        matrices["empty"] = np.zeros((0, 6))
        predicted, dists = cosine_delta_attribution(
            matrices, centers["alpha"], feature_indices=list(range(6))
        )
        assert "empty" not in dists and predicted == "alpha"

    def test_fewer_than_two_authors_raises(self):
        matrices, centers = _matrices()
        with pytest.raises(ValueError):
            cosine_delta_attribution(
                {"alpha": matrices["alpha"]}, centers["alpha"], list(range(6))
            )
```

- [ ] **Step 2: Run to verify failure**

Run: `/Users/andrew/Desktop/Original/.venv/bin/python -m pytest tests/test_attribution_delta.py -q`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement**

```python
# validation/attribution/delta.py
"""
validation/attribution/delta.py — distance-based attribution engines
(Burrows'-Delta family), validation-layer only.

Both engines normalize at CANDIDATE-POOL level: features are z-scored
against the spread of the candidates' centroids/profiles, never against a
single author's own baseline spread. That is the structural difference
from the raw argmin-of-own-z rule the Instrument Report retired — a loose
per-author baseline cannot become an attribution black hole here.
"""
from __future__ import annotations

from typing import Sequence

import numpy as np

_SD_FLOOR = 1e-9


def cosine_delta_attribution(
    baseline_matrices: dict[str, np.ndarray],
    test_vector: np.ndarray,
    feature_indices: Sequence[int],
) -> tuple[str, dict[str, float]]:
    """
    Nearest-centroid by cosine distance in pool-z-scored feature space.

    baseline_matrices: {author: (n_docs, FEATURE_DIM)} raw feature rows
      (one row per baseline document, e.g. from feature_vector()).
    test_vector: (FEATURE_DIM,) raw features of the disputed document.
    feature_indices: which columns to use — pass
      validation.measurability.measurable_indices(corpus) so blank columns
      can never contribute.

    Returns (predicted_author, {author: cosine_distance}); lower = closer.
    """
    idx = np.asarray(list(feature_indices), dtype=int)
    centroids = {
        a: m[:, idx].mean(axis=0)
        for a, m in baseline_matrices.items()
        if m.shape[0] > 0
    }
    if len(centroids) < 2:
        raise ValueError(
            f"attribution needs >= 2 candidates with baseline docs, got {len(centroids)}"
        )
    names = sorted(centroids)
    pool = np.vstack([centroids[a] for a in names])
    mu = pool.mean(axis=0)
    sd = np.maximum(pool.std(axis=0, ddof=0), _SD_FLOOR)
    pool_z = (pool - mu) / sd
    test_z = (np.asarray(test_vector, dtype=float)[idx] - mu) / sd

    distances = {
        a: _cosine_distance(pool_z[i], test_z) for i, a in enumerate(names)
    }
    predicted = min(distances, key=distances.get)
    return predicted, distances


def _cosine_distance(u: np.ndarray, v: np.ndarray) -> float:
    nu, nv = np.linalg.norm(u), np.linalg.norm(v)
    if nu == 0.0 or nv == 0.0:
        return 1.0
    return 1.0 - float(np.dot(u, v) / (nu * nv))
```

- [ ] **Step 4: Run tests + full suite, commit**

```bash
/Users/andrew/Desktop/Original/.venv/bin/python -m pytest tests/test_attribution_delta.py tests/ -q
git add validation/attribution/__init__.py validation/attribution/delta.py tests/test_attribution_delta.py
git commit -m "Add cosine-delta attribution engine (pool-normalized nearest centroid)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 10: Classic MFW Burrows' Delta engine

**Files:**
- Modify: `validation/attribution/delta.py` (append)
- Test: extend `tests/test_attribution_delta.py`

**Interfaces:**
- Produces (used by Task 11):
  - `mfw_delta_attribution(baseline_texts: dict[str, list[str]], test_text: str, top_n: int = 150) -> tuple[str, dict[str, float]]` — classic Burrows' Delta over most-frequent words; deliberately independent of the 109-feature pipeline.

- [ ] **Step 1: Write the failing tests**

```python
# append to tests/test_attribution_delta.py
from validation.attribution.delta import mfw_delta_attribution


def _texts():
    # Two authors with opposite function-word tilts; enough tokens for
    # stable relative frequencies.
    a = ("the cat sat upon the mat and the dog lay upon the rug and "
         "the bird sat upon the branch and the sun shone upon the field ") * 30
    b = ("a child walks with a kite while a friend runs with a ball since "
         "a day begins with a song while a night ends with a story ") * 30
    return {"upon_author": [a, a], "with_author": [b, b]}


class TestMfwDelta:
    def test_recovers_true_author(self):
        texts = _texts()
        pred_a, deltas_a = mfw_delta_attribution(texts, texts["upon_author"][0])
        pred_b, deltas_b = mfw_delta_attribution(texts, texts["with_author"][0])
        assert pred_a == "upon_author"
        assert pred_b == "with_author"
        assert set(deltas_a) == {"upon_author", "with_author"}

    def test_unseen_words_do_not_crash(self):
        pred, _ = mfw_delta_attribution(
            _texts(), "zyx qwv completely novel vocabulary upon upon the the"
        )
        assert pred == "upon_author"

    def test_fewer_than_two_authors_raises(self):
        import pytest

        with pytest.raises(ValueError):
            mfw_delta_attribution({"solo": ["some text here"]}, "test")
```

- [ ] **Step 2: Run to verify failure**

Run: `/Users/andrew/Desktop/Original/.venv/bin/python -m pytest tests/test_attribution_delta.py::TestMfwDelta -q`
Expected: FAIL — `mfw_delta_attribution` not defined.

- [ ] **Step 3: Implement (append to `delta.py`)**

```python
import re
from collections import Counter

_WORD_RE = re.compile(r"[a-z']+")


def _tokens(text: str) -> list[str]:
    return _WORD_RE.findall(text.lower())


def _rel_freqs(tokens: list[str], vocab: list[str]) -> np.ndarray:
    counts = Counter(tokens)
    total = len(tokens) or 1
    return np.array([counts[w] / total for w in vocab], dtype=float)


def mfw_delta_attribution(
    baseline_texts: dict[str, list[str]],
    test_text: str,
    top_n: int = 150,
) -> tuple[str, dict[str, float]]:
    """
    Classic Burrows' Delta: z-score the top_n most-frequent words' relative
    frequencies across the candidate pool; Delta(author) = mean |z_test -
    z_author|. Independent of the feature pipeline by design — the "cheap
    but robust" cross-check engine.
    """
    if len(baseline_texts) < 2:
        raise ValueError(
            f"attribution needs >= 2 candidates, got {len(baseline_texts)}"
        )
    pooled: Counter = Counter()
    for docs in baseline_texts.values():
        for doc in docs:
            pooled.update(_tokens(doc))
    vocab = [w for w, _ in pooled.most_common(top_n)]

    names = sorted(baseline_texts)
    profiles = np.vstack([
        np.mean([_rel_freqs(_tokens(d), vocab) for d in baseline_texts[a]], axis=0)
        for a in names
    ])
    mu = profiles.mean(axis=0)
    sd = np.maximum(profiles.std(axis=0, ddof=0), _SD_FLOOR)
    profiles_z = (profiles - mu) / sd
    test_z = (_rel_freqs(_tokens(test_text), vocab) - mu) / sd

    deltas = {
        a: float(np.mean(np.abs(test_z - profiles_z[i])))
        for i, a in enumerate(names)
    }
    return min(deltas, key=deltas.get), deltas
```

- [ ] **Step 4: Run tests + full suite, commit**

```bash
/Users/andrew/Desktop/Original/.venv/bin/python -m pytest tests/test_attribution_delta.py tests/ -q
git add validation/attribution/delta.py tests/test_attribution_delta.py
git commit -m "Add classic MFW Burrows' Delta engine, pipeline-independent

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 11: Ensemble + side-by-side benchmark integration

**Files:**
- Create: `validation/attribution/ensemble.py`
- Modify: `validation/public_authors/run.py` (compute all three engines per held-out essay; extend summary)
- Test: `tests/test_attribution_ensemble.py`

**Interfaces:**
- Consumes: Tasks 9–10 engines; existing `calibrated_attribution()` and `AttributionResult` in `run.py`; `original.features.pipeline.feature_vector(text) -> np.ndarray (FEATURE_DIM,)`; Task 2's `measurable_indices("public_authors")`.
- Produces:
  - `ensemble_vote(predictions: dict[str, str]) -> tuple[str | None, str]` — `(author or None, basis)`; None routes to manual review.
  - `pairwise_agreement(per_essay_predictions: list[dict[str, str]]) -> dict[str, float]` — keys `"engineA|engineB"`.
  - `run.py` summary gains `per_engine_top1`, `ensemble_coverage`, `ensemble_accuracy_on_covered`, `engine_agreement`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_attribution_ensemble.py
"""
tests/test_attribution_ensemble.py — 2-of-3 agreement routing. Forced
top-1 answers are what made the argmin failure invisible; the ensemble
returns None (manual review) on disagreement instead of guessing.
"""
from __future__ import annotations

from validation.attribution.ensemble import ensemble_vote, pairwise_agreement


class TestEnsembleVote:
    def test_unanimous(self):
        author, basis = ensemble_vote(
            {"deviation_calibrated": "mill", "cosine_delta": "mill", "mfw_delta": "mill"}
        )
        assert author == "mill" and "3-of-3" in basis

    def test_two_of_three(self):
        author, basis = ensemble_vote(
            {"deviation_calibrated": "mill", "cosine_delta": "mill", "mfw_delta": "kempis"}
        )
        assert author == "mill" and "2-of-3" in basis

    def test_three_way_split_routes_to_manual_review(self):
        author, basis = ensemble_vote(
            {"deviation_calibrated": "a", "cosine_delta": "b", "mfw_delta": "c"}
        )
        assert author is None and "manual review" in basis


class TestPairwiseAgreement:
    def test_rates(self):
        rows = [
            {"x": "a", "y": "a"},
            {"x": "a", "y": "b"},
        ]
        agreement = pairwise_agreement(rows)
        assert agreement == {"x|y": 0.5}
```

- [ ] **Step 2: Run to verify failure**

Run: `/Users/andrew/Desktop/Original/.venv/bin/python -m pytest tests/test_attribution_ensemble.py -q`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement `ensemble.py`**

```python
# validation/attribution/ensemble.py
"""
validation/attribution/ensemble.py — agreement routing across attribution
engines. 2-of-N agree → attribute, naming the engines; otherwise None →
"unknown — manual review". Never forces a top-1 answer.
"""
from __future__ import annotations

from collections import Counter
from itertools import combinations


def ensemble_vote(predictions: dict[str, str]) -> tuple[str | None, str]:
    if not predictions:
        return None, "no engine predictions — manual review"
    counts = Counter(predictions.values())
    top_author, top_count = counts.most_common(1)[0]
    if top_count >= 2:
        agreeing = sorted(e for e, p in predictions.items() if p == top_author)
        return top_author, f"{top_count}-of-{len(predictions)} agree ({', '.join(agreeing)})"
    return None, "engines disagree — manual review"


def pairwise_agreement(per_essay_predictions: list[dict[str, str]]) -> dict[str, float]:
    if not per_essay_predictions:
        return {}
    engines = sorted(per_essay_predictions[0])
    out: dict[str, float] = {}
    for a, b in combinations(engines, 2):
        matches = sum(1 for row in per_essay_predictions if row[a] == row[b])
        out[f"{a}|{b}"] = matches / len(per_essay_predictions)
    return out
```

- [ ] **Step 4: Run unit tests**

Run: `/Users/andrew/Desktop/Original/.venv/bin/python -m pytest tests/test_attribution_ensemble.py -q`
Expected: PASS.

- [ ] **Step 5: Integrate into `validation/public_authors/run.py`**

Anchoring on the existing held-out scoring loop (the one that fills
`AttributionResult` with `predicted_author` / `predicted_author_raw`):

1. Once per run, build the delta inputs from the SAME baseline docs the
   deviation engine uses:

```python
    from original.features.pipeline import feature_vector
    from validation.attribution.delta import cosine_delta_attribution, mfw_delta_attribution
    from validation.attribution.ensemble import ensemble_vote, pairwise_agreement
    from validation.measurability import measurable_indices

    feature_idx = measurable_indices("public_authors")
    baseline_matrices = {
        a: np.vstack([feature_vector(doc) for doc in by_author[a]["baseline"]])
        for a in eligible
    }
    baseline_texts = {a: list(by_author[a]["baseline"]) for a in eligible}
```

   (~27 `feature_vector` calls at ~650 ms ≈ 20 s once per run — acceptable
   for this manual benchmark.)

2. Inside the per-essay loop, after the existing calibrated prediction:

```python
        cos_pred, cos_dists = cosine_delta_attribution(
            baseline_matrices, feature_vector(essay_text), feature_idx
        )
        mfw_pred, mfw_deltas = mfw_delta_attribution(baseline_texts, essay_text)
        engine_predictions = {
            "deviation_calibrated": predicted,   # the existing engine's pick
            "cosine_delta": cos_pred,
            "mfw_delta": mfw_pred,
        }
        ensemble_author, ensemble_basis = ensemble_vote(engine_predictions)
```

   Extend `AttributionResult` with
   `engine_predictions: Dict[str, str] = field(default_factory=dict)` and
   `ensemble_author: Optional[str] = None`, `ensemble_basis: str = ""`, and
   store the values.

3. In the summary assembly, add:

```python
        from validation.power import wilson_interval

        rows = [r.engine_predictions for r in results]
        n = len(results)
        summary["n_scored_essays"] = n  # G3's informativeness input (Task 6)
        summary["per_engine_top1"] = {}
        for engine in rows[0]:
            hits = sum(1 for r in results if r.engine_predictions[engine] == r.true_author)
            lo, hi = wilson_interval(hits, n)
            # Every accuracy travels with its interval: at n=22 the CI is
            # ~±0.2, wide enough that two engines can differ by 0.15 and be
            # statistically indistinguishable. Print it so the side-by-side
            # table is never read as a ranking it cannot support.
            summary["per_engine_top1"][engine] = {
                "accuracy": hits / n,
                "wilson_ci_95": [lo, hi],
                "n": n,
            }
        covered = [r for r in results if r.ensemble_author is not None]
        summary["ensemble_coverage"] = len(covered) / len(results)
        summary["ensemble_accuracy_on_covered"] = (
            sum(1 for r in covered if r.ensemble_author == r.true_author) / len(covered)
            if covered else None
        )
        summary["engine_agreement"] = pairwise_agreement(rows)
```

   (Adapt attribute names — `true_author` etc. — to `AttributionResult`'s
   actual fields.)

- [ ] **Step 6: Full suite, then a real benchmark run (manual)**

```bash
/Users/andrew/Desktop/Original/.venv/bin/python -m pytest tests/ -q
```

Expected: `0 failed`. Then run the corpus benchmark once to produce the
first side-by-side table (slow, scores 9 baselines × 22 essays):

```bash
/Users/andrew/Desktop/Original/.venv/bin/python -m validation.public_authors.run
```

Expected: summary JSON now contains `per_engine_top1` (accuracy + 95% Wilson
CI + n for all three engines), `n_scored_essays`, `ensemble_coverage`,
`ensemble_accuracy_on_covered`, `engine_agreement`, and the `experiment`
spec with `task="attribution"`. Record whatever the numbers are — do NOT
tune until they look good. **Read the intervals before drawing any
conclusion**: at n=22 they are roughly ±0.2 wide, so an engine leading by
0.1 has not been shown to be better.

- [ ] **Step 7: Commit**

```bash
git add validation/attribution/ensemble.py validation/public_authors/run.py tests/test_attribution_ensemble.py
git commit -m "Add attribution ensemble: three engines side by side, 2-of-3 routing

public_authors benchmark now reports deviation-calibrated, cosine-delta and
MFW-Delta accuracy on identical held-out essays, pairwise agreement, and an
ensemble that routes disagreement to manual review instead of forcing top-1.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 12: Gate falsifiability contracts

**Files:**
- Create: `validation/gate_contracts.py`
- Test: `tests/test_gate_falsifiability.py`

**Interfaces:**
- Consumes: every `evaluate_g*` in `validation/calibration_gate.py`; Task 6's `verdict`.
- Produces: `GATE_CONTRACTS: dict[str, GateContract]` with
  `GateContract(gate: str, claims: str, failure_witness: Callable[[], GateResult], label_destruction: Callable[[], GateResult] | None, notes: str = "")`.

**⚠ Re-verify signatures first** — the file is under active development.
The witness code below matches tip `34d8ceb6`; adjust arguments if the
merged signatures differ, keeping each witness's *property* (it must
produce `verdict == "fail"`).

- [ ] **Step 1: Write the contracts module**

```python
# validation/gate_contracts.py
"""
validation/gate_contracts.py — the falsifiability register.

For every calibration gate: what it claims to prove, one concrete input on
which it FAILS (proof it cannot pass by construction — the exact defect
G5's first design shipped with), and where meaningful, an input encoding
label destruction (authorship structure removed) that must never PASS.

tests/test_gate_falsifiability.py enforces: every evaluate_g* exported by
validation.calibration_gate has an entry here, every failure witness
fails, every label-destruction result is not "pass". Adding a gate without
a registered failure mode is a test failure, not a review comment.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Optional

from validation.calibration_gate import (
    GateResult,
    evaluate_g1_fpr,
    evaluate_g2_bland_impostor,
    evaluate_g2b_paraphrase_resistant,
    evaluate_g3_attribution,
    evaluate_g4_career_drift_monotone,
    evaluate_g5_permutation_null,
    evaluate_g6_fairness,
)


@dataclass(frozen=True)
class GateContract:
    gate: str
    claims: str
    failure_witness: Callable[[], GateResult]
    label_destruction: Optional[Callable[[], GateResult]] = None
    notes: str = ""


GATE_CONTRACTS: dict[str, GateContract] = {
    "evaluate_g1_fpr": GateContract(
        gate="G1",
        claims="pooled same-author flagged rate <= 5%",
        failure_witness=lambda: evaluate_g1_fpr(
            ["monitor"] * 20, per_corpus={"w": ["monitor"] * 20}
        ),
        label_destruction=None,
        notes="Label destruction for G1 lives in G5's deviation-shift leg; "
        "informativeness (cannot-flag-at-this-N) is handled by the "
        "uninformative verdict, tested in test_calibration_gate.py.",
    ),
    "evaluate_g2_bland_impostor": GateContract(
        gate="G2",
        claims="impostors do not look MORE typical than genuine holdout",
        failure_witness=lambda: evaluate_g2_bland_impostor(
            holdout_q=[0.1, 0.15, 0.2], impostor_q=[0.6, 0.7, 0.8]
        ),
        label_destruction=lambda: evaluate_g2_bland_impostor(
            # swap the populations: genuine work labeled impostor must fail
            holdout_q=[0.02, 0.03, 0.04], impostor_q=[0.3, 0.4, 0.5]
        ),
    ),
    "evaluate_g2b_paraphrase_resistant": GateContract(
        gate="G2b",
        claims="mechanically-paraphrased impostors still separate (PROXY only)",
        failure_witness=lambda: evaluate_g2b_paraphrase_resistant(
            holdout_q=[0.1, 0.2], paraphrased_impostor_q=[0.5, 0.6]
        ),
        label_destruction=None,
        notes="Proxy label must survive in criterion and detail — asserted "
        "in the falsifiability tests.",
    ),
    "evaluate_g3_attribution": GateContract(
        gate="G3",
        claims="public_authors top-1 attribution accuracy >= 0.7",
        failure_witness=lambda: evaluate_g3_attribution(0.455),
        label_destruction=lambda: evaluate_g3_attribution(1.0 / 9.0),
        notes="1/9 is chance level for the 9-author pool — destroyed labels "
        "must land near it and MUST fail.",
    ),
    "evaluate_g4_career_drift_monotone": GateContract(
        gate="G4",
        claims="typicality distance is non-decreasing early -> middle -> late",
        failure_witness=lambda: evaluate_g4_career_drift_monotone(
            {"early": 0.9, "middle": 0.5, "late": 0.7}
        ),
        label_destruction=lambda: evaluate_g4_career_drift_monotone(
            {"early": 0.731, "middle": 0.668, "late": 0.636}  # reversed real values
        ),
    ),
    "evaluate_g5_permutation_null": GateContract(
        gate="G5",
        claims="shuffled labels collapse all three scoring legs "
        "(deviation rises under blending; attribution to chance; drift order broken)",
        failure_witness=lambda: evaluate_g5_permutation_null(
            real_g1_mean_deviation=1.0,
            shuffled_g1_mean_deviation=0.9,  # insensitive to blending → fail
            shuffled_g3_accuracy=0.9,        # still attributes → fail
            g4_nonmonotone_draws=0,
            g4_total_draws=3,                # still monotone → fail
        ),
        label_destruction=None,
        notes="G5 IS the label-destruction control for the suite.",
    ),
    "evaluate_g6_fairness": GateContract(
        gate="G6",
        claims="native/non-native flagged-rate ratio <= 2x",
        failure_witness=lambda: evaluate_g6_fairness(
            native_fpr=0.01, non_native_fpr=0.10
        ),
        label_destruction=None,
        notes="One-zero rates are an infinite disparity and fail; both-zero "
        "is uninformative (commit 34d8ceb6 + Task 6 audit).",
    ),
}
```

- [ ] **Step 2: Write the enforcement tests**

```python
# tests/test_gate_falsifiability.py
"""
tests/test_gate_falsifiability.py — no gate may pass by construction.

Meta-test: every evaluate_g* in validation.calibration_gate must have a
GateContract whose failure witness actually fails. This turns "the gate
cannot fail" from a review finding into an unmergeable state.
"""
from __future__ import annotations

import inspect

import pytest

import validation.calibration_gate as calibration_gate
from validation.gate_contracts import GATE_CONTRACTS


def _all_gate_evaluators() -> list[str]:
    return sorted(
        name
        for name, obj in inspect.getmembers(calibration_gate, inspect.isfunction)
        if name.startswith("evaluate_g")
    )


class TestEveryGateHasAContract:
    def test_no_unregistered_gates(self):
        missing = [n for n in _all_gate_evaluators() if n not in GATE_CONTRACTS]
        assert missing == [], (
            f"gates without falsifiability contracts: {missing} — register a "
            "failure witness in validation/gate_contracts.py before merging"
        )

    def test_no_stale_contracts(self):
        stale = [n for n in GATE_CONTRACTS if n not in _all_gate_evaluators()]
        assert stale == []


@pytest.mark.parametrize("name", sorted(GATE_CONTRACTS))
class TestContracts:
    def test_failure_witness_fails(self, name):
        result = GATE_CONTRACTS[name].failure_witness()
        assert result.verdict == "fail", (
            f"{name}'s failure witness returned {result.verdict!r} — "
            "the gate can no longer fail on its registered counterexample"
        )

    def test_label_destruction_never_passes(self, name):
        contract = GATE_CONTRACTS[name]
        if contract.label_destruction is None:
            pytest.skip("no label-destruction leg for this gate (see notes)")
        result = contract.label_destruction()
        assert result.verdict != "pass", (
            f"{name} passed on label-destroyed input — it is not measuring "
            "authorship"
        )


class TestG2bProxyLabelSurvives:
    def test_proxy_label_in_criterion_and_detail(self):
        result = GATE_CONTRACTS["evaluate_g2b_paraphrase_resistant"].failure_witness()
        assert "proxy" in result.criterion.lower()
        assert "proxy_note" in result.detail
```

- [ ] **Step 3: Run — expect signature mismatches to surface here**

Run: `/Users/andrew/Desktop/Original/.venv/bin/python -m pytest tests/test_gate_falsifiability.py -v`
Expected: PASS if signatures match the merged tip. Any `TypeError` means the
gate signature changed since `34d8ceb6` — fix the witness to the current
signature, preserving its property (verdict must be "fail").

- [ ] **Step 4: Full suite, commit**

```bash
/Users/andrew/Desktop/Original/.venv/bin/python -m pytest tests/ -q
git add validation/gate_contracts.py tests/test_gate_falsifiability.py
git commit -m "Add gate falsifiability contracts: every gate must be able to fail

Registry of claims + failure witnesses + label-destruction legs for G1-G6;
meta-test refuses any evaluate_g* without a registered failure mode.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 13: Hypothesis property tests

**Files:**
- Create: `tests/test_gate_properties.py`

**Interfaces:**
- Consumes: `evaluate_g1_fpr`, `evaluate_g4_career_drift_monotone`, Task 5's power functions, `original.quantum.typicality.p_far`.

- [ ] **Step 1: Write the property tests**

```python
# tests/test_gate_properties.py
"""
tests/test_gate_properties.py — property-based invariants (Hypothesis) for
gate logic and conformal machinery. These are the "formal-ish spec": each
test states an invariant the code must satisfy on ALL inputs, not one
example.
"""
from __future__ import annotations

from hypothesis import given, settings, strategies as st

from original.quantum.typicality import p_far
from validation.calibration_gate import (
    evaluate_g1_fpr,
    evaluate_g4_career_drift_monotone,
)
from validation.power import band_reachable, conformal_p_floor

_SETTINGS = settings(max_examples=50, deadline=None)

_actions = st.lists(
    st.sampled_from(["no_action", "monitor", "review", "schedule_meeting"]),
    min_size=1,
    max_size=300,
)


class TestG1Properties:
    @_SETTINGS
    @given(_actions)
    def test_verdict_agrees_with_the_rate_arithmetic(self, actions):
        rate = sum(1 for a in actions if a != "no_action") / len(actions)
        result = evaluate_g1_fpr(actions, per_corpus={"c": actions})
        assert result.verdict == ("pass" if rate <= 0.05 else "fail")

    @_SETTINGS
    @given(
        _actions,
        st.dictionaries(
            st.text(min_size=1, max_size=6), st.integers(1, 30),
            min_size=1, max_size=8,
        ),
    )
    def test_never_pass_when_no_entity_can_reach_the_band(self, actions, counts):
        # All counts <= 30 → floor 1/31 ≈ 0.0323 > 0.03 → unreachable for all.
        result = evaluate_g1_fpr(
            actions, per_corpus={"c": actions},
            entity_baseline_counts=counts, band_threshold=0.03,
        )
        assert result.verdict != "pass"

    @_SETTINGS
    @given(_actions, st.integers(34, 500))
    def test_reachability_never_downgrades_a_failure(self, actions, big_n):
        result = evaluate_g1_fpr(
            actions, per_corpus={"c": actions},
            entity_baseline_counts={"e": big_n}, band_threshold=0.03,
        )
        rate = sum(1 for a in actions if a != "no_action") / len(actions)
        if rate > 0.05:
            assert result.verdict == "fail"


class TestConformalProperties:
    @_SETTINGS
    @given(
        st.lists(
            st.floats(0, 100, allow_nan=False, allow_infinity=False),
            min_size=1, max_size=60,
        ),
        st.floats(0, 100, allow_nan=False, allow_infinity=False),
    )
    def test_p_far_respects_the_conformal_floor_and_ceiling(self, loo, r_sub):
        p = p_far(r_sub, loo)
        assert conformal_p_floor(len(loo)) <= p <= 1.0

    @_SETTINGS
    @given(st.integers(1, 1000), st.floats(0.001, 0.5))
    def test_band_reachability_is_monotone_in_n(self, n, threshold):
        if band_reachable(n, threshold):
            assert band_reachable(n + 1, threshold)


class TestG4Properties:
    @_SETTINGS
    @given(st.lists(st.floats(0, 10, allow_nan=False), min_size=3, max_size=3))
    def test_verdict_is_exactly_monotonicity(self, values):
        early, middle, late = values
        result = evaluate_g4_career_drift_monotone(
            {"early": early, "middle": middle, "late": late}
        )
        expected = early <= middle <= late
        assert (result.verdict == "pass") is expected
```

- [ ] **Step 2: Run**

Run: `/Users/andrew/Desktop/Original/.venv/bin/python -m pytest tests/test_gate_properties.py -q`
Expected: PASS. Any counterexample Hypothesis finds is a genuine gate bug —
fix the gate, never the invariant (unless the invariant misstates the
gate's documented contract, in which case fix it against the docstring).

- [ ] **Step 3: Full suite, commit**

```bash
/Users/andrew/Desktop/Original/.venv/bin/python -m pytest tests/ -q
git add tests/test_gate_properties.py
git commit -m "Add Hypothesis property tests for gate invariants and conformal floors

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 14: Layer documentation

**Files:**
- Create: `validation/README.md`

**Interfaces:** none (documentation only).

- [ ] **Step 1: Write the README**

```markdown
# validation/ — the instrumentation & validation layer

The scoring engine answers questions; this layer makes sure the questions
and answers can't get mixed up. Background: the 2026-07-30 Instrument
Report and docs/superpowers/specs/2026-07-31-instrumentation-validation-layer-design.md.

## The rules the layer enforces

1. **Measurability is data** (`measurability.py`). Every feature column is
   measurable / scoring-only / structurally-blank / disabled /
   corpus-limited. Aggregation code calls `assert_aggregatable()` and
   refuses anything non-measurable. A canary test keeps the registry
   honest against the real extraction pipeline.
2. **Power before verdicts** (`power.py`). Conformal p-values floor at
   1/(N+1). A gate whose criterion is unreachable at the current corpus
   size reports UNINFORMATIVE, not PASS. `calibration_gate --strict`
   treats uninformative as failure — use it before quoting results.
3. **Reports carry their spec** (`experiment.py`). Every runner embeds
   task / git SHA / seed / env lock / corpus composition / windowing /
   thresholds under `"experiment"`. `diff_specs()` explains disagreeing
   runs and refuses cross-task comparisons.
4. **Corpus floors are policy** (`corpus_policy.py`, `manifest_schema.py`).
   Verification: >= 300 words. Attribution: >= 500 words AND >= 3 baseline
   docs per candidate; short texts are verification-only. Manifest entries
   carry genre and provenance (real_historical / synthetic_ai /
   student_pilot).
5. **Attribution is an ensemble** (`attribution/`). Deviation-calibrated,
   cosine-delta, and MFW-Delta engines run on identical held-out essays;
   2-of-3 agreement attributes, disagreement routes to manual review.
6. **Gates must be able to fail** (`gate_contracts.py`,
   tests/test_gate_falsifiability.py). Every gate registers a failure
   witness and (where meaningful) a label-destruction leg. A gate without
   a registered failure mode fails the suite.

## Running

    # fast unit layer (part of the main suite)
    .venv/bin/python -m pytest tests/ -q

    # gate battery (slow, corpus-driven; --strict before quoting numbers)
    .venv/bin/python -m validation.calibration_gate --strict

    # attribution benchmark, three engines side by side
    .venv/bin/python -m validation.public_authors.run

Weights remain HELD: nothing here writes to original/constants.py.
```

- [ ] **Step 2: Commit**

```bash
git add validation/README.md
git commit -m "Add validation/README.md documenting the instrumentation layer

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 15: Reconcile CLAUDE.md with the merged reality

**Files:**
- Modify: `CLAUDE.md` (Feature dimensionality, Key Architecture, Feature Dimensions sections)

**Interfaces:** none (documentation only).

**Why this task exists:** Task 1's merge brings Tier 18 (uniformity, 6
features) from the plato branch, which never updated `CLAUDE.md`. The moment
that merge lands, the project's own instruction file is wrong in three
places — and it is the file every future session reads first. Verified
2026-07-31: `constants.py` on the plato branch has `FEATURE_DIM = 109` and
`BASE_FEATURE_DIM = 102`, while `CLAUDE.md` still says 103 and 96.

- [ ] **Step 1: Confirm the post-merge numbers from the code, not from this plan**

```bash
/Users/andrew/Desktop/Original/.venv/bin/python -c "
from original.constants import ALL_FEATURE_CODES, BASE_FEATURE_CODES, FEATURE_TIER, DISABLED_FEATURE_GROUPS, FEATURE_GROUPS
disabled = {c for g in DISABLED_FEATURE_GROUPS for c in FEATURE_GROUPS.get(g, [])}
print('FEATURE_DIM      =', len(ALL_FEATURE_CODES))
print('BASE_FEATURE_DIM =', len(BASE_FEATURE_CODES))
print('tiers            =', len(set(FEATURE_TIER.values())))
print('disabled groups  =', sorted(DISABLED_FEATURE_GROUPS), '->', len(disabled), 'features')
print('active           =', len(ALL_FEATURE_CODES) - len(disabled))
"
```

Use the printed values in Step 2 — do not copy numbers from this plan.

- [ ] **Step 2: Update the three stale sections**

1. **Feature dimensionality** (~line 86): `103 dimensional / **97 active**`
   → the measured values; add Tier 18 (uniformity, 6 features) to the
   `DISABLED_FEATURE_GROUPS` sentence alongside Tier 17; update
   `BASE_FEATURE_DIM = 96` (~line 96) to the measured value and drop the
   stale `constants.py:222` line reference.
2. **Key Architecture** (~lines 104, 110): `103-feature pipeline` and
   `103 features across 17 tiers` → measured values / 18 tiers.
3. **Feature Dimensions** (~line 132): `FEATURE_DIM = 103 (current)` →
   measured value.

- [ ] **Step 3: Document the validation layer's standing rules**

Add a section after **Testing**:

```markdown
## Validation Layer
`validation/` enforces instrument hygiene — see `validation/README.md`.
The rules that bite during development:
- Aggregating over a feature column requires it to be MEASURABLE in
  `validation/measurability.py`; blank/scoring-only columns raise.
- Gate verdicts are three-valued: `pass` / `fail` / `uninformative`. A gate
  whose criterion is unreachable at the current N reports uninformative —
  never quote it as a pass. Run
  `python -m validation.calibration_gate --strict` before citing results.
- Every new gate needs a failure witness in `validation/gate_contracts.py`
  or `tests/test_gate_falsifiability.py` fails.
- Corpus floors: verification >= 300 words; attribution >= 500 words and
  >= 3 baseline docs per candidate.
```

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md
git commit -m "Fix stale feature counts in CLAUDE.md; document the validation layer

Tier 18 landed with the instrument-branch merge: FEATURE_DIM 103 -> 109,
BASE_FEATURE_DIM 96 -> 102, 17 -> 18 tiers.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

## Deferred (separate plan when prioritized)

- **Synthetic-author E2E harness** (design spec C7): parametric authors +
  corruption ladder. Independent subsystem; write its own plan.
- **sklearn multi-class engine**: designed as a flagged fourth engine;
  defer until the three-engine table has been read (open decision #4).
- **Separate API endpoints** for verification/attribution/drift: product
  change, out of scope (design spec non-goals).

## Open decision for the user: CI coverage

`.github/workflows/test.yml` has two jobs — `lint` (ruff, **scoped to
`original/`**) and `pytest` (`tests/` + `validation/test_tier10_optional.py`,
`--cov=original --cov-fail-under=78`). Consequences worth a decision:

1. **The corpus gate battery never runs in CI.** Tasks 12–13's falsifiability
   and property tests DO run (they are pure-logic tests in `tests/`), so
   "a gate that cannot fail" is caught automatically. But G1–G6 *results* are
   regenerated only when someone runs the runner by hand, and nothing ever
   invokes `--strict`. Options: (a) leave manual and rely on the fast
   falsifiability layer — recommended, since the battery scores three corpora
   in-process and would dominate a 20-minute CI budget; (b) add a nightly
   `validation` job running `python -m validation.calibration_gate --strict`.
   Do not add it to the per-push `pytest` job either way.
2. **New `validation/` and `tests/` code is not lint-gated.** ruff is scoped
   to `original/` in both CI and `.pre-commit-config.yaml` (deliberate — those
   trees were never swept, per the config's comment). This plan adds ~1,000
   lines outside that scope. Recommendation: leave the scope alone and run
   `ruff check validation/ tests/ --no-fix` manually before the final commit
   rather than widening the gate and inheriting legacy debt.
3. **Coverage floor is safe.** `--cov=original` measures only the product
   package, which this plan does not modify; the new tests import and execute
   `original.*` modules, so coverage can only rise.

## Self-Review Notes

- Spec coverage: C1→Tasks 2–4, C2→Tasks 5–6, C3→Task 7, C4→Task 8,
  C5→Tasks 9–11, C6→Tasks 12–13; Phase 0→Task 1; docs→Tasks 14–15; C7
  explicitly deferred.
- All commands use the absolute venv path; the worktree has no `.venv`.
- Tasks 6, 8 (run.py wiring), 11, and 12 touch files owned by the moving
  plato branch — each carries a re-verify step and symbol anchors instead
  of line numbers.
- **Second-pass corrections (2026-07-31), after verifying against the plato
  branch tip `34d8ceb6`:**
  - Task 4 named a variable `_FEATURE_INDICES`; the real symbol is
    `_FEATURE_INDICES_MEASURED` (`stability.py:51`, consumed at `:189`).
    Following the draft literally would have raised `NameError` on import.
  - Tasks 5/6/11 gained Wilson intervals and `bar_decidable`: the first draft
    applied the "every number carries its floor given N" rule only to G1's
    conformal floor and missed G3, whose *pass* is undemonstrable at n=22
    ([0.615, 0.927] for the 0.818 diagnostic straddles the 0.7 bar).
  - Task 8 gained `check_genre_balance`: the draft recorded corpus
    composition in the ExperimentSpec but never checked it, leaving the
    advisory's lead complaint as a prose caveat.
  - Task 15 added: Task 1's merge silently makes `CLAUDE.md` wrong
    (103→109 features, 96→102 base dim, 17→18 tiers).
```
