import numpy as np
import pytest

from validation.short_regime.stats import CatchResult, auc, bootstrap_ci, catch_at_budget


def test_auc_perfect_separation():
    honest = np.array([0.1, 0.2, 0.3])
    impostor = np.array([0.7, 0.8, 0.9])
    assert auc(honest, impostor) == 1.0


def test_auc_no_separation():
    rng = np.random.default_rng(0)
    x = rng.uniform(size=500)
    y = rng.uniform(size=500)
    assert abs(auc(x, y) - 0.5) < 0.05


def test_auc_ties_count_half():
    assert auc(np.array([0.5]), np.array([0.5])) == 0.5


def test_catch_at_budget_known_quantile():
    # honest = 0.00..0.99; 95th percentile threshold ~0.95
    honest = np.arange(100) / 100.0
    impostor = np.array([0.90, 0.96, 0.97, 0.98])  # 3 of 4 above threshold
    r = catch_at_budget(honest, impostor, budget=0.05)
    assert isinstance(r, CatchResult)
    assert 0.94 <= r.threshold <= 0.96
    assert r.catch_rate == 0.75
    assert r.false_flag_rate <= 0.05
    assert r.n_honest == 100 and r.n_impostor == 4


def test_catch_empty_impostor_raises():
    with pytest.raises(ValueError):
        catch_at_budget(np.array([0.1]), np.array([]))


def test_bootstrap_ci_brackets_point_estimate_and_is_deterministic():
    rng = np.random.default_rng(1)
    honest = rng.normal(0.4, 0.05, 200)
    impostor = rng.normal(0.7, 0.05, 200)
    lo, hi = bootstrap_ci(honest, impostor, metric="auc", n_boot=200, seed=42)
    point = auc(honest, impostor)
    assert lo <= point <= hi
    assert (lo, hi) == bootstrap_ci(honest, impostor, metric="auc", n_boot=200, seed=42)
