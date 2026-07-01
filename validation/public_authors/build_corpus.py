"""
validation/public_authors/build_corpus.py — pull a public-domain author corpus.

Builds a small reproducible authorship-attribution corpus from Wikisource
+ Project Gutenberg. Each essay is uniquely attributed to one author by
the public record, so the ground truth is independently verifiable by
anyone — that is what makes this a real validation rather than a
synthetic benchmark.

The corpus is laid down at:
    validation/public_authors/corpus/<author_id>/<essay_id>.txt
plus
    validation/public_authors/manifest.json   (CorpusEntry shape)

Run:
    python -m validation.public_authors.build_corpus
Or refresh a single author:
    python -m validation.public_authors.build_corpus --only chesterton

Source URLs are curated by hand — committed-to-repo URL list = anyone
can re-build the same corpus and get the same files. No API keys, no
auth, just a polite User-Agent and a respectful sleep between fetches.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

import httpx

_HERE = Path(__file__).resolve().parent
_CORPUS_DIR = _HERE / "corpus"
_MANIFEST = _HERE / "manifest.json"

UA = "OriginalAccuracyBenchmark/1.0 (mailto:arclark555@gmail.com)"
FETCH_SLEEP_SEC = 1.0   # be polite

# ── Curated essay list (8 authors × 5 essays) ────────────────────────────────
#
# Each essay is identified by its Wikisource canonical URL. The slug we use
# as the local filename is a stable identifier — changing it would invalidate
# the manifest.

@dataclass(frozen=True)
class EssayRef:
    author_id: str          # canonical short-id used in filenames
    author_name: str        # display name
    title: str
    url: str
    is_baseline: bool       # True → baseline; False → held-out for scoring


@dataclass(frozen=True)
class GutenbergWork:
    """Fallback source: a Project Gutenberg work chunked into N pseudo-essays.

    PG URLs are stable (unlike many Wikisource subpages). For authors whose
    individual essays are not on Wikisource, we grab a whole work, strip
    PG's boilerplate, and chunk it into roughly equal pieces. Each chunk
    becomes one essay attributed to the author.
    """
    author_id: str
    author_name: str
    work_title: str
    pg_id: int                  # the integer in https://www.gutenberg.org/cache/epub/{id}/pg{id}.txt
    n_chunks: int               # how many pseudo-essays to split into
    n_baseline: int             # how many of those are baseline; remainder are scored
    native_english: bool = True

# Each author: 3 baseline + 2 held-out.
ESSAYS: List[EssayRef] = [
    # ── G.K. Chesterton ──
    EssayRef("chesterton", "G.K. Chesterton", "The Twelve Men",
             "https://en.wikisource.org/wiki/The_Twelve_Men", True),
    EssayRef("chesterton", "G.K. Chesterton", "On Running After One's Hat",
             "https://en.wikisource.org/wiki/Tremendous_Trifles/On_Running_After_One%27s_Hat", True),
    EssayRef("chesterton", "G.K. Chesterton", "A Piece of Chalk",
             "https://en.wikisource.org/wiki/Tremendous_Trifles/A_Piece_of_Chalk", True),
    EssayRef("chesterton", "G.K. Chesterton", "The Dragon's Grandmother",
             "https://en.wikisource.org/wiki/Tremendous_Trifles/The_Dragon%27s_Grandmother", False),
    EssayRef("chesterton", "G.K. Chesterton", "The Tower",
             "https://en.wikisource.org/wiki/Tremendous_Trifles/The_Tower", False),

    # ── John Henry Newman ──
    EssayRef("newman", "John Henry Newman", "A Form of Infidelity of the Day",
             "https://en.wikisource.org/wiki/The_Idea_of_a_University_Defined_and_Illustrated/Discourse_8", True),
    EssayRef("newman", "John Henry Newman", "Knowledge and Religious Duty",
             "https://en.wikisource.org/wiki/The_Idea_of_a_University_Defined_and_Illustrated/Discourse_4", True),
    EssayRef("newman", "John Henry Newman", "Knowledge Its Own End",
             "https://en.wikisource.org/wiki/The_Idea_of_a_University_Defined_and_Illustrated/Discourse_5", True),
    EssayRef("newman", "John Henry Newman", "Knowledge Viewed in Relation to Professional Skill",
             "https://en.wikisource.org/wiki/The_Idea_of_a_University_Defined_and_Illustrated/Discourse_7", False),
    EssayRef("newman", "John Henry Newman", "Knowledge Viewed in Relation to Learning",
             "https://en.wikisource.org/wiki/The_Idea_of_a_University_Defined_and_Illustrated/Discourse_6", False),

    # ── William James (psychology / religion essays in the public domain) ──
    EssayRef("james", "William James", "Habit",
             "https://en.wikisource.org/wiki/The_Principles_of_Psychology/Chapter_4", True),
    EssayRef("james", "William James", "Stream of Thought",
             "https://en.wikisource.org/wiki/The_Principles_of_Psychology/Chapter_9", True),
    EssayRef("james", "William James", "Will to Believe",
             "https://en.wikisource.org/wiki/The_Will_to_Believe_(essay)", True),
    EssayRef("james", "William James", "What Pragmatism Means",
             "https://en.wikisource.org/wiki/Pragmatism:_A_New_Name_for_Some_Old_Ways_of_Thinking/Lecture_II", False),
    EssayRef("james", "William James", "Philosophy and Its Critics",
             "https://en.wikisource.org/wiki/Some_Problems_of_Philosophy/Chapter_1", False),

    # ── Ralph Waldo Emerson ──
    EssayRef("emerson", "Ralph Waldo Emerson", "Self-Reliance",
             "https://en.wikisource.org/wiki/Essays:_First_Series/Self-Reliance", True),
    EssayRef("emerson", "Ralph Waldo Emerson", "History",
             "https://en.wikisource.org/wiki/Essays:_First_Series/History", True),
    EssayRef("emerson", "Ralph Waldo Emerson", "Compensation",
             "https://en.wikisource.org/wiki/Essays:_First_Series/Compensation", True),
    EssayRef("emerson", "Ralph Waldo Emerson", "The Over-Soul",
             "https://en.wikisource.org/wiki/Essays:_First_Series/The_Over-Soul", False),
    EssayRef("emerson", "Ralph Waldo Emerson", "Spiritual Laws",
             "https://en.wikisource.org/wiki/Essays:_First_Series/Spiritual_Laws", False),

    # ── Friedrich Schleiermacher (in English translation; per ADR-005 the
    # translation status is recorded as a manifest field for the bias slicer)
    EssayRef("schleiermacher", "Friedrich Schleiermacher", "On Religion Speech I",
             "https://en.wikisource.org/wiki/On_Religion:_Speeches_to_Its_Cultured_Despisers/First_Speech", True),
    EssayRef("schleiermacher", "Friedrich Schleiermacher", "On Religion Speech II",
             "https://en.wikisource.org/wiki/On_Religion:_Speeches_to_Its_Cultured_Despisers/Second_Speech", True),
    EssayRef("schleiermacher", "Friedrich Schleiermacher", "On Religion Speech III",
             "https://en.wikisource.org/wiki/On_Religion:_Speeches_to_Its_Cultured_Despisers/Third_Speech", True),
    EssayRef("schleiermacher", "Friedrich Schleiermacher", "On Religion Speech IV",
             "https://en.wikisource.org/wiki/On_Religion:_Speeches_to_Its_Cultured_Despisers/Fourth_Speech", False),
    EssayRef("schleiermacher", "Friedrich Schleiermacher", "On Religion Speech V",
             "https://en.wikisource.org/wiki/On_Religion:_Speeches_to_Its_Cultured_Despisers/Fifth_Speech", False),

    # ── Sojourner Truth — short speeches; we use Frederick Douglass who has
    # longer essays in the public record. ──
    EssayRef("douglass", "Frederick Douglass", "What to the Slave is the Fourth of July",
             "https://en.wikisource.org/wiki/What_to_the_Slave_is_the_Fourth_of_July%3F", True),
    EssayRef("douglass", "Frederick Douglass", "The Hypocrisy of American Slavery",
             "https://en.wikisource.org/wiki/The_Hypocrisy_of_American_Slavery", True),
    EssayRef("douglass", "Frederick Douglass", "The Constitution of the United States: Is It Pro-Slavery or Anti-Slavery?",
             "https://en.wikisource.org/wiki/The_Constitution_of_the_United_States:_Is_It_Pro-Slavery_or_Anti-Slavery%3F", True),
    EssayRef("douglass", "Frederick Douglass", "Self-Made Men",
             "https://en.wikisource.org/wiki/Self-Made_Men", False),
    EssayRef("douglass", "Frederick Douglass", "An Address to the Colored People of the United States",
             "https://en.wikisource.org/wiki/An_Address_to_the_Colored_People_of_the_United_States", False),

    # ── Henry David Thoreau ──
    EssayRef("thoreau", "Henry David Thoreau", "Civil Disobedience",
             "https://en.wikisource.org/wiki/Resistance_to_Civil_Government_(Thoreau)", True),
    EssayRef("thoreau", "Henry David Thoreau", "Walking",
             "https://en.wikisource.org/wiki/Walking_(Thoreau)", True),
    EssayRef("thoreau", "Henry David Thoreau", "Life Without Principle",
             "https://en.wikisource.org/wiki/Life_Without_Principle", True),
    EssayRef("thoreau", "Henry David Thoreau", "Slavery in Massachusetts",
             "https://en.wikisource.org/wiki/Slavery_in_Massachusetts", False),
    EssayRef("thoreau", "Henry David Thoreau", "A Plea for Captain John Brown",
             "https://en.wikisource.org/wiki/A_Plea_for_Captain_John_Brown", False),

    # ── John Stuart Mill ──
    EssayRef("mill", "John Stuart Mill", "On Liberty Ch.1",
             "https://en.wikisource.org/wiki/On_Liberty/Chapter_I", True),
    EssayRef("mill", "John Stuart Mill", "On Liberty Ch.2",
             "https://en.wikisource.org/wiki/On_Liberty/Chapter_II", True),
    EssayRef("mill", "John Stuart Mill", "On Liberty Ch.3",
             "https://en.wikisource.org/wiki/On_Liberty/Chapter_III", True),
    EssayRef("mill", "John Stuart Mill", "On Liberty Ch.4",
             "https://en.wikisource.org/wiki/On_Liberty/Chapter_IV", False),
    EssayRef("mill", "John Stuart Mill", "On Liberty Ch.5",
             "https://en.wikisource.org/wiki/On_Liberty/Chapter_V", False),
]


# ── Project Gutenberg fallback (stable URLs, chunk-into-essays) ─────────────
#
# Each work yields N essay-sized chunks. We strip PG's boilerplate and
# split on chapter/section breaks where possible, else by word count.

GUTENBERG_WORKS: List[GutenbergWork] = [
    # Mill, On Liberty — 5 chapters, perfect for chunking
    GutenbergWork("mill", "John Stuart Mill", "On Liberty", pg_id=34901,
                  n_chunks=5, n_baseline=3),
    # Chesterton, Orthodoxy — split into ~5 chunks by word count
    GutenbergWork("chesterton", "G.K. Chesterton", "Orthodoxy", pg_id=130,
                  n_chunks=5, n_baseline=3),
    # Newman, The Idea of a University (Discourses I-V is the public-domain set)
    GutenbergWork("newman", "John Henry Newman", "The Idea of a University", pg_id=24526,
                  n_chunks=5, n_baseline=3),
]


def _fetch_gutenberg(pg_id: int) -> str:
    """Fetch + strip a Project Gutenberg ETXT. Returns plain body prose."""
    url = f"https://www.gutenberg.org/cache/epub/{pg_id}/pg{pg_id}.txt"
    text = _fetch(url)
    # Strip the PG header (everything before *** START OF THIS PROJECT GUTENBERG…)
    m = re.search(r"\*\*\*\s*START OF (?:THIS|THE) PROJECT GUTENBERG[^\n]*\n",
                  text, re.IGNORECASE)
    if m:
        text = text[m.end():]
    # Strip the PG footer.
    m = re.search(r"\*\*\*\s*END OF (?:THIS|THE) PROJECT GUTENBERG", text, re.IGNORECASE)
    if m:
        text = text[:m.start()]
    # Strip "Produced by …" credit blocks at the very top.
    text = re.sub(r"^Produced by[^\n]*\n", "", text, flags=re.MULTILINE)
    return text.strip()


def _chunk_text(text: str, n_chunks: int) -> List[str]:
    """Split text into ~equal chunks at paragraph boundaries.

    First try to split on chapter headers (CHAPTER I, II, … or Discourse N).
    Fall back to splitting by paragraph count.
    """
    # Try chapter-based split first.
    chapter_re = re.compile(
        r"\n\s*(CHAPTER\s+[IVXLCDM]+|Chapter\s+\d+|Discourse\s+[IVXLCDM]+|DISCOURSE\s+[IVXLCDM]+)\b",
        re.IGNORECASE,
    )
    parts = chapter_re.split(text)
    # parts[0] is the prologue; parts[1::2] are chapter headers; parts[2::2] are bodies.
    if len(parts) > 2:
        chunks = []
        for i in range(1, len(parts), 2):
            head = parts[i].strip()
            body = parts[i + 1].strip() if i + 1 < len(parts) else ""
            chunks.append(f"{head}\n\n{body}")
        if len(chunks) >= n_chunks:
            return chunks[:n_chunks]

    # Fall back to paragraph-bucket split.
    paragraphs = [p for p in re.split(r"\n\s*\n", text) if p.strip()]
    if not paragraphs:
        return [text] * n_chunks
    per = max(1, len(paragraphs) // n_chunks)
    chunks: List[str] = []
    for i in range(n_chunks):
        lo = i * per
        hi = (i + 1) * per if i < n_chunks - 1 else len(paragraphs)
        chunks.append("\n\n".join(paragraphs[lo:hi]))
    return chunks


def _build_from_gutenberg(work: GutenbergWork, force: bool, entries: List[dict],
                         authors: Dict[str, dict], skipped: List[str]) -> None:
    """Pull one PG work, chunk it, write each chunk to corpus/<author_id>/."""
    author_dir = _CORPUS_DIR / work.author_id
    author_dir.mkdir(exist_ok=True)
    body_path = author_dir / "_full_work_cache.txt"

    if body_path.exists() and not force:
        body = body_path.read_text(encoding="utf-8")
        print(f"  cached: {work.author_id}/_full_work_cache.txt "
              f"({len(body.split())} words)", flush=True)
    else:
        try:
            body = _fetch_gutenberg(work.pg_id)
        except Exception as e:
            print(f"  FAILED (gutenberg pg{work.pg_id}): {e}", flush=True)
            skipped.append(f"gutenberg/pg{work.pg_id}")
            return
        body_path.write_text(body, encoding="utf-8")
        print(f"  fetched gutenberg pg{work.pg_id} ({len(body.split())} words)",
              flush=True)
        time.sleep(FETCH_SLEEP_SEC)

    chunks = _chunk_text(body, work.n_chunks)
    for i, chunk in enumerate(chunks, 1):
        slug = f"{_slugify(work.work_title)}_part_{i:02d}"
        relpath = f"{work.author_id}/{slug}.txt"
        path = author_dir / f"{slug}.txt"
        path.write_text(chunk, encoding="utf-8")
        is_baseline = (i <= work.n_baseline)
        entries.append({
            "filename": relpath,
            "author_id": work.author_id,
            "label": "authentic",
            "prompt": f"{work.work_title} (part {i} of {work.n_chunks})",
            "word_count": len(chunk.split()),
            "is_baseline": is_baseline,
            "ai_provider": "none",
            "theological_tradition": None,
            "native_english": work.native_english,
            "notes": f"Source: Project Gutenberg pg{work.pg_id} — {work.work_title}, chunk {i}/{work.n_chunks}",
        })
        authors.setdefault(work.author_id,
                           {"name": work.author_name, "native_english": work.native_english})
    print(f"  chunked into {len(chunks)} essays "
          f"({work.n_baseline} baseline + {work.n_chunks - work.n_baseline} scored)",
          flush=True)


# ── Wikisource HTML scraping ─────────────────────────────────────────────────
#
# Wikisource pages have a stable structure: the main content lives in a
# <div class="mw-parser-output">. We strip noise (footers, navigation,
# editor notes) and join paragraph text.

_NAV_NOISE = re.compile(
    r"(Retrieved from|Categories:|Hidden categories:|This page was last|"
    r"Privacy policy|About Wikisource|Disclaimers|Wikimedia)",
    re.IGNORECASE,
)


def _strip_html(html: str) -> str:
    """Strip Wikisource HTML to plain prose."""
    # Drop scripts and styles entirely.
    html = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r"<style[^>]*>.*?</style>", "", html, flags=re.DOTALL | re.IGNORECASE)
    # Extract the main parser output if present.
    m = re.search(r'<div class="mw-parser-output"[^>]*>(.*?)</div>\s*(?:<!--|<noscript)',
                  html, flags=re.DOTALL | re.IGNORECASE)
    body = m.group(1) if m else html
    # Drop hatnotes, references, navigation lists.
    body = re.sub(r'<div class="(hatnote|reflist|noprint|references|catlinks)[^"]*"[^>]*>.*?</div>',
                  '', body, flags=re.DOTALL | re.IGNORECASE)
    # Drop section navigators (prev/next).
    body = re.sub(r'<table[^>]*>.*?</table>', '', body, flags=re.DOTALL | re.IGNORECASE)
    # Drop footnotes ([1], [2], ...).
    body = re.sub(r'<sup[^>]*class="reference"[^>]*>.*?</sup>', '', body,
                  flags=re.DOTALL | re.IGNORECASE)
    body = re.sub(r'\[\d+\]', '', body)
    # Tag → newline at block boundaries, then strip.
    body = re.sub(r'</?(p|div|h[1-6]|blockquote|li)[^>]*>', '\n', body, flags=re.IGNORECASE)
    body = re.sub(r'<[^>]+>', '', body)
    # Decode common HTML entities.
    body = (body
            .replace("&nbsp;", " ").replace("&amp;", "&")
            .replace("&lt;", "<").replace("&gt;", ">")
            .replace("&quot;", '"').replace("&#39;", "'")
            .replace("&mdash;", "—").replace("&ndash;", "–"))
    # Drop nav noise lines.
    body = "\n".join(
        line for line in (l.strip() for l in body.splitlines())
        if line and not _NAV_NOISE.search(line)
    )
    # Collapse runs of blank lines.
    return re.sub(r"\n{3,}", "\n\n", body).strip()


def _slugify(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")


def _fetch(url: str) -> str:
    headers = {"User-Agent": UA}
    with httpx.Client(headers=headers, timeout=30.0, follow_redirects=True) as c:
        r = c.get(url)
        r.raise_for_status()
        return r.text


def build(only: Optional[str] = None, force: bool = False) -> dict:
    """Fetch every essay in ESSAYS, write to corpus/, regenerate manifest.json."""
    _CORPUS_DIR.mkdir(parents=True, exist_ok=True)
    entries: List[dict] = []
    authors: Dict[str, dict] = {}
    skipped: List[str] = []
    for ref in ESSAYS:
        if only and ref.author_id != only:
            continue
        slug = _slugify(ref.title)
        author_dir = _CORPUS_DIR / ref.author_id
        author_dir.mkdir(exist_ok=True)
        path = author_dir / f"{slug}.txt"
        relpath = f"{ref.author_id}/{slug}.txt"
        if path.exists() and not force:
            text = path.read_text(encoding="utf-8")
            print(f"  cached: {ref.author_id}/{slug}.txt ({len(text.split())} words)", flush=True)
        else:
            try:
                html = _fetch(ref.url)
            except Exception as e:
                print(f"  FAILED ({ref.author_id}/{slug}.txt): {e}", flush=True)
                skipped.append(relpath)
                continue
            text = _strip_html(html)
            if len(text.split()) < 300:
                print(f"  SKIP (too short after strip): {ref.author_id}/{slug}.txt — {len(text.split())} words",
                      flush=True)
                skipped.append(relpath)
                continue
            path.write_text(text, encoding="utf-8")
            print(f"  fetched: {ref.author_id}/{slug}.txt ({len(text.split())} words)", flush=True)
            time.sleep(FETCH_SLEEP_SEC)
        authors.setdefault(ref.author_id, {"name": ref.author_name, "native_english": ref.author_id != "schleiermacher"})
        entries.append({
            "filename": relpath,
            "author_id": ref.author_id,
            "label": "authentic",
            "prompt": ref.title,
            "word_count": len(text.split()),
            "is_baseline": ref.is_baseline,
            "ai_provider": "none",
            "theological_tradition": None,
            "native_english": ref.author_id != "schleiermacher",
            "notes": f"Source: {ref.url}",
        })

    # ── Fall back to Project Gutenberg for authors whose Wikisource pages 404 ──
    needed_authors = {w.author_id for w in GUTENBERG_WORKS}
    for work in GUTENBERG_WORKS:
        if only and work.author_id != only:
            continue
        # Skip if we already got enough essays from Wikisource for this author.
        wiki_baselines = sum(
            1 for e in entries
            if e["author_id"] == work.author_id and e["is_baseline"]
        )
        wiki_scored = sum(
            1 for e in entries
            if e["author_id"] == work.author_id and not e["is_baseline"]
        )
        if wiki_baselines >= 3 and wiki_scored >= 1:
            continue
        # Otherwise grab the PG fallback.
        print(f"\nGutenberg fallback for {work.author_id} ({work.work_title}):", flush=True)
        # Remove any partial Wikisource entries for this author (clean slate).
        entries[:] = [e for e in entries if e["author_id"] != work.author_id]
        _build_from_gutenberg(work, force, entries, authors, skipped)

    manifest = {
        "version": "1.0",
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "description": ("Public-author validation corpus for Original. "
                        "Each essay is uniquely attributed by the public record; "
                        "the manifest fixes a 3-baseline / N-scored split per author."),
        "authors": authors,
        "entries": entries,
    }
    _MANIFEST.write_text(json.dumps(manifest, indent=2))
    print(f"\nWrote manifest with {len(entries)} entries to {_MANIFEST}")
    if skipped:
        print(f"Skipped {len(skipped)}: {skipped}")
    return manifest


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--only", help="Only fetch one author_id (e.g. chesterton).")
    ap.add_argument("--force", action="store_true",
                    help="Re-fetch even if cached on disk.")
    a = ap.parse_args(argv)
    build(only=a.only, force=a.force)
    return 0


if __name__ == "__main__":
    sys.exit(main())
