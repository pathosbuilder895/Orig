"""
OPPORTUNITY_MASK production-wiring test (students_scoring.py).

score() only leaves a measurement out when the caller hands it the paper's
unmeasured mask, and the route is the only place that knows the text. If that
hand-off is dropped, the flag goes quietly inert with a green suite: the same
failure mode CLAUDE.md records for GENRE_INVARIANT_WEIGHTS_ENABLED. These
tests drive the real HTTP endpoint and watch what reaches score().
"""

import logging

import numpy as np
import pytest
from fastapi.testclient import TestClient

import run  # repo-root launcher
from original import principal as pr
from original.constants import ALL_FEATURE_CODES, FEATURE_DIM
from original.quantum.state import BaselineSample, StudentState
from original.repository import get_repository
from original.routers import students_scoring

app = run.load_legacy_demo_app()
client = TestClient(app)

_THAT = ALL_FEATURE_CODES.index("that_which_ratio")
_SID = "oppw:scored_student"

# No "that"/"which" relative clause anywhere: nothing to measure.
_TEXT = (
    "The harvest came late this year. Rain fell for nine days. Farmers waited "
    "in barns. Wheat rotted in fields. Prices rose in town. Bakers closed early. "
    "Children stayed home. Roads flooded near the river. Carts stood idle."
)


def _auth(token: str):
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def oppw_tenant():
    client.post(
        "/tenants",
        json={"tenant_id": "oppw", "name": "Opportunity Seminary", "environment": "pilot"},
    )
    rng = np.random.default_rng(17)
    state = StudentState(student_id=_SID)
    for i in range(5):
        v = np.clip(rng.normal(0.5, 0.08, FEATURE_DIM), 0.0, 1.0)
        v[_THAT] = 0.85 + 0.03 * (i % 3)  # a real, varying past preference
        state.add_sample(
            BaselineSample(
                text=f"seed sample {i}",
                vector=v,
                provenance="instructor_verified",
                auth_weight=1.0,
                assignment=f"a{i}",
            )
        )
    get_repository().put(state)
    return pr.mint_principal_token("prof_oppw", "professor", "oppw")


@pytest.fixture
def spy(monkeypatch):
    """Record what the route hands to score(), and what comes back."""
    seen = {}
    real = students_scoring.quantum_score

    def _spy(**kwargs):
        seen["kwargs"] = kwargs
        seen["result"] = real(**kwargs)
        return seen["result"]

    monkeypatch.setattr(students_scoring, "quantum_score", _spy)
    return seen


_AUDIT = (
    "opportunity_mask_applied",
    "opportunity_mode",
    "unmeasured_features",
    "opportunity_deviation_preview",
)


def _without_audit(body):
    return {k: v for k, v in body.items() if k not in _AUDIT}


def _post(token):
    r = client.post(f"/students/{_SID}/score", json={"text": _TEXT}, headers=_auth(token))
    assert r.status_code == 200, r.text
    return r.json()


def test_flag_off_computes_no_mask(oppw_tenant, spy, monkeypatch, caplog):
    monkeypatch.delenv("OPPORTUNITY_MASK", raising=False)
    with caplog.at_level(logging.INFO, logger=students_scoring.__name__):
        _post(oppw_tenant)
    assert spy["kwargs"]["unmeasured_mask"] is None
    assert spy["result"].opportunity_mode is None
    assert "opportunity_mask mode=" not in caplog.text


def test_shadow_hands_the_mask_to_score_and_logs_it(oppw_tenant, spy, monkeypatch, caplog):
    monkeypatch.delenv("OPPORTUNITY_MASK", raising=False)
    off = _post(oppw_tenant)
    monkeypatch.setenv("OPPORTUNITY_MASK", "shadow")
    with caplog.at_level(logging.INFO, logger=students_scoring.__name__):
        shadow = _post(oppw_tenant)

    mask = spy["kwargs"]["unmeasured_mask"]
    assert mask is not None and mask[_THAT]
    result = spy["result"]
    assert result.opportunity_mode == "shadow"
    assert "that_which_ratio" in result.unmeasured_features
    assert result.opportunity_deviation_preview is not None
    lines = [r.getMessage() for r in caplog.records if "opportunity_mask mode=" in r.getMessage()]
    assert len(lines) == 1
    assert lines[0].startswith("opportunity_mask mode=shadow n_unmeasured=")
    assert _SID not in lines[0]  # counts only, never a student id
    # Report-only end to end: apart from the four audit fields, the response
    # is what flag-off returns.
    assert shadow["opportunity_mode"] == "shadow"
    assert shadow["opportunity_mask_applied"] is False
    assert shadow["opportunity_deviation_preview"] is not None
    assert off["opportunity_mode"] is None
    assert _without_audit(shadow) == _without_audit(off)


def test_on_changes_the_score_through_the_route(oppw_tenant, spy, monkeypatch):
    monkeypatch.delenv("OPPORTUNITY_MASK", raising=False)
    off = _post(oppw_tenant)
    monkeypatch.setenv("OPPORTUNITY_MASK", "on")
    on = _post(oppw_tenant)
    assert spy["result"].opportunity_mask_applied is True
    assert on["authorship"]["deviation_score"] != off["authorship"]["deviation_score"]


def test_a_failing_mask_falls_back_to_flag_off(oppw_tenant, spy, monkeypatch, caplog):
    """Nothing in the new layer may take the scoring endpoint down."""
    from original.features import opportunity

    monkeypatch.delenv("OPPORTUNITY_MASK", raising=False)
    off = _post(oppw_tenant)

    def _boom(_text):
        raise RuntimeError("extractor broke")

    monkeypatch.setattr(opportunity, "unmeasured_mask", _boom)
    monkeypatch.setenv("OPPORTUNITY_MASK", "on")
    with caplog.at_level(logging.ERROR, logger=students_scoring.__name__):
        on = _post(oppw_tenant)
    assert spy["kwargs"]["unmeasured_mask"] is None
    assert "opportunity mask failed" in caplog.text
    assert on == off


@pytest.mark.parametrize("mode,expect_write", [("off", True), ("shadow", True), ("on", False)])
def test_on_does_not_store_a_narrowed_fidelity(oppw_tenant, spy, monkeypatch, mode, expect_write):
    """A fidelity encoded over fewer features must not enter the student's
    calibration set: the rows outlive the flag."""
    writes = []
    repo = get_repository()
    monkeypatch.setattr(repo, "put_fidelity_score", lambda **kw: writes.append(kw))
    monkeypatch.setenv("AMPLITUDE_SCORING_ENABLED", "1")
    monkeypatch.setenv("OPPORTUNITY_MASK", mode)
    _post(oppw_tenant)
    assert spy["result"].authorship.quantum_fidelity > 0
    assert bool(writes) is expect_write
