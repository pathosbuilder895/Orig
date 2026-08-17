# Branch Coverage Part 5 — Context Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Read `2026-08-17-branch-coverage-index.md` §Global Constraints first — they all apply here.

**Goal:** Close the 56 missing branches in `original/context/` (84.18%). These are resolver fallback arms, the genre-v2 rule tree and fail-closed loader, blend detection, and narrative generation — the layer whose *degraded* paths are documented product behavior (abstention, `unknown`, `degraded: True` sentinels).

**Architecture:** Resolver tests are pure-function tests with deterministic inputs; nondeterministic third-party seams (`langdetect`, sklearn TF-IDF) are monkeypatched at the module attribute. Genre-v2 tests must preserve the documented invariant set: `off` byte-identical to v1, `unknown` means do-nothing everywhere, loader fails closed to abstention and NEVER falls back to the rules.

**Tech Stack:** pytest, monkeypatch, tmp_path artifacts.

**Baseline data:** `2026-08-17-branch-coverage-baseline.md` §context.

## Global Constraints (additional to the index's)

- **`tests/context/test_genre_dispatch.py` pins `off` ≡ v1 byte-identity over committed corpora** — nothing in this part may touch those tests or that guarantee.
- Genre-v2 loader tests must assert the fail-closed CONTRACT (bad artifact → abstention, never rule fallback) — CLAUDE.md documents this as a deliberate design decision.
- `resolve_topic`'s degraded paths carry `degraded: True` and `_topic_inflation_vector` treats them as no-inflation (`TOPIC_VARIANCE_INFLATION` row) — the remaining `resolve_topic` arm must be tested against that contract, not just for non-crash.

## Measured gap tables (2026-08-17)

| File | Missing | Functions |
|---|---|---|
| `context/resolvers.py` | 17 | `resolve_language` 5/16, `_resolve_genre_v1` 3/20, `resolve_composition_mode` 2/10, singles in `run_resolvers`, `resolve_topic`, `resolve_length`, `resolve_citations`, `_looks_structured`, `_estimate_punct_error_ratio`, `_estimate_comma_splice_rate` |
| `context/genre_v2.py` | 15 | `_resolve_by_rules` 7/18, `_load_artifact` 5/20, `extract_signals` 1/4, `_ensure_loaded` 1/6, `_confidence_min` 1/2 |
| `context/report.py` | 9 | `generate_narrative` 4/26, `_flatten_flags` 2/2, singles in `build_report`, `_baseline_cluster_labels`, `_anchor_consistency` |
| `context/blend.py` | 7 | `detect_blend` 7/20 |
| `context/baseline_match.py` | 7 | `ensure_sample_context_metadata` 3/12, `_ensure_tfidf_vectorizer` 2/6, singles in `match_baseline_cluster`, `_transform_centroid` |
| `context/manifest.py` | 1 | `_derive_directives` 1/18 |

---

### Task 1: `resolve_language` — 5/16 missing (worked example)

**Files:**
- Create: `tests/context/test_resolvers_branches.py`

**Interfaces:**
- Consumes: `original.context.resolvers.resolve_language`, module attributes `_LANGDETECT_AVAILABLE`, `detect_langs`, `_LANG_WINDOW_CHARS` (200).
- Produces: the fake-`detect_langs` pattern Tasks 2-3 reuse for determinism.

The function (read 2026-08-17, `resolvers.py:71-130`) has: empty-text arm, langdetect-unavailable arm, short-text (≤200 chars) single-detection path with an empty-result arm, and a windowed path with a skip arm (<20 stripped chars), per-window exception arm, zero-usable-windows arm, and the code-switch threshold.

- [ ] **Step 1: Write the failing tests**

```python
"""Branch tests for context resolvers (part 5, task 1)."""

from __future__ import annotations

from types import SimpleNamespace

from original.context import resolvers


def _lang(code, prob=0.99):
    return SimpleNamespace(lang=code, prob=prob)


class TestResolveLanguage:
    def test_langdetect_unavailable_defaults_to_english(self, monkeypatch):
        monkeypatch.setattr(resolvers, "_LANGDETECT_AVAILABLE", False)
        out = resolvers.resolve_language("Any text at all, long or short.")
        assert out == {"primary": "en", "segments": {"en": 1.0}, "code_switched": False}

    def test_short_text_single_detection(self, monkeypatch):
        monkeypatch.setattr(resolvers, "_LANGDETECT_AVAILABLE", True)
        monkeypatch.setattr(resolvers, "detect_langs", lambda t: [_lang("de")])
        out = resolvers.resolve_language("Kurzer deutscher Text.")  # ≤ 200 chars
        assert out["primary"] == "de"
        assert out["segments"] == {"de": 1.0}

    def test_short_text_empty_detection_falls_back_to_unknown(self, monkeypatch):
        monkeypatch.setattr(resolvers, "_LANGDETECT_AVAILABLE", True)
        monkeypatch.setattr(resolvers, "detect_langs", lambda t: [])
        out = resolvers.resolve_language("hmm.")
        assert out == {"primary": "unknown", "segments": {}, "code_switched": False}

    def test_windowed_path_skips_blank_windows_and_counts_the_rest(self, monkeypatch):
        monkeypatch.setattr(resolvers, "_LANGDETECT_AVAILABLE", True)
        monkeypatch.setattr(resolvers, "detect_langs", lambda t: [_lang("en")])
        # > 200 chars so the sliding-window path runs; embed a long
        # whitespace run so at least one window strips below 20 chars.
        text = ("English prose continues here. " * 10) + (" " * 400) + (
            "And resumes after the gap with more English prose. " * 10
        )
        out = resolvers.resolve_language(text)
        assert out["primary"] == "en"
        assert out["code_switched"] is False

    def test_all_windows_unusable_yields_unknown(self, monkeypatch):
        monkeypatch.setattr(resolvers, "_LANGDETECT_AVAILABLE", True)

        def _raise(t):
            raise ValueError("no features in text")

        monkeypatch.setattr(resolvers, "detect_langs", _raise)
        out = resolvers.resolve_language("x " * 300)  # long, but every window raises
        assert out == {"primary": "unknown", "segments": {}, "code_switched": False}

    def test_code_switch_flag_fires_above_threshold(self, monkeypatch):
        monkeypatch.setattr(resolvers, "_LANGDETECT_AVAILABLE", True)
        calls = {"n": 0}

        def _alternate(t):
            calls["n"] += 1
            return [_lang("es" if calls["n"] % 3 == 0 else "en")]

        monkeypatch.setattr(resolvers, "detect_langs", _alternate)
        out = resolvers.resolve_language("Plenty of text here to window over. " * 40)
        assert out["primary"] == "en"
        assert out["segments"].get("es", 0) > 0
        assert out["code_switched"] is True  # ~33% es > LANGUAGE_CODE_SWITCH_THRESHOLD
```

- [ ] **Step 2: Run**

Run: `.venv/bin/python -m pytest tests/context/test_resolvers_branches.py -q`
Expected: PASS, except possibly the code-switch test — check `LANGUAGE_CODE_SWITCH_THRESHOLD`'s value in the module first and set the alternation ratio safely above it.

- [ ] **Step 3: Verify + commit**

```bash
.venv/bin/python -m pytest tests/context/ -q \
  --cov=original.context.resolvers --cov-branch --cov-report=term-missing
git add tests/context/test_resolvers_branches.py
git commit -m "Add resolve_language branch tests for fallback, windowing, and code-switch arms"
```

---

### Task 2: Remaining resolver arms (12)

- [ ] Extract exact arms (index snippet). `_resolve_genre_v1`'s 3 (rule-tree arms the committed corpora never hit — synthetic minimal inputs per rule; do NOT touch the byte-identity suite), `resolve_composition_mode`'s 2, and the singles: `resolve_topic`'s remaining arm must assert the `degraded: True` no-inflation contract; `_looks_structured` / punctuation estimators want boundary inputs; `run_resolvers`' remaining arm is likely the exception-isolation wrapper — stub one resolver to raise and assert the others still resolve.
- [ ] Verify + commit `"Add remaining context-resolver branch tests"`.

### Task 3: `genre_v2.py` (15)

- [ ] `_load_artifact` 5/20: tmp-path artifacts per validation arm (missing file, bad schema version, class-set mismatch, coefficient-width mismatch, reference-prediction drift — read the loader for the exact five). Each must yield abstention; assert NO rule fallback fires (the resolver returns `unknown`, not a rule label).
- [ ] `_resolve_by_rules` 7/18: synthetic texts driving the rule arms the corpora never exercised (curly-quote dialogue arm, markup arm, signal-verb arms — the CLAUDE.md `GENRE_RESOLVER_V2` row's history explains which rules were starved and why).
- [ ] `extract_signals`/`_ensure_loaded`/`_confidence_min` singles.
- [ ] Verify + commit `"Add genre-v2 loader fail-closed and rule-arm branch tests"`.

### Task 4: `blend.py` `detect_blend` (7) + `baseline_match.py` (7)

- [ ] `detect_blend` 7/20: too-few-windows arm, uniform-document arm (no shift), single-shift, shift-at-boundary, and the `AI_LIKELIHOOD_SHADOW` window-attach arms if unexercised — but `tests/context/test_blend.py` already pins the flag-off byte-identity; extend THAT file.
- [ ] `baseline_match.py`: `ensure_sample_context_metadata`'s 3 backfill arms (samples missing genre/topic metadata), `_ensure_tfidf_vectorizer`'s sklearn-absent arm (monkeypatch import seam), singles.
- [ ] Verify + commit `"Add blend-detection and baseline-match branch tests"`.

### Task 5: `report.py` (9) + `manifest.py` (1)

- [ ] `generate_narrative` 4/26: flag-combination arms selecting narrative fragments (extract lines; drive via `build_report` with manifests exercising each). `_flatten_flags` 2/2 (nested vs flat). `_derive_directives`' single remaining arm.
- [ ] Verify + commit `"Add context report narrative branch tests"`.

### Task 6: Sweep + part completion

- [ ] Re-measure; cluster ≥95% or annotated; drain partials; update index dashboard; CI ratchet; commit `"Record part 5 context branch-coverage completion"`.

## Self-Review Notes

- Task 1 was written from the actual function source (read 2026-08-17). The short-text exception arm at `resolvers.py:108` already carries `# pragma: no cover` — leave it; that pragma predates this effort.
- The genre-v2 invariants in this plan restate CLAUDE.md's flag row; if a test contradicts one, the test is wrong or the code regressed — either way, stop and diagnose before proceeding.
