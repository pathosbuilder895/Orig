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

── Contamination guards (added 2026-08-01) ─────────────────────────────
The first build of this corpus shipped with five distinct contamination
modes, found by manual inspection:
  1. Wrong author via redirect — Wikisource redirects "Self-Made Men"
     to Stephen Leacock's "Literary Lapses/Self-Made Men", not the
     Frederick Douglass speech (which is not on Wikisource at all).
  2. Wrong work via bad Gutenberg id — pg24962 is a FRENCH sci-fi novel
     (Le Faure & Graffigny), not Edwards' "Religious Affections".
  3. Site chrome — the old mw-parser-output regex failed on current
     Wikisource HTML and silently fell back to the whole page, so files
     began with "Jump to content / Main menu / Create account …".
  4. Back-matter — the Varieties of Religious Experience chunks 6-8
     were the book's INDEX + FOOTNOTES sections, not James' prose.
  5. TOC stubs — the chapter-split regex matched "CHAPTER I" lines in
     tables of contents, producing 6-41-word "essays" (mill, kempis).
Every fetch is therefore now verified: author identity (Wikisource
Author: link / Gutenberg header), English-language stopword ratio,
chrome markers, index/footnote-line ratios, and per-file minimum word
counts. A file that fails ANY check is not written and the failure is
reported; the manifest only ever lists verified files.
"""

from __future__ import annotations

import argparse
import html as html_lib
import json
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.parse import unquote

import httpx

_HERE = Path(__file__).resolve().parent
_CORPUS_DIR = _HERE / "corpus"
_MANIFEST = _HERE / "manifest.json"

UA = "OriginalAccuracyBenchmark/1.0 (mailto:arclark555@gmail.com)"
FETCH_SLEEP_SEC = 1.0  # be polite
_WS_API = "https://en.wikisource.org/w/api.php"

# Verification thresholds. English prose runs a top-50-stopword ratio of
# roughly 0.35-0.45; French text scores ≈ 0.01 on the same list, so 0.22
# is a wide margin in both directions.
MIN_ESSAY_WORDS = 500  # one Wikisource essay
MIN_CHUNK_WORDS = 800  # one Gutenberg pseudo-essay chunk
MIN_ENGLISH_STOPWORD_RATIO = 0.22
MAX_INDEX_LINE_RATIO = 0.30  # "EMERSON, 32, 56." style lines
MAX_FOOTNOTE_LINE_RATIO = 0.20  # "  147 Above, p. 201. …" style lines

_ENGLISH_STOPWORDS = frozenset(
    "the of and to in a is that it he was for on are as with his they at be "
    "this have from or one had by but not what all were we when your can "
    "there an which their if will who has her she them than then these".split()
)

# Any of these in a corpus file means Wikisource site chrome leaked in.
_CHROME_MARKERS = (
    "Jump to content",
    "Main menu",
    "Create account",
    "Personal tools",
    "View history",
    "Wikisource, the free online library",
    "Download EPUB",
    "Random transcription",
    "sister projects",
)


# ── Curated essay list ───────────────────────────────────────────────────────
#
# Each essay is identified by its Wikisource canonical URL. The slug we use
# as the local filename is a stable identifier — changing it would invalidate
# the manifest.
#
# Only authors whose corpus is actually Wikisource-sourced are listed here.
# Authors sourced from Project Gutenberg (mill, chesterton, newman, james,
# kempis, augustine, boethius, edwards) live in GUTENBERG_WORKS below — the
# Wikisource pages originally tried for them are either gone or were never
# used in the built corpus. Friedrich Schleiermacher was dropped entirely:
# "On Religion: Speeches to Its Cultured Despisers" is on neither Wikisource
# nor Project Gutenberg, so the source is not reproducibly resolvable.


@dataclass(frozen=True)
class EssayRef:
    author_id: str  # canonical short-id used in filenames
    author_name: str  # display name
    title: str
    url: str
    is_baseline: bool  # True → baseline; False → held-out for scoring


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
    pg_id: int  # the integer in https://www.gutenberg.org/cache/epub/{id}/pg{id}.txt
    n_chunks: int  # how many pseudo-essays to split into
    n_baseline: int  # how many of those are baseline; remainder are scored
    native_english: bool = True
    # Optional MULTILINE regex locating where the AUTHOR's text begins.
    # Everything before the first match is editor/translator front matter
    # (biographical introduction, translator's preface, TOC) written by
    # someone else — it must not be scored under this author's name.
    start_after: Optional[str] = None


ESSAYS: List[EssayRef] = [
    # ── Ralph Waldo Emerson ──
    EssayRef(
        "emerson",
        "Ralph Waldo Emerson",
        "Self-Reliance",
        "https://en.wikisource.org/wiki/Essays:_First_Series/Self-Reliance",
        True,
    ),
    EssayRef(
        "emerson",
        "Ralph Waldo Emerson",
        "History",
        "https://en.wikisource.org/wiki/Essays:_First_Series/History",
        True,
    ),
    EssayRef(
        "emerson",
        "Ralph Waldo Emerson",
        "Compensation",
        "https://en.wikisource.org/wiki/Essays:_First_Series/Compensation",
        True,
    ),
    EssayRef(
        "emerson",
        "Ralph Waldo Emerson",
        "The Over-Soul",
        "https://en.wikisource.org/wiki/Essays:_First_Series/The_Over-Soul",
        False,
    ),
    EssayRef(
        "emerson",
        "Ralph Waldo Emerson",
        "Spiritual Laws",
        "https://en.wikisource.org/wiki/Essays:_First_Series/Spiritual_Laws",
        False,
    ),
    # ── Frederick Douglass ──
    # Only one of Douglass' long speeches is on Wikisource; "Self-Made Men"
    # is NOT (the bare title redirects to a Stephen Leacock humor piece —
    # contamination mode 1 above). The rest of the douglass corpus is
    # topped up from Project Gutenberg (My Bondage and My Freedom).
    EssayRef(
        "douglass",
        "Frederick Douglass",
        "What to the Slave Is the Fourth of July",
        "https://en.wikisource.org/wiki/What_to_the_Slave_Is_the_Fourth_of_July%3F",
        True,
    ),
    # ── Henry David Thoreau ──
    EssayRef(
        "thoreau",
        "Henry David Thoreau",
        "Civil Disobedience",
        "https://en.wikisource.org/wiki/Aesthetic_Papers/Resistance_to_Civil_Government",
        True,
    ),
    EssayRef(
        "thoreau",
        "Henry David Thoreau",
        "Walking",
        "https://en.wikisource.org/wiki/Excursions_(1863)_Thoreau/Walking",
        True,
    ),
    EssayRef(
        "thoreau",
        "Henry David Thoreau",
        "Life Without Principle",
        "https://en.wikisource.org/wiki/Life_Without_Principle",
        True,
    ),
    EssayRef(
        "thoreau",
        "Henry David Thoreau",
        "Slavery in Massachusetts",
        "https://en.wikisource.org/wiki/Slavery_in_Massachusetts",
        False,
    ),
    EssayRef(
        "thoreau",
        "Henry David Thoreau",
        "A Plea for Captain John Brown",
        "https://en.wikisource.org/wiki/A_Plea_for_Captain_John_Brown",
        False,
    ),
]


# ── Project Gutenberg works (stable URLs, chunk-into-essays) ─────────────────
#
# Each work yields N essay-sized chunks. We strip PG's boilerplate and
# split on chapter/section breaks where possible, else by word count.

GUTENBERG_WORKS: List[GutenbergWork] = [
    # Mill, On Liberty — 5 chapters, perfect for chunking
    GutenbergWork("mill", "John Stuart Mill", "On Liberty", pg_id=34901, n_chunks=5, n_baseline=3),
    # Chesterton, Orthodoxy — split into ~5 chunks by word count
    GutenbergWork(
        "chesterton", "G.K. Chesterton", "Orthodoxy", pg_id=130, n_chunks=5, n_baseline=3
    ),
    # Newman, The Idea of a University (Discourses I-V is the public-domain set)
    GutenbergWork(
        "newman",
        "John Henry Newman",
        "The Idea of a University",
        pg_id=24526,
        n_chunks=5,
        n_baseline=3,
    ),
    # Douglass — tops up the single Wikisource speech above to a full author.
    GutenbergWork(
        "douglass",
        "Frederick Douglass",
        "My Bondage and My Freedom",
        pg_id=202,
        n_chunks=5,
        n_baseline=3,
    ),
    # ── Added for the length-stability study (≥50k words each, formation register) ──
    # William James — Varieties of Religious Experience (~150k words of prose;
    # the trailing INDEX + FOOTNOTES sections are truncated before chunking)
    GutenbergWork(
        "james",
        "William James",
        "The Varieties of Religious Experience",
        pg_id=621,
        n_chunks=8,
        n_baseline=4,
    ),
    # Thomas à Kempis — Imitation of Christ (~63k words; Benham translation).
    # start_after skips the title page, TOC and Benham's introductory note.
    GutenbergWork(
        "kempis",
        "Thomas à Kempis",
        "The Imitation of Christ",
        pg_id=1653,
        n_chunks=5,
        n_baseline=3,
        start_after=r"^THE FIRST BOOK\s*$",
    ),
    # Augustine — Confessions (~110k words; Pusey translation)
    GutenbergWork(
        "augustine", "Augustine of Hippo", "Confessions", pg_id=3296, n_chunks=6, n_baseline=3
    ),
    # Boethius — Consolation of Philosophy (~43k words; H.R. James translation).
    # start_after skips the translator's preface + TOC; James' interspersed
    # per-book SUMMARY blocks remain (as in every edition of this translation).
    GutenbergWork(
        "boethius",
        "Boethius",
        "The Consolation of Philosophy",
        pg_id=14328,
        n_chunks=5,
        n_baseline=3,
        start_after=r"^\s*SUMMARY\.\s*$",
    ),
    # Jonathan Edwards — Selected Sermons (pg34632). "A Treatise Concerning
    # Religious Affections" is not on Project Gutenberg; the id previously
    # used here (24962) is a French science-fiction novel (contamination
    # mode 2 above).
    # start_after skips Gardiner's biographical introduction; the editor's
    # trailing NOTES section is cut by the back-matter truncation.
    GutenbergWork(
        "edwards",
        "Jonathan Edwards",
        "Selected Sermons of Jonathan Edwards",
        pg_id=34632,
        n_chunks=6,
        n_baseline=3,
        start_after=r"^GOD GLORIFIED IN MAN'S DEPENDENCE",
    ),
]


# ── Content verification ─────────────────────────────────────────────────────


def _english_stopword_ratio(text: str) -> float:
    words = re.findall(r"[a-zA-Z']+", text.lower())
    if not words:
        return 0.0
    return sum(1 for w in words if w in _ENGLISH_STOPWORDS) / len(words)


def _index_line_ratio(text: str) -> float:
    """Fraction of non-blank lines shaped like index entries ('EMERSON, 32.')."""
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    if not lines:
        return 0.0
    hits = sum(1 for l in lines if len(l) < 80 and re.search(r",\s*\d{1,4}[.,]?\s*$", l))
    return hits / len(lines)


def _footnote_line_ratio(text: str) -> float:
    """Fraction of non-blank lines opening a numbered footnote block."""
    lines = [l for l in text.splitlines() if l.strip()]
    if not lines:
        return 0.0
    hits = sum(1 for l in lines if re.match(r"\s{2,}\d{1,3}\s+\S", l))
    return hits / len(lines)


def _validate_prose(text: str, min_words: int, label: str) -> List[str]:
    """Return a list of human-readable problems; empty list = verified clean."""
    problems: List[str] = []
    wc = len(text.split())
    if wc < min_words:
        problems.append(f"only {wc} words (need ≥{min_words})")
    ratio = _english_stopword_ratio(text)
    if ratio < MIN_ENGLISH_STOPWORD_RATIO:
        problems.append(f"English stopword ratio {ratio:.2f} — not English prose?")
    chrome = [m for m in _CHROME_MARKERS if m in text]
    if chrome:
        problems.append(f"site chrome leaked in ({chrome[:2]})")
    idx = _index_line_ratio(text)
    if idx > MAX_INDEX_LINE_RATIO:
        problems.append(f"{idx:.0%} of lines look like index entries")
    fnr = _footnote_line_ratio(text)
    if fnr > MAX_FOOTNOTE_LINE_RATIO:
        problems.append(f"{fnr:.0%} of lines look like footnote blocks")
    return [f"{label}: {p}" for p in problems]


def _title_tokens(title: str) -> List[str]:
    return [t for t in re.findall(r"[a-z]+", title.lower()) if len(t) >= 4]


def _author_tokens(author_name: str) -> List[str]:
    return [t for t in re.findall(r"[a-z]+", author_name.lower()) if len(t) >= 4]


# ── Back-matter and chunking ────────────────────────────────────────────────


_BACK_MATTER_RE = re.compile(r"^\s*(INDEX|FOOTNOTES|GLOSSARY|APPENDIX|NOTES)\.?\s*$", re.MULTILINE)


def _truncate_back_matter(text: str) -> str:
    """Cut the text at an INDEX/FOOTNOTES/… heading in its final 40%.

    Books like The Varieties of Religious Experience end with a hundred
    pages of index + collected footnotes; chunked blindly, those became
    "essays" (contamination mode 4). Only the tail is searched so that a
    chapter that merely discusses an index is never truncated on.
    """
    tail_start = int(len(text) * 0.6)
    m = _BACK_MATTER_RE.search(text, tail_start)
    if m:
        return text[: m.start()].rstrip()
    return text


def _chunk_text(text: str, n_chunks: int) -> List[str]:
    """Split text into ~equal chunks at chapter or paragraph boundaries.

    First try to split on chapter headers (CHAPTER I, II, … or Discourse N),
    keeping only substantial chapters — a "CHAPTER I" line inside a table of
    contents captures a stub of a few words (contamination mode 5), so tiny
    bodies are discarded rather than emitted. Falls back to a paragraph
    split balanced by word count.
    """
    text = _truncate_back_matter(text)

    chapter_re = re.compile(
        r"\n\s*(CHAPTER\s+[IVXLCDM]+|Chapter\s+\d+|Discourse\s+[IVXLCDM]+|DISCOURSE\s+[IVXLCDM]+)\b",
        re.IGNORECASE,
    )
    parts = chapter_re.split(text)
    # parts[0] is the prologue (title page, TOC, editor's introduction) and is
    # deliberately dropped — it is not the author's prose. parts[1::2] are
    # chapter headers; parts[2::2] are bodies.
    if len(parts) > 2:
        headers = [parts[i].strip() for i in range(1, len(parts), 2)]
        bodies = [parts[i + 1].strip() if i + 1 < len(parts) else "" for i in range(1, len(parts), 2)]
        # The real text begins at the LAST header numbered I/1 — earlier
        # occurrences are table-of-contents entries. Without this, the final
        # TOC line's "body" is the whole front matter (title page, editor's
        # preface, an introduction by a DIFFERENT author…) masquerading as
        # the author's first chapter.
        start = 0
        for i, head in enumerate(headers):
            m = re.search(r"\b(I|1)\s*$", head.strip())
            if m:
                start = i
        headers, bodies = headers[start:], bodies[start:]
        chapters: List[str] = []
        n_headers = len(headers)
        for head, body in zip(headers, bodies):
            # A TOC entry captures at most a line or two before the next
            # "CHAPTER …" match; a real chapter body is hundreds of words.
            if len(body.split()) >= MIN_CHUNK_WORDS:
                chapters.append(f"{head}\n\n{body}")
        # Only take the chapter route when chapters are natural essay-sized
        # units: enough of them, and most headers carrying a substantial
        # body. A work of many tiny chapters (e.g. The Imitation of Christ,
        # ~500 words each) would otherwise yield an arbitrary scatter of
        # only its longest chapters — the paragraph split covers it evenly.
        if len(chapters) >= n_chunks and len(chapters) >= 0.5 * n_headers:
            return chapters[:n_chunks]

    # Fall back to a paragraph split balanced by word count (bucketing by
    # paragraph COUNT skews badly when paragraph lengths vary, e.g. one-line
    # index entries vs 300-word prose paragraphs).
    paragraphs = [p for p in re.split(r"\n\s*\n", text) if p.strip()]
    if not paragraphs:
        return [text] * n_chunks
    # If a Contents heading sits in the front matter, drop the title page +
    # TOC listing: skip ahead to the first real prose paragraph after it
    # (substantial AND sentence-shaped — a TOC listing is many short lines).
    for ci, p in enumerate(paragraphs):
        if ci > len(paragraphs) * 0.15:
            break
        if re.match(r"^\s*(Contents|CONTENTS)\s*$", p):
            for pi in range(ci + 1, len(paragraphs)):
                cand = paragraphs[pi]
                lines = [l for l in cand.splitlines() if l.strip()]
                mean_len = sum(len(l) for l in lines) / max(1, len(lines))
                if len(cand.split()) >= 80 and mean_len >= 45:
                    paragraphs = paragraphs[pi:]
                    break
            break
    total_words = sum(len(p.split()) for p in paragraphs)
    chunks: List[str] = []
    i = 0
    for k in range(n_chunks):
        remaining_chunks = n_chunks - k
        take_max = len(paragraphs) - i - (remaining_chunks - 1)
        target = sum(len(p.split()) for p in paragraphs[i:]) / remaining_chunks
        acc_words = 0
        take = 0
        while take < take_max:
            acc_words += len(paragraphs[i + take].split())
            take += 1
            if acc_words >= target:
                break
        take = max(1, take)
        chunks.append("\n\n".join(paragraphs[i : i + take]))
        i += take
    return chunks


# ── Project Gutenberg fetching ───────────────────────────────────────────────


def _fetch_gutenberg(pg_id: int, expected_title: str, expected_author: str) -> str:
    """Fetch + verify + strip a Project Gutenberg ETXT. Returns plain body prose.

    Raises ValueError when the fetched text does not look like the expected
    work by the expected author — a wrong pg_id must fail loudly, not ship
    a different book under this author's name (contamination mode 2).
    """
    url = f"https://www.gutenberg.org/cache/epub/{pg_id}/pg{pg_id}.txt"
    text = _fetch(url)

    # Verify BEFORE stripping: the PG header + title page must mention the
    # author and (most of) the title we asked for.
    lowered = text.lower()
    author_hits = [t for t in _author_tokens(expected_author) if t in lowered]
    if not author_hits:
        raise ValueError(f"pg{pg_id} never mentions expected author {expected_author!r}")
    title_tokens = _title_tokens(expected_title)
    title_hits = [t for t in title_tokens if t in lowered]
    if title_tokens and len(title_hits) / len(title_tokens) < 0.6:
        raise ValueError(
            f"pg{pg_id} does not look like {expected_title!r} "
            f"(matched title words: {title_hits or 'none'})"
        )

    # Strip the PG header (everything before *** START OF THIS PROJECT GUTENBERG…)
    m = re.search(r"\*\*\*\s*START OF (?:THIS|THE) PROJECT GUTENBERG[^\n]*\n", text, re.IGNORECASE)
    if m:
        text = text[m.end() :]
    # Strip the PG footer — both the modern "*** END OF …" marker and the
    # old-style bare "End of Project Gutenberg's …" line.
    m = re.search(
        r"(\*\*\*\s*END OF (?:THIS|THE) PROJECT GUTENBERG"
        r"|^End of (?:the |this )?Project Gutenberg)",
        text,
        re.IGNORECASE | re.MULTILINE,
    )
    if m:
        text = text[: m.start()]
    # Strip "Produced by …" / proofreader credit blocks at the very top.
    text = re.sub(
        r"^(Produced by|This etext was proofread|E-text prepared by|Transcribed from)[^\n]*\n",
        "",
        text,
        flags=re.MULTILINE,
    )
    text = re.sub(
        r"^[^\n]*(pgdp\.net|Distributed Proofread|produced from scanned images|"
        r"Google Print|Internet Archive)[^\n]*\n",
        "",
        text,
        flags=re.MULTILINE | re.IGNORECASE,
    )
    text = text.strip()

    ratio = _english_stopword_ratio(text)
    if ratio < MIN_ENGLISH_STOPWORD_RATIO:
        raise ValueError(f"pg{pg_id} body is not English prose (stopword ratio {ratio:.2f})")
    return text


def _build_from_gutenberg(
    work: GutenbergWork,
    force: bool,
    entries: List[dict],
    authors: Dict[str, dict],
    skipped: List[str],
    n_baseline: Optional[int] = None,
) -> None:
    """Pull one PG work, chunk it, write each chunk to corpus/<author_id>/.

    ``n_baseline`` overrides ``work.n_baseline`` — used when the author
    already has verified Wikisource baselines and the PG work only tops up.
    """
    if n_baseline is None:
        n_baseline = work.n_baseline
    author_dir = _CORPUS_DIR / work.author_id
    author_dir.mkdir(exist_ok=True)
    body_path = author_dir / "_full_work_cache.txt"

    body: Optional[str] = None
    if body_path.exists() and not force:
        cached = body_path.read_text(encoding="utf-8")
        lowered = cached.lower()
        cache_ok = (
            _english_stopword_ratio(cached) >= MIN_ENGLISH_STOPWORD_RATIO
            and any(t in lowered for t in _author_tokens(work.author_name))
        )
        if cache_ok:
            body = cached
            print(
                f"  cached: {work.author_id}/_full_work_cache.txt ({len(cached.split())} words)",
                flush=True,
            )
        else:
            print(
                f"  cached {work.author_id}/_full_work_cache.txt fails verification — refetching",
                flush=True,
            )
    if body is None:
        try:
            body = _fetch_gutenberg(work.pg_id, work.work_title, work.author_name)
        except Exception as e:
            print(f"  FAILED (gutenberg pg{work.pg_id}): {e}", flush=True)
            skipped.append(f"gutenberg/pg{work.pg_id}")
            return
        # The cache is read directly by validation/stability — it must hold
        # the verified corpus, not the raw fetch with its INDEX/FOOTNOTES tail.
        body = _truncate_back_matter(body)
        body_path.write_text(body + "\n", encoding="utf-8")
        print(f"  fetched gutenberg pg{work.pg_id} ({len(body.split())} words)", flush=True)
        time.sleep(FETCH_SLEEP_SEC)

    if work.start_after:
        m = re.search(work.start_after, body, re.MULTILINE)
        if not m:
            print(
                f"  REJECTED (gutenberg pg{work.pg_id}): start_after marker "
                f"{work.start_after!r} not found — cannot separate front matter",
                flush=True,
            )
            skipped.append(f"gutenberg/pg{work.pg_id}")
            return
        body = body[m.start() :]

    chunks = _chunk_text(body, work.n_chunks)
    # Verify every chunk BEFORE writing any of them: a single bad chunk
    # invalidates the work's baseline/scored split, so all-or-nothing.
    problems: List[str] = []
    for i, chunk in enumerate(chunks, 1):
        problems += _validate_prose(chunk, MIN_CHUNK_WORDS, f"chunk {i}/{len(chunks)}")
    if len(chunks) < work.n_chunks:
        problems.append(f"only {len(chunks)} chunks (need {work.n_chunks})")
    if problems:
        print(f"  REJECTED (gutenberg pg{work.pg_id} — {work.work_title}):", flush=True)
        for p in problems:
            print(f"    · {p}", flush=True)
        skipped.append(f"gutenberg/pg{work.pg_id}")
        return

    for i, chunk in enumerate(chunks, 1):
        slug = f"{_slugify(work.work_title)}_part_{i:02d}"
        relpath = f"{work.author_id}/{slug}.txt"
        path = author_dir / f"{slug}.txt"
        path.write_text(chunk, encoding="utf-8")
        is_baseline = i <= n_baseline
        entries.append(
            {
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
            }
        )
        authors.setdefault(
            work.author_id, {"name": work.author_name, "native_english": work.native_english}
        )
    print(
        f"  chunked into {len(chunks)} essays "
        f"({n_baseline} baseline + {work.n_chunks - n_baseline} scored)",
        flush=True,
    )


# ── Wikisource fetching ──────────────────────────────────────────────────────
#
# Pages are fetched through the MediaWiki parse API, which returns ONLY the
# rendered page content — no site navigation, no "Jump to content" chrome
# (contamination mode 3 came from scraping the full desktop HTML). The
# rendered header template carries the attribution we verify against.

_NAV_NOISE = re.compile(
    r"(Retrieved from|Categories:|Hidden categories:|This page was last|"
    r"Privacy policy|About Wikisource|Disclaimers|Wikimedia)",
    re.IGNORECASE,
)

_AUTHOR_LINK_RE = re.compile(r'href="/wiki/Author:([^"#?]+)"')


def _fetch_wikisource(url: str) -> Tuple[str, str]:
    """Fetch a Wikisource page's rendered content HTML via the parse API.

    Returns (resolved_page_title, content_html). Raises on HTTP or API
    errors. Redirects are followed — the caller MUST verify authorship,
    because a redirect can land on a same-titled work by someone else
    entirely (contamination mode 1).
    """
    page = unquote(url.rsplit("/wiki/", 1)[1]).replace("_", " ")
    headers = {"User-Agent": UA}
    with httpx.Client(headers=headers, timeout=30.0, follow_redirects=True) as c:
        r = c.get(
            _WS_API,
            params={
                "action": "parse",
                "page": page,
                "prop": "text",
                "redirects": 1,
                "format": "json",
                "formatversion": 2,
            },
        )
        r.raise_for_status()
        data = r.json()
    if "error" in data:
        raise ValueError(f"Wikisource API error for {page!r}: {data['error'].get('info')}")
    parse = data["parse"]
    return parse["title"], parse["text"]


def _verify_wikisource_author(content_html: str, ref: EssayRef, resolved_title: str) -> None:
    """Raise ValueError unless the page is attributed to the expected author.

    Wikisource works carry a header template linking to the author's
    Author: page; that link is the machine-checkable attribution. The page
    title CANNOT be trusted for this — the Leacock page that poisoned the
    first build was titled "…/Self-Made Men" too.
    """
    linked = [unquote(a).replace("_", " ") for a in _AUTHOR_LINK_RE.findall(content_html)]
    expected = _author_tokens(ref.author_name)
    if not linked:
        raise ValueError(
            f"{resolved_title!r} has no Author: attribution link — cannot verify authorship"
        )
    for author in linked:
        lowered = author.lower()
        if any(tok in lowered for tok in expected):
            return
    raise ValueError(
        f"{resolved_title!r} is attributed to {sorted(set(linked))}, "
        f"not {ref.author_name!r} — wrong work (redirect?)"
    )


_NOEXPORT_DIV_RE = re.compile(
    r'<div[^>]*class="[^"]*(?:ws-noexport|noprint|hatnote|dablink|similar|ws-header|wst-header'
    r"|licenseContainer|licenseBanner)"
    r'[^"]*"[^>]*>',
    re.IGNORECASE,
)
_DIV_TOKEN_RE = re.compile(r"</?div\b", re.IGNORECASE)


def _drop_noexport_divs(body: str) -> str:
    """Remove header/hatnote/navigation divs, honouring nested <div> tags.

    The Wikisource header template is a deeply nested div marked
    ``ws-noexport noprint`` — a non-greedy ``.*?</div>`` would cut it off
    mid-header and leave the navigation text in the prose.
    """
    while True:
        m = _NOEXPORT_DIV_RE.search(body)
        if not m:
            return body
        depth = 1
        pos = m.end()
        while depth > 0:
            tok = _DIV_TOKEN_RE.search(body, pos)
            if tok is None:  # unbalanced markup — drop to end of fragment
                pos = len(body)
                break
            depth += 1 if tok.group().lower() == "<div" else -1
            pos = tok.end()
        body = body[: m.start()] + body[pos:]


# Residual navigation/portal lines that can survive HTML stripping on pages
# whose templates render outside the ws-noexport wrappers.
_HEADER_LINE_NOISE = re.compile(
    r"^(←|→|[<>\s​]+$|For works with similar titles|For other versions of this work|"
    r"related portals?:|sister projects?:|Information about this edition|"
    r"Versions of this work|Public domain|This work (is|was) (in the public domain|published))",
    re.IGNORECASE,
)
_LICENSE_LINE_NOISE = re.compile(
    r"(the author died (at least|more than) \d+ years ago|Public domainPublic domain)",
    re.IGNORECASE,
)

# A "Notes"/"Footnotes" heading in an essay's final stretch starts editorial
# end-matter, not the author's prose.
_ESSAY_NOTES_RE = re.compile(r"^\s*(Notes|NOTES|Footnotes|FOOTNOTES)\s*$", re.MULTILINE)


def _strip_content_html(content_html: str) -> str:
    """Reduce Wikisource content HTML to plain prose."""
    body = content_html
    body = re.sub(r"<script[^>]*>.*?</script>", "", body, flags=re.DOTALL | re.IGNORECASE)
    body = re.sub(r"<style[^>]*>.*?</style>", "", body, flags=re.DOTALL | re.IGNORECASE)
    body = _drop_noexport_divs(body)
    # Older pages render the header/footer templates (attribution, prev/next
    # navigation, sister project links) as tables; the prose never does.
    body = re.sub(r"<table[^>]*>.*?</table>", "", body, flags=re.DOTALL | re.IGNORECASE)
    # Footnote markers and reference lists.
    body = re.sub(
        r'<sup[^>]*class="[^"]*reference[^"]*"[^>]*>.*?</sup>',
        "",
        body,
        flags=re.DOTALL | re.IGNORECASE,
    )
    body = re.sub(
        r'<ol[^>]*class="[^"]*references[^"]*"[^>]*>.*?</ol>',
        "",
        body,
        flags=re.DOTALL | re.IGNORECASE,
    )
    body = re.sub(r"\[\d+\]", "", body)
    # Tag → newline at block boundaries, then strip all remaining tags.
    body = re.sub(r"</?(p|div|h[1-6]|blockquote|li|br)[^>]*>", "\n", body, flags=re.IGNORECASE)
    body = re.sub(r"<[^>]+>", "", body)
    body = html_lib.unescape(body)
    body = body.replace("​", "")  # zero-width spaces from pagination templates
    body = re.sub(r"\[\s*edit\s*\]", "", body)
    # Drop residual boilerplate lines.
    body = "\n".join(
        line
        for line in (l.strip() for l in body.splitlines())
        if line
        and not _NAV_NOISE.search(line)
        and not _HEADER_LINE_NOISE.match(line)
        and not _LICENSE_LINE_NOISE.search(line)
    )
    # Cut editorial "Notes"/"Footnotes" end-matter in the essay's final 15%.
    m = _ESSAY_NOTES_RE.search(body, int(len(body) * 0.85))
    if m:
        body = body[: m.start()]
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
        text: Optional[str] = None
        if path.exists() and not force:
            cached = path.read_text(encoding="utf-8")
            if not _validate_prose(cached, MIN_ESSAY_WORDS, relpath):
                text = cached
                print(
                    f"  cached: {ref.author_id}/{slug}.txt ({len(cached.split())} words)",
                    flush=True,
                )
            else:
                print(f"  cached {relpath} fails verification — refetching", flush=True)
        if text is None:
            try:
                resolved_title, content_html = _fetch_wikisource(ref.url)
                _verify_wikisource_author(content_html, ref, resolved_title)
            except Exception as e:
                print(f"  FAILED ({ref.author_id}/{slug}.txt): {e}", flush=True)
                skipped.append(relpath)
                continue
            text = _strip_content_html(content_html)
            problems = _validate_prose(text, MIN_ESSAY_WORDS, f"{ref.author_id}/{slug}.txt")
            if problems:
                for p in problems:
                    print(f"  REJECTED {p}", flush=True)
                skipped.append(relpath)
                continue
            path.write_text(text, encoding="utf-8")
            print(f"  fetched: {ref.author_id}/{slug}.txt ({len(text.split())} words)", flush=True)
            time.sleep(FETCH_SLEEP_SEC)
        authors.setdefault(ref.author_id, {"name": ref.author_name, "native_english": True})
        entries.append(
            {
                "filename": relpath,
                "author_id": ref.author_id,
                "label": "authentic",
                "prompt": ref.title,
                "word_count": len(text.split()),
                "is_baseline": ref.is_baseline,
                "ai_provider": "none",
                "theological_tradition": None,
                "native_english": True,
                "notes": f"Source: {ref.url}",
            }
        )

    # ── Top up from Project Gutenberg where Wikisource left an author short ──
    for work in GUTENBERG_WORKS:
        if only and work.author_id != only:
            continue
        wiki_baselines = sum(
            1 for e in entries if e["author_id"] == work.author_id and e["is_baseline"]
        )
        wiki_scored = sum(
            1 for e in entries if e["author_id"] == work.author_id and not e["is_baseline"]
        )
        # Skip if we already got enough verified essays from Wikisource.
        if wiki_baselines >= 3 and wiki_scored >= 1:
            continue
        print(f"\nGutenberg source for {work.author_id} ({work.work_title}):", flush=True)
        # Verified Wikisource entries are KEPT — the PG chunks only fill the
        # remaining baseline slots. (The old clean-slate behaviour threw away
        # good essays alongside the bad.)
        n_baseline = max(0, work.n_baseline - wiki_baselines)
        _build_from_gutenberg(work, force, entries, authors, skipped, n_baseline=n_baseline)

    # ── Final sweep: report stale files the manifest no longer references ──
    manifest_files = {e["filename"] for e in entries}
    orphans: List[str] = []
    for path in sorted(_CORPUS_DIR.rglob("*.txt")):
        rel = str(path.relative_to(_CORPUS_DIR))
        if path.name == "_full_work_cache.txt":
            continue
        if only and not rel.startswith(f"{only}/"):
            continue
        if rel not in manifest_files:
            orphans.append(rel)
    if orphans:
        print(f"\n⚠ {len(orphans)} stale corpus files not in the manifest — remove with git rm:")
        for rel in orphans:
            print(f"    corpus/{rel}")

    manifest = {
        "version": "1.1",
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "description": (
            "Public-author validation corpus for Original. "
            "Each essay is uniquely attributed by the public record; "
            "the manifest fixes a 3-baseline / N-scored split per author. "
            "Every file passed post-fetch verification (author attribution, "
            "English-prose checks, no site chrome, no index/footnote back-matter)."
        ),
        "authors": authors,
        "entries": entries,
    }
    _MANIFEST.write_text(json.dumps(manifest, indent=2))
    print(f"\nWrote manifest with {len(entries)} entries to {_MANIFEST}")
    if skipped:
        print(f"Skipped {len(skipped)}: {skipped}")
    return manifest


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--only", help="Only fetch one author_id (e.g. chesterton).")
    ap.add_argument("--force", action="store_true", help="Re-fetch even if cached on disk.")
    a = ap.parse_args(argv)
    build(only=a.only, force=a.force)
    return 0


if __name__ == "__main__":
    sys.exit(main())
