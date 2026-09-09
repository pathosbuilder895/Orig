"""
tests/test_tier17.py — branch coverage for `original/features/tier17.py`
(Tier 17 — Behavioral Biometrics).

Tier 17 is in DISABLED_FEATURE_GROUPS by default (see CLAUDE.md) — these
tests call the module's functions directly and do NOT flip that flag or
touch pipeline wiring; they only verify the raw feature functions handle
degenerate keystroke-log shapes (empty log, single event, missing fields,
out-of-range gaps) without raising and route through the correct neutral
arm.

Covers:
  - `_iki_deltas`: empty log, single event (no delta possible), an event
    missing both `elapsed` and `timestamp` (the `continue` arm), and a gap
    that is <= 0 or >= 30s (the "skip append" arm).
  - `_is_paste` was covered here directly (a dead helper unused elsewhere
    in the module) until 2026-09's Tier 17 recalibration removed it
    entirely -- paste_event_rate now reads the revision record's own
    `type` field rather than going through a heuristic.
  - `typing_speed_cv` / `burst_ratio`: the `< 10 deltas -> 0.5` neutral arm,
    and `typing_speed_cv`'s `mean < 1e-6 -> 0.0` arm (>= 10 vanishingly
    small but strictly positive deltas).
  - `deletion_rate`: the empty-keystrokes-and-no-precomputed-rate arm.
  - `pause_density`: the `word_count < 1` arm.
  - `paste_event_rate`: the `word_count < 1` (unnormalisable, raw count)
    arm.
"""

from __future__ import annotations

from original.features.tier17 import (
    _iki_deltas,
    burst_ratio,
    deletion_rate,
    paste_event_rate,
    pause_density,
    revision_depth,
    typing_speed_cv,
)

# ── _iki_deltas edge shapes ─────────────────────────────────────────────────


def test_iki_deltas_empty_log():
    assert _iki_deltas([]) == []


def test_iki_deltas_single_event_has_no_delta():
    assert _iki_deltas([{"elapsed": 100}]) == []


def test_iki_deltas_event_missing_elapsed_and_timestamp_is_skipped():
    # The middle event contributes no `t`, so it must be skipped (not
    # update `prev`) rather than crash or reset the interval.
    deltas = _iki_deltas([{"elapsed": 100}, {"key": "a"}, {"elapsed": 250}])
    assert deltas == [150.0]


def test_iki_deltas_zero_and_overlarge_gaps_are_not_appended():
    # d=0 (not > 0) and d=49000 (not < 30_000) both fail the range check
    # and must not be appended. Elapsed values are deliberately non-zero
    # (truthy) so `ks.get("elapsed") or ks.get("timestamp")` doesn't fall
    # through to the missing-timestamp `continue` arm instead.
    deltas = _iki_deltas([{"elapsed": 1000}, {"elapsed": 1000}, {"elapsed": 50000}])
    assert deltas == []


# ── typing_speed_cv / burst_ratio neutral arms ──────────────────────────────
#
# 2026-09's Tier 17 recalibration changed every degenerate-input arm from a
# flat literal (0.5 or 0.0) to _neutral(code) -- the feature's own NORM_BOUNDS
# midpoint, which is the only raw value that normalises to exactly 0.5
# downstream. A flat 0.5 or 0.0 against a bound like (0.0, 1.5) would
# normalise to something other than "no measurement". See tier17.py's module
# docstring and original/constants.py's NORM_BOUNDS comments for the derivation
# of each bound.


def test_typing_speed_cv_below_ten_deltas_is_neutral():
    assert typing_speed_cv({"keystrokes": [{"elapsed": 100}]}) == 0.75  # (0.0+1.5)/2


def test_typing_speed_cv_implausibly_small_median_returns_neutral():
    # >= 10 keystrokes with vanishingly small (but strictly positive)
    # inter-keystroke intervals -> median below the 60ms physical floor
    # (MIN_PLAUSIBLE_MEDIAN_IKI_MS), read as clock/quantisation noise, not
    # fast typing -- replaces the old "mean < 1e-6 -> 0.0" special case.
    keystrokes = [{"elapsed": i * 0.0000001} for i in range(12)]
    assert typing_speed_cv({"keystrokes": keystrokes}) == 0.75  # (0.0+1.5)/2


def test_burst_ratio_below_ten_deltas_is_neutral():
    assert burst_ratio({"keystrokes": []}) == 0.5  # (0.0+1.0)/2 -- bounds unchanged


# ── deletion_rate / pause_density / paste_event_rate degenerate arms ──────


def test_deletion_rate_no_precomputed_value_and_no_keystrokes_is_neutral():
    assert deletion_rate({"keystrokes": []}) == 0.1  # (0.0+0.20)/2


def test_deletion_rate_empty_dict_is_neutral():
    assert deletion_rate({}) == 0.1  # (0.0+0.20)/2


def test_pause_density_zero_word_count_is_neutral():
    # 0.0 would read as "this writer never pauses" -- the docstring's own
    # reasoning for why this arm returns neutral, not a real reading.
    result = pause_density({"pauses": [{"duration": 5000}], "wordCount": 0})
    assert result == 20.0  # (0.0+40.0)/2


def test_paste_event_rate_zero_word_count_is_neutral():
    # The old fallback returned a raw event count here -- a different unit
    # silently scored on the same scale as the normalised rate. Now neutral.
    result = paste_event_rate({"revisions": [{"type": "paste"}], "wordCount": 0})
    assert result == 2.5  # (0.0+5.0)/2


def test_revision_depth_no_revisions_is_neutral():
    # 0.0 is a real reading here ("only single-char corrections"), so the
    # no-data case must be distinguishable from it -- hence neutral, not 0.0.
    assert revision_depth({"revisions": []}) == 25.0  # (0.0+50.0)/2
