"""
tests/context/test_genre_model.py — the fail-closed loader and inference.

Task 11 of docs/superpowers/plans/2026-08-08-genre-resolution-v2.md.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from original.constants import GENRE_UNKNOWN
from original.context import genre_v2

_ARTIFACT = Path("original/data/genre_model_v1.json")


@pytest.fixture(autouse=True)
def _reset():
    genre_v2._reset_artifact_for_test()
    yield
    genre_v2._reset_artifact_for_test()


def _mutated(tmp_path: Path, **changes) -> str:
    artifact = json.loads(_ARTIFACT.read_text())
    artifact.update(changes)
    path = tmp_path / "mutated.json"
    path.write_text(json.dumps(artifact))
    return str(path)


class TestFailClosed:
    def test_missing_artifact_abstains(self, monkeypatch, tmp_path):
        monkeypatch.setenv("GENRE_MODEL_PATH", str(tmp_path / "nope.json"))
        out = genre_v2.predict("Any text at all. " * 20)
        assert out["primary"] == GENRE_UNKNOWN
        assert out["confidence"] == 0.0

    def test_a_failed_load_does_not_fall_back_to_the_rules(self, monkeypatch, tmp_path):
        """Silently swapping mechanisms is how a measurement stops meaning
        what its label says. The rules would happily claim creative_fiction
        for this text; a broken model must abstain instead."""
        text = "I went down to the river myself, and I sat there thinking. " * 20
        assert genre_v2._resolve_by_rules(text)["primary"] == "personal_essay"
        monkeypatch.setenv("GENRE_MODEL_PATH", str(tmp_path / "nope.json"))
        assert genre_v2.predict(text)["primary"] == GENRE_UNKNOWN
        assert genre_v2.resolve(text)["primary"] == GENRE_UNKNOWN

    def test_schema_drift_is_refused(self, monkeypatch, tmp_path):
        monkeypatch.setenv("GENRE_MODEL_PATH", _mutated(tmp_path, schema_version=99))
        assert genre_v2.predict("Prose. " * 30)["primary"] == GENRE_UNKNOWN

    def test_signal_order_drift_is_refused(self, monkeypatch, tmp_path):
        reordered = list(reversed(genre_v2.SIGNAL_ORDER))
        monkeypatch.setenv("GENRE_MODEL_PATH", _mutated(tmp_path, signal_order=reordered))
        assert genre_v2.predict("Prose. " * 30)["primary"] == GENRE_UNKNOWN

    def test_reference_prediction_drift_is_refused(self, monkeypatch, tmp_path):
        artifact = json.loads(_ARTIFACT.read_text())
        shifted = [[min(1.0, p + 0.5) for p in row] for row in artifact["reference_probabilities"]]
        monkeypatch.setenv("GENRE_MODEL_PATH", _mutated(tmp_path, reference_probabilities=shifted))
        assert genre_v2.predict("Prose. " * 30)["primary"] == GENRE_UNKNOWN

    def test_a_malformed_artifact_is_refused_not_raised(self, monkeypatch, tmp_path):
        path = tmp_path / "garbage.json"
        path.write_text("{not json at all")
        monkeypatch.setenv("GENRE_MODEL_PATH", str(path))
        assert genre_v2.predict("Prose. " * 30)["primary"] == GENRE_UNKNOWN

    def test_a_zero_scale_column_is_refused(self, monkeypatch, tmp_path):
        artifact = json.loads(_ARTIFACT.read_text())
        scale = list(artifact["scale"])
        scale[0] = 0.0
        monkeypatch.setenv("GENRE_MODEL_PATH", _mutated(tmp_path, scale=scale))
        assert genre_v2.predict("Prose. " * 30)["primary"] == GENRE_UNKNOWN

    def test_a_non_object_artifact_is_refused(self, monkeypatch, tmp_path):
        """The artifact must be a JSON object — a bare list or scalar at the
        top level fails the very first shape check, before any field is
        even looked up."""
        path = tmp_path / "not_a_dict.json"
        path.write_text(json.dumps([1, 2, 3]))
        monkeypatch.setenv("GENRE_MODEL_PATH", str(path))
        out = genre_v2.predict("Prose. " * 30)
        assert out["primary"] == GENRE_UNKNOWN
        assert out["confidence"] == 0.0

    def test_a_coefficient_shape_mismatch_is_refused(self, monkeypatch, tmp_path):
        """One fewer coefficient row than there are classes — the kind of
        drift a hand-edited or half-written artifact could produce."""
        artifact = json.loads(_ARTIFACT.read_text())
        coef = artifact["coef"][:-1]
        monkeypatch.setenv("GENRE_MODEL_PATH", _mutated(tmp_path, coef=coef))
        assert genre_v2.predict("Prose. " * 30)["primary"] == GENRE_UNKNOWN

    def test_an_intercept_shape_mismatch_is_refused(self, monkeypatch, tmp_path):
        artifact = json.loads(_ARTIFACT.read_text())
        intercept = artifact["intercept"][:-1]
        monkeypatch.setenv("GENRE_MODEL_PATH", _mutated(tmp_path, intercept=intercept))
        assert genre_v2.predict("Prose. " * 30)["primary"] == GENRE_UNKNOWN

    def test_a_scaler_shape_mismatch_is_refused(self, monkeypatch, tmp_path):
        """`mean`/`scale` must be exactly SIGNAL_ORDER-wide; a truncated
        standardiser vector is unusable, not merely imprecise."""
        artifact = json.loads(_ARTIFACT.read_text())
        mean = artifact["mean"][:-1]
        monkeypatch.setenv("GENRE_MODEL_PATH", _mutated(tmp_path, mean=mean))
        assert genre_v2.predict("Prose. " * 30)["primary"] == GENRE_UNKNOWN

    def test_an_invalid_confidence_floor_is_refused(self, monkeypatch, tmp_path):
        """`confidence_min` must sit strictly inside (0, 1); a floor of
        exactly 1.0 could never be cleared by any prediction and is a sign
        the artifact itself is broken, not merely strict."""
        monkeypatch.setenv("GENRE_MODEL_PATH", _mutated(tmp_path, confidence_min=1.0))
        assert genre_v2.predict("Prose. " * 30)["primary"] == GENRE_UNKNOWN


class TestEnsureLoaded:
    def test_skips_reload_if_another_thread_already_loaded_under_the_lock(self, monkeypatch):
        """Double-checked locking: the outer `_state == _UNLOADED` check and
        the one repeated inside the lock can legitimately disagree if
        another thread finished loading in between. Simulated here with a
        fake lock whose __enter__ advances state, standing in for that
        thread — `_load_artifact` must not be called a second time."""
        genre_v2._state = genre_v2._UNLOADED

        class _RacyLock:
            def __enter__(self):
                genre_v2._state = genre_v2._READY
                return self

            def __exit__(self, *exc_info):
                return False

        monkeypatch.setattr(genre_v2, "_lock", _RacyLock())

        def _must_not_reload():
            raise AssertionError("must not reload once another thread already did")

        monkeypatch.setattr(genre_v2, "_load_artifact", _must_not_reload)
        assert genre_v2._ensure_loaded() is True


class TestConfidenceMin:
    def test_falls_back_to_the_constant_when_the_artifact_will_not_load(
        self, monkeypatch, tmp_path
    ):
        """`_confidence_min` has its own fallback, independent of
        `predict`'s abstention: when there is no usable artifact it must
        still return a real floor rather than propagating the failure."""
        from original.constants import GENRE_CONFIDENCE_MIN

        monkeypatch.setenv("GENRE_MODEL_PATH", str(tmp_path / "nope.json"))
        assert genre_v2._confidence_min() == GENRE_CONFIDENCE_MIN


class TestInference:
    def test_probabilities_sum_to_one(self):
        probabilities = genre_v2._class_probabilities(genre_v2.signal_vector("Prose here. " * 30))
        assert abs(sum(probabilities.values()) - 1.0) < 1e-9

    def test_probabilities_cover_exactly_the_artifact_classes(self):
        artifact = json.loads(_ARTIFACT.read_text())
        probabilities = genre_v2._class_probabilities(genre_v2.signal_vector("Prose. " * 30))
        assert set(probabilities) == set(artifact["classes"])

    def test_low_confidence_abstains(self, monkeypatch):
        monkeypatch.setattr(genre_v2, "_confidence_min", lambda: 0.999)
        assert genre_v2.predict("Ambiguous prose of no clear kind. " * 20)["primary"] == (
            GENRE_UNKNOWN
        )

    def test_a_confident_prediction_is_claimed(self, monkeypatch):
        monkeypatch.setattr(genre_v2, "_confidence_min", lambda: 0.0)
        out = genre_v2.predict("He said, “we go now.” She replied nothing at all. " * 20)
        assert out["primary"] != GENRE_UNKNOWN
        assert 0.0 < out["confidence"] <= 1.0

    def test_confidence_is_the_winning_class_probability(self, monkeypatch):
        monkeypatch.setattr(genre_v2, "_confidence_min", lambda: 0.0)
        text = "The argument turns upon a distinction seldom drawn. " * 25
        out = genre_v2.predict(text)
        probabilities = genre_v2._class_probabilities(genre_v2.signal_vector(text))
        assert out["confidence"] == pytest.approx(max(probabilities.values()))

    def test_empty_text_abstains(self):
        assert genre_v2.predict("")["primary"] == GENRE_UNKNOWN


class TestNoSklearnAtInference:
    def test_inference_does_not_import_sklearn(self, monkeypatch):
        """sklearn is absent from the base requirements.txt — it appears only
        in the dev and demo locks. A resolver that needed it would break on a
        plain install."""
        import sys

        monkeypatch.setitem(sys.modules, "sklearn", None)
        monkeypatch.setitem(sys.modules, "sklearn.linear_model", None)
        out = genre_v2.predict("Prose of some kind. " * 30)
        assert out["primary"] in {*json.loads(_ARTIFACT.read_text())["classes"], GENRE_UNKNOWN}


class TestResolveUsesTheModel:
    def test_resolve_routes_through_predict(self, monkeypatch):
        called = {}

        def _fake(text, citation_data=None):
            called["yes"] = True
            return {"primary": "scholarly_essay", "confidence": 0.9, "secondary": None}

        monkeypatch.setattr(genre_v2, "predict", _fake)
        assert genre_v2.resolve("Prose. " * 30)["primary"] == "scholarly_essay"
        assert called

    def test_markup_still_short_circuits_ahead_of_the_model(self, monkeypatch):
        def _explode(text, citation_data=None):
            raise AssertionError("markup must be decided before the model runs")

        monkeypatch.setattr(genre_v2, "predict", _explode)
        text = "# Heading\n- one\n- two\n- three\n1. step\n"
        assert genre_v2.resolve(text)["primary"] == "structured_template"
