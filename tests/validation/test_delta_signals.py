"""validation/verify/delta_signals.py -- MFW-Delta as a pan_stack fusion
signal. No corpus dependency: synthetic StyleAuthor-shaped fixtures only."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from validation.verify.delta_signals import build_delta_profiles, delta_trial_signals


@dataclass(frozen=True)
class _Author:
    author_id: str
    baselines: tuple
    probes: tuple


def _author(author_id: str, vocab_bias: str, n_baselines=3, n_probes=2) -> _Author:
    # Each author repeats a distinctive word alongside shared filler, so a
    # real MFW-Delta signal should recover which author a probe came from.
    filler = "the and of to in a is that it was for on with as ".split() * 4
    baselines = tuple(
        " ".join(filler + [vocab_bias] * 20) for _ in range(n_baselines)
    )
    probes = tuple(
        " ".join(filler + [vocab_bias] * 20) for _ in range(n_probes)
    )
    return _Author(author_id, baselines, probes)


def test_build_delta_profiles_needs_at_least_two_authors():
    with pytest.raises(ValueError):
        build_delta_profiles([_author("solo", "alpha")], top_n=50)


def test_delta_profiles_rank_the_true_author_closest():
    authors = [_author("alpha", "alphaword"), _author("beta", "betaword"), _author("gamma", "gammaword")]
    profiles = build_delta_profiles(authors, top_n=50)
    for author in authors:
        for probe in author.probes:
            distances = profiles.distances(probe)
            assert min(distances, key=distances.get) == author.author_id, (
                f"probe from {author.author_id} should be closest to its own profile, "
                f"got distances={distances}"
            )


def test_delta_trial_signals_covers_every_combine_trials_identifier():
    """delta_trial_signals must key every trial the same way
    pan_stack.trial_id / combine_trials expect, or pan_stack_delta's merge
    step raises "delta signal missing for trials"."""
    from validation.verify.pan_stack import trial_id

    authors = [_author("alpha", "alphaword"), _author("beta", "betaword")]
    partitions = {"locked": authors}
    signals = delta_trial_signals(partitions, top_n=50)["locked"]

    expected_ids = {
        trial_id(target.author_id, source.author_id, probe_index)
        for target in authors
        for source in authors
        for probe_index in range(len(source.probes))
    }
    assert set(signals) == expected_ids
    for row in signals.values():
        assert set(row) == {"delta_neg_distance", "delta_peer_z"}
        assert row["delta_neg_distance"] <= 0.0  # negated distance, never positive


def test_delta_peer_z_is_positive_for_the_true_author_on_average():
    """delta_peer_z should, on average, favor the claimed author over the
    partition's other candidates -- the same peer-relative shape
    "peer_probability" already uses for the Original score."""
    from validation.verify.pan_stack import trial_id

    authors = [_author("alpha", "alphaword"), _author("beta", "betaword"), _author("gamma", "gammaword")]
    signals = delta_trial_signals({"locked": authors}, top_n=50)["locked"]

    for author in authors:
        for probe_index in range(len(author.probes)):
            genuine = signals[trial_id(author.author_id, author.author_id, probe_index)]
            impostor_zs = [
                signals[trial_id(other.author_id, author.author_id, probe_index)]["delta_peer_z"]
                for other in authors
                if other.author_id != author.author_id
            ]
            assert genuine["delta_peer_z"] > max(impostor_zs)
