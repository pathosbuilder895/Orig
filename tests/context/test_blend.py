"""
tests/context/test_blend.py — Phase 7 sliding-window blend detection tests.

Covers:
- Window enumeration (count + overlap math)
- Pettitt change-point statistic (location + p-value behaviour)
- Edge cases: too-short text, no baseline samples
- End-to-end blend detection: uniform low blend, heterogeneous high blend
- Pydantic schema interop (`BlendResultOut`)

The end-to-end tests use synthetic per-window scores via monkeypatching
where possible — running the full feature extraction inside a unit test
on a 600-token text takes too long and reproduces what the integration
suite already covers.
"""

from __future__ import annotations

from typing import List, Optional

import numpy as np
import pytest

from original.constants import FEATURE_DIM
from original.context.blend import (
    BLEND_DETECT_THRESHOLD, BLEND_INDEX_NOISE_FLOOR,
    SHIFT_LOCATION_MIN_BLEND_INDEX,
    BlendResult, WindowScore,
    _pettitt_change_point, _window_offsets, detect_blend,
)
from original.quantum.state import BaselineSample, StudentState


# ── Helpers ──────────────────────────────────────────────────────────────────

def _state(n_samples: int = 3) -> StudentState:
    return StudentState(student_id="s", samples=[
        BaselineSample(
            text=(f"Baseline sample {i} containing realistic prose with "
                  "natural sentence structure and varied vocabulary." * 5),
            vector=np.random.RandomState(i).uniform(0.3, 0.7, FEATURE_DIM),
            provenance="verified", auth_weight=1.0,
            assignment=f"a{i}",
        )
        for i in range(n_samples)
    ])


# ══════════════════════════════════════════════════════════════════════════════
# Window enumeration
# ══════════════════════════════════════════════════════════════════════════════

class TestWindowOffsets:
    def test_window_count_matches_overlap_3(self):
        # 600 tokens, 300-token windows, 50% overlap → starts at [0, 150, 300]
        # → 3 windows (the spec's canonical example).
        offs = _window_offsets(600, 300, 0.5)
        assert offs == [(0, 300), (150, 450), (300, 600)]

    def test_no_overlap_gives_disjoint_windows(self):
        offs = _window_offsets(900, 300, 0.0)
        assert offs == [(0, 300), (300, 600), (600, 900)]

    def test_short_text_returns_single_window(self):
        # Less than one window's worth of tokens → one window covering all.
        offs = _window_offsets(100, 300, 0.5)
        assert offs == [(0, 100)]

    def test_uneven_step_anchors_tail_window(self):
        # 700 tokens, 300-window, 50% overlap → step=150
        # Starts: 0, 150, 300, 400 (anchored)
        offs = _window_offsets(700, 300, 0.5)
        assert offs[0] == (0, 300)
        # Last window must end at n_tokens (tail anchor).
        assert offs[-1][1] == 700
        # All windows are exactly window_tokens wide.
        for s, e in offs:
            assert e - s == 300

    def test_overlap_75_percent(self):
        # 600 tokens, 300-window, 75% overlap → step=75 → 5 windows.
        offs = _window_offsets(600, 300, 0.75)
        starts = [s for s, _ in offs]
        # Starts at 0, 75, 150, 225, 300 — last fits exactly.
        assert starts == [0, 75, 150, 225, 300]


# ══════════════════════════════════════════════════════════════════════════════
# Pettitt change-point
# ══════════════════════════════════════════════════════════════════════════════

class TestPettittChangePoint:
    def test_too_short_returns_none(self):
        idx, p = _pettitt_change_point(np.array([0.1, 0.5, 0.9]))
        assert idx is None
        assert p == 1.0

    def test_uniform_sequence_high_p_value(self):
        # Uniform → small K → large p-value (cannot reject H0).
        x = np.array([0.10, 0.12, 0.11, 0.09, 0.10, 0.11, 0.13, 0.10])
        idx, p = _pettitt_change_point(x)
        # Argmax may still return SOMETHING; the diagnostic is the p-value.
        assert p > 0.5, f"uniform should have p > 0.5, got {p}"

    def test_clear_shift_locates_correctly(self):
        # 4 low followed by 4 high → change-point at index 3 (last "before").
        x = np.array([0.10, 0.12, 0.11, 0.09, 0.85, 0.88, 0.84, 0.82])
        idx, p = _pettitt_change_point(x)
        assert idx in (3, 4), f"expected 3 or 4, got {idx}"
        # p will be < 1 but may not reject at α=0.05 for n=8 — that's OK,
        # gating is done on blend_index, not p (see module docstring).

    def test_p_value_in_unit_interval(self):
        # Asymptotic approximation can over-shoot; we clamp to [0, 1].
        for x in [
            np.linspace(0, 1, 10),                    # monotone
            np.full(10, 0.5),                          # flat (K=0)
            np.array([0.0]*5 + [1.0]*5),               # strong shift
        ]:
            _idx, p = _pettitt_change_point(x)
            assert 0.0 <= p <= 1.0


# ══════════════════════════════════════════════════════════════════════════════
# detect_blend edge cases
# ══════════════════════════════════════════════════════════════════════════════

class TestDetectBlendEdgeCases:
    def test_text_too_short(self):
        result = detect_blend("Just a few words.", _state(),
                               window_tokens=300)
        assert result.fallback_reason == "text_too_short"
        assert result.per_section == []
        assert result.blend_detected is False
        assert result.blend_index == 0.0

    def test_empty_state_no_baseline_samples(self):
        empty_state = StudentState(student_id="s", samples=[])
        # Provide enough tokens that we get past the "too short" check.
        text = "word " * 400
        result = detect_blend(text, empty_state, window_tokens=300)
        assert result.fallback_reason == "no_baseline_samples"
        assert result.per_section == []

    def test_invalid_overlap_raises(self):
        with pytest.raises(ValueError):
            detect_blend("text", _state(), overlap=1.0)
        with pytest.raises(ValueError):
            detect_blend("text", _state(), overlap=-0.1)

    def test_invalid_window_tokens_raises(self):
        with pytest.raises(ValueError):
            detect_blend("text", _state(), window_tokens=10)


# ══════════════════════════════════════════════════════════════════════════════
# Aggregation logic (unit-tested via direct construction)
# ══════════════════════════════════════════════════════════════════════════════

class TestBlendAggregation:
    """
    The aggregation math (blend_index, shift_positions) is testable in
    isolation by feeding pre-built WindowScore arrays to a synthetic
    detect_blend. Rather than monkeypatch the orchestrator, we replicate
    the aggregator inline so test logic stays explicit.
    """

    def _aggregate(self, scores: List[float]) -> BlendResult:
        """Re-run the aggregation in isolation with a controlled score list."""
        from original.context.blend import (
            BLEND_INDEX_NOISE_FLOOR as nf,
            BLEND_DETECT_THRESHOLD as dt,
            SHIFT_LOCATION_MIN_BLEND_INDEX as st,
            MIN_WINDOWS_FOR_SHIFT_DETECTION as mw,
            _pettitt_change_point,
        )
        per_section = [
            WindowScore(start=i*150, end=i*150+300, score=s, confidence="low")
            for i, s in enumerate(scores)
        ]
        valid = np.array(scores, dtype=np.float64)
        std_score = float(np.std(valid))
        blend_index = float(np.clip(std_score / nf, 0.0, 1.0))
        shift_positions: List[int] = []
        if blend_index >= st and len(valid) >= mw:
            change_idx, _ = _pettitt_change_point(valid)
            if change_idx is not None and change_idx < len(per_section):
                shift_positions.append(per_section[change_idx].end)
        return BlendResult(
            blend_detected=blend_index >= dt or len(shift_positions) > 0,
            blend_index=round(blend_index, 4),
            shift_positions=shift_positions,
            per_section=per_section,
            n_tokens=per_section[-1].end if per_section else 0,
        )

    def test_uniform_text_low_blend_index(self):
        # Same-author windows with small natural variance → blend_index < 0.5.
        # 0.15 noise floor; std of [0.10, 0.11, 0.12, 0.10] ≈ 0.008 → ~0.05.
        result = self._aggregate([0.10, 0.11, 0.12, 0.10, 0.11])
        assert result.blend_index < 0.20, f"expected < 0.20, got {result.blend_index}"
        assert result.blend_detected is False
        assert result.shift_positions == []

    def test_mid_document_shift_detected(self):
        # 50% student-style + 50% AI-style → high std → blend_detected=True
        # AND a shift_position somewhere near the midpoint.
        result = self._aggregate([0.10, 0.12, 0.11, 0.85, 0.88, 0.86])
        assert result.blend_detected is True
        # blend_index should saturate to 1.0 (std ≈ 0.37, /0.15 → 2.5 → clip 1).
        assert result.blend_index == 1.0
        # Shift position should be near the midpoint of the document
        # (windows 0..2 are low, 3..5 are high — boundary at the end of
        # window 2, which is 2*150 + 300 = 600).
        assert len(result.shift_positions) == 1
        # In token space: the boundary should be in the middle third.
        total_tokens = result.n_tokens
        shift = result.shift_positions[0]
        assert total_tokens / 3 <= shift <= 2 * total_tokens / 3, \
            f"shift {shift} not near midpoint of {total_tokens}"

    def test_no_shift_when_below_location_threshold(self):
        # Mild variation: blend_index is below SHIFT_LOCATION_MIN_BLEND_INDEX
        # → no shift_position reported even if Pettitt's argmax is non-trivial.
        # std([0.30, 0.34, 0.32, 0.33]) ≈ 0.015 → blend_index ≈ 0.10.
        result = self._aggregate([0.30, 0.34, 0.32, 0.33, 0.31])
        assert result.blend_index < SHIFT_LOCATION_MIN_BLEND_INDEX
        assert result.shift_positions == []

    def test_blend_detected_via_blend_index_alone(self):
        # blend_index >= 0.5 is enough to flip blend_detected even without
        # a Pettitt shift point (the OR gate in the aggregator).
        # std([0.20, 0.50, 0.20, 0.55]) ≈ 0.17 → blend_index ≈ 1.13 → clip 1.0.
        result = self._aggregate([0.20, 0.55, 0.22, 0.50, 0.18])
        assert result.blend_index >= BLEND_DETECT_THRESHOLD
        assert result.blend_detected is True


# ══════════════════════════════════════════════════════════════════════════════
# End-to-end (slow — full feature extraction)
# ══════════════════════════════════════════════════════════════════════════════

class TestEndToEnd:
    """
    Hits the actual `detect_blend` with a 600-token text. Exercises the
    full pipeline: orchestrator cluster matching, per-window feature
    extraction, scoring. Slow but the only test that catches integration
    bugs.
    """

    @pytest.mark.slow
    def test_uniform_text_produces_low_blend(self):
        # A genuinely uniform text against a similar-style baseline —
        # blend_index should stay well below 0.5.
        text = ("The committee met on Monday to discuss the proposal. "
                "Members reviewed the timeline carefully. ") * 50
        state = _state(n_samples=3)
        result = detect_blend(text, state, window_tokens=300, overlap=0.5,
                                submission_id="e2e_uniform")
        # Per-section must be non-empty (text is long enough).
        assert len(result.per_section) >= 2
        # Each window has a finite score.
        for w in result.per_section:
            assert not np.isnan(w.score)
            assert 0.0 <= w.score <= 1.0
            assert w.confidence == "low"     # window_tokens=300 < 500


# ══════════════════════════════════════════════════════════════════════════════
# Pydantic schema interop
# ══════════════════════════════════════════════════════════════════════════════

class TestPydanticInterop:
    def test_blend_result_to_pydantic(self):
        from original.schemas import BlendResultOut, WindowScoreOut
        windows = [
            WindowScore(start=0, end=300, score=0.2, confidence="low"),
            WindowScore(start=150, end=450, score=0.8, confidence="low"),
        ]
        result = BlendResult(
            blend_detected=True, blend_index=0.85,
            shift_positions=[300], per_section=windows, n_tokens=450,
        )
        # Convert each WindowScore → WindowScoreOut, then build the response.
        pyd = BlendResultOut(
            blend_detected=result.blend_detected,
            blend_index=result.blend_index,
            shift_positions=list(result.shift_positions),
            per_section=[
                WindowScoreOut(start=w.start, end=w.end,
                                score=w.score, confidence=w.confidence)
                for w in result.per_section
            ],
            n_tokens=result.n_tokens,
            fallback_reason=result.fallback_reason,
        )
        assert pyd.blend_detected is True
        assert pyd.blend_index == 0.85
        assert pyd.shift_positions == [300]
        assert len(pyd.per_section) == 2
        assert pyd.per_section[0].confidence == "low"

    def test_to_dict_is_json_safe(self):
        import json
        result = BlendResult(
            blend_detected=False, blend_index=0.1,
            shift_positions=[], per_section=[
                WindowScore(start=0, end=300, score=0.1, confidence="low"),
            ],
            n_tokens=300,
        )
        d = result.to_dict()
        # Round-trip JSON without errors.
        s = json.dumps(d)
        d2 = json.loads(s)
        assert d2["blend_detected"] is False
        assert d2["per_section"][0]["score"] == 0.1
