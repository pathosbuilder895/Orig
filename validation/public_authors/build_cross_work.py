"""Build a public-domain cross-work authorship corpus.

Unlike the legacy public-author manifest, no work contributes to both baseline
and probe. Project Gutenberg identifiers and US public-domain status were
verified on the title pages before inclusion (2026-08-04).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
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
    # 8, not 3: within_noise(f) — the denominator of the topic-sensitivity
    # ratio — is a within-work standard deviation, and 3 samples is a poor
    # estimate of one. 8 needs 8 x 2500 = 20,000 words per work, which every
    # work above clears; 12 would need 30,000 and Utilitarianism would fail.
    chunks: int = 8


# FOUR works per author, not two. `drift_A(f)` — the numerator of the
# topic-sensitivity ratio — is a standard deviation over per-work means, so at
# two works it is estimated from two points (effectively |mean_A - mean_B|/sqrt2)
# and cannot support a 109-dimensional constant. See
# docs/superpowers/specs/2026-08-06-topic-invariant-scoring-design.md.
#
# Selection rule: only works the author actually WROTE. Project Gutenberg's
# author search also returns anthologies, biographies ABOUT the author, and
# translations they merely contributed (e.g. Chesterton's Aesop's Fables) —
# all of which mention the author and would therefore sail past
# _fetch_gutenberg's author check while contaminating the corpus with someone
# else's prose. That is contamination mode 2, and the verification cannot
# catch it; work selection is the only defence.
#
# Titles are spelled as Project Gutenberg spells them, because
# _fetch_gutenberg requires >=60% of the title's >=4-character tokens to
# appear in the fetched text.
WORKS = (
    # ── dickens (fiction) ────────────────────────────────────────────────────
    Work("dickens", "Charles Dickens", "Great Expectations", 1400, "baseline", "fiction"),
    Work("dickens", "Charles Dickens", "David Copperfield", 766, "baseline", "fiction"),
    Work("dickens", "Charles Dickens", "A Tale of Two Cities", 98, "probe", "fiction"),
    Work("dickens", "Charles Dickens", "Bleak House", 1023, "probe", "fiction"),
    # ── chesterton (essay + fiction: within-author register spread) ──────────
    Work("chesterton", "G.K. Chesterton", "Orthodoxy", 130, "baseline", "essay"),
    Work("chesterton", "G.K. Chesterton", "What's Wrong with the World", 1717, "baseline", "essay"),
    Work("chesterton", "G.K. Chesterton", "Heretics", 470, "probe", "essay"),
    Work("chesterton", "G.K. Chesterton", "The Man Who Was Thursday", 1695, "probe", "fiction"),
    # ── christie (fiction) ───────────────────────────────────────────────────
    Work(
        "christie",
        "Agatha Christie",
        "The Mysterious Affair at Styles",
        863,
        "baseline",
        "fiction",
    ),
    Work("christie", "Agatha Christie", "The Murder on the Links", 58866, "baseline", "fiction"),
    Work("christie", "Agatha Christie", "The Secret Adversary", 1155, "probe", "fiction"),
    Work("christie", "Agatha Christie", "The Man in the Brown Suit", 61168, "probe", "fiction"),
    # ── emerson (essay) ──────────────────────────────────────────────────────
    Work("emerson", "Ralph Waldo Emerson", "Essays — First Series", 2944, "baseline", "essay"),
    Work("emerson", "Ralph Waldo Emerson", "Representative Men", 6312, "baseline", "essay"),
    Work("emerson", "Ralph Waldo Emerson", "Essays — Second Series", 2945, "probe", "essay"),
    Work("emerson", "Ralph Waldo Emerson", "The Conduct of Life", 39827, "probe", "essay"),
    # ── mill (essay) ─────────────────────────────────────────────────────────
    Work("mill", "John Stuart Mill", "On Liberty", 34901, "baseline", "essay"),
    Work("mill", "John Stuart Mill", "The Subjection of Women", 27083, "baseline", "essay"),
    Work("mill", "John Stuart Mill", "Utilitarianism", 11224, "probe", "essay"),
    Work(
        "mill",
        "John Stuart Mill",
        "Considerations on Representative Government",
        5669,
        "probe",
        "essay",
    ),
    # ── thoreau (essay) ──────────────────────────────────────────────────────
    Work(
        "thoreau",
        "Henry David Thoreau",
        "Walden, and On the Duty of Civil Disobedience",
        205,
        "baseline",
        "essay",
    ),
    Work(
        "thoreau",
        "Henry David Thoreau",
        "A Week on the Concord and Merrimack Rivers",
        4232,
        "baseline",
        "essay",
    ),
    Work("thoreau", "Henry David Thoreau", "Cape Cod", 34392, "probe", "essay"),
    Work("thoreau", "Henry David Thoreau", "The Maine Woods", 42500, "probe", "essay"),
)


# Inline editorial markup that is not the author's prose. Illustration
# captions in particular are dense in brackets, underscores and colons, so they
# perturb the tier-4 char/punct fingerprint — one of the most heavily weighted
# tiers (1.3) and one of the most topic-INVARIANT, which is exactly the signal
# the derivation is trying to measure.
_INLINE_MARKUP_RE = re.compile(r"\[Illustration[^\]]*\]", re.IGNORECASE)

# Markers that mean a window is front matter rather than prose.
#
# CASE-SENSITIVE, deliberately. An earlier case-insensitive `\bCONTENTS\b`
# matched the ordinary English word — "the contents of her handbag", "we note
# the contents thereof" — in 11 of 24 works, which is a false positive on
# perfectly good prose. Front matter announces itself in capitals; ordinary
# usage does not. The chapter-listing pattern is likewise structural: three
# consecutive "CHAPTER <roman>" headings is a table of contents, not narrative.
_FRONT_MATTER_RE = re.compile(
    r"\bCONTENTS\b"
    r"|BY THE SAME AUTHOR"
    r"|Manuscript Edition"
    r"|Limited to .{0,20}Copies"
    r"|Transcriber'?s? Note"
    r"|(?:CHAPTER [IVXL]+\.?\s+){3,}"
)


def _sample_windows(
    text: str, count: int, words_per_window: int = 2500, lead_in: int = 2500
) -> list[str]:
    """Take evenly spaced, non-overlapping essay-length windows from a work.

    `lead_in` words are skipped before sampling begins. Stripping the Project
    Gutenberg header does NOT remove the book's own front matter — title page,
    publisher's list, table of contents, edition statement — and sampling from
    word 0 therefore made chunk 01 of half the works a contents listing rather
    than prose. Those chunks are not the author writing, and because the
    contamination lands on the same index of every affected work it biases
    `within_noise(f)` systematically rather than randomly.
    """

    text = _INLINE_MARKUP_RE.sub(" ", text)
    words = text.split()

    # Find where front matter actually ends rather than assuming a fixed
    # margin clears it. A flat 2500-word lead-in is wrong in both directions:
    # too much for a work that starts immediately, and too little for one like
    # On Liberty, whose Gutenberg edition runs a long editor's introduction
    # BEFORE its table of contents — so its contents page sits past word 2500
    # and landed in the middle of a sampled window.
    #
    # Scan only the opening quarter: a marker later than that is prose using
    # the same words, not front matter.
    scan_limit = max(lead_in, len(words) // 4)
    head = " ".join(words[:scan_limit])
    last = None
    for m in _FRONT_MATTER_RE.finditer(head):
        last = m
    if last is not None:
        # Convert the character offset back to a word offset, then clear the
        # matched block plus a small margin for the trailing page numbers a
        # contents listing ends with.
        start_words = len(head[: last.end()].split()) + 50
        lead_in = max(lead_in, start_words)

    required = lead_in + count * words_per_window
    if len(words) < required:
        raise ValueError(
            f"work has {len(words)} words; need at least {required} "
            f"({lead_in} lead-in + {count} x {words_per_window})"
        )
    words = words[lead_in:]
    max_start = len(words) - words_per_window
    starts = np.linspace(0, max_start, count, dtype=int)
    # Non-overlap is load-bearing, not cosmetic: these windows are the samples
    # `within_noise(f)` is estimated from, and overlapping windows share text,
    # so their features correlate and the estimate comes out too small —
    # which would inflate every topic-sensitivity ratio that divides by it.
    # The `required` check above implies this, but assert it rather than
    # trusting an implication to survive a future edit to either.
    gaps = np.diff(starts)
    if len(gaps) and int(gaps.min()) < words_per_window:
        raise ValueError(
            f"windows overlap: min gap {int(gaps.min())} < {words_per_window} words "
            f"({count} chunks from {len(words)} words)"
        )
    windows = [" ".join(words[start : start + words_per_window]) for start in starts]

    # Verify the lead-in was actually sufficient for THIS work rather than
    # assuming a fixed margin clears every edition's front matter.
    for i, w in enumerate(windows, 1):
        m = _FRONT_MATTER_RE.search(w)
        if m:
            raise ValueError(
                f"window {i} still looks like front matter (matched {m.group(0)!r}); "
                f"raise lead_in above {lead_in}"
            )
    return windows


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
            # Pass title and author so _fetch_gutenberg's verification actually
            # runs. This call used to supply only pg_id, against a 3-argument
            # signature — so ANY cache miss raised TypeError and the documented
            # rebuild path could not run at all. No `_*_full.txt` caches are
            # committed, so in practice the corpus was frozen at whatever chunk
            # files happened to be checked in. The verification it skipped is
            # the guard against shipping a different book under this author's
            # name (contamination mode 2).
            body = _fetch_gutenberg(work.pg_id, work.title, work.author_name)
            cache.write_text(body, encoding="utf-8")
            time.sleep(1.0)
        chunks = _sample_windows(body, work.chunks)
        if len(chunks) != work.chunks or min(len(c.split()) for c in chunks) < 300:
            raise ValueError(f"unusable chunks for Project Gutenberg {work.pg_id}")
        authors.setdefault(work.author_id, {"name": work.author_name, "native_english": True})
        for index, text in enumerate(chunks, 1):
            filename = f"{work.author_id}/{work_id}_{index:02d}.txt"
            # Write and hash the SAME bytes, newline included. The repo's
            # end-of-file-fixer pre-commit hook appends a trailing newline to
            # every committed text file, so writing without one desynchronises
            # the file from the text_sha256 recorded beside it — the manifest
            # would then describe content that no longer exists on disk. The
            # existing committed corpus already hashes newline-terminated text;
            # this makes that convention explicit rather than incidental.
            payload = text + "\n"
            (CORPUS / filename).write_text(payload, encoding="utf-8")
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
                    "text_sha256": hashlib.sha256(payload.encode("utf-8")).hexdigest(),
                    "license_note": "Project Gutenberg title page: public domain in the USA",
                }
            )
    manifest = {
        "version": "4.1-six-author-cross-work-4x8-leadin",
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
