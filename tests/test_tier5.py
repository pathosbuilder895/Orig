"""
tests/test_tier5.py — optional-dependency (spaCy) branch coverage for
`original/features/tier5.py`.

Tier 5 (POS & Shallow Syntax) requires spaCy + en_core_web_sm. `_get_nlp()`
lazily loads the model once and caches the singleton (or the sentinel string
"unavailable" on failure) in the module-level `_nlp` global. These tests cover:

  - the cached-model arm (second call returns the same object, no reload)
  - the unavailable arm (`spacy.load` raising OSError degrades to "unavailable"
    and logs a warning once, never raises)
  - every dependent feature's documented neutral default when spaCy is
    unavailable, so a missing model degrades a submission instead of 500ing it
  - `_shannon_entropy`'s empty/zero-count edge cases, unit-tested directly
"""

from __future__ import annotations

import logging
import sys
import types
from collections import Counter

import pytest

from original.features import tier5
from original.features.tier1 import TextDoc


def _long_prose() -> str:
    return (
        "The old librarian carefully catalogued every dusty volume. "
        "She often wondered about the students who never returned books. "
        "Quietly, the afternoon light moved slowly across the reading room."
    )


# ── `_get_nlp` arms ────────────────────────────────────────────────────────


def test_get_nlp_caches_model_on_second_call(monkeypatch):
    """A successful load must populate `_nlp` once; a second call returns the
    exact same cached object rather than reloading the model."""
    monkeypatch.setattr(tier5, "_nlp", None)

    first = tier5._get_nlp()
    assert first != "unavailable"

    second = tier5._get_nlp()
    assert second is first


def test_get_nlp_unavailable_degrades_and_logs_once(monkeypatch, caplog):
    """`spacy.load` raising OSError (missing model download) must set `_nlp`
    to the "unavailable" sentinel and log a warning, never propagate."""
    monkeypatch.setattr(tier5, "_nlp", None)
    monkeypatch.setattr(tier5, "_spacy_warning_logged", False)

    def _raise_load(name, disable=None):
        raise OSError("model 'en_core_web_sm' not found")

    fake_spacy = types.ModuleType("spacy")
    fake_spacy.load = _raise_load
    monkeypatch.setitem(sys.modules, "spacy", fake_spacy)

    with caplog.at_level(logging.WARNING, logger="original.features.tier5"):
        result = tier5._get_nlp()

    assert result == "unavailable"
    assert tier5._spacy_warning_logged is True
    assert any("spaCy model unavailable" in r.message for r in caplog.records)

    # Cached failure: a second call must not attempt to reload spaCy again.
    result2 = tier5._get_nlp()
    assert result2 == "unavailable"


def test_get_nlp_unavailable_does_not_relog_warning_once_already_logged(monkeypatch, caplog):
    """`if not _spacy_warning_logged:` must skip re-logging when a previous
    failure already logged the warning — even if `_nlp` gets reset to None
    again (e.g. a retried load in a long-lived process)."""
    monkeypatch.setattr(tier5, "_nlp", None)
    monkeypatch.setattr(tier5, "_spacy_warning_logged", True)  # already logged once

    def _raise_load(name, disable=None):
        raise OSError("model 'en_core_web_sm' not found")

    fake_spacy = types.ModuleType("spacy")
    fake_spacy.load = _raise_load
    monkeypatch.setitem(sys.modules, "spacy", fake_spacy)

    with caplog.at_level(logging.WARNING, logger="original.features.tier5"):
        result = tier5._get_nlp()

    assert result == "unavailable"
    assert not any("spaCy model unavailable" in r.message for r in caplog.records)


def test_is_spacy_available_reflects_nlp_state(monkeypatch):
    monkeypatch.setattr(tier5, "_nlp", "unavailable")
    assert tier5.is_spacy_available() is False

    monkeypatch.setattr(tier5, "_nlp", object())
    assert tier5.is_spacy_available() is True


# ── `_shannon_entropy` edge cases (unit-tested directly) ──────────────────


def test_shannon_entropy_empty_counter_returns_zero():
    assert tier5._shannon_entropy(Counter()) == 0.0


def test_shannon_entropy_skips_zero_count_entries():
    """A Counter holding an explicit zero-count key must skip that entry
    (the `if count > 0` guard) rather than raising on log2(0)."""
    counter = Counter({"a": 0, "b": 4})
    # total = 4 (from 'b' only); single nonzero class -> entropy is exactly 0.
    assert tier5._shannon_entropy(counter) == 0.0


# ── `_get_pos_tags` / `_get_dep_depths` unavailable arms ───────────────────


def test_get_pos_tags_returns_none_when_spacy_unavailable(monkeypatch):
    monkeypatch.setattr(tier5, "_nlp", "unavailable")
    doc = TextDoc(_long_prose())
    assert tier5._get_pos_tags(doc) is None


def test_get_dep_depths_returns_none_when_spacy_unavailable(monkeypatch):
    monkeypatch.setattr(tier5, "_nlp", "unavailable")
    doc = TextDoc(_long_prose())
    assert tier5._get_dep_depths(doc) is None


# ── Dependent features degrade to documented neutral defaults ──────────────


def test_extract_tier5_degrades_to_documented_neutrals_when_spacy_unavailable(monkeypatch):
    """Every Tier 5 feature must fall back to its documented neutral value
    when spaCy is unavailable, never raise."""
    monkeypatch.setattr(tier5, "_nlp", "unavailable")
    doc = TextDoc(_long_prose())

    result = tier5.extract_tier5(doc)

    assert result == {
        "pos_bigram_entropy": 0.0,
        "pos_trigram_entropy": 0.0,
        "noun_verb_ratio": 1.0,
        "adjective_rate": 0.0,
        "adverb_rate": 0.0,
        "subordination_ratio": 0.0,
        "clause_depth_mean": 3.0,
    }


def test_extract_tier5_produces_real_values_when_spacy_available(monkeypatch):
    """Sanity check for the happy path alongside the degrade tests above:
    with spaCy available, features are computed (not the neutral defaults)."""
    monkeypatch.setattr(tier5, "_nlp", None)
    doc = TextDoc(_long_prose())

    result = tier5.extract_tier5(doc)

    assert result["clause_depth_mean"] != 3.0
    assert isinstance(result["pos_bigram_entropy"], float)
    assert result["pos_bigram_entropy"] > 0.0
