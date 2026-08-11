"""
tests/test_tier17_features.py — Tier 17 behavioral-biometric estimators.

These lock in the 2026-08-11 recalibration against published keystroke
benchmarks (Dhakal et al. 2018, 136M keystrokes / 168,960 participants).
The properties that matter are:

  * cadence dispersion is ROBUST (a planning pause must not dominate it)
  * cadence dispersion and burst structure are SPEED-INVARIANT — a slow
    typist and a fast typist writing with the same rhythm must score the
    same, otherwise the feature is a gross-speed proxy
  * "insufficient data" is distinguishable from a real zero, and lands on
    the NORM_BOUNDS midpoint so it normalises to 0.5 (neutral)
  * instrumentation artifacts are rejected rather than scored
"""

from __future__ import annotations

import pytest

from original.constants import NORM_BOUNDS, TIER17_CODES
from original.features.tier17 import (
    burst_ratio,
    deletion_rate,
    extract_tier17,
    paste_event_rate,
    pause_density,
    revision_depth,
    typing_speed_cv,
)


def _neutral(code: str) -> float:
    lo, hi = NORM_BOUNDS[code]
    return (lo + hi) / 2


def _ks(ikis: list[float], key: str = "a") -> dict:
    """Build a keystroke_data blob from a list of inter-key intervals (ms)."""
    keystrokes = [{"key": key, "elapsed": 0.0}]
    t = 0.0
    for d in ikis:
        t += d
        keystrokes.append({"key": key, "elapsed": t})
    return {"keystrokes": keystrokes}


# ── typing_speed_cv: robust + speed-invariant ────────────────────────────────


def test_typing_speed_cv_is_not_dominated_by_a_single_planning_pause():
    """
    Raw stdev/mean explodes when one 30 s planning pause lands in an otherwise
    even trace.  A robust dispersion estimator must barely move.
    """
    even = [200.0] * 40 + [210.0] * 40
    with_pause = even + [25_000.0]

    assert typing_speed_cv(_ks(with_pause)) == pytest.approx(
        typing_speed_cv(_ks(even)), abs=0.05
    )


def test_typing_speed_cv_is_speed_invariant():
    """A slow typist with the same rhythm scores the same as a fast one."""
    fast = [90.0, 110.0, 95.0, 130.0, 100.0, 120.0, 85.0, 105.0, 115.0, 100.0, 95.0, 125.0]
    slow = [d * 4 for d in fast]

    assert typing_speed_cv(_ks(slow)) == pytest.approx(typing_speed_cv(_ks(fast)), abs=1e-9)


def test_typing_speed_cv_detects_bimodal_burst_and_hesitate_cadence():
    """
    Alternating fast keystrokes and hesitations is the single most diagnostic
    composition rhythm, and it is exactly where MAD/median fails: half the
    intervals sit on the median, so MAD reads 0 and the writer scores as
    perfectly metronomic.  An interquartile estimator is bimodality-safe.
    """
    metronomic = [120.0] * 80

    # Unbalanced on purpose: with a 60/40 split the median lands ON the fast
    # mode, so more than half the mass is at distance 0 from it and MAD == 0.
    burst_and_hesitate = ([60.0] * 3 + [420.0] * 2) * 16

    assert typing_speed_cv(_ks(metronomic)) == pytest.approx(0.0, abs=1e-9)
    assert typing_speed_cv(_ks(burst_and_hesitate)) > 1.0


def test_typing_speed_cv_matches_published_population_anchor():
    """
    Dhakal et al. IKI mean 238.7 ms / SD 111.6 ms implies a lognormal with
    sigma_log 0.4446, whose IQR/(1.349*median) is 0.451.
    """
    import numpy as np

    rng = np.random.default_rng(7)
    ikis = list(rng.lognormal(np.log(216.2), 0.4446, 4000))

    assert typing_speed_cv(_ks(ikis)) == pytest.approx(0.451, abs=0.02)


def test_typing_speed_cv_neutral_when_too_few_keystrokes():
    assert typing_speed_cv(_ks([200.0] * 3)) == _neutral("typing_speed_cv")


def test_typing_speed_cv_rejects_sub_physical_cadence_as_instrument_artifact():
    """~60 ms is the observed physical floor; a 5 ms median is a clock bug."""
    assert typing_speed_cv(_ks([5.0] * 60)) == _neutral("typing_speed_cv")


# ── burst_ratio: pause-delimited production bursts ───────────────────────────


def test_burst_ratio_is_speed_invariant():
    """
    The old <150 ms absolute threshold made this a gross-speed proxy: fast
    typists saturated at 1.0, slow typists at 0.  Pause-delimited bursts must
    score a 4x-slower writer with the same phrasing identically.
    """
    fast = [100.0] * 30 + [3_000.0] + [100.0] * 5 + [3_000.0] + [100.0] * 30
    slow = [d * 4 if d < 2_000 else d for d in fast]

    assert 0.05 < burst_ratio(_ks(fast)) < 0.95  # non-degenerate, or this proves nothing

    assert burst_ratio(_ks(slow)) == pytest.approx(burst_ratio(_ks(fast)), abs=1e-9)


def test_burst_ratio_separates_fluent_from_halting_writing():
    fluent = [150.0] * 60
    halting = ([150.0] * 3 + [4_000.0]) * 15

    assert burst_ratio(_ks(fluent)) > 0.9
    assert burst_ratio(_ks(halting)) < 0.2


def test_burst_ratio_neutral_when_too_few_keystrokes():
    assert burst_ratio(_ks([150.0] * 3)) == _neutral("burst_ratio")


# ── IKI extraction hygiene ───────────────────────────────────────────────────


def test_first_keystroke_at_elapsed_zero_is_not_treated_as_missing():
    """
    `ks.get("elapsed") or ks.get("timestamp")` reads a legitimate elapsed=0.0
    as absent.  With no timestamp field to fall back on the whole keystroke is
    skipped, silently discarding the first real interval.
    """
    from original.features.tier17 import _iki_deltas

    keystrokes = [{"key": "a", "elapsed": float(200 * i)} for i in range(5)]

    assert _iki_deltas(keystrokes) == [200.0, 200.0, 200.0, 200.0]


# ── deletion_rate: unit validation on Bbook's precomputed value ──────────────


def test_deletion_rate_accepts_bbook_percentage_scaling():
    """Published mean is 6.31%; a `6.31` from Bbook means percent, not 631%."""
    assert deletion_rate({"deletionRate": 6.31}) == pytest.approx(0.0631)


def test_deletion_rate_passes_through_fractional_value():
    assert deletion_rate({"deletionRate": 0.0631}) == pytest.approx(0.0631)


def test_deletion_rate_neutral_on_uninterpretable_value():
    assert deletion_rate({"deletionRate": 812.0}) == _neutral("deletion_rate")


def test_deletion_rate_computes_from_raw_keystrokes():
    keystrokes = [{"key": "a"}] * 90 + [{"key": "Backspace"}] * 10
    assert deletion_rate({"keystrokes": keystrokes}) == pytest.approx(0.10)


def test_deletion_rate_neutral_when_no_keystrokes():
    assert deletion_rate({}) == _neutral("deletion_rate")


# ── pause_density: 2 s convention, interruptions excluded ────────────────────


def test_pause_density_counts_two_second_pauses():
    """The literature convention is 1 s or 2 s, not the previous 3 s."""
    data = {
        "pauses": [{"duration": 2_500}, {"duration": 2_100}, {"duration": 900}],
        "wordCount": 100,
    }
    assert pause_density(data) == pytest.approx(2.0)


def test_pause_density_excludes_long_interruptions():
    """>20 s is a look-up or a bathroom break, not a planning pause."""
    data = {
        "pauses": [{"duration": 2_500}, {"duration": 2_600}, {"duration": 45_000}],
        "wordCount": 100,
    }
    assert pause_density(data) == pytest.approx(2.0)


def test_pause_density_neutral_without_word_count():
    assert pause_density({"pauses": [{"duration": 2_500}]}) == _neutral("pause_density")


# ── paste_event_rate / revision_depth: missing data is not zero ──────────────


def test_paste_event_rate_neutral_without_word_count():
    """Previously returned a raw count here — a rate and a count aren't the same unit."""
    data = {"revisions": [{"type": "paste"}, {"type": "paste"}]}
    assert paste_event_rate(data) == _neutral("paste_event_rate")


def test_paste_event_rate_normalises_per_hundred_words():
    data = {"revisions": [{"type": "paste"}] * 3, "wordCount": 300}
    assert paste_event_rate(data) == pytest.approx(1.0)


def test_revision_depth_neutral_when_no_revision_data():
    """0.0 is a real value ('single-char corrections'), not 'instrument absent'."""
    assert revision_depth({}) == _neutral("revision_depth")


def test_revision_depth_averages_chars_affected():
    data = {
        "revisions": [
            {"type": "delete", "charsAffected": 3},
            {"type": "delete", "charsAffected": 7},
        ]
    }
    assert revision_depth(data) == pytest.approx(5.0)


# ── whole-tier contract ──────────────────────────────────────────────────────


def test_extract_tier17_returns_all_six_codes():
    assert set(extract_tier17(_ks([200.0] * 50))) == set(TIER17_CODES)


def test_extract_tier17_on_empty_blob_normalises_to_neutral():
    """
    Every feature must land on its NORM_BOUNDS midpoint so the pipeline's
    _normalise() maps it to exactly 0.5 — the same value the disabled-group
    path writes.  A raw 0.5 against bounds (0, 1.5) would normalise to 0.33.
    """
    from original.features.pipeline import _normalise

    raw = extract_tier17({})
    for code in TIER17_CODES:
        assert _normalise(raw[code], code) == pytest.approx(0.5), code
