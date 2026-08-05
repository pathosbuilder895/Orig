from __future__ import annotations

import dataclasses
import uuid

import numpy as np
from fastapi.testclient import TestClient

import run
from original.constants import FEATURE_DIM
from original.quantum.state import BaselineSample, StudentState
from original.style_authorship import (
    StyleAuthorshipResult,
    predict_style_authorship,
    reset_for_tests,
    warm,
)


client = TestClient(run.load_legacy_demo_app())


def _text(identity: int, sample: int = 0) -> str:
    function_pattern = (
        "and the writer will consider whether this argument is sound, but it is also careful; "
        if identity % 2 == 0
        else "however, a reader might ask why these claims have been made: therefore we reply; "
    )
    content = f"identity{identity} sample{sample} covenant mercy justice formation "
    return ((function_pattern + content) * 55).strip()


def _state(identity: int, *, tenant: str = "style-test") -> StudentState:
    samples = [
        BaselineSample(
            text=_text(identity, sample),
            vector=np.full(FEATURE_DIM, 0.4 + identity * 0.001),
            provenance="verified",
            auth_weight=1.0,
            assignment=f"assignment-{sample}",
            submitted_at="2026-01-01",
        )
        for sample in range(3)
    ]
    return StudentState(student_id=f"{tenant}:student-{identity}", samples=samples)


def test_internal_and_response_contracts_default_none():
    from original.quantum.scoring import Layer7Output
    from original.schemas import Layer7OutputResponse

    defaults = {field.name: field.default for field in dataclasses.fields(Layer7Output)}
    assert defaults["style_authorship"] is None
    assert Layer7OutputResponse.model_fields["style_authorship"].default is None


def test_committed_artifact_loads_and_real_inference_uses_peer_cohort():
    reset_for_tests()
    states = [_state(index) for index in range(12)]
    assert warm() is True
    result = predict_style_authorship(_text(0, 9), states[0], states)
    assert result is not None
    assert 0.0 <= result.probability_same_author <= 1.0
    assert result.peer_profiles == 11
    assert result.baseline_samples == 3
    assert result.band in {"consistent", "inconclusive"}
    reset_for_tests()


def test_inference_abstains_below_peer_floor():
    reset_for_tests()


def test_missing_artifact_fails_closed(monkeypatch, tmp_path):
    monkeypatch.setenv("STYLE_AUTHORSHIP_MODEL_PATH", str(tmp_path / "missing.joblib"))
    reset_for_tests()
    states = [_state(index) for index in range(12)]
    assert warm() is False
    assert predict_style_authorship(_text(0, 9), states[0], states) is None
    reset_for_tests()
    states = [_state(index) for index in range(5)]
    assert predict_style_authorship(_text(0, 9), states[0], states) is None
    reset_for_tests()


def test_api_flag_is_attach_only(monkeypatch):
    from original import store
    import original.style_authorship as style_module

    identity = 50
    state = _state(identity, tenant="demo")
    sid = state.student_id
    store.put(state)
    mocked = StyleAuthorshipResult(0.91, "consistent", True, 0.8522, 11, 3, "v1", "fixture")
    monkeypatch.setattr(style_module, "predict_style_authorship", lambda *args, **kwargs: mocked)
    payload = {"text": _text(identity, 7), "submission_id": f"style-{uuid.uuid4().hex}"}

    monkeypatch.setenv("STYLE_AUTHORSHIP_ENABLED", "0")
    off = client.post(f"/students/{sid}/score", json=payload)
    assert off.status_code == 200, off.text
    monkeypatch.setenv("STYLE_AUTHORSHIP_ENABLED", "1")
    on = client.post(f"/students/{sid}/score", json=payload)
    assert on.status_code == 200, on.text
    off_json, on_json = off.json(), on.json()
    assert off_json["style_authorship"] is None
    assert on_json["style_authorship"]["band"] == "consistent"
    off_json.pop("style_authorship")
    on_json.pop("style_authorship")
    assert on_json == off_json
