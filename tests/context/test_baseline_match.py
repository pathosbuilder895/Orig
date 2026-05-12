"""
tests/context/test_baseline_match.py — Phase 4 baseline matching tests.
"""

from __future__ import annotations

import numpy as np
import pytest

from original.constants import FEATURE_DIM
from original.context.baseline_match import (
    _genre_similarity, _topic_similarity, _recency_weight,
    ensure_sample_context_metadata, match_baseline_cluster,
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
        submission_id="sub", language={}, genre={"primary": genre},
        topic={}, length_regime="standard", citations={}, composition_mode={},
        weight_modifications={"amplify_codes": [], "attenuate_codes": [], "mute_codes": []},
        anchor_tiers=[4, 6], baseline_match={}, flags=[], created_at="",
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
# Lazy backfill
# ══════════════════════════════════════════════════════════════════════════════

class TestEnsureSampleContextMetadata:
    def test_lazy_backfill_populates_legacy_samples(self):
        # 3 legacy samples (genre=None, topic_centroid=None) → all populated.
        state = StudentState(student_id="s", samples=[
            _sample("Plato writes about the form of justice extensively in the Republic."),
            _sample("Modern democracy thrives only when citizens deliberate honestly."),
            _sample("The pizza recipe varies widely across regions of Italy."),
        ])
        mutated = ensure_sample_context_metadata(state)
        assert mutated is True
        for s in state.samples:
            assert s.genre is not None
            assert s.topic_centroid is not None
            assert s.topic_centroid.ndim == 1

    def test_idempotent(self):
        # Second call on already-populated samples should NOT mutate again.
        state = StudentState(student_id="s", samples=[
            _sample("Plato discusses the soul.", genre="academic_exegesis",
                    centroid=np.array([0.5, 0.5])),
        ])
        mutated_first  = ensure_sample_context_metadata(state)
        mutated_second = ensure_sample_context_metadata(state)
        assert mutated_first is False     # already populated
        assert mutated_second is False    # still no change


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
        state = StudentState(student_id="s", samples=[
            _sample("Academic 1", genre="academic_exegesis"),
            _sample("Academic 2", genre="academic_exegesis"),
            _sample("Academic 3", genre="academic_exegesis"),
            _sample("Fiction 1",  genre="creative_fiction"),
            _sample("Fiction 2",  genre="creative_fiction"),
        ])
        m = _manifest("academic_exegesis")
        idx, anchor_only = match_baseline_cluster(
            m, state, submission_text="Academic submission text",
        )
        # Top-N should not include fiction indices (3 or 4).
        assert anchor_only is False
        assert len(idx) >= 2
        assert all(i < 3 for i in idx), f"Fiction sample picked: {idx}"

    def test_prefers_recent_when_genre_uniform(self):
        # All same genre, all (effectively) same topic — recency tiebreaker
        # should pick the highest indices.
        state = StudentState(student_id="s", samples=[
            _sample("Same genre A", genre="blog_post"),
            _sample("Same genre B", genre="blog_post"),
            _sample("Same genre C", genre="blog_post"),
            _sample("Same genre D", genre="blog_post"),
        ])
        idx, anchor_only = match_baseline_cluster(
            _manifest("blog_post"), state,
            submission_text="Same genre submission",
        )
        # n_top defaults to 3; recency-favoured → [3, 2, 1].
        assert idx[0] == 3, f"most-recent sample should rank first; got {idx}"

    def test_anchor_only_when_no_matches_above_threshold(self):
        # All samples have genre that doesn't match AND no centroid yet,
        # so genre_sim=0 + topic_sim=0.5 + recency tiny → composite < 0.5.
        state = StudentState(student_id="s", samples=[
            _sample("Random A", genre="creative_fiction"),
            _sample("Random B", genre="creative_fiction"),
        ])
        idx, anchor_only = match_baseline_cluster(
            _manifest("academic_exegesis"), state, submission_text=None,
            min_similarity=0.95,        # pull threshold up — force fallback
        )
        assert anchor_only is True
        assert idx == []

    def test_returns_at_most_n_top(self):
        state = StudentState(student_id="s", samples=[
            _sample(f"Sample {i}", genre="blog_post") for i in range(10)
        ])
        idx, _ = match_baseline_cluster(
            _manifest("blog_post"), state,
            submission_text="A blog post submission",
            n_top=3,
        )
        assert len(idx) <= 3


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
        assert f_sub0[key] != f_sub1[key], (
            f"subset 0 and subset 1 produced identical {key}"
        )

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
