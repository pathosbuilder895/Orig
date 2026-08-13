"""Three pure distance functions for the fused score.

Each maps (baseline, probe) -> float where LARGER means MORE different.
No state, no I/O, no logging: everything here is a deterministic function
of its arguments so it can be tested with fixed inputs.

The expensive halves (compressed baseline size, function-word matrix)
are exposed as separate builders so ``peers.py`` can cache them per
profile instead of recomputing them for every submission.
"""

from __future__ import annotations

import lzma
import re

import numpy as np

from ..style_authorship import FUNCTION_WORDS

CHANNEL_NAMES: tuple[str, ...] = (
    "peer_centered_z",
    "compression",
    "function_word_network",
)
# The shipped artifact (original/data/fused_score_v1.json) does NOT use
# function_word_network — train_fused_score.py's ablation drops it (its AUC
# gain fell below ABLATION_MIN_AUC_GAIN on the PAN development split). It
# stays implemented and unit-tested, and expert.py still computes it on
# every scoring call and persists it via FusedScoreResult.all_channels (I1,
# 2026-08 fix pass), specifically so a later ablation-revisit on real pilot
# traffic has the data without re-instrumenting anything. Do not delete this
# channel on the assumption it's dead code.

# ── Channel 1: diagonal z ─────────────────────────────────────────────────────
# Same shape as quantum/scoring.py's primary formulation — winsorize |z| at
# 4 sigma, RMS across features, tanh(rms / 1.5) — but deliberately WITHOUT the
# tier weight vector and the active-feature mask. This channel is peer-centered
# downstream, so a per-feature prior that applies equally to the claimed author
# and to all eight references would cancel out; leaving it off keeps the channel
# a plain distance. Callers pass baseline_mean / baseline_std straight from
# StudentState so the moments can never drift from production.
_Z_CAP = 4.0
_TANH_DIVISOR = 1.5
_SIGMA_HARD_FLOOR = 0.005

# ── Channel 2: compression ────────────────────────────────────────────────────
# FORMAT_RAW + preset 1 is the configuration measured in the 2026-08 paths
# experiment. preset 1 keeps the dictionary small enough that a ~700-word probe
# actually shifts the compressed size; higher presets wash the signal out.
_LZMA_FILTERS = [{"id": lzma.FILTER_LZMA2, "preset": 1}]

# ── Channel 3: function-word adjacency network ────────────────────────────────
# First 100 function words become states; everything else collapses to OTHER.
# A transition is recorded between two function words separated by <= 3
# non-function tokens, so the network captures local syntactic habit rather
# than raw adjacency.
_FW_STATES: tuple[str, ...] = tuple(FUNCTION_WORDS)[:100]
_FW_INDEX: dict[str, int] = {word: i for i, word in enumerate(_FW_STATES)}
_OTHER_STATE = len(_FW_STATES)
_N_STATES = _OTHER_STATE + 1
_MAX_GAP = 3
_SMOOTHING = 0.05
_TOKEN_RE = re.compile(r"[a-z']+")


def diagonal_z_distance(
    baseline_mean: np.ndarray,
    baseline_std: np.ndarray,
    probe_vec: np.ndarray,
) -> float:
    """Winsorized RMS z-distance in [0, 1]; 0.0 means identical to the mean.

    Argument order matches the module docstring's ``(baseline, probe)``
    convention (aligned in the 2026-08 fix pass — this channel used to take
    ``probe_vec`` first, unlike ``compression_distance`` and
    ``function_word_distance``, which was a silent transposed-call trap)."""
    sigma = np.maximum(np.asarray(baseline_std, dtype=np.float64), _SIGMA_HARD_FLOOR)
    z = (
        np.asarray(probe_vec, dtype=np.float64) - np.asarray(baseline_mean, dtype=np.float64)
    ) / sigma
    z_capped = np.clip(z, -_Z_CAP, _Z_CAP)
    rms_z = float(np.sqrt(np.mean(z_capped**2)))
    return float(np.tanh(rms_z / _TANH_DIVISOR))


def compressed_size(payload: bytes) -> int:
    """Compressed length of ``payload`` under the pinned LZMA configuration."""
    return len(lzma.compress(payload, format=lzma.FORMAT_RAW, filters=_LZMA_FILTERS))


def compression_distance(
    baseline_text: str,
    probe_text: str,
    *,
    baseline_size: int | None = None,
) -> float:
    """Conditional compression cost of ``probe_text`` given ``baseline_text``.

    ``(C(base + probe) - C(base)) / C(probe)`` — near 0 when the baseline
    already "explains" the probe, near or above 1 when it does not. Pass
    ``baseline_size`` to reuse a cached ``C(base)``.
    """
    base_bytes = baseline_text.encode("utf-8", "ignore")
    probe_bytes = probe_text.encode("utf-8", "ignore")
    if not probe_bytes:
        return 1.0
    base_size = compressed_size(base_bytes) if baseline_size is None else int(baseline_size)
    joint = compressed_size(base_bytes + probe_bytes)
    return float((joint - base_size) / max(1, compressed_size(probe_bytes)))


def function_word_matrix(text: str) -> np.ndarray:
    """Row-normalized function-word transition matrix, flattened to unit norm."""
    tokens = _TOKEN_RE.findall(text.lower())
    counts = np.full((_N_STATES, _N_STATES), _SMOOTHING, dtype=np.float64)
    previous: int | None = None
    gap = 0
    for token in tokens:
        state = _FW_INDEX.get(token, _OTHER_STATE)
        if state == _OTHER_STATE:
            gap += 1
            if gap > _MAX_GAP:
                previous = None
            continue
        if previous is not None:
            counts[previous, state] += 1.0
        previous = state
        gap = 0
    probabilities = counts / counts.sum(axis=1, keepdims=True)
    flat = probabilities.reshape(-1)
    return flat / max(float(np.linalg.norm(flat)), 1e-12)


def function_word_distance(baseline_matrix: np.ndarray, probe_matrix: np.ndarray) -> float:
    """Cosine distance in [0, 2] between two unit-norm transition matrices."""
    return float(1.0 - float(np.dot(baseline_matrix, probe_matrix)))
