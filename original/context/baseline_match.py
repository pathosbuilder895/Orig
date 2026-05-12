"""
context/baseline_match.py — Phase 4: Contextual Baseline Matching.

Selects the subset of a student's baseline samples whose context most
closely matches the submission's manifest, and lazily backfills the
context metadata (genre + topic centroid) on legacy samples that
predate the adaptive layer.

The composite similarity score is:

    score = 0.4 · genre_similarity
          + 0.4 · topic_similarity
          + 0.2 · recency_weight

Genre similarity is a 3-step ladder (1.0 same label, 0.5 same family,
0.0 otherwise) using `GENRE_FAMILIES` from `constants.py`.

Topic similarity is `1 - cosine_distance` between the submission's TF-IDF
centroid and each sample's stored TF-IDF centroid. Both vectors come from
a per-student vectoriser (cached on `StudentState._tfidf_vectorizer`) fitted
once over the student's full sample corpus — so the vocabulary is consistent
across calls without leaking across students.

Recency weight is a simple linear ramp: most-recent sample (highest index)
= 1.0, oldest = 0.0.

Returns a tuple `(selected_indices, anchor_only)`. The caller (Phase 5
orchestrator) feeds `selected_indices` to `compute_full_features(...,
baseline_indices=...)`. When fewer than two samples score above
`min_similarity` we fall back to anchor-only scoring and signal that with
`anchor_only=True`.
"""

from __future__ import annotations

import logging
from typing import Any, List, Optional, Tuple

import numpy as np

try:
    from sklearn.feature_extraction.text import TfidfVectorizer
except Exception:                  # pragma: no cover — dev environments without sklearn
    TfidfVectorizer = None         # type: ignore[assignment]

from ..constants import GENRE_FAMILIES
from .resolvers import resolve_genre

log = logging.getLogger(__name__)


# ── Tunable knobs ────────────────────────────────────────────────────────────

# Minimum number of samples to return from a successful match; ensures the
# downstream comparison features have something to chew on. If we can't find
# this many above `min_similarity`, we fall through to anchor-only.
_MIN_CLUSTER_SIZE: int = 2


# ══════════════════════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════════════════════

def _genre_similarity(submission_genre: Optional[str],
                       sample_genre: Optional[str]) -> float:
    """Three-step ladder: 1.0 same label, 0.5 same family, 0.0 otherwise."""
    if submission_genre is None or sample_genre is None:
        # Conservative: an unknown genre can't be claimed as a match. We
        # don't return 0.5 here — that would inflate similarity for
        # under-tagged samples and bias selection toward them.
        return 0.0
    if submission_genre == sample_genre:
        return 1.0
    fam_sub = GENRE_FAMILIES.get(submission_genre)
    fam_sample = GENRE_FAMILIES.get(sample_genre)
    if fam_sub is not None and fam_sample is not None and fam_sub == fam_sample:
        return 0.5
    return 0.0


def _topic_similarity(submission_centroid: Optional[np.ndarray],
                       sample_centroid: Optional[np.ndarray]) -> float:
    """Cosine similarity (1 − cosine distance), null-safe."""
    if submission_centroid is None or sample_centroid is None:
        # Unknown topic ⇒ neutral 0.5 (different from genre handling: a
        # missing topic centroid is the legacy default, not an "unknown
        # genre" judgment, so we don't penalise as hard).
        return 0.5
    a = submission_centroid
    b = sample_centroid
    norm_a = float(np.linalg.norm(a))
    norm_b = float(np.linalg.norm(b))
    if norm_a < 1e-12 or norm_b < 1e-12:
        return 0.5
    sim = float(np.dot(a, b) / (norm_a * norm_b))
    # Clip to [0, 1] — TF-IDF vectors are non-negative so cosine is in [0,1]
    # naturally, but rounding noise can push it just outside.
    return max(0.0, min(1.0, sim))


def _recency_weight(sample_index: int, total: int) -> float:
    """Linear ramp: most recent (highest index) = 1.0, oldest = 0.0."""
    if total <= 1:
        return 1.0
    return float(sample_index) / float(total - 1)


# ══════════════════════════════════════════════════════════════════════════════
# Per-student TF-IDF vectoriser (cached transiently on StudentState)
# ══════════════════════════════════════════════════════════════════════════════

def _ensure_tfidf_vectorizer(state: "object") -> Optional["TfidfVectorizer"]:
    """
    Fit a TF-IDF vectoriser over the student's full sample corpus and cache
    it on `state._tfidf_vectorizer`. Transient (not serialised); rebuilt on
    demand from sample texts. Returns None when sklearn is unavailable or
    the student has no samples.
    """
    if TfidfVectorizer is None:
        return None
    cached = getattr(state, "_tfidf_vectorizer", None)
    if cached is not None:
        return cached
    samples = getattr(state, "samples", None) or []
    texts = [s.text for s in samples if (s.text or "").strip()]
    if not texts:
        return None
    # Vocab capped at 300 to match the topic-centroid storage budget noted
    # in the plan (≈2.4 KB / sample at float64).
    vec = TfidfVectorizer(
        max_features=300,
        lowercase=True,
        token_pattern=r"(?u)\b\w\w+\b",
        ngram_range=(1, 1),
        sublinear_tf=True,
    )
    try:
        vec.fit(texts)
    except ValueError:
        # All texts empty after preprocessing — give up.
        return None
    state._tfidf_vectorizer = vec
    return vec


def _transform_centroid(vec: "TfidfVectorizer", text: str) -> Optional[np.ndarray]:
    """Transform `text` to a dense centroid vector (or None if empty/error)."""
    if not (text or "").strip():
        return None
    try:
        m = vec.transform([text]).toarray()[0]
    except Exception:
        return None
    return m.astype(np.float64)


# ══════════════════════════════════════════════════════════════════════════════
# Lazy backfill of legacy samples
# ══════════════════════════════════════════════════════════════════════════════

def ensure_sample_context_metadata(state: "object") -> bool:
    """
    Lazily compute genre + topic_centroid for samples missing them.

    Mutates `state.samples[i]` in place. Returns True if at least one sample
    was mutated — caller is responsible for `store.put(state)` to persist
    the backfill.

    Idempotent: a sample whose metadata is already populated is left alone.
    """
    samples = getattr(state, "samples", None) or []
    if not samples:
        return False

    mutated = False
    vec = _ensure_tfidf_vectorizer(state)

    for s in samples:
        # Genre backfill — call the rule-based resolver on the sample text.
        if s.genre is None and (s.text or "").strip():
            try:
                g = resolve_genre(s.text).get("primary")
                if g:
                    s.genre = g
                    mutated = True
            except Exception as e:
                log.warning("genre backfill failed for sample: %s", e)

        # Topic centroid backfill — only if vectoriser exists.
        if s.topic_centroid is None and vec is not None and (s.text or "").strip():
            centroid = _transform_centroid(vec, s.text)
            if centroid is not None:
                s.topic_centroid = centroid
                mutated = True

    return mutated


# ══════════════════════════════════════════════════════════════════════════════
# Cluster matching
# ══════════════════════════════════════════════════════════════════════════════

def match_baseline_cluster(
    manifest: "object",
    state: "object",
    submission_text: Optional[str] = None,
    n_top: int = 3,
    min_similarity: float = 0.5,
) -> Tuple[List[int], bool]:
    """
    Pick the top-N baseline samples whose context most closely matches the
    submission's manifest.

    Parameters
    ----------
    manifest : ContextManifest
        Provides `genre.primary` for genre similarity and serves as the
        source of submission identity for the audit trail.
    state : StudentState
        Source of `samples`. Lazy backfill is run before scoring so that
        legacy samples without `genre`/`topic_centroid` still participate.
    submission_text : Optional[str]
        Used to compute the submission's TF-IDF centroid via the per-student
        vectoriser. When `None`, the topic axis is treated as unknown (0.5
        neutral) and matching falls back to genre + recency.
    n_top : int
        Maximum cluster size returned.
    min_similarity : float
        A sample whose composite similarity is below this is excluded.
        When fewer than `_MIN_CLUSTER_SIZE` samples pass, the function
        returns `([], anchor_only=True)`.

    Returns
    -------
    (selected_indices, anchor_only)
        `selected_indices` are positions into `state.samples`, ordered by
        descending similarity. `anchor_only=True` signals to the orchestrator
        that comparison-feature placeholders should be left at neutral 0.5
        and the weight vector should mute everything outside the manifest's
        anchor tiers.
    """
    samples = list(getattr(state, "samples", []) or [])
    if not samples:
        return [], True

    # Idempotent backfill — also primes the TF-IDF vectoriser.
    ensure_sample_context_metadata(state)

    # Submission centroid (None if vectoriser missing or text missing).
    sub_centroid: Optional[np.ndarray] = None
    if submission_text:
        vec = _ensure_tfidf_vectorizer(state)
        if vec is not None:
            sub_centroid = _transform_centroid(vec, submission_text)

    # Submission genre — manifest is either ContextManifest or a dict.
    if isinstance(manifest, dict):
        sub_genre = (manifest.get("genre") or {}).get("primary")
    else:
        sub_genre = (getattr(manifest, "genre", {}) or {}).get("primary")

    total = len(samples)
    scored: List[Tuple[int, float]] = []
    for i, s in enumerate(samples):
        gs = _genre_similarity(sub_genre, s.genre)
        ts = _topic_similarity(sub_centroid, s.topic_centroid)
        rs = _recency_weight(i, total)
        composite = 0.4 * gs + 0.4 * ts + 0.2 * rs
        scored.append((i, composite))

    scored.sort(key=lambda t: t[1], reverse=True)

    above = [(i, s) for (i, s) in scored if s >= min_similarity]

    if len(above) < _MIN_CLUSTER_SIZE:
        # Anchor-only fallback: not enough contextually-similar samples to
        # trust the comparison features. Phase 5 weight vector mutes
        # everything outside the manifest's anchor tiers.
        return [], True

    selected = [i for (i, _) in above[:n_top]]
    return selected, False


__all__ = [
    "match_baseline_cluster",
    "ensure_sample_context_metadata",
    "_genre_similarity",
    "_topic_similarity",
    "_recency_weight",
]
