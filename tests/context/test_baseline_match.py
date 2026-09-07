"""
tests/context/test_baseline_match.py — Phase 4 baseline matching tests.
"""

from __future__ import annotations

import numpy as np
import pytest

import original.context.baseline_match as baseline_match_module
from original.constants import FEATURE_DIM
from original.context.baseline_match import (
    _ensure_tfidf_vectorizer,
    _genre_similarity,
    _topic_similarity,
    _recency_weight,
    _transform_centroid,
    ensure_sample_context_metadata,
    genre_covered_by_baseline,
    match_baseline_cluster,
)
from original.context.manifest import ContextManifest
from original.quantum.state import BaselineSample, StudentState


# ── Helpers ──────────────────────────────────────────────────────────────────


def _sample(text: str, *, genre: str = None, centroid: np.ndarray = None) -> BaselineSample:
    return BaselineSample(
        text=text,
        vector=np.full(FEATURE_DIM, 0.5, dtype=np.float64),
        provenance="verified",
        auth_weight=1.0,
        genre=genre,
        topic_centroid=centroid,
    )


def _manifest(genre: str = "blog_post") -> ContextManifest:
    return ContextManifest(
        submission_id="sub",
        language={},
        genre={"primary": genre},
        topic={},
        length_regime="standard",
        citations={},
        composition_mode={},
        weight_modifications={"amplify_codes": [], "attenuate_codes": [], "mute_codes": []},
        anchor_tiers=[4, 6],
        baseline_match={},
        flags=[],
        created_at="",
    )


# ══════════════════════════════════════════════════════════════════════════════
# Helper functions
# ══════════════════════════════════════════════════════════════════════════════


class TestGenreSimilarity:
    def test_same_label_returns_one(self):
        assert _genre_similarity("academic_exegesis", "academic_exegesis") == 1.0

    def test_same_family_returns_half(self):
        # academic_exegesis and scholarly_essay share family="academic".
        assert _genre_similarity("academic_exegesis", "scholarly_essay") == 0.5

    def test_different_family_returns_zero(self):
        assert _genre_similarity("academic_exegesis", "creative_fiction") == 0.0

    def test_either_none_returns_zero(self):
        # Conservative: an unknown sample/submission genre cannot claim
        # similarity. Returning 0 instead of 0.5 prevents under-tagged
        # samples from biasing the cluster.
        assert _genre_similarity(None, "academic_exegesis") == 0.0
        assert _genre_similarity("academic_exegesis", None) == 0.0
        assert _genre_similarity(None, None) == 0.0


class TestTopicSimilarity:
    def test_identical_centroids(self):
        a = np.array([1.0, 0.0, 0.0])
        assert abs(_topic_similarity(a, a) - 1.0) < 1e-9

    def test_orthogonal_centroids(self):
        a = np.array([1.0, 0.0, 0.0])
        b = np.array([0.0, 1.0, 0.0])
        assert abs(_topic_similarity(a, b)) < 1e-9

    def test_either_none_returns_neutral(self):
        a = np.array([1.0, 0.0, 0.0])
        # Different from genre handling: a missing centroid is the legacy
        # default state, not a confident "unknown topic" judgment.
        assert _topic_similarity(None, a) == 0.5
        assert _topic_similarity(a, None) == 0.5

    def test_zero_norm_returns_neutral(self):
        z = np.zeros(3)
        a = np.array([1.0, 0.0, 0.0])
        assert _topic_similarity(z, a) == 0.5


class TestRecencyWeight:
    def test_oldest_zero_newest_one(self):
        assert _recency_weight(0, 5) == 0.0
        assert _recency_weight(4, 5) == 1.0

    def test_midpoint_half(self):
        assert _recency_weight(2, 5) == 0.5

    def test_single_sample_returns_one(self):
        assert _recency_weight(0, 1) == 1.0


# ══════════════════════════════════════════════════════════════════════════════
# Per-student TF-IDF vectoriser
# ══════════════════════════════════════════════════════════════════════════════


class TestEnsureTfidfVectorizer:
    def test_returns_none_when_sklearn_unavailable(self, monkeypatch):
        # Simulates a dev environment without sklearn — the module-level
        # `TfidfVectorizer = None` fallback in the try/except import block.
        monkeypatch.setattr(baseline_match_module, "TfidfVectorizer", None)
        state = StudentState(student_id="s", samples=[_sample("Some real prose here.")])
        assert _ensure_tfidf_vectorizer(state) is None

    def test_returns_cached_vectorizer_without_refitting(self):
        sentinel = object()
        state = StudentState(student_id="s", samples=[_sample("Some real prose here.")])
        state._tfidf_vectorizer = sentinel
        assert _ensure_tfidf_vectorizer(state) is sentinel

    def test_returns_none_when_no_samples(self):
        state = StudentState(student_id="s", samples=[])
        assert _ensure_tfidf_vectorizer(state) is None

    def test_returns_none_when_all_sample_texts_blank(self):
        state = StudentState(
            student_id="s",
            samples=[_sample(""), _sample("   ")],
        )
        assert _ensure_tfidf_vectorizer(state) is None

    def test_returns_none_when_vocabulary_empty_after_preprocessing(self):
        # Non-blank text that nonetheless tokenises to nothing under the
        # \b\w\w+\b pattern (punctuation-only) — sklearn's fit() raises
        # ValueError("empty vocabulary...") which must be swallowed.
        state = StudentState(
            student_id="s",
            samples=[_sample("..."), _sample("!!!"), _sample("??? ---")],
        )
        assert _ensure_tfidf_vectorizer(state) is None

    def test_fits_and_caches_over_real_texts(self):
        state = StudentState(
            student_id="s",
            samples=[
                _sample("Plato writes about the form of justice extensively."),
                _sample("Modern democracy thrives when citizens deliberate."),
            ],
        )
        vec = _ensure_tfidf_vectorizer(state)
        assert vec is not None
        assert state._tfidf_vectorizer is vec


class TestTransformCentroid:
    def test_blank_text_returns_none(self):
        state = StudentState(student_id="s", samples=[_sample("Real prose about justice.")])
        vec = _ensure_tfidf_vectorizer(state)
        assert _transform_centroid(vec, "   ") is None

    def test_transform_exception_is_swallowed(self):
        class _ExplodingVectorizer:
            def transform(self, texts):
                raise RuntimeError("synthetic transform failure")

        assert _transform_centroid(_ExplodingVectorizer(), "non-blank text") is None

    def test_successful_transform_returns_float64_vector(self):
        state = StudentState(
            student_id="s",
            samples=[_sample("Plato writes about the form of justice extensively.")],
        )
        vec = _ensure_tfidf_vectorizer(state)
        centroid = _transform_centroid(vec, "Plato writes about justice.")
        assert centroid is not None
        assert centroid.dtype == np.float64
        assert centroid.ndim == 1


# ══════════════════════════════════════════════════════════════════════════════
# Lazy backfill
# ══════════════════════════════════════════════════════════════════════════════


class TestEnsureSampleContextMetadata:
    def test_lazy_backfill_populates_legacy_samples(self):
        # 3 legacy samples (genre=None, topic_centroid=None) → all populated.
        state = StudentState(
            student_id="s",
            samples=[
                _sample("Plato writes about the form of justice extensively in the Republic."),
                _sample("Modern democracy thrives only when citizens deliberate honestly."),
                _sample("The pizza recipe varies widely across regions of Italy."),
            ],
        )
        mutated = ensure_sample_context_metadata(state)
        assert mutated is True
        for s in state.samples:
            assert s.genre is not None
            assert s.topic_centroid is not None
            assert s.topic_centroid.ndim == 1

    def test_idempotent(self):
        # Second call on already-populated samples should NOT mutate again.
        state = StudentState(
            student_id="s",
            samples=[
                _sample(
                    "Plato discusses the soul.",
                    genre="academic_exegesis",
                    centroid=np.array([0.5, 0.5]),
                ),
            ],
        )
        mutated_first = ensure_sample_context_metadata(state)
        mutated_second = ensure_sample_context_metadata(state)
        assert mutated_first is False  # already populated
        assert mutated_second is False  # still no change

    def test_no_samples_returns_false(self):
        state = StudentState(student_id="s", samples=[])
        assert ensure_sample_context_metadata(state) is False

    def test_genre_resolver_falsy_primary_skips_mutation(self, monkeypatch):
        # resolve_genre() can legitimately return {"primary": None} (or a
        # falsy label) — the `if g:` guard must skip the assignment rather
        # than writing a falsy genre onto the sample.
        monkeypatch.setattr(
            baseline_match_module, "resolve_genre", lambda text: {"primary": None}
        )
        state = StudentState(student_id="s", samples=[_sample("Some real prose here.")])
        # Topic backfill can still mutate independently of genre, so pin the
        # genre-specific behaviour directly rather than asserting on the
        # overall `mutated` return value.
        ensure_sample_context_metadata(state)
        assert state.samples[0].genre is None

    def test_genre_resolver_exception_is_logged_and_skipped(self, monkeypatch):
        def _explode(text):
            raise RuntimeError("synthetic genre-resolution failure")

        monkeypatch.setattr(baseline_match_module, "resolve_genre", _explode)
        state = StudentState(student_id="s", samples=[_sample("Some real prose here.")])
        # Must not raise — the exception is caught and logged.
        ensure_sample_context_metadata(state)
        assert state.samples[0].genre is None

    def test_topic_centroid_transform_failure_leaves_centroid_none(self):
        # Pre-cache a fake vectoriser on the state so _ensure_tfidf_vectorizer
        # returns it without refitting (cached is not None), and whose
        # transform() always fails — exercising the `centroid is not None`
        # False branch (the loop continues without mutating topic_centroid).
        class _ExplodingVectorizer:
            def transform(self, texts):
                raise RuntimeError("synthetic transform failure")

        state = StudentState(
            student_id="s",
            samples=[_sample("Some real prose that should get a genre.")],
        )
        state._tfidf_vectorizer = _ExplodingVectorizer()
        mutated = ensure_sample_context_metadata(state)
        # Genre backfill still succeeds (real resolve_genre), so `mutated` is
        # True — but the topic centroid must remain unset.
        assert mutated is True
        assert state.samples[0].genre is not None
        assert state.samples[0].topic_centroid is None


# ══════════════════════════════════════════════════════════════════════════════
# match_baseline_cluster
# ══════════════════════════════════════════════════════════════════════════════


class TestMatchBaselineCluster:
    def test_empty_state_returns_anchor_only(self):
        state = StudentState(student_id="s", samples=[])
        idx, anchor_only = match_baseline_cluster(_manifest(), state)
        assert idx == []
        assert anchor_only is True

    def test_prefers_same_genre(self):
        # 3 academic samples + 2 fiction samples; submission=academic →
        # the academic samples should rank highest (genre similarity 1.0
        # vs 0.0/0.5 for the others).
        state = StudentState(
            student_id="s",
            samples=[
                _sample("Academic 1", genre="academic_exegesis"),
                _sample("Academic 2", genre="academic_exegesis"),
                _sample("Academic 3", genre="academic_exegesis"),
                _sample("Fiction 1", genre="creative_fiction"),
                _sample("Fiction 2", genre="creative_fiction"),
            ],
        )
        m = _manifest("academic_exegesis")
        idx, anchor_only = match_baseline_cluster(
            m,
            state,
            submission_text="Academic submission text",
        )
        # Top-N should not include fiction indices (3 or 4).
        assert anchor_only is False
        assert len(idx) >= 2
        assert all(i < 3 for i in idx), f"Fiction sample picked: {idx}"

    def test_prefers_recent_when_genre_uniform(self):
        # All same genre, all (effectively) same topic — recency tiebreaker
        # should pick the highest indices.
        state = StudentState(
            student_id="s",
            samples=[
                _sample("Same genre A", genre="blog_post"),
                _sample("Same genre B", genre="blog_post"),
                _sample("Same genre C", genre="blog_post"),
                _sample("Same genre D", genre="blog_post"),
            ],
        )
        idx, anchor_only = match_baseline_cluster(
            _manifest("blog_post"),
            state,
            submission_text="Same genre submission",
        )
        # n_top defaults to 3; recency-favoured → [3, 2, 1].
        assert idx[0] == 3, f"most-recent sample should rank first; got {idx}"

    def test_anchor_only_when_no_matches_above_threshold(self):
        # All samples have genre that doesn't match AND no centroid yet,
        # so genre_sim=0 + topic_sim=0.5 + recency tiny → composite < 0.5.
        state = StudentState(
            student_id="s",
            samples=[
                _sample("Random A", genre="creative_fiction"),
                _sample("Random B", genre="creative_fiction"),
            ],
        )
        idx, anchor_only = match_baseline_cluster(
            _manifest("academic_exegesis"),
            state,
            submission_text=None,
            min_similarity=0.95,  # pull threshold up — force fallback
        )
        assert anchor_only is True
        assert idx == []

    def test_returns_at_most_n_top(self):
        state = StudentState(
            student_id="s", samples=[_sample(f"Sample {i}", genre="blog_post") for i in range(10)]
        )
        idx, _ = match_baseline_cluster(
            _manifest("blog_post"),
            state,
            submission_text="A blog post submission",
            n_top=3,
        )
        assert len(idx) <= 3

    def test_submission_text_with_no_usable_vectorizer_stays_topic_neutral(self):
        # All baseline sample texts are blank → _ensure_tfidf_vectorizer
        # returns None even though submission_text is provided, so the
        # `if vec is not None:` branch is skipped and sub_centroid stays
        # None — topic similarity falls back to the 0.5 neutral for every
        # sample rather than raising.
        state = StudentState(
            student_id="s",
            samples=[
                _sample("", genre="blog_post"),
                _sample("   ", genre="blog_post"),
            ],
        )
        idx, anchor_only = match_baseline_cluster(
            _manifest("blog_post"),
            state,
            submission_text="A non-blank submission with real words.",
        )
        # genre_sim=1.0 + topic_sim=0.5(neutral) + recency → composite >= 0.5
        # for both samples, so this reaches a real (non-anchor-only) match.
        assert anchor_only is False
        assert idx != []


# ══════════════════════════════════════════════════════════════════════════════
# Genre coverage (2026-08 cross-genre study — feeds weighting.py's
# genre_covered param, a DIFFERENT question than anchor_only above: has this
# exact genre been SEEN, vs are any samples contextually similar enough to
# trust for comparison features)
# ══════════════════════════════════════════════════════════════════════════════


class TestGenreCoveredByBaseline:
    def test_covered_when_exact_genre_present(self):
        state = StudentState(
            student_id="s",
            samples=[_sample("A", genre="academic_exegesis"), _sample("B", genre="blog_post")],
        )
        assert genre_covered_by_baseline(_manifest("academic_exegesis"), state) is True

    def test_not_covered_when_genre_absent(self):
        state = StudentState(
            student_id="s",
            samples=[_sample("A", genre="academic_exegesis"), _sample("B", genre="blog_post")],
        )
        assert genre_covered_by_baseline(_manifest("creative_fiction"), state) is False

    def test_family_match_is_not_enough(self):
        # _genre_similarity gives a family match 0.5 credit for cluster
        # SELECTION, but genre_covered is stricter -- same LABEL only, not
        # same family. A student who's only ever written sermons should
        # still count devotional_reflection as unseen even though both are
        # in the "homiletic" family.
        state = StudentState(student_id="s", samples=[_sample("A", genre="sermon")])
        assert genre_covered_by_baseline(_manifest("devotional_reflection"), state) is False

    def test_unknown_submission_genre_defaults_covered(self):
        # An unclassified genre is never treated as "definitely novel".
        state = StudentState(student_id="s", samples=[_sample("A", genre="blog_post")])
        assert genre_covered_by_baseline(_manifest(genre=None), state) is True

    def test_no_baseline_genres_known_defaults_covered(self):
        # Every sample pre-dates genre backfill (all None) -- can't call
        # anything "uncovered" against an entirely unknown baseline.
        state = StudentState(
            student_id="s", samples=[_sample("A", genre=None), _sample("B", genre=None)]
        )
        assert genre_covered_by_baseline(_manifest("academic_exegesis"), state) is True

    def test_empty_state_defaults_covered(self):
        state = StudentState(student_id="s", samples=[])
        assert genre_covered_by_baseline(_manifest("academic_exegesis"), state) is True

    def test_accepts_dict_manifest(self):
        state = StudentState(student_id="s", samples=[_sample("A", genre="blog_post")])
        d = _manifest("blog_post").__dict__.copy()
        assert genre_covered_by_baseline(d, state) is True
        d["genre"] = {"primary": "creative_fiction"}
        assert genre_covered_by_baseline(d, state) is False


# ══════════════════════════════════════════════════════════════════════════════
# Integration with compute_full_features
# ══════════════════════════════════════════════════════════════════════════════


class TestComputeFullFeaturesWithBaselineIndices:
    def test_subset_indices_filter_baseline(self):
        # Two baseline texts that differ stylistically; computing with one
        # subset vs the other should yield different char-trigram divergence.
        from original.features.pipeline import compute_full_features

        text = "This is the submission text about something specific and unusual."
        baseline = [
            "An academic paper analysing constitutional theory at length and in great detail.",
            "Hey what's up — quick blog post, totally informal vibe, happy Monday yo!",
        ]
        f_full = compute_full_features(text, baseline)
        f_sub0 = compute_full_features(text, baseline, baseline_indices=[0])
        f_sub1 = compute_full_features(text, baseline, baseline_indices=[1])

        # The two subsets should produce different comparison features —
        # baseline_indices is actually filtering, not just decorative.
        # Use char-trigram divergence which is the most baseline-sensitive.
        key = "char_trigram_profile_divergence"
        assert f_sub0[key] != f_sub1[key], f"subset 0 and subset 1 produced identical {key}"

    def test_empty_indices_yields_neutral_placeholder(self):
        from original.features.pipeline import compute_full_features

        text = "Submission text."
        baseline = ["Baseline 1.", "Baseline 2."]
        f = compute_full_features(text, baseline, baseline_indices=[])
        # With empty cluster, comparison features stay at 0.5 placeholder.
        assert f["char_trigram_profile_divergence"] == 0.5

    def test_none_indices_preserves_phase1(self):
        from original.features.pipeline import compute_full_features

        text = "Submission text."
        baseline = ["Baseline 1.", "Baseline 2."]
        f_legacy = compute_full_features(text, baseline)
        f_explicit_none = compute_full_features(text, baseline, baseline_indices=None)
        assert f_legacy == f_explicit_none
