"""
tests/test_schemas.py — Pydantic schema round-trip coverage (WS-7 §7.2, S9).

WS-7's audit flags api.py's `_to_response(r, arc=None, report=None)` as "the
load-bearing dataclass→pydantic mapper... untyped" and recommends guarding
its `report=None`/`arc=None` defaulting path with a round-trip test:

    Layer7Output → asdict → model_validate → response

i.e. build a `Layer7OutputResponse` directly from `dataclasses.asdict()` of
the internal `Layer7Output`/`TensionArcResult` dataclasses (bypassing
`_to_response`'s hand-rolled field copying) and confirm nothing is silently
dropped. Writing this test surfaced several fields that `_to_response`
silently dropped at the time (`AuthorshipSignal.quantum_fidelity`,
`AuthorshipSignal.fidelity_conformal_pvalue`,
`EntanglementAnomaly.expected_correlation`/`observed_product`,
`TensionArcResult.paragraph_arcs`; `BaselineConfidence.von_neumann_entropy`
was also on that list but has since been wired up in `_to_response`) —
schemas.py's response models were
extended (with defaults, so existing `_to_response` call sites still
construct fine) to cover them. This file does not modify or call
`_to_response` itself; that wiring is a later, separate pass.
"""

from __future__ import annotations

import dataclasses

import pytest

from original.ai_likelihood import AiIndicator, AiLikelihoodResult
from original.quantum.scoring import (
    AuthorshipSignal,
    BaselineConfidence,
    DomainSignal,
    EntanglementAnomaly,
    FeatureContribution,
    InterferenceDecomposition,
    Layer7Output,
    RecommendedAction,
    TrajectoryConformance,
)
from original.routers._shared import _to_response
from original.schemas import Layer7OutputResponse
from original.tension_arc import ParagraphArc, SentenceTension, TensionArcResult


def _sentence(i: int) -> SentenceTension:
    return SentenceTension(
        index=i,
        text=f"Sentence {i}.",
        syntactic=0.4,
        logical=0.3,
        cohesion=0.2,
        total=0.3,
        move_type="Q",
    )


def _paragraph_arc() -> ParagraphArc:
    return ParagraphArc(
        index=0,
        sentences=[_sentence(0), _sentence(1)],
        peak_count=1,
        resolved_peaks=1,
        resolution_ratio=1.0,
        mean_tension=0.3,
        max_tension=0.4,
    )


def _tension_arc_result() -> TensionArcResult:
    return TensionArcResult(
        tension_series=[0.1, 0.2, 0.3],
        paragraph_arcs=[_paragraph_arc()],
        resolution_ratio_mean=0.8,
        resolution_ratio_std=0.1,
        catastrophe_index=0.05,
        mean_tension=0.2,
        max_tension=0.35,
        authenticity_signal=0.9,
        arc_flag="authentic",
        arc_flag_reason="resolution ratio within authentic band",
    )


def _feature_contribution(code: str, direction: str) -> FeatureContribution:
    return FeatureContribution(
        code=code,
        name=code.replace("_", " ").title(),
        tier=3,
        contribution=0.05 if direction == "constructive" else -0.05,
        direction=direction,
        baseline_value=0.5,
        submission_value=0.55,
        delta=0.05,
    )


def _entanglement_anomaly() -> EntanglementAnomaly:
    return EntanglementAnomaly(
        feature_a="lexical_diversity",
        feature_b="syntactic_complexity",
        tier_a=2,
        tier_b=3,
        expected_correlation=0.6,
        observed_product=0.1,
        anomaly_score=0.5,
        label="T2-T3 discourse-rhetorical",
    )


def _ai_likelihood_result() -> AiLikelihoodResult:
    return AiLikelihoodResult(
        probability=0.72,
        band="elevated",
        model_version="v1",
        trained_on="corpus-2026-06",
        top_indicators=[
            AiIndicator(code="burstiness", label="Burstiness", z=2.1, direction="lower"),
        ],
    )


def _full_layer7_output() -> Layer7Output:
    """A Layer7Output with every optional field populated (non-default path)."""
    return Layer7Output(
        student_id="student-1",
        submission_id="sub-1",
        authorship=AuthorshipSignal(
            authorship_probability=0.62,
            deviation_score=0.31,
            quantum_fidelity=0.87,
            fidelity_conformal_pvalue=0.043,
            llr_deviation_score=0.28,
        ),
        trajectory=TrajectoryConformance(
            direction="stable", alignment=0.9, confidence=0.8, adjustment_factor=1.0
        ),
        interference=InterferenceDecomposition(
            total_probability=1.0,
            constructive_features=[_feature_contribution("lexical_diversity", "constructive")],
            destructive_features=[_feature_contribution("syntactic_complexity", "destructive")],
            broken_entanglements=[_entanglement_anomaly()],
            tier_breakdown={"tier_2": 0.4, "tier_3": 0.6},
        ),
        baseline_confidence=BaselineConfidence(
            purity=0.95,
            sample_count=6,
            authenticated_count=5,
            effective_sample_count=4.5,
            trajectory_confidence=0.8,
            von_neumann_entropy=0.12,
        ),
        domain=DomainSignal(
            theological_register_score=0.4, register_anomaly=False, confessional_balance="balanced"
        ),
        recommendation=RecommendedAction(
            action="no_action", confidence=0.9, rationale="Well within baseline."
        ),
        feature_vector={"lexical_diversity": 0.55},
        baseline_vector={"lexical_diversity": 0.5},
        catastrophic_drift=False,
        catastrophic_drift_rms_z=1.2,
        tension_arc=_tension_arc_result(),
        context_manifest=None,
        ai_likelihood=_ai_likelihood_result(),
    )


def _minimal_layer7_output() -> Layer7Output:
    """
    The Phase-1 byte-identical default path: tension_arc, context_manifest,
    and ai_likelihood all None (the "arc=None"/"report=None" defaulting path
    WS-7 calls out as where a drift bug would hide).
    """
    return Layer7Output(
        student_id="student-2",
        submission_id="sub-2",
        authorship=AuthorshipSignal(authorship_probability=0.5, deviation_score=0.1),
        trajectory=TrajectoryConformance(
            direction="stable", alignment=0.5, confidence=0.5, adjustment_factor=1.0
        ),
        interference=InterferenceDecomposition(
            total_probability=1.0,
            constructive_features=[],
            destructive_features=[],
            broken_entanglements=[],
            tier_breakdown={},
        ),
        baseline_confidence=BaselineConfidence(
            purity=1.0,
            sample_count=1,
            authenticated_count=1,
            effective_sample_count=1.0,
            trajectory_confidence=0.5,
        ),
        domain=DomainSignal(
            theological_register_score=0.0, register_anomaly=False, confessional_balance="balanced"
        ),
        recommendation=RecommendedAction(action="no_action", confidence=0.5, rationale=""),
        feature_vector={},
        baseline_vector={},
    )


def _make_layer7_output(
    typicality_p_far: float | None = None,
    typicality_p_central: float | None = None,
    typicality_band: str | None = None,
    typicality_n: int = 0,
    trend_aware_typicality=None,
    topic_inflation_applied: bool = False,
    topic_distance: float | None = None,
    topic_mean_inflation: float | None = None,
    deviation_score_inflated: float | None = None,
    characteristic_weighting_applied: bool = False,
    characteristic_mode: str | None = None,
    characteristic_factor_dispersion: float | None = None,
    characteristic_rms_z_preview: float | None = None,
    characteristic_deviation_preview: float | None = None,
) -> Layer7Output:
    """
    Factory for Layer7Output with customizable typicality, topic-inflation
    and characteristic-weighting fields. All other fields use minimal
    (default) values.
    """
    return Layer7Output(
        student_id="student-test",
        submission_id="sub-test",
        authorship=AuthorshipSignal(authorship_probability=0.5, deviation_score=0.1),
        trajectory=TrajectoryConformance(
            direction="stable", alignment=0.5, confidence=0.5, adjustment_factor=1.0
        ),
        interference=InterferenceDecomposition(
            total_probability=1.0,
            constructive_features=[],
            destructive_features=[],
            broken_entanglements=[],
            tier_breakdown={},
        ),
        baseline_confidence=BaselineConfidence(
            purity=1.0,
            sample_count=1,
            authenticated_count=1,
            effective_sample_count=1.0,
            trajectory_confidence=0.5,
        ),
        domain=DomainSignal(
            theological_register_score=0.0, register_anomaly=False, confessional_balance="balanced"
        ),
        recommendation=RecommendedAction(action="no_action", confidence=0.5, rationale=""),
        feature_vector={},
        baseline_vector={},
        typicality_p_far=typicality_p_far,
        typicality_p_central=typicality_p_central,
        typicality_band=typicality_band,
        typicality_n=typicality_n,
        trend_aware_typicality=trend_aware_typicality,
        topic_inflation_applied=topic_inflation_applied,
        topic_distance=topic_distance,
        topic_mean_inflation=topic_mean_inflation,
        deviation_score_inflated=deviation_score_inflated,
        characteristic_weighting_applied=characteristic_weighting_applied,
        characteristic_mode=characteristic_mode,
        characteristic_factor_dispersion=characteristic_factor_dispersion,
        characteristic_rms_z_preview=characteristic_rms_z_preview,
        characteristic_deviation_preview=characteristic_deviation_preview,
    )


def test_layer7_output_dataclass_fields_all_have_response_counterparts():
    """Every Layer7Output dataclass field must exist on Layer7OutputResponse."""
    result = _full_layer7_output()
    response = Layer7OutputResponse.model_validate(dataclasses.asdict(result))
    for f in dataclasses.fields(result):
        assert hasattr(response, f.name), (
            f"Layer7Output.{f.name} has no Layer7OutputResponse counterpart — "
            "a field would be silently dropped on the way to the API response."
        )


def test_layer7_output_round_trip_full_no_dropped_fields():
    """
    Full round trip with every optional branch populated. Guards the fields
    that _to_response's hand-rolled copying silently drops today: this
    exercises schemas.py's models directly (not _to_response), so it proves
    schemas.py itself is a complete, accurate typed contract.
    """
    result = _full_layer7_output()
    response = Layer7OutputResponse.model_validate(dataclasses.asdict(result))

    assert response.student_id == result.student_id
    assert response.submission_id == result.submission_id

    # AuthorshipSignal — quantum_fidelity/fidelity_conformal_pvalue are the
    # fields _to_response never copies into AuthorshipSignalOut today.
    assert response.authorship.authorship_probability == result.authorship.authorship_probability
    assert response.authorship.deviation_score == result.authorship.deviation_score
    assert response.authorship.quantum_fidelity == result.authorship.quantum_fidelity
    assert (
        response.authorship.fidelity_conformal_pvalue == result.authorship.fidelity_conformal_pvalue
    )
    assert response.authorship.llr_deviation_score == result.authorship.llr_deviation_score

    # BaselineConfidence — von_neumann_entropy was dropped by _to_response when
    # this test was written; it's since been wired up (api.py:2294), so this
    # now asserts the round-trip rather than documenting a gap.
    assert response.baseline_confidence.von_neumann_entropy == pytest.approx(0.12)

    # EntanglementAnomaly — expected_correlation/observed_product are dropped
    # by _to_response today.
    anomaly = response.interference.broken_entanglements[0]
    src_anomaly = result.interference.broken_entanglements[0]
    assert anomaly.expected_correlation == src_anomaly.expected_correlation
    assert anomaly.observed_product == src_anomaly.observed_product
    assert anomaly.anomaly_score == src_anomaly.anomaly_score

    # TensionArcResult.paragraph_arcs is dropped by _to_response today (only
    # the summary scalars are surfaced).
    assert response.tension_arc is not None
    assert len(response.tension_arc.paragraph_arcs) == 1
    para = response.tension_arc.paragraph_arcs[0]
    assert para.peak_count == 1
    assert len(para.sentences) == 2
    assert para.sentences[0].move_type == "Q"

    # AI-likelihood — already fully covered, sanity-check it survives too.
    assert response.ai_likelihood is not None
    assert response.ai_likelihood.probability == pytest.approx(0.72)
    assert response.ai_likelihood.top_indicators[0].code == "burstiness"

    # context_manifest stayed None (not populated in this fixture).
    assert response.context_manifest is None


def test_layer7_output_round_trip_minimal_defaults_path():
    """
    The flags-OFF / Phase-1 default path: tension_arc, context_manifest, and
    ai_likelihood are all None. Confirms the round trip degrades cleanly
    (no validation error, optional fields land as None) rather than hiding
    a drift bug behind the defaulting branch, per WS-7's explicit call-out.
    """
    result = _minimal_layer7_output()
    response = Layer7OutputResponse.model_validate(dataclasses.asdict(result))

    assert response.tension_arc is None
    assert response.context_manifest is None
    assert response.ai_likelihood is None
    assert response.interference.broken_entanglements == []
    assert response.authorship.quantum_fidelity == 0.0
    assert response.authorship.fidelity_conformal_pvalue is None
    assert response.baseline_confidence.von_neumann_entropy == 0.0
    # report/human_explanation are not part of Layer7Output at all (built
    # separately by _to_response) — should default to None, not error.
    assert response.report is None
    assert response.human_explanation is None


def test_typicality_fields_round_trip_when_present():
    """Typicality fields copy through _to_response() when populated."""
    result = _make_layer7_output(
        typicality_p_far=0.42,
        typicality_p_central=0.58,
        typicality_band="no_action",
        typicality_n=7,
    )
    response = _to_response(result)
    assert response.typicality_p_far == 0.42
    assert response.typicality_p_central == 0.58
    assert response.typicality_band == "no_action"
    assert response.typicality_n == 7


def test_characteristic_weighting_fields_round_trip_through_to_response():
    """All five CHARACTERISTIC_WEIGHTS audit fields copy through
    _to_response() when populated, and keep their dataclass defaults when
    absent.

    _to_response is a HAND-ROLLED converter: nothing derives its field list
    from Layer7Output, so the five getattr() copies can be deleted without
    any other test noticing. (Mutation-tested: deleting them left 86 tests
    green.) test_layer7_output_dataclass_fields_all_have_response_counterparts
    only proves the Pydantic model HAS the fields, not that the converter
    fills them. Without this test a refactor can silently remove the entire
    shadow surface from the API response while CI stays green -- and the
    shadow soak CLAUDE.md prescribes would then collect nothing at all.
    Same contract, and same reason, as
    test_typicality_fields_round_trip_when_present above.
    """
    result = _make_layer7_output(
        characteristic_weighting_applied=True,
        characteristic_mode="shadow",
        characteristic_factor_dispersion=0.163,
        characteristic_rms_z_preview=1.21,
        characteristic_deviation_preview=0.64,
    )
    response = _to_response(result)
    assert response.characteristic_weighting_applied is True
    assert response.characteristic_mode == "shadow"
    assert response.characteristic_factor_dispersion == 0.163
    assert response.characteristic_rms_z_preview == 1.21
    assert response.characteristic_deviation_preview == 0.64

    absent = _to_response(_make_layer7_output())
    assert absent.characteristic_weighting_applied is False
    assert absent.characteristic_mode is None
    assert absent.characteristic_factor_dispersion is None
    assert absent.characteristic_rms_z_preview is None
    assert absent.characteristic_deviation_preview is None


def test_trend_aware_typicality_round_trips_through_to_response():
    """trend_aware_typicality copies through _to_response() when populated,
    and stays None when absent -- mirrors drift_analysis's existing coverage
    (both share the same report-only contract, see original/quantum/
    longitudinal.py's TrendAwareTypicality)."""
    from original.quantum.longitudinal import TrendAwareTypicality

    reading = TrendAwareTypicality(
        eligible=True,
        reason=None,
        p_far=0.4,
        p_central=0.6,
        band="no_action",
        loo_n=7,
        submission_deviation=0.25,
        selected_model="constant",
    )
    result = _make_layer7_output(trend_aware_typicality=reading)
    response = _to_response(result)
    assert response.trend_aware_typicality is not None
    assert response.trend_aware_typicality.band == "no_action"
    assert response.trend_aware_typicality.selected_model == "constant"
    assert response.trend_aware_typicality.loo_n == 7

    absent = _to_response(_make_layer7_output())
    assert absent.trend_aware_typicality is None


def test_typicality_fields_are_none_when_not_computed():
    """Typicality fields default to None/0 when not computed."""
    result = _make_layer7_output()  # typicality_band defaults to None
    response = _to_response(result)
    assert response.typicality_p_far is None
    assert response.typicality_p_central is None
    assert response.typicality_band is None
    assert response.typicality_n == 0


def test_topic_inflation_fields_round_trip_when_present():
    """
    Finding 4 (2026-08-06 review): deviation_score_inflated, topic_distance,
    topic_mean_inflation, and topic_inflation_applied were computed on
    Layer7Output but silently dropped by _to_response(), making shadow
    mode's entire output unreachable outside unit tests even though
    CLAUDE.md instructs operators to "run shadow first". Same completeness-
    gap shape and same getattr(..., default) fix as the typicality fields
    covered immediately above.
    """
    result = _make_layer7_output(
        topic_inflation_applied=True,
        topic_distance=0.42,
        topic_mean_inflation=1.15,
        deviation_score_inflated=0.37,
    )
    response = _to_response(result)
    assert response.topic_inflation_applied is True
    assert response.topic_distance == pytest.approx(0.42)
    assert response.topic_mean_inflation == pytest.approx(1.15)
    assert response.deviation_score_inflated == pytest.approx(0.37)


def test_topic_inflation_fields_are_default_when_not_computed():
    """Topic-inflation fields default to False/None when the flag is off."""
    result = _make_layer7_output()  # all topic_* fields default
    response = _to_response(result)
    assert response.topic_inflation_applied is False
    assert response.topic_distance is None
    assert response.topic_mean_inflation is None
    assert response.deviation_score_inflated is None
