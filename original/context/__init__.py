"""
original/context/ — Adaptive context-aware scoring layer.

This package wraps the existing static scoring pipeline (`original/quantum/scoring.py`)
with a context-resolution and adaptive-weighting layer. Phase 1 scoring is preserved
verbatim when feature flags `CONTEXT_MANIFEST_ENABLED` and `ADAPTIVE_WEIGHTS_ENABLED`
are unset (the default).

Modules
-------
resolvers       : Six parallel context resolvers (language, genre, topic, length,
                  citations, composition_mode) executed via ThreadPoolExecutor.
manifest        : (Phase 3) ContextManifest dataclass + directive derivation.
baseline_match  : (Phase 4) Cluster-based baseline matching.
weighting       : (Phase 5) Adaptive per-feature weight vector construction.
pipeline        : (Phase 5) Orchestrator that chains resolvers → manifest →
                  match → weights and feeds into the existing score() function.
report          : (Phase 6) ScoringReport assembly + narrative generation.
blend           : (Phase 7) Sliding-window blend / mid-document shift detection.

Phase 2 ships only `resolvers` — see `original/context/resolvers.py`.
"""
