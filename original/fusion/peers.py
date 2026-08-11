"""Deterministic same-tenant reference selection for the fused score.

Two jobs: turn a StudentState into a cached Profile (the expensive halves
of the compression and function-word channels), and pick a stable set of
reference profiles for a claimed student.

Determinism matters here in a way it did not in the offline experiment.
References are ordered by sha256(student_id), never shuffled, so the same
student scored twice gets the same references and the resulting number is
reproducible and explainable.
"""

from __future__ import annotations

import hashlib
import threading
from collections import OrderedDict
from collections.abc import Iterable
from dataclasses import dataclass

import numpy as np

from ..principal import tenant_of
from ..quantum.state import StudentState
from .channels import compressed_size, function_word_matrix

# The artifact is calibrated at exactly this many references. Using fewer
# would evaluate off-calibration, so the expert abstains instead.
N_REFERENCES = 8

# Matches style_authorship.MIN_WORDS / MIN_BASELINES: below these the
# channels are reading noise.
MIN_WORDS = 300
MIN_BASELINES = 3


@dataclass(frozen=True)
class Profile:
    """Everything the channels need from one author, computed once.

    ``baseline_mean``/``baseline_std`` and the text-derived fields
    (``text``, ``compressed_size``, ``fw_matrix``) are deliberately built
    from different sample sets. The moments come straight from
    ``StudentState``, which recency-weights over *every* sample with
    ``auth_weight > 0`` regardless of length — that has to match
    production ``deviation_score``, which uses exactly those moments. The
    text channels only ever see authenticated samples of at least
    ``MIN_WORDS`` words, because a short sample is noise for compression
    and function-word statistics even though it is a perfectly good
    contributor to the z-channel's mean/std. So a short authenticated
    sample can move ``baseline_mean``/``baseline_std`` while being
    invisible to ``text``/``compressed_size``/``fw_matrix``. This is
    intended, not a bug.
    """

    text: str
    compressed_size: int
    fw_matrix: np.ndarray
    baseline_mean: np.ndarray
    baseline_std: np.ndarray
    sample_count: int


_cache: OrderedDict[str, Profile] = OrderedDict()
# Cache key -> owning student_id, and the reverse index. Needed for both C2
# (FERPA erasure must be able to find and evict everything a student's raw
# text touched) and I4 (eviction must clean up its own bookkeeping, not just
# `_cache`, or `_cache_students` would grow without bound too). The cache
# key is a content fingerprint, not the student id, and a student's key
# changes whenever their authenticated baseline text changes — so
# `_cache_students` tracks every key ever built for a student, since a
# stale key from before their most recent baseline edit can otherwise
# outlive that edit in the cache.
_key_student: dict[str, str] = {}
_cache_students: dict[str, set[str]] = {}
_cache_builds = 0
_lock = threading.Lock()

# Each cached Profile holds an author's full concatenated authenticated
# baseline text plus derived matrices — measured ~107 KB/entry (I4, 2026-08
# fix pass). Left unbounded, a term-long pilot of ~500 students each
# accruing several baseline revisions would grow this dict without limit.
# 2000 entries is a documented ceiling (roughly 214 MB worst case) that
# comfortably covers a single tenant's active working set. Eviction is
# oldest-inserted-first, not strict last-accessed LRU, so the cache-hit fast
# path in build_profile() below can stay lock-free.
_MAX_CACHE_ENTRIES = 2000


def _evict_oldest_locked() -> None:
    """Pop the oldest-inserted cache entry and its bookkeeping. Caller must
    hold ``_lock``."""
    if not _cache:
        return
    evicted_key, _ = _cache.popitem(last=False)
    owner = _key_student.pop(evicted_key, None)
    if owner is not None:
        keys = _cache_students.get(owner)
        if keys is not None:
            keys.discard(evicted_key)
            if not keys:
                _cache_students.pop(owner, None)


def reset_cache_for_tests() -> None:
    global _cache_builds
    with _lock:
        _cache.clear()
        _key_student.clear()
        _cache_students.clear()
        _cache_builds = 0


def cache_build_count() -> int:
    return _cache_builds


def clear_student(student_id: str) -> None:
    """Evict every cached ``Profile`` entry for ``student_id`` (C2, 2026-08
    fix pass — FERPA right-to-erasure).

    ``store.delete_student`` purges every persistent store and already
    explicitly clears ``_GENRE_STATS_CACHE`` for exactly this reason; this
    module's ``_cache`` is the first long-lived in-process store of raw
    student text in the live stack, and was not covered by that purge. Safe
    to call for a student with no cached entries (a no-op) — the module may
    not even be loaded when the fusion flags are off, so callers should
    guard the import, not assume this function exists.
    """
    with _lock:
        keys = _cache_students.pop(student_id, None)
        if not keys:
            return
        for key in keys:
            _cache.pop(key, None)
            _key_student.pop(key, None)


def _authenticated_texts(state: StudentState) -> list[str]:
    return [
        sample.text
        for sample in state.samples
        if sample.auth_weight > 0
        and isinstance(sample.text, str)
        and len(sample.text.split()) >= MIN_WORDS
    ]


def _fingerprint(student_id: str, texts: list[str]) -> str:
    digest = hashlib.sha256()
    digest.update(student_id.encode("utf-8"))
    for text in texts:
        digest.update(b"\x00")
        digest.update(text.encode("utf-8", "ignore"))
    return digest.hexdigest()


def build_profile(state: StudentState) -> Profile | None:
    """Cached Profile for ``state``, or None when it is below the floors."""
    global _cache_builds
    texts = _authenticated_texts(state)
    if len(texts) < MIN_BASELINES:
        return None
    key = _fingerprint(state.student_id, texts)
    cached = _cache.get(key)
    if cached is not None:
        # Fast path: no lock needed once the profile is cached.
        return cached
    # Slow path: double-checked locking. Another thread may have built
    # this key while we were computing `key` above, so re-check inside
    # the lock before paying for compression + the function-word matrix,
    # and hold the lock across that work so two threads can never both
    # build the same key.
    with _lock:
        cached = _cache.get(key)
        if cached is not None:
            return cached
        joined = "\n".join(texts)
        profile = Profile(
            text=joined,
            compressed_size=compressed_size(joined.encode("utf-8", "ignore")),
            fw_matrix=function_word_matrix(joined),
            baseline_mean=state.baseline_mean,
            baseline_std=state.baseline_std,
            sample_count=len(texts),
        )
        _cache[key] = profile
        _key_student[key] = state.student_id
        _cache_students.setdefault(state.student_id, set()).add(key)
        _cache_builds += 1
        if len(_cache) > _MAX_CACHE_ENTRIES:
            _evict_oldest_locked()
        return profile


def _order_key(student_id: str) -> str:
    return hashlib.sha256(student_id.encode("utf-8")).hexdigest()


def select_references(
    claimed_state: StudentState,
    states: Iterable[StudentState],
) -> list[Profile]:
    """Exactly ``N_REFERENCES`` same-tenant peer profiles, or ``[]``.

    Returns an empty list — never a short list — when fewer than
    ``N_REFERENCES`` eligible peers exist, because the artifact cannot be
    evaluated at a reference count it was not calibrated at.
    """
    claimed_tenant = tenant_of(claimed_state.student_id)
    candidates = [
        state
        for state in states
        if state.student_id != claimed_state.student_id
        and tenant_of(state.student_id) == claimed_tenant
    ]
    candidates.sort(key=lambda state: _order_key(state.student_id))

    selected: list[Profile] = []
    for state in candidates:
        profile = build_profile(state)
        if profile is None:
            continue
        selected.append(profile)
        if len(selected) == N_REFERENCES:
            return selected
    return []
