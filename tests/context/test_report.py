"""
tests/context/test_report.py — Phase 6 ScoringReport tests.

Covers: verdict thresholds, confidence levels, anchor-tier consistency
filtering, baseline-cluster label resolution, narrative fragment selection,
and JSON-safe serialisation.
"""

from __future__ import annotations

from typing import Dict, List, Optional

import numpy as np
import pytest

from original.constants import (
    ALL_FEATURE_CODES, FEATURE_DIM, FEATURE_TIER,
    TIER4_CODES, TIER6_CODES, TIER16_CODES,
)
from original.context.manifest import ContextManifest
from original.context.report import (
    CONFIDENCE_LOW_UNDER, CONFIDENCE_MEDIUM_UNDER,
    VERDICT_AUTHENTIC_BELOW, VERDICT_ANOMALOUS_AT_OR_ABOVE,
    ScoringReport,
    _verdict_for, _confidence_for,
    build_report, generate_narrative,
)
from original.quantum.scoring import (
    AuthorshipSignal, BaselineConfidence, DomainSignal,
    InterferenceDecomposition, Layer7Output, RecommendedAction,
    TrajectoryConformance,
)
from original.quantum.state import BaselineSample, StudentState


# ── Test helpers ─────────────────────────────────────────────────────────────

def _make_manifest(
    *,
    submission_id: str = "sub1",
    flags: Optional[List[str]] = None,
    anchor_tiers: Optional[List[int]] = None,
    length_regime: str = "standard",
    citations_present: bool = True,
    cluster_indices: Optional[List[int]] = None,
    anchor_only: bool = False,
) -> ContextManifest:
    return ContextManifest(
        submission_id=submission_id,
        language={"primary": "en", "code_switched": False},
        genre={"primary": "scholarly_essay"},
        topic={"novelty": "low"},
        length_regime=length_regime,
        citations={"citations_present": citations_present},
        composition_mode={"mode": "natural_drafted"},
        weight_modifications={"amplify_codes": [], "attenuate_codes": [], "mute_codes": []},
        anchor_tiers=anchor_tiers if anchor_tiers is not None else [4, 6],
        baseline_match={
            "cluster_indices": cluster_indices if cluster_indices is not None else [0, 1, 2],
            "n_samples":       len(cluster_indices) if cluster_indices is not None else 3,
            "anchor_only":     anchor_only,
        },
        flags=flags or [],
        created_at="2026-05-06T00:00:00Z",
    )


def _make_layer7(
    *,
    deviation_score: float = 0.20,
    effective_sample_count: float = 5.0,
    feature_overrides: Optional[Dict[str, float]] = None,
    baseline_overrides: Optional[Dict[str, float]] = None,
) -> Layer7Output:
    """
    Build a synthetic Layer7Output with controllable divergence score and
    per-feature/per-baseline values so anchor-consistency calculations are
    deterministic.
    """
    feat = {c: 0.5 for c in ALL_FEATURE_CODES}
    base = {c: 0.5 for c in ALL_FEATURE_CODES}
    if feature_overrides:
        feat.update(feature_overrides)
    if baseline_overrides:
        base.update(baseline_overrides)

    return Layer7Output(
        student_id="s",
        submission_id="sub1",
        authorship=AuthorshipSignal(authorship_probability=0.7,
                                     deviation_score=deviation_score),
        trajectory=TrajectoryConformance(direction="lateral", alignment=0.0,
                                          confidence=0.0, adjustment_factor=1.0),
        interference=InterferenceDecomposition(
            total_probability=0.7, constructive_features=[], destructive_features=[],
            broken_entanglements=[], tier_breakdown={}),
        baseline_confidence=BaselineConfidence(
            purity=0.5, sample_count=int(effective_sample_count),
            authenticated_count=int(effective_sample_count),
            effective_sample_count=effective_sample_count,
            trajectory_confidence=0.0),
        domain=DomainSignal(theological_register_score=0.0, register_anomaly=False,
                             confessional_balance="balanced"),
        recommendation=RecommendedAction(action="no_action", confidence=0.8,
                                          rationale=""),
        feature_vector=feat, baseline_vector=base,
    )


def _make_state(n_samples: int = 3) -> StudentState:
    return StudentState(student_id="s", samples=[
        BaselineSample(
            text=f"sample {i}", vector=np.full(FEATURE_DIM, 0.5),
            provenance="verified", auth_weight=1.0,
            assignment=f"assignment_{i}",
        )
        for i in range(n_samples)
    ])


# ══════════════════════════════════════════════════════════════════════════════
# Verdict thresholds
# ══════════════════════════════════════════════════════════════════════════════

class TestVerdict:
    def test_verdict_authentic_below_0_3(self):
        assert _verdict_for(0.0) == "authentic"
        assert _verdict_for(0.15) == "authentic"
        assert _verdict_for(VERDICT_AUTHENTIC_BELOW - 0.001) == "authentic"

    def test_verdict_uncertain_in_middle_range(self):
        # The boundary is `< 0.30`, so 0.30 itself is NOT authentic.
        assert _verdict_for(VERDICT_AUTHENTIC_BELOW) == "uncertain"
        assert _verdict_for(0.5) == "uncertain"
        assert _verdict_for(VERDICT_ANOMALOUS_AT_OR_ABOVE - 0.001) == "uncertain"

    def test_verdict_anomalous_above_0_75(self):
        assert _verdict_for(VERDICT_ANOMALOUS_AT_OR_ABOVE) == "anomalous"
        assert _verdict_for(0.85) == "anomalous"
        assert _verdict_for(1.0) == "anomalous"


# ══════════════════════════════════════════════════════════════════════════════
# Confidence levels
# ══════════════════════════════════════════════════════════════════════════════

class TestConfidence:
    def test_anchor_only_returns_insufficient_data(self):
        layer7 = _make_layer7(effective_sample_count=10.0)
        # anchor_only forces insufficient_data regardless of sample count.
        assert _confidence_for(layer7, anchor_only=True) == "insufficient_data"

    def test_low_below_threshold(self):
        layer7 = _make_layer7(effective_sample_count=2.0)
        assert _confidence_for(layer7, anchor_only=False) == "low"
        # Boundary: CONFIDENCE_LOW_UNDER itself is NOT low (uses `<`).
        layer7_b = _make_layer7(effective_sample_count=float(CONFIDENCE_LOW_UNDER))
        assert _confidence_for(layer7_b, anchor_only=False) == "medium"

    def test_medium_in_middle_range(self):
        layer7 = _make_layer7(effective_sample_count=4.5)
        assert _confidence_for(layer7, anchor_only=False) == "medium"

    def test_high_at_or_above_medium_threshold(self):
        layer7 = _make_layer7(effective_sample_count=float(CONFIDENCE_MEDIUM_UNDER))
        assert _confidence_for(layer7, anchor_only=False) == "high"
        layer7_b = _make_layer7(effective_sample_count=20.0)
        assert _confidence_for(layer7_b, anchor_only=False) == "high"


# ══════════════════════════════════════════════════════════════════════════════
# Anchor-tier consistency scoring
# ══════════════════════════════════════════════════════════════════════════════

class TestAnchorTierScores:
    def test_anchor_scores_only_include_anchor_tiers(self):
        # Manifest anchors [4, 6] — report.anchor_tier_scores must contain
        # ONLY those tier indices, not any others.
        m = _make_manifest(anchor_tiers=[4, 6])
        layer7 = _make_layer7()
        report = build_report(layer7, m, _make_state())
        assert set(report.anchor_tier_scores.keys()) == {4, 6}

    def test_perfect_match_gives_consistency_1(self):
        # When feat == base for all anchor codes, consistency = 1.0.
        m = _make_manifest(anchor_tiers=[4])
        # feat and base both default to 0.5 for all codes — perfect match.
        layer7 = _make_layer7()
        report = build_report(layer7, m, _make_state())
        for tier, score in report.anchor_tier_scores.items():
            assert abs(score - 1.0) < 1e-6, \
                f"tier {tier}: expected 1.0, got {score}"

    def test_max_divergence_gives_consistency_0(self):
        # If submission features are all 0.0 and baseline all 1.0, |delta| = 1
        # for every code → consistency = 0.0.
        feat_zero  = {c: 0.0 for c in TIER4_CODES}
        base_one   = {c: 1.0 for c in TIER4_CODES}
        m = _make_manifest(anchor_tiers=[4])
        layer7 = _make_layer7(feature_overrides=feat_zero,
                               baseline_overrides=base_one)
        report = build_report(layer7, m, _make_state())
        assert report.anchor_tier_scores[4] == 0.0

    def test_skips_tier_with_no_codes(self):
        # Tier 99 has no codes in FEATURE_TIER — should be silently dropped
        # rather than reported as 0 (which would conflate "no signal" with
        # "anomalous").
        m = _make_manifest(anchor_tiers=[4, 99])
        layer7 = _make_layer7()
        report = build_report(layer7, m, _make_state())
        assert 99 not in report.anchor_tier_scores
        assert 4 in report.anchor_tier_scores


# ══════════════════════════════════════════════════════════════════════════════
# Baseline cluster resolution
# ══════════════════════════════════════════════════════════════════════════════

class TestBaselineCluster:
    def test_resolves_assignment_labels(self):
        m = _make_manifest(cluster_indices=[0, 2])
        layer7 = _make_layer7()
        state = _make_state(n_samples=3)
        report = build_report(layer7, m, state)
        assert report.baseline_cluster == ["assignment_0", "assignment_2"]

    def test_falls_back_to_sample_index_when_assignment_blank(self):
        m = _make_manifest(cluster_indices=[0])
        layer7 = _make_layer7()
        # Sample with empty assignment.
        state = StudentState(student_id="s", samples=[
            BaselineSample(text="x", vector=np.full(FEATURE_DIM, 0.5),
                            provenance="verified", auth_weight=1.0,
                            assignment=""),
        ])
        report = build_report(layer7, m, state)
        assert report.baseline_cluster == ["sample_0"]

    def test_anchor_only_yields_empty_cluster(self):
        m = _make_manifest(cluster_indices=[], anchor_only=True)
        layer7 = _make_layer7()
        report = build_report(layer7, m, _make_state())
        assert report.baseline_cluster == []
        assert report.confidence == "insufficient_data"

    def test_skips_out_of_range_indices(self):
        m = _make_manifest(cluster_indices=[0, 99])
        layer7 = _make_layer7()
        state = _make_state(n_samples=2)
        report = build_report(layer7, m, state)
        assert report.baseline_cluster == ["assignment_0"]


# ══════════════════════════════════════════════════════════════════════════════
# Narrative builder
# ══════════════════════════════════════════════════════════════════════════════

class TestNarrative:
    def test_includes_baseline_cluster_size(self):
        m = _make_manifest(cluster_indices=[0, 1, 2])
        layer7 = _make_layer7()
        narr = generate_narrative(m, layer7)
        assert "3 baseline sample(s)" in narr

    def test_mentions_software_mediation_when_flagged(self):
        m = _make_manifest(flags=["software_mediated"])
        layer7 = _make_layer7()
        narr = generate_narrative(m, layer7)
        assert "Tool-cleaning" in narr or "tool-clean" in narr.lower()

    def test_mentions_code_switched_when_flagged(self):
        m = _make_manifest(flags=["code_switched"])
        layer7 = _make_layer7()
        narr = generate_narrative(m, layer7)
        assert "Multilingual" in narr or "multilingual" in narr

    def test_mentions_topic_novelty_when_flagged(self):
        m = _make_manifest(flags=["topic_novelty_high"])
        layer7 = _make_layer7()
        narr = generate_narrative(m, layer7)
        assert "topic" in narr.lower() and "novel" in narr.lower()

    def test_mentions_micro_length_regime(self):
        m = _make_manifest(length_regime="micro")
        layer7 = _make_layer7()
        narr = generate_narrative(m, layer7)
        assert "micro" in narr

    def test_mentions_citations_present_when_true(self):
        m = _make_manifest(citations_present=True)
        layer7 = _make_layer7()
        narr = generate_narrative(m, layer7)
        assert "Citations are present" in narr or "T16" in narr

    def test_mentions_citations_absent_when_false(self):
        m = _make_manifest(citations_present=False)
        layer7 = _make_layer7()
        narr = generate_narrative(m, layer7)
        assert "No citations" in narr

    def test_anchor_only_uses_fallback_opening(self):
        m = _make_manifest(cluster_indices=[], anchor_only=True)
        layer7 = _make_layer7()
        narr = generate_narrative(m, layer7)
        assert "anchor-only fallback" in narr

    def test_confidence_insufficient_when_anchor_only(self):
        m = _make_manifest(cluster_indices=[], anchor_only=True)
        layer7 = _make_layer7(effective_sample_count=10.0)
        narr = generate_narrative(m, layer7)
        # Despite high sample count, anchor_only forces insufficient_data.
        assert "insufficient_data" in narr or "insufficient" in narr.lower()

    def test_includes_verdict_label(self):
        m = _make_manifest()
        # Authentic
        layer7_auth = _make_layer7(deviation_score=0.1)
        assert "authentic" in generate_narrative(m, layer7_auth)
        # Anomalous
        layer7_anom = _make_layer7(deviation_score=0.95)
        assert "anomalous" in generate_narrative(m, layer7_anom)

    def test_deterministic_for_same_input(self):
        m = _make_manifest(flags=["software_mediated"])
        layer7 = _make_layer7()
        n1 = generate_narrative(m, layer7)
        n2 = generate_narrative(m, layer7)
        assert n1 == n2


# ══════════════════════════════════════════════════════════════════════════════
# build_report end-to-end
# ══════════════════════════════════════════════════════════════════════════════

class TestBuildReport:
    def test_full_field_population(self):
        m = _make_manifest(flags=["software_mediated"])
        layer7 = _make_layer7(deviation_score=0.4)
        state = _make_state()
        report = build_report(layer7, m, state)

        assert report.submission_id == "sub1"
        assert abs(report.divergence_score - 0.4) < 1e-9
        assert report.verdict == "uncertain"     # 0.4 is in the middle band
        assert report.confidence == "medium"     # eff=5.0
        assert report.flags == ["software_mediated"]
        assert len(report.baseline_cluster) == 3
        assert len(report.anchor_tier_scores) == 2     # T4, T6
        assert "sub1" in report.narrative
        assert "uncertain" in report.narrative

    def test_to_dict_is_json_safe(self):
        # The anchor_tier_scores dict has int keys internally — to_dict()
        # must convert them to strings so the result is JSON-serialisable.
        m = _make_manifest(anchor_tiers=[4, 6, 8])
        layer7 = _make_layer7()
        report = build_report(layer7, m, _make_state())
        d = report.to_dict()

        import json
        # Should round-trip through JSON without TypeErrors.
        s = json.dumps(d)
        d2 = json.loads(s)
        assert isinstance(d2["anchor_tier_scores"], dict)
        # Keys must be strings.
        for k in d2["anchor_tier_scores"]:
            assert isinstance(k, str)

    def test_accepts_manifest_dict_or_dataclass(self):
        # build_report should tolerate either ContextManifest dataclass or
        # its to_dict() — adapt-pipeline serialises in both forms.
        m_dataclass = _make_manifest()
        m_dict = m_dataclass.to_dict()
        layer7 = _make_layer7()
        state = _make_state()

        r1 = build_report(layer7, m_dataclass, state)
        r2 = build_report(layer7, m_dict, state)

        assert r1.verdict == r2.verdict
        assert r1.confidence == r2.confidence
        assert r1.anchor_tier_scores == r2.anchor_tier_scores


# ══════════════════════════════════════════════════════════════════════════════
# Pydantic schema interop
# ══════════════════════════════════════════════════════════════════════════════

class TestPydanticInterop:
    def test_to_dict_matches_pydantic_model(self):
        from original.schemas import ScoringReportOut

        m = _make_manifest(flags=["software_mediated", "topic_novelty_high"])
        layer7 = _make_layer7(deviation_score=0.55)
        report = build_report(layer7, m, _make_state())
        # Pydantic model should validate the dict directly.
        pyd = ScoringReportOut(**report.to_dict())
        assert pyd.submission_id == report.submission_id
        assert pyd.verdict == report.verdict
        assert pyd.confidence == report.confidence
        # anchor_tier_scores: ints → str conversion preserved.
        assert set(pyd.anchor_tier_scores.keys()) == {"4", "6"}
