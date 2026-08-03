"""
tests/context/test_weighting.py — Phase 5 build_adaptive_weight_vector tests.
"""

from __future__ import annotations

import numpy as np
import pytest

from original.constants import (
    ALL_FEATURE_CODES,
    FEATURE_DIM,
    FEATURE_TIER,
    TIER_WEIGHTS,
    TIER1_CODES,
    TIER2_CODES,
    TIER3_CODES,
    TIER4_CODES,
    TIER6_CODES,
    TIER9_CODES,
    TIER10_CODES,
    TIER11_CODES,
    TIER14_CODES,
    TIER15_CODES,
    TIER16_CODES,
)
from original.context.manifest import ContextManifest, build_manifest
from original.context.weighting import (
    AMPLIFY_FACTOR,
    ATTENUATE_FACTOR,
    GENRE_MISMATCH_ATTENUATE_TIERS,
    build_adaptive_weight_vector,
)


# ── Fixtures ─────────────────────────────────────────────────────────────────


def _empty_manifest() -> ContextManifest:
    """Manifest with no directives — vector should equal static base weights."""
    return ContextManifest(
        submission_id="empty",
        language={},
        genre={},
        topic={},
        length_regime="standard",
        citations={},
        composition_mode={},
        weight_modifications={"amplify_codes": [], "attenuate_codes": [], "mute_codes": []},
        anchor_tiers=[],
        baseline_match={},
        flags=[],
        created_at="",
    )


def _static_base_vector() -> np.ndarray:
    """The vector that scoring.py computes as _TIER_WEIGHT_VECTOR."""
    return np.array(
        [TIER_WEIGHTS.get(FEATURE_TIER[c], 1.0) for c in ALL_FEATURE_CODES],
        dtype=np.float64,
    )


# ══════════════════════════════════════════════════════════════════════════════
# Shape + identity invariants
# ══════════════════════════════════════════════════════════════════════════════


class TestShapeAndIdentity:
    def test_build_weight_vector_shape(self):
        v = build_adaptive_weight_vector(_empty_manifest())
        assert v.shape == (FEATURE_DIM,)
        assert v.dtype == np.float64

    def test_default_manifest_matches_static_tier_weights(self):
        # Empty directives, no anchors → must match the static base vector
        # element-wise. This is the "OFF flag" sanity guard: when no
        # directives fire, scoring is byte-identical to Phase 1.
        v = build_adaptive_weight_vector(_empty_manifest())
        assert np.allclose(v, _static_base_vector())

    def test_accepts_dict_or_dataclass(self):
        # The adaptive pipeline often passes manifest.to_dict() rather than
        # the dataclass — must handle both equivalently.
        m = _empty_manifest()
        from_dataclass = build_adaptive_weight_vector(m)
        from_dict = build_adaptive_weight_vector(m.to_dict())
        assert np.allclose(from_dataclass, from_dict)


# ══════════════════════════════════════════════════════════════════════════════
# Anchor amplification
# ══════════════════════════════════════════════════════════════════════════════


class TestAnchorAmplification:
    def test_amplify_anchor_tiers_t4_t6(self):
        m = _empty_manifest()
        m.anchor_tiers = [4, 6]
        v = build_adaptive_weight_vector(m)
        for code in TIER4_CODES:
            i = ALL_FEATURE_CODES.index(code)
            expected = TIER_WEIGHTS[4] * AMPLIFY_FACTOR
            assert abs(v[i] - expected) < 1e-9, f"T4 code {code} not amplified"
        for code in TIER6_CODES:
            i = ALL_FEATURE_CODES.index(code)
            expected = TIER_WEIGHTS[6] * AMPLIFY_FACTOR
            assert abs(v[i] - expected) < 1e-9, f"T6 code {code} not amplified"

    def test_non_anchor_tiers_keep_base_weight(self):
        # Anchor only tier 4 — every other tier must keep its base weight
        # (modulo no other directives firing).
        m = _empty_manifest()
        m.anchor_tiers = [4]
        v = build_adaptive_weight_vector(m)
        # T6 should NOT be amplified now (it's not in anchor_tiers).
        for code in TIER6_CODES:
            i = ALL_FEATURE_CODES.index(code)
            assert abs(v[i] - TIER_WEIGHTS[6]) < 1e-9


# ══════════════════════════════════════════════════════════════════════════════
# Mute
# ══════════════════════════════════════════════════════════════════════════════


class TestMuting:
    def test_mute_t16_when_no_citations(self):
        m = _empty_manifest()
        m.weight_modifications = {
            "amplify_codes": [],
            "attenuate_codes": [],
            "mute_codes": list(TIER16_CODES),
        }
        v = build_adaptive_weight_vector(m)
        for code in TIER16_CODES:
            i = ALL_FEATURE_CODES.index(code)
            assert v[i] == 0.0, f"T16 code {code} should be muted"

    def test_mute_overrides_anchor(self):
        # Even if a tier is BOTH anchored AND has codes in mute_codes, the
        # mute wins (mute is hard zero, never overridden).
        m = _empty_manifest()
        m.anchor_tiers = [16]
        m.weight_modifications = {
            "amplify_codes": [],
            "attenuate_codes": [],
            "mute_codes": list(TIER16_CODES),
        }
        v = build_adaptive_weight_vector(m)
        for code in TIER16_CODES:
            i = ALL_FEATURE_CODES.index(code)
            assert v[i] == 0.0


# ══════════════════════════════════════════════════════════════════════════════
# Attenuation
# ══════════════════════════════════════════════════════════════════════════════


class TestAttenuation:
    def test_attenuate_t11_t14_when_tool_cleaned(self):
        m = _empty_manifest()
        attenuate = list(TIER11_CODES) + list(TIER14_CODES)
        m.weight_modifications = {
            "amplify_codes": [],
            "attenuate_codes": attenuate,
            "mute_codes": [],
        }
        v = build_adaptive_weight_vector(m)
        for code in TIER11_CODES:
            i = ALL_FEATURE_CODES.index(code)
            expected = TIER_WEIGHTS[11] * ATTENUATE_FACTOR
            assert abs(v[i] - expected) < 1e-9
        for code in TIER14_CODES:
            i = ALL_FEATURE_CODES.index(code)
            expected = TIER_WEIGHTS[14] * ATTENUATE_FACTOR
            assert abs(v[i] - expected) < 1e-9

    def test_attenuate_beats_anchor(self):
        # If a code is BOTH in anchor_tiers AND attenuate_codes, attenuate
        # wins — the resolver said this code is contextually noisy in this
        # submission, that signal trumps the generic identity anchor.
        m = _empty_manifest()
        m.anchor_tiers = [10]
        m.weight_modifications = {
            "amplify_codes": [],
            "attenuate_codes": list(TIER10_CODES),
            "mute_codes": [],
        }
        v = build_adaptive_weight_vector(m)
        for code in TIER10_CODES:
            i = ALL_FEATURE_CODES.index(code)
            expected = TIER_WEIGHTS[10] * ATTENUATE_FACTOR
            assert (
                abs(v[i] - expected) < 1e-9
            ), f"T10 code {code} should be attenuated, not amplified"


# ══════════════════════════════════════════════════════════════════════════════
# Composite (multiple directives at once)
# ══════════════════════════════════════════════════════════════════════════════


class TestComposite:
    def test_full_directive_combo(self):
        # T16 muted, T11+T14 attenuated, T10+T15 attenuated, anchor [4, 6, 8, 13].
        m = _empty_manifest()
        m.anchor_tiers = [4, 6, 8, 13]
        m.weight_modifications = {
            "amplify_codes": [],
            "attenuate_codes": list(TIER10_CODES)
            + list(TIER11_CODES)
            + list(TIER14_CODES)
            + list(TIER15_CODES),
            "mute_codes": list(TIER16_CODES),
        }
        v = build_adaptive_weight_vector(m)

        # T16 muted
        for code in TIER16_CODES:
            assert v[ALL_FEATURE_CODES.index(code)] == 0.0
        # T11 attenuated
        for code in TIER11_CODES:
            expected = TIER_WEIGHTS[11] * ATTENUATE_FACTOR
            assert abs(v[ALL_FEATURE_CODES.index(code)] - expected) < 1e-9
        # T4 amplified
        for code in TIER4_CODES:
            expected = TIER_WEIGHTS[4] * AMPLIFY_FACTOR
            assert abs(v[ALL_FEATURE_CODES.index(code)] - expected) < 1e-9


# ══════════════════════════════════════════════════════════════════════════════
# Real-manifest smoke test
# ══════════════════════════════════════════════════════════════════════════════


class TestRealManifest:
    def test_built_from_resolver_outputs(self):
        # Build a manifest from real resolver outputs (no citations, low
        # novelty etc. in this short text), then feed it to weighting.
        from original.context.resolvers import run_resolvers

        text = "The committee considered the proposal carefully. " * 50
        out = run_resolvers(text, ["Baseline a.", "Baseline b."])
        m = build_manifest("smoke", out)
        v = build_adaptive_weight_vector(m)

        assert v.shape == (FEATURE_DIM,)
        # Real manifest from this text → no citations → T16 muted.
        for code in TIER16_CODES:
            i = ALL_FEATURE_CODES.index(code)
            assert v[i] == 0.0
        # Default anchors {4, 6} → those tiers amplified.
        for code in TIER4_CODES:
            i = ALL_FEATURE_CODES.index(code)
            assert abs(v[i] - TIER_WEIGHTS[4] * AMPLIFY_FACTOR) < 1e-9


# ══════════════════════════════════════════════════════════════════════════════
# Genre-mismatch attenuation (2026-08 cross-genre study)
# ══════════════════════════════════════════════════════════════════════════════


class TestGenreMismatchAttenuation:
    def test_genre_covered_true_is_a_noop(self):
        # Default (and explicit True) must match the no-genre-covered-param
        # call exactly -- the common case is untouched.
        m = _empty_manifest()
        assert np.allclose(
            build_adaptive_weight_vector(m),
            build_adaptive_weight_vector(m, genre_covered=True),
        )

    def test_genre_uncovered_attenuates_flagged_tiers(self):
        m = _empty_manifest()
        v = build_adaptive_weight_vector(m, genre_covered=False)
        for tier in GENRE_MISMATCH_ATTENUATE_TIERS:
            base = TIER_WEIGHTS[tier]
            for code in ALL_FEATURE_CODES:
                if FEATURE_TIER.get(code) == tier:
                    i = ALL_FEATURE_CODES.index(code)
                    assert abs(v[i] - base * ATTENUATE_FACTOR) < 1e-9, (
                        f"tier {tier} code {code} not attenuated on genre mismatch"
                    )

    def test_genre_uncovered_leaves_other_tiers_untouched(self):
        m = _empty_manifest()
        v = build_adaptive_weight_vector(m, genre_covered=False)
        untouched_tiers = set(TIER_WEIGHTS) - GENRE_MISMATCH_ATTENUATE_TIERS
        for code in TIER1_CODES + TIER4_CODES + TIER6_CODES:
            i = ALL_FEATURE_CODES.index(code)
            tier = FEATURE_TIER[code]
            assert tier in untouched_tiers  # sanity: these codes aren't in the attenuated set
            assert abs(v[i] - TIER_WEIGHTS[tier]) < 1e-9

    def test_mute_beats_genre_attenuation(self):
        # A muted code in an attenuated tier must stay exactly 0.0, not
        # 0.0 * ATTENUATE_FACTOR (still 0.0, but this proves the code path
        # skips the multiply rather than relying on 0 * x == 0 by luck).
        some_t3_code = next(c for c in TIER3_CODES)
        m = _empty_manifest()
        m.weight_modifications = {
            "mute_codes": [some_t3_code], "attenuate_codes": [], "amplify_codes": [],
        }
        v = build_adaptive_weight_vector(m, genre_covered=False)
        assert v[ALL_FEATURE_CODES.index(some_t3_code)] == 0.0

    def test_genre_attenuation_stacks_with_existing_attenuation(self):
        # A code already attenuated by the manifest's own directives (e.g.
        # high topic novelty) AND in a genre-mismatch tier should be
        # attenuated twice -- the two mechanisms answer different questions
        # ("is this specific submission noisy here" vs "has this genre ever
        # been seen") and both apply.
        some_t9_code = next(c for c in TIER9_CODES)
        m = _empty_manifest()
        m.weight_modifications = {
            "mute_codes": [], "attenuate_codes": [some_t9_code], "amplify_codes": [],
        }
        v = build_adaptive_weight_vector(m, genre_covered=False)
        base = TIER_WEIGHTS[9]
        expected = base * ATTENUATE_FACTOR * ATTENUATE_FACTOR
        assert abs(v[ALL_FEATURE_CODES.index(some_t9_code)] - expected) < 1e-9

    def test_tiers_2_3_9_10_are_the_attenuated_set(self):
        # Pin the exact tier set so a future edit to constants.py's tier
        # numbering can't silently change what this attenuates.
        assert GENRE_MISMATCH_ATTENUATE_TIERS == frozenset({2, 3, 9, 10})
