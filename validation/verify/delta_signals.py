"""Burrows'-Delta signals for the pan_stack fusion, computed per partition.

Reuses validation.attribution.delta's tokenization/relative-frequency
primitives rather than re-implementing them. Every other channel in
pan_stack.py (raw/peer probability, LUAR-family character/content
similarity) is either embedding- or z-score-based; Delta is the one
classic, word-frequency-only method never tried in that fusion — genuinely
independent evidence, not a variant of what's already there.

Profiles are built ONCE per partition (from each author's baseline texts
only, mirroring how the other channels never let a probe see its own
partition's baseline-building step) and reused for every probe in that
partition — mfw_delta_attribution itself rebuilds its pool per call, which
would be wasteful and, worse, silently rebuild the vocabulary/z-scale from
a different sub-pool per probe.
"""

from __future__ import annotations

from collections import Counter
from typing import Sequence

import numpy as np

from validation.attribution.delta import _SD_FLOOR, _rel_freqs, _tokens


class DeltaProfiles:
    """Frozen MFW-Delta reference for one partition's authors."""

    def __init__(self, names: Sequence[str], vocab: Sequence[str], profiles_z: np.ndarray):
        self.names = tuple(names)
        self.vocab = tuple(vocab)
        self.profiles_z = profiles_z  # (n_authors, len(vocab))
        self._mu: np.ndarray | None = None
        self._sd: np.ndarray | None = None

    def distances(self, probe_text: str) -> dict[str, float]:
        """Mean |z| distance from the probe to every author's profile."""
        freqs = _rel_freqs(_tokens(probe_text), list(self.vocab))
        test_z = (freqs - self._mu) / self._sd
        return {
            name: float(np.mean(np.abs(test_z - self.profiles_z[i])))
            for i, name in enumerate(self.names)
        }


def build_delta_profiles(
    authors: Sequence, *, top_n: int = 150
) -> DeltaProfiles:
    """Build partition-local MFW-Delta profiles from baseline texts only.

    ``authors`` elements need only a ``.author_id`` and ``.baselines``
    attribute (StyleAuthor satisfies this).
    """
    if len(authors) < 2:
        raise ValueError(f"delta profile build needs >= 2 authors, got {len(authors)}")
    pooled: Counter = Counter()
    for author in authors:
        for text in author.baselines:
            pooled.update(_tokens(text))
    vocab = [w for w, _ in pooled.most_common(top_n)]
    if not vocab:
        raise ValueError("delta profile build: pooled vocabulary is empty")

    names = [author.author_id for author in authors]
    raw = np.vstack(
        [
            np.mean([_rel_freqs(_tokens(t), vocab) for t in author.baselines], axis=0)
            for author in authors
        ]
    )
    mu = raw.mean(axis=0)
    sd = np.maximum(raw.std(axis=0, ddof=0), _SD_FLOOR)
    profiles_z = (raw - mu) / sd

    result = DeltaProfiles(names, vocab, profiles_z)
    result._mu = mu
    result._sd = sd
    return result


def delta_trial_signals(
    partitions: dict[str, Sequence], *, top_n: int = 150
) -> dict[str, dict[str, dict[str, float]]]:
    """Per-partition Delta signals, keyed the same way as
    ``pan_stack.original_trial_signals`` so ``combine_trials`` can merge them.

    Returns ``{partition_name: {trial_id: {"delta_neg_distance": ..., "delta_peer_z": ...}}}``.

    delta_neg_distance: -mean|z| distance from probe to the CLAIMED author's
      profile (negated so higher = more similar, matching the sign
      convention every other signal in this fusion already uses).
    delta_peer_z: how much closer the probe is to the claimed author than to
      the rest of the partition's pool, standardized -- the same
      peer-relative idea "peer_probability" already uses for the Original
      score, applied to Delta's own distance metric instead of rms_z.
    """
    from validation.verify.pan_stack import trial_id

    output: dict[str, dict[str, dict[str, float]]] = {}
    for partition_name, authors in partitions.items():
        profiles = build_delta_profiles(authors, top_n=top_n)
        rows: dict[str, dict[str, float]] = {}
        for source in authors:
            for probe_index, text in enumerate(source.probes):
                distances = profiles.distances(text)
                values = np.array([distances[n] for n in profiles.names], dtype=np.float64)
                mean_other = {
                    target: float(
                        (values.sum() - distances[target]) / max(1, len(values) - 1)
                    )
                    for target in profiles.names
                }
                std_pool = float(values.std(ddof=0)) or 1.0
                for target in profiles.names:
                    identifier = trial_id(target, source.author_id, probe_index)
                    rows[identifier] = {
                        "delta_neg_distance": -distances[target],
                        "delta_peer_z": (mean_other[target] - distances[target]) / std_pool,
                    }
        output[partition_name] = rows
    return output
