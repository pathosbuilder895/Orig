# Short-Baseline Scoring Adaptation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make same-author recognition work at the realistic student operating point — a baseline of ~3 essays × 500 words — measured as impostor catch rate at a fixed ≤5% false-flag budget.

**Architecture:** A new measurement harness (`validation/short_regime/`) establishes the floor at the operating point, then a 16-combo grid measures the four dormant levers that already exist in the codebase (`LENGTH_ADAPTIVE_WEIGHTS`, `RANK_REMEDIATION=shrinkage`, `BAYESIAN_PRIOR_ENABLED`, `NULL_MODEL=impostor`). Only after the grid do contingent product changes land (cohort-prior fallback, percentile calibration), each behind a new default-OFF env flag. Scoring calls `StudentState` + `score()` directly — no server, no DB.

**Tech Stack:** Python 3 (`.venv/bin/python` ONLY), numpy, pytest, existing `original.quantum` / `original.features` modules.

## Global Constraints

- Always `.venv/bin/python` and `.venv/bin/pytest` — system python3 has a broken pydantic_settings.
- All behavior changes ship behind env flags, **default OFF**; flags-off scoring must stay byte-identical (project rule, verified in Task 9).
- Never reorder `ALL_FEATURE_CODES` or touch `NORM_BOUNDS` (requires explicit user permission).
- `ACTION_THRESHOLDS` in `original/constants.py:652` is publish-synced to README.md, MODEL_CARD.md, OWNERS_MANUAL.md — Task 8 produces a **proposal doc only**; changing the constant requires explicit user permission.
- Operating point everywhere: baseline = 3 samples × 500 words, probes = 500 words, `n_tokens=500` (inside the `short` bucket, `LENGTH_BUCKETS_BY_TOKENS` = 0–750, `constants.py:292`).
- Success metric: impostor catch rate at ≤5% false-flag budget (threshold = 95th percentile of honest scores), with AUC and bootstrap CIs reported alongside.
- Commit style: `Add ...`/`Fix ...`, co-author line `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`.
- Deterministic: every random draw takes an explicit seed; no wall-clock in outputs except report filenames.

## Background for the implementer (read once)

Why short baselines fail today, from the code:

1. `StudentState.baseline_std` (`original/quantum/state.py:235`) floors per-feature σ at `0.15/√N` — at N=3 that's 0.087, a *uniform* floor. It stops z-score explosions but is uninformed: a feature whose true cohort σ is 0.02 and one whose σ is 0.20 get the same treatment.
2. The density matrix ρ from 3 samples is rank-3 in a 96-dim space. `RANK_REMEDIATION=shrinkage` (`original/quantum/state.py:190`, read from `os.environ` at ρ-build time) blends toward isotropic via Ledoit-Wolf — built for this, never measured at this operating point.
3. `BAYESIAN_PRIOR_ENABLED` (`original/quantum/scoring.py:532`) blends student μ/σ with a cross-student prior, α = N/(N+PRIOR_WEIGHT) — exactly hierarchical shrinkage — but only fires if the last baseline sample has a non-None `genre` AND the caller passes `ScoringConfig.genre_stats`. The harness must supply both.
4. `LENGTH_ADAPTIVE_WEIGHTS` (`original/quantum/scoring.py:553` area) rescales tier weights per length bucket. The `short` schedule was normalized so Σ(w²) is preserved (see comment at `constants.py:298` and the 2026-06-30 seminary lift incident) — read that comment before touching any weight math.
5. Prior session measurement (2026-07-29, Lewis/Chesterton length sweep): with 4×1300-word baselines, same-author vs other-author separation margin is **negative until ~6,000-word samples**. The 3×500 regime is harder still. Expect the flags-off baseline run to look bad; that's the point of measuring it.

Key call signatures used throughout (verify once against source, then trust the plan):

```python
from original.features.pipeline import feature_vector, extract_features
# feature_vector(text: str) -> np.ndarray shape (FEATURE_DIM,)
# extract_features(text: str) -> dict[str, float]

from original.quantum.state import StudentState, BaselineSample
# StudentState(student_id=str); .add_sample(BaselineSample(text=..., vector=...,
#     provenance="verified", auth_weight=1.0, genre="essay"))

from original.quantum.scoring import score as quantum_score, ScoringConfig
# quantum_score(state=, submission_vector=, feature_dict=, submission_id=,
#     n_tokens=int, impostor_stats=None|(mu,sigma), scoring_config=ScoringConfig(...))
#   -> Layer7Output; result.authorship.deviation_score: float
#   -> result.authorship.llr_deviation_score: float|None (only when
#      scoring_config.null_model=="impostor" AND impostor_stats supplied)
# ScoringConfig(bayesian_prior_enabled=, prior_weight=, length_adaptive_weights=,
#     null_model=, genre_stats={"mean": nd, "std": nd, "n_samples": int})
```

## File Structure

```
validation/short_regime/
  __init__.py            # empty
  stats.py               # catch@budget, AUC, bootstrap CI — pure numpy, no original.* imports
  corpus.py              # operating-point trials from validation/corpus (no network)
  runner.py              # trials × lever-combo -> score rows; owns all env/flag handling
  report.py              # rows -> report.json + report.md
tests/
  test_short_regime_stats.py
  test_short_regime_corpus.py
  test_short_regime_runner.py
docs/calibration/
  short_regime_thresholds_<date>.md    # Task 8 output (proposal only)
```

Tasks 6–7 additionally touch `original/routers/students_scoring.py`, `original/store.py`, `original/quantum/scoring.py` — **contingent tasks**, see the decision gate after Task 5.

---

### Task 1: Statistics module

**Files:**
- Create: `validation/short_regime/__init__.py` (empty)
- Create: `validation/short_regime/stats.py`
- Test: `tests/test_short_regime_stats.py`

**Interfaces:**
- Consumes: nothing (numpy only)
- Produces:
  - `CatchResult` dataclass: `threshold: float, catch_rate: float, false_flag_rate: float, n_honest: int, n_impostor: int`
  - `catch_at_budget(honest: np.ndarray, impostor: np.ndarray, budget: float = 0.05) -> CatchResult`
  - `auc(honest: np.ndarray, impostor: np.ndarray) -> float`
  - `bootstrap_ci(honest, impostor, metric: str, n_boot: int = 1000, seed: int = 0) -> tuple[float, float]` where metric ∈ {"auc", "catch"}

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_short_regime_stats.py
import numpy as np
import pytest

from validation.short_regime.stats import CatchResult, auc, bootstrap_ci, catch_at_budget


def test_auc_perfect_separation():
    honest = np.array([0.1, 0.2, 0.3])
    impostor = np.array([0.7, 0.8, 0.9])
    assert auc(honest, impostor) == 1.0


def test_auc_no_separation():
    rng = np.random.default_rng(0)
    x = rng.uniform(size=500)
    y = rng.uniform(size=500)
    assert abs(auc(x, y) - 0.5) < 0.05


def test_auc_ties_count_half():
    assert auc(np.array([0.5]), np.array([0.5])) == 0.5


def test_catch_at_budget_known_quantile():
    # honest = 0.00..0.99; 95th percentile threshold ~0.95
    honest = np.arange(100) / 100.0
    impostor = np.array([0.90, 0.96, 0.97, 0.98])  # 3 of 4 above threshold
    r = catch_at_budget(honest, impostor, budget=0.05)
    assert isinstance(r, CatchResult)
    assert 0.94 <= r.threshold <= 0.96
    assert r.catch_rate == 0.75
    assert r.false_flag_rate <= 0.05
    assert r.n_honest == 100 and r.n_impostor == 4


def test_catch_empty_impostor_raises():
    with pytest.raises(ValueError):
        catch_at_budget(np.array([0.1]), np.array([]))


def test_bootstrap_ci_brackets_point_estimate_and_is_deterministic():
    rng = np.random.default_rng(1)
    honest = rng.normal(0.4, 0.05, 200)
    impostor = rng.normal(0.7, 0.05, 200)
    lo, hi = bootstrap_ci(honest, impostor, metric="auc", n_boot=200, seed=42)
    point = auc(honest, impostor)
    assert lo <= point <= hi
    assert (lo, hi) == bootstrap_ci(honest, impostor, metric="auc", n_boot=200, seed=42)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_short_regime_stats.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'validation.short_regime'`

- [ ] **Step 3: Implement stats.py**

```python
# validation/short_regime/stats.py
"""Pure-numpy metrics for the short-baseline operating-point harness.

No I/O, no original.* imports — unit-testable in CI without any corpus.
Deviation convention: LOWER = more same-author-like, so an impostor is
"caught" when its score is ABOVE the honest-quantile threshold.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class CatchResult:
    threshold: float
    catch_rate: float
    false_flag_rate: float
    n_honest: int
    n_impostor: int


def auc(honest: np.ndarray, impostor: np.ndarray) -> float:
    """P(random impostor scores above random honest); ties count 1/2."""
    honest = np.asarray(honest, dtype=float)
    impostor = np.asarray(impostor, dtype=float)
    if honest.size == 0 or impostor.size == 0:
        raise ValueError("auc needs non-empty honest and impostor arrays")
    wins = (impostor[:, None] > honest[None, :]).sum()
    ties = (impostor[:, None] == honest[None, :]).sum()
    return float((wins + 0.5 * ties) / (impostor.size * honest.size))


def catch_at_budget(
    honest: np.ndarray, impostor: np.ndarray, budget: float = 0.05
) -> CatchResult:
    """Threshold = (1-budget) quantile of honest; catch = frac impostors above."""
    honest = np.asarray(honest, dtype=float)
    impostor = np.asarray(impostor, dtype=float)
    if honest.size == 0 or impostor.size == 0:
        raise ValueError("catch_at_budget needs non-empty honest and impostor arrays")
    thr = float(np.quantile(honest, 1.0 - budget, method="higher"))
    return CatchResult(
        threshold=thr,
        catch_rate=float((impostor > thr).mean()),
        false_flag_rate=float((honest > thr).mean()),
        n_honest=int(honest.size),
        n_impostor=int(impostor.size),
    )


def bootstrap_ci(
    honest: np.ndarray,
    impostor: np.ndarray,
    metric: str,
    n_boot: int = 1000,
    seed: int = 0,
    budget: float = 0.05,
) -> tuple[float, float]:
    """Percentile-bootstrap 95% CI over resampled honest AND impostor sets."""
    honest = np.asarray(honest, dtype=float)
    impostor = np.asarray(impostor, dtype=float)
    rng = np.random.default_rng(seed)
    vals = np.empty(n_boot)
    for b in range(n_boot):
        h = honest[rng.integers(0, honest.size, honest.size)]
        i = impostor[rng.integers(0, impostor.size, impostor.size)]
        vals[b] = auc(h, i) if metric == "auc" else catch_at_budget(h, i, budget).catch_rate
    return float(np.quantile(vals, 0.025)), float(np.quantile(vals, 0.975))
```

Also create empty `validation/short_regime/__init__.py`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_short_regime_stats.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add validation/short_regime/__init__.py validation/short_regime/stats.py tests/test_short_regime_stats.py
git commit -m "Add short-regime stats module: catch@budget, AUC, bootstrap CI

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 2: Operating-point corpus assembly

**Files:**
- Create: `validation/short_regime/corpus.py`
- Test: `tests/test_short_regime_corpus.py`

**Interfaces:**
- Consumes: text files under `validation/corpus/` (already committed: `seminary_01..05_*.txt` — 5 essays each; `burke_*.txt` ×173, `douglass_*.txt` ×173, `lincoln_*.txt` ×101, `paine_*.txt` ×125; `ai_*.txt` ×20, `ghost_*.txt` ×5)
- Produces:
  - `Trial` dataclass: `student_id: str, baseline: list[str] (len 3), honest: list[str]`
  - `build_pools(corpus_dir: Path, words: int = 500) -> dict[str, list[str]]` — author id → non-overlapping `words`-word chunks
  - `build_trials(pools: dict, n_baseline: int = 3, max_honest: int = 30, seed: int = 7) -> list[Trial]`
  - `attack_probes(corpus_dir: Path, words: int = 500) -> dict[str, list[str]]` — `{"ai": [...], "ghost": [...]}`

**Design notes for the implementer:**
- One author = one pseudo-student. Baseline chunks and honest chunks must never overlap (disjoint slices of the concatenation).
- Word-slice chunking is fine here (harness, not product). Drop trailing chunk if < `words`.
- Authors: `["seminary_01".."seminary_05", "burke", "douglass", "lincoln", "paine"]`. Seminary pools = concatenation of that student's 5 essays; big authors = concatenation of all their files in sorted filename order (sorted = deterministic).
- Impostor probes are NOT built here — the runner scores author A's honest chunks against author B's state, so every honest chunk doubles as an impostor probe cross-author. `ai_*`/`ghost_*` are separate labeled attack probes against seminary students only.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_short_regime_corpus.py
from pathlib import Path

import pytest

from validation.short_regime.corpus import Trial, attack_probes, build_pools, build_trials

CORPUS = Path(__file__).resolve().parent.parent / "validation" / "corpus"
pytestmark = pytest.mark.skipif(not CORPUS.exists(), reason="validation corpus absent")


def test_pools_have_expected_authors_and_chunk_sizes():
    pools = build_pools(CORPUS, words=500)
    for author in ["seminary_01", "seminary_05", "burke", "douglass", "lincoln", "paine"]:
        assert author in pools, author
        assert all(len(c.split()) == 500 for c in pools[author])
    assert len(pools["burke"]) > 50          # 173 docs -> plenty of chunks
    assert len(pools["seminary_01"]) >= 4    # 5 essays -> at least 3 baseline + 1 honest


def test_trials_disjoint_and_deterministic():
    pools = build_pools(CORPUS, words=500)
    t1 = build_trials(pools, n_baseline=3, max_honest=30, seed=7)
    t2 = build_trials(pools, n_baseline=3, max_honest=30, seed=7)
    assert [t.student_id for t in t1] == [t.student_id for t in t2]
    for tr in t1:
        assert len(tr.baseline) == 3
        assert 1 <= len(tr.honest) <= 30
        assert set(tr.baseline).isdisjoint(set(tr.honest))
        assert t2[[x.student_id for x in t2].index(tr.student_id)].baseline == tr.baseline


def test_attack_probes_labeled():
    atk = attack_probes(CORPUS, words=500)
    assert set(atk) == {"ai", "ghost"}
    assert len(atk["ai"]) >= 10
    assert all(len(c.split()) == 500 for v in atk.values() for c in v)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_short_regime_corpus.py -v`
Expected: FAIL — `ImportError: cannot import name 'Trial'`

- [ ] **Step 3: Implement corpus.py**

```python
# validation/short_regime/corpus.py
"""Assemble operating-point trials from the committed validation corpus.

One author = one pseudo-student. Baseline and honest chunks are disjoint
slices of the author's concatenated text. Impostor scoring is done by the
runner (author A's honest chunks scored against author B's baseline), so
this module only produces same-author material plus labeled attack probes.
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from pathlib import Path

SEMINARY = [f"seminary_{i:02d}" for i in range(1, 6)]
BIG_AUTHORS = ["burke", "douglass", "lincoln", "paine"]


@dataclass(frozen=True)
class Trial:
    student_id: str
    baseline: list[str]
    honest: list[str]


def _chunks(text: str, words: int) -> list[str]:
    w = text.split()
    return [
        " ".join(w[i : i + words])
        for i in range(0, len(w) - words + 1, words)
    ]


def _author_text(corpus_dir: Path, prefix: str) -> str:
    files = sorted(corpus_dir.glob(f"{prefix}_*.txt"))
    return "\n".join(f.read_text(encoding="utf-8") for f in files)


def build_pools(corpus_dir: Path, words: int = 500) -> dict[str, list[str]]:
    pools: dict[str, list[str]] = {}
    for author in SEMINARY + BIG_AUTHORS:
        cs = _chunks(_author_text(corpus_dir, author), words)
        if len(cs) >= 4:  # need 3 baseline + >=1 honest
            pools[author] = cs
    return pools


def build_trials(
    pools: dict[str, list[str]],
    n_baseline: int = 3,
    max_honest: int = 30,
    seed: int = 7,
) -> list[Trial]:
    trials = []
    for author in sorted(pools):
        cs = pools[author]
        rng = random.Random(f"{seed}:{author}")
        idx = list(range(len(cs)))
        rng.shuffle(idx)
        base_idx = idx[:n_baseline]
        honest_idx = idx[n_baseline : n_baseline + max_honest]
        trials.append(
            Trial(
                student_id=author,
                baseline=[cs[i] for i in base_idx],
                honest=[cs[i] for i in honest_idx],
            )
        )
    return trials


def attack_probes(corpus_dir: Path, words: int = 500) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for kind in ("ai", "ghost"):
        text = _author_text(corpus_dir, kind)
        out[kind] = _chunks(text, words)
    return out
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_short_regime_corpus.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add validation/short_regime/corpus.py tests/test_short_regime_corpus.py
git commit -m "Add short-regime corpus assembly: 9 pseudo-students at 3x500-word operating point

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 3: Runner and report — flags-off floor measurement

**Files:**
- Create: `validation/short_regime/runner.py`
- Create: `validation/short_regime/report.py`
- Test: `tests/test_short_regime_runner.py`

**Interfaces:**
- Consumes: `Trial`, `build_pools`, `build_trials`, `attack_probes` (Task 2); `catch_at_budget`, `auc`, `bootstrap_ci` (Task 1); `feature_vector`, `StudentState`, `BaselineSample`, `quantum_score`, `ScoringConfig` (existing).
- Produces:
  - `LeverCombo` dataclass: `length_adaptive: bool, rank_shrinkage: bool, cohort_prior: bool, decision_stat: str` (`"deviation"` or `"llr"`), plus `.name` property like `"LAW+SHRINK"` / `"OFF"`
  - `build_state(trial: Trial, combo: LeverCombo) -> StudentState`
  - `cohort_stats(trials: list[Trial], exclude: str) -> dict` — `{"mean": nd, "std": nd, "n_samples": int}` from all OTHER trials' baseline vectors
  - `run_combo(trials, attacks, combo, budget=0.05) -> dict` — the full result block for one combo
  - CLI: `python -m validation.short_regime.runner --combo off [--report-dir DIR]`

**Critical implementation facts:**
- `RANK_REMEDIATION` is read from `os.environ` inside `StudentState._build_density_matrix` (`state.py:190`) — set/unset it in `build_state` BEFORE the first `density_matrix` access, and build states fresh per combo (never reuse a state across combos; ρ may be cached).
- The Bayesian prior needs `BaselineSample(..., genre="essay")` set (gate at `scoring.py:~545` checks `state.samples[-1].genre`) AND `ScoringConfig(genre_stats=...)`. The harness passes cohort stats (genre-agnostic) — document in the report that this stands in for `store.get_genre_stats`.
- `decision_stat="llr"` requires `null_model="impostor"` in ScoringConfig AND `impostor_stats=(mu, sigma)` passed to `quantum_score`; the score to analyze is then `authorship.llr_deviation_score` (fall back to `deviation_score` if None and count the fallbacks in the report).
- Feature vectors are expensive (~1-2 s/chunk): extract each unique chunk ONCE, cache in a dict keyed by `id(text)`-safe hash, reuse across combos.
- Keep `CONTEXT_MANIFEST_ENABLED=0`, `ADAPTIVE_WEIGHTS_ENABLED=0` for the whole harness (the Lewis run showed the adaptive path degrades separation; it is out of scope here).

- [ ] **Step 1: Write the failing test** (uses 2 tiny fabricated trials — no corpus needed, runs in CI)

```python
# tests/test_short_regime_runner.py
import numpy as np

from validation.short_regime.corpus import Trial
from validation.short_regime.runner import LeverCombo, build_state, cohort_stats, run_combo

WORDS_A = ("the quick brown fox jumps over the lazy dog and then rests quietly " * 50)
WORDS_B = ("epistemology notwithstanding the categorical imperative demands rigorous scrutiny always " * 50)


def _trial(sid, text):
    c = text.split()
    mk = lambda i: " ".join(c[i * 400 : (i + 1) * 400])
    return Trial(student_id=sid, baseline=[mk(0), mk(1), mk(2)], honest=[mk(3)])


def test_build_state_has_three_samples_and_genre():
    t = _trial("a", WORDS_A)
    s = build_state(t, LeverCombo(False, False, False, "deviation"))
    assert s.sample_count == 3
    assert s.samples[-1].genre == "essay"


def test_cohort_stats_excludes_self():
    trials = [_trial("a", WORDS_A), _trial("b", WORDS_B)]
    cs = cohort_stats(trials, exclude="a")
    assert cs["n_samples"] == 3          # only b's 3 baseline vectors
    assert cs["mean"].shape == cs["std"].shape


def test_run_combo_off_produces_metrics():
    trials = [_trial("a", WORDS_A), _trial("b", WORDS_B)]
    out = run_combo(trials, attacks={}, combo=LeverCombo(False, False, False, "deviation"))
    assert out["combo"] == "OFF"
    assert out["n_honest"] == 2 and out["n_impostor"] == 2
    assert 0.0 <= out["auc"] <= 1.0
    assert "catch_rate" in out and "threshold" in out
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_short_regime_runner.py -v`
Expected: FAIL — `ModuleNotFoundError` / `ImportError` on runner

- [ ] **Step 3: Implement runner.py**

```python
# validation/short_regime/runner.py
"""Score operating-point trials under a lever combo.

Honest score  = trial's own honest chunk vs its own state.
Impostor score = another trial's honest chunk vs this state (all cross pairs).
Attack score  = ai/ghost chunk vs each seminary state (labeled separately).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np

_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_ROOT))

from original.features.pipeline import extract_features, feature_vector  # noqa: E402
from original.quantum.scoring import ScoringConfig                       # noqa: E402
from original.quantum.scoring import score as quantum_score              # noqa: E402
from original.quantum.state import BaselineSample, StudentState          # noqa: E402

from .corpus import Trial, attack_probes, build_pools, build_trials      # noqa: E402
from .stats import auc, bootstrap_ci, catch_at_budget                    # noqa: E402

N_TOKENS = 500
_VEC_CACHE: dict[str, tuple[np.ndarray, dict]] = {}


@dataclass(frozen=True)
class LeverCombo:
    length_adaptive: bool
    rank_shrinkage: bool
    cohort_prior: bool
    decision_stat: str  # "deviation" | "llr"

    @property
    def name(self) -> str:
        parts = [
            "LAW" if self.length_adaptive else "",
            "SHRINK" if self.rank_shrinkage else "",
            "PRIOR" if self.cohort_prior else "",
            "LLR" if self.decision_stat == "llr" else "",
        ]
        return "+".join(p for p in parts if p) or "OFF"


def _features(text: str) -> tuple[np.ndarray, dict]:
    key = hashlib.sha256(text.encode()).hexdigest()
    if key not in _VEC_CACHE:
        _VEC_CACHE[key] = (feature_vector(text), extract_features(text))
    return _VEC_CACHE[key]


def build_state(trial: Trial, combo: LeverCombo) -> StudentState:
    # RANK_REMEDIATION is read from os.environ inside _build_density_matrix —
    # set it BEFORE the first density_matrix access, fresh state per combo.
    if combo.rank_shrinkage:
        os.environ["RANK_REMEDIATION"] = "shrinkage"
    else:
        os.environ.pop("RANK_REMEDIATION", None)
    state = StudentState(student_id=trial.student_id)
    for t in trial.baseline:
        vec, _ = _features(t)
        state.add_sample(
            BaselineSample(
                text=t, vector=vec, provenance="verified",
                auth_weight=1.0, genre="essay",
            )
        )
    return state


def cohort_stats(trials: list[Trial], exclude: str) -> dict:
    vecs = [
        _features(t)[0]
        for tr in trials if tr.student_id != exclude
        for t in tr.baseline
    ]
    V = np.stack(vecs)
    return {
        "mean": V.mean(axis=0),
        "std": np.maximum(V.std(axis=0), 0.005),
        "n_samples": len(vecs),
    }


def _score(state, text, sid, combo, cstats) -> tuple[float, bool]:
    vec, fd = _features(text)
    cfg = ScoringConfig(
        bayesian_prior_enabled=combo.cohort_prior,
        prior_weight=3.0,
        length_adaptive_weights=combo.length_adaptive,
        null_model="impostor" if combo.decision_stat == "llr" else "none",
        genre_stats=cstats if combo.cohort_prior else None,
    )
    imp = (cstats["mean"], cstats["std"]) if combo.decision_stat == "llr" else None
    res = quantum_score(
        state=state, submission_vector=vec, feature_dict=fd,
        submission_id=sid, n_tokens=N_TOKENS,
        impostor_stats=imp, scoring_config=cfg,
    )
    a = res.authorship
    if combo.decision_stat == "llr" and a.llr_deviation_score is not None:
        return float(a.llr_deviation_score), False
    return float(a.deviation_score), combo.decision_stat == "llr"


def run_combo(trials, attacks, combo: LeverCombo, budget: float = 0.05) -> dict:
    honest, impostor, attack_rows, llr_fallbacks = [], [], [], 0
    for tr in trials:
        state = build_state(tr, combo)
        cstats = cohort_stats(trials, exclude=tr.student_id)
        for j, h in enumerate(tr.honest):
            d, fb = _score(state, h, f"h:{tr.student_id}:{j}", combo, cstats)
            honest.append(d); llr_fallbacks += fb
        for other in trials:
            if other.student_id == tr.student_id:
                continue
            for j, h in enumerate(other.honest[:5]):  # cap: 5 impostor probes/pair
                d, fb = _score(state, h, f"i:{other.student_id}->{tr.student_id}:{j}", combo, cstats)
                impostor.append(d); llr_fallbacks += fb
        if tr.student_id.startswith("seminary"):
            for kind, chunks in attacks.items():
                for j, c in enumerate(chunks[:5]):
                    d, fb = _score(state, c, f"{kind}:{tr.student_id}:{j}", combo, cstats)
                    attack_rows.append({"kind": kind, "target": tr.student_id, "score": d})
                    llr_fallbacks += fb
    h, i = np.array(honest), np.array(impostor)
    cr = catch_at_budget(h, i, budget)
    return {
        "combo": combo.name,
        "n_honest": len(honest), "n_impostor": len(impostor),
        "auc": round(auc(h, i), 4),
        "auc_ci": [round(x, 4) for x in bootstrap_ci(h, i, "auc", seed=42)],
        "threshold": round(cr.threshold, 4),
        "catch_rate": round(cr.catch_rate, 4),
        "catch_ci": [round(x, 4) for x in bootstrap_ci(h, i, "catch", seed=42)],
        "false_flag_rate": round(cr.false_flag_rate, 4),
        "honest_scores": [round(x, 4) for x in honest],
        "impostor_scores": [round(x, 4) for x in impostor],
        "attacks": attack_rows,
        "llr_fallbacks": llr_fallbacks,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--combo", default="off", help="'off' or 'grid' (Task 4)")
    ap.add_argument("--report-dir", default=None)
    args = ap.parse_args(argv)
    os.environ["CONTEXT_MANIFEST_ENABLED"] = "0"
    os.environ["ADAPTIVE_WEIGHTS_ENABLED"] = "0"

    corpus_dir = _ROOT / "validation" / "corpus"
    pools = build_pools(corpus_dir)
    trials = build_trials(pools)
    attacks = attack_probes(corpus_dir)
    print(f"{len(trials)} pseudo-students; honest probes: "
          f"{sum(len(t.honest) for t in trials)}", file=sys.stderr)

    combos = [LeverCombo(False, False, False, "deviation")]
    if args.combo == "grid":
        combos = [
            LeverCombo(law, shr, pri, ds)
            for law in (False, True) for shr in (False, True)
            for pri in (False, True) for ds in ("deviation", "llr")
        ]
    results = []
    for c in combos:
        t0 = time.perf_counter()
        r = run_combo(trials, attacks, c)
        r["elapsed_s"] = round(time.perf_counter() - t0, 1)
        print(f"  {r['combo']:22s} AUC={r['auc']:.3f} "
              f"catch@5%={r['catch_rate']:.3f}", file=sys.stderr)
        results.append(r)

    from .report import write_report
    out = Path(args.report_dir) if args.report_dir else (
        _ROOT / "validation" / "benchmarks" / time.strftime("%Y-%m-%d") / "short_regime"
    )
    write_report(out, results)
    print(f"reports -> {out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Implement report.py**

```python
# validation/short_regime/report.py
"""Write short-regime results as report.json + report.md."""
from __future__ import annotations

import json
from pathlib import Path


def write_report(out_dir: Path, results: list[dict]) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "report.json").write_text(json.dumps(results, indent=2))
    lines = [
        "# Short-regime operating point (3×500-word baseline, 500-word probes)",
        "",
        "| combo | AUC | AUC 95% CI | catch@5% | catch CI | threshold | llr fallbacks |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in sorted(results, key=lambda r: -r["catch_rate"]):
        lines.append(
            f"| {r['combo']} | {r['auc']:.3f} | {r['auc_ci'][0]:.3f}–{r['auc_ci'][1]:.3f} "
            f"| {r['catch_rate']:.3f} | {r['catch_ci'][0]:.3f}–{r['catch_ci'][1]:.3f} "
            f"| {r['threshold']:.3f} | {r['llr_fallbacks']} |"
        )
    (out_dir / "report.md").write_text("\n".join(lines) + "\n")
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_short_regime_runner.py -v`
Expected: 3 passed (each test takes ~10–30 s — feature extraction is real)

- [ ] **Step 6: Run the flags-off floor measurement (the real corpus)**

Run: `cd ~/Desktop/Original && .venv/bin/python -m validation.short_regime.runner --combo off`
Expected: stderr shows 9 pseudo-students, one `OFF` result line, and a report path. Record the AUC and catch@5% — this is the number every later change is judged against. Sanity checks: `false_flag_rate <= 0.05`; `n_impostor > n_honest`.

- [ ] **Step 7: Commit**

```bash
git add validation/short_regime/runner.py validation/short_regime/report.py tests/test_short_regime_runner.py
git commit -m "Add short-regime runner + flags-off floor measurement at 3x500 operating point

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 4: The 16-combo lever grid

**Files:**
- Modify: `validation/short_regime/runner.py` (no code change needed — `--combo grid` already implemented in Task 3)
- Create: `validation/benchmarks/<date>/short_regime/` output (gitignored except via explicit add below)

**Interfaces:**
- Consumes: everything from Task 3.
- Produces: the grid report — the decision input for Tasks 6–8.

- [ ] **Step 1: Run the grid**

Run: `cd ~/Desktop/Original && .venv/bin/python -m validation.short_regime.runner --combo grid`
Expected: 16 result lines. Runtime estimate: ~9 states × ~300 unique probe texts, vectors cached after first combo — expect 20–60 min total. If it's much slower, reduce `other.honest[:5]` caps — but note the reduction in the report.

- [ ] **Step 2: Commit the grid report** (benchmarks dir is gitignored; force-add just this report)

```bash
git add -f validation/benchmarks/$(date +%F)/short_regime/report.json validation/benchmarks/$(date +%F)/short_regime/report.md
git commit -m "Add short-regime lever-grid results (16 combos at 3x500 operating point)

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

- [ ] **Step 3: Write the marginal-effects summary into the report.md by hand**

For each lever L, compute mean catch@5% across the 8 combos with L on minus the 8 with L off. Append a "Marginal effects" section to `report.md` (4 rows: LAW, SHRINK, PRIOR, LLR) and amend the commit. This is arithmetic on 16 numbers — do it by hand or with a 5-line python snippet; no new module.

**DECISION GATE — STOP HERE.** Present the grid to the user. The rest of the plan is contingent:
- If some combo of existing levers reaches an acceptable catch rate at the 5% budget → Tasks 6–7 may be unnecessary; skip to Task 8 (threshold proposal for that combo) and Task 9.
- If no combo is acceptable → proceed to Task 5 (diagnosis) and then Tasks 6–7 with the grid as the baseline to beat.
- "Acceptable" is the user's call, informed by CIs — do not decide for them.

---

### Task 5: Per-feature reliability at 500 words (diagnosis)

**Files:**
- Create: `validation/short_regime/reliability.py`
- Test: `tests/test_short_regime_reliability.py`
- Output: `validation/short_regime/reliability_500w.json` (committed)

**Interfaces:**
- Consumes: `build_pools` (Task 2), `feature_vector`, `ALL_FEATURE_CODES`, `FEATURE_TIER` from `original.constants`.
- Produces: `feature_reliability(pools, words=500, max_chunks=30) -> dict[str, float]` — per-feature-code ICC(1) ∈ [0,1]; JSON report `{code: {"icc": float, "tier": int}}` sorted descending.

**Method:** For each author with ≥6 chunks, extract vectors for up to `max_chunks` chunks. ICC per feature = between-author variance / (between + within). High ICC at 500 words = the feature still carries identity at this length; near 0 = noise. This names WHICH of the 103 features to trust in the short bucket, replacing intuition with measurement.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_short_regime_reliability.py
import numpy as np

from validation.short_regime.reliability import icc_1


def test_icc_perfectly_reliable_feature():
    # 3 authors, 4 obs each, zero within-author variance
    groups = [np.full(4, 0.2), np.full(4, 0.5), np.full(4, 0.8)]
    assert icc_1(groups) > 0.99


def test_icc_pure_noise_feature():
    rng = np.random.default_rng(0)
    groups = [rng.normal(0.5, 0.1, 50) for _ in range(3)]
    assert icc_1(groups) < 0.1


def test_icc_clipped_to_unit_interval():
    groups = [np.array([0.5, 0.5]), np.array([0.5, 0.5])]
    assert 0.0 <= icc_1(groups) <= 1.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_short_regime_reliability.py -v`
Expected: FAIL — module not found

- [ ] **Step 3: Implement reliability.py**

```python
# validation/short_regime/reliability.py
"""Per-feature ICC(1) at the 500-word operating point.

ICC = between-author variance / total variance per feature. Answers: which
of the 103 features still separates authors at 500 words? Output feeds the
Task 6-8 decisions and any future refit of LENGTH_WEIGHT_SCHEDULE['short']
(constants.py:298 — read the Σ(w²) normalisation comment before refitting).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_ROOT))

from original.constants import ALL_FEATURE_CODES, FEATURE_TIER  # noqa: E402
from original.features.pipeline import feature_vector           # noqa: E402

from .corpus import build_pools                                  # noqa: E402


def icc_1(groups: list[np.ndarray]) -> float:
    """One-way ICC: var(group means) / (var(group means) + mean within-var)."""
    means = np.array([g.mean() for g in groups])
    within = float(np.mean([g.var(ddof=1) if g.size > 1 else 0.0 for g in groups]))
    between = float(means.var(ddof=1)) if means.size > 1 else 0.0
    total = between + within
    if total <= 1e-12:
        return 0.0
    return float(np.clip(between / total, 0.0, 1.0))


def feature_reliability(pools, words: int = 500, max_chunks: int = 30) -> dict[str, float]:
    per_author = {}
    for author, chunks in pools.items():
        if len(chunks) < 6:
            continue
        per_author[author] = np.stack([feature_vector(c) for c in chunks[:max_chunks]])
    out = {}
    for k, code in enumerate(ALL_FEATURE_CODES):
        groups = [V[:, k] for V in per_author.values()]
        out[code] = icc_1(groups)
    return out


def main() -> int:
    pools = build_pools(_ROOT / "validation" / "corpus", words=500)
    rel = feature_reliability(pools)
    report = {
        code: {"icc": round(v, 4), "tier": FEATURE_TIER.get(code, 0)}
        for code, v in sorted(rel.items(), key=lambda kv: -kv[1])
    }
    out = Path(__file__).parent / "reliability_500w.json"
    out.write_text(json.dumps(report, indent=2))
    print(f"wrote {out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run tests, then the study**

Run: `.venv/bin/pytest tests/test_short_regime_reliability.py -v` — Expected: 3 passed
Run: `cd ~/Desktop/Original && .venv/bin/python -m validation.short_regime.reliability`
Expected: `reliability_500w.json` written; skim it — tiers the stability study called length-fragile should show low ICC. Note the top-10 and bottom-10 features in the commit message body.

- [ ] **Step 5: Commit**

```bash
git add validation/short_regime/reliability.py tests/test_short_regime_reliability.py validation/short_regime/reliability_500w.json
git commit -m "Add per-feature ICC reliability study at 500-word operating point

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 6 (CONTINGENT — only after the Task 4 gate): tenant-cohort prior fallback

Makes `BAYESIAN_PRIOR_ENABLED` usable in production at cold start. Today the caller resolves `get_genre_stats(genre)` (`original/routers/students_scoring.py:~125`), which is empty until enough same-genre data accumulates — exactly when the prior is most needed. Add a genre-agnostic cohort fallback behind a new flag.

**Files:**
- Modify: `original/store.py` — add `get_cohort_stats()` next to the existing `get_genre_stats` (find it with `grep -n "def get_genre_stats" original/store.py` and mirror its query WITHOUT the genre filter; also mirror in `original/postgres_repository.py` — both backends or the task is incomplete)
- Modify: `original/routers/students_scoring.py` (the `_genre_stats` block near line 125)
- Test: `tests/test_cohort_prior_fallback.py`

**Interfaces:**
- Consumes: existing repo pattern for `get_genre_stats` (returns `{"mean": nd, "std": nd, "n_samples": int}` or None).
- Produces: env flag `COHORT_PRIOR_FALLBACK` (default unset = OFF); router change:

```python
# original/routers/students_scoring.py — replace the _genre_stats block
    _genre_stats = None
    if _scoring_config_env.bayesian_prior_enabled and state.sample_count < 10:
        _genre = (
            state.samples[-1].genre
            if state.samples and getattr(state.samples[-1], "genre", None)
            else None
        )
        if _genre:
            _genre_stats = _repo().get_genre_stats(_genre)
        # Cohort fallback: when no same-genre prior exists yet (cold start),
        # fall back to the tenant-wide cohort prior. Gated separately so the
        # genre-keyed behaviour is unchanged unless explicitly enabled.
        if _genre_stats is None and os.environ.get("COHORT_PRIOR_FALLBACK") == "1":
            _genre_stats = _repo().get_cohort_stats()
```

- [ ] **Step 1: Write failing tests** — three cases: (a) flag off + no genre stats → `genre_stats is None` reaches scoring (assert via monkeypatched `_repo`); (b) flag on + genre stats present → genre stats win (fallback NOT called); (c) flag on + genre stats None → cohort stats used. Use FastAPI TestClient against `/students/{id}/score` with a monkeypatched repository exposing call counters. Mirror the fixture pattern of the nearest existing router test (`grep -rn "students_scoring\|/score" tests/ | head` to find it) — copy its client/app setup verbatim.
- [ ] **Step 2: Run tests, verify all three fail** (`get_cohort_stats` doesn't exist yet).
- [ ] **Step 3: Implement `get_cohort_stats` in `store.py`** — same aggregation as `get_genre_stats` minus the genre WHERE-clause; floors: return None below 3 students / 5 vectors (mirror the null-pool floors, `original/quantum/null_pool.py`). Then the router change above. Then `postgres_repository.py`.
- [ ] **Step 4: Run the new tests (3 passed) and the touched-module suites:** `.venv/bin/pytest tests/test_cohort_prior_fallback.py tests/quantum/ -q` — Expected: 0 failed.
- [ ] **Step 5: Re-run the harness with the fallback live** — temporarily add a `LeverCombo` variant or verify via grid that PRIOR combos now behave identically to the harness's hand-fed cohort stats (they should — same math).
- [ ] **Step 6: Commit**

```bash
git add original/store.py original/postgres_repository.py original/routers/students_scoring.py tests/test_cohort_prior_fallback.py
git commit -m "Add COHORT_PRIOR_FALLBACK: tenant-wide prior when genre stats are cold

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

Also add the flag row to CLAUDE.md's env-flag table in the same commit.

---

### Task 7 (CONTINGENT): length-conditioned percentile calibration (attach-only)

The Lewis session showed ordering survives but absolute calibration doesn't. Attach an honest-percentile alongside the raw score: `deviation_percentile` = where this deviation falls in the honest same-author distribution for the submission's length bucket. Attach-only — never changes `action` (same contract as `llr_deviation_score`).

**Files:**
- Create: `original/quantum/percentile.py`
- Create: `original/quantum/percentile_table.json` (fitted from Task 3/4 honest scores + the existing seminary stability data)
- Modify: `original/quantum/scoring.py` — new `ScoringConfig` field `percentile_table: dict | None = None`, read `SCORE_PERCENTILE_ENABLED` in `from_env`; attach in the authorship block next to llr
- Modify: `original/routers/students_scoring.py` — load table (module-level, once) and pass via config
- Test: `tests/quantum/test_percentile.py`

**Interfaces:**
- Produces: `percentile_of(deviation: float, n_tokens: int, table: dict) -> float` — linear interpolation over the stored honest-score quantile grid for `_length_bucket_for(n_tokens)`; table schema `{"short": {"q": [0.0, 0.01, ..., 1.0], "v": [scores...]}, "medium": ..., "long": ...}`; `AuthorshipResult.deviation_percentile: float | None`.

- [ ] **Step 1: Failing tests** — (a) `percentile_of(v, 500, table)` returns 0.95 when v equals the stored 95th-quantile score for `short`; (b) monotone in v; (c) `score()` with flag off → `deviation_percentile is None` (attach-only contract); (d) flag on + table → populated, and `action` identical to flag-off on the same input.
- [ ] **Step 2: Verify they fail.**
- [ ] **Step 3: Implement.** Fit the table with a one-off script inside the step: quantile grid (0..1 step 0.01) of Task 3's `honest_scores` for the short bucket; leave `medium`/`long` as `null` (percentile returns None for missing buckets — explicit, not silently wrong). Follow the exact pattern `llr_deviation_score` uses for attachment and response threading (grep it through `scoring.py` → `schemas.py` → `students_scoring.py` and mirror all three).
- [ ] **Step 4: Full quantum suite green:** `.venv/bin/pytest tests/quantum/ -q` — 0 failed.
- [ ] **Step 5: Commit** (include CLAUDE.md flag-table row for `SCORE_PERCENTILE_ENABLED`).

---

### Task 8: Threshold proposal document (NO code change)

**Files:**
- Create: `docs/calibration/short_regime_thresholds_<date>.md`

- [ ] **Step 1: Compute proposed thresholds** from the winning combo's honest distribution: the score values at honest quantiles {0.50, 0.80, 0.95} → proposed `no_action`/`monitor`/`schedule_conversation`/`escalate` boundaries for the short bucket, with the catch rate each implies. Show current `ACTION_THRESHOLDS` alongside.
- [ ] **Step 2: Write the doc** — proposal, evidence (grid table, CIs), and an explicit "requires user sign-off; publish-sync README.md + MODEL_CARD.md + OWNERS_MANUAL.md if adopted" banner.
- [ ] **Step 3: Commit the doc. Do NOT touch `constants.py`.**

---

### Task 9: Regression and byte-identical verification

- [ ] **Step 1: Full suite:** `.venv/bin/pytest tests/ validation/test_tier10_optional.py -q` — Expected: 0 failed (XFAIL/XPASS on the 5 TestAuthEndpoints throttle tests is normal).
- [ ] **Step 2: Byte-identical flags-off check:** score one fixed seminary chunk against a fixed 3-sample state on `main` and on this branch with all flags unset; assert `deviation_score` identical to full float precision. One-off script — show both numbers in the PR description.
- [ ] **Step 3: Commit any fixes; open PR** to `main` per project convention (branch → PR, no direct push).

---

## Explicitly out of scope (name it so nobody "helpfully" adds it)

- Sequential baseline growth over the semester (auto-admitting clean submissions to the baseline. The drift-gate machinery in `students_baseline.py` already points this way; it is the highest-value *product* lever but a separate effort with its own risks.)
- Refitting `LENGTH_WEIGHT_SCHEDULE["short"]` from the Task 5 ICC data — do not touch `constants.py` weight math in this plan; the ICC report is the input to that future proposal.
- Any change to the adaptive-context path (`CONTEXT_MANIFEST_ENABLED`/`ADAPTIVE_WEIGHTS_ENABLED`) — measured harmful at short lengths in the 2026-07-29 Lewis run; fixing it is its own investigation.
- The genre-shift harness spec (2026-07-27) — separate deliverable; its min-sample-size floor should be updated to cite this plan's measurements when both exist.
