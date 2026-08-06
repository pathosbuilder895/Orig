"""
validation/plato/build_corpus.py — build the Plato chronology corpus.

Fetches Benjamin Jowett's translations of the Platonic dialogues from Project
Gutenberg, strips the editorial apparatus, cuts the remaining dialogue text
into fixed-width chunks, and writes a manifest.

    python -m validation.plato.build_corpus                 # build
    python -m validation.plato.build_corpus --verify-strip  # check the strip only
    python -m validation.plato.build_corpus --only crito    # refresh one work
    python -m validation.plato.build_corpus --force         # ignore the cache

Why the apparatus strip is the load-bearing step
------------------------------------------------
Every Jowett Gutenberg file opens with Jowett's OWN introduction (and often an
analysis), which is Victorian academic English prose, not translated Plato.
Left in, the study would substantially measure Jowett's essay style. Worse, it
would do so *differentially*: the introduction is a far larger fraction of a
short early dialogue like the Crito than of the Laws, so the contamination
would correlate with the very ground truth we are testing against. The same
applies to the FOOTNOTES blocks in the Cary volume.

So the strip HARD-FAILS rather than falling back. A silent partial strip is
worse than no corpus at all, because it produces a plausible number.

Chunking
--------
Fixed 2000-word chunks. That sits inside the ``medium`` bucket of
``LENGTH_BUCKETS_BY_TOKENS`` (750-2500), so submission length cannot vary as a
confound, and it is well above the ~300-word reliability floor documented in
MODEL_CARD.md. Each work is capped at 12 chunks, sampled evenly across the
whole work, so that the Republic and the Laws (~200k words each) do not swamp
the Crito (~4k after stripping).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import httpx

from validation.plato import chronology
from validation.plato.chronology import CARY_DIALOGUES, CARY_PG_ID, GROUP_NAMES, Dialogue

_HERE = Path(__file__).resolve().parent
_CORPUS_DIR = _HERE / "corpus"
_MANIFEST = _HERE / "manifest.json"
_CACHE_DIR = _HERE / "corpus" / "_raw_cache"

UA = "OriginalAccuracyBenchmark/1.0 (mailto:arclark555@gmail.com)"
FETCH_SLEEP_SEC = 1.0

CHUNK_WORDS = 2000
MAX_CHUNKS_PER_WORK = 12
# Below this, a work contributes no chunk at all rather than a short one that
# would sit in a different length bucket from everything else.
MIN_CHUNK_WORDS = 1200


class StripError(RuntimeError):
    """The apparatus strip could not find its markers. Never recovered from."""


# ── Fetch ───────────────────────────────────────────────────────────────────


def _fetch(url: str) -> str:
    with httpx.Client(headers={"User-Agent": UA}, timeout=60.0, follow_redirects=True) as c:
        r = c.get(url)
        r.raise_for_status()
        return r.text


def _fetch_gutenberg(pg_id: int, force: bool = False) -> str:
    """Fetch a PG plain-text ebook, with an on-disk cache. Returns normalised text."""
    _CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cached = _CACHE_DIR / f"pg{pg_id}.txt"
    if cached.exists() and not force:
        return _normalise(cached.read_text(encoding="utf-8"))
    url = f"https://www.gutenberg.org/cache/epub/{pg_id}/pg{pg_id}.txt"
    text = _fetch(url)
    cached.write_text(text, encoding="utf-8")
    time.sleep(FETCH_SLEEP_SEC)
    return _normalise(text)


_LEADING_WS = re.compile(r"^[ \t]+", re.M)


def _normalise(text: str) -> str:
    """CRLF -> LF, and strip per-line leading whitespace.

    Both are Gutenberg transcription artefacts, and the second one is
    destructive: some volunteers indent the entire body by six spaces (the
    Timaeus is transcribed this way). Measured effect of that indentation on a
    2000-word chunk — 76 of 103 features change, with no error and no warning:

        pos_bigram_entropy    0.000 -> 0.652   (Republic: 0.651)
        char_trigram_entropy  0.000 -> 0.619   (Republic: 0.628)
        block_quote_rate      1.000 -> 0.000   (indent reads as a block quote)
        type_token_ratio      1.000 -> 0.000
        mean_sentence_length  0.000 -> 0.670

    Left uncorrected it made the Timaeus look like a dramatic late-period
    outlier (mean |z| 4.58 against 1.23 for the next dialogue) purely because
    of six leading spaces. Blank lines are untouched, so paragraph structure
    survives.
    """
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return _LEADING_WS.sub("", text)


def _strip_pg_boilerplate(text: str) -> str:
    m = re.search(r"\*\*\*\s*START OF (?:THIS|THE) PROJECT GUTENBERG[^\n]*\n", text, re.I)
    if m:
        text = text[m.end() :]
    m = re.search(r"\*\*\*\s*END OF (?:THIS|THE) PROJECT GUTENBERG", text, re.I)
    if m:
        text = text[: m.start()]
    text = re.sub(r"^\s*(Produced by|This etext was prepared by)[^\n]*\n", "", text, flags=re.M)
    return text.strip()


# ── Apparatus strip ─────────────────────────────────────────────────────────

# Standalone headings that begin Jowett's own editorial matter.
_APPARATUS_HEAD = re.compile(
    r"^[ \t]*(INTRODUCTION(?:\s+AND\s+ANALYSIS)?|ANALYSIS|PREFACE|APPENDIX(?:\s+[IVXLC]+)?)\.?[ \t]*$",
    re.M,
)
_CONTENTS_HEAD = re.compile(r"^[ \t]*Contents\.?[ \t]*$", re.M | re.I)

# Jowett always writes a substantial introduction; across the corpus the strip
# removes 10-53% of a file. A strip that removes almost nothing means the
# markers matched the wrong place — which is exactly what a table-of-contents
# entry causes, since it repeats every real heading verbatim. Guarding on the
# cut fraction is what turns that silent partial strip into a hard failure.
MIN_CUT_FRACTION = 0.05


def _skip_contents_block(text: str) -> int:
    """Return an offset past the table of contents, or 0 if there is none.

    A contents block repeats every section heading of the file, so searching
    for headings without skipping it finds the contents entry rather than the
    real heading — leaving Jowett's introduction in the corpus.

    The block is the run of short lines after the ``Contents`` heading; it ends
    at the first gap of two or more consecutive blank lines.
    """
    m = _CONTENTS_HEAD.search(text)
    if not m:
        return 0
    pos = m.end()
    blanks = 0
    seen_entry = False
    for line in text[pos:].splitlines(keepends=True):
        stripped = line.strip()
        if not stripped:
            blanks += 1
            if blanks >= 2 and seen_entry:
                return pos
        else:
            # A long line is prose, not a contents entry — the block is over.
            if len(stripped) > 70:
                return pos
            blanks = 0
            seen_entry = True
        pos += len(line)
    return pos
# The dramatis personae list — where a dialogue proper begins, when present.
_PERSONS = re.compile(r"^[ \t]*PERSONS OF THE DIALOGUE.*$", re.M)
# Trailing editorial matter to cut off the end of a body.
_TRAILING_APPARATUS = re.compile(r"^[ \t]*(FOOTNOTES?|APPENDIX(?:\s+[IVXLC]+)?)\.?[ \t]*$", re.M)


def _title_heading_re(title: str) -> re.Pattern:
    """A standalone-line heading matching a work's own title.

    Jowett repeats the title as a section heading where the dialogue proper
    starts (e.g. ``THE REPUBLIC.`` at the head of the body). Tolerates leading
    whitespace and a trailing period.
    """
    return re.compile(rf"^[ \t]*{re.escape(title.upper())}\.?[ \t]*$", re.M)


def extract_jowett_body(text: str, title: str, slug: str) -> Tuple[str, dict]:
    """Return (dialogue text, diagnostics), having removed Jowett's apparatus.

    The rule: find where the editorial apparatus begins, then take the FIRST
    occurrence after it of either the dramatis personae list or a repeat of the
    work's title as a standalone heading. That handles all three shapes present
    in the corpus:

      * Crito     — no title repeat; PERSONS OF THE DIALOGUE marks the body.
      * Apology   — a monologue, so no PERSONS list; the APOLOGY heading marks it.
      * Republic  — PERSONS appears twice (contents + body); the one after the
                    apparatus heading is the real one.

    Raises StripError if no marker is found. See the module docstring for why
    this must never fall back.
    """
    body_src = _strip_pg_boilerplate(text)

    # Skip the table of contents first: it repeats every heading in the file,
    # so searching without skipping it matches the contents entry near the top
    # and silently leaves Jowett's whole introduction in the "body".
    contents_end = _skip_contents_block(body_src)

    app = _APPARATUS_HEAD.search(body_src, contents_end)
    if not app:
        raise StripError(f"{slug}: no apparatus heading (INTRODUCTION/ANALYSIS/APPENDIX) found")
    apparatus_at = app.start()

    candidates: List[Tuple[int, str]] = []
    m = _PERSONS.search(body_src, apparatus_at)
    if m:
        candidates.append((m.start(), "PERSONS OF THE DIALOGUE"))
    tm = _title_heading_re(title).search(body_src, apparatus_at)
    if tm:
        candidates.append((tm.start(), f"title heading {title.upper()!r}"))

    if not candidates:
        raise StripError(
            f"{slug}: apparatus heading found at offset {apparatus_at}, but no body "
            f"marker after it (looked for PERSONS OF THE DIALOGUE and a "
            f"{title.upper()!r} heading)"
        )

    start, marker = min(candidates)
    body = body_src[start:]

    # Cut trailing editorial matter (footnotes, appendices) if any.
    trail = _TRAILING_APPARATUS.search(body)
    trailing_cut = 0
    if trail:
        trailing_cut = len(body[trail.start() :].split())
        body = body[: trail.start()]

    body = body.strip()
    before = len(body_src.split())
    after = len(body.split())
    diagnostics = {
        "marker": marker,
        "words_before_strip": before,
        "words_after_strip": after,
        "trailing_words_cut": trailing_cut,
        "cut_fraction": round(1.0 - after / before, 4) if before else 0.0,
    }
    if after < MIN_CHUNK_WORDS:
        raise StripError(
            f"{slug}: only {after} words survived the strip (marker: {marker}) — "
            f"below the {MIN_CHUNK_WORDS}-word floor. The marker probably matched "
            f"the wrong place."
        )
    if diagnostics["cut_fraction"] < MIN_CUT_FRACTION:
        raise StripError(
            f"{slug}: the strip removed only {diagnostics['cut_fraction']:.1%} of the file "
            f"({before:,} -> {after:,} words, marker: {marker}). Jowett's introduction is "
            f"never that small, so the marker matched the wrong place and his own prose "
            f"is still in the corpus."
        )
    return body, diagnostics


# The Cary volume (PG 13726) packs three dialogues into one file, each preceded
# by its own editorial introduction and followed by a FOOTNOTES block. Segment
# boundaries are the dramatis-personae / title headings verified by inspection.
_CARY_SEGMENTS: Dict[str, str] = {
    "apology": r"^[ \t]*THE APOLOGY OF SOCRATES\.[ \t]*$",
    "crito": r"^[ \t]*SOCRATES, CRITO\.[ \t]*$",
    "phaedo": r"^[ \t]*THEN SOCRATES, APOLLODORUS, CEBES, SIMMIAS, AND CRITO\.[ \t]*$",
}


def extract_cary_bodies(text: str) -> Dict[str, Tuple[str, dict]]:
    """Split the Cary volume into its three dialogues, stripping apparatus.

    Each body runs from its heading to the next FOOTNOTES block. Raises
    StripError if any of the three cannot be located.
    """
    src = _strip_pg_boilerplate(text)
    out: Dict[str, Tuple[str, dict]] = {}
    for slug, pattern in _CARY_SEGMENTS.items():
        matches = list(re.finditer(pattern, src, re.M))
        if not matches:
            raise StripError(f"cary/{slug}: segment heading not found (pattern {pattern!r})")
        # Take the LAST match: the first is the table-of-contents entry.
        start = matches[-1].start()
        rest = src[start:]
        trail = _TRAILING_APPARATUS.search(rest)
        trailing_cut = 0
        if trail:
            trailing_cut = len(rest[trail.start() :].split())
            rest = rest[: trail.start()]
        body = rest.strip()
        if len(body.split()) < MIN_CHUNK_WORDS:
            raise StripError(
                f"cary/{slug}: only {len(body.split())} words survived the strip — "
                f"below the {MIN_CHUNK_WORDS}-word floor."
            )
        out[slug] = (
            body,
            {
                "marker": f"cary segment {slug}",
                "words_before_strip": len(src.split()),
                "words_after_strip": len(body.split()),
                "trailing_words_cut": trailing_cut,
            },
        )
    return out


# ── Measurement helpers ─────────────────────────────────────────────────────

# Jowett renders dialogue turns as "SOCRATES:  Why have you come...".
_SPEAKER_LABEL = re.compile(r"^[ \t]*[A-Z][A-Z .'’-]{1,28}:", re.M)


def direct_speech_ratio(text: str) -> float:
    """Speaker labels per 1000 words.

    The genre covariate. The late dialogues (Laws, Timaeus, Critias) are close
    to continuous exposition while the early ones are rapid question-and-answer,
    and that difference correlates with chronology — so a raw correlation
    between style and date could be measuring dramatic form rather than career
    stage. Reported per chunk and partialled out of the headline metric.
    """
    words = len(text.split())
    if words == 0:
        return 0.0
    return round(1000.0 * len(_SPEAKER_LABEL.findall(text)) / words, 3)


def chunk_words(text: str, size: int = CHUNK_WORDS, cap: int = MAX_CHUNKS_PER_WORK) -> List[str]:
    """Cut into fixed-width word chunks, then sample evenly down to `cap`.

    Slices the ORIGINAL string between word boundaries rather than rejoining
    ``text.split()``. Rejoining would flatten every chunk onto a single line,
    which destroys paragraph structure — and the feature pipeline reads that
    structure: Tier 2's paragraph features split on blank lines, and speaker
    labels ("SOCRATES:") are detected at line starts. Flattening makes all 13
    Tier 2 features constant across the corpus, so the active-feature mask
    silently drops them.

    Even sampling (rather than taking the first `cap`) matters too: a work must
    contribute material from its beginning, middle and end, or the corpus would
    represent only the opening of the Republic.
    """
    spans = [m.span() for m in re.finditer(r"\S+", text)]
    if not spans:
        return []
    chunks: List[str] = []
    for i in range(0, len(spans), size):
        group = spans[i : i + size]
        if len(group) < MIN_CHUNK_WORDS:
            continue  # drop a short tail so every chunk shares a length bucket
        chunks.append(text[group[0][0] : group[-1][1]])
    if len(chunks) <= cap:
        return chunks
    n = len(chunks)
    idx = sorted({round(i * (n - 1) / (cap - 1)) for i in range(cap)})
    return [chunks[i] for i in idx]


# ── Build ───────────────────────────────────────────────────────────────────


@dataclass
class WorkResult:
    slug: str
    translator: str
    diagnostics: dict
    n_chunks: int
    error: Optional[str] = None


def _load_body(d: Dialogue, force: bool) -> Tuple[str, dict]:
    raw = _fetch_gutenberg(d.pg_id, force=force)
    return extract_jowett_body(raw, d.title, d.slug)


def build(
    only: Optional[str] = None, force: bool = False, verify_only: bool = False
) -> Tuple[List[WorkResult], dict]:
    """Fetch, strip, chunk and write the corpus. Returns (results, manifest)."""
    results: List[WorkResult] = []
    entries: List[dict] = []

    targets = [d for d in chronology.DIALOGUES if not only or d.slug == only]

    print(f"\n{'work':<16} {'before':>9} {'after':>9} {'cut%':>6} {'chunks':>7}  marker")
    print("─" * 88)

    for d in targets:
        try:
            body, diag = _load_body(d, force)
        except StripError as e:
            results.append(WorkResult(d.slug, "jowett", {}, 0, error=str(e)))
            print(f"{d.slug:<16} {'':>9} {'':>9} {'':>6} {'':>7}  ✗ STRIP FAILED")
            continue
        except Exception as e:  # network / HTTP
            results.append(WorkResult(d.slug, "jowett", {}, 0, error=f"fetch: {e}"))
            print(f"{d.slug:<16} {'':>9} {'':>9} {'':>6} {'':>7}  ✗ FETCH FAILED: {e}")
            continue

        chunks = chunk_words(body)
        before, after = diag["words_before_strip"], diag["words_after_strip"]
        cut_pct = 100.0 * (before - after) / before if before else 0.0
        print(
            f"{d.slug:<16} {before:>9,} {after:>9,} {cut_pct:>5.1f}% {len(chunks):>7}  {diag['marker']}"
        )
        results.append(WorkResult(d.slug, "jowett", diag, len(chunks)))

        if not verify_only:
            _write_chunks(entries, d, "jowett", chunks)

    # ── Cary control volume ──
    if not only or only in CARY_DIALOGUES:
        try:
            raw = _fetch_gutenberg(CARY_PG_ID, force=force)
            cary = extract_cary_bodies(raw)
            for slug, (body, diag) in cary.items():
                if only and slug != only:
                    continue
                chunks = chunk_words(body)
                print(
                    f"{'cary/' + slug:<16} {diag['words_before_strip']:>9,} "
                    f"{diag['words_after_strip']:>9,} {'':>6} {len(chunks):>7}  {diag['marker']}"
                )
                results.append(WorkResult(slug, "cary", diag, len(chunks)))
                if not verify_only:
                    _write_chunks(entries, chronology.by_slug(slug), "cary", chunks)
        except StripError as e:
            results.append(WorkResult("cary", "cary", {}, 0, error=str(e)))
            print(f"{'cary':<16} ✗ STRIP FAILED: {e}")
        except Exception as e:
            results.append(WorkResult("cary", "cary", {}, 0, error=f"fetch: {e}"))
            print(f"{'cary':<16} ✗ FETCH FAILED: {e}")

    manifest = {
        "version": "1.0",
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "description": (
            "Plato chronology corpus. Jowett translations from Project Gutenberg, "
            "editorial apparatus stripped, cut into fixed 2000-word chunks. "
            "Includes Henry Cary translations of three overlapping dialogues as a "
            "translator control, and the spurious Eryxias as a negative control."
        ),
        "chunk_words": CHUNK_WORDS,
        "max_chunks_per_work": MAX_CHUNKS_PER_WORK,
        "entries": entries,
    }
    if not verify_only:
        _MANIFEST.write_text(json.dumps(manifest, indent=2))
        print(f"\nWrote {len(entries)} entries to {_MANIFEST}")
    return results, manifest


def _write_chunks(entries: List[dict], d: Dialogue, translator: str, chunks: List[str]) -> None:
    out_dir = _CORPUS_DIR / translator / d.slug
    out_dir.mkdir(parents=True, exist_ok=True)
    for i, chunk in enumerate(chunks, 1):
        name = f"{d.slug}_{i:02d}.txt"
        (out_dir / name).write_text(chunk, encoding="utf-8")
        entries.append(
            {
                "filename": f"{translator}/{d.slug}/{name}",
                "slug": d.slug,
                "title": d.title,
                "translator": translator,
                "chronology_group": GROUP_NAMES.get(d.group) if d.group else None,
                "chron_rank": d.group,
                "high_confidence": d.high_confidence,
                "spurious": d.spurious,
                "note": d.note,
                "word_count": len(chunk.split()),
                "direct_speech_ratio": direct_speech_ratio(chunk),
                "pg_id": CARY_PG_ID if translator == "cary" else d.pg_id,
            }
        )


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--only", help="Only build one dialogue slug (e.g. crito).")
    ap.add_argument("--force", action="store_true", help="Re-fetch even if cached.")
    ap.add_argument(
        "--verify-strip",
        action="store_true",
        help="Report the apparatus strip without writing any corpus files.",
    )
    a = ap.parse_args(argv)

    results, _ = build(only=a.only, force=a.force, verify_only=a.verify_strip)

    failures = [r for r in results if r.error]
    print()
    print(chronology.summary())
    print()
    print(f"works processed: {len(results)}   strip/fetch failures: {len(failures)}")
    for r in failures:
        print(f"  ✗ {r.slug} ({r.translator}): {r.error}")
    if failures:
        print("\nFAILED — the corpus is not usable until every work strips cleanly.")
        return 1
    total_chunks = sum(r.n_chunks for r in results)
    print(f"total chunks: {total_chunks}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
