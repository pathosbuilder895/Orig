from __future__ import annotations

import dataclasses
import sys
import uuid
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

import run
from original.constants import FEATURE_DIM
from original.quantum.state import BaselineSample, StudentState
from original.style_authorship import (
    EXPECTED_SCHEMA_VERSION,
    EXPECTED_SIGNAL_ORDER,
    MIN_BASELINES,
    MIN_PEER_PROFILES,
    SIGNATURE_VERSION,
    StyleAuthorshipResult,
    content_reduced_signature,
    predict_style_authorship,
    reset_for_tests,
    vocabulary_sha256,
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


def _state_n(identity: int, n: int, *, tenant: str = "style-test") -> StudentState:
    samples = [
        BaselineSample(
            text=_text(identity, sample),
            vector=np.full(FEATURE_DIM, 0.4 + identity * 0.001),
            provenance="verified",
            auth_weight=1.0,
            assignment=f"assignment-{sample}",
            submitted_at="2026-01-01",
        )
        for sample in range(n)
    ]
    return StudentState(student_id=f"{tenant}:student-{identity}", samples=samples)


def _state(identity: int, *, tenant: str = "style-test") -> StudentState:
    return _state_n(identity, 3, tenant=tenant)


@pytest.fixture()
def style_reset():
    """Fresh singleton before and after each test that touches the loader."""
    reset_for_tests()
    yield
    reset_for_tests()


def _make_fixture_artifact(
    tmp_path: Path,
    *,
    schema_version=EXPECTED_SCHEMA_VERSION,
    signature_version=SIGNATURE_VERSION,
    signal_order=None,
    bad_vocab_checksum: bool = False,
    drift_refs: bool = False,
    strict_threshold: float = 0.75,
    drop_key: str | None = None,
    not_a_dict: bool = False,
) -> Path:
    """Build a small-but-structurally-real style-authorship artifact.

    Mirrors scripts/train_style_authorship.py's schema exactly (character
    vectorizer + style scaler + calibrator + reference signals), just fit on
    a tiny in-test corpus instead of the PAN corpus, so it is fast and has no
    external dependency. The ``bad_*``/``drop_key``/``not_a_dict`` knobs each
    trip exactly one `_load_artifact` validation arm.
    """
    import joblib
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler

    texts = [_text(i) for i in range(6)]
    vectorizer = TfidfVectorizer(analyzer="char", ngram_range=(2, 3), min_df=1)
    vectorizer.fit(texts)

    style_vectors = np.stack([content_reduced_signature(text) for text in texts])
    scaler = StandardScaler().fit(style_vectors)

    rng = np.random.default_rng(7)
    signals = rng.normal(size=(24, 4))
    labels = (signals[:, 0] > 0).astype(int)
    calibrator = LogisticRegression(max_iter=200).fit(signals, labels)

    reference = signals[:8]
    reference_probabilities = calibrator.predict_proba(reference)[:, 1]
    if drift_refs:
        reference_probabilities = np.clip(reference_probabilities + 0.5, 0, 1)

    checksum = vocabulary_sha256(vectorizer)
    if bad_vocab_checksum:
        checksum = "0" * 64

    artifact = {
        "schema_version": schema_version,
        "signature_version": signature_version,
        "signal_order": signal_order if signal_order is not None else list(EXPECTED_SIGNAL_ORDER),
        "character_vectorizer": vectorizer,
        "style_scaler": scaler,
        "calibrator": calibrator,
        "strict_threshold": strict_threshold,
        "vocabulary_sha256": checksum,
        "reference_signals": reference,
        "reference_probabilities": reference_probabilities,
        "provenance": {"dataset": "fixture-style-corpus"},
    }
    if drop_key:
        artifact.pop(drop_key, None)
    if not_a_dict:
        artifact = ["not", "a", "dict"]
    path = tmp_path / "fixture_style.joblib"
    joblib.dump(artifact, path)
    return path


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


def test_inference_abstains_below_peer_floor(style_reset, tmp_path, monkeypatch):
    """peers < MIN_PEER_PROFILES abstains with None, identical to flag-off."""
    monkeypatch.setenv("STYLE_AUTHORSHIP_MODEL_PATH", str(_make_fixture_artifact(tmp_path)))
    assert warm() is True
    claimed = _state(0)
    thin_peer_pool = [_state(index) for index in range(1, 6)]  # 5 < MIN_PEER_PROFILES (10)
    assert len(thin_peer_pool) < MIN_PEER_PROFILES
    result = predict_style_authorship(_text(0, 9), claimed, [claimed, *thin_peer_pool])
    assert result is None, (
        "below-peer-floor must abstain with exactly the flag-off return value (None)"
    )


def test_inference_abstains_missing_raw_text(style_reset, tmp_path, monkeypatch):
    """Fewer than MIN_BASELINES authenticated baseline texts abstains with None."""
    monkeypatch.setenv("STYLE_AUTHORSHIP_MODEL_PATH", str(_make_fixture_artifact(tmp_path)))
    assert warm() is True
    claimed = _state_n(0, 2)  # 2 < MIN_BASELINES (3)
    assert len(claimed.samples) < MIN_BASELINES
    plenty_of_peers = [_state(index) for index in range(1, 15)]
    result = predict_style_authorship(_text(0, 9), claimed, [claimed, *plenty_of_peers])
    assert result is None, (
        "missing-raw-text abstention must return exactly the flag-off value (None)"
    )


def test_success_with_heterogeneous_peer_pool_excludes_thin_peers(
    style_reset, tmp_path, monkeypatch
):
    """Peers below MIN_BASELINES are skipped (not counted), not appended, while
    the loop keeps going — success is still reached once enough real peers exist."""
    monkeypatch.setenv("STYLE_AUTHORSHIP_MODEL_PATH", str(_make_fixture_artifact(tmp_path)))
    assert warm() is True
    claimed = _state(0)
    good_peers = [_state(index) for index in range(1, 11)]  # exactly MIN_PEER_PROFILES
    thin_peers = [_state_n(90 + index, 1) for index in range(3)]  # excluded, not counted
    result = predict_style_authorship(
        _text(0, 9), claimed, [claimed, *good_peers, *thin_peers]
    )
    assert result is not None
    assert result.peer_profiles == len(good_peers), "thin peers must not count toward the floor"


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


# ── content_reduced_signature edge case ────────────────────────────────────


def test_content_reduced_signature_handles_text_with_no_sentences():
    """A probe with no `.`/`!`/`?` boundaries (e.g. an ellipsis-only submission)
    must not divide-by-zero or blow up computing sentence rhythm — it falls
    back to the zero rhythm vector rather than raising."""
    vec = content_reduced_signature("...")
    assert vec.shape[0] > 0
    assert np.all(np.isfinite(vec))


# ── _load_artifact validation arms: every bad artifact abstains like flag-off ─


def test_import_error_escalating_inconsistent_version_warning_is_tolerated(
    style_reset, tmp_path, monkeypatch
):
    """If sklearn.exceptions.InconsistentVersionWarning can't be imported, the
    loader just skips the warning escalation (`except ImportError: pass`) and
    still loads a structurally-valid artifact — this is not a fail-closed arm."""
    monkeypatch.setenv("STYLE_AUTHORSHIP_MODEL_PATH", str(_make_fixture_artifact(tmp_path)))
    monkeypatch.setitem(sys.modules, "sklearn.exceptions", None)
    assert warm() is True


def test_non_dict_artifact_disables_expert(style_reset, tmp_path, monkeypatch):
    monkeypatch.setenv(
        "STYLE_AUTHORSHIP_MODEL_PATH", str(_make_fixture_artifact(tmp_path, not_a_dict=True))
    )
    assert warm() is False
    states = [_state(index) for index in range(12)]
    assert predict_style_authorship(_text(0, 9), states[0], states) is None


def test_schema_version_mismatch_disables_expert(style_reset, tmp_path, monkeypatch):
    monkeypatch.setenv(
        "STYLE_AUTHORSHIP_MODEL_PATH",
        str(_make_fixture_artifact(tmp_path, schema_version=EXPECTED_SCHEMA_VERSION + 1)),
    )
    assert warm() is False
    states = [_state(index) for index in range(12)]
    assert predict_style_authorship(_text(0, 9), states[0], states) is None


def test_signature_version_mismatch_disables_expert(style_reset, tmp_path, monkeypatch):
    monkeypatch.setenv(
        "STYLE_AUTHORSHIP_MODEL_PATH",
        str(_make_fixture_artifact(tmp_path, signature_version=SIGNATURE_VERSION + 1)),
    )
    assert warm() is False
    states = [_state(index) for index in range(12)]
    assert predict_style_authorship(_text(0, 9), states[0], states) is None


def test_signal_order_mismatch_disables_expert(style_reset, tmp_path, monkeypatch):
    monkeypatch.setenv(
        "STYLE_AUTHORSHIP_MODEL_PATH",
        str(_make_fixture_artifact(tmp_path, signal_order=list(reversed(EXPECTED_SIGNAL_ORDER)))),
    )
    assert warm() is False
    states = [_state(index) for index in range(12)]
    assert predict_style_authorship(_text(0, 9), states[0], states) is None


def test_vocabulary_checksum_mismatch_disables_expert(style_reset, tmp_path, monkeypatch):
    monkeypatch.setenv(
        "STYLE_AUTHORSHIP_MODEL_PATH",
        str(_make_fixture_artifact(tmp_path, bad_vocab_checksum=True)),
    )
    assert warm() is False
    states = [_state(index) for index in range(12)]
    assert predict_style_authorship(_text(0, 9), states[0], states) is None


def test_reference_prediction_drift_disables_expert(style_reset, tmp_path, monkeypatch):
    monkeypatch.setenv(
        "STYLE_AUTHORSHIP_MODEL_PATH", str(_make_fixture_artifact(tmp_path, drift_refs=True))
    )
    assert warm() is False
    states = [_state(index) for index in range(12)]
    assert predict_style_authorship(_text(0, 9), states[0], states) is None


@pytest.mark.parametrize("bad_threshold", [0.5, 1.0, 0.2])
def test_invalid_strict_threshold_disables_expert(
    style_reset, tmp_path, monkeypatch, bad_threshold
):
    """`strict_threshold` must satisfy 0.5 < t < 1.0 (both boundaries excluded)."""
    monkeypatch.setenv(
        "STYLE_AUTHORSHIP_MODEL_PATH",
        str(_make_fixture_artifact(tmp_path, strict_threshold=bad_threshold)),
    )
    assert warm() is False
    states = [_state(index) for index in range(12)]
    assert predict_style_authorship(_text(0, 9), states[0], states) is None


def test_generic_load_exception_disables_expert(style_reset, tmp_path, monkeypatch):
    """A malformed-but-dict artifact missing a required key raises inside the
    loader (KeyError) — the broad `except Exception` arm must still fail
    closed rather than propagate."""
    monkeypatch.setenv(
        "STYLE_AUTHORSHIP_MODEL_PATH",
        str(_make_fixture_artifact(tmp_path, drop_key="reference_signals")),
    )
    assert warm() is False
    states = [_state(index) for index in range(12)]
    assert predict_style_authorship(_text(0, 9), states[0], states) is None


def test_ensure_loaded_skips_reload_when_already_loaded_inside_lock(style_reset, monkeypatch):
    """Double-checked locking guard: if another thread finished loading while
    this call was waiting on the lock, `_ensure_loaded` must not call
    `_load_artifact` again — it just observes the now-current state."""
    import original.style_authorship as style_module

    class _WonTheRaceLock:
        def __enter__(self):
            # Simulate a concurrent caller finishing the load first, between
            # this call's outer state checks and it acquiring the lock.
            style_module._state = style_module._READY
            style_module._artifact = {"raced": True}

        def __exit__(self, *exc_info):
            return False

    def _boom():
        raise AssertionError("_load_artifact must not run when state changed under the lock")

    monkeypatch.setattr(style_module, "_lock", _WonTheRaceLock())
    monkeypatch.setattr(style_module, "_load_artifact", _boom)
    assert style_module._state == style_module._UNLOADED
    assert style_module._ensure_loaded() is True
    assert style_module._artifact == {"raced": True}


# ── predict_style_authorship's own broad exception guard ───────────────────


def test_predict_malformed_text_fails_closed(style_reset, tmp_path, monkeypatch):
    """A non-string `text` blows up on `text.split()` before anything else
    runs — the prediction-time `except Exception` must still return None
    rather than propagate, exactly like every other failure mode here."""
    monkeypatch.setenv("STYLE_AUTHORSHIP_MODEL_PATH", str(_make_fixture_artifact(tmp_path)))
    assert warm() is True
    states = [_state(index) for index in range(12)]
    assert predict_style_authorship(None, states[0], states) is None
