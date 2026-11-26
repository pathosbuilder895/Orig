# Writing State Past-Paper Examples Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Sentence length quotes each paper's typical sentences, and before any analysis Writing State fills its side-by-side panel with real sentences from the student's past papers, one family of related habits at a time.

**Architecture:** Two pure functions in `original/evidence.py` (a typical-sentence pick, and a family-wide past-paper example builder), one staff-only GET route beside `_attach_staff_explainability` in `original/routers/students_scoring.py`, and a past-paper mode inside the existing `#hero-evi` panel in `demo/original/writing-state.html`. Nothing touches scoring.

**Tech Stack:** Python 3.11, FastAPI, pydantic, pytest; vanilla JS in one HTML page; Playwright e2e (`demo/bluebook/e2e/`).

**Spec:** `docs/superpowers/specs/2026-11-16-writing-state-past-paper-examples-design.md`

## Global Constraints

- Branch `claude/writing-state-past-paper-examples`, stacked on `claude/original-alpha-workflow` (#341). PR base is `claude/original-alpha-workflow`. Never push to `main` or to #341's branch; never merge.
- Python: `PY=/Users/andrew/Code/Orig/.venv/bin/python` run from the worktree root (it resolves `original` to this worktree; checked 2026-11-16).
- No change to any score, threshold, weight, action, stored data or `original/constants.py`. No new environment flag.
- Gate: `EVIDENCE_PASSAGES_ENABLED` read only through `original.evidence.evidence_enabled()` (exact "1").
- Staff only: `_require_staff` (`original/routers/_shared.py:80`); path under `/students/{student_id}/…` so the tenant-isolation middleware (`original/api.py:503`) scopes it.
- Past papers: `state.samples` with `auth_weight > 0` and stored `text`, labelled `past paper 1…N` in that order, exactly as scoring does.
- No wording of judgment in the no-analysis view: no "suspicious", no "doesn't match", no score. Pass page strings through `EV.clean`.
- No dash characters U+2014 or U+2015 anywhere (code, copy, commits, PR).
- Commits: conventional (`Fix …`, `Add …`, `Refactor …`), ending `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- CI holds 98% combined statement + branch coverage (`--cov-branch`).

## Review Focus

1. **A late examples reply after an analysis.** If the examples request answers after the teacher has analysed a paper, the analysed view must stay; past-paper mode must not take the panel back. (Task 4 e2e: held response released after analysis.)
2. **The roster's late re-render.** `loadStudent` calls `renderAll()` again when the roster answers, and `renderAll()` calls `EVI.close()`; past-paper mode must survive that. (Task 4 e2e waits for the roster reply before asserting the panel is open.)
3. **Student text containing markup.** A past paper with `<img src=x onerror=…>` or `&` must show as text in the new columns and rows, never as HTML. (Task 4 e2e with its own writer.)
4. **A habit that never occurs.** Voice habits such as contractions are absent from the Mill fixtures; each paper must read "none in this paper", not an empty or broken column. (Task 4 e2e, Voice family.)
5. **A not-located paper.** When the engine's counting cannot be matched to a paper's text, that paper shows its number with "numbers only", never invented quotes. (Task 2 unit test.)

---

### Task 1: Typical sentences for sentence length

**Files:**
- Modify: `original/evidence.py:820-831` (`_length_pick`) and `:892-895` (`chosen` in `build_feature_evidence`)
- Test: `tests/test_evidence.py` (update `test_sentence_spread_examples_do_not_repeat_a_sentence` at :491; add two tests)

**Interfaces:**
- Produces: `_typical_pick(places: Sequence[Place], mean: float, limit: int) -> list[Place]` and `_spread_pick(places: Sequence[Place], limit: int) -> list[Place]`. `_length_pick` is removed (its only caller is `chosen`).

- [ ] **Step 1: Write the failing tests** in `tests/test_evidence.py`. Add a module constant (word counts 3, 10, 11, 30; mean 13.5, verified with `read_paper` on 2026-11-16):

```python
TYPICAL = ("The dog ran. We walked down to the river and sat there quietly. "
           "She said the old bridge had been closed for many years. "
           "The long road ran on and on past every field and farm and river and town "
           "until the light was gone and the night came down on all of us.")

def test_mean_sentence_length_quotes_each_papers_typical_sentences():
    r = ev.read_paper(TYPICAL, "mean_sentence_length")
    assert r.value == 13.5 and [p.words for p in r.places] == [3, 10, 11, 30]
    assert [p.words for p in ev._typical_pick(r.places, r.value, 3)] == [11, 10, 3]

def test_sentence_length_examples_do_not_depend_on_direction():
    past = [("past paper 1", PLAIN[0]), ("past paper 2", TYPICAL)]
    low = ev.build_feature_evidence(_feature("mean_sentence_length", -0.3), TYPICAL, past, rank=1)
    high = ev.build_feature_evidence(_feature("mean_sentence_length", 0.3), TYPICAL, past, rank=1)
    assert low["this_paper"] == high["this_paper"] and low["past_papers"] == high["past_papers"]
    assert [q["words"] for q in low["this_paper"]["examples"]] == [11, 10, 3]
    # Round-robin across papers, each paper's own typical sentence first.
    p1 = ev.read_paper(PLAIN[0], "mean_sentence_length")
    first = ev._typical_pick(p1.places, p1.value, 1)[0].words
    assert [(q["paper"], q["words"]) for q in low["past_papers"]["examples"]][:2] == [("past paper 1", first), ("past paper 2", 11)]
```

  In `test_sentence_spread_examples_do_not_repeat_a_sentence`, replace the three `_length_pick` calls with `ev._spread_pick(places, 3)` (len 1) and `ev._spread_pick(many, 2)` (len 2), and delete the `"mean", "lower"` line.

- [ ] **Step 2: Run them to see them fail**

Run: `$PY -m pytest tests/test_evidence.py -k "typical or direction or spread_examples" -q`
Expected: FAIL (`AttributeError: ... has no attribute '_typical_pick'` / `'_spread_pick'`).

- [ ] **Step 3: Implement.** `_typical_pick` sorts by `(abs((p.words or 0) - mean), p.start)` and returns the first `limit`. `_spread_pick` is the existing spread branch unchanged (interleave longest/shortest, dedupe). In `build_feature_evidence`, `chosen` takes the paper's reading: mean mode calls `_typical_pick(places, reading.value, max_examples)` for this paper with `this.value` and for each past paper with that paper's `r.value`; spread calls `_spread_pick`; others `_pick` as now. Direction no longer reaches any pick.

- [ ] **Step 4: Run the evidence tests**

Run: `$PY -m pytest tests/test_evidence.py tests/test_evidence_all_features.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add original/evidence.py tests/test_evidence.py
git commit -m "Fix sentence-length passages to quote each paper's typical sentences"
```

### Task 2: Habit families and the past-paper example builder

**Files:**
- Modify: `original/evidence.py` (new constant, three helpers, one builder; factor the name/description lookup out of `build_feature_evidence`)
- Test: `tests/test_evidence.py`

**Interfaces:**
- Consumes: `_typical_pick`, `_pick`, `_quote`, `read_paper`, `_round`, `NOT_LOCATED_NOTE`, `MAX_EXAMPLES` (all in `original/evidence.py`).
- Produces:
  - `FAMILIES: dict[str, tuple[str, ...]]`, in this order, exactly:
    - `"Sentence shape"`: `mean_sentence_length, sentence_length_variance, comma_rate, semicolon_colon_rate, dash_rate, parenthetical_rate, sentence_initial_conjunction_rate`
    - `"Linking ideas"`: `discourse_marker_density, additive_ratio, adversative_ratio, causal_ratio, temporal_ratio, transition_density`
    - `"Voice"`: `first_person_ratio, contraction_rate, question_ratio, modal_verb_ratio, passive_voice_ratio`
    - `"Claims and confidence"`: `hedging_density, assertion_density, claim_density, appeal_to_authority_density, quote_rate`
  - `family_of(code: str) -> str | None`
  - `_extremes_pick(places: Sequence[Place]) -> list[tuple[str | None, Place]]`: `[]` for no places; `[(None, p)]` for one place (my call: a lone sentence is neither longest nor shortest); otherwise `[("longest", L), ("shortest", S)]` where `L` is first by `(-words, start)` and `S` is first by `(words, start)` among the places other than `L`, so the two are always distinct sentences.
  - `_name_and_description(code: str) -> tuple[str, str]`: `describe(code)`, with the description replaced by `feature_info()[code]["description"]` when present (the lookup `build_feature_evidence` does today; it now calls this).
  - `build_past_paper_examples(habit: str, baselines: Sequence[tuple[str, str]]) -> dict[str, Any]`, raising `ValueError` when `habit` is not in `LOCATABLE`. Returns:

    ```
    {"family": <name>, "habit": habit,
     "families": [{"name": n, "habits": list(codes)} for n, codes in FAMILIES.items()],
     "features": [<entry> for code in FAMILIES[family]]}
    <entry> = {"code", "name", "description", "unit": spec.unit, "what_is_marked": spec.what,
               "kind": "located", "per_paper": [<paper>, ...], "note": NOT_LOCATED_NOTE  # only if any paper's places is None
              }
    <paper> = {"paper": label, "value": _round(r.value),
               "count": len(r.places) or None when places is None,
               "examples": [{"role": role, "quote": _quote(text, place, label)}, ...]}
    ```

    Picks per paper: `mean` mode gives `("typical", p)` for `_typical_pick(places, r.value, MAX_EXAMPLES)`; `spread` gives `_extremes_pick(places)`; every other habit gives `(None, p)` for `_pick(places, MAX_EXAMPLES)`. A paper whose `places is None` gets `examples: []`. `families` is my addition to the spec's response: the page needs every family's name and codes to draw the four buttons and to know which family a clicked habit opens, without copying `FAMILIES` into JavaScript.

- [ ] **Step 1: Write the failing tests** (names and assertions):
  - `test_every_locatable_habit_is_in_exactly_one_family`: `list(ev.FAMILIES) == ["Sentence shape", "Linking ideas", "Voice", "Claims and confidence"]`; the concatenated codes have no duplicates and `sorted(...) == sorted(ev.LOCATABLE)`; `ev.family_of("comma_rate") == "Sentence shape"`; `ev.family_of("typing_speed_cv") is None`.
  - `test_past_paper_examples_return_the_whole_family_in_order` (parametrize over every code in `LOCATABLE`, baselines `[("past paper 1", PLAIN[0])]`): `out["habit"] == code`, `out["family"] == ev.family_of(code)`, `[f["code"] for f in out["features"]] == list(ev.FAMILIES[out["family"]])`, `out["features"][0]["name"] == ev._name_and_description(out["features"][0]["code"])[0]`, `out["families"][0] == {"name": "Sentence shape", "habits": list(ev.FAMILIES["Sentence shape"])}`.
  - `test_past_paper_examples_label_papers_in_order_and_quote_verbatim` (baselines `PLAIN` labelled 1..3, habit `"discourse_marker_density"` and `"mean_sentence_length"`): every feature's `[p["paper"] for p in per_paper] == ["past paper 1", "past paper 2", "past paper 3"]`; every quote has `passage == text[passage_start:passage_end]` for its paper's text; `len(examples) <= 3`; non-length features have every `role is None`.
  - `test_sentence_length_is_typical_and_variation_is_longest_and_shortest` (baselines `[("past paper 1", TYPICAL)]`): mean feature `[(e["role"], e["quote"]["words"]) for e in examples] == [("typical", 11), ("typical", 10), ("typical", 3)]`; variance feature `== [("longest", 30), ("shortest", 3)]`.
  - `test_a_single_sentence_paper_gets_one_variation_quote_without_a_role`: baselines `[("past paper 1", "Only one sentence here.")]`, variance examples `== [(None, 4)]` as `(role, words)`.
  - `test_a_paper_that_cannot_be_located_has_no_examples_and_says_so(monkeypatch)`: `monkeypatch.setattr(ev, "_original_sentences", lambda view: None)`; for habit `"comma_rate"` every feature has `note == ev.NOT_LOCATED_NOTE`, every paper `examples == []` and `count is None`, and `value` is still a number.
  - `test_no_past_papers_gives_empty_lists`: `build_past_paper_examples("comma_rate", [])` has seven features, each `per_paper == []` and no `note`.
  - `test_unknown_habit_is_refused`: `pytest.raises(ValueError)` for `"typing_speed_cv"` and `"nope"`.

- [ ] **Step 2: Run them to see them fail**

Run: `$PY -m pytest tests/test_evidence.py -k "family or past_paper_examples or single_sentence or cannot_be_located or no_past_papers or unknown_habit" -q`
Expected: FAIL (`AttributeError: ... 'FAMILIES'`).

- [ ] **Step 3: Implement** the constant, `family_of`, `_extremes_pick`, `_name_and_description` (and switch `build_feature_evidence` to it), and `build_past_paper_examples` per the Interfaces block. Read each paper once per habit with `read_paper` (measured 2026-11-16: seven habits on a 1,300-word paper take 2 ms).

- [ ] **Step 4: Run the evidence tests**

Run: `$PY -m pytest tests/test_evidence.py tests/test_evidence_all_features.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add original/evidence.py tests/test_evidence.py
git commit -m "Add habit families and past-paper example builder"
```

### Task 3: Staff-only past-paper examples route

**Files:**
- Modify: `original/routers/students_scoring.py:652-736` (factor two helpers out of `_attach_staff_explainability`; add the route after it)
- Modify: `original/schemas.py` (new model after `PreliminaryScoreOut`, :1095)
- Create: `tests/test_past_paper_examples_route.py`
- Modify: `tests/test_voice_leak.py` (`test_evidence_and_preliminary_are_staff_only_with_both_flags_on`, :612)

**Interfaces:**
- Consumes: `build_past_paper_examples`, `LOCATABLE`, `evidence_enabled` from `original.evidence`; `_require_staff` from `._shared`.
- Produces:
  - `class PastPaperExamplesResponse(BaseModel)`: `baseline_papers: list[dict[str, Any]]`, `family: str`, `habit: str`, `families: list[dict[str, Any]]`, `features: list[dict[str, Any]]`.
  - `_past_papers_of(state) -> tuple[list, list[tuple[str, str]]]`: `(used_samples, [(f"past paper {i + 1}", s.text), ...])`.
  - `_baseline_papers(state, used, baselines, student_id: str | None) -> list[dict[str, Any]]`: the existing `baseline_papers` block moved verbatim, including the `_sample_sources` lookup that loses only `source` on failure.
  - `GET /students/{student_id}/past-paper-examples?habit=<code>` (default `mean_sentence_length`) → `PastPaperExamplesResponse`. Checks, in order: flag off → 404 `"Not found"`; `_require_staff(request)` (403 or 401); `_repo().get(student_id) is None` → 404 `f"Student '{student_id}' not found"`; `habit not in LOCATABLE` → 422 `"Unknown habit"`. Then `used, baselines = _past_papers_of(state)`; body is `{**build_past_paper_examples(habit, baselines), "baseline_papers": _baseline_papers(state, used, baselines, student_id)}`. Any exception there: `logging.getLogger(__name__).exception("past paper examples failed")` and 503 `"Examples could not be shown just now."`.

- [ ] **Step 1: Write the failing route tests** in `tests/test_past_paper_examples_route.py`, using `live_client` and `tests.alpha.test_past_papers._workspace` / `_ok` exactly as `tests/test_student_sample_source.py:237` does (`INVITE_NO_EXPIRY=1`, `principal.invalidate_tenant_cache()`). Seed three past papers with `POST /students/{sid}/baseline` as the teacher, `provenance: "verified"`, `assignment: f"Paper {k}"`, `submitted_at: f"2026-0{k}-10"`, texts `tests.alpha.test_alpha_ready_e2e._paper(0, TOPICS[k])`.
  - `test_flag_off_is_404`: flag unset, teacher → 404.
  - `test_staff_get_the_whole_family_with_the_scores_labels`: flag "1", teacher → 200; `family == "Sentence shape"`, `habit == "mean_sentence_length"`, seven features; mean feature per-paper labels `["past paper 1", "past paper 2", "past paper 3"]`, every example role `"typical"`; `?habit=contraction_rate` gives `family == "Voice"`. Then `POST /students/{sid}/score` as the teacher: `score["evidence"]["baseline_papers"] == body["baseline_papers"]` (titles, dates and `source` included).
  - `test_students_are_refused_even_for_their_own_record`: the student's own headers → 403; the classmate's → 403.
  - `test_another_workspace_is_refused`: a second `_workspace`'s teacher → 403.
  - `test_unknown_student_is_404_and_unknown_habit_is_422`: teacher, `f"{principal.tenant_of(sid)}:nobody"` (their tenant, no record) → 404; `?habit=typing_speed_cv` on the real student → 422.
  - `test_a_student_without_stored_text_gets_empty_lists(monkeypatch)`: patch `original.routers.students_scoring._repo` to return an object whose `get()` gives `SimpleNamespace(samples=[SimpleNamespace(text="", auth_weight=1.0)])`; demo principal (no headers) → 200, `baseline_papers == []`, every `per_paper == []`.
  - `test_a_build_failure_is_503(monkeypatch)`: patch `original.evidence.build_past_paper_examples` to raise → 503.
  - In `tests/test_voice_leak.py:612`, after the score checks: `client.get(f"/students/{sid}/past-paper-examples", headers=hdr).status_code == 403`, and the demo principal (no headers) gets 200 with `len(features) == 7`.

- [ ] **Step 2: Run them to see them fail**

Run: `$PY -m pytest tests/test_past_paper_examples_route.py -q`
Expected: FAIL with 404s where 200/403/422 are expected (route missing).

- [ ] **Step 3: Implement** the model, the two helpers (and `_attach_staff_explainability` now calls them, behaviour unchanged), and the route.

- [ ] **Step 4: Run the route, evidence, source and leak tests**

Run: `$PY -m pytest tests/test_past_paper_examples_route.py tests/test_evidence.py tests/test_student_sample_source.py tests/test_voice_leak.py -q`
Expected: all pass (the existing `_attach_staff_explainability` assertions pin the refactor).

- [ ] **Step 5: Commit**

```bash
git add original/routers/students_scoring.py original/schemas.py tests/test_past_paper_examples_route.py tests/test_voice_leak.py
git commit -m "Add staff-only past-paper examples route"
```

### Task 4: Past-paper mode on Writing State

**Files:**
- Modify: `demo/original/writing-state.html` (CSS near :138-160; markup inside `#hero-evi` at :461; `makeEvidence` at :953; `renderAll` at :1227; `loadStudent` at :1338)
- Create: `demo/bluebook/e2e/past-paper-examples.spec.mjs`

**Interfaces:**
- Consumes: `GET /students/{id}/past-paper-examples?habit=` (Task 3 response shape); `EV.pastSource`, `EV.markParts`, `EV.quoteSource`, `EV.fmt`, `EV.clean` (`demo/original/js/evidence-view.js`); `Live.api` (returns `{ok, status, data}`); `quoteHTML`, `esc`, `poss`, `who` already in the page.
- Produces (inside the page):
  - `PP = {state: 'idle'|'on', cache: Map<familyName, response>, families: [{name, habits}], habit: '', seq: 0}`.
  - `startPastExamples()`: called in `loadStudent` on the `!restoreLast()` branch, only when `hasBaseline()`. Fetches the default family; enters past-paper mode only if the reply is 200, `!S.result` still holds, `PP.seq` is unchanged, and at least one paper of any feature has examples; then opens sentence length unless the panel is already open. Anything else: nothing changes.
  - `EVI.open(code, from)`: while `!S.result && PP.state === 'on'` and the code is in a family from `PP.families`, opens that family with `code` in full (fetching and caching the family on first use; on a non-200, falls back to today's numbers-only panel). Otherwise unchanged.
  - `EVI.pastHabit() -> string`: the habit shown in past-paper mode, or `''`. `renderAll()` reads it before `EVI.close()` and, if non-empty and `!S.result`, reopens it without scrolling, so the roster's late `renderAll()` keeps the panel (Review Focus 2). After an analysis `S.result` is set, so the panel closes as today.
  - Markup: one new container `#evi-past` inside `#hero-evi` holding `#evi-fams` (four buttons from `PP.families`, `aria-pressed` on the current one), `#evi-pcols` (one `.evi-pcol` per paper, two per row, scrolling inside the panel), `#evi-rel` (heading plus one `button.evi-rel-row[data-code]` per other habit), `#evi-pline` (the plain line). In past-paper mode `#evi-past` shows and `.evi-cols`, `#evi-tabs`, `#evi-foot`, `#evi-flag` hide; `close()` and analysed-mode `render()` restore them. `#evi-name` is the habit's name; `#evi-nums` shows the past papers' range and unit only.
  - Column content: heading `EV.pastSource(paper, baseline_papers)`; the number `EV.fmt(value) + ' ' + unit`; up to its examples as `quoteHTML(quote)`, each with a source line `EV.quoteSource(quote, ROLE[role] || '')` where `ROLE = {typical: 'Typical', longest: 'Longest', shortest: 'Shortest'}`; `count === 0` shows "None in this paper."; `count === null` shows the feature's `note` through `EV.clean`.
  - Related rows: name, then per paper `EV.fmt(value)` with unit and one quote (the first example; for variation both longest and shortest), or "none in this paper" (`count === 0`) or "numbers only" (`count === null`). Clicking a row sets `PP.habit` and redraws with no request.
  - Related heading per family (my wording): Sentence shape "Related: how these sentences are built"; Linking ideas "Related: how ideas are joined"; Voice "Related: how the writer speaks"; Claims and confidence "Related: how claims are made".
  - Plain line: `EV.clean('These are sentences from ' + poss() + ' own past papers, so you can see their usual writing before you analyse anything.', '')`.
  - Every student-derived string goes through `esc` or `textContent`.

- [ ] **Step 1: Write the e2e spec** `past-paper-examples.spec.mjs`, reusing `teacher-evidence.spec.mjs`'s imports, fixtures (`fixtures/evidence/mill-1..3.txt`, `chesterton.txt`), `seedPastPapers` and `analyse` (copy the two helpers). Tests (names, then what they assert):
  - `no analysis yet: no examples panel, flags off` (untagged, runs in the main CI job): staff opens Writing State for a seeded writer, waits for the roster reply; `#hero-evi` hidden; the examples request answered 404.
  - `past papers fill the panel before any analysis @evidence-on`: fetch the API body with `page.request.get` in the staff context, for comparison. On the page, after the roster reply: `#hero-evi` visible, `#evi-name` is the sentence-length name from the API, `#evi-pcols .evi-pcol` count 3, each column contains its paper's `assignment`, the first mark in column 1 equals the API's first example match slice, its source line contains "Typical"; `#evi-rel .evi-rel-row` count 6; `#evi-pline` contains "own past papers" and the page has no element with text matching `/suspicious|does(n.t| not) match|deviation/i` inside `#hero-evi`.
  - `a related row and a family button switch the habit @evidence-on`: click the `sentence_length_variance` row → `#evi-name` changes, column 1 has two quotes whose source lines contain "Longest" and "Shortest", and no new examples request was made (count requests with `page.on('request')`). Click the Voice button → one new request with `habit=first_person_ratio`; `#evi-name` is the first-person name; for every paper whose API `contraction_rate` count is 0 the contraction row reads "none in this paper" (Review Focus 4).
  - `an analysis replaces past papers with this paper beside them @evidence-on`: analyse Chesterton; `#hero-evi` closed; clicking the comma bar shows `#evi-sub-lbl` "This paper" and `#evi-past` hidden. Reload: the restored result shows, no examples request is made.
  - `a late examples reply never covers an analysis @evidence-on` (Review Focus 1): `page.route('**/past-paper-examples*')` holds the first reply; analyse; then release it; `#evi-past` stays hidden and `#hero-evi` is not open on sentence length.
  - `student markup in a past paper is shown as text @evidence-on` (Review Focus 3): seed one past paper whose first sentence contains `<img src=x onerror="window.__x=1"> & <b>bold</b>`; the first column's text contains the literal `<b>bold</b>`, `#evi-pcols img` count 0, `window.__x` undefined.
  - `a student session gets no examples @evidence-on`: `request.get` with the student's bearer token → 403.

- [ ] **Step 2: Implement** the CSS, markup and script per the Interfaces block.

- [ ] **Step 3: Run the static page tests**

Run: `$PY -m pytest tests/test_original_suite_static.py tests/test_button_audit_fixes.py -q`
Expected: all pass (these parse the page's inline scripts and check its wording).

- [ ] **Step 4: Run the e2e spec** against two local servers (Task 5 Step 2 has the commands); both runs pass.

- [ ] **Step 5: Commit**

```bash
git add demo/original/writing-state.html demo/bluebook/e2e/past-paper-examples.spec.mjs
git commit -m "Add past-paper examples to Writing State before an analysis"
```

### Task 5: Full verification, browser check and PR

**Files:** none new (fixes only, if something fails).

- [ ] **Step 1: Full suite with branch coverage**, in the background (it outruns 600 s):

Run: `$PY -m pytest tests/ validation/test_tier10_optional.py -m "not blocker and not certification" -q --cov=original --cov-branch --cov-report=term | tail -5`
Expected: 0 failed; TOTAL at or above 98%.

- [ ] **Step 2: Playwright, both servers.** Install once: `cd demo/bluebook && npm ci && npx playwright install chromium`. Start each server with `preview_start` from a temporary `.claude/launch.json` entry (revert the file afterwards with `git checkout .claude/launch.json`), `runtimeExecutable: "/usr/bin/env"` and args `ORIGINAL_ENV=pilot SECRET_KEY=ci-test-only-secret-do-not-deploy MAINTENANCE_TOKEN=ci-test-only LOGIN_THROTTLE_MAX_ATTEMPTS=500 [EVIDENCE_PASSAGES_ENABLED=1 PRELIMINARY_SCORE_ENABLED=1] /Users/andrew/Code/Orig/.venv/bin/python run.py --demo --frontend-dir demo --skip-seed --port 8013`. Do not stop any server you did not start.

Run (flags off): `PLAYWRIGHT_BASE_URL=http://localhost:8013 npx playwright test e2e/past-paper-examples.spec.mjs e2e/teacher-evidence.spec.mjs --grep-invert "@evidence-on"`
Run (flags on): `PLAYWRIGHT_BASE_URL=http://localhost:8013 npx playwright test e2e/past-paper-examples.spec.mjs e2e/teacher-evidence.spec.mjs -g "@evidence-on"`
Expected: all pass both times (teacher-evidence.spec.mjs proves the analysed view is unchanged).

- [ ] **Step 3: Look at it.** On the flags-on server, seed a writer with the three Mill papers, open Writing State, screenshot the panel on sentence length and on the Voice family, at desktop and phone width. Send both to Andrew.

- [ ] **Step 4: Push and open the PR** with base `claude/original-alpha-workflow`, title `Add past-paper examples to Writing State`, body summarising fix 1, the families, the route, the page, and the test runs, ending with the attribution line.
