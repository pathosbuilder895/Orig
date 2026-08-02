"""
Chunk the validation/public_authors corpus and extract feature vectors,
with per-file curation for the contamination found 2026-08-01:

  - edwards/: ALL parts are a French sci-fi novel, author dropped entirely
  - douglass/self_made_men.txt: actually Stephen Leacock, excluded
  - james parts 06-08: index back-matter, excluded
  - mill, kempis: part files are stubs; real text in _full_work_cache.txt
    (mill cache opens with an editor's preface -> skip the first 15%)
  - emerson/thoreau/douglass/james-pragmatism: Wikisource dumps -- nav chrome
    on short lines, body as one giant line -> line-filter + sentence-split

Cleaned roster: 10 authors.
"""
import json
import re
import sys
import time
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent.parent
sys.path.insert(0, str(_ROOT))

import numpy as np
from original.features.pipeline import feature_vector

HERE = Path(__file__).parent
CORPUS = _ROOT / "validation" / "public_authors" / "corpus"
CAP_PER_AUTHOR = 35
TARGET_WORDS = 700

EXCLUDE_AUTHORS = {"edwards"}
EXCLUDE_FILES = {
    "douglass/self_made_men.txt",
    "james/the_varieties_of_religious_experience_part_06.txt",
    "james/the_varieties_of_religious_experience_part_07.txt",
    "james/the_varieties_of_religious_experience_part_08.txt",
}
# authors whose real text lives in _full_work_cache.txt (part files are stubs)
USE_CACHE = {"mill": 0.15, "kempis": 0.05}  # value = leading fraction to skip

SENT_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[\"'“‘]?[A-Z])")


def split_oversized(paras, limit=900):
    out = []
    for p in paras:
        if len(p.split()) <= limit:
            out.append(p)
            continue
        sents, cur, cur_w = SENT_SPLIT.split(p), [], 0
        for s in sents:
            n = len(s.split())
            if cur_w + n > TARGET_WORDS and cur:
                out.append(" ".join(cur))
                cur, cur_w = [], 0
            cur.append(s)
            cur_w += n
        if cur:
            out.append(" ".join(cur))
    return out


def paragraphs_for(text):
    paras = [re.sub(r"\s+", " ", p).strip() for p in re.split(r"\n\s*\n", text)]
    big = [p for p in paras if len(p.split()) >= 15]
    if len(big) >= 5:
        return split_oversized(big)          # Gutenberg-style: real blank-line paragraphs
    # Wikisource-style: nav chrome on short lines, body on giant lines
    lines = [re.sub(r"\s+", " ", ln).strip() for ln in text.splitlines()]
    body = [ln for ln in lines if len(ln.split()) >= 15]
    return split_oversized(body)


def chunk_paragraphs(paras):
    chunks, cur, cur_words = [], [], 0
    for p in paras:
        n = len(p.split())
        if cur_words + n > TARGET_WORDS and cur:
            chunks.append(" ".join(cur))
            cur, cur_words = [], 0
        cur.append(p)
        cur_words += n
    if cur and cur_words >= TARGET_WORDS * 0.4:
        chunks.append(" ".join(cur))
    elif cur and chunks:
        chunks[-1] += " " + " ".join(cur)
    return chunks


def evenly_spaced(n, k):
    if n <= k:
        return list(range(n))
    return sorted(set(int(round(i * (n - 1) / (k - 1))) for i in range(k)))


def main():
    all_chunks = []
    for author_dir in sorted(CORPUS.iterdir()):
        if not author_dir.is_dir() or author_dir.name in EXCLUDE_AUTHORS:
            continue
        author = author_dir.name
        paras = []
        if author in USE_CACHE:
            text = (author_dir / "_full_work_cache.txt").read_text(encoding="utf-8", errors="ignore")
            text = text[int(len(text) * USE_CACHE[author]):]
            paras = paragraphs_for(text)
        else:
            for f in sorted(author_dir.glob("*.txt")):
                rel = f"{author}/{f.name}"
                if f.name.startswith("_full_work_cache") or rel in EXCLUDE_FILES:
                    continue
                paras.extend(paragraphs_for(f.read_text(encoding="utf-8", errors="ignore")))
        chunks = chunk_paragraphs(paras)
        keep = evenly_spaced(len(chunks), CAP_PER_AUTHOR)
        for j, k in enumerate(keep):
            all_chunks.append({
                "author": author,
                "chunk_id": f"{author}_{j:03d}",
                "word_count": len(chunks[k].split()),
                "text": chunks[k],
            })
        print(f"{author:12s} {len(chunks):4d} chunks -> kept {len(keep)}", flush=True)

    print(f"\nExtracting features for {len(all_chunks)} chunks...", flush=True)
    vectors, meta = [], []
    t0 = time.time()
    for n, c in enumerate(all_chunks):
        vectors.append(feature_vector(c["text"]))
        meta.append({k: c[k] for k in ("author", "chunk_id", "word_count")})
        if (n + 1) % 25 == 0 or n == len(all_chunks) - 1:
            el = time.time() - t0
            print(f"  {n+1}/{len(all_chunks)} elapsed={el:.0f}s "
                  f"remaining={(len(all_chunks)-n-1)*el/(n+1):.0f}s", flush=True)

    np.save(HERE / "pa_vectors.npy", np.stack(vectors))
    (HERE / "pa_meta.json").write_text(json.dumps(meta, indent=1))
    print(f"Done. shape={np.stack(vectors).shape}", flush=True)


if __name__ == "__main__":
    main()
