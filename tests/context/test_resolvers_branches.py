"""Branch tests for context resolvers (part 5, tasks 1-2).

Task 1 targeted original.context.resolvers.resolve_language (closes the
branches left uncovered by tests/context/test_resolvers.py, which only
exercises the "real langdetect on long text" arms — see resolvers.py:71-139).

Task 2 extends this file to close every remaining branch reported by:

    .venv/bin/python -m pytest tests/context/ -q \
        --cov=original.context.resolvers --cov-branch --cov-report=term-missing

as measured 2026-08-19 (93% -> target 100%). Missing arms at that baseline,
matched against the live source (not the stale plan brief, which cited
line/arm counts that no longer matched):

    255            _resolve_genre_v1 rule 1 (academic_exegesis)
    287            _resolve_genre_v1 rule 6 (creative_fiction)
    290            _resolve_genre_v1 rule 7 (structured_template)
    307            _looks_structured: `if not lines: return False`
    393            resolve_topic: centroid-norm underflow -> degraded True
    449->455       resolve_length: for-loop exhausted without a bounds match
                   (defensive fallback to the pre-loop "long" default)
    514->525       resolve_citations: format-cue loop completes without a
                   match -> stays "informal"
    569->571       resolve_composition_mode: paste_rate <= 0 skips the
                   software_mediated=True arm
    572            resolve_composition_mode: heavy edit-signature arm
    615            _estimate_comma_splice_rate: `if not sentences: return 0.0`
    624            _estimate_punct_error_ratio: `if not text: return 0.0`
    663->670       run_resolvers: citation_data already supplied, skips the
                   internal preprocess() call entirely
    666-668        run_resolvers: internal preprocess() raises -> falls back
                   to citation_data=None (other resolvers still complete)

Note on `_resolve_genre_v1`: this function is ALSO pinned byte-identical to
v1 rules over the committed corpora by tests/context/test_genre_dispatch.py.
That file and that guarantee are not touched here — the texts below are new,
synthetic, minimal inputs constructed only to walk specific rule-tree arms
the committed corpora happen not to exercise, verified against the live
GENRE_RULES thresholds (see the arithmetic each test's docstring/comment
references) rather than guessed.
"""

from __future__ import annotations

import re as _re
from types import SimpleNamespace

import numpy as np

from original.context import resolvers
from original.features.preprocess import CitationData


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
        out = resolvers.resolve_language("Kurzer deutscher Text.")  # <= 200 chars
        assert out["primary"] == "de"
        assert out["segments"] == {"de": 1.0}
        assert out["code_switched"] is False

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
        text = (
            ("English prose continues here. " * 10)
            + (" " * 400)
            + ("And resumes after the gap with more English prose. " * 10)
        )
        out = resolvers.resolve_language(text)
        assert out["primary"] == "en"
        assert out["code_switched"] is False

    def test_windowed_path_empty_detection_result_is_skipped(self, monkeypatch):
        # Covers the in-loop `if langs:` False arm: detect_langs succeeds
        # (no exception) but returns an empty list for a usable window, so
        # the window contributes nothing to `counts`/`total` without hitting
        # the except-continue arm covered by test_all_windows_unusable below.
        monkeypatch.setattr(resolvers, "_LANGDETECT_AVAILABLE", True)
        calls = {"n": 0}

        def _sometimes_empty(t):
            calls["n"] += 1
            return [] if calls["n"] % 2 == 0 else [_lang("en")]

        monkeypatch.setattr(resolvers, "detect_langs", _sometimes_empty)
        # > 200 chars, no blank windows.
        text = "Plenty of usable English prose in every window here. " * 20
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
        assert out["code_switched"] is True  # ~33% es > LANGUAGE_CODE_SWITCH_THRESHOLD (0.05)


class TestResolveGenreV1RuleTree:
    """Synthetic minimal inputs for the three rule-tree arms the committed
    corpora never hit. Does NOT touch test_genre_dispatch.py or its
    byte-identity guarantee — these call `_resolve_genre_v1` directly with
    new text, same as every other test in this module.
    """

    def test_rule1_heavy_citation_signal_verbs_long_sentences_is_academic_exegesis(self):
        # cite_density = 3 citations / 75 words * 100 = 4.0 >= 1.5 (min)
        # msl = 27.0 >= 20.0 (min); signal_verb_total = 3 >= 3 (min)
        # (argues/contends/maintains each match `_SIGNAL_PHRASE_RE` once).
        text = (
            "Smith argues that the doctrine of justification developed significantly "
            "throughout the long medieval period shaping subsequent theological "
            "discourse across many centuries indeed (Smith, 2020, p. 45). Jones "
            "contends that this development reflects deeper philosophical currents "
            "within scholastic thought that many later scholars continue to debate "
            "today in various academic circles (Jones, 2019, p. 12). Brown maintains "
            "that these currents ultimately trace back to Augustinian influences upon "
            "later medieval commentators writing throughout western Europe during "
            "that formative era (Brown, 2018, p. 7)."
        )
        out = resolvers._resolve_genre_v1(text)
        assert out == {"primary": "academic_exegesis", "confidence": 0.5, "secondary": None}

    def test_rule6_dialogue_without_citation_framing_is_creative_fiction(self):
        # No signal verbs, no citations (cite_density 0 < 0.1), no block
        # quote, msl ~16.3 (14 < msl < 20 so rules 4/5 don't intercept it
        # first), and a short quoted span matches the dialogue regex.
        text = (
            '"The tide always tells the truth to those who wait," the captain '
            "murmured quietly. Rain lashed against the broken windows as thunder "
            "rolled steadily through the abandoned harbor town below the cliffs. "
            "Nobody dared to leave the shelter of the old lighthouse until well "
            "past midnight had finally arrived."
        )
        out = resolvers._resolve_genre_v1(text)
        assert out == {"primary": "creative_fiction", "confidence": 0.5, "secondary": None}

    def test_rule7_structural_markers_without_earlier_match_is_structured_template(self):
        # A numbered/bulleted list: no citations, no dialogue quotes (so
        # rules 1-6 all fall through), and `_looks_structured` reads True
        # (100% of non-blank lines open with a list/heading marker).
        text = (
            "1. Introduction and overview of the entire project scope and its many "
            "various goals\n"
            "2. Background information and detailed history relevant to this "
            "particular subject matter\n"
            "3. Methodology used throughout the analysis including data collection "
            "procedures applied\n"
            "4. Results obtained from testing across every scenario considered "
            "during the study\n"
            "5. Conclusion summarizing findings and outlining future work still to "
            "be done\n"
            "- Additional note about limitations encountered while carrying out "
            "this research project\n"
            "- Another note about scope and boundaries defined at the outset of "
            "the work\n"
        )
        out = resolvers._resolve_genre_v1(text)
        assert out == {"primary": "structured_template", "confidence": 0.5, "secondary": None}


class TestLooksStructuredBoundary:
    def test_no_non_blank_lines_returns_false(self):
        assert resolvers._looks_structured("") is False

    def test_whitespace_only_text_returns_false(self):
        assert resolvers._looks_structured("   \n\t \n  ") is False


class TestResolveTopicDegraded:
    def test_centroid_norm_underflow_returns_degraded_medium(self, monkeypatch):
        # Forces the `norm < 1e-12` guard (resolvers.py:391-398) without a
        # contrived corpus: patch np.linalg.norm (the exact call the
        # function makes on the re-normalised centroid) to report underflow.
        # Per CLAUDE.md's TOPIC_VARIANCE_INFLATION row, "degraded" must be
        # True here so a resolver failure never reads as maximum topic
        # distance to a caller keying inflation off this dict.
        monkeypatch.setattr(np.linalg, "norm", lambda *a, **k: 0.0)
        out = resolvers.resolve_topic(
            "Some submission text about theology and history.",
            ["Baseline text about theology.", "Another baseline text about history."],
        )
        assert out == {
            "domain": "unknown",
            "baseline_distance": 0.5,
            "novelty": "medium",
            "degraded": True,
        }


class TestResolveLengthFallback:
    def test_bounds_gap_falls_back_to_pre_loop_default(self, monkeypatch):
        # LENGTH_REGIME_BOUNDS ships as a contiguous [0, inf) partition, so
        # the for-loop always finds a match on real token counts and the
        # pre-loop `regime = "long"` default is only reachable if the bounds
        # table itself has a gap. That is exactly the scenario this default
        # defends against, so exercise it by patching the module-level
        # bounds to a table with a gap rather than declaring the line
        # unreachable.
        monkeypatch.setattr(resolvers, "LENGTH_REGIME_BOUNDS", {"short": (150, 500)})
        out = resolvers.resolve_length("word " * 5000)  # 5000 tokens: outside (150, 500)
        assert out["regime"] == "long"
        assert out["tokens"] == 5000


class TestResolveCitationsFormatFallback:
    def test_no_format_cue_matches_stays_informal(self):
        # A bare "ibid" (no trailing period/comma) trips `_IBID_RE`
        # (`\bibid(?:\.|,)?\b`, count > 0) but not the "chicago" format cue
        # (`\bibid\.` requires the period), and nothing else in the text
        # matches turabian/mla/apa either. The format loop must therefore
        # run to completion over every label without breaking, leaving
        # "informal".
        text = (
            "As cited above ibid the argument holds broadly across many later "
            "theological works today."
        )
        out = resolvers.resolve_citations(text)
        assert out["citations_present"] is True
        assert out["format"] == "informal"


class TestResolveCompositionModeKeystrokeBranches:
    def test_zero_paste_rate_skips_software_mediated_but_heavy_edit_signature_fires(
        self, monkeypatch
    ):
        import original.features.tier17 as tier17_mod

        monkeypatch.setattr(
            tier17_mod,
            "extract_tier17",
            lambda kd: {
                "paste_event_rate": 0.0,
                "deletion_rate": 0.9,  # > 0.20 -> edit_signature = "heavy"
                "revision_depth": 0.0,
            },
        )
        text = "This is a normal short test paragraph with some words in it today."
        out = resolvers.resolve_composition_mode(text, keystroke_data={"keystrokes": []})
        assert out["software_mediated"] is False
        assert out["edit_signature"] == "heavy"
        assert out["mode"] == "natural_drafted"


class TestPunctuationAndCommaSpliceEstimatorBoundaries:
    def test_punct_error_ratio_empty_text_is_zero(self):
        assert resolvers._estimate_punct_error_ratio("") == 0.0

    def test_comma_splice_rate_defends_against_an_empty_split_result(self, monkeypatch):
        # `re.split(r"(?<=[.!?])\s+", text)` always returns a list with at
        # least one element for any str input (including "") — the
        # `if not sentences` guard has no reachable real-text input. Rather
        # than leave it unreachable, patch `re.split` itself to confirm the
        # guard's contract (return 0.0, no ZeroDivisionError) holds if that
        # invariant were ever violated.
        monkeypatch.setattr(_re, "split", lambda *a, **k: [])
        assert resolvers._estimate_comma_splice_rate("Some text here.") == 0.0


class TestRunResolversPreprocessBranches:
    def test_citation_data_already_supplied_skips_internal_preprocess(self, monkeypatch):
        # citation_data is not None, so `run_resolvers` must skip its own
        # `preprocess()` call (663->670) entirely. Prove it by making
        # `preprocess` blow up if it's called at all — the run must still
        # succeed using the supplied (empty) CitationData.
        def _boom(text):
            raise AssertionError("preprocess should not be called when citation_data is given")

        monkeypatch.setattr(resolvers, "preprocess", _boom)
        out = resolvers.run_resolvers(
            "Some short submission text.",
            baseline_texts=[],
            citation_data=CitationData(),
        )
        assert "_errors" not in out
        assert set(out) == {
            "language",
            "genre",
            "topic",
            "length",
            "citations",
            "composition_mode",
        }

    def test_internal_preprocess_failure_falls_back_to_none_other_resolvers_still_run(
        self, monkeypatch
    ):
        # citation_data=None (default) forces run_resolvers to try its own
        # preprocess() call; make it raise so the except branch (666-668)
        # sets citation_data=None and logs instead of propagating. genre and
        # citations both call `preprocess` themselves too (same patched
        # name), so they land in `_errors` — but language/topic/length/
        # composition_mode don't depend on it and must still resolve,
        # matching run_resolvers' documented per-resolver isolation
        # contract.
        def _boom(text):
            raise RuntimeError("synthetic preprocess failure")

        monkeypatch.setattr(resolvers, "preprocess", _boom)
        out = resolvers.run_resolvers("Some short submission text.", baseline_texts=[])

        assert "_errors" in out
        failed = {e["resolver"] for e in out["_errors"]}
        assert {"genre", "citations"} <= failed
        for name in ("language", "topic", "length", "composition_mode"):
            assert name in out
