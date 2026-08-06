import numpy as np

from validation.audits.pooling_exchangeability import assess_exchangeability


def test_homogeneous_students_are_exchangeable():
    rng = np.random.default_rng(11)
    per_student = [rng.normal(1.0, 0.2, 25) for _ in range(6)]
    out = assess_exchangeability(per_student)
    assert out["verdict"] == "exchangeable"


def test_shifted_students_are_heterogeneous():
    """One student centred at 3.0 while the rest sit at 1.0 means a
    pooled reference would misprice everybody."""
    rng = np.random.default_rng(12)
    per_student = [rng.normal(1.0, 0.2, 25) for _ in range(5)]
    per_student.append(rng.normal(3.0, 0.2, 25))
    out = assess_exchangeability(per_student)
    assert out["verdict"] == "heterogeneous"


def test_too_few_students_is_insufficient_not_a_pass():
    out = assess_exchangeability([np.array([1.0, 1.1])])
    assert out["verdict"] == "insufficient"
