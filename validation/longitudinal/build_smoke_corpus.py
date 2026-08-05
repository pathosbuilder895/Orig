"""Build a small, real, dated single-author corpus to smoke-test the
longitudinal drift runner end-to-end.

This is deliberately NOT a locked benchmark. It exists to answer one
question: does `validation.longitudinal.run` actually load a manifest, score
each probe, and produce `gradual_drift`/`constant` verdicts without error?

Why this corpus and not the existing six-author cross-work corpus
(`validation/public_authors/cross_work_corpus/`): that corpus gives each
author only two works — two distinct time points — which cannot exercise a
trend fit (`LongitudinalConfig.min_samples_for_trend` requires six dated
samples before ANY probe is scored). This one needs a single author with many
separately-dated works.

Why Mark Twain: eight major novels with well-documented, unambiguous
first-publication years spanning 1869-1896 (27 years), all public domain and
individually available as single Project Gutenberg files (no chaptered
multi-file reassembly needed).

IMPORTANT — Project Gutenberg's catalogue "issued" date is the date the
*ebook* was released (all eight of these were released within weeks of each
other in mid-2004), not the date the *work* was originally published. Using
the PG issued date as `submitted_at` would silently replace 27 years of real
authorial evolution with a few weeks of PG's digitization batch order —
guaranteed to show either no drift or spurious digitization-order artifacts.
The years below are the real first-publication years, hand-verified against
public bibliographic record, not scraped from the catalogue. Day/month are
arbitrarily set to Jan 1: only year-level precision is claimed.

Run from the repository root:
    .venv/bin/python -m validation.longitudinal.build_smoke_corpus
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from validation.public_authors.build_corpus import _chunk_text  # noqa: E402
from validation.verify.gutenberg_corpus import _fetch, normalize_text  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = Path(__file__).with_name("smoke_corpus") / "twain"
MANIFEST_OUT = Path(__file__).with_name("smoke_manifest.json")
TEXT_URL = "https://www.gutenberg.org/cache/epub/{book_id}/pg{book_id}.txt"

# (Project Gutenberg book id, title, real first-publication year — verified
# against public bibliographic record, independent of PG's release date).
WORKS = [
    (3176, "The Innocents Abroad", 1869),
    (74, "The Adventures of Tom Sawyer, Complete", 1876),
    (119, "A Tramp Abroad", 1880),
    (1837, "The Prince and the Pauper", 1881),
    (245, "Life on the Mississippi", 1883),
    (86, "A Connecticut Yankee in King Arthur's Court", 1889),
    (102, "The Tragedy of Pudd'nhead Wilson", 1894),
    (2874, "Personal Recollections of Joan of Arc, Volume 1", 1896),
]

AUTHOR_ID = "twain"


def build() -> dict:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    entries = []
    for book_id, title, year in WORKS:
        raw = _fetch(TEXT_URL.format(book_id=book_id))
        text = normalize_text(raw)
        window = _chunk_text(text, 1)[0]
        words = window.split()
        if len(words) > 2500:
            window = " ".join(words[:2500])
        filename = f"{AUTHOR_ID}/{book_id}_{title.split(',')[0].lower().replace(' ', '_')}.txt"
        (OUT_DIR.parent / filename).write_text(window, encoding="utf-8")
        word_count = len(window.split())
        entries.append(
            {
                "author_id": AUTHOR_ID,
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
        print(f"  {book_id:>5}  {title:<50} {year}  {word_count} words")

    manifest = {
        "schema": "original.longitudinal.smoke.v1",
        "purpose": (
            "Wiring smoke test for validation.longitudinal.run — NOT a locked "
            "benchmark and NOT evidence for a promotion decision. Single "
            "author, eight real dated works, real publication years."
        ),
        "author": "Mark Twain (1835-1910)",
        "entries": entries,
    }
    MANIFEST_OUT.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


if __name__ == "__main__":
    build()
    print(f"\nwrote {MANIFEST_OUT.relative_to(ROOT)}")
