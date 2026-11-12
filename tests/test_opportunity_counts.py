"""Opportunity counts: how many chances a text gave a measurement to occur.

A share such as ``that_which_ratio`` is "that" uses over ("that" + "which")
uses. When a text has neither, the extractor returns a placeholder (0.5 or
0.0) that is not a measurement. ``original/features/opportunity.py`` reports
the denominator for each such measurement so the scorer can tell "balanced"
from "nothing to measure".
"""

from __future__ import annotations

import numpy as np
import pytest

from original.constants import ALL_FEATURE_CODES, FEATURE_DIM
from original.features.baseline_scope import NOT_COMPUTED_FOR_BASELINES
from original.features.opportunity import (
    OPPORTUNITY_FEATURES,
    opportunity_counts,
    unmeasured_mask,
)
from original.features.pipeline import _normalise, extract_features

_IDX = {code: i for i, code in enumerate(ALL_FEATURE_CODES)}

NO_RELATIVES = (
    "The harvest came late. Rain fell for nine days. Farmers waited in barns. "
    "Wheat rotted in fields. Prices rose in town. Bakers closed early."
)
WITH_WHICH = (
    "The harvest which came late ruined the farmers. The barn which stood "
    "on the hill burned. Rain fell for nine days."
)


def test_registry_codes_are_real_and_compared():
    for code in OPPORTUNITY_FEATURES:
        assert code in _IDX
        assert code not in NOT_COMPUTED_FOR_BASELINES


def test_counts_cover_every_registered_feature():
    counts = opportunity_counts(WITH_WHICH)
    assert set(counts) == set(OPPORTUNITY_FEATURES)
    assert all(isinstance(v, int) and v >= 0 for v in counts.values())


def test_zero_opportunities_is_unmeasured():
    counts = opportunity_counts(NO_RELATIVES)
    assert counts["that_which_ratio"] == 0
    mask = unmeasured_mask(NO_RELATIVES)
    assert mask.shape == (FEATURE_DIM,)
    assert mask.dtype == bool
    assert mask[_IDX["that_which_ratio"]]


def test_present_opportunities_are_measured():
    counts = opportunity_counts(WITH_WHICH)
    assert counts["that_which_ratio"] == 2
    assert not unmeasured_mask(WITH_WHICH)[_IDX["that_which_ratio"]]


def test_min_count_raises_the_bar():
    assert not unmeasured_mask(WITH_WHICH, min_count=2)[_IDX["that_which_ratio"]]
    assert unmeasured_mask(WITH_WHICH, min_count=3)[_IDX["that_which_ratio"]]


def test_min_count_below_one_is_rejected():
    with pytest.raises(ValueError):
        unmeasured_mask(WITH_WHICH, min_count=0)


def test_unregistered_features_are_never_marked():
    mask = unmeasured_mask("")
    registered = np.zeros(FEATURE_DIM, dtype=bool)
    for code in OPPORTUNITY_FEATURES:
        registered[_IDX[code]] = True
    assert not mask[~registered].any()
    # An empty text gives no measurement any chance to occur.
    assert mask[registered].all()


def test_source_loyalty_keeps_its_own_three_citation_floor():
    # The extractor itself calls fewer than three citations "insufficient
    # data", so one or two citations are still not a measurement.
    text = (
        "Grace is free, as Calvin argues (Calvin 1559). The point stands. "
        "Barth disagrees on the ground of it (Barth 1932). So the matter rests."
    )
    counts = opportunity_counts(text)
    assert counts["source_loyalty_index"] < 3
    assert unmeasured_mask(text)[_IDX["source_loyalty_index"]]


@pytest.mark.parametrize("text", [NO_RELATIVES, WITH_WHICH, ""])
def test_zero_count_coincides_with_the_extractor_placeholder(text):
    """The count and the extractor must agree about 'nothing to measure'."""
    feats = extract_features(text)
    counts = opportunity_counts(text)
    for code, spec in OPPORTUNITY_FEATURES.items():
        if counts[code] == 0:
            assert feats[code] == pytest.approx(_normalise(spec.placeholder, code)), code


def test_marker_ratios_share_one_count():
    counts = opportunity_counts("However, the plan failed. Therefore we left, and then slept.")
    shared = {
        counts[c] for c in ("additive_ratio", "adversative_ratio", "causal_ratio", "temporal_ratio")
    }
    assert len(shared) == 1
    assert shared.pop() >= 2
