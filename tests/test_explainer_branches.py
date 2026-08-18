"""
tests/test_explainer_branches.py — original/explainer.py, the plain-English
professor explanation layer.

No dedicated test file existed for this module — it's exercised indirectly
via ``original/routers/_shared.py`` in various API-level tests, which is why
the module already showed ~75% line coverage before this file existed. These
are direct unit tests against ``explain()`` (and its ``_delta_intensity``
helper) with minimal, hand-built ``Layer7Output`` instances, table-driven
over the score/flag combinations the indirect API coverage doesn't happen to
exercise: the "slightly"/"marginally" delta-intensity bands, the mid-range
deviation-score bands used when there are no destructive features, and the
AI-likelihood elevated/strong report-only branch.
"""

from __future__ import annotations

from original.ai_likelihood import AiIndicator, AiLikelihoodResult
from original.explainer import _delta_intensity, explain
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


def _make_result(
    *,
    action: str = "no_action",
    deviation_score: float = 0.1,
    destructive: list | None = None,
    ai_likelihood=None,
) -> Layer7Output:
    result = Layer7Output(
        student_id="s1",
        submission_id="sub1",
        authorship=AuthorshipSignal(authorship_probability=0.9, deviation_score=deviation_score),
        trajectory=TrajectoryConformance(
            direction="stable", alignment=0.5, confidence=0.5, adjustment_factor=1.0
        ),
        interference=InterferenceDecomposition(
            total_probability=1.0,
            constructive_features=[],
            destructive_features=destructive or [],
            broken_entanglements=[],
            tier_breakdown={},
        ),
        baseline_confidence=BaselineConfidence(
            purity=0.9,
            sample_count=5,
            authenticated_count=3,
            effective_sample_count=5.0,
            trajectory_confidence=0.8,
        ),
        domain=DomainSignal(
            theological_register_score=0.5, register_anomaly=False, confessional_balance="balanced"
        ),
        recommendation=RecommendedAction(action=action, confidence=0.8, rationale="r"),
        feature_vector={},
        baseline_vector={},
    )
    if ai_likelihood is not None:
        result.ai_likelihood = ai_likelihood
    return result


# ── _delta_intensity: the two unexercised bands ──────────────────────────────


def test_delta_intensity_slightly_band():
    assert _delta_intensity(0.10) == "slightly higher than usual"


def test_delta_intensity_marginally_band():
    assert _delta_intensity(-0.02) == "marginally lower than usual"


def test_delta_intensity_notably_band():
    assert _delta_intensity(0.20) == "notably higher than usual"


# ── explain(): score-based reason, mid/high deviation bands ──────────────────
# (Only reached when there are no destructive features — the "minor
# variation" / "notable deviation" / "significant deviation" bands.)


def test_explain_score_based_reason_minor_variation_band():
    result = _make_result(deviation_score=0.45, destructive=[])
    out = explain(result)
    assert any("minor variation" in r for r in out["top_reasons"])


def test_explain_score_based_reason_notable_deviation_band():
    result = _make_result(deviation_score=0.60, destructive=[])
    out = explain(result)
    assert any("notable deviation" in r for r in out["top_reasons"])


def test_explain_score_based_reason_significant_deviation_band():
    result = _make_result(deviation_score=0.90, destructive=[])
    out = explain(result)
    assert any("significant deviation" in r for r in out["top_reasons"])


# ── explain(): AI-likelihood elevated/strong branch (report-only) ───────────


def test_explain_ai_likelihood_elevated_with_indicator_appends_reason():
    indicator = AiIndicator(code="burstiness", label="Vocabulary bursts", z=3.2, direction="higher")
    ai_like = AiLikelihoodResult(
        probability=0.8,
        band="elevated",
        model_version="v1",
        trained_on="corpus",
        top_indicators=[indicator],
    )
    result = _make_result(ai_likelihood=ai_like)
    out = explain(result)
    joined = " ".join(out["top_reasons"]).lower()
    assert "vocabulary bursts is unusually high" in joined
    assert "ai-generated text" in joined


def test_explain_ai_likelihood_strong_without_indicators_uses_generic_reason():
    ai_like = AiLikelihoodResult(
        probability=0.95,
        band="strong",
        model_version="v1",
        trained_on="corpus",
        top_indicators=[],
    )
    result = _make_result(ai_likelihood=ai_like)
    out = explain(result)
    assert any("overall statistical patterns resemble" in r for r in out["top_reasons"])


def test_explain_ai_likelihood_low_band_is_not_surfaced():
    """A `low` band must never append a reason — it's the majority case and
    must stay silent, not just 'not elevated/strong'."""
    ai_like = AiLikelihoodResult(
        probability=0.1,
        band="low",
        model_version="v1",
        trained_on="corpus",
        top_indicators=[AiIndicator(code="x", label="X", z=0.5, direction="higher")],
    )
    result = _make_result(deviation_score=0.1, ai_likelihood=ai_like)
    out = explain(result)
    assert not any("ai-generated" in r.lower() for r in out["top_reasons"])


# ── Sanity: at least one destructive-feature path is exercised directly ─────


def test_explain_uses_destructive_feature_plain_name():
    feature = FeatureContribution(
        code="burstiness",
        name="Burstiness",
        tier=7,
        contribution=-0.4,
        direction="destructive",
        baseline_value=0.5,
        submission_value=0.9,
        delta=0.4,
    )
    result = _make_result(action="monitor", deviation_score=0.5, destructive=[feature])
    out = explain(result)
    assert any("vocabulary bursts" in r for r in out["top_reasons"])


def test_explain_ghostwriting_signal_appends_note_to_summary():
    """A broken entanglement whose label mentions ghostwriting must both set
    ``ghostwriting_signal`` True and append the note to the summary."""
    anomaly = EntanglementAnomaly(
        feature_a="signal_verb_entropy",
        feature_b="source_loyalty_index",
        tier_a=16,
        tier_b=16,
        expected_correlation=0.6,
        observed_product=0.05,
        anomaly_score=0.9,
        label="Possible ghostwriting signature (T16 citation fingerprint mismatch)",
    )
    result = _make_result(action="escalate", deviation_score=0.9)
    result.interference.broken_entanglements = [anomaly]
    out = explain(result)
    assert out["ghostwriting_signal"] is True
    assert "ghostwriting signal detected" in out["summary"]
