"""Orchestrate the fused score: profile -> center -> fuse -> abstain.

Report-only by construction. This module receives no mutable scoring state
and returns a frozen dataclass; it cannot reach deviation_score,
quantum_fidelity, or the recommended action even by accident.

Peer-centering is one generic step applied identically to all three
channels: each channel's raw distance to the claimed author, minus the mean
of its raw distances to the eight references. A negative value means the
probe sits closer to the claimed author than to a typical classmate.
"""

from __future__ import annotations

import logging
import math
from collections.abc import Iterable
from dataclasses import dataclass

import numpy as np

from ..quantum.state import StudentState
from .artifact import load_artifact
from .channels import (
    compression_distance,
    diagonal_z_distance,
    function_word_distance,
    function_word_matrix,
)
from .peers import MIN_WORDS, Profile, build_profile, select_references

log = logging.getLogger(__name__)


@dataclass(frozen=True, eq=True)
class FusedScoreResult:
    """Report-only evidence weight. Higher log-odds = more impostor-like.

    ``eq=True`` gives value equality (the determinism test relies on it);
    the dict field makes instances unhashable, which is correct — these are
    per-submission observations, never dictionary keys.

    ``channels`` holds only the channels the shipped model actually fuses
    (``model.channel_order``) — this is what feeds ``fused_log_odds`` and
    what the API surfaces when the flag is enabled. ``all_channels`` holds
    every channel this call computed, regardless of ``channel_order`` (I1,
    2026-08 fix pass): the shipped artifact drops ``function_word_network``
    in its ablation, but the channel is still computed on every call (see
    ``channels.py``'s note on why it is retained), and persisting only the
    two fused values would discard that ablation-revisit data for free. Use
    ``all_channels`` for persistence, ``channels`` for anything that must
    only ever reflect what the model actually used.
    """

    fused_log_odds: float
    probability_different_author: float
    band: str
    channels: dict[str, float]
    all_channels: dict[str, float]
    reference_profiles: int
    baseline_samples: int
    model_version: str
    trained_on: str


def reset_for_tests() -> None:
    from . import artifact, peers

    artifact.reset_for_tests()
    peers.reset_cache_for_tests()


def _raw_distances(
    profile: Profile,
    probe_vec: np.ndarray,
    probe_text: str,
    probe_fw: np.ndarray,
) -> dict[str, float]:
    return {
        "peer_centered_z": diagonal_z_distance(
            profile.baseline_mean, profile.baseline_std, probe_vec
        ),
        "compression": compression_distance(
            profile.text, probe_text, baseline_size=profile.compressed_size
        ),
        "function_word_network": function_word_distance(profile.fw_matrix, probe_fw),
    }


def predict_fused_score(
    text: str,
    claimed_state: StudentState,
    states: Iterable[StudentState],
    *,
    probe_vector: np.ndarray | None = None,
) -> FusedScoreResult | None:
    """Fused, peer-centered evidence weight — or ``None`` when unavailable.

    Thin wrapper over :func:`predict_fused_score_with_reason` that drops the
    reason code, kept for every existing caller and test that only cares
    about the result. See that function's docstring for the abstain
    contract.
    """
    result, _reason, _n_peers, _n_baselines = predict_fused_score_with_reason(
        text, claimed_state, states, probe_vector=probe_vector
    )
    return result


def predict_fused_score_with_reason(
    text: str,
    claimed_state: StudentState,
    states: Iterable[StudentState],
    *,
    probe_vector: np.ndarray | None = None,
) -> tuple[FusedScoreResult | None, str, int, int]:
    """Same contract as :func:`predict_fused_score`, plus an outcome reason.

    Returns ``(result, reason, n_peers, n_baselines)``. ``reason`` is
    ``"hit"`` on success, else a short code identifying the abstain/failure
    path: ``probe_too_short``, ``artifact_unavailable``,
    ``baseline_below_min``, ``insufficient_peers``,
    ``probe_vector_shape_mismatch``, or ``channel_error``. ``n_peers`` and
    ``n_baselines`` reflect whatever was known at the point of abstain (0
    when the check that would have produced the count never ran).

    Returning the reason here — rather than a module-level "last abstain
    reason" — keeps this safe under concurrent scoring calls (I2, 2026-08 fix
    pass): a global would race across requests from different threads.

    ``probe_vector`` lets the scoring path hand over the feature vector it
    has already extracted. Feature extraction is the most expensive step in
    scoring, and re-running it here would double that cost for every
    submission; omit the argument only in tests and offline tools.

    Returns None (never raises, never a partial result) when the probe is
    too short, the claimed baseline carries fewer than three text samples,
    fewer than eight eligible same-tenant peers exist, the artifact is
    missing or invalid, or any channel fails.

    Every abstain path is logged at DEBUG with a distinguishing reason —
    these are ordinary operating states (a cold-start student, a
    not-yet-installed artifact), not failures, and must not be confused in
    the logs with the WARNING the blanket handler below emits for a genuine
    bug.
    """
    try:
        # Cheapest checks first: a short probe or a missing artifact must not
        # pay for eight peer profiles before abstaining.
        if len(text.split()) < MIN_WORDS:
            log.debug("Fused score abstain: probe below MIN_WORDS")
            return None, "probe_too_short", 0, 0

        model = load_artifact()
        if model is None:
            log.debug("Fused score abstain: artifact unavailable")
            return None, "artifact_unavailable", 0, 0

        claimed_profile = build_profile(claimed_state)
        if claimed_profile is None:
            log.debug("Fused score abstain: claimed baseline below MIN_BASELINES")
            return None, "baseline_below_min", 0, 0

        references = select_references(claimed_state, states)
        if not references:
            log.debug("Fused score abstain: fewer than N_REFERENCES eligible peers")
            return None, "insufficient_peers", 0, claimed_profile.sample_count

        probe_vec = _probe_vector(text, claimed_state, probe_vector)
        if probe_vec is None:
            return (
                None,
                "probe_vector_shape_mismatch",
                len(references),
                claimed_profile.sample_count,
            )
        probe_fw = function_word_matrix(text)

        own = _raw_distances(claimed_profile, probe_vec, text, probe_fw)
        peer_rows = [
            _raw_distances(reference, probe_vec, text, probe_fw) for reference in references
        ]
        centered = {
            name: float(own[name] - np.mean([row[name] for row in peer_rows])) for name in own
        }

        values = np.asarray([centered[name] for name in model.channel_order], dtype=np.float64)
        log_odds = model.log_odds(values)
        result = FusedScoreResult(
            fused_log_odds=round(log_odds, 6),
            probability_different_author=round(1.0 / (1.0 + math.exp(-log_odds)), 6),
            band=model.band(log_odds),
            channels={name: round(centered[name], 6) for name in model.channel_order},
            all_channels={name: round(centered[name], 6) for name in centered},
            reference_profiles=len(references),
            baseline_samples=claimed_profile.sample_count,
            model_version=model.model_version,
            trained_on=model.trained_on,
        )
        return result, "hit", len(references), claimed_profile.sample_count
    except Exception as exc:  # noqa: BLE001
        log.warning(
            "Fused score failed (%s: %s); returning None",
            type(exc).__name__,
            exc,
            exc_info=True,
        )
        return None, "channel_error", 0, 0


def _probe_vector(
    text: str,
    claimed_state: StudentState,
    supplied: np.ndarray | None,
) -> np.ndarray | None:
    """The probe's feature vector: the caller's if given, else extracted here."""
    if supplied is not None:
        vector = np.asarray(supplied, dtype=np.float64)
    else:
        from ..features.pipeline import feature_vector

        vector = np.asarray(feature_vector(text), dtype=np.float64)
    if vector.shape != claimed_state.baseline_mean.shape:
        log.debug(
            "Fused score abstain: probe vector shape %s != baseline %s",
            vector.shape,
            claimed_state.baseline_mean.shape,
        )
        return None
    return vector
