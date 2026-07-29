import numpy as np

from validation.short_regime.reliability import icc_1


def test_icc_perfectly_reliable_feature():
    # 3 authors, 4 obs each, zero within-author variance
    groups = [np.full(4, 0.2), np.full(4, 0.5), np.full(4, 0.8)]
    assert icc_1(groups) > 0.99


def test_icc_pure_noise_feature():
    rng = np.random.default_rng(0)
    groups = [rng.normal(0.5, 0.1, 50) for _ in range(3)]
    assert icc_1(groups) < 0.1


def test_icc_clipped_to_unit_interval():
    groups = [np.array([0.5, 0.5]), np.array([0.5, 0.5])]
    assert 0.0 <= icc_1(groups) <= 1.0
