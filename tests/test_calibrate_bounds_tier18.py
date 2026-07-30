"""tests/test_calibrate_bounds_tier18.py — Tier 18 uniformity features wired
into scripts/calibrate_bounds.py raw extraction (Task 12, two-axis plan).

The calibration script must produce raw (un-normalised) values for the six
Tier 18 codes so a future --suggest-bounds run can propose NORM_BOUNDS for
them. Raw extractors are pure — no clipping — so values need only be finite,
not confined to [0, 1].
"""

from __future__ import annotations

import math


# Varied sentence lengths, punctuation, and vocabulary so every Tier 18
# extractor has enough signal to return a genuine (non-fallback) value.
_SYNTHETIC_DOC = (
    "The seminar met on Tuesday. Professor Alvarez, who had spent thirty "
    "years studying patristic manuscripts, opened with a long meditation on "
    "the transmission of texts across monastic scriptoria. Short questions "
    "followed. Some students pressed hard on the dating of the earliest "
    "fragments; others wondered aloud whether the scribe's hand could be "
    "identified at all. Nobody agreed. The debate, lively and occasionally "
    "sharp, ran well past the scheduled hour. A few notes were taken. "
    "Afterward, three of us walked to the library and pulled the facsimile "
    "editions from the reserve shelf, comparing letterforms until the lights "
    "dimmed. It was slow work. We argued about serifs, about ligatures, "
    "about the weight of a downstroke, and about what any of it could prove. "
    "The evening ended without a verdict, though everyone promised to return "
    "with better evidence next week."
)


class TestCalibrateBoundsTier18:
    def test_extract_raw_includes_finite_tier18_values(self):
        from original.constants import TIER18_CODES
        from scripts.calibrate_bounds import extract_raw

        raw = extract_raw(_SYNTHETIC_DOC)
        for code in TIER18_CODES:
            assert code in raw, f"{code} missing from extract_raw output"
            assert isinstance(raw[code], float), f"{code} is not a float"
            assert math.isfinite(raw[code]), f"{code} is not finite: {raw[code]}"
        # Genuine extraction, not a wall of 0.5 fallback/placeholder values.
        assert any(raw[code] != 0.5 for code in TIER18_CODES)

    def test_tier_labels_includes_18(self):
        from scripts.calibrate_bounds import _TIER_LABELS

        assert 18 in _TIER_LABELS
