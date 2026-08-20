# Branch Coverage Part 6 — Feature Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Read `2026-08-17-branch-coverage-index.md` §Global Constraints first — they all apply here.

**Goal:** Close the 84 missing branches in `original/features/` (87.72%). Nearly all are guard arms: short-input neutral fallbacks (0.5), zero-denominator arms (0.0), and optional-dependency degrade paths (spaCy, sentence-transformers, word-frequency tables). These guards decide what value enters the 109-dim vector when a submission is thin or a dependency is absent — silent-wrong here poisons every downstream score.

**Architecture:** Pure-function tests over hand-built `TextDoc` inputs (`original/features/tier1.py:TextDoc(text)` — a plain constructor). Optional-dependency arms are driven by monkeypatching the module-level loader/model attributes, mirroring the approach `tests/test_tier10_st_backend.py` already uses for the sentence-transformers seam.

**Tech Stack:** pytest, monkeypatch; extend existing test files where they exist (`tests/test_uniformity.py`, `tests/test_features.py`, `tests/test_tier10_st_backend.py`).

**Baseline data:** `2026-08-17-branch-coverage-baseline.md` §features.

## Global Constraints (additional to the index's)

- **Neutral values are contract:** the 0.5 fallback fires only under the documented conditions (CLAUDE.md §Feature dimensionality: e.g. tier-10's 0.5 requires too-few-usable-sentences, NOT a missing backend — the TF-IDF fallback is a genuine backend). A test that finds 0.5 where a real value belongs has found a bug.
- **Never reorder or renumber anything in `original/constants.py`** (`ALL_FEATURE_CODES`, `NORM_BOUNDS` are permission-gated).
- Guard-arm tests assert the EXACT sentinel (`== 0.5`, `== 0.0`), not `pytest.approx` — the sentinel is a discrete branch outcome, not a computation.

## Measured gap tables (2026-08-17)

| File | Missing | Functions |
|---|---|---|
| `uniformity.py` | 12 | 2 each: `window_feature_variance_ratio`, `vocab_introduction_flatness`, `sentence_length_dispersion_ratio`, `punctuation_dispersion_ratio`, `function_word_burstiness_ratio`, `clause_depth_variance_ratio` |
| `tier7.py` | 10 | `transition_predictability` 3/10, `_gini_coefficient` 2/6, singles in `vocabulary_introduction_rate`, `repetition_gap_entropy`, `perplexity_proxy`, `burstiness`, `_load_word_freqs` |
| `tier11.py` | 9 | `_extract_error_profile` 6/26, `_get_nlp` 2/4, `compute_tier11_comparison` 1/2 |
| `tier5.py` | 8 | `_shannon_entropy` 2/6, `_get_nlp` 2/4, `_get_dep_depths` 2/6 (+nested `_depth` 1/4), `_get_pos_tags` 1/2 |
| `prosodic.py` | 8 | `_semantic_field_concentration` 3/12, singles in `_word_stress`, `_shannon_entropy`, `_metric_flatness_score`, `_chiasmus_rate`, `_article_omission_rate` |
| `tier10.py` | 7 | `compute_tier10_comparison` 3/12, `_tfidf_encode` 2/4, `_get_st_model` 1/4, `_encode_sentences` 1/4 |
| `tier6.py` | 6 | `citation_style_consistency` 5/10, `list_marker_preference` 1/6 |
| `tier2.py` | 6 | `paragraph_topic_position` 2/12, singles in `thematic_progression_score`, `sentence_opener_variety`, `lexical_chain_density`, `avg_paragraph_length` |
| `tier17.py` | 5 | singles: `typing_speed_cv`, `pause_density`, `paste_event_rate`, `deletion_rate`, `_iki_deltas` |
| `pipeline.py` | 5 | `_kl_divergence` 2/8, singles in `extract_features`, `build_aggregate_baseline_profiles`, `_normalise` |
| `tier4.py` / `tier16.py` / `tier9.py` / `tier3.py` / `tier1.py` / `preprocess.py` | 2+2+1+1+1+1 | `_shannon_entropy` 2/6, singles |

---

### Task 1: `uniformity.py` guard arms — 12 missing (worked example)

**Files:**
- Modify: `tests/test_uniformity.py` (append; keep its existing conventions)

**Interfaces:**
- Consumes: `original.features.uniformity` ratio functions; `original.features.tier1.TextDoc`.
- Produces: nothing later tasks depend on.

Each of the six ratio functions (source read 2026-08-17) guards twice: a short-input arm returning exactly `0.5` and a degenerate-denominator arm returning exactly `0.0` (or a second `0.5` for too-few-windows). The digest shows 2 missing per function — the guards, never exercised because existing tests use full-length prose.

- [ ] **Step 1: Write the failing tests**

```python
# ── Guard-arm branch tests (branch-coverage part 6, task 1) ──────────────────


from original.features.tier1 import TextDoc
from original.features import uniformity


def _doc(text: str) -> TextDoc:
    return TextDoc(text)


class TestUniformityGuardArms:
    def test_sentence_length_dispersion_short_input_is_neutral(self):
        assert uniformity.sentence_length_dispersion_ratio(_doc("One. Two.")) == 0.5

    def test_window_variance_needs_six_sentences(self):
        five = "Alpha one. Beta two. Gamma three. Delta four. Epsilon five."
        assert uniformity.window_feature_variance_ratio(_doc(five)) == 0.5

    def test_window_variance_normal_path_returns_a_real_variance(self):
        nine = (
            "Short one. A somewhat longer second sentence here. Tiny. "
            "Another middling sentence follows now. Very small. "
            "This sentence extends to a considerable and deliberate length indeed. "
            "Brief. Medium sized sentence again here. Final one closes."
        )
        value = uniformity.window_feature_variance_ratio(_doc(nine))
        assert value != 0.5 and value >= 0.0

    def test_function_word_burstiness_needs_five_function_words(self):
        assert uniformity.function_word_burstiness_ratio(_doc("Ships sail westward.")) == 0.5

    def test_punctuation_dispersion_needs_four_sentences(self):
        assert uniformity.punctuation_dispersion_ratio(_doc("A one. B two. C three.")) == 0.5

    def test_vocab_introduction_flatness_short_input_is_neutral(self):
        assert uniformity.vocab_introduction_flatness(_doc("Few words only here.")) == 0.5

    def test_clause_depth_variance_short_input_is_neutral(self):
        assert uniformity.clause_depth_variance_ratio(_doc("Deep. Shallow.")) == 0.5
```

- [ ] **Step 2: Run**

Run: `.venv/bin/python -m pytest tests/test_uniformity.py -q`
Expected: PASS as written for the four functions whose guards this plan read (`sentence_length_dispersion_ratio` <3 sentences, `window_feature_variance_ratio` <6, `function_word_burstiness_ratio` <5 function-word hits, `punctuation_dispersion_ratio` <4). For `vocab_introduction_flatness` and `clause_depth_variance_ratio`, read their guard conditions first and size the inputs to sit just under them.

- [ ] **Step 3: Close each function's SECOND missing arm** — extract the exact pairs with the index snippet; the remaining arms are the zero-mean/`< 1e-9` denominators (e.g. `sentence_length_dispersion_ratio` → `0.0`) or the post-windowing `len < 2` re-guards. A zero-mean sentence list needs sentences whose `split()` is empty after tokenizing — if an arm proves unreachable through any real `TextDoc` (the sentence splitter may guarantee non-empty), annotate it `# pragma: no cover` with that argument instead.

- [ ] **Step 4: Verify + commit**

```bash
.venv/bin/python -m pytest tests/test_uniformity.py -q \
  --cov=original.features.uniformity --cov-branch --cov-report=term-missing
git add tests/test_uniformity.py
git commit -m "Add uniformity guard-arm branch tests pinning the 0.5/0.0 sentinels"
```

---

### Task 2: Optional-dependency seams — `tier5.py`, `tier11.py`, `tier10.py` (24)

- [ ] `_get_nlp` arms (tier5, tier11): spaCy available (cached-model arm on second call) and unavailable (monkeypatch the loader to raise `OSError`) — assert each dependent feature degrades to its documented neutral, not an exception.
- [ ] `tier10.py`: `_get_st_model` absent arm → the TF-IDF fallback MUST produce real non-neutral values (CLAUDE.md pins this); `_tfidf_encode`'s 2 arms (too-few sentences for the 0.5; normal); `compute_tier10_comparison`'s 3 arms; `_encode_sentences` remaining arm. Extend `tests/test_tier10_st_backend.py`.
- [ ] `tier11.py` `_extract_error_profile` 6/26: error-category arms needing specific malformed inputs (read the function; build one minimal text per untaken category).
- [ ] Verify + commit `"Add optional-dependency degrade-path branch tests for tiers 5, 10, 11"`.

### Task 3: Statistical helpers — `tier7.py`, `tier4.py`, `tier16.py`, `pipeline.py`, `prosodic.py` (27)

- [ ] `_gini_coefficient`/`_shannon_entropy` (three modules share the shape): empty input, single-element, all-identical arms — exact sentinels per implementation.
- [ ] `transition_predictability` 3/10 + singles (`burstiness`, `perplexity_proxy`, `repetition_gap_entropy`, `vocabulary_introduction_rate`): short/degenerate-input arms; `_load_word_freqs` missing-file arm via monkeypatched path.
- [ ] `pipeline.py`: `_kl_divergence` zero-mass arms; `extract_features`/`build_aggregate_baseline_profiles`/`_normalise` singles (extract lines first).
- [ ] `prosodic.py`: `_semantic_field_concentration` 3/12 and the five singles — degenerate-input arms (no stressed syllables, no articles, no chiasmus candidates).
- [ ] Verify + commit `"Add statistical-helper degenerate-input branch tests"`.

### Task 4: Structure analyzers — `tier2.py`, `tier6.py`, `tier9.py`, `tier3.py`, `tier1.py`, `preprocess.py`, `tier17.py` (21)

- [ ] `citation_style_consistency` 5/10: per-style arms (footnote vs parenthetical vs none, mixed) — one synthetic text each.
- [ ] `tier2.py` arms: single-paragraph documents, no-opener-variety, empty-chain inputs.
- [ ] `tier17.py` singles: keystroke-log edge shapes (empty log, single event) — these features are DISABLED by default; test the functions directly, do not enable the group.
- [ ] `_tag_move`/`theological_register_score`/`_split_paragraphs`/`_extract_citation_data` singles (extract lines first).
- [ ] Verify + commit `"Add structure-analyzer branch tests for citation, paragraph, and keystroke edges"`.

### Task 5: Sweep + part completion

- [ ] Re-measure; cluster ≥97% branch (it starts at 87.72 — features should end highest of all clusters since almost everything is a pure function) or annotated; drain partials; update index dashboard; CI ratchet; commit `"Record part 6 features branch-coverage completion"`.

## Self-Review Notes

- Task 1's four verified guards were read from source 2026-08-17 (`uniformity.py:34-84`); the two marked verify-first. The `TextDoc` constructor takes just a text string (`tier1.py:19`).
- The tier-10 constraint (fallback produces REAL values; 0.5 only on too-few-sentences) comes verbatim from CLAUDE.md §Feature dimensionality — Task 2's tests operationalize it.
- Sentence-splitter guarantees may make some zero-denominator arms unreachable; the annotation path in Task 1 Step 3 exists for exactly that, argument required.
