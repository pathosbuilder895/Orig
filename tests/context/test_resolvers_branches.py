"""Branch tests for context resolvers (part 5, task 1).

Targets original.context.resolvers.resolve_language: closes the branches
left uncovered by tests/context/test_resolvers.py, which only exercises the
"real langdetect on long text" arms. See resolvers.py:71-139 for the source
this reconciles against (read 2026-08-19).
"""

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
