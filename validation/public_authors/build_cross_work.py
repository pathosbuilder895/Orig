"""Build a public-domain cross-work authorship corpus.

Unlike the legacy public-author manifest, no work contributes to both baseline
and probe. Project Gutenberg identifiers and US public-domain status were
verified on the title pages before inclusion (2026-08-04).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .build_corpus import _fetch_gutenberg, _slugify

HERE = Path(__file__).resolve().parent
CORPUS = HERE / "cross_work_corpus"
MANIFEST = HERE / "cross_work_manifest.json"


@dataclass(frozen=True)
class Work:
    author_id: str
    author_name: str
    title: str
    pg_id: int
    role: str  # baseline | probe
    genre: str
    chunks: int = 3


WORKS = (
    Work("dickens", "Charles Dickens", "Great Expectations", 1400, "baseline", "fiction"),
    Work("dickens", "Charles Dickens", "A Tale of Two Cities", 98, "probe", "fiction"),
    Work("chesterton", "G.K. Chesterton", "Orthodoxy", 130, "baseline", "essay"),
    Work("chesterton", "G.K. Chesterton", "Heretics", 470, "probe", "essay"),
    Work(
        "christie",
        "Agatha Christie",
        "The Mysterious Affair at Styles",
        863,
        "baseline",
        "fiction",
    ),
    Work("christie", "Agatha Christie", "The Secret Adversary", 1155, "probe", "fiction"),
    Work("emerson", "Ralph Waldo Emerson", "Essays — First Series", 2944, "baseline", "essay"),
    Work("emerson", "Ralph Waldo Emerson", "Essays — Second Series", 2945, "probe", "essay"),
    Work("mill", "John Stuart Mill", "On Liberty", 34901, "baseline", "essay"),
    Work("mill", "John Stuart Mill", "Utilitarianism", 11224, "probe", "essay"),
    Work(
        "thoreau",
        "Henry David Thoreau",
        "Walden, and On the Duty of Civil Disobedience",
        205,
        "baseline",
        "essay",
    ),
    Work("thoreau", "Henry David Thoreau", "Cape Cod", 34392, "probe", "essay"),
)


def _sample_windows(text: str, count: int, words_per_window: int = 2500) -> list[str]:
    """Take evenly spaced, non-overlapping essay-length windows from a work."""

    words = text.split()
    required = count * words_per_window
    if len(words) < required:
        raise ValueError(f"work has {len(words)} words; need at least {required}")
    max_start = len(words) - words_per_window
    starts = np.linspace(0, max_start, count, dtype=int)
    return [" ".join(words[start : start + words_per_window]) for start in starts]


def build(*, force: bool = False) -> dict:
    CORPUS.mkdir(parents=True, exist_ok=True)
    entries: list[dict] = []
    authors: dict[str, dict] = {}
    for work in WORKS:
        work_id = _slugify(work.title)
        author_dir = CORPUS / work.author_id
        author_dir.mkdir(exist_ok=True)
        cache = author_dir / f"_{work_id}_full.txt"
        if cache.exists() and not force:
            body = cache.read_text(encoding="utf-8")
        else:
            body = _fetch_gutenberg(work.pg_id)
            cache.write_text(body, encoding="utf-8")
            time.sleep(1.0)
        chunks = _sample_windows(body, work.chunks)
        if len(chunks) != work.chunks or min(len(c.split()) for c in chunks) < 300:
            raise ValueError(f"unusable chunks for Project Gutenberg {work.pg_id}")
        authors.setdefault(work.author_id, {"name": work.author_name, "native_english": True})
        for index, text in enumerate(chunks, 1):
            filename = f"{work.author_id}/{work_id}_{index:02d}.txt"
            (CORPUS / filename).write_text(text, encoding="utf-8")
            entries.append(
                {
                    "filename": filename,
                    "author_id": work.author_id,
                    "work_id": work_id,
                    "label": "authentic",
                    "prompt": work.title,
                    "word_count": len(text.split()),
                    "is_baseline": work.role == "baseline",
                    "partition_role": work.role,
                    "genre": work.genre,
                    "language": "en",
                    "translation": False,
                    "ai_provider": "none",
                    "native_english": True,
                    "source_url": f"https://www.gutenberg.org/ebooks/{work.pg_id}",
                    "source_pg_id": work.pg_id,
                    "source_body_sha256": hashlib.sha256(body.encode("utf-8")).hexdigest(),
                    "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                    "license_note": "Project Gutenberg title page: public domain in the USA",
                }
            )
    manifest = {
        "version": "3.0-six-author-cross-work",
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "split_rule": "A work appears in exactly one of baseline or probe.",
        "jurisdiction": "United States",
        "authors": authors,
        "entries": entries,
    }
    MANIFEST.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    result = build(force=args.force)
    print(f"wrote {len(result['entries'])} entries to {MANIFEST}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
