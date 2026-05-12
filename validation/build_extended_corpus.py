"""
validation/build_extended_corpus.py — Extend the validation corpus with additional authors.

Fetches public-domain texts from Project Gutenberg for four authors whose prose
is roughly contemporary with (or interestingly contrasts with) the Federalist Papers:

  - Thomas Paine    (populist 18th-c. political pamphleteer)
  - Edmund Burke    (ornate British 18th-c. political philosophy)
  - Abraham Lincoln (direct 19th-c. American political oratory)
  - Frederick Douglass (19th-c. rhetorical/narrative prose)

Each text is split into 800–2 000-word chunks.  Chunks are saved to
validation/corpus/ and appended to the existing validation/manifest.json.

Cross-author ghostwritten entries are added so the calibration study can
produce a full pairwise similarity matrix.

Usage:
    python -m validation.build_extended_corpus
"""

from __future__ import annotations

import json
import re
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Tuple

ROOT       = Path(__file__).resolve().parent.parent
CORPUS_DIR = ROOT / "validation" / "corpus"
MANIFEST   = ROOT / "validation" / "manifest.json"

# ── Author definitions ────────────────────────────────────────────────────────

AUTHORS: List[Dict] = [
    {
        "id":   "paine",
        "name": "Thomas Paine",
        "urls": [
            # Common Sense (Project Gutenberg #147 plain text)
            "https://www.gutenberg.org/cache/epub/147/pg147.txt",
            # Rights of Man Part 1 (#3755)
            "https://www.gutenberg.org/cache/epub/3755/pg3755.txt",
            # Rights of Man Part 2 (#3756)
            "https://www.gutenberg.org/cache/epub/3756/pg3756.txt",
        ],
        "prefix": "paine",
        "prompt": "18th-century political argument",
        "n_baseline": 8,
    },
    {
        "id":   "burke",
        "name": "Edmund Burke",
        "urls": [
            # Reflections on the Revolution in France (#15679)
            "https://www.gutenberg.org/cache/epub/15679/pg15679.txt",
        ],
        "prefix": "burke",
        "prompt": "18th-century political philosophy",
        "n_baseline": 6,
    },
    {
        "id":   "lincoln",
        "name": "Abraham Lincoln",
        "urls": [
            # Lincoln's speeches and letters (#2658)
            "https://www.gutenberg.org/cache/epub/2658/pg2658.txt",
        ],
        "prefix": "lincoln",
        "prompt": "19th-century American political address",
        "n_baseline": 6,
    },
    {
        "id":   "douglass",
        "name": "Frederick Douglass",
        "urls": [
            # Narrative of the Life of Frederick Douglass (#23)
            "https://www.gutenberg.org/cache/epub/23/pg23.txt",
            # My Bondage and My Freedom (#99)
            "https://www.gutenberg.org/cache/epub/202/pg202.txt",
        ],
        "prefix": "douglass",
        "prompt": "19th-century autobiographical and oratorical prose",
        "n_baseline": 6,
    },
]

# Federalist Paper author IDs already in the manifest (for cross-author entries)
FEDERALIST_AUTHORS = ["hamilton", "madison", "jay"]

TARGET_CHUNK_MIN = 800
TARGET_CHUNK_MAX = 2000


# ── Helpers ───────────────────────────────────────────────────────────────────

def fetch(url: str, retries: int = 3) -> str:
    for attempt in range(retries):
        try:
            print(f"  Fetching {url} …")
            with urllib.request.urlopen(url, timeout=30) as r:
                return r.read().decode("utf-8-sig", errors="replace")
        except Exception as e:
            if attempt == retries - 1:
                raise
            print(f"  Retry {attempt+1}: {e}")
            time.sleep(2)
    return ""


def strip_gutenberg(text: str) -> str:
    """Remove Project Gutenberg header and footer boilerplate."""
    # Start marker variants
    for marker in [
        "*** START OF THE PROJECT GUTENBERG",
        "***START OF THE PROJECT GUTENBERG",
        "*END*THE SMALL PRINT",
    ]:
        idx = text.find(marker)
        if idx != -1:
            # Skip to end of that line
            text = text[text.index("\n", idx) + 1:]
            break

    # End marker variants
    for marker in [
        "*** END OF THE PROJECT GUTENBERG",
        "***END OF THE PROJECT GUTENBERG",
        "End of the Project Gutenberg",
        "End of Project Gutenberg",
    ]:
        idx = text.find(marker)
        if idx != -1:
            text = text[:idx]
            break

    return text.strip()


def split_into_chunks(text: str, min_words: int, max_words: int) -> List[str]:
    """
    Split text into chunks of min_words–max_words on paragraph boundaries.
    Returns list of chunk strings, each with reasonable prose content.
    """
    # Normalise line endings
    text = re.sub(r"\r\n", "\n", text)
    # Split on double newlines (paragraph breaks)
    paragraphs = [p.strip() for p in re.split(r"\n{2,}", text) if p.strip()]

    chunks: List[str] = []
    current: List[str] = []
    current_words = 0

    for para in paragraphs:
        words = len(para.split())
        if words < 10:          # skip very short lines (headers, page numbers)
            continue
        current.append(para)
        current_words += words

        if current_words >= min_words:
            chunk_text = "\n\n".join(current)
            if current_words <= max_words * 1.5:
                chunks.append(chunk_text)
                current = []
                current_words = 0
            elif current_words > max_words * 1.5:
                # Flush what we have and start fresh
                chunks.append(chunk_text)
                current = []
                current_words = 0

    if current and current_words >= min_words // 2:
        chunks.append("\n\n".join(current))

    return chunks


def load_manifest() -> dict:
    if MANIFEST.exists():
        return json.loads(MANIFEST.read_text(encoding="utf-8"))
    return {
        "version": "1.0",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "description": "Extended authorship validation corpus",
        "authors": {},
        "entries": [],
    }


def existing_prefixes(manifest: dict) -> set:
    """Return set of filename prefixes already in the manifest."""
    return {e["filename"].split("_")[0] for e in manifest["entries"]}


# ── Main ──────────────────────────────────────────────────────────────────────

def build_author(author: Dict, corpus_dir: Path) -> Tuple[List[str], List[dict]]:
    """
    Fetch texts, split into chunks, save files, return (filenames, manifest_entries).
    Returns only the author's own entries (baseline + authentic scoring).
    Cross-author entries are built separately.
    """
    all_chunks: List[str] = []

    for url in author["urls"]:
        raw = fetch(url)
        clean = strip_gutenberg(raw)
        chunks = split_into_chunks(clean, TARGET_CHUNK_MIN, TARGET_CHUNK_MAX)
        all_chunks.extend(chunks)
        print(f"    {len(chunks)} chunks from {url.split('/')[-1]}")

    if len(all_chunks) < author["n_baseline"] + 2:
        print(f"  WARNING: only {len(all_chunks)} chunks for {author['id']} — may be insufficient")

    # Save files
    prefix   = author["prefix"]
    n_base   = author["n_baseline"]
    filenames: List[str] = []
    for i, chunk in enumerate(all_chunks):
        fname = f"{prefix}_{i+1:03d}.txt"
        (corpus_dir / fname).write_text(chunk, encoding="utf-8")
        filenames.append(fname)

    # Build manifest entries (authentic only)
    entries: List[dict] = []
    for i, fname in enumerate(filenames):
        is_base = i < n_base
        entries.append({
            "filename":    fname,
            "author_id":   author["id"],
            "label":       "authentic",
            "prompt":      author["prompt"],
            "word_count":  len(all_chunks[i].split()),
            "is_baseline": is_base,
            "notes":       f"{author['name']} {'[BASELINE]' if is_base else '[SCORING]'}",
        })

    print(f"  {author['id']}: {len(filenames)} files ({n_base} baseline, {len(filenames)-n_base} scoring)")
    return filenames, entries


def build_cross_author_entries(
    new_author: Dict,
    new_filenames: List[str],
    all_authors: List[Dict],
    manifest: dict,
    corpus_dir: Path,
) -> List[dict]:
    """
    For each new author, add their scoring chunks (non-baseline) as
    'ghostwritten' entries under every OTHER author's author_id.
    Also add existing Federalist scoring chunks as 'ghostwritten' under new author.
    """
    cross: List[dict] = []
    n_base = new_author["n_baseline"]
    scoring_files = new_author["filenames"][n_base:]   # non-baseline chunks

    # New author's chunks scored against every other new author's baseline
    for other in all_authors:
        if other["id"] == new_author["id"]:
            continue
        for fname in scoring_files[:4]:   # limit to 4 cross-author entries per pair
            path = corpus_dir / fname
            if not path.exists():
                continue
            cross.append({
                "filename":    fname,
                "author_id":   other["id"],
                "label":       "ghostwritten",
                "prompt":      new_author["prompt"],
                "word_count":  len(path.read_text(encoding="utf-8").split()),
                "is_baseline": False,
                "notes":       f"{new_author['name']} chunk scored against {other['name']} baseline",
            })

    # Also score some Federalist chunks against this new author's baseline
    fed_scoring = [
        e for e in manifest.get("entries", [])
        if e["author_id"] in FEDERALIST_AUTHORS
        and not e["is_baseline"]
        and e["label"] == "authentic"
    ]
    # 3 per Federalist author
    import random
    random.seed(42)
    for fed_author in FEDERALIST_AUTHORS:
        fed_chunks = [e for e in fed_scoring if e["author_id"] == fed_author]
        for e in random.sample(fed_chunks, min(3, len(fed_chunks))):
            cross.append({
                "filename":    e["filename"],
                "author_id":   new_author["id"],
                "label":       "ghostwritten",
                "prompt":      e["prompt"],
                "word_count":  e["word_count"],
                "is_baseline": False,
                "notes":       f"Federalist ({fed_author}) scored against {new_author['name']} baseline",
            })

    return cross


def main():
    CORPUS_DIR.mkdir(parents=True, exist_ok=True)
    manifest = load_manifest()
    existing = existing_prefixes(manifest)

    print(f"Existing manifest: {len(manifest['entries'])} entries, prefixes: {existing}")

    built_authors: List[Dict] = []

    # Build each new author
    for author in AUTHORS:
        if author["prefix"] in existing:
            print(f"Skipping {author['id']} — already in manifest")
            # Still need their filenames for cross-author entries
            existing_files = sorted(CORPUS_DIR.glob(f"{author['prefix']}_*.txt"))
            author["filenames"] = [f.name for f in existing_files]
            built_authors.append(author)
            continue

        print(f"\nBuilding {author['name']} …")
        filenames, entries = build_author(author, CORPUS_DIR)
        author["filenames"] = filenames

        # Update authors dict in manifest
        manifest["authors"][author["id"]] = {
            "name":   author["name"],
            "chunks": len(filenames),
        }

        manifest["entries"].extend(entries)
        built_authors.append(author)

    # Build cross-author ghostwritten entries (for newly added authors only)
    print("\nBuilding cross-author entries …")
    for author in built_authors:
        if author["prefix"] in existing:
            continue    # already had cross entries built last run
        cross = build_cross_author_entries(author, author["filenames"], built_authors, manifest, CORPUS_DIR)
        manifest["entries"].extend(cross)
        print(f"  {author['id']}: +{len(cross)} cross-author entries")

    # Save manifest
    manifest["updated_at"] = datetime.now(timezone.utc).isoformat()
    MANIFEST.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    total = len(manifest["entries"])
    authors = len(set(e["author_id"] for e in manifest["entries"]))
    print(f"\nManifest saved: {total} entries, {authors} author_ids")
    print(f"Corpus dir: {CORPUS_DIR} ({len(list(CORPUS_DIR.glob('*.txt')))} files)")


if __name__ == "__main__":
    main()
