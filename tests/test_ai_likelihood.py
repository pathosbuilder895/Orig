"""
tests/test_ai_likelihood.py — the AI-likelihood second scoring mode.

Covers the full contract from MODEL_CARD.md / the PR plan:
  1. Layer7Output + response schema carry an optional field defaulting to None.
  2. Flag-off → response ai_likelihood is null; flag-on with a "low"-band
     fixture → the REST of the response is unchanged (attach-only guarantee).
  3. Happy path with an in-test-trained fixture artifact.
  4. Graceful degradation: missing artifact → None + exactly one warning.
  5. Load-time validation: shuffled feature_codes and drifted reference
     probs both disable the detector.
  6. Masking invariance: tier-17/comparison dims are forced to 0.5.
  7. Narrative banding (elevated/strong) stays non-accusatory and digit-free.
"""

from __future__ import annotations

import dataclasses
import logging
import sys
import uuid
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

import run
from original.ai_likelihood import _MASKED_CODES
from original.constants import (
    ALL_FEATURE_CODES,
    FEATURE_DIM,
    TIER18_CODES,
)

app = run.load_legacy_demo_app()
client = TestClient(app)

_PPX_IDX = ALL_FEATURE_CODES.index("perplexity_proxy")

_ESSAY = (
    "Grace and peace are the twin notes that open nearly every Pauline letter, "
    "and their repetition is not accidental but theological. The writer returns "
    "again and again to the same vocabulary, the same cadence, the same habit of "
    "qualifying a bold claim with a gentle clause. Across a semester these habits "
    "compound into a recognizable voice, and it is that voice, not any single "
    "sentence, that the system learns to know and to defend with care and patience. "
    "The argument unfolds in stages, each one resting on the last, until the "
    "conclusion arrives less as a surprise than as something already half-known. "
    "Doctrine, on this account, is not a cage but a trellis: it gives the growing "
    "mind something to climb. When a student writes about justification, or about "
    "the sacraments, or about the strange patience of God with a stiff-necked "
    "people, the words carry the fingerprints of every previous essay. Style is "
    "the residue of formation, and formation is slow. That slowness is precisely "
    "what makes the voice trustworthy as evidence: nobody can counterfeit a "
    "semester of habits in an afternoon, and nobody loses them overnight either. "
    "So the system watches, patiently, and asks only whether this new page sounds "
    "like the pages that came before it, and says so in plain language."
)


def _make_fixture_artifact(
    tmp_path: Path,
    *,
    thresholds=None,
    shuffle_codes=False,
    drift_refs=False,
    bad_masked_codes=False,
    schema_version=1,
    not_a_dict=False,
    drop_key=None,
) -> Path:
    """Train a tiny LogisticRegression and wrap it in the exact artifact schema."""
    import joblib
    from sklearn.linear_model import LogisticRegression

    rng = np.random.default_rng(1729)
    n_half = 20
    X = np.full((n_half * 2, FEATURE_DIM), 0.5)
    # Separable on perplexity_proxy: humans ~0.40, AI ~0.80.
    X[:n_half, _PPX_IDX] = 0.40 + rng.normal(0, 0.02, n_half)
    X[n_half:, _PPX_IDX] = 0.80 + rng.normal(0, 0.02, n_half)
    y = np.array([0] * n_half + [1] * n_half)

    model = LogisticRegression(max_iter=500, random_state=1729).fit(X, y)
    human_X = X[y == 0]
    reference_vectors = X[:8].copy()
    reference_probs = model.predict_proba(reference_vectors)[:, 1]
    if drift_refs:
        reference_probs = np.clip(reference_probs + 0.5, 0, 1)

    codes = list(ALL_FEATURE_CODES)
    if shuffle_codes:
        codes = codes[::-1]

    # Derived from the module rather than rebuilt from tier constants, so the
    # fixture cannot silently drift out of agreement with the loader. It had:
    # this list omitted TIER18_CODES while _MASKED_CODES included them.
    masked_codes = list(_MASKED_CODES)
    if bad_masked_codes:
        masked_codes = [c for c in masked_codes if c not in set(TIER18_CODES)]

    artifact = {
        "schema_version": schema_version,
        "model": model,
        "model_name": "fixture_logreg",
        "feature_codes": codes,
        "masked_codes": masked_codes,
        "thresholds": thresholds or {"elevated": 0.6, "strong": 0.9},
        "human_centroid": human_X.mean(axis=0),
        "human_std": np.maximum(human_X.std(axis=0), 1e-6),
        "reference_vectors": reference_vectors,
        "reference_probs": reference_probs,
        "provenance": {
            "trained_at": "fixture",
            "git_sha": "fixture",
            "sklearn_version": "fixture",
            "numpy_version": "fixture",
            "dataset": {"name": "fixture-dataset"},
        },
    }
    if drop_key:
        artifact.pop(drop_key, None)
    if not_a_dict:
        artifact = ["not", "a", "dict"]
    path = tmp_path / "fixture_detector.joblib"
    joblib.dump(artifact, path)
    return path


@pytest.fixture()
def detector_reset():
    """Fresh singleton before and after each test that touches the loader."""
    from original.ai_likelihood import reset_for_tests

    reset_for_tests()
    yield
    reset_for_tests()


def _seed_student(sid: str) -> None:
    r = client.post(f"/students/{sid}/baseline", json={"text": _ESSAY, "provenance": "proctored"})
    assert r.status_code == 200, r.text


# ── 1 + 6. Dataclass field + schema round-trip ────────────────────────────────


def test_layer7_output_has_ai_likelihood_field_default_none():
    from original.quantum.scoring import Layer7Output

    defaults = {f.name: f.default for f in dataclasses.fields(Layer7Output)}
    assert "ai_likelihood" in defaults
    assert defaults["ai_likelihood"] is None


def test_response_schema_has_optional_ai_likelihood():
    from original.schemas import Layer7OutputResponse, AiLikelihoodOut, AiIndicatorOut

    assert Layer7OutputResponse.model_fields["ai_likelihood"].default is None
    expected = {"probability", "band", "model_version", "trained_on", "top_indicators"}
    assert expected.issubset(set(AiLikelihoodOut.model_fields.keys()))
    assert {"code", "label", "z", "direction"}.issubset(set(AiIndicatorOut.model_fields.keys()))


def test_batch_matches_scalar_probabilities(tmp_path, monkeypatch, detector_reset):
    from original.ai_likelihood import predict_ai_likelihood, predict_ai_likelihood_batch

    monkeypatch.setenv("AI_LIKELIHOOD_MODEL_PATH", str(_make_fixture_artifact(tmp_path)))
    X = np.full((3, FEATURE_DIM), 0.5)
    X[:, _PPX_IDX] = [0.35, 0.60, 0.85]
    batch = predict_ai_likelihood_batch(X)
    scalar = np.array([predict_ai_likelihood(row).probability for row in X])
    assert batch is not None
    assert np.allclose(batch, scalar, atol=5e-5)
    assert predict_ai_likelihood_batch(np.zeros((2, FEATURE_DIM - 1))) is None


# ── 2. Flag-off null + attach-only identity ───────────────────────────────────


def test_flag_off_response_null_and_flag_on_changes_nothing_else(
    tmp_path, monkeypatch, detector_reset
):
    # Deterministic Phase 1 path for the comparison (flags read at call time).
    monkeypatch.setenv("CONTEXT_MANIFEST_ENABLED", "0")
    monkeypatch.setenv("ADAPTIVE_WEIGHTS_ENABLED", "0")
    monkeypatch.delenv("AI_LIKELIHOOD_ENABLED", raising=False)

    sid = f"ai_like_identity_{uuid.uuid4().hex[:8]}"
    _seed_student(sid)
    body = {"text": _ESSAY, "submission_id": "fixed_submission_id"}

    r_off = client.post(f"/students/{sid}/score", json=body)
    assert r_off.status_code == 200, r_off.text
    resp_off = r_off.json()
    assert resp_off["ai_likelihood"] is None

    # Flag on with a fixture whose thresholds guarantee band == "low", so the
    # narrative layers stay silent and the ONLY difference is the new field.
    fixture = _make_fixture_artifact(tmp_path, thresholds={"elevated": 0.999, "strong": 0.9999})
    monkeypatch.setenv("AI_LIKELIHOOD_ENABLED", "1")
    monkeypatch.setenv("AI_LIKELIHOOD_MODEL_PATH", str(fixture))
    from original.ai_likelihood import reset_for_tests

    reset_for_tests()

    r_on = client.post(f"/students/{sid}/score", json=body)
    assert r_on.status_code == 200, r_on.text
    resp_on = r_on.json()

    assert resp_on["ai_likelihood"] is not None
    assert resp_on["ai_likelihood"]["band"] == "low"
    assert 0.0 <= resp_on["ai_likelihood"]["probability"] <= 1.0

    resp_off.pop("ai_likelihood")
    resp_on.pop("ai_likelihood")
    assert resp_on == resp_off, (
        "flag-on response differs beyond the ai_likelihood field — the "
        "detector must be attach-only"
    )


# ── 3. Happy path ─────────────────────────────────────────────────────────────


def test_happy_path_predicts_band_and_indicators(tmp_path, monkeypatch, detector_reset):
    fixture = _make_fixture_artifact(tmp_path)
    monkeypatch.setenv("AI_LIKELIHOOD_MODEL_PATH", str(fixture))
    from original.ai_likelihood import predict_ai_likelihood, warm, _INDICATOR_WHITELIST

    assert warm() is True

    vec = np.full(FEATURE_DIM, 0.5)
    vec[_PPX_IDX] = 0.85  # deep in the fixture's "AI" class, z >> 2
    result = predict_ai_likelihood(vec)

    assert result is not None
    assert 0.0 <= result.probability <= 1.0
    assert result.probability > 0.5
    assert result.band in ("low", "elevated", "strong")
    assert result.band != "low"
    assert result.model_version == "v1"
    assert result.trained_on == "fixture-dataset"
    assert len(result.top_indicators) <= 3
    assert all(ind.code in _INDICATOR_WHITELIST for ind in result.top_indicators)
    assert any(
        ind.code == "perplexity_proxy" and ind.direction == "higher"
        for ind in result.top_indicators
    )


# ── 4. Graceful degradation ───────────────────────────────────────────────────


def test_missing_artifact_returns_none_and_warns_once(
    tmp_path, monkeypatch, detector_reset, caplog
):
    monkeypatch.setenv("AI_LIKELIHOOD_MODEL_PATH", str(tmp_path / "nope.joblib"))
    from original.ai_likelihood import predict_ai_likelihood

    vec = np.full(FEATURE_DIM, 0.5)
    with caplog.at_level(logging.WARNING, logger="original.ai_likelihood"):
        assert predict_ai_likelihood(vec) is None
        assert predict_ai_likelihood(vec) is None  # second call: silent

    warnings_ = [
        rec for rec in caplog.records if "AI-likelihood detector disabled" in rec.getMessage()
    ]
    assert len(warnings_) == 1, "load failure must log exactly once"


def test_missing_artifact_endpoint_still_200(tmp_path, monkeypatch, detector_reset):
    monkeypatch.setenv("AI_LIKELIHOOD_ENABLED", "1")
    monkeypatch.setenv("AI_LIKELIHOOD_MODEL_PATH", str(tmp_path / "nope.joblib"))

    sid = f"ai_like_degrade_{uuid.uuid4().hex[:8]}"
    _seed_student(sid)
    r = client.post(f"/students/{sid}/score", json={"text": _ESSAY})
    assert r.status_code == 200, r.text
    assert r.json()["ai_likelihood"] is None


# ── 5. Load-time validation failures ──────────────────────────────────────────


def test_shuffled_feature_codes_disable_detector(tmp_path, monkeypatch, detector_reset):
    fixture = _make_fixture_artifact(tmp_path, shuffle_codes=True)
    monkeypatch.setenv("AI_LIKELIHOOD_MODEL_PATH", str(fixture))
    from original.ai_likelihood import predict_ai_likelihood, warm

    assert warm() is False
    assert predict_ai_likelihood(np.full(FEATURE_DIM, 0.5)) is None


def test_masked_codes_mismatch_disables_detector(tmp_path, monkeypatch, detector_reset):
    """Training and inference must agree on which dims are placeholders.

    An artifact whose masked set omits Tier 18 may have fitted those columns,
    which the runtime then erases to 0.5 — a silent probability shift that no
    other load check would notice.
    """
    fixture = _make_fixture_artifact(tmp_path, bad_masked_codes=True)
    monkeypatch.setenv("AI_LIKELIHOOD_MODEL_PATH", str(fixture))
    from original.ai_likelihood import predict_ai_likelihood, warm

    assert warm() is False
    assert predict_ai_likelihood(np.full(FEATURE_DIM, 0.5)) is None


def test_reference_prob_drift_disables_detector(tmp_path, monkeypatch, detector_reset):
    fixture = _make_fixture_artifact(tmp_path, drift_refs=True)
    monkeypatch.setenv("AI_LIKELIHOOD_MODEL_PATH", str(fixture))
    from original.ai_likelihood import predict_ai_likelihood, warm

    assert warm() is False
    assert predict_ai_likelihood(np.full(FEATURE_DIM, 0.5)) is None


# ── 6. Masking invariance ─────────────────────────────────────────────────────


def test_masked_dims_do_not_affect_prediction(tmp_path, monkeypatch, detector_reset):
    fixture = _make_fixture_artifact(tmp_path)
    monkeypatch.setenv("AI_LIKELIHOOD_MODEL_PATH", str(fixture))
    from original.ai_likelihood import predict_ai_likelihood, _MASKED_IDX

    vec_a = np.full(FEATURE_DIM, 0.5)
    vec_a[_PPX_IDX] = 0.85
    vec_b = vec_a.copy()
    vec_b[_MASKED_IDX] = 0.93  # keystroke/comparison data present at scoring time

    res_a = predict_ai_likelihood(vec_a)
    res_b = predict_ai_likelihood(vec_b)
    assert res_a is not None and res_b is not None
    assert res_a.probability == res_b.probability
    assert res_a.band == res_b.band


# ── 7. Narrative banding ──────────────────────────────────────────────────────


class _Band:
    def __init__(self, band: str):
        self.band = band


class _FakeLayer7:
    """Minimal stand-in; build_professor_explanation getattrs defensively."""

    def __init__(self, ai_likelihood=None):
        self.ai_likelihood = ai_likelihood


def test_narrative_strong_band_is_non_accusatory_and_digit_free():
    from original.quantum.professor_narrative import build_professor_explanation

    result = build_professor_explanation(_FakeLayer7(_Band("strong")), "Jane")
    ai_sentences = [h for h in result.hypotheses if "AI-generated" in h]
    assert ai_sentences, "strong band must surface an AI hypothesis"
    sentence = ai_sentences[0]
    assert not any(
        ch.isdigit() for ch in sentence
    ), "professor-facing prose must stay number-free (tone rule)"
    for banned in ("cheat", "fraud", "plagiar"):
        assert banned not in sentence.lower()
    # Innocent situational explanation still leads the list.
    assert (
        "pressure" in result.hypotheses[0].lower() or "unfamiliar" in result.hypotheses[0].lower()
    )
    assert result.has_ai_signals is True
    assert result.ai_likelihood_band == "strong"


def test_narrative_elevated_band_mentions_innocent_alternatives():
    from original.quantum.professor_narrative import build_professor_explanation

    result = build_professor_explanation(_FakeLayer7(_Band("elevated")), "Jane")
    ai_sentences = [h for h in result.hypotheses if "AI-generated" in h]
    assert ai_sentences
    assert "can also reflect" in ai_sentences[0]
    assert result.ai_likelihood_band == "elevated"
    # elevated alone does NOT force the has_ai flag (that's reserved for strong)
    assert result.has_ai_signals is False


def test_narrative_without_ai_likelihood_is_unchanged():
    from original.quantum.professor_narrative import build_professor_explanation

    base = build_professor_explanation(_FakeLayer7(None), "Jane")
    low = build_professor_explanation(_FakeLayer7(_Band("low")), "Jane")
    assert base.hypotheses == low.hypotheses
    assert base.has_ai_signals == low.has_ai_signals is False
    assert base.ai_likelihood_band is None
    assert low.ai_likelihood_band == "low"


# ── 8. The COMMITTED artifact must actually load ──────────────────────────────
#
# Every test above uses in-test fixture artifacts, which is how the pipeline's
# 103→109 growth (Tier 18, PR #115) silently disabled the shipped detector for
# weeks: the loader fail-closed on the stale committed artifact, every scoring
# call returned None, and the suite stayed green. These tests pin the real
# artifact to the live pipeline so the next feature-dim bump (or an sklearn
# skew that trips the reference-drift gate) fails the suite instead.


def test_committed_artifact_loads_and_predicts(monkeypatch, detector_reset):
    from original import ai_likelihood

    monkeypatch.delenv("AI_LIKELIHOOD_MODEL_PATH", raising=False)
    assert ai_likelihood.DEFAULT_ARTIFACT_PATH.exists(), (
        f"committed artifact missing at {ai_likelihood.DEFAULT_ARTIFACT_PATH}"
    )
    assert ai_likelihood.warm() is True, (
        "the committed artifact failed load-time validation — the detector is "
        "silently disabled in production (retrain via scripts/train_ai_detector.py)"
    )

    result = ai_likelihood.predict_ai_likelihood(np.full(FEATURE_DIM, 0.5))
    assert result is not None
    assert 0.0 <= result.probability <= 1.0
    assert result.band in {"low", "elevated", "strong"}

    batch = ai_likelihood.predict_ai_likelihood_batch(np.full((3, FEATURE_DIM), 0.5))
    assert batch is not None
    assert len(batch) == 3
    # scalar path rounds to 4 decimals; batch path returns raw probabilities
    assert np.isclose(batch[0], result.probability, atol=5e-5)


def test_committed_artifact_schema_matches_pipeline(monkeypatch, detector_reset):
    import joblib

    from original.ai_likelihood import DEFAULT_ARTIFACT_PATH

    art = joblib.load(DEFAULT_ARTIFACT_PATH)
    assert art["feature_codes"] == list(ALL_FEATURE_CODES)
    assert art["model"].n_features_in_ == FEATURE_DIM
    # Placeholder dims must be masked on both sides of the train/predict
    # boundary; a feature group added to the pipeline but not to masked_codes
    # would go live at predict time against a model that never saw it vary.
    # Compared against the runtime's own set (not a hand-rebuilt union) so this
    # cannot drift, and by equality rather than issubset so an artifact that
    # masks something the runtime does not is caught too.
    assert set(art["masked_codes"]) == set(_MASKED_CODES)
    assert set(TIER18_CODES) <= set(art["masked_codes"])


# ── Additional _load_artifact validation arms ─────────────────────────────────


def test_non_dict_artifact_disables_detector(tmp_path, monkeypatch, detector_reset):
    fixture = _make_fixture_artifact(tmp_path, not_a_dict=True)
    monkeypatch.setenv("AI_LIKELIHOOD_MODEL_PATH", str(fixture))
    from original.ai_likelihood import predict_ai_likelihood, warm

    assert warm() is False
    assert predict_ai_likelihood(np.full(FEATURE_DIM, 0.5)) is None


def test_schema_version_mismatch_disables_detector(tmp_path, monkeypatch, detector_reset):
    fixture = _make_fixture_artifact(tmp_path, schema_version=2)
    monkeypatch.setenv("AI_LIKELIHOOD_MODEL_PATH", str(fixture))
    from original.ai_likelihood import predict_ai_likelihood, warm

    assert warm() is False
    assert predict_ai_likelihood(np.full(FEATURE_DIM, 0.5)) is None


def test_generic_load_exception_disables_detector(tmp_path, monkeypatch, detector_reset):
    """A malformed-but-dict artifact missing a required key raises inside the
    loader (KeyError) — the broad `except Exception` arm must still fail
    closed rather than propagate."""
    fixture = _make_fixture_artifact(tmp_path, drop_key="reference_vectors")
    monkeypatch.setenv("AI_LIKELIHOOD_MODEL_PATH", str(fixture))
    from original.ai_likelihood import predict_ai_likelihood, warm

    assert warm() is False
    assert predict_ai_likelihood(np.full(FEATURE_DIM, 0.5)) is None


def test_import_error_escalating_inconsistent_version_warning_is_tolerated(
    tmp_path, monkeypatch, detector_reset
):
    """If sklearn.exceptions.InconsistentVersionWarning can't be imported, the
    loader just skips the warning escalation (`except ImportError: pass`) and
    still loads a structurally-valid artifact — this is not a fail-closed arm."""
    fixture = _make_fixture_artifact(tmp_path)
    monkeypatch.setenv("AI_LIKELIHOOD_MODEL_PATH", str(fixture))
    monkeypatch.setitem(sys.modules, "sklearn.exceptions", None)
    from original.ai_likelihood import warm

    assert warm() is True


def test_ensure_loaded_skips_reload_when_already_loaded_inside_lock(detector_reset, monkeypatch):
    """Double-checked locking guard: if another thread finished loading while
    this call was waiting on the lock, `_ensure_loaded` must not call
    `_load_artifact` again — it just observes the now-current state."""
    import original.ai_likelihood as ai_likelihood_module

    class _WonTheRaceLock:
        def __enter__(self):
            ai_likelihood_module._state = ai_likelihood_module._READY
            ai_likelihood_module._artifact = {"raced": True}

        def __exit__(self, *exc_info):
            return False

    def _boom():
        raise AssertionError("_load_artifact must not run when state changed under the lock")

    monkeypatch.setattr(ai_likelihood_module, "_lock", _WonTheRaceLock())
    monkeypatch.setattr(ai_likelihood_module, "_load_artifact", _boom)
    assert ai_likelihood_module._state == ai_likelihood_module._UNLOADED
    assert ai_likelihood_module._ensure_loaded() is True
    assert ai_likelihood_module._artifact == {"raced": True}


# ── _band boundary ─────────────────────────────────────────────────────────────


def test_band_boundaries_are_inclusive_on_the_low_side():
    from original.ai_likelihood import _band

    thresholds = {"elevated": 0.6, "strong": 0.9}
    assert _band(0.0, thresholds) == "low"
    assert _band(0.5999, thresholds) == "low"
    assert _band(0.6, thresholds) == "elevated"  # elevated boundary, inclusive
    assert _band(0.8999, thresholds) == "elevated"
    assert _band(0.9, thresholds) == "strong"  # strong boundary, inclusive
    assert _band(1.0, thresholds) == "strong"


# ── predict_ai_likelihood: dimensionality + broad exception guard ─────────────


def test_predict_wrong_length_vector_returns_none(tmp_path, monkeypatch, detector_reset):
    fixture = _make_fixture_artifact(tmp_path)
    monkeypatch.setenv("AI_LIKELIHOOD_MODEL_PATH", str(fixture))
    from original.ai_likelihood import predict_ai_likelihood

    assert predict_ai_likelihood(np.full(FEATURE_DIM - 1, 0.5)) is None


def test_predict_malformed_vector_fails_closed(tmp_path, monkeypatch, detector_reset):
    """A vector that can't be coerced to float64 (e.g. strings) must not
    propagate — the prediction-time `except Exception` fails closed to None."""
    fixture = _make_fixture_artifact(tmp_path)
    monkeypatch.setenv("AI_LIKELIHOOD_MODEL_PATH", str(fixture))
    from original.ai_likelihood import predict_ai_likelihood

    bad_vec = np.array(["not", "a", "number"] * (FEATURE_DIM // 3 + 1))[:FEATURE_DIM]
    assert predict_ai_likelihood(bad_vec) is None


# ── predict_ai_likelihood_batch's arms ─────────────────────────────────────────


def test_batch_missing_artifact_returns_none(tmp_path, monkeypatch, detector_reset):
    monkeypatch.setenv("AI_LIKELIHOOD_MODEL_PATH", str(tmp_path / "nope.joblib"))
    from original.ai_likelihood import predict_ai_likelihood_batch

    assert predict_ai_likelihood_batch(np.full((3, FEATURE_DIM), 0.5)) is None


def test_batch_reshapes_a_single_1d_vector(tmp_path, monkeypatch, detector_reset):
    fixture = _make_fixture_artifact(tmp_path)
    monkeypatch.setenv("AI_LIKELIHOOD_MODEL_PATH", str(fixture))
    from original.ai_likelihood import predict_ai_likelihood, predict_ai_likelihood_batch

    vec = np.full(FEATURE_DIM, 0.5)
    vec[_PPX_IDX] = 0.85
    batch = predict_ai_likelihood_batch(vec)  # 1D input, not (n, FEATURE_DIM)
    assert batch is not None
    assert batch.shape == (1,)
    scalar = predict_ai_likelihood(vec)
    assert np.isclose(batch[0], scalar.probability, atol=5e-5)


def test_batch_empty_input_fails_closed(tmp_path, monkeypatch, detector_reset):
    """An empty batch (0 rows) passes the dimensionality check — shape is
    (0, FEATURE_DIM) — but sklearn's predict_proba refuses a 0-sample input
    and raises; the batch predictor must fail closed to None rather than
    propagate that, exactly like every other predict-time exception here."""
    fixture = _make_fixture_artifact(tmp_path)
    monkeypatch.setenv("AI_LIKELIHOOD_MODEL_PATH", str(fixture))
    from original.ai_likelihood import predict_ai_likelihood_batch

    assert predict_ai_likelihood_batch(np.empty((0, FEATURE_DIM))) is None


def test_batch_mixed_none_and_vector_rows_fails_closed(tmp_path, monkeypatch, detector_reset):
    """blend.py's caller filters None window vectors out before calling the
    batch predictor, but the batch predictor is called from more than one
    place — it must fail closed on its own if ever handed a ragged/None-mixed
    input rather than raise (np.asarray(..., dtype=float64) on a list mixing
    None with a full vector raises ValueError: inhomogeneous shape)."""
    fixture = _make_fixture_artifact(tmp_path)
    monkeypatch.setenv("AI_LIKELIHOOD_MODEL_PATH", str(fixture))
    from original.ai_likelihood import predict_ai_likelihood_batch

    mixed = [None, np.full(FEATURE_DIM, 0.5)]
    assert predict_ai_likelihood_batch(mixed) is None
