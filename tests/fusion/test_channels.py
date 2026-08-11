"""Pure-function tests for the three fusion channels.

Each channel maps (baseline, probe) -> float where LARGER means MORE
different. These tests pin the direction, the identity property, and
determinism; the absolute values are pinned only where they are exactly
derivable, so a refactor that changes calibration fails loudly.
"""

from __future__ import annotations

import numpy as np
import pytest

from original.constants import FEATURE_DIM
from original.fusion.channels import (
    CHANNEL_NAMES,
    compressed_size,
    compression_distance,
    diagonal_z_distance,
    function_word_distance,
    function_word_matrix,
)

_PROSE_A = (
    "However, a reader might ask why these claims have been made; therefore we reply "
    "that the argument is careful, and that it is also sound. "
) * 40

_PROSE_B = (
    "The cat sat. Rain fell. Dogs ran fast! Birds sing loud songs. "
    "Short bursts everywhere. No subordination here. "
) * 40


def test_channel_names_are_the_documented_three():
    assert CHANNEL_NAMES == ("peer_centered_z", "compression", "function_word_network")


def test_diagonal_z_is_zero_when_probe_equals_baseline_mean():
    mean = np.full(FEATURE_DIM, 0.5)
    std = np.full(FEATURE_DIM, 0.1)
    assert diagonal_z_distance(mean.copy(), mean, std) == pytest.approx(0.0)


def test_diagonal_z_matches_the_production_tanh_formula():
    # Every feature exactly 2 sigma away -> rms_z == 2.0 -> tanh(2/1.5).
    mean = np.full(FEATURE_DIM, 0.5)
    std = np.full(FEATURE_DIM, 0.1)
    probe = mean + 2.0 * std
    assert diagonal_z_distance(probe, mean, std) == pytest.approx(np.tanh(2.0 / 1.5))


def test_diagonal_z_winsorizes_at_four_sigma():
    mean = np.full(FEATURE_DIM, 0.5)
    std = np.full(FEATURE_DIM, 0.1)
    at_cap = diagonal_z_distance(mean + 4.0 * std, mean, std)
    way_past = diagonal_z_distance(mean + 400.0 * std, mean, std)
    assert at_cap == pytest.approx(way_past)


def test_diagonal_z_floors_degenerate_sigma():
    mean = np.full(FEATURE_DIM, 0.5)
    std = np.zeros(FEATURE_DIM)
    value = diagonal_z_distance(np.full(FEATURE_DIM, 0.6), mean, std)
    assert np.isfinite(value)
    assert 0.0 <= value <= 1.0


def test_compression_distance_is_smaller_for_same_style():
    same = compression_distance(_PROSE_A, _PROSE_A[:600])
    different = compression_distance(_PROSE_A, _PROSE_B[:600])
    assert same < different


def test_compression_distance_accepts_precomputed_baseline_size():
    size = compressed_size(_PROSE_A.encode("utf-8"))
    with_cache = compression_distance(_PROSE_A, _PROSE_B[:600], baseline_size=size)
    without = compression_distance(_PROSE_A, _PROSE_B[:600])
    assert with_cache == pytest.approx(without)


def test_compression_distance_handles_empty_probe():
    assert compression_distance(_PROSE_A, "") == pytest.approx(1.0)


def test_function_word_matrix_is_unit_norm():
    matrix = function_word_matrix(_PROSE_A)
    assert float(np.linalg.norm(matrix)) == pytest.approx(1.0)


def test_function_word_distance_is_zero_against_itself():
    matrix = function_word_matrix(_PROSE_A)
    assert function_word_distance(matrix, matrix) == pytest.approx(0.0, abs=1e-9)


def test_function_word_distance_separates_styles():
    a = function_word_matrix(_PROSE_A)
    b = function_word_matrix(_PROSE_B)
    assert function_word_distance(a, b) > function_word_distance(a, a)


def test_function_word_matrix_handles_empty_text():
    matrix = function_word_matrix("")
    assert np.all(np.isfinite(matrix))
    assert float(np.linalg.norm(matrix)) == pytest.approx(1.0)


def test_all_channels_are_deterministic():
    mean = np.full(FEATURE_DIM, 0.5)
    std = np.full(FEATURE_DIM, 0.1)
    probe = np.linspace(0.2, 0.8, FEATURE_DIM)
    assert diagonal_z_distance(probe, mean, std) == diagonal_z_distance(probe, mean, std)
    assert compression_distance(_PROSE_A, _PROSE_B[:600]) == compression_distance(
        _PROSE_A, _PROSE_B[:600]
    )
    first = function_word_matrix(_PROSE_A)
    second = function_word_matrix(_PROSE_A)
    assert np.array_equal(first, second)
