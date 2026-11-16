# Rule D AI-Mirror Screen Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Test whether rule D flags 20 AI-written papers that mirror (same title, same journal) a held-out paper of 20 humanities `locked_test` authors, with the false-flag rate beside it.

**Architecture:** A new validation-only module `validation/scholarly/ai_mirror.py` picks the targets, writes the prompt sheet, cleans and records the AI replies, checks the rebuilt environment against the committed thresholds, and opens `locked_test` once under a new study id. Rule D's `build_scores` gains an optional `extra_docs` input (default `None`, unchanged behaviour). The corpus restore learns to clean each paper with the cleaner version it was recorded with.

**Tech Stack:** Python 3.11, numpy, scikit-learn (rule D's TF-IDF), pydantic (manifest), pytest; `pdftotext` from poppler-utils on Linux for the restore.

**Spec:** `docs/superpowers/specs/2026-11-16-rule-d-ai-mirror-design.md`

## Global Constraints

- Branch `claude/rule-d-ai-mirror`, stacked on `claude/practical-mendel-d9eju5` (PR #336). Never push to `main`; the PR targets `claude/practical-mendel-d9eju5`.
- Use the checkout's own `.venv/bin/python` (create with `python3.11 -m venv .venv` and install per README). Never system python3.
- Never bare `git stash`. Delete files with `git rm`. No U+2014 or U+2015 characters in any file, commit or PR text.
- Rule D, `rule_d_thresholds_humanities.json`, the vectorizer procedure, `SEEDS` and `CONFIGS` do not change. `build_scores` with `extra_docs=None` must behave exactly as today.
- Study id `scholarly-ai-mirror-2026-11-16`. Collection `humanities` only. Seed `7`. 20 targets. Tools `("claude", "chatgpt", "gemini")`.
- Prompt and continuation text are copied verbatim from the spec; nothing about the targets, prompts, rule or decision changes after the pre-registration commit (Task 7).
- `locked_test` is opened once for this study, only after the environment gate passes, in the same cloud session as the restore.
- Corpus paper text is never committed. AI replies (raw and cleaned) are committed under `validation/scholarly/ai_mirror/`.
- Every reported number names the writing it was measured on (published humanities scholarship, not student writing) and puts the honest flag count beside the catch count.
- Commits: conventional prefix (`Add`, `Fix`), ending `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## Review Focus

1. A reply with no blank lines (one giant paragraph): it must still cut to exactly the configuration's word count. Test in Task 6 (`test_ai_cut_single_paragraph`).
2. A reply still under 1,200 words after the one continuation: it must enter only the two 300-word configurations and be listed as missing from `matched_1200_1200`. Test in Task 6 (`test_short_ai_text_enters_only_300_configs`).
3. A manifest paper with an unknown `cleaner_version`: the restore must fail loudly, not count a silent mismatch. Test in Task 1 (`test_strip_inline_rejects_unknown_version`).
4. A target author the loader skips at the opening (rotted link): it must be reported in `missing_authors`, with the Wilson interval on the real n. Test in Task 6 (`test_summarise_reports_missing_author`).
5. Running the opening twice, or with an AI text that differs from its recorded hash or is uncommitted: it must refuse before the partition is opened. Tests in Task 6 (`test_open_locked_guards`).

---

### Task 1: Restore with the cleaner each paper was recorded with

**Files:**
- Modify: `validation/scholarly/clean.py` (`_NOTE_MARK`, `strip_inline`, `clean_pages`, `pdf_bytes_to_extraction`, `pdf_bytes_to_text`)
- Modify: `validation/scholarly/fetch.py` (`restore`)
- Test: `tests/test_scholarly_corpus.py`

**Interfaces:**
- Produces: `clean.strip_inline(text: str, version: str = CLEAN_VERSION) -> str`; `clean.clean_pages(pages, min_para_words=12, version=CLEAN_VERSION)`; `clean.pdf_bytes_to_text(pdf, tmp_dir, name="doc", timeout=120, version=CLEAN_VERSION)`; `restore` passes `version=p.cleaner_version`.

- [ ] **Step 1: Write the failing tests**

```python
def test_strip_inline_v1_strips_digits_glued_to_letters():
    assert clean.strip_inline("the church12 said it.", version="1") == "the church said it."
    assert clean.strip_inline("the church12 said it.", version="2") == "the church12 said it."
    assert clean.strip_inline("the church12 said it.") == clean.strip_inline("the church12 said it.", version="2")

def test_strip_inline_rejects_unknown_version():
    with pytest.raises(ValueError):
        clean.strip_inline("text", version="3")

def test_restore_cleans_each_paper_with_its_recorded_version(monkeypatch, tmp_path):
    # manifest: one author, 6 papers, three recorded as cleaner_version "1", three as "2";
    # monkeypatch loader.load_manifest to return it and clean.pdf_bytes_to_text to record
    # the version it was called with and return the text whose sha256 the paper records.
    out = fetch.restore("humanities", tmp_path, workers=1, fetch_url=lambda url: b"%PDF")
    assert seen_versions == {p.source_paper_id: p.cleaner_version for p in papers}
    assert out["restored"] == 6 and out["mismatch"] == 0 and "warning" not in out
```

- [ ] **Step 2: Run them to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_scholarly_corpus.py -k "strip_inline or recorded_version" -q`
Expected: FAIL (`strip_inline() got an unexpected keyword argument 'version'`).

- [ ] **Step 3: Implement**

Replace `_NOTE_MARK` with `_NOTE_MARKS = {"1": <the v1 regex>, "2": <today's regex>}`. The v1 regex, verbatim from commit `7006e5af`: `r"(?<=[.,;:!?”’)\"])\d{1,3}(?=\s|$)|(?<=[a-z])\d{1,2}(?=[\s.,;:)])"`. `strip_inline` raises `ValueError` for a version not in `_NOTE_MARKS`. Thread `version` through `clean_pages` and both `pdf_bytes_to_*` functions. In `restore`, call `clean.pdf_bytes_to_text(..., version=p.cleaner_version)` and delete the old-cleaner warning. Update the CLEAN_VERSION comment and the README "Reusing it" paragraph to say restore now uses each paper's recorded version.

- [ ] **Step 4: Run the scholarly tests**

Run: `.venv/bin/python -m pytest tests/test_scholarly_corpus.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

`git commit -m "Fix scholarly restore to clean each paper with its recorded cleaner version"`

---

### Task 2: Let rule D score extra papers

**Files:**
- Modify: `validation/scholarly/rule_d.py` (`build_scores`)
- Test: `tests/test_scholarly_ai_mirror.py` (new)

**Interfaces:**
- Produces: `rule_d._trial_docs(t, authors, honest_of, field, hosts, seed, extra=None) -> list[tuple[str, int, str | None, str]]`; `rule_d.build_scores(collection, sets, vecs, extra_docs: dict | None = None) -> list[dict]`, where `extra_docs[(config_name, seed)][author_id]` is a list of `(text, 1, None, "ai")`. Rows for those docs carry `kind == "ai"` and `src is None`.

- [ ] **Step 1: Write the failing tests**

```python
def test_trial_docs_without_extra_equals_probe_docs(monkeypatch):
    monkeypatch.setattr(rule_d, "probe_docs", lambda *a: [("h", 0, None, "honest")])
    assert rule_d._trial_docs(T("A1"), ["A1"], {}, {}, {}, 7) == [("h", 0, None, "honest")]

def test_trial_docs_appends_only_this_authors_extras(monkeypatch):
    monkeypatch.setattr(rule_d, "probe_docs", lambda *a: [])
    extra = {"A1": [("ai text", 1, None, "ai")], "A2": [("other", 1, None, "ai")]}
    assert rule_d._trial_docs(T("A1"), ["A1", "A2"], {}, {}, {}, 7, extra) == [("ai text", 1, None, "ai")]

def test_build_scores_extra_docs_defaults_to_none():
    assert inspect.signature(rule_d.build_scores).parameters["extra_docs"].default is None
```

(`T` is a minimal stand-in with a `student_id` attribute.)

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_scholarly_ai_mirror.py -q`
Expected: FAIL (`module 'rule_d' has no attribute '_trial_docs'`).

- [ ] **Step 3: Implement**

`_trial_docs` returns `probe_docs(...)` plus `extra.get(t.student_id, [])` when `extra` is given. In `build_scores`, add every extra doc's text to the `texts` list passed to `store.ensure`, and iterate `_trial_docs(t, authors, honest_of, field, hosts, seed, (extra_docs or {}).get((name, seed)))` in place of `probe_docs(...)`.

- [ ] **Step 4: Run the tests**

Run: `.venv/bin/python -m pytest tests/test_scholarly_ai_mirror.py tests/test_scholarly_corpus.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

`git commit -m "Add optional extra papers to rule D scoring, unchanged by default"`

---

### Task 3: Pick the targets and write the prompt sheet

**Files:**
- Create: `validation/scholarly/ai_mirror.py`
- Test: `tests/test_scholarly_ai_mirror.py`

**Interfaces:**
- Produces, in `ai_mirror.py`:
  - constants `STUDY_ID = "scholarly-ai-mirror-2026-11-16"`, `COLLECTION = "humanities"`, `SEED = 7`, `N_TARGETS = 20`, `TOOLS = ("claude", "chatgpt", "gemini")`, `PROMPT`, `CONTINUE_PROMPT` (verbatim from the spec), `CONTINUE_BELOW = 1300`, `AI_DIR = HERE / "ai_mirror"`.
  - `@dataclass(frozen=True) class Target: rank: int; author_id: str; paper_id: str; title: str; venue: str; tool: str`
  - `new_paper_for(papers: list[ScholarlyPaper], seed: int, n_past: int = 4, past_words: int = 1200, new_words: int = 1200) -> str`: the `honest_ids[0]` that `loader.load_trials` would choose, from metadata only.
  - `select_targets(manifest: ScholarlyManifest, candidates: dict) -> list[Target]`: `locked_test` authors sorted by `loader._rank(SEED, "ai-mirror:" + author_id)`, first 20, `tool = TOOLS[rank % 3]`, title and venue (`host`) from the candidate record whose `work_id` is the paper id; `KeyError` if absent.
  - `render_sheet(targets: list[Target]) -> str`
  - CLI `python -m validation.scholarly.ai_mirror select`: writes `ai_mirror/targets_humanities.json` and `ai_mirror/prompts_humanities.md`.

- [ ] **Step 1: Write the failing tests**

```python
def test_new_paper_for_matches_loader(tmp_path):
    # 3 development-partition authors x 6 papers of 1,600 words, texts in tmp_path/humanities/texts
    ts = loader.load_trials("humanities", "development", past_words=1200, new_words=1200, seed=7,
                            manifest=m, cache=tmp_path)
    for t in ts.trials:
        assert ai_mirror.new_paper_for(m.authors()[t.student_id], 7) == t.honest_ids[0]

def test_select_targets_deterministic_locked_only():
    a = ai_mirror.select_targets(loader.load_manifest("humanities"), CANDIDATES)
    assert a == ai_mirror.select_targets(loader.load_manifest("humanities"), CANDIDATES)
    assert len({t.author_id for t in a}) == 20
    assert all(policy.partition_of(t.author_id) == "locked_test" for t in a)

def test_tools_split_7_7_6():
    assert Counter(t.tool for t in TARGETS) == {"claude": 7, "chatgpt": 7, "gemini": 6}

def test_select_targets_raises_when_paper_not_in_candidates():
    with pytest.raises(KeyError):
        ai_mirror.select_targets(manifest, {"authors": []})

def test_sheet_carries_exact_prompts():
    sheet = ai_mirror.render_sheet(TARGETS)
    for t in TARGETS:
        assert ai_mirror.PROMPT.format(title=t.title, venue=t.venue) in sheet
        assert f"validation/scholarly/ai_mirror/raw/{t.author_id}.txt" in sheet
    assert chr(0x2014) not in sheet and ai_mirror.CONTINUE_PROMPT in sheet
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_scholarly_ai_mirror.py -q`
Expected: FAIL (`No module named 'validation.scholarly.ai_mirror'`).

- [ ] **Step 3: Implement** the interfaces above. The sheet lists, per target: number, tool, the filled prompt in a fenced block, the continuation rule, and the path to save the reply to.

- [ ] **Step 4: Run the tests**

Run: `.venv/bin/python -m pytest tests/test_scholarly_ai_mirror.py -q`
Expected: all pass.

- [ ] **Step 5: Commit**

`git commit -m "Add AI-mirror target selection and prompt sheet for rule D"`

---

### Task 4: Clean and record AI replies

**Files:**
- Modify: `validation/scholarly/ai_mirror.py`
- Test: `tests/test_scholarly_ai_mirror.py`

**Interfaces:**
- Produces: `normalise_ai_text(raw: str, title: str) -> str`; `intake(author_id: str, model: str, date: str, route: str, continued: bool) -> dict`; CLI `intake --author A... --model "..." --date YYYY-MM-DD --route app|subagent [--continued]`. `intake` reads `ai_mirror/raw/<author_id>.txt`, writes `ai_mirror/texts/<author_id>.txt`, and upserts `ai_mirror/manifest_humanities.json` entry `{author_id, paper_id, tool, model, date, route, continued, words, sha256, raw_sha256}`. `ValueError` for an author not in the targets file or a missing raw file.

- [ ] **Step 1: Write the failing tests**

```python
RAW = ("# A Study of Grace\n\n**Introduction** " + "word " * 30 + "\n\n## Part two\n\n- "
       + "bullet words " * 10 + "see https://example.org now.\n\nshort para here\n\n"
       "References\n\nSmith, J. (2010). A book.\n")

def test_normalise_strips_markdown_title_short_paras_and_references():
    out = ai_mirror.normalise_ai_text(RAW, "A Study of Grace")
    for bad in ("#", "**", "A Study of Grace", "References", "Smith, J.", "https://", "short para here"):
        assert bad not in out
    assert out.count("\n\n") == 1        # two body paragraphs left
    assert not out.lstrip().startswith("-")

def test_intake_records_hash_and_word_count(tmp_path, monkeypatch):
    monkeypatch.setattr(ai_mirror, "AI_DIR", tmp_path)   # with a targets file and raw/<A>.txt
    e = ai_mirror.intake("A1", "GPT-x", "2026-11-17", "app", False)
    text = (tmp_path / "texts" / "A1.txt").read_text(encoding="utf-8")
    assert e["words"] == len(text.split())
    assert e["sha256"] == hashlib.sha256(text.encode("utf-8")).hexdigest()

def test_intake_rejects_unknown_author(tmp_path, monkeypatch):
    monkeypatch.setattr(ai_mirror, "AI_DIR", tmp_path)
    with pytest.raises(ValueError):
        ai_mirror.intake("NOPE", "m", "2026-11-17", "app", False)
```

- [ ] **Step 2: Run to verify they fail.** Run: `.venv/bin/python -m pytest tests/test_scholarly_ai_mirror.py -k "normalise or intake" -q`. Expected: FAIL (no attribute).

- [ ] **Step 3: Implement.** In order: cut everything from the first line that is only `references`, `bibliography`, `works cited`, `notes` or `endnotes` (any case, optional colon); drop lines starting with `#` and a line equal to the title (case and punctuation ignored); remove `**`, `__` and single `*`/`_` emphasis markers and leading bullet or number markers; split on blank lines; apply `clean.strip_inline` to each paragraph; drop paragraphs under 12 words; join with `"\n\n"`. `intake` prints a reminder to send `CONTINUE_PROMPT` once when `words < CONTINUE_BELOW` and `continued` is false.

- [ ] **Step 4: Run the tests.** Run: `.venv/bin/python -m pytest tests/test_scholarly_ai_mirror.py -q`. Expected: all pass.

- [ ] **Step 5: Commit.** `git commit -m "Add cleaning and intake for AI-mirror replies"`

---

### Task 5: The environment gate

**Files:**
- Modify: `validation/scholarly/ai_mirror.py`
- Test: `tests/test_scholarly_ai_mirror.py`

**Interfaces:**
- Consumes: `rule_d.fit_or_load_vectorizers`, `rule_d.calibrate(collection, n_boot)` (returns a dict, writes no file), `fetch.verify`.
- Produces: `thresholds_match(recomputed: dict[str, float], committed: dict[str, float]) -> list[str]` (config names that differ at 6 decimals or are missing); `check_environment(n_boot: int = 10) -> dict`, CLI `check-env`, writing `ai_mirror/environment_humanities.json` with `{date, verify, vectorizers_sha256, sha_matches_committed, recomputed, committed, mismatches, passed}`. `passed` is `mismatches == []`; a different vectorizer hash alone does not fail the gate (pickle bytes can differ across library builds) but is recorded.

- [ ] **Step 1: Write the failing tests**

```python
COMMITTED = {"matched_300_300": -0.529301, "matched_1200_1200": -1.244517,
             "long_past_1200_short_new_300": -0.919008}

def test_thresholds_match_equal_at_six_decimals():
    assert ai_mirror.thresholds_match({**COMMITTED, "matched_300_300": -0.5293014}, COMMITTED) == []

def test_thresholds_match_reports_difference_and_missing():
    r = {"matched_300_300": -0.529302, "matched_1200_1200": -1.244517}
    assert ai_mirror.thresholds_match(r, COMMITTED) == ["long_past_1200_short_new_300", "matched_300_300"]
```

- [ ] **Step 2: Run to verify they fail.** Expected: FAIL (no attribute).
- [ ] **Step 3: Implement** (return the list sorted).
- [ ] **Step 4: Run the tests.** Expected: all pass.
- [ ] **Step 5: Commit.** `git commit -m "Add environment gate comparing rebuilt rule D thresholds with the committed ones"`

---

### Task 6: Scoring summary and the single locked opening

**Files:**
- Modify: `validation/scholarly/ai_mirror.py`
- Test: `tests/test_scholarly_ai_mirror.py`

**Interfaces:**
- Consumes: `rule_d.build_scores(..., extra_docs=...)` (Task 2), `rule_d.cell_report`, `loader.load_trial_grid`, `loader.cut_words`, `loader._rank`, `Target` (Task 3), the AI manifest (Task 4), the environment file (Task 5).
- Produces:
  - `wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]`; `(0.0, 1.0)` when `n == 0`.
  - `decide(k: int, n: int) -> str`: `"below_95"` when the Wilson upper end is under 0.95, else `"95_not_ruled_out"`; `"no_papers"` when `n == 0`.
  - `ai_cut(text: str, words: int, author_id: str) -> str`: `loader.cut_words(text, words, random.Random(loader._rank(SEED, "ai:" + author_id)))`.
  - `ai_extra_docs(texts: dict[str, str]) -> tuple[dict, dict[str, list[str]]]`: the `extra_docs` mapping for `(config, SEED)` of every config in `CONFIGS`, and per config the authors left out because the text is shorter than that config's new-paper length.
  - `summarise_ai(rows: list[dict], thresholds: dict[str, float], targets: list[Target], left_out: dict) -> dict`: per config `{caught, n, rate, wilson95, outcome, per_tool: {tool: [caught, n]}, missing_authors, papers: [{author, tool, D, caught}]}` plus `honest_same_authors: {config: {flagged, n}}` from seed-7 honest rows of the targets. Caught means `D > threshold`.
  - `reproduction_diff(cells: dict, published: dict) -> list[str]`: `"config/kind/key"` for each of `honest_flag_rate, catch_rate, auc, n_authors, n_honest, n_probe` that differs.
  - `open_locked(study: str, n_boot: int = 1000) -> dict`, CLI `locked --study ...`. Guards, all checked before `load_trial_grid` is called: study equals `STUDY_ID`; no `ai_mirror_humanities_locked_test_*.json` exists; the environment file exists with `passed: true`; every AI text's sha256 equals its manifest entry; `git status --porcelain validation/scholarly/ai_mirror` is empty. Then: open the full grid (`CONFIGS` x `SEEDS`, `n_past=4, n_new=2, n_probes=5`, `allow_locked_for=study`), score with `extra_docs`, compute the non-AI cells as `rule_d.locked` does, and write `validation/scholarly/ai_mirror_humanities_locked_test_<YYYY-MM-DD>.json` with `{study_id, date, vectorizers_sha256, thresholds, reproduction: {equal, diffs}, ai: summarise_ai(...), skipped}`.

- [ ] **Step 1: Write the failing tests**

```python
def test_wilson_and_decide():
    assert tuple(round(x, 3) for x in ai_mirror.wilson(19, 20)) == (0.764, 0.991)
    assert round(ai_mirror.wilson(20, 20)[0], 3) == 0.839
    assert ai_mirror.decide(17, 20) == "below_95" and ai_mirror.decide(18, 20) == "95_not_ruled_out"
    assert ai_mirror.wilson(0, 0) == (0.0, 1.0) and ai_mirror.decide(0, 0) == "no_papers"

def test_ai_cut_single_paragraph():
    text = " ".join(["word"] * 1250)
    assert len(ai_mirror.ai_cut(text, 1200, "A1").split()) == 1200
    assert ai_mirror.ai_cut(text, 1200, "A1") == ai_mirror.ai_cut(text, 1200, "A1")

def test_short_ai_text_enters_only_300_configs():
    extra, left_out = ai_mirror.ai_extra_docs({"A1": " ".join(["w"] * 800)})
    assert "A1" not in extra[("matched_1200_1200", 7)]
    assert "A1" in extra[("matched_300_300", 7)] and "A1" in extra[("long_past_1200_short_new_300", 7)]
    assert left_out["matched_1200_1200"] == ["A1"]

def test_summarise_reports_missing_author():
    # targets A1 (claude), A2 (gemini); only A1 has an ai row, D above threshold
    s = ai_mirror.summarise_ai(rows, {"matched_1200_1200": -1.0, ...}, targets, {})
    c = s["matched_1200_1200"]
    assert (c["caught"], c["n"], c["missing_authors"]) == (1, 1, ["A2"])
    assert c["wilson95"] == list(ai_mirror.wilson(1, 1))

def test_reproduction_diff():
    pub = {"matched_1200_1200": {"random": {"catch_rate": 0.9477, "auc": 0.98}}}
    new = {"matched_1200_1200": {"random": {"catch_rate": 0.9478, "auc": 0.98}}}
    assert ai_mirror.reproduction_diff(new, pub) == ["matched_1200_1200/random/catch_rate"]

@pytest.mark.parametrize("broken", ["wrong_study", "result_exists", "env_failed",
                                    "text_hash_differs", "uncommitted"])
def test_open_locked_guards(broken, tmp_path, monkeypatch):
    # set up a passing fixture under tmp_path, break one thing, and stub load_trial_grid
    # to fail the test if it is ever called
    with pytest.raises(SystemExit):
        ai_mirror.open_locked(study)
```

- [ ] **Step 2: Run to verify they fail.** Expected: FAIL (no attribute).
- [ ] **Step 3: Implement** the interfaces above.
- [ ] **Step 4: Run the tests.** Run: `.venv/bin/python -m pytest tests/test_scholarly_ai_mirror.py tests/test_scholarly_corpus.py -q`. Expected: all pass.
- [ ] **Step 5: Commit.** `git commit -m "Add the single locked_test opening for the AI-mirror screen"`

---

### Task 7: Select the targets and pre-register (before any AI paper exists)

**Files:**
- Create: `validation/scholarly/ai_mirror/targets_humanities.json`, `validation/scholarly/ai_mirror/prompts_humanities.md` (by the CLI)
- Create: `docs/research/2026-11-16-scholarly-ai-mirror-preregistration.md`

- [ ] **Step 1:** Run `.venv/bin/python -m validation.scholarly.ai_mirror select`. Expected: 20 targets, tools 7/7/6, both files written.
- [ ] **Step 2:** Ask Andrew which route the Claude share takes (claude.ai pasted by him, or a fresh subagent given only the prompt). Record his answer.
- [ ] **Step 3:** Write the pre-registration, modelled on `docs/research/2026-11-12-scholarly-locked-test-preregistration.md`: tool, date, question, decision it informs; study id; the statement that nothing changes after this commit and results are reported as they come out; a link to the spec for the design; the SHA-256 of `targets_humanities.json`; the prompt and continuation text; the committed thresholds; the decision rule (17 or fewer of 20 caught: below 95%; 18 or more: 95% not ruled out, scale to about 130); the Claude-share route; that venue names are used exactly as recorded in the committed candidate list (two are cut at 80 characters and two are repositories, not journals); the opening procedure (one cloud session: restore, `check-env`, `locked` only if `passed`; if the gate fails, stop and report to Andrew, AI papers stay committed and unused).
- [ ] **Step 4:** Commit and push: `git commit -m "Pre-register the rule D AI-mirror screen (study scholarly-ai-mirror-2026-11-16)"`, `git push -u origin claude/rule-d-ai-mirror`.

---

### Task 8: Generate and record the 20 AI papers

No code. Done when 20 entries are in `ai_mirror/manifest_humanities.json`.

- [ ] **Step 1:** Andrew pastes each prompt from `prompts_humanities.md` into the assigned app in a new chat, and saves the whole reply to `validation/scholarly/ai_mirror/raw/<author_id>.txt`. For the subagent route (Claude share only, if chosen): one fresh `general-purpose` subagent per paper, whose entire prompt is the filled prompt and nothing else (as the spec says); save its reply the same way and record the model id.
- [ ] **Step 2:** Run `intake` for each. Where it reports fewer than 1,300 words, send `CONTINUE_PROMPT` once in the same chat, save that reply to `validation/scholarly/ai_mirror/raw/<author_id>.cont.txt`, and re-run `intake` with `--continued`. Before committing, read each entry's paragraph-cut counts and look at any non-zero one. No other re-prompting, regenerating or editing.
- [ ] **Step 3:** Commit raw files, texts and the manifest, and push: `git commit -m "Add the 20 AI-mirror papers for the rule D screen"`.

---

### Task 9: Rebuild, gate, open once, report

Runs in one Claude Code cloud session on this branch (Linux), so the restored cache lasts from Step 2 to Step 5.

- [ ] **Step 1:** `sudo apt-get install -y poppler-utils`; create `.venv` and install per README.
- [ ] **Step 2:** `.venv/bin/python -m validation.scholarly.fetch --collection humanities --restore`, then `--verify`. Expected: `missing` and `hash_mismatch` near 0; record both.
- [ ] **Step 3:** `.venv/bin/python -m validation.scholarly.ai_mirror check-env` (long; run in the background). If `passed` is false: commit the environment file, push, stop, and report the mismatches to Andrew. Do not open `locked_test`. If it is true: commit and push the environment file (`git commit -m "Add the AI-mirror environment gate result"`) before Step 4; the `locked` step refuses while anything under `ai_mirror/` is uncommitted.
- [ ] **Step 4:** `.venv/bin/python -m validation.scholarly.ai_mirror locked --study scholarly-ai-mirror-2026-11-16` (once). Expected: one new line in `LOCKED_OPENINGS.tsv`, the result JSON written.
- [ ] **Step 5:** Write `docs/research/<date>-scholarly-ai-mirror-results.md`: the primary (1200 vs 1200) and secondary (1200 past vs 300 new) results as caught/n with Wilson intervals and the outcome, the same authors' honest flags beside each, the per-tool table marked descriptive, the reproduction check, missing authors, and the limits (published humanities scholarship, not student writing; topic-only prompts; three tools; 20 is a screen). Add a `scholarly/ai_mirror` paragraph to `validation/scholarly/README.md` and one line to the `docs/STATUS.md` session log.
- [ ] **Step 6:** Run `.venv/bin/python -m pytest tests/test_scholarly_ai_mirror.py tests/test_scholarly_corpus.py -q` (expect all pass), commit the results JSON, `LOCKED_OPENINGS.tsv`, write-up, README and STATUS (`git commit -m "Add rule D AI-mirror screen results (single locked opening)"`), push, and open a draft PR into `claude/practical-mendel-d9eju5` with the AGENTS.md checklist and the body ending `🤖 Generated with [Claude Code](https://claude.com/claude-code)`.
