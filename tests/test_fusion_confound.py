import pytest

from validation.fusion_confound.analyze import analyze_rows
from validation.fusion_confound.synthetic import report as synthetic_report


def test_recovers_baseline_volume_slope_controlling_reference_count():
    rows = []
    for baseline in range(3, 49):
        references = 8 + baseline % 5
        compression = 0.806 - 0.0016 * baseline + 0.002 * references
        fused = 0.2 + 0.4 * compression + 0.001 * references
        rows.append(
            {
                "channels": {"compression": compression},
                "fused_log_odds": fused,
                "baseline_samples": baseline,
                "reference_profiles": references,
                "band": "inconclusive",
            }
        )
    report = analyze_rows(rows)
    assert report["verdict"] == "measured"
    assert report["compression_channel"]["controls_reference_profiles"] is True
    assert report["compression_channel"]["baseline_slope"] == pytest.approx(-0.0016)
    assert report["compression_channel"]["implied_shift_3_to_30"] == pytest.approx(-0.0432)
    assert report["fused_log_odds"]["baseline_slope"] < 0
    low, high = report["compression_channel"]["baseline_slope_ci95"]
    assert low <= report["compression_channel"]["baseline_slope"] <= high


def test_abstains_loudly_when_rows_are_thin():
    report = analyze_rows([{"abstain_reason": "thin_reference"}])
    assert report["verdict"] == "uninformative"
    assert report["abstain_reasons"] == {"thin_reference": 1}


def test_constant_reference_count_is_absorbed_by_intercept():
    # The shipped fused artifact is calibrated at exactly 8 references
    # (fusion/peers.py: N_REFERENCES = 8), so real successful rows commonly
    # carry no variation in this control — retaining it anyway would make
    # the regression rank-deficient rather than merely uninformative.
    rows = [
        {
            "channels": {"compression": 0.8 - baseline * 0.002},
            "fused_log_odds": baseline * 0.01,
            "baseline_samples": baseline,
            "reference_profiles": 8,
            "band": "inconclusive",
        }
        for baseline in (3, 6, 12, 24, 30, 48)
    ]
    report = analyze_rows(rows)
    compression = report["compression_channel"]
    assert compression["controls_reference_profiles"] is False
    assert compression["reference_profiles_coefficient"] is None
    assert compression["baseline_slope"] == pytest.approx(-0.002)


def test_threshold_gap_context_is_optional():
    rows = []
    for baseline in range(3, 49):
        references = 8 + baseline % 5
        compression = 0.806 - 0.0016 * baseline + 0.002 * references
        rows.append(
            {
                "channels": {"compression": compression},
                "fused_log_odds": 0.2 + 0.4 * compression,
                "baseline_samples": baseline,
                "reference_profiles": references,
                "band": "inconclusive",
            }
        )
    without = analyze_rows(rows)
    assert "thresholds" not in without

    with_gap = analyze_rows(rows, threshold_fa5=1.5, threshold_fa1=2.9)
    assert with_gap["thresholds"] == {"fa5": 1.5, "fa1": 2.9, "gap": pytest.approx(1.4)}
    assert "shift_3_to_30_as_fraction_of_gap" in with_gap["fused_log_odds"]


def test_synthetic_fixture_reproduces_known_endpoint_shape():
    result = synthetic_report()
    assert result["fixture"]["compression_at_3"] == pytest.approx(0.799)
    assert result["fixture"]["compression_at_48"] == pytest.approx(0.730)
    assert result["compression_channel"]["baseline_slope"] < 0
