#!/usr/bin/env python3
"""
fetch_benchmark_data.py — Download and cache benchmark datasets for Original.

Fetches:
  1. arXiv full-text papers (HTML format) for 8 prolific authors
     — Long academic prose, multi-topic, known-author ground truth
     — Uses arxiv HTML endpoint for paragraph-rich text (not just abstract)
  2. PAN 2021 Authorship Verification dataset (Zenodo)
     — Pre-structured same/different-author pairs with ground truth
     — Cross-topic same-author pairs = the hard test for Original
  3. PAN 2022 Authorship Verification dataset (Zenodo)
     — Larger, includes cross-topic and cross-genre variants

All data cached to .benchmark_cache/ — subsequent runs skip downloads.

Usage
-----
  python scripts/fetch_benchmark_data.py              # fetch all
  python scripts/fetch_benchmark_data.py --arxiv      # arXiv only
  python scripts/fetch_benchmark_data.py --pan        # PAN only
  python scripts/fetch_benchmark_data.py --pan-year 2021
  python scripts/fetch_benchmark_data.py --force      # re-download even if cached

After running this, benchmark.py will automatically use the richer data.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import re
import sys
import time
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from typing import List, Optional
from html.parser import HTMLParser

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("fetch")

PROJECT_ROOT = Path(__file__).parent.parent
CACHE_DIR = PROJECT_ROOT / ".benchmark_cache"
ARXIV_DIR = CACHE_DIR / "arxiv"
PAN_DIR = CACHE_DIR / "pan"
RAID_DIR = CACHE_DIR / "raid"
M4_DIR = CACHE_DIR / "m4"


# ── Utilities ──────────────────────────────────────────────────────────────────

def _get(url: str, timeout: int = 30, retries: int = 3) -> bytes:
    """Fetch URL with retries and polite delay."""
    headers = {
        "User-Agent": "Original-Benchmark/1.0 (academic research; contact: original-benchmark)",
        "Accept": "text/html,application/xhtml+xml,application/xml,application/json,*/*",
    }
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except Exception as e:
            if attempt == retries - 1:
                raise
            wait = 2 ** attempt
            log.warning("  Attempt %d failed (%s), retrying in %ds...", attempt + 1, e, wait)
            time.sleep(wait)
    raise RuntimeError(f"Failed to fetch {url} after {retries} attempts")


class _TextExtractor(HTMLParser):
    """Minimal HTML→text extractor. Strips scripts, styles, nav, figure captions."""
    SKIP_TAGS = {"script", "style", "nav", "header", "footer", "figure", "figcaption",
                 "aside", "button", "select", "noscript", "svg", "math"}

    def __init__(self):
        super().__init__()
        self.chunks: list[str] = []
        self._skip_depth = 0
        self._current_tag = ""

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP_TAGS:
            self._skip_depth += 1
        self._current_tag = tag

    def handle_endtag(self, tag):
        if tag in self.SKIP_TAGS and self._skip_depth > 0:
            self._skip_depth -= 1
        if tag in {"p", "h1", "h2", "h3", "h4", "li", "td", "th", "div", "section"}:
            self.chunks.append("\n")

    def handle_data(self, data):
        if self._skip_depth == 0:
            text = data.strip()
            if text:
                self.chunks.append(text + " ")

    def get_text(self) -> str:
        raw = "".join(self.chunks)
        # Collapse whitespace
        raw = re.sub(r" {2,}", " ", raw)
        raw = re.sub(r"\n{3,}", "\n\n", raw)
        return raw.strip()


def html_to_text(html: bytes) -> str:
    parser = _TextExtractor()
    try:
        parser.feed(html.decode("utf-8", errors="replace"))
    except Exception:
        pass
    return parser.get_text()


# ── arXiv ──────────────────────────────────────────────────────────────────────

# Eight authors with distinct styles, many papers, across multiple arXiv topics.
# Selected for: (a) prolific enough to build a 5-paper baseline, (b) stylistically
# recognisable, (c) spanning multiple topic areas (the hard test for Original).
ARXIV_AUTHORS = [
    # id used for filenames          arXiv search query
    ("bengio_yoshua",               "Bengio, Yoshua"),
    ("lecun_yann",                  "LeCun, Yann"),
    ("manning_christopher",         "Manning, Christopher"),
    ("karpathy_andrej",             "Karpathy, Andrej"),
    ("abbeel_pieter",               "Abbeel, Pieter"),
    ("chollet_francois",            "Chollet, Francois"),
    ("ng_andrew",                   "Ng, Andrew"),
    ("goodfellow_ian",              "Goodfellow, Ian"),
]

# Maximum papers to fetch per author (baseline + test budget)
ARXIV_MAX_PER_AUTHOR = 12


def _fetch_arxiv_paper_ids(author_query: str, max_results: int = 15) -> list[tuple[str, str]]:
    """Return list of (paper_id, title) for an author via arXiv API."""
    query = urllib.parse.quote(f'au:"{author_query}"')
    url = (
        f"http://export.arxiv.org/api/query"
        f"?search_query={query}"
        f"&max_results={max_results}"
        f"&sortBy=submittedDate&sortOrder=descending"
    )
    data = _get(url)
    root = ET.fromstring(data)
    ns = {"atom": "http://www.w3.org/2005/Atom"}
    results = []
    for entry in root.findall("atom:entry", ns):
        id_el = entry.find("atom:id", ns)
        title_el = entry.find("atom:title", ns)
        if id_el is None or title_el is None:
            continue
        # arXiv ID is the last path component of the URL
        paper_id = id_el.text.strip().split("/")[-1]
        title = re.sub(r"\s+", " ", title_el.text or "").strip()
        results.append((paper_id, title))
    return results


def _fetch_arxiv_html(paper_id: str) -> str:
    """
    Fetch full-text HTML for a paper.
    Tries ar5iv.labs.arxiv.org (LaTeX → HTML conversion) first,
    then falls back to the abstract page for the summary.
    Returns cleaned plain text.
    """
    # ar5iv gives nicely structured HTML for papers that have LaTeX source
    html_url = f"https://ar5iv.labs.arxiv.org/html/{paper_id}"
    try:
        html = _get(html_url, timeout=20)
        text = html_to_text(html)
        # ar5iv pages have the full paper — aim for at least 1500 chars
        if len(text) >= 1500:
            # Trim to first ~6000 chars (intro + methods, avoids reference sections)
            # Find a good break point near 6000 chars
            cutoff = 6000
            if len(text) > cutoff:
                # Break at last paragraph boundary before cutoff
                break_pos = text.rfind("\n\n", 0, cutoff)
                text = text[:break_pos if break_pos > 2000 else cutoff]
            return text.strip()
    except Exception as e:
        log.debug("  ar5iv failed for %s: %s", paper_id, e)

    # Fallback: abstract from export.arxiv.org
    abs_url = f"http://export.arxiv.org/api/query?id_list={paper_id}"
    try:
        data = _get(abs_url, timeout=15)
        root = ET.fromstring(data)
        ns = {"atom": "http://www.w3.org/2005/Atom"}
        for entry in root.findall("atom:entry", ns):
            summary_el = entry.find("atom:summary", ns)
            title_el = entry.find("atom:title", ns)
            if summary_el is not None:
                title = (title_el.text or "").strip()
                abstract = re.sub(r"\s+", " ", summary_el.text or "").strip()
                return f"{title}\n\n{abstract}"
    except Exception as e:
        log.debug("  Abstract fallback failed for %s: %s", paper_id, e)

    return ""


def fetch_arxiv(force: bool = False) -> dict[str, list[dict]]:
    """
    Fetch arXiv papers for all authors. Returns:
        { author_id: [ { "paper_id": str, "title": str, "text": str }, ... ] }
    Cached to .benchmark_cache/arxiv/<author_id>/
    """
    ARXIV_DIR.mkdir(parents=True, exist_ok=True)
    all_authors: dict[str, list[dict]] = {}

    for author_id, author_query in ARXIV_AUTHORS:
        author_dir = ARXIV_DIR / author_id
        author_dir.mkdir(exist_ok=True)
        meta_path = author_dir / "meta.json"

        # Load cached metadata
        cached: list[dict] = []
        if meta_path.exists() and not force:
            cached = json.loads(meta_path.read_text())
            if len(cached) >= 6:
                log.info("✓ arXiv %s: %d papers (cached)", author_id, len(cached))
                all_authors[author_id] = cached
                continue

        log.info("→ arXiv %s: fetching paper list...", author_id)
        try:
            paper_ids = _fetch_arxiv_paper_ids(author_query, max_results=ARXIV_MAX_PER_AUTHOR)
            time.sleep(1)  # polite delay for arXiv API
        except Exception as e:
            log.warning("  Failed to fetch paper list for %s: %s", author_id, e)
            all_authors[author_id] = cached
            continue

        papers = list(cached)  # start from cached
        cached_ids = {p["paper_id"] for p in cached}

        for paper_id, title in paper_ids:
            if paper_id in cached_ids:
                continue
            if len(papers) >= ARXIV_MAX_PER_AUTHOR:
                break

            text_path = author_dir / f"{paper_id}.txt"
            if text_path.exists() and not force:
                text = text_path.read_text(encoding="utf-8")
            else:
                log.info("  Fetching %s: %s", paper_id, title[:60])
                try:
                    text = _fetch_arxiv_html(paper_id)
                    time.sleep(1.5)  # polite delay
                except Exception as e:
                    log.warning("  Failed to fetch %s: %s", paper_id, e)
                    continue

                if len(text) < 300:
                    log.debug("  Skipping %s: too short (%d chars)", paper_id, len(text))
                    continue

                text_path.write_text(text, encoding="utf-8")

            papers.append({"paper_id": paper_id, "title": title, "text": text})
            log.info("  + %s (%d chars)", paper_id, len(text))

        # Save metadata (without text inline — text lives in .txt files)
        meta = [{"paper_id": p["paper_id"], "title": p["title"], "text_len": len(p["text"])}
                for p in papers]
        meta_path.write_text(json.dumps(meta, indent=2))

        log.info("✓ arXiv %s: %d papers total", author_id, len(papers))
        all_authors[author_id] = papers

    return all_authors


# ── PAN Authorship Verification Datasets ──────────────────────────────────────

# PAN 2021, 2022, 2023 authorship verification datasets on Zenodo.
# Each is a ZIP containing:
#   pan21-authorship-verification-training-large/
#     pairs.jsonl   — {id, pair: [text1, text2], authors: [a1, a2]}
#     truth.jsonl   — {id, same: bool, almost_same: bool}
#
# All three editions released under Creative Commons — free to download.

PAN_DATASETS = {
    2021: {
        "name": "PAN 2021 Authorship Verification",
        "zenodo_id": "5176357",
        "zenodo_url": "https://zenodo.org/record/5176357/files/pan21-authorship-verification-training-large.zip",
        "zip_name": "pan21-authorship-verification-training-large.zip",
        "inner_dir": "pan21-authorship-verification-training-large",
        "note": "English, cross-topic, fan fiction + news + academic",
    },
    2022: {
        "name": "PAN 2022 Authorship Verification",
        "zenodo_url": "https://zenodo.org/record/7013764/files/pan22-authorship-verification-training-dataset-without-labels.zip",
        "zip_name": "pan22-av-training.zip",
        "inner_dir": "pan22-authorship-verification-training-dataset-without-labels",
        "note": "Multilingual, cross-genre, includes cross-topic same-author pairs",
    },
    2023: {
        "name": "PAN 2023 Authorship Verification",
        "zenodo_url": "https://zenodo.org/record/7729936/files/pan23-authorship-verification-training-dataset20230410.zip",
        "zip_name": "pan23-av-training.zip",
        "inner_dir": "pan23-authorship-verification-training-dataset20230410",
        "note": "English, cross-topic same-author pairs — hardest edition",
    },
}


def fetch_pan(years: list[int] = None, force: bool = False) -> dict[int, dict]:
    """
    Download and extract PAN authorship verification datasets.
    Returns { year: {"pairs": [...], "truth": {...}} }
    where pairs is list of {id, texts: [t1, t2]} and truth is {id: bool}.
    """
    if years is None:
        years = [2021, 2022, 2023]

    PAN_DIR.mkdir(parents=True, exist_ok=True)
    results = {}

    for year in years:
        if year not in PAN_DATASETS:
            log.warning("Unknown PAN year: %d (available: %s)", year, list(PAN_DATASETS.keys()))
            continue

        ds = PAN_DATASETS[year]
        year_dir = PAN_DIR / str(year)
        year_dir.mkdir(exist_ok=True)
        cache_file = year_dir / "dataset.json"

        if cache_file.exists() and not force:
            log.info("✓ PAN %d: loaded from cache", year)
            data = json.loads(cache_file.read_text())
            results[year] = data
            continue

        log.info("→ PAN %d: downloading from Zenodo...", year)
        log.info("  URL: %s", ds["zenodo_url"])
        log.info("  Note: %s", ds["note"])

        zip_path = year_dir / ds["zip_name"]

        if not zip_path.exists() or force:
            try:
                raw = _get(ds["zenodo_url"], timeout=120)
                zip_path.write_bytes(raw)
                log.info("  Downloaded %s (%.1f MB)", ds["zip_name"], len(raw) / 1e6)
            except Exception as e:
                log.error("  Failed to download PAN %d: %s", year, e)
                log.error("  Try downloading manually from: %s", ds["zenodo_url"])
                log.error("  Save to: %s", zip_path)
                continue

        log.info("  Extracting...")
        try:
            with zipfile.ZipFile(zip_path, "r") as zf:
                zf.extractall(year_dir)
        except Exception as e:
            log.error("  Failed to extract: %s", e)
            continue

        # Find the pairs.jsonl and truth.jsonl files
        inner = year_dir / ds["inner_dir"]
        pairs_path = inner / "pairs.jsonl"
        truth_path = inner / "truth.jsonl"

        if not pairs_path.exists():
            # Search recursively
            found = list(year_dir.rglob("pairs.jsonl"))
            if found:
                pairs_path = found[0]
                truth_path = pairs_path.parent / "truth.jsonl"
            else:
                log.error("  Could not find pairs.jsonl in extracted archive")
                continue

        # Parse pairs
        pairs = []
        with open(pairs_path, encoding="utf-8") as f:
            for line in f:
                obj = json.loads(line.strip())
                texts = obj.get("pair", [])
                if len(texts) == 2 and all(len(t) > 100 for t in texts):
                    pairs.append({
                        "id": obj["id"],
                        "texts": texts,
                    })

        # Parse truth labels
        truth = {}
        if truth_path.exists():
            with open(truth_path, encoding="utf-8") as f:
                for line in f:
                    obj = json.loads(line.strip())
                    truth[obj["id"]] = obj.get("same", False)
        else:
            log.warning("  truth.jsonl not found — labels unavailable for PAN %d", year)

        data = {
            "year": year,
            "n_pairs": len(pairs),
            "n_labeled": len(truth),
            "n_same": sum(1 for v in truth.values() if v),
            "n_different": sum(1 for v in truth.values() if not v),
            "pairs": pairs[:2000],   # cap at 2000 pairs to keep cache manageable
            "truth": truth,
        }

        cache_file.write_text(json.dumps(data))
        log.info("✓ PAN %d: %d pairs (%d same, %d different)",
                 year, len(pairs), data["n_same"], data["n_different"])
        results[year] = data

    return results


# ── RAID (Robust AI Detection benchmark) ──────────────────────────────────────
#
# RAID is the largest open AI-detection benchmark — ~10M rows covering 8
# domains × 11 generators × 4 decoding strategies × 11 attacks.
# https://github.com/liamdugan/raid
#
# The full set is huge. We only ever need a sample, and a small CSV file
# is published at HuggingFace's `liamdugan/raid` dataset hub. We try the
# small/sample slice first and fall back to a manual-download message
# pointing at the documented URLs.
#
# Cached file: .benchmark_cache/raid/raid_sample.csv
#   columns: id, adv_source_id, source_id, model, decoding,
#            repetition_penalty, attack, domain, title, prompt, generation
#   (a row with model="human" is a human-written reference)

RAID_DOWNLOAD_URLS = [
    # HuggingFace dataset mirror, smallest sample slice.
    "https://huggingface.co/datasets/liamdugan/raid/resolve/main/data/raid_sample.csv",
    "https://huggingface.co/datasets/liamdugan/raid/raw/main/data/raid_sample.csv",
]


def fetch_raid(force: bool = False) -> Optional[Path]:
    """
    Download the RAID sample CSV into ``.benchmark_cache/raid/``.

    Returns the cached CSV path on success, or None if the download
    fails and the user needs to fetch it manually.
    """
    RAID_DIR.mkdir(parents=True, exist_ok=True)
    out_path = RAID_DIR / "raid_sample.csv"

    if out_path.exists() and not force:
        log.info("✓ RAID: cached at %s (%.1f MB)", out_path, out_path.stat().st_size / 1e6)
        return out_path

    for url in RAID_DOWNLOAD_URLS:
        log.info("→ RAID: trying %s", url)
        try:
            raw = _get(url, timeout=120)
            out_path.write_bytes(raw)
            log.info("✓ RAID: downloaded %.1f MB → %s", len(raw) / 1e6, out_path)
            return out_path
        except Exception as e:
            log.warning("  failed: %s", e)

    log.error("Could not download RAID automatically.")
    log.error("  Manual fetch:")
    log.error("    git clone https://github.com/liamdugan/raid")
    log.error("    cp raid/data/raid_sample.csv %s", out_path)
    log.error("  Then re-run.")
    return None


# ── M4 (Multi-domain, Multi-generator, Multilingual, Multi-source) ────────────
#
# M4 mixes human text vs machine-generated continuations across multiple
# domains (arxiv, peerread, reddit, wikihow, wikipedia, etc.) and
# generators (chatGPT, davinci, cohere, dolly, bloomz, flan-t5).
# https://github.com/mbzuai-nlp/M4
#
# Each JSONL line has fields ``text``, ``label`` (0 = human, 1 = machine),
# ``source``, ``model``. We download the per-source JSONL files directly
# from the GitHub raw URL.

M4_BASE = "https://raw.githubusercontent.com/mbzuai-nlp/M4/main/data"
M4_FILES = [
    # source-specific JSONL files; English-only first pass
    "arxiv_chatGPT.jsonl",
    "arxiv_cohere.jsonl",
    "arxiv_davinci.jsonl",
    "peerread_chatGPT.jsonl",
    "peerread_cohere.jsonl",
    "wikihow_chatGPT.jsonl",
    "wikipedia_chatgpt.jsonl",
    "reddit_chatGPT.jsonl",
]


def fetch_m4(force: bool = False) -> List[Path]:
    """
    Download a sampling of M4 JSONL files. Returns the list of cached
    files on disk (may be partial if some URLs 404).
    """
    M4_DIR.mkdir(parents=True, exist_ok=True)
    cached: List[Path] = []

    for fname in M4_FILES:
        target = M4_DIR / fname
        if target.exists() and not force:
            log.info("✓ M4 %s: cached (%.1f KB)", fname, target.stat().st_size / 1e3)
            cached.append(target)
            continue

        url = f"{M4_BASE}/{fname}"
        log.info("→ M4 %s", url)
        try:
            raw = _get(url, timeout=60)
            target.write_bytes(raw)
            log.info("✓ M4 %s: %.1f KB", fname, len(raw) / 1e3)
            cached.append(target)
        except Exception as e:
            log.warning("  M4 %s: %s (skipping)", fname, e)

    if not cached:
        log.error("No M4 files downloaded. Try:")
        log.error("  git clone https://github.com/mbzuai-nlp/M4")
        log.error("  cp M4/data/*.jsonl %s/", M4_DIR)

    return cached


# ── Summary ────────────────────────────────────────────────────────────────────

def print_summary(arxiv_data: dict, pan_data: dict):
    print("\n" + "=" * 60)
    print("  BENCHMARK DATA SUMMARY")
    print("=" * 60)

    print("\n▸ arXiv Papers")
    total_papers = 0
    for author_id, papers in arxiv_data.items():
        usable = [p for p in papers if len(p.get("text", "")) >= 500]
        total_papers += len(usable)
        print(f"  {author_id:<28} {len(usable):>3} papers  "
              f"(avg {sum(len(p['text']) for p in usable) // max(len(usable), 1):,} chars)")
    print(f"  Total: {total_papers} papers across {len(arxiv_data)} authors")
    print(f"  Baseline: 5 papers/author → Test: 2-3 papers/author + cross-author pairs")

    print("\n▸ PAN Authorship Verification")
    for year, data in pan_data.items():
        print(f"  PAN {year}: {data['n_pairs']:,} pairs  "
              f"({data['n_same']:,} same-author, {data['n_different']:,} different)")

    print("\n▸ Ready to run:")
    print("  python scripts/benchmark.py --dataset arxiv")
    print("  python scripts/benchmark.py --dataset pan2021")
    print("  python scripts/benchmark.py --dataset pan2022")
    print("  python scripts/benchmark.py --dataset all")
    print()


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--arxiv", action="store_true", help="Fetch arXiv papers only")
    parser.add_argument("--pan", action="store_true", help="Fetch PAN datasets only")
    parser.add_argument("--pan-year", type=int, choices=[2021, 2022, 2023],
                        help="Fetch specific PAN year only")
    parser.add_argument("--raid", action="store_true", help="Fetch RAID sample CSV only")
    parser.add_argument("--m4", action="store_true", help="Fetch M4 JSONL files only")
    parser.add_argument("--force", action="store_true", help="Re-download even if cached")
    args = parser.parse_args()

    any_specific = args.arxiv or args.pan or args.pan_year or args.raid or args.m4
    fetch_legacy = not any_specific   # default: arXiv + PAN for back-compat

    arxiv_data = {}
    pan_data = {}
    raid_path: Optional[Path] = None
    m4_paths: List[Path] = []

    if args.arxiv or fetch_legacy:
        log.info("=" * 50)
        log.info("Fetching arXiv papers")
        log.info("=" * 50)
        arxiv_data = fetch_arxiv(force=args.force)

    if args.pan or args.pan_year or fetch_legacy:
        log.info("=" * 50)
        log.info("Fetching PAN datasets")
        log.info("=" * 50)
        years = [args.pan_year] if args.pan_year else [2021, 2022, 2023]
        pan_data = fetch_pan(years=years, force=args.force)

    if args.raid:
        log.info("=" * 50)
        log.info("Fetching RAID sample")
        log.info("=" * 50)
        raid_path = fetch_raid(force=args.force)

    if args.m4:
        log.info("=" * 50)
        log.info("Fetching M4 JSONL files")
        log.info("=" * 50)
        m4_paths = fetch_m4(force=args.force)

    if arxiv_data or pan_data:
        print_summary(arxiv_data, pan_data)
    if raid_path:
        log.info("RAID ready: %s", raid_path)
    if m4_paths:
        log.info("M4 ready: %d JSONL files in %s", len(m4_paths), M4_DIR)
    if not (arxiv_data or pan_data or raid_path or m4_paths):
        log.warning("No data fetched. Run with --arxiv, --pan, --raid, --m4, or no flags for arXiv+PAN.")


if __name__ == "__main__":
    main()
