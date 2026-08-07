"""Extract feature vectors for the cross-work corpus, cached to disk.

Companion to derive.py, which turns these vectors into TOPIC_SENSITIVITY.
Separated so the ~4-minute extraction runs once and the derivation can be
re-run and re-tuned instantly.

Usage:
    .venv/bin/python -m validation.topic_sensitivity_2026-08.extract
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent.parent
sys.path.insert(0, str(_ROOT))

import numpy as np  # noqa: E402

from original.features.pipeline import feature_vector  # noqa: E402

CORPUS = _ROOT / "validation" / "public_authors" / "cross_work_corpus"
MANIFEST = _ROOT / "validation" / "public_authors" / "cross_work_manifest.json"
VECTORS = _HERE / "vectors.npy"
META = _HERE / "vectors_meta.json"

# ── Transcription normalisation ──────────────────────────────────────────────
#
# MEASURED PROBLEM this exists to remove. Project Gutenberg editions of the
# same author use different typographic conventions depending on who prepared
# them, and the difference is large:
#
#   chesterton/orthodoxy              curly-quote rate  0.00 / straight  7.05
#   chesterton/the_man_who_was_thursday                23.35 /           0.00
#   emerson/representative_men                          0.00 /          10.05
#   emerson/essays_first_series                         1.15 /           0.00
#   dickens/david_copperfield                           1.30 /           0.00
#   dickens/great_expectations                         21.75 /           0.00
#
# Chesterton did not change his punctuation between Orthodoxy and Heretics;
# his transcribers did. Left uncorrected, that variance lands in drift_A(f)
# and reads as topic sensitivity — and it concentrates in the tier-4
# char/punct features, which the codebase treats as the most edit-resistant
# identity signal. A first derivation run on unnormalised text ranked
# `semicolon_colon_rate` the 2nd MOST topic-sensitive feature, flatly
# contradicting the Lewis study, which found it the single most topic-
# INVARIANT (validation/genre_crossgenre_2026-08/README.md, Finding 4).
#
# Normalising here rather than in the corpus builder keeps the committed
# chunks faithful to their source; this is a measurement decision, not a
# correction to the text.
_TYPOGRAPHY = str.maketrans(
    {
        "“": '"',  # left double quote
        "”": '"',  # right double quote
        "‘": "'",  # left single quote
        "’": "'",  # right single quote / apostrophe
        "–": "-",  # en dash
        "—": "-",  # em dash
        "…": "...",  # ellipsis
        " ": " ",  # non-breaking space
    }
)


def normalise_typography(text: str) -> str:
    """Fold transcriber-specific typography to a single convention."""
    return text.translate(_TYPOGRAPHY)


def main() -> int:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    entries = manifest["entries"]
    print(
        f"corpus version {manifest['version']}: {len(entries)} chunks, "
        f"{len(manifest['authors'])} authors",
        flush=True,
    )

    vectors: list[np.ndarray] = []
    meta: list[dict] = []
    t0 = time.time()
    for n, entry in enumerate(entries, 1):
        text = (CORPUS / entry["filename"]).read_text(encoding="utf-8")
        vectors.append(feature_vector(normalise_typography(text)))
        meta.append(
            {
                "author": entry["author_id"],
                "work": entry["work_id"],
                "genre": entry["genre"],
                "role": entry["partition_role"],
                "filename": entry["filename"],
                "word_count": entry["word_count"],
            }
        )
        if n % 25 == 0 or n == len(entries):
            elapsed = time.time() - t0
            rate = n / elapsed
            print(
                f"  {n}/{len(entries)}  elapsed={elapsed:.0f}s  "
                f"eta={(len(entries) - n) / rate:.0f}s",
                flush=True,
            )

    arr = np.stack(vectors)
    np.save(VECTORS, arr)
    META.write_text(json.dumps(meta, indent=1) + "\n", encoding="utf-8")
    print(f"\nwrote {VECTORS.name} shape={arr.shape} and {META.name}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
