"""Opt-in on-disk memo for the calibration battery's feature extraction.

Why: ``python -m validation.calibration_gate`` re-extracts the same corpus
texts thousands of times. Every leave-one-out fold re-uploads an entity's
N-1 baselines through ``/students/{sid}/baseline``, so a 12-text Plato
dialogue alone costs 132 extractions for 12 documents, and G5's
shuffled-label reruns repeat the whole G1/G3/G4 machinery on the same
texts. Extraction (spaCy parse + 109 features) is the dominant cost; the
2026-09-07 TermSim merge measured the full battery at 20+ CPU-hours,
beyond any CI timeout and beyond what a reviewer will re-run. Memoising
``feature_vector`` on text collapses that to one extraction per distinct
document.

What it does NOT do: change a single vector. The memo is a pure function of
the inputs extraction itself depends on — the text, the feature layout
(``FEATURE_DIM`` + ``ALL_FEATURE_CODES``), the process-global
``DISABLED_FEATURE_GROUPS`` (G2b/G6 toggle the ``uniformity`` group for
their own legs, which changes tier-18 outputs — see
``calibration_gate._uniformity_features_enabled``), and the tier-10
semantic backend actually in use (sentence-transformers vs the TF-IDF
fallback produce different values for the same text). Any of those
differing yields a different key, never a stale hit. Keystroke-carrying
requests bypass the memo entirely, exactly as
``validation/termsim/runner.py``'s ``install_vector_cache`` does — this
module is that helper's key scheme hardened for a process that toggles
feature groups mid-run.

Scope: only the two API route modules' local ``feature_vector`` bindings
are patched (the battery scores through the live routes), and only for
the duration of ``run_all()``; the ``original.features.pipeline`` function
itself and every other importer are untouched. Production has no cache
path. Opt in with ``CALIBRATION_GATE_VECTOR_CACHE=<dir>``; the report JSON
records the directory and key scheme so a reader can tell a memoised run
from a cold one.
"""

from __future__ import annotations

import fcntl
import hashlib
import os
from collections.abc import Callable
from pathlib import Path

import numpy as np

ENV_VAR = "CALIBRATION_GATE_VECTOR_CACHE"
KEY_SCHEME = "sha256(FEATURE_DIM, ALL_FEATURE_CODES, sorted DISABLED_FEATURE_GROUPS, tier10 backend, text)"


def semantic_backend() -> str:
    """Which tier-10 encoder this process will use: ``"st"`` when the
    sentence-transformers model loads, ``"tfidf"`` otherwise. Loading it here
    is not extra work — the first extraction would load it anyway."""
    from original.features import tier10

    return "st" if tier10._get_st_model() is not None else "tfidf"


def vector_cache_key(text: str, backend: str | None = None) -> str:
    from original.constants import ALL_FEATURE_CODES, DISABLED_FEATURE_GROUPS, FEATURE_DIM

    parts = [
        str(FEATURE_DIM),
        ",".join(ALL_FEATURE_CODES),
        ",".join(sorted(DISABLED_FEATURE_GROUPS)),
        backend if backend is not None else semantic_backend(),
        text,
    ]
    return hashlib.sha256("\0".join(parts).encode("utf-8")).hexdigest()


def make_cached_feature_vector(cache_dir: Path, extract: Callable, backend: str) -> Callable:
    cache_dir.mkdir(parents=True, exist_ok=True)

    def cached(text: str, keystroke_data=None):
        if keystroke_data:
            # Behavioural features are request-specific; never memoised.
            return extract(text, keystroke_data=keystroke_data)
        key = vector_cache_key(text, backend)
        path = cache_dir / f"{key}.npy"
        lock_path = cache_dir / f"{key}.lock"
        with lock_path.open("w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            if path.exists():
                return np.load(path)
            vector = extract(text)
            temporary = path.with_suffix(".tmp.npy")
            np.save(temporary, vector)
            temporary.replace(path)
            return vector

    cached.__wrapped__ = extract  # type: ignore[attr-defined]
    return cached


def install_vector_cache(cache_dir: Path) -> Callable[[], None]:
    """Patch the two route modules' ``feature_vector`` bindings; return a
    restore callable that puts the originals back."""
    from original.features.pipeline import feature_vector as extract
    from original.routers import students_baseline, students_scoring

    cached = make_cached_feature_vector(Path(cache_dir), extract, semantic_backend())
    originals = (students_baseline.feature_vector, students_scoring.feature_vector)
    students_baseline.feature_vector = cached
    students_scoring.feature_vector = cached

    def restore() -> None:
        students_baseline.feature_vector, students_scoring.feature_vector = originals

    return restore


def maybe_install_from_env() -> tuple[Callable[[], None], dict | None]:
    """``(restore, description)``: a no-op restore and ``None`` when the env
    var is unset, else the installed cache and a dict for the report."""
    cache_dir = os.environ.get(ENV_VAR)
    if not cache_dir:
        return (lambda: None), None
    restore = install_vector_cache(Path(cache_dir))
    return restore, {
        "dir": str(Path(cache_dir).resolve()),
        "key_scheme": KEY_SCHEME,
        "semantic_backend": semantic_backend(),
        "scope": "students_baseline.feature_vector and students_scoring.feature_vector, "
        "for the duration of run_all() only",
    }
