"""
tests/validation/test_genre_artifact.py — shape of the committed genre model.

Task 10 of docs/superpowers/plans/2026-08-08-genre-resolution-v2.md.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from original.context import genre_v2

_ARTIFACT = Path("original/data/genre_model_v1.json")


@pytest.fixture(scope="module")
def artifact():
    return json.loads(_ARTIFACT.read_text())


class TestArtifactShape:
    def test_schema_version_is_pinned(self, artifact):
        assert artifact["schema_version"] == 1

    def test_signal_order_matches_the_extractor(self, artifact):
        """A reordered extractor would silently feed the model shuffled
        columns — confident nonsense rather than a visible failure."""
        assert tuple(artifact["signal_order"]) == genre_v2.SIGNAL_ORDER

    def test_coefficient_matrix_matches_classes_and_signals(self, artifact):
        assert len(artifact["coef"]) == len(artifact["classes"])
        assert all(len(row) == len(genre_v2.SIGNAL_ORDER) for row in artifact["coef"])
        assert len(artifact["intercept"]) == len(artifact["classes"])

    def test_scaler_is_the_right_width_with_no_zero_scale(self, artifact):
        assert len(artifact["mean"]) == len(genre_v2.SIGNAL_ORDER)
        assert len(artifact["scale"]) == len(genre_v2.SIGNAL_ORDER)
        assert all(s > 0 for s in artifact["scale"])

    def test_confidence_floor_is_a_real_probability(self, artifact):
        assert 0.0 < artifact["confidence_min"] < 1.0


class TestClassSet:
    def test_excludes_the_labels_with_no_corpus_evidence(self, artifact):
        for label in ("blog_post", "correspondence", "structured_template", "unknown"):
            assert label not in artifact["classes"]

    def test_excludes_sermon(self, artifact):
        """One author (Edwards) — it would be an author detector."""
        assert "sermon" not in artifact["classes"]

    def test_every_class_is_a_known_genre_label(self, artifact):
        from original.constants import GENRE_LABELS

        assert set(artifact["classes"]) <= set(GENRE_LABELS)


class TestProvenance:
    def test_reference_predictions_are_present_for_drift_detection(self, artifact):
        assert len(artifact["reference_signals"]) >= 3
        assert len(artifact["reference_probabilities"]) == len(artifact["reference_signals"])

    def test_artifact_pins_the_codebook_and_labels_it_was_derived_from(self, artifact):
        codebook = Path("validation/genre_2026-08/CODEBOOK.md")
        labels = Path("validation/genre_2026-08/labels.json")
        assert artifact["codebook_sha256"] == hashlib.sha256(codebook.read_bytes()).hexdigest()
        assert artifact["labels_sha256"] == hashlib.sha256(labels.read_bytes()).hexdigest()

    def test_derivation_size_is_recorded(self, artifact):
        assert artifact["n_derivation"] > 0


class TestNoPickle:
    def test_the_artifact_is_plain_json(self):
        """Committed to git, so a pickle here would be a code-execution
        surface — and it keeps inference free of any sklearn dependency."""
        json.loads(_ARTIFACT.read_text())

    def test_the_artifact_holds_no_opaque_blobs(self, artifact):
        def _plain(value) -> bool:
            if isinstance(value, dict):
                return all(_plain(v) for v in value.values())
            if isinstance(value, list):
                return all(_plain(v) for v in value)
            return value is None or isinstance(value, (str, int, float, bool))

        assert _plain(artifact)
