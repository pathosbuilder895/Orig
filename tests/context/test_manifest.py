"""
tests/context/test_manifest.py — Phase 3 ContextManifest tests.

Each test exercises one row of the directive-derivation table directly
against `_derive_directives()` to keep coverage tight and readable.
The orchestrator-level `build_manifest()` smoke test ends the file.
"""

from __future__ import annotations

from typing import Dict

import pytest

from original.context.manifest import (
    ContextManifest,
    _derive_directives,
    build_manifest,
)
from original.constants import (
    TIER1_CODES, TIER7_CODES, TIER10_CODES, TIER11_CODES,
    TIER13_CODES, TIER14_CODES, TIER15_CODES, TIER16_CODES,
)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _resolver_outputs(
    *,
    length_regime: str = "standard",
    genre: str = "scholarly_essay",
    citations_present: bool = True,
    composition_mode: str = "natural_drafted",
    code_switched: bool = False,
    novelty: str = "low",
) -> Dict[str, Dict]:
    """Construct a resolver_outputs dict with the requested per-resolver state."""
    return {
        "language":         {"primary": "en", "segments": {"en": 1.0},
                              "code_switched": code_switched},
        "genre":            {"primary": genre, "confidence": 0.5, "secondary": None},
        "topic":            {"domain": "unknown", "baseline_distance": 0.1,
                              "novelty": novelty},
        "length":           {"tokens": 1000, "regime": length_regime,
                              "reliable_tiers": [], "suppress_tiers": []},
        "citations":        {"citations_present": citations_present,
                              "density": 1.0 if citations_present else 0.0,
                              "block_quote_ratio": 0.0,
                              "format": "chicago" if citations_present else "none"},
        "composition_mode": {"mode": composition_mode,
                              "edit_signature": "normal",
                              "software_mediated": composition_mode == "tool_cleaned"},
    }


# ══════════════════════════════════════════════════════════════════════════════
# Length-regime derivation
# ══════════════════════════════════════════════════════════════════════════════

class TestLengthRegime:
    def test_micro_mutes_most_tiers_keeps_anchors(self):
        d = _derive_directives(_resolver_outputs(length_regime="micro"))
        muted = set(d["weight_modifications"]["mute_codes"])
        # T7 codes (and T1, T2, etc.) muted under micro.
        assert set(TIER7_CODES).issubset(muted)
        assert set(TIER1_CODES).issubset(muted)
        # T4, T6, T13, T14 retained — never appear in mute_codes.
        from original.constants import (
            TIER4_CODES, TIER6_CODES,
        )
        assert not (set(TIER4_CODES) & muted)
        assert not (set(TIER6_CODES) & muted)
        assert not (set(TIER13_CODES) & muted)
        assert not (set(TIER14_CODES) & muted)
        # Default anchors always present.
        assert 4 in d["anchor_tiers"] and 6 in d["anchor_tiers"]

    def test_short_mutes_t7_and_attenuates_ttr(self):
        d = _derive_directives(_resolver_outputs(length_regime="short"))
        muted = set(d["weight_modifications"]["mute_codes"])
        attenuated = set(d["weight_modifications"]["attenuate_codes"])
        assert set(TIER7_CODES).issubset(muted)
        assert "type_token_ratio" in attenuated


# ══════════════════════════════════════════════════════════════════════════════
# Citations
# ══════════════════════════════════════════════════════════════════════════════

class TestCitations:
    def test_no_citations_mutes_t16(self):
        d = _derive_directives(_resolver_outputs(citations_present=False))
        muted = set(d["weight_modifications"]["mute_codes"])
        assert set(TIER16_CODES).issubset(muted)
        # T16 is NOT an anchor when no citations.
        assert 16 not in d["anchor_tiers"]

    def test_with_citations_anchors_t16(self):
        d = _derive_directives(_resolver_outputs(citations_present=True))
        muted = set(d["weight_modifications"]["mute_codes"])
        assert not (set(TIER16_CODES) & muted)
        assert 16 in d["anchor_tiers"]


# ══════════════════════════════════════════════════════════════════════════════
# Genre
# ══════════════════════════════════════════════════════════════════════════════

class TestGenre:
    def test_creative_fiction_mutes_t16(self):
        # Even with citations_present=True, creative_fiction wins (mute > anchor)
        # because mute set strictly dominates per the precedence rules in
        # _derive_directives.
        d = _derive_directives(_resolver_outputs(
            genre="creative_fiction", citations_present=True
        ))
        muted = set(d["weight_modifications"]["mute_codes"])
        assert set(TIER16_CODES).issubset(muted)

    def test_academic_genre_anchors_t8_t13(self):
        for label in ("academic_exegesis", "scholarly_essay", "sermon"):
            d = _derive_directives(_resolver_outputs(genre=label))
            assert 8 in d["anchor_tiers"], f"{label} should anchor T8"
            assert 13 in d["anchor_tiers"], f"{label} should anchor T13"

    def test_blog_post_does_not_anchor_t8_t13(self):
        d = _derive_directives(_resolver_outputs(genre="blog_post"))
        assert 8 not in d["anchor_tiers"]
        assert 13 not in d["anchor_tiers"]


# ══════════════════════════════════════════════════════════════════════════════
# Composition mode
# ══════════════════════════════════════════════════════════════════════════════

class TestCompositionMode:
    def test_tool_cleaned_attenuates_t11_t14(self):
        d = _derive_directives(_resolver_outputs(composition_mode="tool_cleaned"))
        attenuated = set(d["weight_modifications"]["attenuate_codes"])
        assert set(TIER11_CODES).issubset(attenuated)
        assert set(TIER14_CODES).issubset(attenuated)
        assert "software_mediated" in d["flags"]

    def test_natural_drafted_no_attenuation(self):
        d = _derive_directives(_resolver_outputs(composition_mode="natural_drafted"))
        attenuated = set(d["weight_modifications"]["attenuate_codes"])
        # T11 / T14 should not be attenuated by composition mode alone.
        assert not (set(TIER11_CODES) & attenuated)
        assert not (set(TIER14_CODES) & attenuated)
        assert "software_mediated" not in d["flags"]


# ══════════════════════════════════════════════════════════════════════════════
# Topic
# ══════════════════════════════════════════════════════════════════════════════

class TestTopic:
    def test_high_novelty_attenuates_t10_t15(self):
        d = _derive_directives(_resolver_outputs(novelty="high"))
        attenuated = set(d["weight_modifications"]["attenuate_codes"])
        assert set(TIER10_CODES).issubset(attenuated)
        assert set(TIER15_CODES).issubset(attenuated)
        assert "topic_novelty_high" in d["flags"]

    def test_low_novelty_no_attenuation(self):
        d = _derive_directives(_resolver_outputs(novelty="low"))
        attenuated = set(d["weight_modifications"]["attenuate_codes"])
        assert not (set(TIER10_CODES) & attenuated)
        assert not (set(TIER15_CODES) & attenuated)
        assert "topic_novelty_high" not in d["flags"]


# ══════════════════════════════════════════════════════════════════════════════
# Language
# ══════════════════════════════════════════════════════════════════════════════

class TestLanguage:
    def test_code_switched_flag(self):
        d = _derive_directives(_resolver_outputs(code_switched=True))
        assert "code_switched" in d["flags"]

    def test_monolingual_no_flag(self):
        d = _derive_directives(_resolver_outputs(code_switched=False))
        assert "code_switched" not in d["flags"]


# ══════════════════════════════════════════════════════════════════════════════
# Default invariants
# ══════════════════════════════════════════════════════════════════════════════

class TestDefaults:
    def test_default_anchors_always_t4_t6(self):
        # Every combination — even one with maximum muting — must keep T4, T6.
        for regime in ("micro", "short", "standard", "long"):
            for genre in ("scholarly_essay", "blog_post", "creative_fiction"):
                d = _derive_directives(_resolver_outputs(
                    length_regime=regime, genre=genre,
                ))
                assert 4 in d["anchor_tiers"], f"{regime}/{genre} dropped T4"
                assert 6 in d["anchor_tiers"], f"{regime}/{genre} dropped T6"

    def test_mute_overrides_attenuate(self):
        # micro length mutes T11 (via tier expansion); tool_cleaned would also
        # attenuate T11. The precedence rule in _derive_directives says mute
        # wins — T11 codes appear ONLY in mute_codes, not attenuate_codes.
        d = _derive_directives(_resolver_outputs(
            length_regime="micro", composition_mode="tool_cleaned"
        ))
        muted = set(d["weight_modifications"]["mute_codes"])
        attenuated = set(d["weight_modifications"]["attenuate_codes"])
        # T11 codes muted by length, NOT in attenuated even though tool_cleaned
        # would normally attenuate them.
        assert set(TIER11_CODES).issubset(muted)
        assert not (set(TIER11_CODES) & attenuated)


# ══════════════════════════════════════════════════════════════════════════════
# Round-trip serialisation
# ══════════════════════════════════════════════════════════════════════════════

class TestRoundTrip:
    def test_to_dict_round_trip(self):
        outputs = _resolver_outputs(
            length_regime="standard",
            genre="academic_exegesis",
            citations_present=True,
            composition_mode="tool_cleaned",
            code_switched=True,
            novelty="high",
        )
        m = build_manifest("test_xyz", outputs)
        d = m.to_dict()
        m2 = ContextManifest.from_dict(d)
        # All scalar fields preserved.
        assert m2.submission_id == "test_xyz"
        assert m2.length_regime == "standard"
        # All directive lists preserved.
        assert m2.flags == m.flags
        assert m2.anchor_tiers == m.anchor_tiers
        assert m2.weight_modifications == m.weight_modifications
        # JSON serialisation round-trip.
        import json
        d2 = json.loads(m.to_json())
        assert d2 == d

    def test_from_dict_tolerates_unknown_keys(self):
        # Forward-compat: a manifest written by a future version with extra
        # fields should still deserialise (extras dropped).
        outputs = _resolver_outputs()
        m = build_manifest("forward_compat", outputs)
        d = m.to_dict()
        d["future_field"] = {"some": "extra"}
        m2 = ContextManifest.from_dict(d)
        assert m2.submission_id == "forward_compat"

    def test_build_manifest_with_resolver_errors(self):
        # When resolvers fail and `_errors` is in the dict, build_manifest
        # must still produce a valid manifest (defaults applied).
        partial_outputs = {
            "language":  {"primary": "en", "code_switched": False},
            "_errors":   [{"resolver": "genre", "exc": "ValueError: boom"}],
        }
        m = build_manifest("partial", partial_outputs)
        assert m.submission_id == "partial"
        assert m.length_regime == "unknown"
        assert m.anchor_tiers == [4, 6]    # defaults still present
        assert m.created_at != ""


# ══════════════════════════════════════════════════════════════════════════════
# Pydantic schema interop
# ══════════════════════════════════════════════════════════════════════════════

class TestPydanticInterop:
    def test_manifest_to_dict_matches_pydantic_model(self):
        from original.schemas import ContextManifestOut

        outputs = _resolver_outputs()
        m = build_manifest("pyd_test", outputs)
        # Pydantic model should accept the dict verbatim.
        pyd = ContextManifestOut(**m.to_dict())
        assert pyd.submission_id == "pyd_test"
        assert pyd.length_regime == "standard"
        assert pyd.flags == m.flags
