# Rule D Adversarial Study Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Score rule D on the six cheating tests' own cells (G-A1 to G-A5), next to a fresh run of
the existing scorer on the same documents. Pre-register the bars, open once, and write it up.

**Architecture:** A study package under `validation/adversarial/` covers five jobs:
- builds each victim's class;
- scores rule D in-process with `original.rule_d.core.observe`;
- writes rule D rows in the battery's own row schema;
- judges both columns with the battery's unchanged reducers (`report.py`) and gate evaluators
  (`calibration_gate.py`);
- guards the single opening with git checks and a log.

Nothing under `original/`, and none of `report.py`, `runner.py`, `calibration_gate.py` or
`imitation_controls.py`, is modified.

**Tech Stack:** Python 3.11, numpy, pytest, FastAPI `TestClient` (via the runner), git CLI.

**Spec:** `docs/superpowers/specs/2026-11-27-rule-d-adversarial-study-design.md` (approved by Andrew
2026-11-27). Read it first; section numbers below (§N) refer to it.

## Global Constraints

- Use `.venv/bin/python` from the checkout root. A new worktree needs its own venv
  (`python3.11 -m venv .venv`, then install per README), never system python3.
- No edits under `original/`, nor to `validation/adversarial/report.py`, `runner.py`,
  `imitation_controls.py` or `validation/calibration_gate.py`. Import, don't copy, except where a
  task says "mirror" and pins the mirror with a test.
- Rule D exactly as shipped: `core.THRESHOLDS`, the vectorizer artifact, `MIN_PEER_STUDENTS = 3`,
  `MIN_PEER_PAPERS = 5`, `MIN_NEW_WORDS = 250`.
- Seed `report.HARNESS_SEED` (20260920), `report.NS = (3, 5, 10)`, scoring env
  `report.LIVE_SCORING_ENV` plus `RULE_D_OBSERVATION=off` for the existing-scorer run.
- Study id `rule-d-adversarial-2026-11`. RJ class size 20, floor class 3.
- No D value, flag, rate or AUROC is printed or written without `--open`.
- No dash characters U+2014 or U+2015 in any file or commit message.
- Commits: conventional (`Add ...`, `Fix ...`), ending with
  `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Branch `claude/rule-d-adversarial-study`;
  never push to `main`.
- Everything runs locally; no text leaves the machine.

## Review Focus

1. A cell whose existing-scorer row says `scoring_refused`: rule D must record it as refused, not
   score the papers left over. (Task 3)
2. A classmate whose papers are all held by the drift gate drops out, and the class can fall below
   rule D's floor. The documents then come back inconclusive rather than erroring. (Task 3)
3. An impostor document dropped as a leak or as inconclusive must not shift positions: the
   battery's `kept_impostors` indexes by position. (Task 3)
4. A population more than half inconclusive must not read `pass`. (Task 4)
5. A crash after `started` is logged must block a plain re-open. A completed study must block
   every re-open. (Task 6)

---

### Task 1: Classes and readings

**Files:**
- Create: `validation/adversarial/rule_d_classes.py`
- Test: `tests/adversarial/test_rule_d_classes.py`

**Interfaces:**
- Consumes: `report._digest(value: str) -> str`, `report._rj_order(chunks) -> list[str]`,
  `profiles.VictimProfile`.
- Produces:
  - `RJ_CLASS_SIZE = 20`, `FLOOR_CLASS_SIZE = 3`,
    `READINGS = ("classmate_essay", "outside_writer", "floor")`.
  - `@dataclass(frozen=True) class Classmate: writer_id: str; papers: tuple[str, ...]`
  - `@dataclass(frozen=True) class ReadingPlan: reading: str; genuine_class: tuple[Classmate, ...];
    impostor_classes: tuple[tuple[Classmate, ...], ...]`. There is one entry of
    `impostor_classes` per impostor document, in document order.
  - `sha(text: str) -> str` (hex SHA-256 of the UTF-8 text).
  - `public_author_plans(victim: VictimProfile, others: list[VictimProfile]) -> list[ReadingPlan]`.
    `others` holds every other victim at the same N. This returns `classmate_essay` and
    `outside_writer` (§3).
  - `rj_plans(victim_id: str, impostor_docs: list[str], control_essays: dict[str, str],
    chunks_by_pid: dict[str, list[str]], n: int, seed: int) -> list[ReadingPlan]`. This returns
    `classmate_essay`, `outside_writer` and `floor`.

- [ ] **Step 1: Write the failing tests**

  - `test_public_author_classmates_drop_their_first_paper`: three victims a, b, c with baselines
    `["a0","a1","a2"]` and so on. For victim a, every classmate in `classmate_essay` has
    `papers == ("b1","b2")` / `("c1","c2")`.
  - `test_public_author_outside_writer_removes_the_source`: a's impostor docs are `["b0","c0"]`.
    `impostor_classes[0]` has no writer b, and `impostor_classes[1]` has no writer c. The
    `genuine_class` keeps both.
  - `test_public_author_classmate_essay_uses_one_class_for_every_document`: every entry of
    `impostor_classes` equals `genuine_class`.
  - `test_rj_sources_are_found_by_text`: impostor docs equal to `control_essays["p1"]` and
    `control_essays["p2"]` give sources `{"p1","p2"}`. A doc matching no essay raises `ValueError`.
  - `test_rj_draw_excludes_sources_and_is_seeded`: 30 eligible writers, 5 sources.
    - `outside_writer` has 20 writers, none of them a source and none the victim.
    - The same call twice gives the same order.
    - `classmate_essay` is those 20 plus the 5 sources.
    - `floor` is the first 3 of the 20.
  - `test_rj_eligibility_and_papers`: a writer with fewer than n chunks is never drawn. Each
    classmate's papers are their first n chunks in `_rj_order`.
  - `test_rj_takes_all_when_fewer_than_20_eligible`: 8 eligible writers give an `outside_writer`
    class of 8.

- [ ] **Step 2: Run to verify they fail**

  Run: `.venv/bin/python -m pytest tests/adversarial/test_rule_d_classes.py -q`
  Expected: FAIL with `ModuleNotFoundError: validation.adversarial.rule_d_classes`.

- [ ] **Step 3: Implement the interfaces above.**

  - The RJ draw order is `sorted(eligible - sources - {victim},
    key=lambda p: _digest(f"{seed}:rj-class:{victim_id}:{p}"))`.
  - Sources are found by matching each impostor doc's `sha` against `control_essays`.
  - In `classmate_essay`, sources are appended in impostor-doc order.

- [ ] **Step 4: Run to verify they pass**

  Run: `.venv/bin/python -m pytest tests/adversarial/test_rule_d_classes.py -q`
  Expected: all pass.

- [ ] **Step 5: Commit**

  `git add validation/adversarial/rule_d_classes.py tests/adversarial/test_rule_d_classes.py`
  then `git commit -m "Add classes and readings for the rule D adversarial study"`.

### Task 2: Admission, scored texts and the profile cache

**Files:**
- Create: `validation/adversarial/rule_d_inputs.py`
- Test: `tests/adversarial/test_rule_d_inputs.py`

**Interfaces:**
- Consumes:
  - `runner._post_baseline(client, student_id, text, assignment) -> bool` (True = held);
  - `runner._new_student_id(victim_id, attack) -> str`;
  - `runner._default_api_client()`, `runner._submission_seed(victim_id) -> int`,
    `runner._maybe_transform`;
  - `generators.MechanicalObfuscation(seed=...)`, `poisoning.poison_profile(profile, attack)`;
  - `core.build_paper_profile`, `original.features.pipeline.feature_vector`.
- Produces:
  - `scored_texts(cell: report.Cell) -> tuple[list[str], list[str], list[str]]`, returning
    `(baselines, holdouts, impostors)` exactly as `runner.run_attack` derives them. For
    `obfuscated_baselines`, `outsourced_baselines` and `sigma_inflation` the baselines are poisoned.
    For `mechanical_obfuscation` the holdouts and impostors are transformed. Otherwise everything
    is unchanged.
  - `class Admission: __init__(self, client=None); held(self, texts: list[str]) -> list[int]`. It
    posts each text to one fresh throwaway student, in order, and returns the held indices. Results
    are cached on `tuple(sha(t) for t in texts)`.
  - `class ProfileCache: vector(self, text) -> np.ndarray; profile(self, text, label) -> dict`. It
    uses `feature_vector` for both the paper vector and `feature_fn`, with `with_pieces=True`, and
    is cached by `sha`.

- [ ] **Step 1: Write the failing tests**

  - `test_scored_texts_matches_run_attack`: monkeypatch `runner._run_api_path` to capture its
    `baseline_texts`, `holdout_texts` and `impostor_texts`. Run `runner.run_attack(profile, attack,
    path="api")` on a small fixture profile for each of `"none"`, `"sigma_inflation"` and
    `"mechanical_obfuscation"`. Assert `scored_texts` returns the same three lists.
  - `test_admission_returns_held_indices_and_caches`: a fake client returns 200, 202, 200, 409.
    `held(["a","b","c","d"]) == [1, 3]`. A second identical call makes no request.
  - `test_admission_raises_on_unexpected_status`: a 500 raises `RuntimeError`.
  - `test_profile_cache_extracts_each_text_once`: monkeypatch `feature_vector` with a counter.
    Two `profile()` calls on the same text extract the paper once, plus once per 300-word piece.

- [ ] **Step 2: Run to verify they fail**

  Run: `.venv/bin/python -m pytest tests/adversarial/test_rule_d_inputs.py -q`
  Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement.** `scored_texts` mirrors `runner.run_attack`'s derivation of the scored
  texts. The test above pins that mirror.

- [ ] **Step 4: Run to verify they pass**

  Run: `.venv/bin/python -m pytest tests/adversarial/test_rule_d_inputs.py -q`
  Expected: all pass.

- [ ] **Step 5: Commit** both files: `Add admission, scored texts and profile cache for the rule D study`.

### Task 3: Scoring rule D rows

**Files:**
- Create: `validation/adversarial/rule_d_score.py`
- Test: `tests/adversarial/test_rule_d_score.py`

**Interfaces:**
- Consumes: Task 1 `ReadingPlan`, `Classmate`, `sha`; Task 2 `scored_texts`, `Admission`,
  `ProfileCache`; `core.observe`, `core.word_count`, the `core` floor constants;
  `report.live_scoring_env()`.
- Produces:
  - `FLAG_ACTION = "monitor"`, `CLEAR_ACTION = "no_action"`.
  - `floor_reason(new_text: str, claimed: list[dict], peers: dict[str, list[dict]]) -> str | None`.
    It returns the reason `core.observe` would give for `inconclusive`, or None, without computing D.
  - `score_cell(cell, existing_row: dict, plans: list[ReadingPlan], *, cache, admission,
    dry_run: bool) -> list[dict]`, returning one row per plan.
- **Row schema:** these keys are copied from `existing_row`: `corpus`, `kind`, `n`, `victim_id`,
  `injected_indices`, `held_baseline_indices`, `scoring_refused`, `mean_baseline_std`. Plus:
  - `reading`;
  - `holdout_obs` and `impostor_obs`: per position, `Observation.as_dict()` or
    `{"status": "leaked"}` / `{"status": "refused"}`. In a dry run this is just
    `{"status", "reason"}`, with no index or flag;
  - `holdout_actions`, `holdout_scores`, `impostor_actions`, `impostor_scores`: only observed
    documents, with leaked positions removed;
  - `impostor_in_baseline: []`;
  - `n_inconclusive`, `n_leak_dropped`, `class_size`, `class_ids`.

  Action is `FLAG_ACTION` when `reads_less_like_student`, else `CLEAR_ACTION`; score is
  `Observation.index`.
- Claimed papers are the scored baselines minus `existing_row["held_baseline_indices"]`.
  Classmates' papers are their papers minus `admission.held(papers)`. A classmate left with none
  is dropped.
- Leaks are the positions in `existing_row["impostor_in_baseline"]`, plus any scored document whose
  `sha` matches a claimed or classmate paper.

- [ ] **Step 1: Write the failing tests** (fixtures stub `core.observe` with a fake returning
  fixed `Observation`s, and `Admission` with a dict):

  - `test_refused_cell_is_refused_not_scored`: `existing_row["scoring_refused"] = True` gives every
    obs `{"status": "refused"}` and empty action lists, and `observe` is never called.
  - `test_held_papers_are_left_out`: held index 1 means the claimed profiles passed to `observe`
    exclude baseline 1.
  - `test_classmate_with_every_paper_held_drops_out`: that writer is absent from the `peers`
    passed to `observe`, and `class_size` counts only the rest.
  - `test_below_floor_is_inconclusive_not_an_error` (real `core.observe`, 2 classmates): status is
    `inconclusive`, it is counted in `n_inconclusive`, and it is absent from the score lists.
  - `test_leaks_and_inconclusive_keep_positions_aligned`: impostors at positions 0, 1 and 2, where
    position 0 leaks and position 1 is inconclusive. Then `impostor_obs[0]["status"] == "leaked"`,
    `impostor_scores == [D of position 2]`, and `impostor_in_baseline == []`.
  - `test_flag_maps_to_monitor`: flagged gives `"monitor"`, not flagged gives `"no_action"`.
  - `test_floor_reason_agrees_with_observe`: for each of no claimed papers, 2 classmates, 4 peer
    papers, and a 200-word text, `floor_reason` is non-None exactly when `core.observe` returns
    `inconclusive`. Both are run on the same fixture.
  - `test_dry_run_never_calls_observe_and_writes_no_index`: in a dry run no obs contains `index`
    or `reads_less_like_student`.

- [ ] **Step 2: Run to verify they fail**

  Run: `.venv/bin/python -m pytest tests/adversarial/test_rule_d_score.py -q`
  Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement** `floor_reason` and `score_cell`. The whole call runs inside
  `report.live_scoring_env()`. `floor_reason` mirrors the three checks at the top of
  `core.observe`, and the agreement test pins the mirror.

- [ ] **Step 4: Run to verify they pass**

  Run: `.venv/bin/python -m pytest tests/adversarial/test_rule_d_score.py -q`
  Expected: all pass.

- [ ] **Step 5: Commit** both files: `Add rule D row scoring for the adversarial study`.

### Task 4: Populations and verdicts for both columns

**Files:**
- Create: `validation/adversarial/rule_d_verdicts.py`
- Test: `tests/adversarial/test_rule_d_verdicts.py`

**Interfaces:**
- Consumes:
  - `report.ga1_inputs`, `report.attack_populations`, `report.peer_swap_populations`,
    `report.ga5_inputs`;
  - `calibration_gate.evaluate_g_a1_cold_start_fpr`, `evaluate_g_a2_imitation`,
    `evaluate_g_a3_paraphrase`, `evaluate_g_a4_peer_imitation`, `evaluate_g_a5_sigma_inflation`;
  - the helpers `_ga_rate_leg`, `_ga_auc_leg`, `_ga_result`, `_GA_SIGMA_DROP_BAR`, and `GateResult`.
- Produces:
  - `COUNTING = ("G-A1 public_authors", "G-A1 riddell_juola", "G-A2 length-matched", "G-A3",
    "G-A4 riddell_juola", "G-A5")`.
  - `as_clean(slice_rows: list[dict]) -> list[dict]`: `genuine_slice` rows relabelled `kind="clean"`
    so `attack_populations` uses them as G-A2's comparator.
  - `ga5_rule_d(cells: list[dict]) -> GateResult`: the gate's drop and AUROC legs and its
    "no inflated baseline scored" and "clean catch <= 10%" reasons, but **not** the sigma-growth
    reason (§5). Sigma values go to `detail["sigma"]`.
  - `downgrade_if_mostly_inconclusive(result: GateResult, counts: dict[str, tuple[int, int]])
    -> GateResult`. Here `counts` maps population name to (inconclusive, total). A `pass` with any
    population more than half inconclusive becomes `uninformative`, with a reason. `fail` stays
    `fail`, by the gates' "a measured failure is never softened" rule.
  - `verdicts(rows: list[dict], slice_rows: list[dict], cut_rows: list[dict], *, column: str)
    -> dict[str, GateResult]`. `column` is `"rule_d"` or `"existing"`. For rule D, each result goes
    through `downgrade_if_mostly_inconclusive`, with counts from the rows' `n_inconclusive` and their
    obs lists. Keys:
    - the counting names;
    - for rule D, readings suffixed (`"G-A1 riddell_juola classmate_essay"`, `"... outside_writer"`,
      the same for G-A4);
    - report-only keys: `"G-A2 uncut"`, `"G-A4 public_authors <reading>"`,
      `"mechanical_obfuscation"`, `"rj_self_obfuscation"`, `"rj_self_imitation"`,
      `"floor G-A1"`, `"floor G-A4"`, `"N3 cut 2500"`.

    For rule D, `"G-A1 riddell_juola"` is `pass` only when both reading verdicts pass (§5). Rows are
    filtered by corpus, kind and reading before each reducer.
  - `victim_bootstrap(pop_rows: list[dict], stat, *, reps: int = 2000, seed: int = HARNESS_SEED)
    -> list[float]`: a 95% interval resampling victims. Reported in `detail`, never deciding.

- [ ] **Step 1: Write the failing tests** (hand-built rows in the harness schema):

  - `test_ga1_split_by_corpus`: public-author and RJ rows give two independent results.
  - `test_rj_ga1_needs_both_readings`: `classmate_essay` passes but `outside_writer` fails, so
    `"G-A1 riddell_juola"` reads `fail`.
  - `test_ga2_length_matched_uses_slices`: the `G-A2 length-matched` comparator scores equal the
    slice rows' holdout scores, and `G-A2 uncut` uses the clean rows'.
  - `test_ga5_rule_d_ignores_sigma_growth`: with identical clean and inflated sigma,
    `ga5_rule_d` can pass, while `evaluate_g_a5_sigma_inflation` on the same cells reads
    `uninformative`.
  - `test_mostly_inconclusive_downgrades_pass_only`: `pass` with 6 of 10 inconclusive becomes
    `uninformative`, and `fail` stays `fail`.
  - `test_existing_column_has_no_readings`: `column="existing"` produces no reading-suffixed keys.
  - `test_victim_bootstrap_is_seeded`: two calls give equal intervals.

- [ ] **Step 2: Run to verify they fail**

  Run: `.venv/bin/python -m pytest tests/adversarial/test_rule_d_verdicts.py -q`
  Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement.** `ga5_rule_d` builds its legs with `_ga_rate_leg` and `_ga_auc_leg`
  exactly as `evaluate_g_a5_sigma_inflation` does, minus the sigma reason. The sigma test pins
  that difference.

- [ ] **Step 4: Run to verify they pass**

  Run: `.venv/bin/python -m pytest tests/adversarial/test_rule_d_verdicts.py -q`
  Expected: all pass.

- [ ] **Step 5: Commit** both files: `Add both columns' verdicts for the rule D study`.

### Task 5: Study cells, the existing-scorer run, and the CLI dry run

**Files:**
- Create: `validation/adversarial/rule_d_study.py`
- Test: `tests/adversarial/test_rule_d_study.py`

**Interfaces:**
- Consumes: Tasks 1-4; `report.build_cells`, `report.run_cells`, `report.run_harness`;
  `imitation_controls.cut_words`; `generators.LLMImitation`;
  `fetch_riddell_juola.load_riddell_juola_baselines`, `load_riddell_juola_split_by_id`.
- Produces:
  - `STUDY_KINDS`, the ten kinds in §1's table: `clean`, `rj_clean`, the four `llm_*`,
    `sigma_inflation`, `mechanical_obfuscation`, `rj_self_obfuscation`, `rj_self_imitation`.
  - `slice_cells(cells) -> list[Cell]`, with `kind="genuine_slice"`, `corpus="controls"`, and the
    slices in `genuine_holdout`. W is that victim's imitation word count at that N.
  - `cut_cells(cells, words=2500) -> list[Cell]`. It uses N=3 public-author `clean` and
    `sigma_inflation` cells only, with every baseline, holdout and impostor document cut by
    `cut_words`, and `kind` suffixed `"_cut2500"`.
  - `run_existing(out: Path, workers: int | None) -> dict`. It sets `os.environ["RULE_D_OBSERVATION"] = "off"`
    before any work: spawned workers inherit it, and `lock_environment` does not reset it. Then it
    runs `run_harness(kinds=STUDY_KINDS, path="api")` and `run_cells` on the slice and cut cells.
    It writes `{"meta", "rows", "slice_rows", "cut_rows"}`.
  - `run_rule_d(existing: dict, *, dry_run: bool) -> dict`. It rebuilds the same cells, joins each
    to its existing row on `(corpus, kind, n, victim_id)` (raising when one is missing), builds the
    plans, and scores. It returns `{"meta", "rows", "slice_rows", "cut_rows", "verdicts"}`.
    `verdicts` is omitted when `dry_run`.
  - `meta` includes:
    - `study_id`, `commit`, `core.THRESHOLDS`, `core.STUDY_ID`, `textprofile.artifact_meta()`;
    - the corpus fingerprint from `existing["meta"]`;
    - class sizes, leak drops, inconclusive reasons and runtime;
    - `word_counts`: min, median and max per population and side (§4 asks for each side's range).
  - With `--open`, `verdicts` also holds `"official"`, the unchanged
    `calibration_gate.adversarial_results_from_rows(existing["rows"], existing["meta"])`
    (§6's continuity row).
  - **Admission reproduction check:** before scoring, `admission.held(scored baselines)` for every
    victim must equal its `existing_row["held_baseline_indices"]`, or `run_rule_d` raises. A fresh
    throwaway student's drift gate depends only on its texts and their order, so this also licenses
    posting classmates' papers instead of reusing earlier rows. For a public-author classmate,
    whose papers leave out the first, posting is the faithful case anyway.
  - `main(argv) -> int`, with these subcommands:
    - `existing --out PATH [--workers K]`;
    - `run --existing PATH --out PATH [--open] [--reopen-after-crash]`.

    Without `--open`, `run` is a dry run. It prints counts only and writes
    `<out>.dry.json`, never `<out>`.

- [ ] **Step 1: Write the failing tests**

  - `test_study_kinds_match_the_design`: the ten kinds, with none of `obfuscated_baselines`,
    `outsourced_baselines` or `rj_embedded_*`.
  - `test_slice_cells_cut_to_the_imitation_length`: on a fixture with a 650-word imitation, every
    slice has 650 words.
  - `test_cut_cells_only_touch_n3_public_authors`.
  - `test_join_raises_on_a_missing_existing_row`.
  - `test_admission_mismatch_raises`: a fake `Admission` that disagrees with one victim's
    `held_baseline_indices` makes `run_rule_d` raise.
  - `test_dry_run_output_has_no_outcomes`: run `main(["run", ...])` without `--open` on a tiny
    fixture corpus (monkeypatch `build_cells`). The `.dry.json` contains no `index`,
    `reads_less_like_student`, `auc`, `rate` or `verdicts` key at any depth, and `<out>` does not
    exist.

- [ ] **Step 2: Run to verify they fail**

  Run: `.venv/bin/python -m pytest tests/adversarial/test_rule_d_study.py -q`
  Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement.** Build plans per corpus:
  - public authors use `public_author_plans` with the other victims at the same N;
  - RJ uses `rj_plans` with the loaders' data;
  - LLM, `sigma_inflation` and `mechanical_obfuscation` cells use the `classmate_essay` plan only;
  - `rj_self_*` cells use `outside_writer` only.

- [ ] **Step 4: Run to verify they pass**

  Run: `.venv/bin/python -m pytest tests/adversarial/ -q`
  Expected: all pass, including the battery's existing tests (unchanged).

- [ ] **Step 5: Commit** both files: `Add the rule D study runner and dry run`.

### Task 6: The single opening

**Files:**
- Create: `validation/adversarial/rule_d_opening.py`
- Modify: `validation/adversarial/rule_d_study.py` (`run --open` calls the opening checks)
- Test: `tests/adversarial/test_rule_d_opening.py`

**Interfaces:**
- Produces:
  - `STUDY_ID = "rule-d-adversarial-2026-11"`.
  - `OPENINGS_LOG = Path("validation/adversarial/RULE_D_OPENINGS.tsv")`.
  - `PREREG = Path("docs/research/2026-11-27-rule-d-adversarial-preregistration.md")`.
  - `class OpeningRefused(Exception)`.
  - `code_commit_from_prereg(text: str) -> str`. It parses the line `**Code commit:** \`<40-hex>\``,
    raising `OpeningRefused` when that line is absent.
  - `check_can_open(root: Path, *, reopen_after_crash: bool) -> str`. It returns the code commit C,
    or raises `OpeningRefused` naming the first failed check (§7.4).
  - `log_started(root: Path, commit: str) -> None` and `log_completed(root: Path) -> None`. Lines
    are `timestamp\tstudy_id\tcommit\tstarted|completed`. `log_completed` rewrites the study's last
    line in place.
- Order in `run --open`: `check_can_open`, `log_started(HEAD)`, score every cell, write `<out>`,
  `log_completed`.

- [ ] **Step 1: Write the failing tests** (each builds a temp git repo with a bare remote via
  `subprocess`):

  - `test_refuses_a_dirty_tree`.
  - `test_refuses_when_head_is_not_on_the_remote`.
  - `test_refuses_without_the_prereg_at_head`.
  - `test_refuses_when_code_changed_after_c`: a commit after C touches a `.py` file, so the open
    is refused.
  - `test_allows_only_prereg_and_log_after_c`.
  - `test_refuses_a_second_open_after_completed`, with and without `--reopen-after-crash`.
  - `test_started_line_blocks_plain_open_but_allows_reopen_flag`, and a reopen appends a second
    line.
  - `test_reopen_flag_refused_when_never_started`.
  - `test_log_completed_rewrites_only_the_last_line`.

- [ ] **Step 2: Run to verify they fail**

  Run: `.venv/bin/python -m pytest tests/adversarial/test_rule_d_opening.py -q`
  Expected: FAIL with `ModuleNotFoundError`.

- [ ] **Step 3: Implement** with `git status --porcelain`, `git branch -r --contains HEAD`,
  `git cat-file -e HEAD:<PREREG>` and `git diff --name-only <C> HEAD`. Then wire `run --open` in
  `rule_d_study.py` in the order above.

- [ ] **Step 4: Run to verify they pass**

  Run: `.venv/bin/python -m pytest tests/adversarial/ -q`
  Expected: all pass.

- [ ] **Step 5: Commit** the three files: `Add the single-opening guard for the rule D study`.

### Task 7: Existing-scorer run, dry run, and pre-registration (commits C and P)

**Files:**
- Create: `validation/adversarial/reports/2026-11-27_rule_d_study_existing_scorer.json`
- Create: `docs/research/2026-11-27-rule-d-adversarial-preregistration.md`

- [ ] **Step 1: Run the existing scorer in the background** (about an hour on 8 workers):

  Run: `.venv/bin/python -m validation.adversarial.rule_d_study existing --out validation/adversarial/reports/2026-11-27_rule_d_study_existing_scorer.json`

  Expected: a `[adversarial] N/N cells` final line and the JSON written. Its `meta.n_cells` should
  match the cells `build_cells(STUDY_KINDS)` makes.

- [ ] **Step 2: Dry run**

  Run: `.venv/bin/python -m validation.adversarial.rule_d_study run --existing validation/adversarial/reports/2026-11-27_rule_d_study_existing_scorer.json --out "$TMPDIR/rule_d_study.json"`

  Expected: population sizes close to §1 (public authors 13/6/6, `rj_clean` 21/19/13). It also
  prints class sizes, leak drops (public authors 0), and inconclusive reasons. It prints no
  outcome.

- [ ] **Step 3: Commit C**: the existing-scorer JSON, `Add the existing scorer's run for the rule D study`.
  Record C's hash.

- [ ] **Step 4: Write the pre-registration**, following
  `docs/research/2026-11-12-scholarly-locked-test-preregistration.md`. Its header table holds Tool,
  Date, Question and the decision it informs, followed by:
  - **Study id** and **Code commit:** \`C\` (the exact line `code_commit_from_prereg` parses);
  - the single-opening statement;
  - rule D exactly: link `core.observe`, with the SHA-256 of `core.THRESHOLDS` serialised as
    sorted JSON, and `textprofile.artifact_meta()`;
  - cells, classes, readings, length rules and bars, copied from §1 to §5;
  - the counting list (`COUNTING`) and the report-only list;
  - the dry run's population sizes;
  - the corpus fingerprint;
  - the crash rule.

- [ ] **Step 5: Gatekeeper review.** Dispatch the `validation-gatekeeper` agent on the
  pre-registration and the dry-run output. Fix anything it finds in the note. If a fix needs a code
  change, re-run Steps 1-3 and record the new C.

- [ ] **Step 6: Commit P and push**: the note only, `Add pre-registration for the rule D adversarial study`.
  Then `git push -u origin claude/rule-d-adversarial-study`. Expected: the push succeeds (the
  pre-push hook runs the mapped tests).

### Task 8: Open once, write up, open the PR

**Files:**
- Create: `validation/adversarial/reports/2026-11-27_rule_d_study.json`
  (the date is the opening's date if it differs)
- Create: `validation/adversarial/RULE_D_OPENINGS.tsv`
- Create: `docs/research/2026-11-27-rule-d-adversarial-results.md`
- Modify: `docs/research/ADVERSARIAL_BASELINE_FINDINGS_2026-09-20.md` (one addendum paragraph)
- Modify: `docs/testing/10-gap-register.md` (pointer), `docs/STATUS.md` (one line)

- [ ] **Step 1: Open, in the background**

  Run: `.venv/bin/python -m validation.adversarial.rule_d_study run --existing validation/adversarial/reports/2026-11-27_rule_d_study_existing_scorer.json --out validation/adversarial/reports/2026-11-27_rule_d_study.json --open`

  Expected: the log line ends `completed` and the JSON contains `verdicts`.

  On a crash, stop and tell Andrew: a re-run needs his approval in chat (§7.5).

- [ ] **Step 2: Write the results doc.**
  - For each counting gate, a two-column table (existing scorer, rule D) with rates and their
    Wilson intervals, AUROC and its lower bound, the victim-bootstrap interval, and the verdict.
  - For rule D, one row per reading.
  - The official gate-verdict continuity row.
  - The report-only rows.
  - The limits list from §8, verbatim in substance.

  Every number must be read from the two JSON files. State each result as it came out, pass or fail.

- [ ] **Step 3: Gatekeeper review** of the results doc against the JSON. Fix the doc, never the data.

- [ ] **Step 4: Addendum, gap-register pointer and STATUS line.**

- [ ] **Step 5: Commit and push**: the JSON, the log, the results doc and the three doc edits,
  `Add rule D results on the six cheating tests`. Then open a PR to `main` whose body summarises the
  counting verdicts in both columns, links the design, pre-registration and results docs, and ends
  with `🤖 Generated with [Claude Code](https://claude.com/claude-code)`. Andrew reviews and merges.
