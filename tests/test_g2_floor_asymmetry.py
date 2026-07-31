from validation.audits.g2_floor_asymmetry import analyze_floor_asymmetry


def test_detects_pure_floor_artifact():
    """Both legs rank-1 in their own reference sets, only N differs:
    the q gap is entirely an artifact and must be reported as such."""
    holdout = [{"q": 1 / 6, "n": 5, "rank": 1}] * 10      # floor 0.167
    impostor = [{"q": 1 / 21, "n": 20, "rank": 1}] * 10   # floor 0.048
    out = analyze_floor_asymmetry(holdout, impostor)
    assert out["holdout_at_floor_rate"] == 1.0
    assert out["impostor_at_floor_rate"] == 1.0
    assert out["matched_n_verdict"] == "artifact"


def test_detects_genuine_separation():
    """Impostors rank first while holdouts sit mid-distribution: the
    separation survives matching on N."""
    holdout = [{"q": 3 / 6, "n": 5, "rank": 3}] * 10
    impostor = [{"q": 1 / 21, "n": 20, "rank": 1}] * 10
    out = analyze_floor_asymmetry(holdout, impostor)
    assert out["holdout_at_floor_rate"] == 0.0
    assert out["matched_n_verdict"] == "genuine"
