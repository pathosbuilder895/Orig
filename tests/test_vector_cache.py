"""validation/vector_cache.py — the battery's opt-in extraction memo must be
invisible in the vectors it returns and impossible to serve stale."""
from __future__ import annotations

import numpy as np
import pytest

from validation import vector_cache


class TestKey:
    def test_key_changes_with_text(self):
        assert vector_cache.vector_cache_key("a", "tfidf") != vector_cache.vector_cache_key("b", "tfidf")

    def test_key_changes_with_semantic_backend(self):
        assert vector_cache.vector_cache_key("a", "st") != vector_cache.vector_cache_key("a", "tfidf")

    def test_key_changes_when_a_feature_group_is_toggled(self):
        """G2b/G6 discard 'uniformity' for one leg; a vector extracted under
        that state must never be served to a leg running with it disabled."""
        from original.constants import DISABLED_FEATURE_GROUPS

        saved = set(DISABLED_FEATURE_GROUPS)
        try:
            DISABLED_FEATURE_GROUPS.add("uniformity")
            k_disabled = vector_cache.vector_cache_key("a", "tfidf")
            DISABLED_FEATURE_GROUPS.discard("uniformity")
            k_enabled = vector_cache.vector_cache_key("a", "tfidf")
        finally:
            DISABLED_FEATURE_GROUPS.clear()
            DISABLED_FEATURE_GROUPS.update(saved)
        assert k_disabled != k_enabled


class TestCachedFunction:
    def _extract_counter(self):
        calls = []

        def extract(text, keystroke_data=None):
            calls.append((text, keystroke_data))
            return np.full(3, float(len(text)))

        return extract, calls

    def test_second_call_is_served_from_disk_and_identical(self, tmp_path):
        extract, calls = self._extract_counter()
        cached = vector_cache.make_cached_feature_vector(tmp_path, extract, "tfidf")
        first = cached("hello")
        second = cached("hello")
        assert len(calls) == 1
        np.testing.assert_array_equal(first, second)
        assert list((tmp_path).glob("*.npy"))

    def test_distinct_texts_are_extracted_separately(self, tmp_path):
        extract, calls = self._extract_counter()
        cached = vector_cache.make_cached_feature_vector(tmp_path, extract, "tfidf")
        cached("one")
        cached("two")
        assert len(calls) == 2

    def test_keystroke_requests_bypass_the_cache(self, tmp_path):
        extract, calls = self._extract_counter()
        cached = vector_cache.make_cached_feature_vector(tmp_path, extract, "tfidf")
        cached("x", keystroke_data={"k": 1})
        cached("x", keystroke_data={"k": 1})
        assert len(calls) == 2
        assert calls[0][1] == {"k": 1}
        assert not list(tmp_path.glob("*.npy"))


class TestInstall:
    def test_install_patches_route_bindings_and_restore_reverts(self, tmp_path, monkeypatch):
        from original.routers import students_baseline, students_scoring

        monkeypatch.setattr(vector_cache, "semantic_backend", lambda: "tfidf")
        before = (students_baseline.feature_vector, students_scoring.feature_vector)
        restore = vector_cache.install_vector_cache(tmp_path)
        try:
            assert students_baseline.feature_vector is not before[0]
            assert students_scoring.feature_vector is not before[1]
            assert students_baseline.feature_vector is students_scoring.feature_vector
            assert students_baseline.feature_vector.__wrapped__ is before[0]
        finally:
            restore()
        assert (students_baseline.feature_vector, students_scoring.feature_vector) == before

    def test_env_unset_is_a_no_op(self, monkeypatch):
        monkeypatch.delenv(vector_cache.ENV_VAR, raising=False)
        restore, description = vector_cache.maybe_install_from_env()
        assert description is None
        restore()  # must not raise

    def test_env_set_installs_and_describes(self, tmp_path, monkeypatch):
        from original.routers import students_baseline

        monkeypatch.setattr(vector_cache, "semantic_backend", lambda: "tfidf")
        monkeypatch.setenv(vector_cache.ENV_VAR, str(tmp_path))
        before = students_baseline.feature_vector
        restore, description = vector_cache.maybe_install_from_env()
        try:
            assert description["dir"] == str(tmp_path.resolve())
            assert description["semantic_backend"] == "tfidf"
            assert students_baseline.feature_vector is not before
        finally:
            restore()
        assert students_baseline.feature_vector is before


class TestThroughLiveRoutes:
    def test_baseline_uploads_reuse_one_extraction_per_text(
        self, live_client, store_reset, tmp_path, monkeypatch
    ):
        """The battery's real path: two students upload the same text via
        /students/{sid}/baseline; extraction runs once, the second upload is
        served from disk, and the stored vectors are identical."""
        from original import store
        from original.features import pipeline

        calls = []
        real = pipeline.feature_vector

        def counting(text, keystroke_data=None):
            calls.append(text)
            return real(text, keystroke_data=keystroke_data)

        monkeypatch.setattr(pipeline, "feature_vector", counting)
        monkeypatch.setattr(vector_cache, "semantic_backend", lambda: "tfidf")
        monkeypatch.setenv(vector_cache.ENV_VAR, str(tmp_path))
        restore, description = vector_cache.maybe_install_from_env()
        text = "The quick brown fox jumps over the lazy dog. " * 40
        try:
            for sid in ("demo:vc_a", "demo:vc_b"):
                r = live_client.post(
                    f"/students/{sid}/baseline",
                    json={"text": text, "provenance": "verified", "submitted_at": "2026-01-01"},
                )
                assert r.status_code == 200, r.text
        finally:
            restore()
        assert len(calls) == 1
        assert len(list(tmp_path.glob("*.npy"))) == 1
        a = store.get("demo:vc_a").samples[0].vector
        b = store.get("demo:vc_b").samples[0].vector
        np.testing.assert_array_equal(a, b)
