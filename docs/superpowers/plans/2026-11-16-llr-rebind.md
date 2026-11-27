# LLR rebind action mode Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `LLR_ACTION_MODE=rebind`, which lets `llr_deviation_score` set the recommended action tier. It is default-off, logged in shadow, and judged by a new G-REBIND gate.

**Architecture:**
- There is one new candidate in `_llr_action_candidates`, tier-mapped by a new constant.
- `shadow` mode logs it.
- A pure harness reads the per-pair records that `validation/verify/run_null_model.py` already produces, picks the cut-offs on a derivation split, and scores a held-out split through `evaluate_g_rebind`.

**Tech Stack:** Python 3.11, pytest, numpy (all existing).

**Spec:** `docs/superpowers/specs/2026-11-16-llr-rebind-design.md`

## Global Constraints

- The default stays `LLR_ACTION_MODE=gate`. `gate`, `shadow`, `trigger` and `blend` output must stay byte-identical to `main`.
- `rebind` applies only where `null_model == "impostor"` and `llr_deviation_score is not None`. Everywhere else the behaviour is today's, exactly.
- The catastrophic-drift `escalate` override is unchanged.
- Cut-offs are chosen on the derivation split only. The hold-out is never used for selection.
- G-REBIND passes only if all of these hold on the hold-out:
  - catch at `schedule_conversation`+ is above `gate` mode's;
  - honest false-alarm rate at `schedule_conversation`+ is ≤ 5% and ≤ `gate` mode's;
  - honest false-alarm rate at `escalate` is ≤ `gate` mode's.
- If the Wilson upper bound of a 0-false-alarm result is above 5% at the available n, the verdict is `uninformative`.
- Every new `evaluate_g*` needs a failure witness in `validation/gate_contracts.py`.
- Use `.venv/bin/python` only. Coverage must stay at 98% or above, statement plus branch.
- Work on branch `claude/llr-rebind` in its own worktree, never in the shared `session-9cf400` folder.
- Do not change `ALL_FEATURE_CODES` or `NORM_BOUNDS`.

## Review Focus

- **`llr_deviation_score` exactly on a cut-off** (for example 0.60). It must land in the higher tier, matching how `ACTION_THRESHOLDS` treats `lo <= x < hi`. Tested in Task 1.
- **`llr_deviation_score` of 1.0 or above, or 0.0.** These map to `escalate` and `no_action`, with no exception. Tested in Task 1.
- **An unknown mode string.** It still raises `ValueError`, so a typo in the env var can't silently mean "off". Tested in Task 1.
- **A corpus with no impostor-pair records, or n too small for 5%.** The gate returns `uninformative`, never `pass`. Tested in Task 3.
- **The derivation and hold-out splits sharing an author.** The harness refuses to run. Tested in Task 3.

---

### Task 1: `rebind` candidate and mode

**Files:**
- Modify: `original/quantum/scoring.py`. Add `LLR_REBIND_THRESHOLDS` near line 2210 and change `_llr_action_candidates` (line 2214) and `_apply_llr_action_mode` (line 2246).
- Test: `tests/quantum/test_llr_action_modes.py`, `tests/config/test_flag_byte_identity.py`

**Interfaces:**
- Produces: `LLR_REBIND_THRESHOLDS: dict[str, tuple[float, float]]`, keyed exactly like `original/constants.py:706` `ACTION_THRESHOLDS`.
  - Initial values are `{"no_action": (0.0, 0.40), "monitor": (0.40, 0.60), "schedule_conversation": (0.60, 0.75), "escalate": (0.75, 1.0)}`.
  - They are placeholders until Task 4, which is safe because the mode is off by default.
- Produces: `_rebind_action(llr_deviation_score: float, thresholds: dict[str, tuple[float, float]] = LLR_REBIND_THRESHOLDS) -> str`.
- Produces: `_llr_action_candidates(...)` returns a dict that now also carries a `"rebind"` key.

- [ ] **Step 1: Write the failing tests.** All of them go in `tests/quantum/test_llr_action_modes.py`.
  - `test_rebind_action_maps_tiers`. Using the placeholder table:
    - `_rebind_action(0.10) == "no_action"`
    - `_rebind_action(0.40) == "monitor"`
    - `_rebind_action(0.599) == "monitor"`
    - `_rebind_action(0.60) == "schedule_conversation"`
    - `_rebind_action(0.75) == "escalate"`
    - `_rebind_action(1.0) == "escalate"`
    - `_rebind_action(1.7) == "escalate"`
  - `test_rebind_mode_replaces_action`. `_apply_llr_action_mode(RecommendedAction("no_action", 0.5, "r"), 0.2, 0.8, "rebind").action == "escalate"`, and its rationale contains `"LLR rebind"`.
  - `test_rebind_mode_can_lower_to_no_action`. Start from `"escalate"` with llr 0.1. The result is `"no_action"`.
  - `test_unknown_mode_still_raises`. Mode `"rebnd"` raises `ValueError`.
  - `test_rebind_needs_impostor_null`. Call `score()` with `ScoringConfig(null_model="none", llr_action_mode="rebind")`. Its action equals the same call with `llr_action_mode="gate"`.
- [ ] **Step 2: Run the tests and see them fail.** `.venv/bin/python -m pytest tests/quantum/test_llr_action_modes.py -q`. Expected: FAIL, `_rebind_action` not defined.
- [ ] **Step 3: Implement `_rebind_action`.**
  - Use the same `lo <= x < hi` loop as the blend branch, with a `>= 1.0` clamp to `escalate`.
  - Add `"rebind": _rebind_action(llr_deviation_score)` to the candidates dict.
  - Add `"rebind"` entries to `_verbs` ("rebound") and to `_reasons`. The reason reads: `f"action tier set from llr_deviation_score={llr_deviation_score:.3f} (peer-relative)."`
  - Extend the `ScoringConfig.llr_action_mode` docstring to describe `rebind`.
- [ ] **Step 4: Run the tests and see them pass.** Same command as Step 2. Expected: PASS.
- [ ] **Step 5: Check byte identity.** `.venv/bin/python -m pytest tests/config/test_flag_byte_identity.py tests/quantum/ -q`. Expected: 0 failed.
- [ ] **Step 6: Commit.** Use `git commit -m "Add LLR_ACTION_MODE=rebind (default off)"` with the co-author trailer.

### Task 2: Shadow logs `rebind_would`

**Files:**
- Modify: `original/quantum/scoring.py`, the `shadow` log line in `_apply_llr_action_mode`.
- Test: `tests/quantum/test_llr_action_modes.py`

**Interfaces:** consumes the `"rebind"` key from Task 1.

- [ ] **Step 1: Write the failing test.** `test_shadow_logs_rebind_would` uses `caplog` at INFO. With llr 0.8 under `"shadow"`, the log contains `"rebind_would=escalate"`, and the returned recommendation `is` the input object.
- [ ] **Step 2: Run the test and see it fail.** Expected: FAIL.
- [ ] **Step 3: Add the field.** Put ` rebind_would=%s` after `blend_would=%s` and pass `candidates["rebind"]`.
- [ ] **Step 4: Run the test and see it pass,** together with `tests/config/test_flag_byte_identity.py`. Expected: PASS.
- [ ] **Step 5: Commit.** Use `git commit -m "Log rebind_would in LLR shadow mode"`.

### Task 3: G-REBIND harness and gate

**Files:**
- Create: `validation/rebind/__init__.py`
- Create: `validation/rebind/harness.py`
- Modify: `validation/calibration_gate.py`. Add `evaluate_g_rebind` and register it in `run_all()` (line 2302), following the G7 pattern so that a missing corpus gives `uninformative`.
- Modify: `validation/gate_contracts.py`. Add a witness.
- Test: `tests/validation/test_rebind_harness.py`

**Interfaces:**
- Consumes: `_llr_action_candidates` from `original.quantum.scoring`.
- Produces: `PairRecord`, a frozen dataclass with these fields:
  - `author: str`
  - `genuine: bool`
  - `deviation: float`
  - `llr: float`
  - `corpus: str`
- Produces: `load_records(path: Path) -> list[PairRecord]`. It reads `run_null_model.py`'s JSON output, and the implementer maps its same-pair and diff-pair keys.
- Produces: `split_by_author(records, seed: int, derivation_frac: float = 0.6) -> tuple[list[PairRecord], list[PairRecord]]`. It raises `ValueError` if any author ends up on both sides.
- Produces: `select_thresholds(derivation: list[PairRecord], max_fpr: float = 0.05) -> dict[str, tuple[float, float]]`.
  - It picks the `schedule_conversation` cut-off as the lowest llr value whose genuine false-alarm rate is at or below `max_fpr`.
  - It picks the `escalate` cut-off the same way, at `max_fpr / 5`.
  - `monitor` is set to `schedule_conversation − 0.15`, floored at 0.
- Produces: `rates(records, mode: str, thresholds) -> dict` with keys:
  - `catch_sc`: share of impostor pairs at `schedule_conversation`+;
  - `fa_sc`: share of genuine pairs at `schedule_conversation`+;
  - `fa_esc`: share of genuine pairs at `escalate`;
  - `n_genuine`;
  - `n_impostor`.

  The `gate` mode's action is derived from `deviation` through `ACTION_THRESHOLDS` and then `_llr_action_candidates(...)["gate"]`.
- Produces: `evaluate_g_rebind(holdout: list[PairRecord], thresholds: dict) -> GateResult`, named `"G-REBIND"`. It follows the Global Constraints criterion, with a Wilson 95% upper bound for the uninformative rule. `detail` carries both modes' `rates`.

- [ ] **Step 1: Write the failing tests.**
  - `test_split_refuses_shared_author`. Hand-built records with an overlapping author raise `ValueError`.
  - `test_select_thresholds_respects_fpr`. 100 genuine llr values spread evenly from 0 to 0.5, plus 100 impostor values from 0.5 to 1. The selected `schedule_conversation` lower bound gives `fa_sc <= 0.05` on the same records.
  - `test_gate_passes_on_separable`. 400 genuine at llr 0.1, 400 impostor at llr 0.9, deviation 0.7 for all of them (so `gate` has a high false-alarm rate). The verdict is `"pass"`.
  - `test_gate_fails_when_rebind_worse`. Impostor llr is 0.1 and genuine llr is 0.9. The verdict is `"fail"`.
  - `test_gate_uninformative_small_n`. 10 genuine and 10 impostor, otherwise separable. The verdict is `"uninformative"`.
  - `test_gate_uninformative_no_impostors`. The verdict is `"uninformative"`.
- [ ] **Step 2: Run the tests and see them fail.** `.venv/bin/python -m pytest tests/validation/test_rebind_harness.py -q`. Expected: FAIL, import error.
- [ ] **Step 3: Implement the harness functions and `evaluate_g_rebind`** with the signatures above.
- [ ] **Step 4: Register the failure witness** in `GATE_CONTRACTS`, using the inverted-separation input from `test_gate_fails_when_rebind_worse`. Pass every argument after the first by keyword, as the SIGNATURE TRAP note at the top of that file requires.
- [ ] **Step 5: Run the tests and see them pass.** `.venv/bin/python -m pytest tests/validation/test_rebind_harness.py tests/test_gate_falsifiability.py -q`. Expected: PASS.
- [ ] **Step 6: Commit.** Use `git commit -m "Add G-REBIND gate and calibration harness"`.

### Task 4: Measure, set the cut-offs, document

**Files:**
- Create: `validation/rebind/run.py`, a CLI with `--records <json>... --seed 20261116 --out <json>`.
- Create: `validation/rebind/report_2026-11-16.json`
- Modify:
  - `original/quantum/scoring.py`: set `LLR_REBIND_THRESHOLDS` to the selected values;
  - `CLAUDE.md`: the `LLR_ACTION_MODE` row;
  - `MODEL_CARD.md`;
  - `docs/STATUS.md`.

- [ ] **Step 1: Produce the records.**
  - Run `validation/verify/run_null_model.py --baselines 3` on seminary, `public_authors` and the PAN 20 cross-fandom corpus, each with its manifest. Note the exact commands in the report.
  - Run them in the background, because they take minutes.
- [ ] **Step 2: Run the harness.** `.venv/bin/python -m validation.rebind.run --records <the three outputs> --seed 20261116 --out validation/rebind/report_2026-11-16.json`.
  - Expected: a JSON file with the thresholds, the per-corpus hold-out `rates` for `gate` and `rebind`, and a `verdict`.
- [ ] **Step 3: Set `LLR_REBIND_THRESHOLDS`** to the report's thresholds, then re-run the Task 1 tests. A changed value breaks `test_rebind_action_maps_tiers`, so update that test's expected values to the new table.
- [ ] **Step 4: Run the strict gate.** `.venv/bin/python -m validation.calibration_gate --strict --only G-REBIND`. Record the verdict exactly as printed, including `uninformative`.
- [ ] **Step 5: Write the docs.**
  - The CLAUDE.md row says what `rebind` is, its hold-out numbers per corpus with their corpus names, and its G-REBIND verdict. It also says it is not validated on real students and that shadow comes first.
  - MODEL_CARD.md gets the same numbers.
  - STATUS gets one session-log line.
- [ ] **Step 6: Run the full CI command.** `.venv/bin/python -m pytest tests/ validation/test_tier10_optional.py -m "not blocker and not certification" -q`, then `.venv/bin/ruff check original/` and `ruff format --check original/`. Expected: 0 failed.
- [ ] **Step 7: Commit, push, and open a PR.** Use `git commit -m "Calibrate rebind cut-offs and record G-REBIND result"`, push `claude/llr-rebind`, and open the PR with the AGENTS.md checklist. Never merge it.
