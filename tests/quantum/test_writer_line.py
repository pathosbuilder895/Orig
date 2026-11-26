import numpy as np
import pytest

from original.constants import WRITER_LINE_STD_FLOOR, WRITER_LINE_Z_THRESHOLDS
from original.quantum.writer_line import loo_deviation_scores, writer_line_action, writer_z


def test_too_few_papers_abstains():
    assert writer_z(1.0, [0.5, 0.6]) is None


def test_z_uses_own_mean_and_spread():
    assert writer_z(1.0, [0.5, 0.5, 0.8]) == pytest.approx(
        (1.0 - 0.6) / max(np.std([0.5, 0.5, 0.8]), WRITER_LINE_STD_FLOOR)
    )


def test_spread_floor_caps_z():
    assert writer_z(0.6, [0.5, 0.5, 0.5]) == pytest.approx(0.1 / WRITER_LINE_STD_FLOOR)


@pytest.mark.parametrize("bad", [float("nan"), float("inf")])
def test_non_finite_abstains(bad):
    assert writer_z(bad, [0.5, 0.6, 0.7]) is None
    assert writer_z(1.0, [0.5, bad, 0.7]) is None
    assert writer_line_action(None) is None
    assert writer_line_action(bad) is None


def test_tier_bands():
    t = WRITER_LINE_Z_THRESHOLDS
    for name in ("monitor", "schedule_conversation"):
        lo, hi = t[name]
        assert writer_line_action((lo + hi) / 2) == name
    assert writer_line_action(t["monitor"][0] - 1.0) == "no_action"
    assert writer_line_action(t["escalate"][0] + 1.0) == "escalate"


def test_below_lowest_band_is_first_tier():
    custom = {
        "no_action": (0.0, 1.0),
        "monitor": (1.0, 2.0),
        "escalate": (2.0, 3.0),
    }
    assert writer_line_action(-5.0, custom) == "no_action"
    assert writer_line_action(1e9, custom) == "escalate"


def test_band_boundaries_are_inclusive_lower():
    t = WRITER_LINE_Z_THRESHOLDS
    for name in ("monitor", "schedule_conversation", "escalate"):
        assert writer_line_action(t[name][0]) == name


def test_exactly_three_papers_returns_float():
    assert isinstance(writer_z(0.7, [0.5, 0.6, 0.7]), float)


# ── Task 2: wiring into score() behind WRITER_LINE ────────────────────────────

import dataclasses  # noqa: E402

from original.constants import ALL_FEATURE_CODES, FEATURE_DIM  # noqa: E402
from original.quantum.null_pool import build_impostor_stats  # noqa: E402
from original.quantum.scoring import ScoringConfig, score  # noqa: E402
from original.quantum.state import BaselineSample, StudentState  # noqa: E402

_TIERS = ["no_action", "monitor", "schedule_conversation", "escalate"]


def _state(sid="t:s", seed=0, n=4, noise=0.01, weights=None):
    rng = np.random.RandomState(seed)
    base = rng.uniform(0.3, 0.7, FEATURE_DIM)
    weights = weights or [1.0] * n
    samples = [
        BaselineSample(
            text="word " * 300,
            vector=np.clip(base + rng.normal(0, noise, FEATURE_DIM), 0, 1),
            provenance="proctored",
            auth_weight=w,
            assignment=f"a{i}",
        )
        for i, w in enumerate(weights)
    ]
    return StudentState(student_id=sid, samples=samples), base


def _score(state, base, shift=0.02, impostor_stats=None, **cfg):
    vec = np.clip(base + shift, 0, 1)
    fd = {c: float(v) for c, v in zip(ALL_FEATURE_CODES, vec, strict=True)}
    return score(
        state,
        vec,
        fd,
        submission_id="sub",
        n_tokens=300,
        impostor_stats=impostor_stats,
        scoring_config=ScoringConfig(**cfg),
    )


def test_off_is_byte_identical(monkeypatch):
    monkeypatch.delenv("WRITER_LINE", raising=False)
    s, b = _state()
    unset = _score(s, b)
    s2, b2 = _state()
    off = _score(s2, b2, writer_line="off")
    assert dataclasses.asdict(unset) == dataclasses.asdict(off)
    assert off.writer_line_z is None and off.writer_line_action is None
    monkeypatch.setenv("WRITER_LINE", "off")
    assert ScoringConfig.from_env().writer_line == "off"
    monkeypatch.setenv("WRITER_LINE", "bogus")
    assert ScoringConfig.from_env().writer_line == "off"


def test_unknown_value_is_off():
    s, b = _state()
    off = _score(s, b, writer_line="off")
    s2, b2 = _state()
    bogus = _score(s2, b2, writer_line="bogus")
    assert dataclasses.asdict(off) == dataclasses.asdict(bogus)


def test_shadow_changes_no_field_but_sets_diagnostics():
    s, b = _state()
    off = _score(s, b, writer_line="off")
    s2, b2 = _state()
    shadow = _score(s2, b2, writer_line="shadow")
    assert shadow.writer_line_z is not None
    assert shadow.writer_line_action is not None
    a, c = dataclasses.asdict(off), dataclasses.asdict(shadow)
    for k in ("writer_line_z", "writer_line_action"):
        a.pop(k), c.pop(k)
    assert a == c


def test_on_replaces_base_tier():
    s, b = _state()
    # shift 0.06 puts the writer z above the calibrated escalate cut.
    off = _score(s, b, shift=0.06, writer_line="off")
    s2, b2 = _state()
    on = _score(s2, b2, shift=0.06, writer_line="on")
    assert _TIERS.index(on.recommendation.action) >= _TIERS.index("schedule_conversation")
    assert _TIERS.index(off.recommendation.action) < _TIERS.index(on.recommendation.action)
    assert on.recommendation.confidence == off.recommendation.confidence
    assert "Per-writer line" in on.recommendation.rationale
    assert on.authorship.deviation_score == off.authorship.deviation_score


def test_on_still_lets_gate_lower_one_step():
    s, b = _state()
    peers = [_state(f"t:p{i}", 100 + i)[0] for i in range(5)]
    imp = build_impostor_stats(s.student_id, [s, *peers])
    shadow_llr = _score(
        s, b, shift=0.06, impostor_stats=imp, null_model="impostor", writer_line="on",
        llr_action_mode="shadow",
    )
    gated = _score(s, b, shift=0.06, impostor_stats=imp, null_model="impostor", writer_line="on")
    assert gated.authorship.llr_deviation_score <= 0.35
    assert shadow_llr.recommendation.action == gated.writer_line_action == "escalate"
    assert gated.recommendation.action == "schedule_conversation"


def test_on_catastrophic_drift_still_escalates(monkeypatch):
    # Patching the module attribute works only because score() imports
    # writer_line_action inside the function body, at call time. A natural
    # rms_z >= 3 case always also gives a high writer z, so a low tier is forced.
    import original.quantum.writer_line as wl

    monkeypatch.setattr(wl, "writer_line_action", lambda z, thresholds=None: "no_action")
    s, b = _state(n=5, noise=0.25)
    on = _score(s, b, shift=0.6, writer_line="on")
    assert on.catastrophic_drift
    assert on.writer_line_action == "no_action"
    assert on.recommendation.action == "escalate"
    assert "Catastrophic drift" in on.recommendation.rationale


def test_on_abstains_below_min_papers():
    s, b = _state(n=3)  # 3 papers -> 3 LOO distances: enough
    assert _score(s, b, writer_line="on").writer_line_z is not None
    s, b = _state(n=2)
    off = _score(s, b, writer_line="off")
    s2, b2 = _state(n=2)
    on = _score(s2, b2, writer_line="on")
    assert on.writer_line_z is None and on.writer_line_action is None
    assert on.recommendation == off.recommendation


def test_on_computes_under_characteristic_weights():
    s, b = _state()
    peers = [_state(f"t:p{i}", 100 + i)[0] for i in range(5)]
    imp = build_impostor_stats(s.student_id, [s, *peers])
    on = _score(s, b, impostor_stats=imp, characteristic_weights="on", writer_line="on")
    assert on.characteristic_weighting_applied
    assert on.writer_line_z is not None
    # Typicality keeps its own guard.
    typ = _score(
        s, b, impostor_stats=imp, characteristic_weights="on", typicality_scoring_enabled=True
    )
    assert typ.typicality_band is None and typ.typicality_n == 0


def test_zero_auth_weight_papers_do_not_count():
    s, b = _state(weights=[1.0, 1.0, 0.0, 0.0])
    assert _score(s, b, writer_line="on").writer_line_z is None
    s, b = _state(weights=[1.0, 1.0, 1.0, 0.0])
    assert len(s.loo_distances) == 3
    assert _score(s, b, writer_line="on").writer_line_z is not None


def test_on_computes_under_length_adaptive_weights():
    s, b = _state()
    on = _score(s, b, length_adaptive_weights=True, writer_line="on")
    assert on.writer_line_z is not None and on.writer_line_action is not None


# ── Task 3b: leave-one-out deviation reference ───────────────────────────────


def test_loo_deviation_scores_needs_three_papers():
    s, _ = _state(n=2)
    assert loo_deviation_scores(s, score, scoring_config=ScoringConfig()) == []
    s, _ = _state(n=3)
    out = loo_deviation_scores(s, score, scoring_config=ScoringConfig())
    assert len(out) == 3 and all(0.0 <= d <= 1.0 for d in out)


def test_loo_deviation_scores_does_not_mutate_state():
    s, _ = _state()
    before = [(x.auth_weight, x.vector.copy(), x.genre) for x in s.samples]
    n_before, rho = len(s.samples), s.density_matrix.copy()
    loo_deviation_scores(s, score, scoring_config=ScoringConfig())
    assert len(s.samples) == n_before
    assert np.array_equal(s.density_matrix, rho)
    for (w, v, g), x in zip(before, s.samples, strict=True):
        assert x.auth_weight == w and np.array_equal(x.vector, v) and x.genre == g


def test_loo_deviation_scores_uses_given_weights():
    s, _ = _state(noise=0.05)
    plain = loo_deviation_scores(s, score, scoring_config=ScoringConfig())
    w = np.ones(FEATURE_DIM)
    w[: FEATURE_DIM // 2] = 5.0
    weighted = loo_deviation_scores(s, score, adaptive_weights=w, scoring_config=ScoringConfig())
    assert plain != weighted


def test_loo_deviation_scores_forces_writer_line_off():
    s, _ = _state()
    seen = []

    def spy(*args, **kwargs):
        seen.append(kwargs["scoring_config"].writer_line)
        return score(*args, **kwargs)

    loo_deviation_scores(s, spy, scoring_config=ScoringConfig(writer_line="on"))
    assert seen == ["off"] * 4


def test_loo_deviation_scores_failure_returns_empty():
    s, _ = _state()

    def boom(*a, **k):
        raise RuntimeError("x")

    assert loo_deviation_scores(s, boom, scoring_config=ScoringConfig()) == []


def test_off_never_computes_reference(monkeypatch):
    import original.quantum.writer_line as wl

    def fail(*a, **k):
        raise AssertionError("loo_deviation_scores called under off")

    monkeypatch.setattr(wl, "loo_deviation_scores", fail)
    s, b = _state()
    _score(s, b, writer_line="off")


def test_z_is_on_final_deviation_score():
    s, b = _state()
    on = _score(s, b, writer_line="shadow")
    ref = loo_deviation_scores(s, score, n_tokens=300, scoring_config=ScoringConfig())
    assert on.writer_line_z == pytest.approx(writer_z(on.authorship.deviation_score, ref))
