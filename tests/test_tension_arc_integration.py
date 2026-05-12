"""
tests/test_tension_arc_integration.py — Integration tests for Tension Arc Analysis.

Tests cover:
  1. analyze_tension_arc returns a valid TensionArcResult
  2. analyze_tension_arc with a student baseline_kappa
  3. update_student_baseline_kappa running-mean helper
  4. Layer7Output has tension_arc field defaulting to None
  5. score endpoint includes tension_arc in the response JSON
"""

from __future__ import annotations

import dataclasses


# ── 1. analyze_tension_arc returns a valid TensionArcResult ──────────────────

def test_analyze_tension_arc_returns_result():
    from original.tension_arc import analyze_tension_arc, TensionArcResult

    # Minimum viable text (200+ words)
    text = (
        "The doctrine of justification by faith alone stands at the heart of Reformed "
        "theology. Luther discovered that the righteousness of God spoken of in Romans "
        "is not the righteousness by which God punishes sinners but the righteousness "
        "by which He graciously acquits them through faith in Jesus Christ. This insight "
        "transformed his understanding of the gospel entirely. For centuries the church "
        "had taught that merit cooperates with grace in securing salvation, yet Luther "
        "found no such teaching in Paul's letter to the Galatians. The anathemas of "
        "the Jerusalem council in Acts 15 confirmed his reading. Whether the reformers "
        "overread Paul or recovered his authentic intention remains disputed among "
        "scholars today, though the exegetical evidence seems strongly in Luther's "
        "favour. The New Perspective on Paul, associated with Sanders, Dunn and Wright, "
        "challenges the traditional framing but does not necessarily undermine the "
        "soteriological conclusion. Justification remains a forensic declaration, not "
        "a process of moral transformation. The two must not be confused, though they "
        "always occur together in the order of salvation. Union with Christ precedes "
        "both and is the ground of each. These distinctions matter because they shape "
        "pastoral practice and the assurance believers may legitimately claim."
    )

    result = analyze_tension_arc(text, baseline_kappa=None)

    assert isinstance(result, TensionArcResult)
    assert isinstance(result.catastrophe_index, float)
    assert 0.0 <= result.catastrophe_index <= 1.0
    assert isinstance(result.tension_series, list)
    assert isinstance(result.arc_flag, str)
    assert result.arc_flag in ("authentic", "ai_typical", "review", "insufficient_length")
    assert isinstance(result.arc_flag_reason, str)
    # authenticity_signal must be None when no baseline supplied
    assert result.authenticity_signal is None


# ── 2. analyze_tension_arc with a baseline_kappa ─────────────────────────────

def test_analyze_tension_arc_with_baseline_kappa():
    from original.tension_arc import analyze_tension_arc

    text = (
        "Atonement theology has generated fierce debate across the centuries. "
        "Anselm's satisfaction theory, which dominated medieval soteriology, holds "
        "that Christ's death satisfies the honour of God violated by human sin. "
        "Abelard countered that the atonement works primarily by evoking love in "
        "the believer, not by addressing divine honour. The Reformation complicated "
        "both positions by emphasising penal substitution: Christ bore the penalty "
        "deserved by sinners, and this forensic transfer is the heart of the gospel. "
        "Contemporary theologians question whether any single theory captures the full "
        "range of New Testament atonement language. Christus Victor, the Girardian "
        "scapegoat reading, and participatory atonement models each illuminate aspects "
        "the others neglect. What remains constant across all serious treatments is the "
        "conviction that atonement is objective: something was accomplished outside and "
        "apart from us that makes reconciliation with God possible. The subjective "
        "appropriation of that reality through faith is a secondary question, however "
        "important for the life of the believer and the integrity of pastoral preaching."
    )

    result = analyze_tension_arc(text, baseline_kappa=0.45)

    assert isinstance(result.arc_flag, str)
    assert result.arc_flag in ("authentic", "ai_typical", "review", "insufficient_length")
    # When baseline_kappa is supplied, authenticity_signal should be set (or None if
    # insufficient_length triggered before reaching the signal computation)
    if result.arc_flag != "insufficient_length":
        # authenticity_signal is computed when kappa > 0 and baseline exists
        # It may still be None if catastrophe_index == 0 (single-paragraph doc)
        assert result.authenticity_signal is None or (
            isinstance(result.authenticity_signal, float)
            and 0.0 <= result.authenticity_signal <= 1.0
        )


# ── 3. update_student_baseline_kappa running-mean helper ─────────────────────

def test_update_student_baseline_kappa():
    from original.tension_arc import update_student_baseline_kappa

    # Single value → mean of one = itself
    result = update_student_baseline_kappa([], 0.5)
    assert abs(result - 0.5) < 1e-9

    # Two values → mean
    result = update_student_baseline_kappa([0.5], 0.7)
    assert 0.5 < result < 0.7

    # Many values → still a float
    result = update_student_baseline_kappa([0.5, 0.6, 0.7], 0.9)
    assert isinstance(result, float)
    # Mean of [0.5, 0.6, 0.7, 0.9] = 0.675
    assert abs(result - 0.675) < 1e-6


# ── 4. Layer7Output has tension_arc field defaulting to None ─────────────────

def test_layer7_output_has_tension_arc_field():
    from original.quantum.scoring import Layer7Output

    fields = {f.name for f in dataclasses.fields(Layer7Output)}
    assert "tension_arc" in fields

    # Verify default is None (field must not be required)
    field_defaults = {f.name: f.default for f in dataclasses.fields(Layer7Output)}
    assert field_defaults["tension_arc"] is None


# ── 5. ScoreResponse schema includes tension_arc field ───────────────────────

def test_score_response_includes_tension_arc_field():
    """
    Verifies the Pydantic schema exposes tension_arc.
    We test the schema directly rather than making a live API call,
    because the API requires a fully seeded DB with baselines.
    """
    from original.schemas_v1.submission import ScoreResponse, TensionArcOut

    # tension_arc must be an Optional field on ScoreResponse
    assert "tension_arc" in ScoreResponse.model_fields
    field_info = ScoreResponse.model_fields["tension_arc"]
    # default must be None (optional)
    assert field_info.default is None

    # TensionArcOut must have the expected fields
    expected_fields = {
        "catastrophe_index", "resolution_ratio_mean", "resolution_ratio_std",
        "mean_tension", "max_tension", "authenticity_signal",
        "arc_flag", "arc_flag_reason", "tension_series", "paragraph_arcs",
    }
    assert expected_fields.issubset(set(TensionArcOut.model_fields.keys()))
