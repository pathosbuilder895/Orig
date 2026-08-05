"""Live pilot API contract for report-only longitudinal analysis."""

from __future__ import annotations


def test_score_request_date_is_optional_and_backward_compatible():
    from original.schemas import ScoreSubmissionRequest

    old = ScoreSubmissionRequest(text="An ordinary submission.")
    dated = ScoreSubmissionRequest(text="A dated submission.", submitted_at="2025-10-01")
    assert old.submitted_at == ""
    assert dated.submitted_at == "2025-10-01"


def test_drift_analysis_response_shape_accepts_internal_payload():
    from original.quantum.longitudinal import DriftAnalysis
    from original.schemas import DriftAnalysisOut

    internal = DriftAnalysis(
        eligible=True,
        reason=None,
        selected_model="constant",
        historical_deviation=0.2,
        predicted_current_deviation=0.2,
        drift_relief=0.0,
        trend_confidence=0.0,
        predictive_improvement=-0.1,
        sample_count=6,
        dated_sample_count=6,
        span_days=180,
        extrapolation_days=0,
        change_point_index=None,
        change_point_evidence=None,
        interpretation="stable_consistent",
    )
    response = DriftAnalysisOut(**internal.to_dict())
    assert response.model_version == "longitudinal-ridge-v1"
    assert response.interpretation == "stable_consistent"


def test_trend_aware_typicality_response_shape_accepts_internal_payload():
    from original.quantum.longitudinal import TrendAwareTypicality
    from original.schemas import TrendAwareTypicalityOut

    internal = TrendAwareTypicality(
        eligible=True,
        reason=None,
        p_far=0.5,
        p_central=0.5,
        band="no_action",
        loo_n=8,
        submission_deviation=0.3,
        selected_model="gradual_drift",
    )
    response = TrendAwareTypicalityOut(**internal.to_dict())
    assert response.model_version == "longitudinal-typicality-v1"
    assert response.band == "no_action"
