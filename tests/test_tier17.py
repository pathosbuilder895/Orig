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
  - `_is_paste`: unit-tested directly — it is not called by any other
    function in this module (dead helper), so no production code path
    reaches it.
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
    _is_paste,
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


# ── _is_paste (unit-tested directly; unused elsewhere in the module) ───────


def test_is_paste_true_on_paste_event_type():
    assert _is_paste("paste", "x") is True


def test_is_paste_true_on_v_key():
    assert _is_paste(None, "v") is True


def test_is_paste_false_otherwise():
    assert _is_paste(None, "x") is False


# ── typing_speed_cv / burst_ratio neutral arms ──────────────────────────────


def test_typing_speed_cv_below_ten_deltas_is_neutral():
    assert typing_speed_cv({"keystrokes": [{"elapsed": 100}]}) == 0.5


def test_typing_speed_cv_near_zero_mean_returns_zero():
    # >= 10 keystrokes with vanishingly small (but strictly positive)
    # inter-keystroke intervals -> mean < 1e-6.
    keystrokes = [{"elapsed": i * 0.0000001} for i in range(12)]
    assert typing_speed_cv({"keystrokes": keystrokes}) == 0.0


def test_burst_ratio_below_ten_deltas_is_neutral():
    assert burst_ratio({"keystrokes": []}) == 0.5


# ── deletion_rate / pause_density / paste_event_rate degenerate arms ──────


def test_deletion_rate_no_precomputed_value_and_no_keystrokes_is_zero():
    assert deletion_rate({"keystrokes": []}) == 0.0


def test_deletion_rate_empty_dict_is_zero():
    assert deletion_rate({}) == 0.0


def test_pause_density_zero_word_count_is_zero():
    result = pause_density({"pauses": [{"duration": 5000}], "wordCount": 0})
    assert result == 0.0


def test_paste_event_rate_zero_word_count_returns_raw_count():
    result = paste_event_rate({"revisions": [{"type": "paste"}], "wordCount": 0})
    assert result == 1.0


def test_revision_depth_no_revisions_is_zero():
    assert revision_depth({"revisions": []}) == 0.0
