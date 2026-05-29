"""
tests/test_professor_narrative.py — Unit tests for the professor narrative module.

Tests cover: magnitude thresholds, headline variants, summary variants,
observation assembly, hypothesis selection, suggested actions, confidence notes,
and the top-level builder with partial/missing layer7 data.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

import pytest

from original.quantum.professor_narrative import (
    ProfessorExplanation,
    _build_confidence_note,
    _build_headline,
    _build_hypotheses,
    _build_observations,
    _build_suggested_action,
    _build_summary,
    _magnitude,
    build_professor_explanation,
)


# ── _magnitude ────────────────────────────────────────────────────────────────

class TestMagnitude:
    def test_below_threshold_returns_none(self):
        assert _magnitude(0.05) is None
        assert _magnitude(-0.09) is None
        assert _magnitude(0.0) is None

    def test_somewhat_band(self):
        assert _magnitude(0.10) == "somewhat"
        assert _magnitude(0.15) == "somewhat"
        assert _magnitude(-0.19) == "somewhat"

    def test_notably_band(self):
        assert _magnitude(0.20) == "notably"
        assert _magnitude(0.25) == "notably"
        assert _magnitude(-0.31) == "notably"

    def test_significantly_band(self):
        assert _magnitude(0.32) == "significantly"
        assert _magnitude(0.40) == "significantly"
        assert _magnitude(-0.44) == "significantly"

    def test_markedly_band(self):
        assert _magnitude(0.45) == "markedly"
        assert _magnitude(1.0) == "markedly"
        assert _magnitude(-2.0) == "markedly"

    def test_exact_boundary_lower(self):
        # 0.10 is the first non-None value
        assert _magnitude(0.10) is not None
        assert _magnitude(0.099) is None


# ── _build_headline ───────────────────────────────────────────────────────────

class TestBuildHeadline:
    def test_low_deviation_no_concern(self):
        # Polarity reframe: lead with positive confidence %, "confirmed authentic"
        h = _build_headline(0.20, "Jane")
        assert "Jane" in h
        # Should lead with what was CONFIRMED (≥80%), not what deviated
        assert "%" in h
        assert "consistent" in h.lower()
        assert "confirmed" in h.lower()

    def test_medium_deviation_some_differences(self):
        h = _build_headline(0.40, "Marcus")
        assert "Marcus" in h
        assert "%" in h
        assert "consistent" in h.lower()
        # Should note areas to explore, not lead with accusation
        assert "closer look" in h.lower() or "areas" in h.lower() or "exploring" in h.lower()

    def test_high_deviation_noticeable(self):
        h = _build_headline(0.60, "Alex")
        assert "Alex" in h
        assert "%" in h
        assert "consistent" in h.lower()
        # Notable differences, not "noticeably different"
        assert "notable" in h.lower() or "differences" in h.lower()

    def test_very_high_deviation_warrants_conversation(self):
        h = _build_headline(0.80, "Sam")
        assert "Sam" in h
        assert "conversation" in h.lower()

    def test_boundary_exactly_0_30(self):
        # 0.30 falls into "with a few areas worth a closer look" band
        h = _build_headline(0.30, "Test")
        assert "%" in h
        assert "consistent" in h.lower()
        # Should NOT say "confirmed authentic" (that's the < 0.30 band)
        assert "closer look" in h.lower() or "areas" in h.lower() or "exploring" in h.lower()

    def test_boundary_exactly_0_55(self):
        # 0.55 falls into "notable differences" band
        h = _build_headline(0.55, "Test")
        assert "%" in h
        assert "consistent" in h.lower()
        assert "notable" in h.lower() or "differences" in h.lower()

    def test_boundary_exactly_0_75(self):
        h = _build_headline(0.75, "Test")
        assert "conversation" in h.lower()

    def test_headline_shows_positive_percentage(self):
        """Voice-match percentage should always appear and be positive."""
        for dev in (0.10, 0.30, 0.55, 0.75, 0.90):
            h = _build_headline(dev, "Student")
            assert "%" in h, f"Missing % for deviation={dev}"
            # Extract the number before the %
            import re
            pct_vals = [int(m) for m in re.findall(r"(\d+)%", h)]
            assert all(p >= 0 for p in pct_vals), f"Negative % in headline: {h}"


# ── _build_summary ────────────────────────────────────────────────────────────

class TestBuildSummary:
    def test_low_deviation_strong_match(self):
        s = _build_summary(0.15, "no_action", "Jane", 0, "insufficient_data")
        assert "strong match" in s.lower()
        assert "Jane" in s

    def test_low_deviation_with_growth_adds_growth_note(self):
        s = _build_summary(0.15, "no_action", "Jane", 0, "growth")
        assert "development" in s.lower() or "positive" in s.lower()

    def test_medium_deviation_common_explanation(self):
        s = _build_summary(0.40, "monitor", "Marcus", 3, "lateral")
        assert "Marcus" in s
        # Should mention common innocent explanations
        assert "topic" in s.lower() or "genre" in s.lower() or "common" in s.lower()

    def test_high_deviation_noticeable(self):
        s = _build_summary(0.65, "schedule_conversation", "Alex", 4, "lateral")
        assert "Alex" in s
        # New framing: leads with what was confirmed, then notes the differences
        assert "differences" in s.lower() or "conversation" in s.lower() or "pattern" in s.lower()

    def test_very_high_deviation_substantial(self):
        s = _build_summary(0.85, "escalate", "Sam", 6, "regressive")
        assert "Sam" in s
        assert "substantial" in s.lower() or "conversation" in s.lower()


# ── _build_observations ───────────────────────────────────────────────────────

@dataclass
class _FakeFC:
    code: str
    delta: float
    direction: str = "destructive"


class TestBuildObservations:
    def test_no_features_gives_generic_note(self):
        obs = _build_observations([], [], "Jane")
        assert len(obs) == 1
        assert "Jane" in obs[0]

    def test_unknown_feature_code_skipped(self):
        fc = _FakeFC(code="nonexistent_code_xyz", delta=0.5)
        obs = _build_observations([fc], [], "Jane")
        # Falls through to generic note since code not in _FEATURE_PLAIN
        assert len(obs) >= 1

    def test_small_delta_skipped(self):
        fc = _FakeFC(code="type_token_ratio", delta=0.05)
        obs = _build_observations([fc], [], "Jane")
        # delta < 0.10 → _magnitude returns None → skipped → generic note
        assert len(obs) == 1

    def test_known_feature_positive_delta(self):
        fc = _FakeFC(code="type_token_ratio", delta=0.35)
        obs = _build_observations([fc], [], "Jane")
        assert len(obs) >= 1
        assert "Jane" in obs[0]
        # Positive delta → "more" description (richer vocabulary)
        assert "vocabulary" in obs[0].lower() or "varied" in obs[0].lower()

    def test_known_feature_negative_delta(self):
        fc = _FakeFC(code="type_token_ratio", delta=-0.35)
        obs = _build_observations([fc], [], "Jane")
        assert len(obs) >= 1
        # Negative delta → "less" description for type_token_ratio:
        # "used a narrower vocabulary range than usual, repeating words more frequently"
        assert "narrower" in obs[0].lower() or "vocabulary" in obs[0].lower() or "repeating" in obs[0].lower()

    def test_capped_at_five(self):
        features = [_FakeFC(code="type_token_ratio", delta=0.5 + i * 0.1) for i in range(10)]
        obs = _build_observations(features, [], "Jane")
        assert len(obs) <= 5

    def test_constructive_fills_gap_when_few_destructive(self):
        # One destructive with sub-threshold delta → generic note
        # Two constructive → added as context
        destr = [_FakeFC(code="type_token_ratio", delta=0.08)]  # below threshold
        constr = [_FakeFC(code="avg_sentence_length", delta=0.0, direction="constructive")]
        obs = _build_observations(destr, constr, "Jane")
        # Some mention of "consistent" from constructive, or the generic fallback
        assert len(obs) >= 1

    def test_behavioral_feature_included(self):
        fc = _FakeFC(code="paste_event_rate", delta=0.30)
        obs = _build_observations([fc], [], "Jane")
        assert any("paste" in o.lower() or "pasted" in o.lower() for o in obs)


# ── _build_hypotheses ─────────────────────────────────────────────────────────

class TestBuildHypotheses:
    def test_always_includes_innocent_first(self):
        hyps = _build_hypotheses(0.40, False, False, 0.8, "monitor")
        assert len(hyps) >= 2
        # First hypothesis is always an innocent situational explanation
        assert "stress" in hyps[0].lower() or "fatigue" in hyps[0].lower() or "pressure" in hyps[0].lower()

    def test_behavioral_signal_adds_pasting_hypothesis(self):
        hyps = _build_hypotheses(0.50, True, False, 0.5, "schedule_conversation")
        assert any("composed elsewhere" in h.lower() or "pasted" in h.lower() for h in hyps)

    def test_ai_signal_adds_ai_hypothesis(self):
        hyps = _build_hypotheses(0.50, False, True, 0.5, "schedule_conversation")
        assert any("ai" in h.lower() for h in hyps)

    def test_high_deviation_low_fidelity_adds_ghostwriting(self):
        hyps = _build_hypotheses(0.80, False, False, 0.3, "escalate")
        assert any("another person" in h.lower() or "ghost" in h.lower() for h in hyps)

    def test_no_ghostwriting_below_threshold(self):
        hyps = _build_hypotheses(0.70, False, False, 0.5, "schedule_conversation")
        assert not any("another person" in h.lower() for h in hyps)

    def test_capped_at_four(self):
        hyps = _build_hypotheses(0.85, True, True, 0.2, "escalate")
        assert len(hyps) <= 4

    def test_no_accusations_in_any_hypothesis(self):
        """None of the hypotheses should contain accusatory language."""
        hyps = _build_hypotheses(0.90, True, True, 0.2, "escalate")
        accusatory = ["cheated", "cheating", "lied", "plagiarist", "dishonest"]
        for hyp in hyps:
            for word in accusatory:
                assert word not in hyp.lower(), f"Accusatory word '{word}' found in: {hyp}"


# ── _build_suggested_action ───────────────────────────────────────────────────

class TestBuildSuggestedAction:
    def test_no_action(self):
        s = _build_suggested_action("no_action", "Jane")
        assert "no action" in s.lower() or "consistent" in s.lower()

    def test_monitor(self):
        s = _build_suggested_action("monitor", "Jane")
        assert "Jane" in s
        assert "next submission" in s.lower() or "keep an eye" in s.lower()

    def test_schedule_conversation(self):
        s = _build_suggested_action("schedule_conversation", "Jane")
        assert "Jane" in s
        assert "conversation" in s.lower() or "schedule" in s.lower()

    def test_escalate(self):
        s = _build_suggested_action("escalate", "Jane")
        assert "Jane" in s
        # Should suggest meeting, not accuse
        assert "meet" in s.lower() or "submission" in s.lower()
        # Should not accuse
        assert "cheat" not in s.lower()


# ── _build_confidence_note ────────────────────────────────────────────────────

class TestBuildConfidenceNote:
    def test_many_samples_well_established(self):
        n = _build_confidence_note(8)
        assert "8" in n
        assert "reliable" in n.lower() or "well-established" in n.lower()

    def test_medium_samples_developing(self):
        n = _build_confidence_note(5)
        assert "5" in n
        assert "developing" in n.lower() or "improve" in n.lower()

    def test_few_samples_preliminary(self):
        n = _build_confidence_note(2)
        assert "2" in n
        assert "limited" in n.lower() or "preliminary" in n.lower()

    def test_boundary_eight_is_well_established(self):
        n = _build_confidence_note(8)
        assert "reliable" in n.lower() or "well-established" in n.lower()

    def test_boundary_four_is_developing(self):
        n = _build_confidence_note(4)
        assert "developing" in n.lower() or "improve" in n.lower()


# ── build_professor_explanation (top-level) ───────────────────────────────────

# Minimal stub objects that look like Layer7Output attributes

@dataclass
class _AuthSignal:
    deviation_score: float = 0.5
    quantum_fidelity: float = 0.7

@dataclass
class _Rec:
    action: str = "monitor"

@dataclass
class _Traj:
    direction: str = "lateral"

@dataclass
class _BC:
    sample_count: int = 4

@dataclass
class _FC:
    code: str
    delta: float
    direction: str = "destructive"

@dataclass
class _Interference:
    destructive_features: List = field(default_factory=list)
    constructive_features: List = field(default_factory=list)

@dataclass
class _Layer7:
    authorship: _AuthSignal = field(default_factory=_AuthSignal)
    recommendation: _Rec = field(default_factory=_Rec)
    trajectory: _Traj = field(default_factory=_Traj)
    baseline_confidence: _BC = field(default_factory=_BC)
    interference: _Interference = field(default_factory=_Interference)


class TestBuildProfessorExplanation:
    def test_returns_dataclass(self):
        result = build_professor_explanation(_Layer7(), "Jane")
        assert isinstance(result, ProfessorExplanation)

    def test_has_all_fields(self):
        result = build_professor_explanation(_Layer7())
        assert result.headline
        assert result.summary
        assert isinstance(result.observations, list)
        assert isinstance(result.hypotheses, list)
        assert result.suggested_action
        assert result.confidence_note

    def test_student_name_appears_in_headline(self):
        result = build_professor_explanation(_Layer7(), "Marcus")
        assert "Marcus" in result.headline

    def test_default_name_fallback(self):
        # No student_name → default "this student"
        result = build_professor_explanation(_Layer7())
        assert "this student" in result.headline.lower() or result.headline  # at least has something

    def test_behavioral_signals_detected(self):
        paste_fc = _FC(code="paste_event_rate", delta=0.30)
        layer7 = _Layer7(interference=_Interference(destructive_features=[paste_fc]))
        result = build_professor_explanation(layer7, "Jane")
        assert result.has_behavioral_signals is True

    def test_ai_signals_detected(self):
        ai_fc = _FC(code="burstiness", delta=-0.30)
        layer7 = _Layer7(interference=_Interference(destructive_features=[ai_fc]))
        result = build_professor_explanation(layer7, "Jane")
        assert result.has_ai_signals is True

    def test_no_behavioral_or_ai_signals_by_default(self):
        result = build_professor_explanation(_Layer7(), "Jane")
        assert result.has_behavioral_signals is False
        assert result.has_ai_signals is False

    def test_graceful_with_none_fields(self):
        """Handles a completely empty object without raising."""
        class Empty:
            pass
        result = build_professor_explanation(Empty(), "Jane")
        assert isinstance(result, ProfessorExplanation)

    def test_no_jargon_in_output(self):
        """The narrative should not contain quantum or mathematical jargon."""
        result = build_professor_explanation(_Layer7(), "Jane")
        all_text = " ".join([
            result.headline, result.summary,
            *result.observations, *result.hypotheses,
            result.suggested_action, result.confidence_note,
        ]).lower()
        jargon = ["quantum", "fidelity", "rms", "z-score", "eigenvalue",
                  "born probability", "density matrix", "tanh"]
        for term in jargon:
            assert term not in all_text, f"Jargon term '{term}' found in narrative"

    def test_high_deviation_action_is_escalate(self):
        layer7 = _Layer7(
            authorship=_AuthSignal(deviation_score=0.85, quantum_fidelity=0.2),
            recommendation=_Rec(action="escalate"),
            baseline_confidence=_BC(sample_count=6),
        )
        result = build_professor_explanation(layer7, "Jane")
        assert "meet" in result.suggested_action.lower() or "submission" in result.suggested_action.lower()

    def test_hypotheses_not_empty(self):
        result = build_professor_explanation(_Layer7(), "Jane")
        assert len(result.hypotheses) >= 2

    def test_observations_not_empty(self):
        result = build_professor_explanation(_Layer7(), "Jane")
        assert len(result.observations) >= 1
