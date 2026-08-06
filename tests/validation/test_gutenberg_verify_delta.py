"""validation/verify/gutenberg_verify_delta.py -- matched-pair trial
construction. No LUAR/corpus dependency: exercises _matched_trials and
_build_trials directly with synthetic data."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from validation.verify.gutenberg_verify_delta import _build_trials, _matched_trials


@dataclass(frozen=True)
class _Author:
    author_id: str


def test_matched_trials_pairs_every_probe_with_itself_and_one_offset_author():
    authors = [_Author(f"a{i}") for i in range(4)]
    # matrix[row, author_index] = (luar, char, content); row = source_author*3 + probe_index
    matrix = np.zeros((12, 4, 3))
    for row in range(12):
        for author_index in range(4):
            matrix[row, author_index] = (row, author_index, row * 10 + author_index)

    genuine, impostor = _matched_trials(authors, matrix, offset=1)

    assert len(genuine) == 12
    assert len(impostor) == 12
    for row, (target_id, source_id, probe_index, values) in enumerate(genuine):
        source_idx = row // 3
        assert target_id == source_id == f"a{source_idx}"
        assert probe_index == row % 3
        np.testing.assert_array_equal(values, matrix[row, source_idx])

    for row, (target_id, source_id, probe_index, values) in enumerate(impostor):
        source_idx = row // 3
        impostor_idx = (source_idx + 1) % 4
        assert target_id == f"a{impostor_idx}"
        assert source_id == f"a{source_idx}"
        assert target_id != source_id
        np.testing.assert_array_equal(values, matrix[row, impostor_idx])


def test_build_trials_labels_and_signal_completeness():
    from validation.verify.pan_stack import trial_id

    authors = [_Author(f"a{i}") for i in range(3)]
    matrix = np.arange(9 * 3 * 3, dtype=float).reshape(9, 3, 3)

    delta_rows = {}
    for row in range(9):
        source_idx, probe_index = row // 3, row % 3
        for target_idx in range(3):
            identifier = trial_id(f"a{target_idx}", f"a{source_idx}", probe_index)
            delta_rows[identifier] = {"delta_neg_distance": -float(row), "delta_peer_z": float(target_idx)}

    trials = _build_trials(authors, matrix, delta_rows)
    assert len(trials) == 18  # 9 genuine + 9 impostor

    genuine = [t for t in trials if t.label == 1]
    impostor = [t for t in trials if t.label == 0]
    assert len(genuine) == 9 and len(impostor) == 9
    for t in trials:
        assert set(t.signals) == {
            "luar_cosine",
            "character_similarity",
            "content_reduced_similarity",
            "delta_neg_distance",
            "delta_peer_z",
        }
    # No trial_id collisions between genuine and impostor sets.
    assert len({t.trial_id for t in trials}) == 18
