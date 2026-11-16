import numpy as np
import pytest

from original.quantum.writer_line import writer_line_action, writer_z


def test_too_few_papers_abstains():
    assert writer_z(1.0, [0.5, 0.6]) is None


def test_z_uses_own_mean_and_spread():
    assert writer_z(1.0, [0.5, 0.5, 0.8]) == pytest.approx(
        (1.0 - 0.6) / max(np.std([0.5, 0.5, 0.8]), 0.05)
    )


def test_spread_floor_caps_z():
    assert writer_z(0.6, [0.5, 0.5, 0.5]) == pytest.approx(0.1 / 0.05)


@pytest.mark.parametrize("bad", [float("nan"), float("inf")])
def test_non_finite_abstains(bad):
    assert writer_z(bad, [0.5, 0.6, 0.7]) is None
    assert writer_z(1.0, [0.5, bad, 0.7]) is None
    assert writer_line_action(None) is None
    assert writer_line_action(bad) is None


def test_tier_bands():
    assert writer_line_action(0.5) == "no_action"
    assert writer_line_action(1.5) == "monitor"
    assert writer_line_action(2.5) == "schedule_conversation"
    assert writer_line_action(9.0) == "escalate"
