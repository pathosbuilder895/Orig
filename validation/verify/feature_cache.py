"""Persistent, content-addressed cache for the 109-dim stylometric feature
vector, plus parallel extraction for cache misses.

Mirrors pan_luar_expert.py's EmbeddingCache for LUAR embeddings. That cache
is why the Gutenberg ablations finish in minutes; PAN has never had an
equivalent, which is the entire reason PAN ablations take an hour-plus on
the same-sized locked cohort — every run re-extracts every document from
scratch, serially, in-process, discarded when the process exits.

original.features.pipeline.feature_vector(text) is a pure, deterministic
function of the text alone (no model weights, no network, no keystroke
data in this validation context) — SHA-256 of the text is a sufficient
cache key, unlike EmbeddingCache's key which also has to pin model
identity/revision.
"""

from __future__ import annotations

import hashlib
import json
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Sequence

import numpy as np

from original.constants import FEATURE_DIM

CACHE_SCHEMA = "original.feature_cache.v1"
DEFAULT_CACHE_PATH = Path(".benchmark_cache/features/feature_vectors.npz")


def _text_key(text: str) -> str:
    digest = hashlib.sha256()
    digest.update(CACHE_SCHEMA.encode())
    digest.update(str(FEATURE_DIM).encode())
    digest.update(text.encode("utf-8"))
    return digest.hexdigest()


class FeatureCache:
    """Content-addressed cache: sha256(schema, FEATURE_DIM, text) -> vector."""

    def __init__(self, path: Path = DEFAULT_CACHE_PATH):
        self.path = path
        self.values: dict[str, np.ndarray] = {}
        if path.exists():
            with np.load(path, allow_pickle=False) as archive:
                metadata = json.loads(str(archive["metadata"].item()))
                if metadata.get("schema") != CACHE_SCHEMA:
                    raise ValueError("incompatible feature cache schema")
                if metadata.get("feature_dim") != FEATURE_DIM:
                    raise ValueError(
                        "feature cache was built for FEATURE_DIM="
                        f"{metadata.get('feature_dim')}, current is {FEATURE_DIM} "
                        "-- delete the cache file and rebuild"
                    )
                keys = archive["keys"].tolist()
                vectors = archive["vectors"]
                self.values = {
                    str(key): np.asarray(vector, dtype=np.float64)
                    for key, vector in zip(keys, vectors)
                }

    def get(self, text: str) -> np.ndarray | None:
        return self.values.get(_text_key(text))

    def put(self, text: str, vector: np.ndarray) -> None:
        value = np.asarray(vector, dtype=np.float64)
        if value.shape != (FEATURE_DIM,):
            raise ValueError(f"invalid feature vector shape: {value.shape}")
        self.values[_text_key(text)] = value

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        keys = sorted(self.values)
        vectors = (
            np.stack([self.values[key] for key in keys])
            if keys
            else np.empty((0, FEATURE_DIM))
        )
        # Atomic write: a crash or a concurrent reader mid-save must never see
        # a truncated cache file, only the old one or the new one.
        temporary = self.path.with_suffix(self.path.suffix + ".tmp.npz")
        np.savez_compressed(
            temporary,
            metadata=json.dumps(
                {"schema": CACHE_SCHEMA, "feature_dim": FEATURE_DIM}, sort_keys=True
            ),
            keys=np.asarray(keys),
            vectors=vectors.astype(np.float64),
        )
        temporary.replace(self.path)


def extract_many(
    texts: Sequence[str],
    *,
    cache: FeatureCache | None = None,
    cache_path: Path = DEFAULT_CACHE_PATH,
    max_workers: int | None = None,
    save_every: int = 200,
    progress_label: str = "feature_cache",
) -> dict[str, np.ndarray]:
    """Return {text: 109-dim vector} for every text, deduplicated.

    Cache hits are free. Cache misses are extracted in a process pool
    (feature_vector is CPU-bound: spaCy parsing, n-gram counting, no shared
    GPU/network state to serialize across workers) and the cache is
    incrementally saved as results land, so an interrupted run keeps
    whatever it already computed.
    """
    from original.features.pipeline import feature_vector as _extract_one

    if cache is None:
        cache = FeatureCache(cache_path)

    unique_texts = list(dict.fromkeys(texts))  # de-dup, stable order
    result: dict[str, np.ndarray] = {}
    missing: list[str] = []
    for text in unique_texts:
        cached = cache.get(text)
        if cached is not None:
            result[text] = cached
        else:
            missing.append(text)

    print(
        f"[{progress_label}] {len(result)} cached, {len(missing)} to extract "
        f"({len(unique_texts)} unique texts)",
        file=sys.stderr,
    )
    if not missing:
        return result

    completed = 0
    with ProcessPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(_extract_one, text): text for text in missing}
        for future in as_completed(futures):
            text = futures[future]
            vector = future.result()
            result[text] = vector
            cache.put(text, vector)
            completed += 1
            if completed % 25 == 0 or completed == len(missing):
                print(
                    f"[{progress_label}] extracted {completed}/{len(missing)}",
                    file=sys.stderr,
                )
            if completed % save_every == 0:
                cache.save()
    cache.save()
    return result
