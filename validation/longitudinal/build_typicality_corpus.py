"""Build a small, real, dated TWO-author corpus to measure whether
trend_aware_typicality actually helps -- higher same-author recognition,
lower false-positive rate against an impostor -- versus the flat,
recency-weighted reference `state.loo_distances` uses today.

Separate from build_smoke_corpus.py's single-author Twain corpus on
purpose: that corpus and its manifest are pinned by an existing regression
test (tests/quantum/test_dirichlet_multinomial_drift.py) that reads the
WHOLE manifest as one author's trajectory. Mixing a second author into that
file would silently corrupt that test's meaning. This writes to its own
directory and manifest instead.

Two authors, not more, is a deliberate floor: this is a wiring/direction
smoke test for trend_aware_typicality's real behavior on real prose, not a
locked benchmark. Real chronological, multi-work bibliographies at scale
would need either hand-curation (does not scale past a handful of authors
in one session) or a large pre-registered corpus (the existing Gutenberg
400-writer builder, validation/verify/gutenberg_corpus.py, which lacks
usable per-work publication dates -- see build_smoke_corpus.py's docstring
for why PG's "issued" field can't substitute).

Run from the repository root:
    .venv/bin/python -m validation.longitudinal.build_typicality_corpus
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from validation.public_authors.build_corpus import _chunk_text  # noqa: E402
from validation.verify.gutenberg_corpus import _fetch, normalize_text  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
OUT_ROOT = Path(__file__).with_name("typicality_corpus")
MANIFEST_OUT = Path(__file__).with_name("typicality_manifest.json")
TEXT_URL = "https://www.gutenberg.org/cache/epub/{book_id}/pg{book_id}.txt"

# (Project Gutenberg book id, title, real first-publication year -- hand-
# verified against public bibliographic record, independent of PG's release
# date; see build_smoke_corpus.py for why that distinction matters).
AUTHORS = {
    "twain": {
        "display_name": "Mark Twain (1835-1910)",
        "works": [
            (3176, "The Innocents Abroad", 1869),
            (74, "The Adventures of Tom Sawyer, Complete", 1876),
            (119, "A Tramp Abroad", 1880),
            (1837, "The Prince and the Pauper", 1881),
            (245, "Life on the Mississippi", 1883),
            (86, "A Connecticut Yankee in King Arthur's Court", 1889),
            (102, "The Tragedy of Pudd'nhead Wilson", 1894),
            (2874, "Personal Recollections of Joan of Arc, Volume 1", 1896),
        ],
    },
    "dickens": {
        "display_name": "Charles Dickens (1812-1870)",
        "works": [
            (580, "The Pickwick Papers", 1837),
            (730, "Oliver Twist", 1838),
            (700, "The Old Curiosity Shop", 1841),
            (968, "Martin Chuzzlewit", 1844),
            (821, "Dombey and Son", 1848),
            (766, "David Copperfield", 1850),
            (1023, "Bleak House", 1853),
            (883, "Our Mutual Friend", 1865),
        ],
    },
}


def build() -> dict:
    entries = []
    for author_id, meta in AUTHORS.items():
        out_dir = OUT_ROOT / author_id
        out_dir.mkdir(parents=True, exist_ok=True)
        print(f"-- {meta['display_name']} --")
        for book_id, title, year in meta["works"]:
            raw = _fetch(TEXT_URL.format(book_id=book_id))
            text = normalize_text(raw)
            window = _chunk_text(text, 1)[0]
            words = window.split()
            if len(words) > 2500:
                window = " ".join(words[:2500])
            slug = title.split(",")[0].lower().replace(" ", "_").replace("'", "")
            filename = f"{author_id}/{book_id}_{slug}.txt"
            (OUT_ROOT / filename).write_text(window, encoding="utf-8")
            word_count = len(window.split())
            entries.append(
                {
                    "author_id": author_id,
                    "filename": filename,
                    "label": "authentic",
                    "prompt": title,
                    "submitted_at": f"{year}-01-01",
                    "word_count": word_count,
                    "genre": "fiction",
                    "source_pg_id": book_id,
                    "license_note": "Project Gutenberg title page: public domain in the USA",
                    "date_precision": "year-only; day/month is a placeholder, not a real submission date",
                }
            )
            print(f"  {book_id:>5}  {title:<45} {year}  {word_count} words")

    manifest = {
        "schema": "original.longitudinal.typicality_smoke.v1",
        "purpose": (
            "Measures whether trend_aware_typicality changes same-author "
            "recognition / impostor-rejection versus the flat, recency-"
            "weighted reference state.loo_distances uses today. NOT a "
            "locked benchmark -- two authors, eight works each, real "
            "publication years. See validation/longitudinal/README.md."
        ),
        "authors": {aid: meta["display_name"] for aid, meta in AUTHORS.items()},
        "entries": entries,
    }
    MANIFEST_OUT.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


if __name__ == "__main__":
    build()
    print(f"\nwrote {MANIFEST_OUT.relative_to(ROOT)}")
