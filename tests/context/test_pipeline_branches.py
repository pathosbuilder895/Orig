"""
tests/context/test_pipeline_branches.py — branch coverage for
original/context/pipeline.py::run_adaptive_pipeline's exception-fallback
arms.

run_adaptive_pipeline wraps every Phase 5 stage (resolvers, baseline
matching, weight-vector build, feature extraction) in its own try/except
so a single stage failure degrades gracefully instead of failing the whole
scoring request. TestScenarios / TestGenreInvariantWeighting in
test_integration.py and the flag matrix in test_flag_matrix.py exercise
every SUCCESS path through this function (flags-off short-circuit,
manifest-only mode, full adaptive-weights mode with genre-invariant
on/off) — none of them ever make an inner stage raise, so the four
`except Exception` fallback arms were never exercised.

Each test below monkeypatches exactly one stage function to raise. It
patches the name as bound in `original.context.pipeline`'s own namespace
(pipeline.py does `from .resolvers import run_resolvers` etc., so that
module-local name is what must be patched — patching the origin module's
attribute would leave pipeline.py's already-imported reference untouched)
and asserts both the graceful-degradation contract `AdaptivePipelineResult`
promises and that the pipeline still returns a usable result rather than
propagating the exception.

Stages 5 (build_adaptive_weight_vector) and 6 (compute_full_features) run
concurrently inside a `ThreadPoolExecutor(max_workers=2)`; per CPython,
an exception raised inside submitted work is captured and re-raised from
`.result()` in the calling thread, so monkeypatching the target function
to raise is sufficient — no thread-pool-specific plumbing needed.
"""

from __future__ import annotations

from typing import List

import numpy as np

import original.context.pipeline as pipeline_mod
from original.constants import ALL_FEATURE_CODES, FEATURE_DIM
from original.context.pipeline import run_adaptive_pipeline
from original.features.pipeline import extract_features, feature_vector
from original.quantum.state import BaselineSample, StudentState


def _make_state(texts: List[str], student_id: str = "s") -> StudentState:
    samples = []
    for i, t in enumerate(texts):
        seed = abs(hash((student_id, i, t))) % (2**32 - 1)
        v = np.random.RandomState(seed).uniform(0.3, 0.7, size=FEATURE_DIM)
        samples.append(
            BaselineSample(
                text=t,
                vector=v,
                provenance="verified",
                auth_weight=1.0,
                assignment=f"a{i}",
                submitted_at=f"2025-01-{i + 1:02d}",
            )
        )
    return StudentState(student_id=student_id, samples=samples)


TEXT = (
    "As Smith (2020) argues, the institutional reform requires "
    "deliberate scaffolding (Smith, 2020, p. 33). Subsequent scholars "
    "have largely concurred (Jones, 2021). "
) * 10


# ══════════════════════════════════════════════════════════════════════════════
# Stage 2 (run_resolvers) exception -> Phase-1 fallback
# ══════════════════════════════════════════════════════════════════════════════


class TestResolverExceptionFallback:
    """`run_resolvers` raising aborts the whole manifest stage — the
    fallback calls `extract_features` + `feature_vector` directly and
    returns with `fallback_reason="resolver_exception"`, `manifest=None`,
    `adaptive_weights=None`."""

    def test_resolver_exception_falls_back_to_phase1(self, monkeypatch):
        def _boom(*args, **kwargs):
            raise RuntimeError("resolver boom")

        monkeypatch.setattr(pipeline_mod, "run_resolvers", _boom)

        state = _make_state(["Baseline one.", "Baseline two."])
        result = run_adaptive_pipeline(
            TEXT,
            state,
            "resolver-boom",
            enable_manifest=True,
            enable_adaptive_weights=True,
        )

        assert result.fallback_reason == "resolver_exception"
        assert result.manifest is None
        assert result.adaptive_weights is None
        assert result.feat_dict == extract_features(TEXT)
        assert np.array_equal(result.vector, feature_vector(TEXT))

    def test_resolver_exception_fires_in_manifest_only_mode_too(self, monkeypatch):
        # The resolver stage runs before the enable_adaptive_weights branch
        # ever gets checked, so a resolver failure can't be dodged by
        # leaving adaptive weights off.
        def _boom(*args, **kwargs):
            raise ValueError("resolver boom 2")

        monkeypatch.setattr(pipeline_mod, "run_resolvers", _boom)

        state = _make_state(["Baseline one.", "Baseline two."])
        result = run_adaptive_pipeline(
            TEXT,
            state,
            "resolver-boom-manifest-only",
            enable_manifest=True,
            enable_adaptive_weights=False,
        )
        assert result.fallback_reason == "resolver_exception"
        assert result.manifest is None
        assert result.adaptive_weights is None


# ══════════════════════════════════════════════════════════════════════════════
# Stage 4 (baseline matching) exception -> anchor-only fallback
# ══════════════════════════════════════════════════════════════════════════════


class TestBaselineMatchExceptionFallback:
    """`ensure_sample_context_metadata` / `match_baseline_cluster` raising
    degrades to an anchor-only cluster (empty indices, anchor_only=True,
    genre_covered=True, error recorded on the manifest) but does NOT abort
    the whole pipeline — stages 5+6 still run on top of the fallback."""

    def test_match_baseline_cluster_exception_anchor_only_fallback(self, monkeypatch):
        def _boom(*args, **kwargs):
            raise RuntimeError("cluster match boom")

        monkeypatch.setattr(pipeline_mod, "match_baseline_cluster", _boom)

        state = _make_state(["Baseline one.", "Baseline two.", "Baseline three."])
        result = run_adaptive_pipeline(
            TEXT,
            state,
            "cluster-boom",
            enable_manifest=True,
            enable_adaptive_weights=True,
        )

        # Stage 3 (manifest) already succeeded before the failing stage, so
        # it's still attached -- only stage 4's own outputs degrade.
        assert result.manifest is not None
        assert result.manifest.baseline_match["cluster_indices"] == []
        assert result.manifest.baseline_match["n_samples"] == 0
        assert result.manifest.baseline_match["anchor_only"] is True
        assert result.manifest.baseline_match["genre_covered"] is True
        assert "cluster match boom" in result.manifest.baseline_match["error"]

        assert result.anchor_only is True
        assert result.cluster_indices == []
        # Not a total abort -- stages 5+6 still ran on top of the fallback.
        assert result.adaptive_weights is not None
        assert result.adaptive_weights.shape == (FEATURE_DIM,)
        assert result.vector.shape == (FEATURE_DIM,)
        assert result.fallback_reason is None  # only set on the Stage 2 arm

    def test_ensure_sample_context_metadata_exception_anchor_only_fallback(self, monkeypatch):
        # ensure_sample_context_metadata is the FIRST call inside the
        # stage-4 try block -- it raising must land in the same except arm
        # as match_baseline_cluster raising.
        def _boom(*args, **kwargs):
            raise RuntimeError("metadata boom")

        monkeypatch.setattr(pipeline_mod, "ensure_sample_context_metadata", _boom)

        state = _make_state(["Baseline one.", "Baseline two."])
        result = run_adaptive_pipeline(
            TEXT,
            state,
            "metadata-boom",
            enable_manifest=True,
            enable_adaptive_weights=True,
        )
        assert result.manifest.baseline_match["anchor_only"] is True
        assert result.manifest.baseline_match["cluster_indices"] == []
        assert "metadata boom" in result.manifest.baseline_match["error"]
        assert result.adaptive_weights is not None  # stages 5+6 still ran


# ══════════════════════════════════════════════════════════════════════════════
# Stage 5 (build_adaptive_weight_vector) exception -> static (None) weights
# ══════════════════════════════════════════════════════════════════════════════


class TestWeightVectorBuildExceptionFallback:
    def test_weight_vector_build_exception_falls_back_to_none(self, monkeypatch):
        def _boom(*args, **kwargs):
            raise RuntimeError("weight build boom")

        monkeypatch.setattr(pipeline_mod, "build_adaptive_weight_vector", _boom)

        state = _make_state(["Baseline one.", "Baseline two."])
        result = run_adaptive_pipeline(
            TEXT,
            state,
            "weights-boom",
            enable_manifest=True,
            enable_adaptive_weights=True,
        )

        assert result.adaptive_weights is None
        # Stage 6 (feature extraction), running concurrently in the other
        # thread, is unaffected.
        assert result.manifest is not None
        assert result.vector.shape == (FEATURE_DIM,)
        assert result.feat_dict
        assert result.fallback_reason is None  # only set on the Stage 2 arm


# ══════════════════════════════════════════════════════════════════════════════
# Stage 6 (compute_full_features) exception -> extract_features fallback
# ══════════════════════════════════════════════════════════════════════════════


class TestFeatureExtractionExceptionFallback:
    def test_compute_full_features_exception_falls_back_to_extract_features(self, monkeypatch):
        def _boom(*args, **kwargs):
            raise RuntimeError("feature extraction boom")

        monkeypatch.setattr(pipeline_mod, "compute_full_features", _boom)

        state = _make_state(["Baseline one.", "Baseline two."])
        result = run_adaptive_pipeline(
            TEXT,
            state,
            "features-boom",
            enable_manifest=True,
            enable_adaptive_weights=True,
        )

        assert result.feat_dict == extract_features(TEXT)
        expected_vec = np.array(
            [result.feat_dict[c] for c in ALL_FEATURE_CODES], dtype=np.float64
        )
        assert np.array_equal(result.vector, expected_vec)
        # Stage 5 (weight vector), running concurrently in the other
        # thread, is unaffected.
        assert result.adaptive_weights is not None
        assert result.adaptive_weights.shape == (FEATURE_DIM,)
        assert result.fallback_reason is None  # only set on the Stage 2 arm
