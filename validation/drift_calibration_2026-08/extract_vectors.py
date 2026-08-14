"""Extract feature vectors for the Phase-8 drift-gate calibration study.

Extracts the full 109-dim production feature vector (``feature_vector``) once
per corpus text and caches the results to an ``.npz`` so the threshold sweep
in ``calibrate.py`` never re-runs the pipeline.

Corpus selection
----------------
Genuine single-author sets (false-hold side):
  - seminary_01..11 (validation/corpus/seminary_*.txt) — the same texts the
    G1/G6 calibration-gate legs upload; the population check_drift actually
    gates in the demo stack.
  - burke / douglass / lincoln / paine (first 60 docs each, sorted order),
    fed_hamilton / fed_madison / fed_jay — real historical single-author
    prose at realistic upload lengths (~800-2000 words).
  - validation/public_authors/corpus — 11 more authors (3-6 docs each);
    docs are truncated to MAX_WORDS words because several are full essays
    (10k+ words) far beyond any realistic baseline upload.

Impostor-only sets (catch side):
  - ai_*.txt, ghost_*.txt — AI-generated / ghostwritten seminary-register
    texts; never used as genuine baselines.

Usage:
  ~/Desktop/Original/.venv/bin/python validation/drift_calibration_2026-08/extract_vectors.py OUT.npz
"""

from __future__ import annotations

import glob
import json
import os
import re
import sys
import time
from multiprocessing import Pool

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, REPO)

CORPUS = os.path.join(REPO, "validation", "corpus")
PUBLIC = os.path.join(REPO, "validation", "public_authors")

# Cap for oversized public_authors essays (words). Real baseline uploads are
# essays, not books; the attribution floor is >=300 words and pilot uploads
# run ~300-2000.
MAX_WORDS = 1500
# Cap the two 173-doc historical sets — 60 sequential docs is far beyond any
# real student's upload count and keeps extraction tractable.
MAX_DOCS_PER_BIG_AUTHOR = 60


def collect() -> list[dict]:
    entries: list[dict] = []

    # Seminary authors: seminary_01..05 are seminary_NN_<topic>.txt,
    # seminary_06..11 are seminary_NN_MMM.txt. Group by the NN author id.
    for f in sorted(glob.glob(os.path.join(CORPUS, "seminary_*.txt"))):
        m = re.match(r"seminary_(\d+)_", os.path.basename(f))
        if not m:
            continue
        entries.append(
            {"path": f, "author": f"seminary_{m.group(1)}", "family": "seminary", "role": "genuine"}
        )

    for author, cap in [
        ("burke", MAX_DOCS_PER_BIG_AUTHOR),
        ("douglass", MAX_DOCS_PER_BIG_AUTHOR),
        ("lincoln", MAX_DOCS_PER_BIG_AUTHOR),
        ("paine", MAX_DOCS_PER_BIG_AUTHOR),
        ("fed_hamilton", None),
        ("fed_madison", None),
        ("fed_jay", None),
    ]:
        files = sorted(glob.glob(os.path.join(CORPUS, f"{author}_*.txt")))
        if cap:
            files = files[:cap]
        for f in files:
            entries.append({"path": f, "author": author, "family": "historical", "role": "genuine"})

    for prefix in ("ai", "ghost"):
        for f in sorted(glob.glob(os.path.join(CORPUS, f"{prefix}_*.txt"))):
            entries.append(
                {"path": f, "author": prefix, "family": "seminary", "role": "impostor_only"}
            )

    manifest = json.load(open(os.path.join(PUBLIC, "manifest.json")))
    for e in manifest["entries"]:
        if e.get("label") != "authentic":
            continue  # AI/obfuscated entries are a different study's material
        entries.append(
            {
                "path": os.path.join(PUBLIC, "corpus", e["filename"]),
                "author": f"pa_{e['author_id']}",
                "family": "public_authors",
                "role": "genuine",
            }
        )
    return entries


def _extract(entry: dict):
    from original.features.pipeline import feature_vector

    text = open(entry["path"], encoding="utf-8").read()
    words = text.split()
    truncated = False
    if len(words) > MAX_WORDS:
        text = " ".join(words[:MAX_WORDS])
        truncated = True
    vec = feature_vector(text)
    return entry, vec, len(words), truncated


def main(out_path: str) -> None:
    import numpy as np

    entries = collect()
    print(f"{len(entries)} docs to extract", flush=True)
    t0 = time.time()
    results = []
    with Pool(max(2, (os.cpu_count() or 4) - 2)) as pool:
        for i, r in enumerate(pool.imap_unordered(_extract, entries, chunksize=4)):
            results.append(r)
            if (i + 1) % 25 == 0:
                print(f"  {i + 1}/{len(entries)}  ({time.time() - t0:.0f}s)", flush=True)

    vecs = np.stack([r[1] for r in results])
    meta = [
        {**r[0], "word_count": r[2], "truncated": r[3], "path": os.path.relpath(r[0]["path"], REPO)}
        for r in results
    ]
    np.savez_compressed(out_path, vectors=vecs, meta=json.dumps(meta))
    print(f"wrote {out_path}: {vecs.shape} in {time.time() - t0:.0f}s", flush=True)


if __name__ == "__main__":
    main(sys.argv[1])
