"""Compute feature_vector() for a capped, evenly-spaced sample of chunks per work,
caching results to disk so sweep_harness.py / action_mode_sweep.py never have
to re-run extraction. Companion to validation/public_authors/ -- see README.md
for how this differs from that harness.
"""
import json
import sys
import time
from collections import defaultdict
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent.parent
sys.path.insert(0, str(_ROOT))

import numpy as np
from original.features.pipeline import feature_vector

HERE = Path(__file__).parent
CAP_PER_WORK = 35


def evenly_spaced_indices(n: int, k: int) -> list[int]:
    if n <= k:
        return list(range(n))
    return sorted(set(int(round(i * (n - 1) / (k - 1))) for i in range(k)))


def main():
    records = json.loads((HERE / "chunks.json").read_text())
    by_work = defaultdict(list)
    for i, r in enumerate(records):
        work_slug = r["chunk_id"].rsplit("_", 1)[0]
        by_work[work_slug].append(i)

    selected = []
    for work_slug, idxs in by_work.items():
        keep = evenly_spaced_indices(len(idxs), CAP_PER_WORK)
        selected.extend(idxs[k] for k in keep)
    selected.sort()
    print(f"Selected {len(selected)} / {len(records)} chunks (cap={CAP_PER_WORK}/work)", flush=True)

    vectors = []
    kept_records = []
    t_start = time.time()
    for n, i in enumerate(selected):
        r = records[i]
        vec = feature_vector(r["text"])
        vectors.append(vec)
        kept_records.append({k: r[k] for k in ("author", "work", "genre", "chunk_id", "word_count")})
        if (n + 1) % 25 == 0 or n == len(selected) - 1:
            elapsed = time.time() - t_start
            rate = (n + 1) / elapsed
            remaining = (len(selected) - n - 1) / rate if rate > 0 else float("inf")
            print(f"  {n+1}/{len(selected)}  elapsed={elapsed:.0f}s  est_remaining={remaining:.0f}s", flush=True)

    arr = np.stack(vectors)
    np.save(HERE / "vectors.npy", arr)
    (HERE / "vectors_meta.json").write_text(json.dumps(kept_records, indent=1))
    print(f"\nDone. vectors.npy shape={arr.shape}, total_time={time.time()-t_start:.0f}s", flush=True)


if __name__ == "__main__":
    main()
