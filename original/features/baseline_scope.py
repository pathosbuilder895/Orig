"""Which measurements a past paper has no value for, by how its vector is made.

Every stored past-paper vector is made by ``features.pipeline.extract_features``
(``feature_vector``): the baseline upload, imports, admin seeding and the
stores' own rebuilds all call it. That function computes no comparison
measurement. A comparison measurement compares one text with a set of past
papers, so ``extract_features`` writes a fixed placeholder for each of them,
and only ``compute_full_features`` fills one in, for the paper being scored,
against its past papers.

So for these codes the scored paper has a real number and every past paper
has the placeholder. Comparing the two would treat the placeholder as if it
were a past paper's own value. Scoring therefore leaves these codes out of
the comparison (``quantum.state.StudentState.active_feature_mask``,
``quantum.scoring.score``), and the evidence pages say "not compared: past
papers have no value for this" (ADR-013, "Comparison measurements").

This list is the computing path's own record, not a guess from the values:
``extract_features`` writes its placeholders from it. If past papers ever get
real values for one of these codes (for example a leave-one-out comparison
among the past papers themselves), that code leaves this list in the same
change.
"""

from __future__ import annotations

import numpy as np

from ..constants import ALL_FEATURE_CODES, COMPARISON_CODES, MUSICAL_COMPARISON_CODES

#: Codes ``extract_features`` never computes (in the order it writes them).
NOT_COMPUTED_FOR_BASELINES: tuple[str, ...] = tuple(MUSICAL_COMPARISON_CODES) + tuple(
    COMPARISON_CODES
)

#: The same codes as a boolean mask over ``ALL_FEATURE_CODES``.
NOT_COMPUTED_FOR_BASELINES_MASK: np.ndarray = np.array(
    [code in NOT_COMPUTED_FOR_BASELINES for code in ALL_FEATURE_CODES], dtype=bool
)
NOT_COMPUTED_FOR_BASELINES_MASK.setflags(write=False)

#: What the pages say about one of them.
NOT_COMPARED_WORDS = "not compared: past papers have no value for this"
