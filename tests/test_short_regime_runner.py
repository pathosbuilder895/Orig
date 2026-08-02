
from validation.short_regime.corpus import Trial
from validation.short_regime.runner import LeverCombo, build_state, cohort_stats, run_combo

WORDS_A = "the quick brown fox jumps over the lazy dog and then rests quietly " * 50
WORDS_B = (
    "epistemology notwithstanding the categorical imperative demands rigorous scrutiny always " * 50
)


def _trial(sid, text):
    c = text.split()

    def mk(i):
        return " ".join(c[i * 400 : (i + 1) * 400])

    return Trial(student_id=sid, baseline=[mk(0), mk(1), mk(2)], honest=[mk(3)])


def test_build_state_has_three_samples_and_genre():
    t = _trial("a", WORDS_A)
    s = build_state(t, LeverCombo(False, False, False, "deviation"))
    assert s.sample_count == 3
    assert s.samples[-1].genre == "essay"


def test_cohort_stats_excludes_self():
    trials = [_trial("a", WORDS_A), _trial("b", WORDS_B)]
    cs = cohort_stats(trials, exclude="a")
    assert cs["n_samples"] == 3          # only b's 3 baseline vectors
    assert cs["mean"].shape == cs["std"].shape


def test_run_combo_off_produces_metrics():
    trials = [_trial("a", WORDS_A), _trial("b", WORDS_B)]
    out = run_combo(trials, attacks={}, combo=LeverCombo(False, False, False, "deviation"))
    assert out["combo"] == "OFF"
    assert out["n_honest"] == 2 and out["n_impostor"] == 2
    assert 0.0 <= out["auc"] <= 1.0
    assert "catch_rate" in out and "threshold" in out
