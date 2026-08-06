"""
validation/plato/features.py — cached feature extraction for the Plato study.

Turns corpus chunks into the 103-dimensional feature matrix that both the
translator gate and the Arm B seriation run on. Extraction is slow (spaCy on
every chunk, plus the Tier 10 semantic backend), so results are cached to an
``.npz`` keyed on the manifest contents.

``lock_environment()`` MUST run before any ``original.*`` import — it pins the
seeds and the scoring feature flags. Importing this module does that for you.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path
from typing import List, Sequence, Tuple

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# Lock the environment BEFORE original.* is imported anywhere.
from validation.benchmark.reproducibility import lock_environment  # noqa: E402

ENV_LOCK = lock_environment()

import numpy as np  # noqa: E402

from original.constants import ALL_FEATURE_CODES, FEATURE_TIER  # noqa: E402
from original.features.pipeline import feature_vector  # noqa: E402

from validation.plato.normalise import normalise  # noqa: E402

_CORPUS_DIR = _HERE / "corpus"
_MANIFEST = _HERE / "manifest.json"


def _cache_path(normalised: bool) -> Path:
    return _HERE / ("_features_cache_norm.npz" if normalised else "_features_cache.npz")

# The 7 comparison features are only computable at scoring time against a
# baseline; standalone extraction leaves them at the 0.5 placeholder, so they
# carry no variance and must not be counted as active dimensions.
COMPARISON_TIER = 0


def load_manifest() -> dict:
    with open(_MANIFEST) as f:
        return json.load(f)


def _manifest_key(manifest: dict) -> str:
    """Hash the actual corpus BYTES, not just filenames and word counts.

    Keying on (filename, word_count) is not enough: stripping the per-line
    indentation from the Timaeus changed 76 of 103 features while leaving every
    word count identical, so a stale cache was silently reused and the rebuilt
    corpus produced byte-identical (wrong) results. Any transformation that
    rewrites text without changing its word count has the same failure mode.
    """
    h = hashlib.sha256()
    for e in sorted(manifest["entries"], key=lambda x: x["filename"]):
        h.update(e["filename"].encode())
        path = _CORPUS_DIR / e["filename"]
        if path.exists():
            h.update(path.read_bytes())
    return h.hexdigest()[:16]


def build_matrix(
    manifest: dict | None = None, force: bool = False, normalised: bool = False
) -> Tuple[np.ndarray, List[dict]]:
    """Return (X, entries) where X is (n_chunks, 103), rows aligned to entries.

    With ``normalised=True`` each chunk passes through
    ``validation.plato.normalise`` first, which unifies edition and
    transcription conventions (quote glyphs, dashes, italic markup, speaker
    label rendering) without touching punctuation density or prose. Raw and
    normalised matrices are cached separately so the two can be compared.
    """
    manifest = manifest or load_manifest()
    entries = manifest["entries"]
    key = _manifest_key(manifest)
    cache = _cache_path(normalised)

    if cache.exists() and not force:
        cached = np.load(cache, allow_pickle=False)
        if str(cached.get("key", np.array("")).item()) == key:
            return cached["X"], entries

    rows = []
    total = len(entries)
    for i, e in enumerate(entries, 1):
        text = (_CORPUS_DIR / e["filename"]).read_text(encoding="utf-8")
        if normalised:
            text = normalise(text)
        rows.append(feature_vector(text))
        if i % 20 == 0 or i == total:
            print(f"  features: {i}/{total}", file=sys.stderr, flush=True)
    X = np.vstack(rows)
    np.savez_compressed(cache, X=X, key=np.array(key))
    return X, entries


def informative_mask(X: np.ndarray, min_std: float = 1e-6) -> np.ndarray:
    """Columns that actually vary, excluding the placeholder comparison features.

    Mirrors the intent of ``StudentState.active_feature_mask``: a dimension that
    is constant across the corpus carries no information and would otherwise
    inject zeros into every distance.
    """
    varies = X.std(axis=0) > min_std
    not_comparison = np.array(
        [FEATURE_TIER.get(code, -1) != COMPARISON_TIER for code in ALL_FEATURE_CODES]
    )
    return varies & not_comparison


def standardise(X: np.ndarray, mask: np.ndarray | None = None) -> np.ndarray:
    """Z-score each retained column so no feature dominates a distance by scale."""
    if mask is None:
        mask = informative_mask(X)
    Xm = X[:, mask]
    return (Xm - Xm.mean(axis=0)) / Xm.std(axis=0)


def tier_of(code: str) -> int:
    return FEATURE_TIER.get(code, -1)


def active_codes(mask: np.ndarray) -> Sequence[str]:
    return [c for c, keep in zip(ALL_FEATURE_CODES, mask) if keep]
