# Pilot-Scale Reachability + Verification Closeout — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the typicality axis capable of producing a non-`no_action` verdict at realistic pilot sample sizes (currently it cannot until a student has 33 prior submissions), and close out the verification work whose results are still unproven.

**Architecture:** The typicality axis computes conformal p-values against a student's *own* leave-one-out distances, so the smallest reachable p-value is `1/(N+1)` where N is that student's submission count. Every band threshold (.03/.02/.015/.005) therefore needs N ≥ 33/49/66/199. We add an opt-in *population-calibrated* mode: the reference distribution is pooled from many students' same-author LOO distances within the tenant, making N large immediately while `rms_z`'s existing per-student self-normalization keeps samples comparable. This is the same remedy that fixed attribution (calibrate against a population instead of a single self-normalized scale), applied to the other axis. Everything ships behind a default-off flag; the pooling assumption gets an empirical exchangeability check before it is trusted.

**Tech Stack:** Python 3.11, NumPy, FastAPI, pytest. No new dependencies.

## Global Constraints

- Python is `~/Desktop/Original/.venv/bin/python` — never system `python3`, never a relative `.venv` path.
- Work only in the worktree `/Users/andrew/Desktop/Original/.claude/worktrees/plato-works-dating-analysis-b05b1a` on branch `claude/plato-works-dating-analysis-b05b1a`. Verify `pwd` and `git branch --show-current` before starting and again before every commit.
- **All new behavior is opt-in.** With every new flag unset, scoring output must be byte-identical to current `main`. This is the project's standing Phase-1 guarantee.
- **`original/constants.py` is permission-gated.** No task in this plan may edit `ALL_FEATURE_CODES` ordering, `TIER_WEIGHTS`, or `NORM_BOUNDS`. Tasks that would need to STOP and surface the exact diff to the user.
- Full suite must end at 0 failed: `~/Desktop/Original/.venv/bin/python -m pytest tests/ validation/test_tier10_optional.py -q`. The 5 `TestAuthEndpoints` rate-limit tests are `xfail(strict=False)` and never count as failures.
- Commit trailer: `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`
- `git add` specific paths only — never `git add -A`. Untracked corpus caches must stay untracked.
- Never kill a running python process; other work may be executing in this worktree.

---

## The finding this plan exists to fix

Measured against the shipped thresholds in `original/quantum/typicality.py:34-37`:

| Band boundary | Threshold | Min N to reach |
|---|---|---|
| leave `no_action` (p_far) | 0.030 | 33 |
| too-central (p_central) | 0.020 | 49 |
| `monitor` | 0.015 | 66 |
| `schedule_conversation` | 0.005 | 199 |

A student with 5–30 prior submissions cannot receive any action but `no_action`, regardless of how anomalous their work is. Only the catastrophic `rms_z >= 3` override and the identity axis (LLR) do any work at pilot scale. G1's `0/216` and G6's structurally-zero flag rates are consequences of this, not independent bugs.

## Workstream map

This plan covers **Phase 0** and **Phase 1**. Phases 2 and 3 are named here so the sequencing is visible; each needs its own plan and its own corpus work.

- **Phase 0 — Closeout (this plan).** Finish and prove the verification work already in the tree: the un-reviewed vacuous-pass fix, the G2 floor-asymmetry audit, gate determinism, and the first real run of G5/G2b/G6.
- **Phase 1 — Population-calibrated typicality (this plan).** The reachability remedy.
- **Phase 2 — Tier hygiene (separate plan).** Tier 18 `NORM_BOUNDS` recalibration (permission-gated), a scoring-time harness so tiers 0/11/12 can be measured at all, and weight re-derivation once a non-Plato-dominated corpus exists.
- **Phase 3 — Corpus (separate plan).** The binding constraint under Phase 2 and under any future weight work: the derivation corpus is 21 Plato dialogues in one translator's English against 5 seminary pseudo-authors.

---

## Task 1: Review the vacuous-pass fix that shipped without one

**Files:**
- Review only: `validation/calibration_gate.py`, `tests/test_calibration_gate.py` (commit `34d8ceb6`)
- Create: `.superpowers/sdd/task-14-fix-review.md`

**Interfaces:**
- Consumes: commit `34d8ceb6`, the prior review's findings list.
- Produces: a verdict recorded on disk; no code changes unless a defect is confirmed.

Commit `34d8ceb6` was completed in the main thread after both subagents hit a session limit, and is the only change on this branch that never got an independent review. It closed two CRITICALs, so it needs one.

- [ ] **Step 1: Confirm the working directory**

Run: `cd /Users/andrew/Desktop/Original/.claude/worktrees/plato-works-dating-analysis-b05b1a && pwd && git branch --show-current`
Expected: the worktree path and `claude/plato-works-dating-analysis-b05b1a`.

- [ ] **Step 2: Verify each claim in the commit independently**

Run `git show 34d8ceb6` and check, with evidence, each of:
1. `_conformal_p_floor(n)` returns `1/(n+1)` and `_threshold_reachable(n, threshold)` is the correct predicate, including at `n=0`.
2. G6 returns the unreachable-threshold skip (not a pass) whenever the observed minimum `typicality_n` cannot reach `0.02`.
3. G1's `current_value` carries the `UNINFORMATIVE` annotation but its `passed` value is unchanged from before the commit.
4. `evaluate_g6_fairness` on `(0,0)`, `(0,0.05)`, `(0.05,0)`, `(0.02,0.03)` returns fail/fail/fail/pass with the documented `current_value` strings.
5. `_paraphrase_proxy` preserves paragraph count, newline count, and word count on every file in `validation/corpus/ai_*.txt`.

- [ ] **Step 3: Look for what the fix might have broken**

Specifically check: does the G1 annotation change `GateResult.detail` keys that any other code or test reads? Does the reachability guard fire on G2/G2b (which use `q`, not a threshold) where it should not? Does `_paraphrase_proxy` handle a single-paragraph document, a document with no sentence-final punctuation, and an empty string without raising?

- [ ] **Step 4: Run the gate tests**

Run: `~/Desktop/Original/.venv/bin/python -m pytest tests/test_calibration_gate.py -q`
Expected: `47 passed`.

- [ ] **Step 5: Record the verdict**

Write `.superpowers/sdd/task-14-fix-review.md` with a per-claim CONFIRMED/REFUTED table and any new findings ranked by severity. If a defect is confirmed, STOP and report it rather than fixing it inline — it needs its own TDD cycle.

- [ ] **Step 6: Commit the review record**

```bash
git add .superpowers/sdd/task-14-fix-review.md
git commit -m "$(cat <<'EOF'
Record independent review of the G6 vacuous-pass fix

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: Determine whether G2's margin is real or floor-driven

**Files:**
- Create: `validation/audits/g2_floor_asymmetry.py`
- Create: `tests/test_g2_floor_asymmetry.py`

**Interfaces:**
- Consumes: `validation.calibration_gate._compute_g2_q_values` (read-only), `original.quantum.typicality.p_far`/`p_central`.
- Produces: `analyze_floor_asymmetry(holdout_records, impostor_records) -> dict` with keys `holdout_at_floor_rate`, `impostor_at_floor_rate`, `holdout_n_range`, `impostor_n`, `matched_n_verdict`.

G2 is the project's strongest positive evidence: median impostor `q` 0.048 vs holdout 0.222. But every impostor `q` is a multiple of `1/21` (N=20, floor 0.0476) and the median sits *exactly on that floor*, while holdouts run at N≈3–11 (floors 0.083–0.25) with several also at their own floor. If both legs are rank-1 within their own reference sets and only the denominators differ, G2 measures sample size, not authorship.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_g2_floor_asymmetry.py
from validation.audits.g2_floor_asymmetry import analyze_floor_asymmetry


def test_detects_pure_floor_artifact():
    """Both legs rank-1 in their own reference sets, only N differs:
    the q gap is entirely an artifact and must be reported as such."""
    holdout = [{"q": 1 / 6, "n": 5, "rank": 1}] * 10      # floor 0.167
    impostor = [{"q": 1 / 21, "n": 20, "rank": 1}] * 10   # floor 0.048
    out = analyze_floor_asymmetry(holdout, impostor)
    assert out["holdout_at_floor_rate"] == 1.0
    assert out["impostor_at_floor_rate"] == 1.0
    assert out["matched_n_verdict"] == "artifact"


def test_detects_genuine_separation():
    """Impostors rank first while holdouts sit mid-distribution: the
    separation survives matching on N."""
    holdout = [{"q": 3 / 6, "n": 5, "rank": 3}] * 10
    impostor = [{"q": 1 / 21, "n": 20, "rank": 1}] * 10
    out = analyze_floor_asymmetry(holdout, impostor)
    assert out["holdout_at_floor_rate"] == 0.0
    assert out["matched_n_verdict"] == "genuine"
```

- [ ] **Step 2: Run it to verify it fails**

Run: `~/Desktop/Original/.venv/bin/python -m pytest tests/test_g2_floor_asymmetry.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'validation.audits'`.

- [ ] **Step 3: Implement the analyzer**

```python
# validation/audits/g2_floor_asymmetry.py
"""Is G2's margin authorship signal, or the arithmetic of unequal N?

q = min(p_far, p_central) is quantised at 1/(n+1). The impostor leg runs
at n=20 (floor 0.0476); holdouts run at n=3-11 (floors 0.083-0.25). A
gap between the two medians is only evidence of discrimination if it
survives after both legs are put on a common footing.
"""

from __future__ import annotations


def _at_floor(rec: dict) -> bool:
    """True when the sample is already the most extreme its n allows."""
    return rec["rank"] == 1


def analyze_floor_asymmetry(holdout_records, impostor_records) -> dict:
    h_floor = sum(_at_floor(r) for r in holdout_records) / max(1, len(holdout_records))
    i_floor = sum(_at_floor(r) for r in impostor_records) / max(1, len(impostor_records))

    # Rank is scale-free where q is not: if both legs are saturated at
    # rank 1, the q difference is the floor difference and nothing else.
    if h_floor >= 0.5 and i_floor >= 0.5:
        verdict = "artifact"
    elif i_floor > h_floor:
        verdict = "genuine"
    else:
        verdict = "inconclusive"

    h_ns = sorted({r["n"] for r in holdout_records})
    return {
        "holdout_at_floor_rate": h_floor,
        "impostor_at_floor_rate": i_floor,
        "holdout_n_range": (h_ns[0], h_ns[-1]) if h_ns else (0, 0),
        "impostor_n": sorted({r["n"] for r in impostor_records}),
        "matched_n_verdict": verdict,
    }
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `~/Desktop/Original/.venv/bin/python -m pytest tests/test_g2_floor_asymmetry.py -q`
Expected: `2 passed`.

- [ ] **Step 5: Run it against the real G2 legs**

Add a `main()` to the module that re-runs G2's two legs recording `typicality_n`, `typicality_p_far`, `typicality_p_central` and the rank per sample, then prints the analyzer's dict. Run it detached (it is HTTP-heavy):

```bash
nohup ~/Desktop/Original/.venv/bin/python -m validation.audits.g2_floor_asymmetry \
  > "$SCRATCH/g2_audit.log" 2>&1 & disown
```

Record the PID, then wait on it. Report the printed dict verbatim.

- [ ] **Step 6: Commit**

```bash
git add validation/audits/g2_floor_asymmetry.py tests/test_g2_floor_asymmetry.py
git commit -m "$(cat <<'EOF'
Add G2 floor-asymmetry audit — is the margin signal or unequal N?

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: Make the gate reproducible

**Files:**
- Modify: `validation/calibration_gate.py` (loader functions only)
- Test: `tests/test_calibration_gate.py` (extend)

**Interfaces:**
- Consumes: `_load_plato_texts_by_dialogue`, `_load_seminary_texts`.
- Produces: no signature changes; a `corpus_fingerprint` entry in each `GateResult.detail`.

Across the two recorded runs G1 reproduced bit-identically, but G2's individual `q` values changed *denominators* (n=5 → n=11 for some dialogues) and G4's group means drifted ~0.005 — on corpora the G3 repairs never touched. Suspected cause: the untracked Plato caches (`validation/plato/_features_cache*.npz`, `corpus/_raw_cache/pg1497.txt`, `pg1750.txt`) were regenerated mid-session. A gate that cannot reproduce cannot certify anything.

- [ ] **Step 1: Find the actual cause before changing anything**

Compare the two reports' `holdout_q` lists and derive each value's `n`. Then check whether the Plato loader's per-dialogue chunk counts depend on any untracked cache file, on filesystem ordering (`glob` without `sorted`), or on a rebuild step. Record the diagnosis in the commit message — do not guess.

- [ ] **Step 2: Write the failing test**

```python
class TestCorpusDeterminism:
    def test_plato_loader_is_order_stable(self):
        """Chunk counts and ordering must not depend on filesystem
        enumeration order — two loads must agree exactly."""
        from validation.calibration_gate import _load_plato_texts_by_dialogue

        a = _load_plato_texts_by_dialogue()
        b = _load_plato_texts_by_dialogue()
        assert list(a.keys()) == sorted(a.keys())
        assert {k: len(v) for k, v in a.items()} == {k: len(v) for k, v in b.items()}
        assert a == b
```

- [ ] **Step 3: Run it to verify it fails (or passes for the right reason)**

Run: `~/Desktop/Original/.venv/bin/python -m pytest tests/test_calibration_gate.py -k Determinism -q`
If it passes, the drift came from the corpus content changing rather than load order — say so explicitly and move to Step 4's fingerprint, which catches that case instead.

- [ ] **Step 4: Add a corpus fingerprint to every gate result**

Hash the sorted `(entity_id, len(texts), total_chars)` triples for each corpus and attach as `detail["corpus_fingerprint"]`. Two runs whose fingerprints differ are not comparable, and the report will now say so instead of silently drifting.

- [ ] **Step 5: Run the full suite**

Run: `~/Desktop/Original/.venv/bin/python -m pytest tests/ validation/test_tier10_optional.py -q`
Expected: 0 failed.

- [ ] **Step 6: Commit**

```bash
git add validation/calibration_gate.py tests/test_calibration_gate.py
git commit -m "$(cat <<'EOF'
Make the calibration gate reproducible: stable loaders + corpus fingerprint

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: Record the first full G1–G6 run

**Files:**
- Create: `validation/calibration_report_<YYYY-MM-DD>.json`
- Modify: none

**Interfaces:**
- Consumes: `validation.calibration_gate.run_all` at current HEAD.
- Produces: the first recorded values for G5, G2b, and G6.

G5, G2b and G6 have never executed against a corpus. The 2026-07-30 report predates all three.

- [ ] **Step 1: Confirm HEAD includes every gate**

Run: `grep -c "def run_g5\|def _compute_g2b_paraphrase_data\|def _compute_g6_fairness_data" validation/calibration_gate.py`
Expected: `3`.

- [ ] **Step 2: Launch detached**

A full run took 3h51m last time and this one adds three gates. Plain background jobs have died at turn boundaries in this project; use nohup plus a pidfile, then wait on the PID.

```bash
nohup ~/Desktop/Original/.venv/bin/python -m validation.calibration_gate \
  --out validation/calibration_report_$(date +%F).json \
  > "$SCRATCH/gate_full.log" 2>&1 & disown
echo $! > "$SCRATCH/gate_full.pid"
```

- [ ] **Step 3: Record results exactly as measured**

Expected, and each must be reported as-is whatever it says: G5 exercises the deviation-shift criterion for the first time; G6 should report `SKIPPED (threshold unreachable)` rather than a pass; G2b should report a real median comparison. **Do not tune anything to make a gate pass.**

- [ ] **Step 4: Commit the report**

```bash
git add validation/calibration_report_<YYYY-MM-DD>.json
git commit -m "$(cat <<'EOF'
Record first full G1-G6 calibration run

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: Pooled calibration set — the pure function

**Files:**
- Create: `original/quantum/pooled_calibration.py`
- Test: `tests/quantum/test_pooled_calibration.py`

**Interfaces:**
- Consumes: nothing (pure NumPy).
- Produces: `build_pooled_reference(per_student_distances: list[np.ndarray], min_students: int = 3, min_total: int = 30) -> np.ndarray | None` and `pooled_reference_stats(ref: np.ndarray) -> dict`.

The reference distribution is the pooled set of same-author LOO `rms_z` distances across students. `rms_z` is already z-normalized against each student's own baseline spread, which is precisely what makes samples from different students comparable — the same property the attribution fix relied on. Returns `None` rather than a thin reference when there is not enough data, so callers fall back to self-calibration instead of inventing confidence.

- [ ] **Step 1: Write the failing test**

```python
# tests/quantum/test_pooled_calibration.py
import numpy as np
import pytest

from original.quantum.pooled_calibration import (
    build_pooled_reference,
    pooled_reference_stats,
)


def test_pools_across_students():
    per_student = [np.array([1.0, 1.1, 0.9]), np.array([1.2, 0.8]), np.array([1.0, 1.3])]
    ref = build_pooled_reference(per_student, min_students=3, min_total=5)
    assert ref is not None
    assert len(ref) == 7
    assert np.all(np.diff(ref) >= 0), "reference must be sorted for p-value lookup"


def test_returns_none_below_the_student_floor():
    """Two students is not a population — refuse rather than pretend."""
    per_student = [np.array([1.0, 1.1, 0.9]), np.array([1.2, 0.8])]
    assert build_pooled_reference(per_student, min_students=3, min_total=5) is None


def test_returns_none_below_the_total_floor():
    per_student = [np.array([1.0]), np.array([1.1]), np.array([0.9])]
    assert build_pooled_reference(per_student, min_students=3, min_total=30) is None


def test_ignores_empty_and_nonfinite_contributions():
    per_student = [
        np.array([1.0, 1.1, 0.9]),
        np.array([]),
        np.array([np.nan, 1.2]),
        np.array([1.0, 1.3]),
    ]
    ref = build_pooled_reference(per_student, min_students=3, min_total=5)
    assert ref is not None
    assert np.all(np.isfinite(ref))
    assert len(ref) == 6


def test_stats_report_the_reachable_floor():
    ref = build_pooled_reference([np.arange(20.0)] * 3, min_students=3, min_total=30)
    stats = pooled_reference_stats(ref)
    assert stats["n"] == 60
    assert stats["p_floor"] == pytest.approx(1 / 61)
    assert stats["n_students"] is None  # not recoverable from the pooled array
```

- [ ] **Step 2: Run it to verify it fails**

Run: `~/Desktop/Original/.venv/bin/python -m pytest tests/quantum/test_pooled_calibration.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'original.quantum.pooled_calibration'`.

- [ ] **Step 3: Implement**

```python
# original/quantum/pooled_calibration.py
"""Population-calibrated typicality reference (Phase 1, opt-in).

Per-student conformal p-values are quantised at 1/(N+1), so with a
realistic pilot N (5-30 submissions) the smallest reachable p-value is
0.032-0.167 while the band thresholds need 0.005-0.03. The typicality
axis is therefore inert at pilot scale — see the reachability table in
docs/superpowers/plans/2026-07-31-pilot-scale-reachability.md.

Pooling every student's same-author LOO distances into one reference
distribution raises N into the hundreds immediately. The pooling is only
legitimate because rms_z is already standardised against each student's
own baseline spread, so a distance of 1.4 means the same thing for a
tight writer and a variable one. That assumption is not taken on faith:
Task 7 checks it empirically before this mode is trusted.
"""

from __future__ import annotations

import numpy as np


def build_pooled_reference(
    per_student_distances: list[np.ndarray],
    min_students: int = 3,
    min_total: int = 30,
) -> np.ndarray | None:
    """Sorted pooled reference, or None when there is too little data.

    Returning None is load-bearing: the caller falls back to per-student
    self-calibration rather than computing a confident-looking p-value
    against a reference too thin to support one.
    """
    contributions = []
    for d in per_student_distances:
        arr = np.asarray(d, dtype=float).ravel()
        arr = arr[np.isfinite(arr)]
        if arr.size:
            contributions.append(arr)

    if len(contributions) < min_students:
        return None

    pooled = np.concatenate(contributions)
    if pooled.size < min_total:
        return None

    return np.sort(pooled)


def pooled_reference_stats(ref: np.ndarray | None) -> dict:
    """Diagnostics for the report — including the p-value floor this
    reference makes reachable, which is the whole point of pooling."""
    if ref is None or len(ref) == 0:
        return {"n": 0, "p_floor": 1.0, "n_students": None}
    n = int(len(ref))
    return {"n": n, "p_floor": 1.0 / (n + 1), "n_students": None}
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `~/Desktop/Original/.venv/bin/python -m pytest tests/quantum/test_pooled_calibration.py -q`
Expected: `5 passed`.

- [ ] **Step 5: Commit**

```bash
git add original/quantum/pooled_calibration.py tests/quantum/test_pooled_calibration.py
git commit -m "$(cat <<'EOF'
Add pooled typicality calibration set (pure, unwired)

Per-student conformal p-values are quantised at 1/(N+1), so at pilot N
the typicality bands are unreachable and the axis can only ever return
no_action. Pooling same-author LOO distances across students raises the
reachable floor. Pure functions only; nothing is wired yet.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: Gather per-student distances from the store

**Files:**
- Create: `original/quantum/pooled_source.py`
- Test: `tests/quantum/test_pooled_source.py`

**Interfaces:**
- Consumes: `build_pooled_reference` (Task 5); the repository's `all_states()`; `StudentState.loo_distances`.
- Produces: `collect_tenant_distances(states: dict[str, StudentState], tenant: str, exclude_sid: str) -> list[np.ndarray]`.

Follows the tenant-scoping convention already established by `original/quantum/null_pool.py:86-99`, which pools by tenant over `all_states()`. The scored student is excluded from their own reference set — including them would leak the sample into its own calibration.

- [ ] **Step 1: Write the failing test**

```python
# tests/quantum/test_pooled_source.py
import numpy as np

from original.quantum.pooled_source import collect_tenant_distances


class _FakeState:
    def __init__(self, distances):
        self._d = np.asarray(distances, dtype=float)

    @property
    def loo_distances(self):
        return self._d


def test_scopes_to_tenant_and_excludes_self():
    states = {
        "demo:alice": _FakeState([1.0, 1.1]),
        "demo:bob": _FakeState([0.9, 1.2]),
        "other:carol": _FakeState([5.0, 5.1]),
    }
    out = collect_tenant_distances(states, tenant="demo", exclude_sid="demo:alice")
    assert len(out) == 1
    assert np.allclose(out[0], [0.9, 1.2])


def test_flat_ids_belong_to_the_demo_sandbox():
    """Legacy un-namespaced ids are the demo sandbox, matching
    principal.py's tenant_of() convention."""
    states = {"legacy": _FakeState([1.0, 1.1]), "demo:bob": _FakeState([0.9])}
    out = collect_tenant_distances(states, tenant="demo", exclude_sid="demo:bob")
    assert len(out) == 1
    assert np.allclose(out[0], [1.0, 1.1])


def test_skips_states_without_usable_distances():
    states = {
        "demo:alice": _FakeState([]),
        "demo:bob": _FakeState([0.9, 1.2]),
        "demo:carol": _FakeState([np.nan]),
    }
    out = collect_tenant_distances(states, tenant="demo", exclude_sid="demo:zed")
    assert len(out) == 1
```

- [ ] **Step 2: Run it to verify it fails**

Run: `~/Desktop/Original/.venv/bin/python -m pytest tests/quantum/test_pooled_source.py -q`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement**

```python
# original/quantum/pooled_source.py
"""Tenant-scoped collection of same-author LOO distances for pooling.

Tenant scoping mirrors null_pool.py: a reference distribution must never
mix tenants, and the scored student never contributes to the reference
they are measured against.
"""

from __future__ import annotations

import numpy as np

from ..principal import DEMO_TENANT, tenant_of


def collect_tenant_distances(states, tenant: str, exclude_sid: str) -> list[np.ndarray]:
    out: list[np.ndarray] = []
    for sid, state in states.items():
        if sid == exclude_sid:
            continue
        if (tenant_of(sid) or DEMO_TENANT) != tenant:
            continue
        try:
            d = np.asarray(state.loo_distances, dtype=float).ravel()
        except Exception:
            continue
        d = d[np.isfinite(d)]
        if d.size:
            out.append(d)
    return out
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `~/Desktop/Original/.venv/bin/python -m pytest tests/quantum/test_pooled_source.py -q`
Expected: `3 passed`.

- [ ] **Step 5: Commit**

```bash
git add original/quantum/pooled_source.py tests/quantum/test_pooled_source.py
git commit -m "$(cat <<'EOF'
Add tenant-scoped collector for pooled typicality distances

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: Check the pooling assumption before trusting it

**Files:**
- Create: `validation/audits/pooling_exchangeability.py`
- Test: `tests/test_pooling_exchangeability.py`

**Interfaces:**
- Consumes: `collect_tenant_distances` (Task 6), `build_pooled_reference` (Task 5).
- Produces: `assess_exchangeability(per_student_distances) -> dict` with `between_within_variance_ratio`, `ks_max_pairwise`, `verdict` in `{"exchangeable", "heterogeneous", "insufficient"}`.

Pooling assumes one student's `rms_z` of 1.4 means what another's does. That assumption is exactly the class of thing this project has been burned by four times — attribution compared per-author scales, G1 and G6 compared unreachable thresholds, G2 may compare unequal floors. It gets measured, not asserted, and the result gates whether Task 8 may be enabled.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_pooling_exchangeability.py
import numpy as np

from validation.audits.pooling_exchangeability import assess_exchangeability


def test_homogeneous_students_are_exchangeable():
    rng = np.random.default_rng(11)
    per_student = [rng.normal(1.0, 0.2, 25) for _ in range(6)]
    out = assess_exchangeability(per_student)
    assert out["verdict"] == "exchangeable"


def test_shifted_students_are_heterogeneous():
    """One student centred at 3.0 while the rest sit at 1.0 means a
    pooled reference would misprice everybody."""
    rng = np.random.default_rng(12)
    per_student = [rng.normal(1.0, 0.2, 25) for _ in range(5)]
    per_student.append(rng.normal(3.0, 0.2, 25))
    out = assess_exchangeability(per_student)
    assert out["verdict"] == "heterogeneous"


def test_too_few_students_is_insufficient_not_a_pass():
    out = assess_exchangeability([np.array([1.0, 1.1])])
    assert out["verdict"] == "insufficient"
```

- [ ] **Step 2: Run it to verify it fails**

Run: `~/Desktop/Original/.venv/bin/python -m pytest tests/test_pooling_exchangeability.py -q`
Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement**

```python
# validation/audits/pooling_exchangeability.py
"""Is a pooled typicality reference legitimate on this population?

Pooling rms_z across students assumes the standardisation already made
them comparable. If between-student variance dominates within-student
variance, it did not, and a pooled p-value would be systematically wrong
for the students furthest from the pooled centre.
"""

from __future__ import annotations

import numpy as np
from scipy import stats

_MIN_STUDENTS = 3
_MIN_PER_STUDENT = 2
_RATIO_LIMIT = 1.0   # between-student variance must not exceed within
_KS_LIMIT = 0.5      # no student may be this far from the pooled rest


def assess_exchangeability(per_student_distances) -> dict:
    usable = []
    for d in per_student_distances:
        arr = np.asarray(d, dtype=float).ravel()
        arr = arr[np.isfinite(arr)]
        if arr.size >= _MIN_PER_STUDENT:
            usable.append(arr)

    if len(usable) < _MIN_STUDENTS:
        return {
            "between_within_variance_ratio": None,
            "ks_max_pairwise": None,
            "verdict": "insufficient",
            "n_students": len(usable),
        }

    means = np.array([a.mean() for a in usable])
    between = float(means.var(ddof=1))
    within = float(np.mean([a.var(ddof=1) for a in usable if a.size > 1]))
    ratio = between / within if within > 0 else float("inf")

    ks_max = 0.0
    for i, arr in enumerate(usable):
        rest = np.concatenate([a for j, a in enumerate(usable) if j != i])
        ks_max = max(ks_max, float(stats.ks_2samp(arr, rest).statistic))

    verdict = "exchangeable" if (ratio <= _RATIO_LIMIT and ks_max <= _KS_LIMIT) else "heterogeneous"
    return {
        "between_within_variance_ratio": ratio,
        "ks_max_pairwise": ks_max,
        "verdict": verdict,
        "n_students": len(usable),
    }
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `~/Desktop/Original/.venv/bin/python -m pytest tests/test_pooling_exchangeability.py -q`
Expected: `3 passed`.

- [ ] **Step 5: Run it on the real corpora and record the answer**

Build per-student distances from the seminary corpus (the closest thing to the target domain) and from the Plato dialogues, then report both verdicts. **If either says `heterogeneous`, STOP and report** — Task 8 must not be enabled on a population where pooling is invalid, and the finding is more valuable than the feature.

- [ ] **Step 6: Commit**

```bash
git add validation/audits/pooling_exchangeability.py tests/test_pooling_exchangeability.py
git commit -m "$(cat <<'EOF'
Check the pooled-calibration exchangeability assumption empirically

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: Wire pooled calibration into scoring behind a flag

**Files:**
- Modify: `original/quantum/scoring.py` (the typicality block and `ScoringConfig`)
- Modify: `original/schemas.py`, `original/routers/_shared.py` (one new response field)
- Test: `tests/quantum/test_pooled_typicality_integration.py`

**Interfaces:**
- Consumes: `build_pooled_reference`, `pooled_reference_stats`, `collect_tenant_distances`.
- Produces: `ScoringConfig.typicality_pooled_calibration` (env `TYPICALITY_POOLED_CALIBRATION`), `Layer7Output.typicality_calibration` in `{"self", "pooled"}`, surfaced on the API response.

Blocked on Task 7 returning `exchangeable`.

- [ ] **Step 1: Write the failing test**

```python
# tests/quantum/test_pooled_typicality_integration.py
import os

import numpy as np
import pytest

from original.quantum.scoring import ScoringConfig


def test_flag_defaults_off():
    cfg = ScoringConfig.from_env()
    assert cfg.typicality_pooled_calibration is False


def test_flag_reads_env(monkeypatch):
    monkeypatch.setenv("TYPICALITY_POOLED_CALIBRATION", "1")
    assert ScoringConfig.from_env().typicality_pooled_calibration is True


def test_pooled_mode_reaches_bands_that_self_mode_cannot():
    """The whole point: with 8 own samples the floor is 1/9=0.111 and no
    band is reachable; against a 200-sample pooled reference the floor is
    0.005 and every band is."""
    from original.quantum.typicality import p_far, SCHEDULE_FAR_THRESHOLD

    own = np.linspace(0.5, 1.5, 8)
    pooled = np.linspace(0.5, 1.5, 200)
    extreme = 99.0

    assert p_far(extreme, own) > SCHEDULE_FAR_THRESHOLD      # unreachable
    assert p_far(extreme, pooled) <= SCHEDULE_FAR_THRESHOLD  # reachable


def test_falls_back_to_self_when_reference_too_thin():
    """A thin population must degrade to self-calibration, never to a
    confident p-value against a reference that cannot support one."""
    from original.quantum.pooled_calibration import build_pooled_reference

    assert build_pooled_reference([np.array([1.0, 1.1])], min_students=3) is None
```

- [ ] **Step 2: Run it to verify it fails**

Run: `~/Desktop/Original/.venv/bin/python -m pytest tests/quantum/test_pooled_typicality_integration.py -q`
Expected: FAIL with `AttributeError: 'ScoringConfig' object has no attribute 'typicality_pooled_calibration'`.

- [ ] **Step 3: Implement the wiring**

In `ScoringConfig` (`original/quantum/scoring.py:230`), beside `typicality_scoring_enabled`:

```python
    typicality_pooled_calibration: bool = False  # was TYPICALITY_POOLED_CALIBRATION
```

and in `from_env` (near line 257), beside its sibling:

```python
            typicality_pooled_calibration=os.environ.get(
                "TYPICALITY_POOLED_CALIBRATION", "0"
            ) == "1",
```

Add the field default beside the other typicality locals (near line 648):

```python
    typicality_calibration: str | None = None
```

Then replace the reference selection inside the existing `if config.typicality_scoring_enabled and adaptive_weights is None:` block. The current body opens with `loo = state.loo_distances` / `typicality_n = len(loo)` (lines 654-655); substitute:

```python
        loo = state.loo_distances
        typicality_calibration = "self"

        # Per-student references are quantised at 1/(N+1), so at pilot N no
        # band is reachable (see the reachability table in the Phase 1 plan).
        # A pooled tenant reference raises the floor; we fall back to self
        # whenever the tenant cannot support one, so a thin population
        # degrades to today's behaviour rather than to a confident number.
        if config.typicality_pooled_calibration and pooled_states is not None:
            from .pooled_calibration import build_pooled_reference
            from .pooled_source import collect_tenant_distances
            from ..principal import DEMO_TENANT, tenant_of

            pooled_ref = build_pooled_reference(
                collect_tenant_distances(
                    pooled_states,
                    tenant=tenant_of(student_id) or DEMO_TENANT,
                    exclude_sid=student_id,
                )
            )
            if pooled_ref is not None:
                loo = pooled_ref
                typicality_calibration = "pooled"

        typicality_n = len(loo)
```

The rest of the block (the `if typicality_n >= 2:` body computing `p_far_fn`, `p_central`, `band_from_p`, `typicality_source`) is unchanged — it already reads whatever `loo` holds.

`score()` must accept the new optional inputs without breaking existing call sites; add them as keyword parameters defaulting to `None`, exactly as `impostor_stats` is threaded today:

```python
    pooled_states: dict | None = None,
    student_id: str = "",
```

Add the field to `Layer7Output` beside the other typicality fields, add `typicality_calibration: str | None = None` to `Layer7OutputResponse` in `original/schemas.py`, and copy it in `_to_response()` (`original/routers/_shared.py`) with the established pattern:

```python
        typicality_calibration=getattr(r, "typicality_calibration", None),
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `~/Desktop/Original/.venv/bin/python -m pytest tests/quantum/test_pooled_typicality_integration.py -q`
Expected: `4 passed`.

- [ ] **Step 5: Prove the flag-off guarantee**

Score a fixture submission with the flag unset, then again with it explicitly `0`, and assert every field of both `Layer7Output`s is identical to a run from before this task. The Phase-1 byte-identical guarantee is not negotiable.

- [ ] **Step 6: Run the full suite**

Run: `~/Desktop/Original/.venv/bin/python -m pytest tests/ validation/test_tier10_optional.py -q`
Expected: 0 failed.

- [ ] **Step 7: Commit**

```bash
git add original/quantum/scoring.py original/schemas.py original/routers/_shared.py \
        tests/quantum/test_pooled_typicality_integration.py
git commit -m "$(cat <<'EOF'
Wire pooled typicality calibration behind TYPICALITY_POOLED_CALIBRATION

Default off; falls back to per-student self-calibration whenever the
tenant cannot support a pooled reference. typicality_calibration records
which mode produced each verdict.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 9: Re-run G1 and G6 with pooled calibration — the payoff test

**Files:**
- Modify: `validation/calibration_gate.py` (add a pooled-mode run variant)
- Create: `validation/calibration_report_pooled_<YYYY-MM-DD>.json`

**Interfaces:**
- Consumes: everything above.
- Produces: the first G1/G6 numbers that are not structurally predetermined.

This is where the plan proves itself. With pooled calibration the thresholds become reachable, so G1 measures a real false-positive rate and G6 a real fairness ratio for the first time.

- [ ] **Step 1: Assert reachability before believing any result**

The run must record, per gate, the reference `n` and the resulting `p_floor`, and `_threshold_reachable` must return True. A pooled run that is still unreachable is a failed experiment, not a passing gate.

- [ ] **Step 2: Run both modes and compare**

Run the gate twice — `TYPICALITY_POOLED_CALIBRATION=0` and `=1` — detached, into two report files.

- [ ] **Step 3: Interpret honestly**

Expect G1's flagged rate to rise above 0.0%. **A rate above 5% means G1 genuinely fails**, which is a real result about calibration and must be recorded as a failure, not tuned away. The band thresholds may then need re-derivation against a reachable regime — that is Phase 2 work, and it should be driven by measurement rather than by the desire for a green gate.

- [ ] **Step 4: Commit both reports**

```bash
git add validation/calibration_report_pooled_<YYYY-MM-DD>.json validation/calibration_gate.py
git commit -m "$(cat <<'EOF'
Record G1-G6 under pooled typicality calibration

First run in which the typicality bands are arithmetically reachable.

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 10: Amend the spec

**Files:**
- Modify: `docs/superpowers/specs/2026-07-28-two-axis-verification-design.md`

Three corrections are outstanding. Do this last so it records what was actually measured.

- [ ] **Step 1: §5 reachability**

State plainly that at pilot N (5–30 submissions) no band is reachable and the axis returns `no_action` for every student, and reference the pooled-calibration remedy.

- [ ] **Step 2: The G5 row**

The current row says shuffled G1 "becomes uninformative noise, not ≤5%". That is wrong for a conformal pipeline: the rate stays at nominal under any exchangeable relabeling by construction. Replace with the shipped criteria — deviation-shift for the G1 leg, chance for G3, non-monotone in ≥2 of 3 draws for G4.

- [ ] **Step 3: The G6 row**

Record that the p_central criterion is unreachable on the fairness slice at n=4 and that the gate skips rather than passes; note that the "and the Phase-4 uniformity features" clause is recorded as measurement but not gated pending Tier 18 bounds recalibration.

- [ ] **Step 4: Commit**

```bash
git add docs/superpowers/specs/2026-07-28-two-axis-verification-design.md
git commit -m "$(cat <<'EOF'
Correct spec: reachability at pilot N, G5 criteria, G6 skip semantics

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
EOF
)"
```

---

## Deferred to their own plans

**Phase 2 — Tier hygiene.** Tier 18 `NORM_BOUNDS` are miscalibrated: `punctuation_dispersion_ratio` normalizes to exactly 0.0 on all three corpora (a variance scored against CV-shaped bounds, raw ≈0.001 against a floor of 0.3) and two more pin at 1.0 on every Plato chunk, so three of six uniformity features are constants wherever they are measured. Fixing it edits `constants.py` and needs explicit user permission; `scripts/calibrate_bounds.py` (already wired for Tier 18) is the tool. Separately, tiers 0, 11 and 12 compute only at scoring time against a baseline, so no corpus sweep can see them — they need a scoring-time measurement harness before any weight derivation can speak about them at all.

**Phase 3 — Corpus.** Every remaining unknown reduces to this: 21 of 27 derivation "authors" are Plato dialogues in one translator's English, the seminary corpus contributes 5 pseudo-authors of 5 essays each, and no student has enough submissions to reach a band. Weight derivation, Tier 18 validation, G6 fairness, and the reachability remedy itself all get more trustworthy with real student text at realistic per-author volume, and none of them fully resolve without it.
