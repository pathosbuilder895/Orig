import pytest

from validation.verify.pan_stack import combine_trials, trial_id
from validation.verify.pan_style_expert import TrialScores


def test_trial_id_includes_probe_identity():
    assert trial_id("target", "source", 2) == "target|source|probe-2"


def test_combine_trials_rejects_misalignment():
    style = [TrialScores("target", "source", 0, 0.4, -0.2)]
    with pytest.raises(ValueError, match="trial alignment failure"):
        combine_trials(style, {})


def test_combine_trials_preserves_claim_label_and_signals():
    style = [TrialScores("author", "author", 1, 0.4, -0.2)]
    identifier = trial_id("author", "author", 1)
    rows = combine_trials(style, {identifier: {"raw_probability": 0.6, "peer_probability": 0.7}})
    assert len(rows) == 1
    assert rows[0].label == 1
    assert rows[0].author_id == "author"
    assert rows[0].signals["content_reduced_similarity"] == -0.2
