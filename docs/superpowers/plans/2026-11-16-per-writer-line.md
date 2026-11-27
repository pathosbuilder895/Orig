# Per-writer line (`WRITER_LINE`) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a default-off `WRITER_LINE` mode. When it is on, the base verdict tier comes from how unusual the paper is for this student, measured against the student's own baseline papers.

**Architecture:**
- `StudentState.loo_distances` (leave-one-out `rms_z` of each baseline paper, cached) already gives the student's own spread. A pure helper turns the submission's `rms_z` into a z-score against those distances and maps it to a tier.
- `score()` applies it right after `_recommend` and before the LLR step. A new `G-WRITERLINE` gate measures it against `gate` mode.

**Tech Stack:** Python 3.11, numpy, pytest.

**Spec:** `docs/superpowers/specs/2026-11-16-per-writer-line-design.md`

**Build location:** a new worktree on branch `claude/writer-line`, created from `claude/llr-rebind`. The rebind branch holds the records and the harness this reuses.

## Global Constraints

- **Flag values.** `WRITER_LINE` is `off` (default), `shadow` or `on`. Any other value is read as `off`. `off` must be byte-identical to today, and `score-integrity-reviewer` must sign off.
- **Fallback.** Fewer than `WRITER_LINE_MIN_PAPERS = 3` contributing baseline papers, or any degraded path, gives exactly today's behaviour (NORTH_STAR rule 3).
- **Order.** Writer line, then the LLR step (`gate` may still lower one step), then the catastrophic-drift escalate. That last override is unchanged.
- **Shadow purity.** `shadow` logs `writer_line_would=<action> writer_line_z=<z>` and changes no output field.
- **Gate rules.** `G-WRITERLINE` needs a failure witness in `validation/gate_contracts.py`. z cut-offs come from the derivation split only. Below about 74 genuine papers the verdict is `uninformative`.
- **Coverage.** 98% combined statement and branch coverage.

## Ruling made while planning (Andrew to check)

**The spec says to measure on `deviation_score`. The plan measures on `rms_z` instead.**
- Why: `deviation_score` is computed from `rms_z`, and `loo_distances` already holds each baseline paper's leave-one-out `rms_z`, cached. That removes the N extra scoring passes the spec worried about (spec decision 2), and no new storage is needed.
- What it costs: `loo_distances` is computed without per-feature weights. When weights change `rms_z` (adaptive, length-adaptive, characteristic `on`, topic inflation `on`), the two are not comparable.
- So the writer line abstains in exactly the cases where `typicality_band` is withheld today (`scoring.py` around line 1294), and uses the same condition.

## Review Focus

1. **Every baseline paper scores almost the same** (spread near 0), so one slightly odd paper becomes a huge z. Expected: the spread floor `WRITER_LINE_STD_FLOOR` caps z. The test lives in Task 1.
2. **Baseline papers that are all authenticated with zero weight** (`auth_weight == 0`). They don't count toward the minimum, so the result is a fallback. Task 2.
3. **A submission scored with weights that changed `rms_z`.** Expected: abstain, not a misleading z. Task 2.
4. **`rms_z` is NaN or infinite.** Expected: fallback, never `escalate`. Task 1.
5. **A writer whose papers vary a lot**, so the line goes so high nothing is ever flagged. Expected: the report counts writers whose `escalate` cut is unreachable. Task 3.

---

### Task 1: Pure z-score and tier helpers

**Files:**
- Create: `original/quantum/writer_line.py`
- Modify: `original/constants.py`, appending the new constants after `ACTION_THRESHOLDS` (no reordering)
- Test: `tests/quantum/test_writer_line.py`

**Interfaces:**
- Produces:
  - constants `WRITER_LINE_MIN_PAPERS = 3`, `WRITER_LINE_STD_FLOOR = 0.05`, and `WRITER_LINE_Z_THRESHOLDS: dict[str, tuple[float, float]]`, with placeholder bands `monitor >= 1.0`, `schedule_conversation >= 2.0`, `escalate >= 3.0` until Task 3 calibrates them;
  - `writer_z(rms_z: float, loo: list[float]) -> float | None`;
  - `writer_line_action(z: float | None, thresholds=WRITER_LINE_Z_THRESHOLDS) -> str | None`.

- [ ] **Step 1: Write failing tests**

```python
def test_too_few_papers_abstains():
    assert writer_z(1.0, [0.5, 0.6]) is None

def test_z_uses_own_mean_and_spread():
    assert writer_z(1.0, [0.5, 0.5, 0.8]) == pytest.approx((1.0 - 0.6) / max(np.std([0.5, 0.5, 0.8]), 0.05))

def test_spread_floor_caps_z():
    assert writer_z(0.6, [0.5, 0.5, 0.5]) == pytest.approx(0.1 / 0.05)

@pytest.mark.parametrize("bad", [float("nan"), float("inf")])
def test_non_finite_abstains(bad):
    assert writer_z(bad, [0.5, 0.6, 0.7]) is None
    assert writer_line_action(None) is None

def test_tier_bands():
    assert writer_line_action(0.5) == "no_action"
    assert writer_line_action(2.5) == "schedule_conversation"
    assert writer_line_action(9.0) == "escalate"
```

- [ ] **Step 2: Run them.** `.venv/bin/python -m pytest tests/quantum/test_writer_line.py -q`. Expected: import errors.
- [ ] **Step 3: Implement both helpers.** Use the population std (`np.std`, ddof 0) and bands of the form `lo <= z < hi`; anything at or above the top band is `escalate`.
- [ ] **Step 4: Run the tests.** Expected: they pass.
- [ ] **Step 5: Commit** with the message "Add per-writer line helpers (unused)".

### Task 2: Wire into `score()` behind `WRITER_LINE`

**Files:**
- Modify: `original/quantum/scoring.py`:
  - a `ScoringConfig` field `writer_line: str = "off"`, read from env next to `llr_action_mode` (around line 677);
  - the call site between `_recommend` and the LLR step (around lines 1561-1590);
  - result fields `writer_line_z: float | None = None` and `writer_line_action: str | None = None`.
- Modify: `original/routers/students_scoring.py`, adding one INFO log line `writer_line mode=… outcome=applied|abstain|shadow would=… z=…` with no student ids.
- Test: `tests/quantum/test_writer_line.py`; add to `tests/config/test_flag_byte_identity.py`.

**Interfaces:**
- Consumes `writer_z`, `writer_line_action` and `state.loo_distances`.
- Produces the result fields above, which Task 3 reads.

- [ ] **Step 1: Write failing tests:**
  - `test_off_is_byte_identical`: the same input with `off` and with the env var unset gives equal `Layer7Output`.
  - `test_shadow_changes_no_field_but_sets_diagnostics`: `recommendation.action` and `deviation_score` match `off`; `writer_line_z` is set.
  - `test_on_replaces_base_tier`: a state with 4 tight baseline papers and a far submission becomes `schedule_conversation` or higher, where `off` gives a lower tier.
  - `test_on_still_lets_gate_lower_one_step`: a confident-genuine llr (≤ 0.35) under `impostor` lowers the writer-line tier one step.
  - `test_on_catastrophic_drift_still_escalates`.
  - `test_on_abstains_below_min_papers`.
  - `test_on_abstains_when_weights_modify_rms_z`, using the same withhold condition as typicality.
  - `test_zero_auth_weight_papers_do_not_count`.
- [ ] **Step 2: Run them.** Expected: they fail.
- [ ] **Step 3: Implement.** On `on` with a non-None action, rebuild the `RecommendedAction` with that action and a rationale naming the z. Keep the confidence of the original recommendation.
- [ ] **Step 4: Run** `tests/quantum/` and `tests/config/test_flag_byte_identity.py`. The 30 local byte-identity failures caused by this venv's sentence-transformers backend are known; compare against base.
- [ ] **Step 5: Ask `score-integrity-reviewer`** for flag-off identity and shadow purity before committing.
- [ ] **Step 6: Commit** with the message "Add WRITER_LINE mode (default off)".

### Task 3: Records, harness and the `G-WRITERLINE` gate

**Files:**
- Modify: `validation/verify/run_null_model.py`. Each `extra.pairs` row gains `rms_z` and `loo` (that baseline's `loo_distances`).
- Create: `validation/writer_line/__init__.py`, `validation/writer_line/harness.py` and `validation/writer_line/run.py`. Reuse `split_by_author` and `rates` from `validation/rebind/harness.py`, adding a `writer_line` mode.
- Modify:
  - `validation/calibration_gate.py`: `evaluate_g_writerline` and `"G-WRITERLINE"` in `GATE_LEGS`, registered like G-REBIND;
  - `validation/gate_contracts.py`: the witness.
- Regenerate: `validation/rebind/records/*.json`, now with `rms_z` and `loo`.
- Test: `tests/validation/test_writer_line_harness.py`.

**Interfaces:**
- Produces:
  - `select_z_thresholds(derivation, max_fpr=0.05) -> dict`, with genuine values only and `escalate` at `max_fpr / 5`;
  - `evaluate_g_writerline(holdout, thresholds) -> GateResult`;
  - a report with `writers_escalate_unreachable` per corpus (Review Focus 5).

- [ ] **Step 1: Write failing tests:**
  - a pass fixture where the writer line beats gate;
  - the witness fixture, where the writer line raises false alarms above gate, gives `fail`;
  - n_genuine 29 gives `uninformative`;
  - records lacking `loo` raise a clear "re-run run_null_model.py" error;
  - thresholds use derivation genuine z only.
- [ ] **Step 2: Run them.** Expected: they fail.
- [ ] **Step 3: Implement,** then regenerate the records with `NULL_MODEL=impostor`.
- [ ] **Step 4: Run** `.venv/bin/python -m validation.writer_line.run --records validation/rebind/records/*.json --seed 20261116 --out validation/writer_line/report_2026-11-16.json`. Record the verdict as-is. `uninformative` is expected.
- [ ] **Step 5: Copy the calibrated z bands** into `WRITER_LINE_Z_THRESHOLDS`. Re-run the Task 1 and 2 tests and update the placeholder-dependent assertions.
- [ ] **Step 6:** run `python -m validation.calibration_gate --strict` and `tests/test_gate_falsifiability.py`.
- [ ] **Step 7: Commit** with the message "Add G-WRITERLINE gate and calibrate per-writer cut-offs".

### Task 4: Docs

**Files:** `CLAUDE.md` (a new flag-table row after `LLR_ACTION_MODE`), `MODEL_CARD.md`, `docs/STATUS.md`.

- [ ] **Step 1:** Add the row.
  - Content: what it does; that it uses `loo_distances` and `rms_z`; that it abstains below 3 papers and under weight-modifying flags; that it does not help first papers.
  - Results: the exploratory numbers (49.6% catch, 6.1% false alarms over 200 splits, not a validation result) and the Task 3 verdict.
  - Instruction: "Run `shadow` first; do not set `on` before G-WRITERLINE passes on a larger honest corpus."
- [ ] **Step 2:** Add the MODEL_CARD entry and one STATUS log line.
- [ ] **Step 3: Commit** with the message "Document WRITER_LINE".

## Not in this plan

Growing the honest corpus to about 74 or more genuine papers, so the gate can return an answer. It is its own task once this lands.
