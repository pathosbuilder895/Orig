"""
tests/test_tier11.py — optional-dependency (spaCy) and error-category branch
coverage for `original/features/tier11.py`.

Tier 11 (Error Ecology) detects three error categories (comma_splice,
adj_chain, punct_error) via spaCy dependency parsing when available, falling
back to regex heuristics when it is not. These tests cover:

  - `_get_nlp`'s unavailable arm (mirrors tier5: OSError degrades cleanly)
  - each error-category arm on the spaCy path: comma-splice detection, the
    adjective-chain run (both the ADJ-increment and the DET/NUM/PUNCT
    continue arms), and punctuation errors
  - the full regex-fallback block when spaCy is unavailable
  - `compute_tier11_comparison`'s empty-input fallback
"""

from __future__ import annotations

import logging
import sys
import types

from original.features import tier11
from original.features.tier1 import TextDoc


# ── `_get_nlp` unavailable arm ──────────────────────────────────────────────


def test_get_nlp_unavailable_degrades_and_logs_once(monkeypatch, caplog):
    monkeypatch.setattr(tier11, "_nlp", None)
    monkeypatch.setattr(tier11, "_spacy_warning_logged", False)

    def _raise_load(name, disable=None):
        raise OSError("model 'en_core_web_sm' not found")

    fake_spacy = types.ModuleType("spacy")
    fake_spacy.load = _raise_load
    monkeypatch.setitem(sys.modules, "spacy", fake_spacy)

    with caplog.at_level(logging.WARNING, logger="original.features.tier11"):
        result = tier11._get_nlp()

    assert result == "unavailable"
    assert tier11._spacy_warning_logged is True
    assert any("use regex fallbacks" in r.message for r in caplog.records)


def test_get_nlp_caches_model_on_second_call(monkeypatch):
    monkeypatch.setattr(tier11, "_nlp", None)
    first = tier11._get_nlp()
    assert first != "unavailable"
    second = tier11._get_nlp()
    assert second is first


def test_get_nlp_unavailable_does_not_relog_warning_once_already_logged(monkeypatch, caplog):
    """Mirrors the tier5 equivalent: `if not _spacy_warning_logged:` must skip
    re-logging when a previous failure already logged the warning."""
    monkeypatch.setattr(tier11, "_nlp", None)
    monkeypatch.setattr(tier11, "_spacy_warning_logged", True)  # already logged once

    def _raise_load(name, disable=None):
        raise OSError("model 'en_core_web_sm' not found")

    fake_spacy = types.ModuleType("spacy")
    fake_spacy.load = _raise_load
    monkeypatch.setitem(sys.modules, "spacy", fake_spacy)

    with caplog.at_level(logging.WARNING, logger="original.features.tier11"):
        result = tier11._get_nlp()

    assert result == "unavailable"
    assert not any("use regex fallbacks" in r.message for r in caplog.records)


# ── spaCy-path error-category arms ──────────────────────────────────────────


def test_extract_error_profile_detects_comma_splice_via_dependency_parse(monkeypatch):
    """A comma whose left neighbour has a root-like dep (ROOT/ccomp/advcl/
    parataxis) within the same sentence must count as a comma splice."""
    monkeypatch.setattr(tier11, "_nlp", None)
    doc = TextDoc("The sun was setting, the birds flew home.")

    profile = tier11._extract_error_profile(doc)

    assert profile["comma_splice"] > 0.0


def test_extract_error_profile_comma_with_non_matching_left_dep_is_not_a_splice(monkeypatch):
    """A comma is common in well-formed prose too — when the left neighbour's
    dep isn't one of the root-like categories, it must NOT count as a splice
    (the `if left.dep_ in (...)` false arm)."""
    monkeypatch.setattr(tier11, "_nlp", None)
    doc = TextDoc("I finished my homework, she went to the store.")

    profile = tier11._extract_error_profile(doc)

    assert profile["comma_splice"] == 0.0


def test_extract_error_profile_detects_adjective_chain_and_det_continue_arm(monkeypatch):
    """3+ ADJ tokens stacked before a NOUN must count as an adj_chain. The
    same sentence's leading DET ("The") exercises the `elif dep.pos_ not in
    (DET, NUM, PUNCT): break` continue arm (DET is in the allowed set, so the
    loop must continue rather than break) before the ADJ run begins."""
    monkeypatch.setattr(tier11, "_nlp", None)
    doc = TextDoc("The tall dark mysterious stranger walked in.")

    profile = tier11._extract_error_profile(doc)

    assert profile["adj_chain"] > 0.0


def test_extract_error_profile_detects_punct_error_regardless_of_spacy(monkeypatch):
    monkeypatch.setattr(tier11, "_nlp", None)
    doc = TextDoc("Wait, what?! That can't be right...")

    profile = tier11._extract_error_profile(doc)

    assert profile["punct_error"] > 0.0


def test_extract_error_profile_normal_text_has_no_errors(monkeypatch):
    """Sanity check: clean, well-formed text should not trip any category —
    exercises the loop bodies completing without ever matching."""
    monkeypatch.setattr(tier11, "_nlp", None)
    doc = TextDoc("The cat sleeps on the warm windowsill every afternoon.")

    profile = tier11._extract_error_profile(doc)

    assert profile == {"comma_splice": 0.0, "adj_chain": 0.0, "punct_error": 0.0}


# ── Regex-fallback block (spaCy unavailable) ────────────────────────────────


def test_extract_error_profile_regex_fallback_when_spacy_unavailable(monkeypatch):
    """With spaCy unavailable, all three categories must be detected via the
    regex fallbacks instead (comma-splice heuristic, suffix-chain heuristic,
    and the always-regex punctuation check)."""
    monkeypatch.setattr(tier11, "_nlp", "unavailable")
    doc = TextDoc(
        "Later, she left quickly. The exciting amazing wonderful trip was great!!"
    )

    profile = tier11._extract_error_profile(doc)

    assert profile["comma_splice"] > 0.0
    assert profile["adj_chain"] > 0.0
    assert profile["punct_error"] > 0.0


def test_extract_error_profile_regex_fallback_no_matches(monkeypatch):
    """The regex fallback path must also complete cleanly (no matches) on
    text that doesn't trip any of its patterns."""
    monkeypatch.setattr(tier11, "_nlp", "unavailable")
    doc = TextDoc("Quiet mornings bring calm thoughts and simple joy.")

    profile = tier11._extract_error_profile(doc)

    assert profile == {"comma_splice": 0.0, "adj_chain": 0.0, "punct_error": 0.0}


# ── `compute_tier11_comparison` empty-input fallback ────────────────────────


def test_compute_tier11_comparison_returns_fallback_when_base_list_empty():
    result = tier11.compute_tier11_comparison(
        {"_error_profile": {"comma_splice": 1.0}}, {"_error_profiles": []}
    )
    assert result == {
        "error_kl_divergence": 0.5,
        "stumble_rate_consistency": 0.5,
        "punctuation_error_ratio": 0.5,
    }


def test_compute_tier11_comparison_returns_fallback_when_sub_profile_empty():
    result = tier11.compute_tier11_comparison(
        {}, {"_error_profiles": [{"comma_splice": 1.0}]}
    )
    assert result == {
        "error_kl_divergence": 0.5,
        "stumble_rate_consistency": 0.5,
        "punctuation_error_ratio": 0.5,
    }
