"""
features/opportunity.py, how many chances a text gave a measurement to occur.

Some measurements are shares: "that" uses over ("that" + "which") uses,
first-person pronouns over all personal pronouns. When a text has no eligible
place at all, the extractor has nothing to divide and returns a placeholder
(0.5 for most, 0.0 for some). That placeholder is not a measurement, and 0.5
is also a real value ("balanced"), so the number alone cannot say which it is.

This module reports the denominator. ``score()`` uses it, under
``OPPORTUNITY_MASK`` (off by default), to leave a measurement out of the
comparison for a paper that gave it no chance to occur, instead of comparing
the placeholder with the student's real past values.

Each count comes from the same helper the extractor itself divides by, so the
two cannot drift apart. Only the paper being scored is covered: past-paper
vectors are stored without their counts, so a placeholder inside a student's
history still enters that student's mean and spread (a known limit, recorded
in docs/research/2026-11-10-opportunity-mask.md).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import numpy as np

from ..constants import ALL_FEATURE_CODES, FEATURE_DIM
from .preprocess import CitationData, preprocess
from .prosodic import _polysyndeton_counts, _pronoun_ambiguity_counts
from .tier1 import TextDoc
from .tier2 import _find_discourse_markers
from .tier3 import _epistemic_counts, _personal_pronoun_count
from .tier6 import _abbreviation_counts, _that_which_counts


@dataclass(frozen=True)
class OpportunityFeature:
    """One share-type measurement and the count it is a share of.

    count       : (prose doc, citation data) -> number of opportunities.
    placeholder : the raw value the extractor returns with no opportunities.
    floor       : the fewest opportunities the extractor itself treats as a
                  measurement (3 for source_loyalty_index, 1 otherwise).
    """

    count: Callable[[TextDoc, CitationData], int]
    placeholder: float
    floor: int = 1


def _marker_count(doc: TextDoc, _cd: CitationData) -> int:
    return len(_find_discourse_markers(doc.clean))


OPPORTUNITY_FEATURES: dict[str, OpportunityFeature] = {
    # Choices between two forms.
    "that_which_ratio": OpportunityFeature(lambda d, _c: sum(_that_which_counts(d)), 0.5),
    "epistemic_certainty_ratio": OpportunityFeature(lambda d, _c: sum(_epistemic_counts(d)), 0.5),
    "abbreviation_tendency": OpportunityFeature(lambda d, _c: sum(_abbreviation_counts(d)), 0.5),
    "polysyndeton_ratio": OpportunityFeature(lambda d, _c: sum(_polysyndeton_counts(d)), 0.5),
    # Shares of a category.
    "additive_ratio": OpportunityFeature(_marker_count, 0.0),
    "adversative_ratio": OpportunityFeature(_marker_count, 0.0),
    "causal_ratio": OpportunityFeature(_marker_count, 0.0),
    "temporal_ratio": OpportunityFeature(_marker_count, 0.0),
    "first_person_ratio": OpportunityFeature(lambda d, _c: _personal_pronoun_count(d), 0.0),
    "pronoun_ambiguity_rate": OpportunityFeature(
        lambda d, _c: _pronoun_ambiguity_counts(d)[1], 0.5
    ),
    # Habits of citing, which need citations to exist.
    "signal_verb_assertiveness": OpportunityFeature(
        lambda _d, c: len(c.signal_verb_assertiveness_scores), 0.5
    ),
    "source_loyalty_index": OpportunityFeature(lambda _d, c: len(c.cited_authors), 0.5, floor=3),
    "ibid_usage_rate": OpportunityFeature(
        lambda _d, c: c.paren_citation_count + c.footnote_marker_count, 0.0
    ),
    "citation_position_pref": OpportunityFeature(lambda _d, c: len(c.citation_positions), 0.5),
}

_INDEX = {code: i for i, code in enumerate(ALL_FEATURE_CODES)}


def opportunity_counts(text: str) -> dict[str, int]:
    """{feature code: opportunities in this text} for every registered feature."""
    prose, citation_data = preprocess(text)
    doc = TextDoc(prose)
    return {
        code: int(spec.count(doc, citation_data)) for code, spec in OPPORTUNITY_FEATURES.items()
    }


def mask_from_counts(counts: dict[str, int], min_count: int = 1) -> np.ndarray:
    """Boolean vector, True where a registered feature was not measured.

    A feature is not measured when its count is below ``min_count`` or below
    the extractor's own floor, whichever is higher. ``min_count=1`` (the
    default) marks only the zero-opportunity case, which is the fault repair.
    Higher values are a research setting, not a default: see the research
    note for why a threshold must not be tuned on the data it is reported on.
    """
    if min_count < 1:
        raise ValueError("min_count must be at least 1")
    mask = np.zeros(FEATURE_DIM, dtype=bool)
    for code, spec in OPPORTUNITY_FEATURES.items():
        if counts[code] < max(min_count, spec.floor):
            mask[_INDEX[code]] = True
    return mask


def unmeasured_mask(text: str, min_count: int = 1) -> np.ndarray:
    """Convenience: ``mask_from_counts(opportunity_counts(text), min_count)``."""
    return mask_from_counts(opportunity_counts(text), min_count)
