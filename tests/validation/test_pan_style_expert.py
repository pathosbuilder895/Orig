import json
from pathlib import Path

import numpy as np
import pytest

from validation.verify.pan_style_expert import (
    TrialScores,
    alternative_aware_signals,
    alternative_margin_signals,
    content_masked_sequence,
    StyleAuthor,
    _threshold_at_constraints,
    _threshold_at_fpr,
    assert_partition_integrity,
    content_reduced_signature,
    load_author_partitions,
    matched_verification_trials,
    function_sequence_signals,
    function_margin_signals,
    style_margin_only_signals,
    peer_aligned_signals,
)
from tests.validation.test_pan_verify_corpus import _fixture


def test_author_partitions_are_disjoint_and_cross_topic(tmp_path):
    cache = _fixture(tmp_path)
    partitions = load_author_partitions(
        cache_dir=cache,
        n_locked=1,
        n_development=1,
        n_calibration=1,
        min_text_chars=20,
    )
    ids = [{author.author_id for author in rows} for rows in partitions.values()]
    assert not (ids[0] & ids[1] or ids[0] & ids[2] or ids[1] & ids[2])
    assert all(
        author.baseline_fandom != author.probe_fandom
        for rows in partitions.values()
        for author in rows
    )


def test_fresh_lock_is_taken_after_prior_lock_development_and_calibration(tmp_path):
    cache = _fixture(tmp_path)
    # The tiny fixture has only three eligible authors: reserve the first,
    # develop on the second, and lock the third.
    partitions = load_author_partitions(
        cache_dir=cache,
        prior_locked_authors=1,
        n_development=1,
        n_calibration=0,
        n_locked=1,
        min_text_chars=20,
    )
    assert len(partitions["development"]) == 1
    assert len(partitions["calibration"]) == 0
    assert len(partitions["locked"]) == 1
    assert partitions["development"][0].author_id != partitions["locked"][0].author_id


def test_partition_can_require_three_baselines_but_only_one_probe(tmp_path):
    cache = _fixture(tmp_path)
    partitions = load_author_partitions(
        cache_dir=cache,
        n_locked=1,
        n_development=0,
        n_calibration=0,
        samples=3,
        probe_samples=1,
        min_text_chars=20,
    )
    author = partitions["locked"][0]
    assert len(author.baselines) == 3
    assert len(author.probes) == 1


def test_partition_integrity_rejects_author_leakage():
    author = StyleAuthor("a", "one", "two", ("baseline",), ("probe",))
    with pytest.raises(ValueError, match="author leakage"):
        assert_partition_integrity({"development": [author], "locked": [author]})


def test_content_reduced_signature_is_finite_and_fixed_width():
    first = content_reduced_signature("This is a sentence, and it is short. But this is another!")
    second = content_reduced_signature("Those were examples; they were deliberately different words.")
    assert first.shape == second.shape
    assert first.size > 100
    assert np.isfinite(first).all()


def test_threshold_is_selected_from_negative_scores_only():
    labels = np.array([1, 1, 0, 0, 0, 0], dtype=np.int8)
    scores = np.array([0.2, 0.9, 0.1, 0.3, 0.4, 0.8])
    threshold = _threshold_at_fpr(labels, scores, 0.25)
    assert threshold > 0.8


def test_operating_threshold_jointly_enforces_precision_and_fpr():
    labels = np.asarray([1] * 20 + [0] * 200)
    scores = np.asarray([0.9] * 12 + [0.4] * 8 + [0.85] + [0.1] * 199)
    threshold = _threshold_at_constraints(labels, scores, min_true_positives=10)
    selected = scores >= threshold
    assert labels[selected].mean() >= 0.90
    assert selected[labels == 0].mean() <= 0.01


def test_peer_alignment_uses_other_targets_without_labels():
    from validation.verify.pan_style_expert import TrialScores

    trials = [
        TrialScores(f"target-{i}", "source", 0, float(i), float(i * 2)) for i in range(4)
    ]
    matrix = peer_aligned_signals(trials)
    assert matrix.shape == (4, 4)
    assert np.allclose(matrix[:, :2], [[i, i * 2] for i in range(4)])
    assert matrix[0, 2] < 0 < matrix[-1, 2]


def test_alternative_aware_signals_reward_the_best_enrolled_match():
    trials = [
        TrialScores("a", "source", 0, 0.9, -0.1),
        TrialScores("b", "source", 0, 0.5, -0.4),
        TrialScores("c", "source", 0, 0.2, -0.8),
    ]
    signals = alternative_aware_signals(trials)
    assert signals.shape == (3, 8)
    assert signals[0, 4] > 0
    assert signals[1, 4] < 0
    assert signals[0, 6] == 1.0
    np.testing.assert_allclose(alternative_margin_signals(trials), signals[:, :6])
    np.testing.assert_allclose(style_margin_only_signals(trials), signals[:, 4:6])


def test_matched_verification_has_one_impostor_per_genuine():
    trials = []
    for source in ("a", "b", "c"):
        for target in ("a", "b", "c"):
            for probe in (0, 1):
                trials.append(TrialScores(target, source, probe, 0.1, -0.1))
    matched = matched_verification_trials(trials)
    labels = np.asarray([trial.label for trial in matched])
    assert len(matched) == 12
    assert labels.sum() == 6
    assert len(labels) - labels.sum() == 6


def test_content_masking_removes_topics_but_retains_function_words_and_shapes():
    masked = content_masked_sequence("The elephants rapidly crossed a bridge.")
    assert "elephants" not in masked
    assert "bridge" not in masked
    assert "the" in masked
    assert "W9" in masked


def test_function_sequence_signals_include_peer_relative_margins():
    trials = [
        TrialScores("a", "source", 0, 0.9, -0.1, 0.8),
        TrialScores("b", "source", 0, 0.5, -0.4, 0.4),
        TrialScores("c", "source", 0, 0.2, -0.8, 0.1),
    ]
    signals = function_sequence_signals(trials)
    assert signals.shape == (3, 9)
    assert signals[0, 8] > 0
    np.testing.assert_allclose(function_margin_signals(trials), signals[:, 6:9])
