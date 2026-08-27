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
                "fused_score": fused,
                "baseline_samples": baseline,
                "reference_profiles": references,
            }
        )
    report = analyze_rows(rows)
    assert report["verdict"] == "measured"
    assert report["compression_channel"]["baseline_slope"] == pytest.approx(-0.0016)
    assert report["compression_channel"]["implied_shift_3_to_30"] == pytest.approx(-0.0432)
    assert report["fused_score"]["baseline_slope"] < 0


def test_abstains_loudly_when_rows_are_thin():
    report = analyze_rows([{"abstain_reason": "thin_reference"}])
    assert report["verdict"] == "uninformative"
    assert report["abstain_reasons"] == {"thin_reference": 1}


def test_synthetic_fixture_reproduces_known_endpoint_shape():
    result = synthetic_report()
    assert result["fixture"]["compression_at_3"] == pytest.approx(0.799)
    assert result["fixture"]["compression_at_48"] == pytest.approx(0.730)
    assert result["compression_channel"]["baseline_slope"] < 0
