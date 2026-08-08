"""
scripts/fetch_seminary_theology_corpus.py — stage real, pre-LLM-era theology
prose for ingestion into the seminary_authentic pool.

`validation/manifest.json`'s `seminary_authentic` group (the false-positive
rate that gates `AI_LIKELIHOOD_ENABLED`, see `scripts/train_ai_detector.py
eval-seminary`) held only 25 essays — all synthetic, from
`validation/generate_modern_corpus.py`'s 5 templated student profiles. At
n=25 the gate moves in 1/25 = 0.04 steps, so a single borderline essay
decides pass/fail (see MODEL_CARD.md v1.4.26, re-cleared in v1.4.27 by
this corpus growth). This script fetches real
public-domain theological/devotional prose — sermons and addresses by
authors who died decades before any LLM existed, so authenticity is not in
question — chunks it into essay-sized (~300-550 word) excerpts, and stages
them for `scripts/add_seminary_essays.py` to ingest.

This is deliberately a two-step pipeline, mirroring how
`validation/public_authors/build_corpus.py` (fetch+verify+chunk) and
`scripts/add_ai_essays.py` (validate+ingest) are already split in this repo:
this script only stages verified .txt files to a local directory; nothing
under validation/ is written until add_seminary_essays.py runs against that
staging directory.

Reuses `validation.public_authors.build_corpus`'s already-verified Gutenberg
fetch/strip/chunk helpers rather than reimplementing them — same
contamination guards (author/title match, English-prose ratio, back-matter
truncation), same paragraph-balanced chunker.

One additional guard this script adds on top of that: these particular
source books (Fleming H. Revell Co. reprints, mostly) carry trailing
publisher's-catalog ad pages ("THE RED LIBRARY", lists of other titles)
inside the Gutenberg body text, past the point `_truncate_back_matter`'s
INDEX/FOOTNOTES/... heading regex looks for. A catalog "paragraph" is a
single book title — a handful of words — so a chunk's mean words-per-
paragraph is a strong, generator-agnostic signal: real sermon/address prose
in this corpus never drops below ~20; every rejected catalog-contaminated
chunk sampled during development was under 10. The first and last fine
chunk of every work are also always dropped (title page / TOC and
catalog / colophon risk concentrate there).

Run:
    .venv/bin/python scripts/fetch_seminary_theology_corpus.py --out /tmp/seminary_staging
    # then, per author group printed at the end:
    .venv/bin/python scripts/add_seminary_essays.py /tmp/seminary_staging/seminary_06_moody \\
        --author-name "Dwight Lyman Moody" --author-id seminary_06 \\
        --title "The Overcoming Life, and Other Sermons" \\
        --tradition "Evangelical (Congregationalist revivalist)" --native-english \\
        --source-note "Project Gutenberg #33015 (https://www.gutenberg.org/ebooks/33015)"
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import List

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

import validation.public_authors.build_corpus as bc  # noqa: E402

TARGET_CHUNK_WORDS = 400  # matches the existing seminary essays' ~310-460w register
MIN_ESSAY_WORDS = 300  # validation.corpus_policy.VERIFICATION_MIN_WORDS
MAX_ESSAY_WORDS = 600
MIN_MEAN_PARAGRAPH_WORDS = 20  # below this, a chunk is TOC/catalog/index, not prose


@dataclass(frozen=True)
class SourceWork:
    group_slug: str  # staging subdirectory name, e.g. "seminary_06_moody"
    author_name: str
    title: str
    pg_id: int
    target_essays: int  # how many essays to keep from this work, evenly sampled


# ── Curated roster ───────────────────────────────────────────────────────────
#
# All died well before any LLM existed (native_english / dates verified
# against the Gutenberg header + public biographical record — this is what
# "pre-LLM-era" authenticity rests on, same spirit as build_corpus.py's
# author/title verification for a different threat model).
#   Moody     d. 1899   Torrey    d. 1928   Murray  d. 1917
#   Drummond  d. 1897   Spurgeon  d. 1892   Brooks  d. 1893
WORKS: List[SourceWork] = [
    SourceWork("seminary_06_moody", "Dwight Lyman Moody", "The Overcoming Life, and Other Sermons", 33015, 18),
    SourceWork("seminary_07_torrey", "Reuben Archer Torrey", "The Person and Work of the Holy Spirit", 30241, 20),
    SourceWork("seminary_08_murray", "Andrew Murray", "Holy in Christ", 26990, 8),
    SourceWork("seminary_08_murray", "Andrew Murray", "Humility: The Beauty of Holiness", 57121, 6),
    SourceWork("seminary_08_murray", "Andrew Murray", "The Ministry of Intercession", 29296, 8),
    SourceWork("seminary_09_drummond", "Henry Drummond", "The Greatest Thing in the World, and Other Addresses", 16739, 16),
    SourceWork("seminary_10_spurgeon", "Charles Haddon Spurgeon", "Around the Wicket Gate", 60669, 6),
    SourceWork("seminary_10_spurgeon", "Charles Haddon Spurgeon", "Talks to Farmers", 42518, 8),
    SourceWork("seminary_10_spurgeon", "Charles Haddon Spurgeon", "Gleanings among the Sheaves", 42657, 8),
    SourceWork("seminary_11_brooks", "Phillips Brooks", "Addresses by the Right Reverend Phillips Brooks", 14497, 16),
]


def _mean_paragraph_words(text: str) -> float:
    paras = [p for p in re.split(r"\n\s*\n", text) if p.strip()]
    if not paras:
        return 0.0
    return sum(len(p.split()) for p in paras) / len(paras)


def _candidate_chunks(work: SourceWork) -> List[str]:
    """Fetch, verify, and finely chunk one work; return only clean prose chunks."""
    body = bc._fetch_gutenberg(work.pg_id, work.title, work.author_name)
    body = bc._truncate_back_matter(body)
    total_words = len(body.split())
    n_chunks = max(3, total_words // TARGET_CHUNK_WORDS)
    chunks = bc._chunk_text(body, n_chunks)
    # Drop the first and last fine chunk unconditionally: title page/TOC and
    # publisher's catalog/colophon concentrate there (see module docstring).
    chunks = chunks[1:-1]

    good: List[str] = []
    for c in chunks:
        wc = len(c.split())
        if not (MIN_ESSAY_WORDS <= wc <= MAX_ESSAY_WORDS):
            continue
        if _mean_paragraph_words(c) < MIN_MEAN_PARAGRAPH_WORDS:
            continue
        if bc._validate_prose(c, MIN_ESSAY_WORDS, work.title):
            continue
        good.append(c)
    return good


def _evenly_sample(items: List[str], k: int) -> List[str]:
    """Evenly spaced sample across the work, not just its first k chunks —
    preserves topic spread instead of concentrating on one section."""
    n = len(items)
    if k >= n:
        return items
    return [items[round(i * (n - 1) / (k - 1))] for i in range(k)] if k > 1 else [items[n // 2]]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--out", type=Path, required=True, help="Staging directory to write chunks into.")
    ap.add_argument(
        "--only", default=None, help="Only process one group_slug (e.g. seminary_08_murray)."
    )
    args = ap.parse_args(argv)

    args.out.mkdir(parents=True, exist_ok=True)
    total_written = 0
    for work in WORKS:
        if args.only and work.group_slug != args.only:
            continue
        print(f"[fetch-seminary] {work.author_name} — {work.title} (pg{work.pg_id})", flush=True)
        try:
            good = _candidate_chunks(work)
        except Exception as e:
            print(f"  FAILED: {e}", file=sys.stderr, flush=True)
            return 1
        sampled = _evenly_sample(good, work.target_essays)
        # One subdirectory per SOURCE WORK, nested under the author group —
        # an author with several works (e.g. Murray, Spurgeon below) pools
        # them under one seminary_NN identity via repeated add_seminary_
        # essays.py calls, but each call needs a single --title, so each
        # work's chunks must stay separable rather than flatten together.
        title_slug = re.sub(r"[^a-z0-9]+", "_", work.title.lower()).strip("_")
        work_dir = args.out / work.group_slug / title_slug
        work_dir.mkdir(parents=True, exist_ok=True)
        for i, chunk in enumerate(sampled, start=1):
            path = work_dir / f"{i:03d}.txt"
            path.write_text(chunk.strip() + "\n", encoding="utf-8")
        print(
            f"  {len(good)} clean candidate chunks, kept {len(sampled)} "
            f"(evenly sampled) → {work_dir}",
            flush=True,
        )
        total_written += len(sampled)

    print(f"\n[fetch-seminary] staged {total_written} essay(s) total under {args.out}")
    print("next, per group directory: scripts/add_seminary_essays.py <group_dir> --author-name ... ")
    return 0


if __name__ == "__main__":
    sys.exit(main())
