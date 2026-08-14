"""
Fetch additional public-domain authors for the thin genre classes.

Run:
    .venv/bin/python validation/genre_2026-08/fetch_authors.py

Why this exists. G8's precision leg failed for a structural reason rather
than a modelling one: `personal_essay` had three authors in the whole
repository and `creative_fiction` two, so leave-one-author-out cross
validation trained on one or two — the same single-author condition the
codebook rejects as an author detector. No amount of feature work or
regularisation fixes a class the corpus cannot represent, and both were
measured to fix nothing (minimum out-of-fold precision stayed at 0.000).

Six authors are added, three per thin class, chosen so each class rests on
several distinct writers rather than one voice:

    creative_fiction   Austen, Twain, Conan Doyle       (two works each)
    personal_essay     Franklin, Washington, Keller,
                       Grant, Cellini

Two works per fiction author rather than one: within-author variety keeps a
class from resting on a single book's voice, the same reason the split is
author-disjoint rather than document-disjoint.

Every work is verified against its expected title and author by
`_fetch_gutenberg` before use, so a wrong Project Gutenberg id fails loudly
instead of shipping a different book under the wrong name. Bodies are cached
so a re-run costs no network.
"""

from __future__ import annotations

import hashlib
import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent.parent
sys.path.insert(0, str(_ROOT))

from validation.public_authors.build_corpus import _fetch_gutenberg, _slugify  # noqa: E402
from validation.public_authors.build_cross_work import _sample_windows  # noqa: E402

CORPUS = _HERE / "corpus"
MANIFEST = _HERE / "corpus_manifest.json"
CHUNKS_PER_WORK = 14


@dataclass(frozen=True)
class Work:
    author_id: str
    author_name: str
    title: str
    pg_id: int
    genre: str


WORKS = (
    # creative_fiction — invented narrative, scene and character dialogue.
    Work("austen", "Jane Austen", "Pride and Prejudice", 1342, "creative_fiction"),
    Work("austen", "Jane Austen", "Emma", 158, "creative_fiction"),
    Work("twain", "Mark Twain", "Adventures of Huckleberry Finn", 76, "creative_fiction"),
    Work("twain", "Mark Twain", "The Adventures of Tom Sawyer", 74, "creative_fiction"),
    Work(
        "doyle",
        "Arthur Conan Doyle",
        "The Adventures of Sherlock Holmes",
        1661,
        "creative_fiction",
    ),
    Work(
        "doyle",
        "Arthur Conan Doyle",
        "The Hound of the Baskervilles",
        2852,
        "creative_fiction",
    ),
    # personal_essay — the writer's own life is the subject, not the
    # illustration. All three are autobiography proper, which is the least
    # ambiguous form the class has: the boundary trouble that sank the first
    # attempt was with essayists who argue in the first person, and adding
    # more of those would have deepened the problem rather than fixed it.
    Work(
        "franklin",
        "Benjamin Franklin",
        "The Autobiography of Benjamin Franklin",
        20203,
        "personal_essay",
    ),
    Work("washington", "Booker T. Washington", "Up From Slavery", 2376, "personal_essay"),
    Work("keller", "Helen Keller", "The Story of My Life", 2397, "personal_essay"),
    Work(
        "grant",
        "Ulysses S. Grant",
        "Personal Memoirs of U. S. Grant",
        4367,
        "personal_essay",
    ),
    Work("cellini", "Benvenuto Cellini", "The Autobiography of Benvenuto Cellini", 4028,
         "personal_essay"),
)


def main(force: bool = False) -> None:
    CORPUS.mkdir(parents=True, exist_ok=True)
    entries: list[dict] = []

    for work in WORKS:
        work_id = _slugify(work.title)
        author_dir = CORPUS / work.author_id
        author_dir.mkdir(exist_ok=True)
        cache = author_dir / f"_{work_id}_full.txt"

        if cache.exists() and not force:
            body = cache.read_text(encoding="utf-8")
        else:
            body = _fetch_gutenberg(work.pg_id, work.title, work.author_name)
            cache.write_text(body, encoding="utf-8")
            time.sleep(1.0)

        chunks = _sample_windows(body, CHUNKS_PER_WORK)
        if len(chunks) != CHUNKS_PER_WORK or min(len(c.split()) for c in chunks) < 300:
            raise ValueError(f"unusable chunks for Project Gutenberg {work.pg_id}")

        for index, text in enumerate(chunks, 1):
            # Normalised on write: no trailing whitespace, exactly one final
            # newline. The repo's pre-commit hooks enforce both, and a hook
            # rewriting a corpus file AFTER its sha256 went into the manifest
            # would leave the manifest quietly wrong about what is on disk.
            text = "\n".join(line.rstrip() for line in text.splitlines()).strip() + "\n"
            filename = f"{work.author_id}/{work_id}_{index:02d}.txt"
            (CORPUS / filename).write_text(text, encoding="utf-8")
            entries.append(
                {
                    "filename": filename,
                    "author_id": work.author_id,
                    "author_name": work.author_name,
                    "work_id": work_id,
                    "title": work.title,
                    "genre": work.genre,
                    "word_count": len(text.split()),
                    "source_url": f"https://www.gutenberg.org/ebooks/{work.pg_id}",
                    "source_pg_id": work.pg_id,
                    "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                    "license_note": (
                        "Project Gutenberg title page: public domain in the USA"
                    ),
                }
            )

    MANIFEST.write_text(
        json.dumps(
            {
                "version": "1.0-genre-thin-class-top-up",
                "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "jurisdiction": "United States",
                "purpose": (
                    "Additional authors for the genre classes the repository could "
                    "not represent: creative_fiction had 2 authors and "
                    "personal_essay 3, so leave-one-author-out trained on 1-2."
                ),
                "chunks_per_work": CHUNKS_PER_WORK,
                "entries": entries,
            },
            indent=1,
        )
        + "\n"
    )

    from collections import Counter

    per_genre = Counter(e["genre"] for e in entries)
    print(f"wrote {len(entries)} chunks to {CORPUS.relative_to(_ROOT)}")
    for genre, count in sorted(per_genre.items()):
        authors = sorted({e["author_id"] for e in entries if e["genre"] == genre})
        print(f"  {genre:20s} {count:3d} chunks  {authors}")


if __name__ == "__main__":
    main(force="--force" in sys.argv)
