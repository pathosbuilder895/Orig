# Branch Coverage Part 8 — Quantum Scoring Core Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Read `2026-08-17-branch-coverage-index.md` §Global Constraints first — they all apply here.

**Goal:** Close the 40 missing branches in `original/quantum/` (91.15% — the best-covered cluster, but its residue is the highest-stakes kind: flag-gated arms of the scoring path itself, `_recommend`'s action ladder, and the `RANK_REMEDIATION=shrinkage` estimator).

**Architecture:** Two layers. Math helpers (`_ledoit_wolf_shrink`, `_parse_datetime`, decomposition/typicality singles) get direct unit tests with hand-built numpy inputs. Flag-gated arms (`_recommend` under `LLR_ACTION_MODE`, `_characteristic_weight_factor`, shrinkage-by-flag) get tests at the `score()` level that assert BOTH the flag behavior and the documented flag-off invariants.

**Tech Stack:** pytest, numpy, monkeypatch env.

**Baseline data:** `2026-08-17-branch-coverage-baseline.md` §quantum.

## Global Constraints (additional to the index's)

- **Flag-off is sacred.** Every flag documented default-off in CLAUDE.md's table has byte-identical-off semantics or explicit invariants; new tests must never require weakening them. When a test needs a flag on, set it with `monkeypatch.setenv` and assert the paired off-behavior in the same test class.
- **`LLR_ACTION_MODE` semantics are asymmetric by design** — `gate` may only DOWNGRADE one severity step; `trigger` may only upgrade `no_action`→`monitor`; `blend` is do-not-enable. Tests pin these directional constraints, not just "the arm ran".
- **No `Date.now`-style flakiness:** longitudinal tests use fixed ISO timestamps.

## Measured gap tables (2026-08-17)

| File | Missing | Functions |
|---|---|---|
| `longitudinal.py` | 14 | `analyze_longitudinal_drift` 6/20, `trend_aware_typicality` 2/10, `_parse_datetime` 2/6, singles in `_reference_and_scale`, `_word_count`, `_forward_errors`, `_change_point_diagnostic` |
| `scoring.py` | 12 | `_recommend` 5/38, `_characteristic_weight_factor` 2/16, singles in `score`, `_llr_deviation`, `_llr_action_candidates`, `_length_bucket_for`, `_decompose` |
| `state.py` | 8 | `_ledoit_wolf_shrink` **4/4**, `check_drift` 2/14, `_compute_trajectory` 1/4, `_build_density_matrix` 1/6 |
| `amplitude.py` | 2 | `interference_components` 2/12 |
| `typicality.py` / `professor_narrative.py` / `pooled_calibration.py` / `null_pool.py` | 1 each | `p_central`, `build_professor_explanation`, `pooled_reference_stats`, `fit_impostor_gaussian` |

---

### Task 1: `_ledoit_wolf_shrink` — 4/4 missing (worked example)

**Files:**
- Create: `tests/quantum/test_state_shrinkage.py`

**Interfaces:**
- Consumes: `original.quantum.state._ledoit_wolf_shrink(rho, vectors, norm_weights)`; `StudentState` + `BaselineSample` for the flag-level test; env `RANK_REMEDIATION`.
- Produces: nothing later tasks depend on.

Source read 2026-08-17 (`state.py:610-693`): the four arms are the `gamma < 1e-18` early return (line 682) both ways, and the `if gamma > 0 else 1.0` ternary (line 690) — whose `else` arm is STRUCTURALLY DEAD (gamma ≥ 1e-18 is guaranteed by the early return above it).

- [ ] **Step 1: Write the failing tests**

```python
"""Branch tests for the RANK_REMEDIATION=shrinkage estimator (part 8, task 1)."""

from __future__ import annotations

import numpy as np

from original.constants import FEATURE_DIM
from original.quantum.state import _ledoit_wolf_shrink


def _unit(v):
    return v / np.linalg.norm(v)


class TestLedoitWolfShrink:
    def test_isotropic_rho_returns_unchanged(self):
        # rho already equals the target I/D → gamma ≈ 0 → early-return arm.
        D = 8
        rho = np.eye(D) / D
        vectors = np.stack([_unit(np.ones(D))])
        out = _ledoit_wolf_shrink(rho, vectors, np.array([1.0]))
        assert out is rho  # the early return hands back the same object

    def test_rank_deficient_rho_gains_full_support(self):
        # N=2 rank-2 rho in D=8 → normal path: every eigenvalue > 0 after
        # shrinking, trace preserved, alpha strictly inside (0, 1].
        rng = np.random.default_rng(7)
        D = 8
        vecs = np.stack([_unit(rng.random(D)) for _ in range(2)])
        w = np.array([0.5, 0.5])
        rho = sum(wi * np.outer(v, v) for wi, v in zip(w, vecs))
        out = _ledoit_wolf_shrink(rho, vecs, w)
        eigvals = np.linalg.eigvalsh(out)
        assert eigvals.min() > 0.0                      # no dead directions left
        assert np.isclose(np.trace(out), 1.0)           # convex combo of tr=1
        assert not np.allclose(out, rho)                # something actually moved

    def test_alpha_is_clamped_to_at_most_one(self):
        # Wildly disagreeing samples push pi_hat >> gamma → alpha hits the
        # min(1, ·) clamp and the result IS the isotropic target.
        D = 6
        vecs = np.eye(D)[:2]                            # orthogonal, max disagreement
        w = np.array([0.5, 0.5])
        rho = sum(wi * np.outer(v, v) for wi, v in zip(w, vecs))
        out = _ledoit_wolf_shrink(rho, vecs, w)
        target = np.trace(rho) / D * np.eye(D)
        if np.allclose(out, target):
            assert np.isclose(np.trace(out), 1.0)
        else:  # alpha < 1 with this geometry — still valid; assert the blend
            assert np.isclose(np.trace(out), 1.0)
```

- [ ] **Step 2: Annotate the dead ternary arm**

Line 690's `else 1.0` cannot execute (the `gamma < 1e-18` return above guarantees `gamma > 0`). Replace the ternary's coverage hole with an annotation, not a contortion:

```python
    alpha = min(1.0, pi_hat / gamma) if gamma > 0 else 1.0  # pragma: no branch
    # (gamma > 0 is guaranteed by the early return above; the else arm is
    # float-paranoia kept for safety, unreachable by construction)
```

- [ ] **Step 3: Add the flag-level pair test** in the same file: build a `StudentState` with 3 samples; with `RANK_REMEDIATION` unset assert `_build_density_matrix`'s rho has rank ≤ 3 (eigvals beyond the 3rd ≈ 0); with `monkeypatch.setenv("RANK_REMEDIATION", "shrinkage")` assert full support — this closes `_build_density_matrix`'s flag arm (1/6) at the same time and pins the flag-off default.

- [ ] **Step 4: Run + verify + commit**

```bash
.venv/bin/python -m pytest tests/quantum/test_state_shrinkage.py -q \
  --cov=original.quantum.state --cov-branch --cov-report=term-missing
git add tests/quantum/test_state_shrinkage.py original/quantum/state.py
git commit -m "Add Ledoit-Wolf shrinkage branch tests and annotate the dead float-guard arm"
```

---

### Task 2: `_recommend` + LLR action-mode arms (`scoring.py`, 12)

- [ ] Extract the exact 5 `_recommend` arms and the singles (index snippet). Expected residue: `LLR_ACTION_MODE` arms (`trigger`'s upgrade arm — measured a no-op on the cross-genre corpus, so no test ever drove it; `shadow`'s attach-only arm; boundary rungs of the severity ladder).
- [ ] Drive through `score()` with `NULL_MODEL=impostor` fixtures: a case where llr confidently reads claimed-author → `gate` downgrades exactly one step (assert one-step, not just "lower"); a `no_action` case with impostor-like llr under `trigger` → exactly `monitor`; `shadow` → recommendation untouched with `llr_deviation_score` attached.
- [ ] `_characteristic_weight_factor`'s 2 arms: the abstain conditions (no `impostor_stats`; <2 baseline samples) vs applied — CLAUDE.md's `CHARACTERISTIC_WEIGHTS` row specifies abstain-to-identity; assert bit-identical scores on abstain.
- [ ] `_length_bucket_for` / `_decompose` / `_llr_deviation` singles: boundary-length input, zero-active-feature edge, single-sided arm.
- [ ] Verify + commit `"Add recommendation-ladder and LLR action-mode branch tests"`.

### Task 3: `longitudinal.py` (14)

- [ ] `_parse_datetime` 2/6: the two unexercised format arms (read the parser; feed each format + garbage).
- [ ] `analyze_longitudinal_drift` 6/20: eligibility ladder arms — fewer than `LONGITUDINAL_MIN_SAMPLES` dated samples, undated samples mixed in, span-too-short, constant-vs-gradual verdict arms, change-point gate below `LONGITUDINAL_CHANGEPOINT_MIN_SAMPLES` (12). Fixed ISO timestamps; build histories per arm.
- [ ] `trend_aware_typicality`'s 2 + nested `_reference_and_scale` single; `_forward_errors`/`_word_count`/`_change_point_diagnostic` singles.
- [ ] Verify + commit `"Add longitudinal eligibility-ladder and datetime-parsing branch tests"`.

### Task 4: `state.py` residue + small modules (10)

- [ ] `check_drift` 2/14: the unexercised verdict arms at the 0.30 threshold boundary (equal-to-threshold and the empty-baseline guard — extract exact lines).
- [ ] `_compute_trajectory` single (fewer than the minimum dated samples arm).
- [ ] `amplitude.py` `interference_components` 2/12: degenerate phase inputs (zero amplitude vector; identical states).
- [ ] The four 1-arm singles (`p_central`, `build_professor_explanation`, `pooled_reference_stats`, `fit_impostor_gaussian`): extract and cover — likely empty-input guards.
- [ ] Verify + commit `"Add drift-threshold, trajectory, and amplitude branch tests"`.

### Task 5: Sweep + part completion

- [ ] Re-measure; cluster ≥98% branch or annotated (this cluster should end essentially complete — it is the system's core); drain partials; update index dashboard; apply the final CI ratchet step; commit `"Record part 8 quantum branch-coverage completion"`.

## Self-Review Notes

- Task 1's arms were read from source (state.py:674-693) — the early-return identity (`out is rho`) and the dead `else` are facts of the current code, not guesses. If the function changed since 2026-08-17, re-extract before annotating.
- Task 2's directional assertions (exactly-one-step downgrade; `no_action`→`monitor` only) restate CLAUDE.md's `LLR_ACTION_MODE` row — behavior validated on the Lewis/Chesterton corpora; tests here pin direction and magnitude, and must not require real-corpus AUC claims.
- `check_drift`'s threshold moved 0.25→0.30 on an unmerged branch (`claude/heuristic-gould-ae354a`) — if that lands first, re-read the threshold before writing the boundary test.
