#!/usr/bin/env python3
"""
benchmark.py — Run Original against four public authorship datasets.

Datasets
--------
1. arXiv          — Academic papers, same author across topics (via arXiv API)
2. Federalist     — 85 essays by Hamilton, Madison, Jay (classic benchmark)
3. Reuters-50     — 50 authors × 50 news articles (downloaded on first run)
4. PAN-style      — Synthetic same/different author pairs built from arXiv

Each dataset builds a per-author baseline (N papers) then scores holdout
documents (same author = should be authentic, different author = suspicious).

Metrics reported: Accuracy, Precision, Recall, F1, AUC (where possible)

Usage
-----
  python scripts/benchmark.py                    # all datasets, API on localhost:8001
  python scripts/benchmark.py --dataset arxiv    # one dataset only
  python scripts/benchmark.py --api http://localhost:8001
  python scripts/benchmark.py --baseline-n 4 --test-n 2
  python scripts/benchmark.py --output results.json
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import re
import sys
import time
import urllib.request
import urllib.parse
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).parent.parent
BENCHMARK_CACHE = PROJECT_ROOT / ".benchmark_cache"
sys.path.insert(0, str(PROJECT_ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("benchmark")

# ── Data structures ────────────────────────────────────────────────────────────

@dataclass
class AuthorDoc:
    author_id: str
    text: str
    title: str = ""
    source: str = ""


@dataclass
class BenchmarkPair:
    """One test case: baseline_author vs. test_doc (same or different author)."""
    baseline_author: str
    test_doc: AuthorDoc
    same_author: bool          # ground truth
    predicted_score: float = 0.0   # Original's authorship probability
    predicted_label: Optional[bool] = None  # True = same author predicted


@dataclass
class DatasetResult:
    name: str
    pairs: list = field(default_factory=list)
    accuracy: float = 0.0
    precision: float = 0.0
    recall: float = 0.0
    f1: float = 0.0
    threshold: float = 0.5
    n_same: int = 0
    n_different: int = 0
    errors: list = field(default_factory=list)


# ── Original API client ────────────────────────────────────────────────────────

class OriginalClient:
    def __init__(self, base_url: str = "http://localhost:8001"):
        self.base_url = base_url.rstrip("/")

    def _post(self, path: str, body: dict) -> dict:
        data = json.dumps(body).encode()
        req = urllib.request.Request(
            f"{self.base_url}{path}",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())

    def _delete_student(self, student_id: str):
        """Remove a student so we start fresh for each benchmark run."""
        req = urllib.request.Request(
            f"{self.base_url}/students/{student_id}",
            method="DELETE",
        )
        try:
            with urllib.request.urlopen(req, timeout=10):
                pass
        except Exception:
            pass  # If DELETE not supported, that's fine

    def health(self) -> bool:
        try:
            req = urllib.request.Request(f"{self.base_url}/health")
            with urllib.request.urlopen(req, timeout=5) as resp:
                return json.loads(resp.read()).get("status") == "ok"
        except Exception:
            return False

    def add_baseline(self, student_id: str, text: str, provenance: str = "benchmark") -> bool:
        try:
            self._post(f"/students/{student_id}/baseline", {
                "text": text,
                "provenance": provenance,
                "assignment": "benchmark-baseline",
            })
            return True
        except Exception as e:
            log.warning("add_baseline failed for %s: %s", student_id, e)
            return False

    def score(self, student_id: str, text: str, force: bool = True) -> Optional[float]:
        try:
            resp = self._post(
                f"/students/{student_id}/score{'?force=true' if force else ''}",
                {"text": text, "assignment": "benchmark-test"},
            )
            # authorship_probability is the key metric: 1.0 = definitely same author
            return resp.get("authorship_signal", {}).get("probability", 0.5)
        except Exception as e:
            log.warning("score failed for %s: %s", student_id, e)
            return None


# ── arXiv dataset ──────────────────────────────────────────────────────────────
# Loads from .benchmark_cache/arxiv/ (populated by scripts/fetch_benchmark_data.py).
# Falls back to live API abstract-only fetch if cache is empty.

BENCHMARK_CACHE = PROJECT_ROOT / ".benchmark_cache"
ARXIV_CACHE_DIR = BENCHMARK_CACHE / "arxiv"

# Author IDs must match what fetch_benchmark_data.py used
ARXIV_AUTHOR_IDS = [
    "bengio_yoshua", "lecun_yann", "manning_christopher",
    "karpathy_andrej", "abbeel_pieter", "chollet_francois",
    "ng_andrew", "goodfellow_ian",
]

# Fallback: minimal author list for live API abstract fetch
ARXIV_AUTHORS_LIVE = [
    ("Yoshua_Bengio",   "Bengio, Yoshua"),
    ("Yann_LeCun",      "LeCun, Yann"),
    ("Geoffrey_Hinton", "Hinton, Geoffrey"),
    ("Andrej_Karpathy", "Karpathy, Andrej"),
    ("Pieter_Abbeel",   "Abbeel, Pieter"),
]


def _load_arxiv_from_cache(author_id: str) -> list[AuthorDoc]:
    """Load cached arXiv papers for one author."""
    author_dir = ARXIV_CACHE_DIR / author_id
    if not author_dir.exists():
        return []
    docs = []
    for txt_file in sorted(author_dir.glob("*.txt")):
        text = txt_file.read_text(encoding="utf-8", errors="ignore").strip()
        if len(text) >= 500:
            docs.append(AuthorDoc(
                author_id=author_id,
                text=text,
                title=txt_file.stem,
                source="arxiv_cached",
            ))
    return docs


def _fetch_arxiv_live(author_query: str, max_results: int = 10) -> list[AuthorDoc]:
    """Live fallback: fetch abstracts from arXiv API."""
    query = urllib.parse.quote(f'au:"{author_query}"')
    url = (
        f"http://export.arxiv.org/api/query"
        f"?search_query={query}"
        f"&max_results={max_results}"
        f"&sortBy=submittedDate&sortOrder=descending"
    )
    docs = []
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Original-Benchmark/1.0"})
        with urllib.request.urlopen(req, timeout=20) as resp:
            xml_data = resp.read()
        root = ET.fromstring(xml_data)
        ns = {"atom": "http://www.w3.org/2005/Atom"}
        for entry in root.findall("atom:entry", ns):
            title_el = entry.find("atom:title", ns)
            summary_el = entry.find("atom:summary", ns)
            if title_el is None or summary_el is None:
                continue
            title = re.sub(r"\s+", " ", title_el.text or "").strip()
            abstract = re.sub(r"\s+", " ", summary_el.text or "").strip()
            if len(abstract) < 200:
                continue
            docs.append(AuthorDoc(
                author_id=author_query,
                text=f"{title}\n\n{abstract}",
                title=title,
                source="arxiv_live",
            ))
        time.sleep(0.5)
    except Exception as e:
        log.warning("arXiv live fetch failed for %s: %s", author_query, e)
    return docs


def load_arxiv(baseline_n: int, test_n: int) -> tuple[dict[str, list], list[AuthorDoc]]:
    baselines: dict[str, list[AuthorDoc]] = {}
    test_docs: list[AuthorDoc] = []

    # Try cache first (populated by fetch_benchmark_data.py)
    cache_authors_found = 0
    for author_id in ARXIV_AUTHOR_IDS:
        docs = _load_arxiv_from_cache(author_id)
        if len(docs) >= baseline_n + 1:
            cache_authors_found += 1
            baselines[author_id] = docs[:baseline_n]
            for doc in docs[baseline_n:baseline_n + test_n]:
                test_docs.append(doc)
            log.info("  [cache] %s: %d baseline, %d test (avg %.0f chars/doc)",
                     author_id, len(baselines[author_id]),
                     min(test_n, len(docs) - baseline_n),
                     sum(len(d.text) for d in baselines[author_id]) / len(baselines[author_id]))

    if cache_authors_found >= 3:
        log.info("arXiv: loaded %d authors from cache (%d baseline docs, %d test docs)",
                 cache_authors_found, sum(len(v) for v in baselines.values()), len(test_docs))
        return baselines, test_docs

    # Fallback: live API (abstracts only — run fetch_benchmark_data.py for full text)
    log.warning("arXiv cache empty or insufficient. Falling back to live API (abstracts only).")
    log.warning("For full-text papers, run:  python scripts/fetch_benchmark_data.py --arxiv")

    for author_id, author_query in ARXIV_AUTHORS_LIVE:
        if author_id in baselines:
            continue
        docs = _fetch_arxiv_live(author_query, max_results=baseline_n + test_n + 5)
        if len(docs) < baseline_n + 1:
            log.warning("Not enough arXiv papers for %s (got %d)", author_id, len(docs))
            continue
        baselines[author_id] = docs[:baseline_n]
        for doc in docs[baseline_n:baseline_n + test_n]:
            doc.author_id = author_id
            test_docs.append(doc)
        log.info("  [live] %s: %d baseline, %d test", author_id,
                 len(baselines[author_id]), min(test_n, len(docs) - baseline_n))

    return baselines, test_docs


# ── Federalist Papers dataset ──────────────────────────────────────────────────

FEDERALIST_URL = "https://www.gutenberg.org/cache/epub/1404/pg1404.txt"

# Known attributions: Hamilton=H, Madison=M, Jay=J, Disputed=D
FEDERALIST_ATTRIBUTION = {
    1: "Jay", 2: "Jay", 3: "Jay", 4: "Jay", 5: "Jay",
    6: "Hamilton", 7: "Hamilton", 8: "Hamilton", 9: "Hamilton", 10: "Madison",
    11: "Hamilton", 12: "Hamilton", 13: "Hamilton", 14: "Madison",
    15: "Hamilton", 16: "Hamilton", 17: "Hamilton", 18: "Madison",
    19: "Madison", 20: "Madison", 21: "Hamilton", 22: "Hamilton",
    23: "Hamilton", 24: "Hamilton", 25: "Hamilton", 26: "Hamilton",
    27: "Hamilton", 28: "Hamilton", 29: "Hamilton", 30: "Hamilton",
    31: "Hamilton", 32: "Hamilton", 33: "Hamilton", 34: "Hamilton",
    35: "Hamilton", 36: "Hamilton", 37: "Madison", 38: "Madison",
    39: "Madison", 40: "Madison", 41: "Madison", 42: "Madison",
    43: "Madison", 44: "Madison", 45: "Madison", 46: "Madison",
    47: "Madison", 48: "Madison", 49: "Madison", 50: "Madison",
    51: "Madison", 52: "Madison", 53: "Madison", 54: "Madison",
    55: "Madison", 56: "Madison", 57: "Madison", 58: "Madison",
    62: "Madison", 63: "Madison",
    64: "Jay",
    65: "Hamilton", 66: "Hamilton", 67: "Hamilton", 68: "Hamilton",
    69: "Hamilton", 70: "Hamilton", 71: "Hamilton", 72: "Hamilton",
    73: "Hamilton", 74: "Hamilton", 75: "Hamilton", 76: "Hamilton",
    77: "Hamilton", 78: "Hamilton", 79: "Hamilton", 80: "Hamilton",
    81: "Hamilton", 82: "Hamilton", 83: "Hamilton", 84: "Hamilton",
    85: "Hamilton",
    # 49-58 and 62-63 disputed — attributed to Madison by modern scholarship
}

_federalist_cache: Optional[str] = None

def fetch_federalist() -> str:
    global _federalist_cache
    if _federalist_cache:
        return _federalist_cache

    cache_path = PROJECT_ROOT / ".benchmark_cache" / "federalist.txt"
    cache_path.parent.mkdir(exist_ok=True)

    if cache_path.exists():
        _federalist_cache = cache_path.read_text(encoding="utf-8", errors="ignore")
        return _federalist_cache

    log.info("Downloading Federalist Papers from Project Gutenberg...")
    try:
        req = urllib.request.Request(
            FEDERALIST_URL,
            headers={"User-Agent": "Original-Benchmark/1.0"}
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            text = resp.read().decode("utf-8", errors="ignore")
        cache_path.write_text(text, encoding="utf-8")
        _federalist_cache = text
        log.info("  Downloaded %d chars", len(text))
    except Exception as e:
        log.warning("Failed to download Federalist Papers: %s", e)
        _federalist_cache = ""
    return _federalist_cache


def parse_federalist_essays(raw: str) -> dict[int, str]:
    """Extract individual essays from the Gutenberg text."""
    essays = {}
    # Split on "FEDERALIST No." or "FEDERALIST. No."
    pattern = re.compile(r"FEDERALIST[.\s]+No\.\s*(\d+)", re.IGNORECASE)
    parts = pattern.split(raw)
    # parts = [preamble, number, text, number, text, ...]
    i = 1
    while i < len(parts) - 1:
        try:
            number = int(parts[i])
            text = parts[i + 1].strip()
            # Trim to first 3000 chars (intro + first few paragraphs)
            text = text[:4000].strip()
            if len(text) > 300:
                essays[number] = text
        except (ValueError, IndexError):
            pass
        i += 2
    return essays


def load_federalist(baseline_n: int, test_n: int) -> tuple[dict[str, list], list[AuthorDoc]]:
    raw = fetch_federalist()
    if not raw:
        return {}, []

    essays = parse_federalist_essays(raw)
    log.info("Parsed %d Federalist essays", len(essays))

    # Group by author
    by_author: dict[str, list[AuthorDoc]] = {"Hamilton": [], "Madison": [], "Jay": []}
    for num, text in essays.items():
        author = FEDERALIST_ATTRIBUTION.get(num)
        if author and author in by_author:
            by_author[author].append(AuthorDoc(
                author_id=author,
                text=text,
                title=f"Federalist No. {num}",
                source="federalist",
            ))

    baselines: dict[str, list[AuthorDoc]] = {}
    test_docs: list[AuthorDoc] = []

    for author, docs in by_author.items():
        if len(docs) < baseline_n + 1:
            log.warning("Not enough Federalist essays for %s (got %d)", author, len(docs))
            continue
        baselines[author] = docs[:baseline_n]
        for doc in docs[baseline_n:baseline_n + test_n]:
            test_docs.append(doc)
        log.info("  %s: %d baseline, %d test", author, len(baselines[author]),
                 min(test_n, len(docs) - baseline_n))

    return baselines, test_docs


# ── Reuters-50 dataset ─────────────────────────────────────────────────────────

# Reuters-50 is available via several mirrors. We use a subset of well-known authors
# by fetching samples from the NLTK corpus or a known GitHub mirror.

REUTERS_AUTHORS_SUBSET = [
    "AaronPressman", "AlanCrosby", "AlexanderSmith", "BenjaminKangLim",
    "BradDorfman", "DarrenSchuettler", "DavidLawder", "EdnaFernandes",
]

REUTERS_GITHUB_BASE = (
    "https://raw.githubusercontent.com/selva86/datasets/master/reuters_50/C50train/"
)

def fetch_reuters_author(author: str, max_docs: int = 10) -> list[AuthorDoc]:
    """Fetch Reuters articles for one author from GitHub mirror."""
    cache_dir = PROJECT_ROOT / ".benchmark_cache" / "reuters" / author
    cache_dir.mkdir(parents=True, exist_ok=True)

    docs = []
    for i in range(1, max_docs + 1):
        filename = f"{i}.txt"
        cache_file = cache_dir / filename
        text = ""

        if cache_file.exists():
            text = cache_file.read_text(encoding="utf-8", errors="ignore")
        else:
            url = f"{REUTERS_GITHUB_BASE}{author}/{filename}"
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "Original-Benchmark/1.0"})
                with urllib.request.urlopen(req, timeout=10) as resp:
                    text = resp.read().decode("utf-8", errors="ignore")
                cache_file.write_text(text, encoding="utf-8")
                time.sleep(0.2)
            except Exception:
                break  # No more files for this author

        if len(text) > 200:
            docs.append(AuthorDoc(
                author_id=author,
                text=text,
                title=f"{author} article {i}",
                source="reuters",
            ))

    return docs


def load_reuters(baseline_n: int, test_n: int) -> tuple[dict[str, list], list[AuthorDoc]]:
    log.info("Fetching Reuters-50 articles...")
    baselines: dict[str, list[AuthorDoc]] = {}
    test_docs: list[AuthorDoc] = []

    for author in REUTERS_AUTHORS_SUBSET:
        docs = fetch_reuters_author(author, max_docs=baseline_n + test_n + 2)
        if len(docs) < baseline_n + 1:
            log.warning("Not enough Reuters articles for %s (got %d)", author, len(docs))
            continue
        baselines[author] = docs[:baseline_n]
        for doc in docs[baseline_n:baseline_n + test_n]:
            test_docs.append(doc)
        log.info("  %s: %d baseline, %d test", author, len(baselines[author]),
                 min(test_n, len(docs) - baseline_n))

    return baselines, test_docs


# ── PAN Authorship Verification datasets (real) ────────────────────────────────
#
# Format on disk (.benchmark_cache/pan/<year>/dataset.json):
#   { pairs: [{id, texts: [t1, t2]}, ...], truth: {id: bool} }
#
# Loaded by fetch_benchmark_data.py.

PAN_CACHE_DIR = BENCHMARK_CACHE / "pan"


def _load_pan_dataset(year: int) -> Optional[dict]:
    cache_file = PAN_CACHE_DIR / str(year) / "dataset.json"
    if not cache_file.exists():
        return None
    try:
        return json.loads(cache_file.read_text())
    except Exception as e:
        log.warning("Failed to load PAN %d cache: %s", year, e)
        return None


def _cluster_pan_pairs(
    pairs: list[dict], truth: dict[str, bool], min_cluster: int = 3, max_clusters: int = 20,
) -> dict[str, list[str]]:
    """
    Group same-author pairs into pseudo-author clusters via union-find.
    If (A,B) and (B,C) are same-author, A/B/C form one cluster.
    Returns { cluster_id: [text, text, ...] }
    """
    same_pairs = [p for p in pairs if truth.get(p["id"], False)]
    parent: dict[str, str] = {}

    def find(x):
        if x not in parent:
            parent[x] = x
        if parent[x] != x:
            parent[x] = find(parent[x])
        return parent[x]

    def union(x, y):
        px, py = find(x), find(y)
        if px != py:
            parent[px] = py

    texts: dict[str, str] = {}
    for pair in same_pairs:
        k0, k1 = f"{pair['id']}_0", f"{pair['id']}_1"
        texts[k0] = pair["texts"][0]
        texts[k1] = pair["texts"][1]
        union(k0, k1)

    from collections import defaultdict
    groups: dict[str, list[str]] = defaultdict(list)
    for k in texts:
        groups[find(k)].append(k)

    result = {}
    for root, members in groups.items():
        cluster_texts = [texts[m] for m in members if len(texts[m]) >= 300]
        if len(cluster_texts) >= min_cluster:
            result[root[:8]] = cluster_texts
        if len(result) >= max_clusters:
            break
    return result


def _load_pan(year: int, baseline_n: int, test_n: int) -> tuple[dict[str, list], list[AuthorDoc]]:
    data = _load_pan_dataset(year)
    if data is None:
        log.warning("PAN %d cache not found. Run:  python scripts/fetch_benchmark_data.py --pan-year %d", year, year)
        return {}, []

    pairs = data["pairs"]
    truth = data["truth"]
    log.info("PAN %d: %d pairs (%d same-author, %d different)",
             year, len(pairs), data.get("n_same", 0), data.get("n_different", 0))

    clusters = _cluster_pan_pairs(pairs, truth, min_cluster=baseline_n + 1)
    log.info("  Formed %d pseudo-author clusters (≥%d texts each)", len(clusters), baseline_n + 1)

    baselines: dict[str, list[AuthorDoc]] = {}
    test_docs: list[AuthorDoc] = []

    if clusters:
        for cluster_id, cluster_texts in clusters.items():
            author_id = f"pan{year}_{cluster_id}"
            baselines[author_id] = [
                AuthorDoc(author_id=author_id, text=t, title=f"pan{year}-{cluster_id}-b{i}",
                          source=f"pan{year}")
                for i, t in enumerate(cluster_texts[:baseline_n])
            ]
            for i, t in enumerate(cluster_texts[baseline_n:baseline_n + test_n]):
                test_docs.append(AuthorDoc(
                    author_id=author_id, text=t,
                    title=f"pan{year}-{cluster_id}-t{i}", source=f"pan{year}",
                ))
    else:
        # Fallback: paired mode — text[0]=baseline, text[1]=test
        log.info("  Falling back to paired mode (1 baseline doc per author)")
        same_pairs = [p for p in pairs if truth.get(p["id"], False)
                      and all(len(t) >= 400 for t in p["texts"])][:50]
        for i, pair in enumerate(same_pairs):
            author_id = f"pan{year}_pair{i}"
            baselines[author_id] = [AuthorDoc(
                author_id=author_id, text=pair["texts"][0],
                title=f"{pair['id']}_baseline", source=f"pan{year}",
            )]
            test_docs.append(AuthorDoc(
                author_id=author_id, text=pair["texts"][1],
                title=f"{pair['id']}_test", source=f"pan{year}",
            ))

    log.info("  %d authors, %d baseline docs, %d test docs",
             len(baselines), sum(len(v) for v in baselines.values()), len(test_docs))
    return baselines, test_docs


def load_pan2021(baseline_n: int, test_n: int) -> tuple[dict[str, list], list[AuthorDoc]]:
    return _load_pan(2021, baseline_n, test_n)

def load_pan2022(baseline_n: int, test_n: int) -> tuple[dict[str, list], list[AuthorDoc]]:
    return _load_pan(2022, baseline_n, test_n)

def load_pan2023(baseline_n: int, test_n: int) -> tuple[dict[str, list], list[AuthorDoc]]:
    return _load_pan(2023, baseline_n, test_n)


# ── PAN-style synthetic dataset (legacy) ──────────────────────────────────────

def load_pan_style(baseline_n: int, test_n: int) -> tuple[dict[str, list], list[AuthorDoc]]:
    """
    Legacy: try real PAN 2021 first, fall back to synthetic arXiv pairs.
    """
    real_b, real_t = load_pan2021(baseline_n, test_n)
    if real_b:
        return real_b, real_t

    log.warning("Real PAN cache unavailable. Using synthetic arXiv pairs.")
    log.warning("Run:  python scripts/fetch_benchmark_data.py --pan")
    pan_authors = [
        ("pan_Bengio",  "Bengio, Yoshua"),
        ("pan_Manning", "Manning, Christopher"),
        ("pan_LeCun",   "LeCun, Yann"),
    ]
    baselines: dict[str, list[AuthorDoc]] = {}
    test_docs: list[AuthorDoc] = []
    for author_id, author_query in pan_authors:
        docs = _fetch_arxiv_live(author_query, max_results=baseline_n + test_n + 5)
        if len(docs) < baseline_n + 1:
            continue
        baselines[author_id] = docs[:baseline_n]
        for doc in docs[baseline_n:baseline_n + test_n]:
            doc.author_id = author_id
            test_docs.append(doc)
    return baselines, test_docs


# ── Benchmark engine ───────────────────────────────────────────────────────────

def build_pairs(
    baselines: dict[str, list[AuthorDoc]],
    test_docs: list[AuthorDoc],
    different_author_samples: int = 1,
) -> list[BenchmarkPair]:
    """
    For each test doc:
    - 1 same-author pair (ground truth = True)
    - N different-author pairs (ground truth = False)
    """
    pairs = []
    author_ids = list(baselines.keys())

    for doc in test_docs:
        # Same-author pair
        if doc.author_id in baselines:
            pairs.append(BenchmarkPair(
                baseline_author=doc.author_id,
                test_doc=doc,
                same_author=True,
            ))

        # Different-author pairs
        others = [a for a in author_ids if a != doc.author_id]
        for other in others[:different_author_samples]:
            pairs.append(BenchmarkPair(
                baseline_author=other,
                test_doc=doc,
                same_author=False,
            ))

    return pairs


def run_dataset(
    name: str,
    baselines: dict[str, list[AuthorDoc]],
    test_docs: list[AuthorDoc],
    client: OriginalClient,
    threshold: float = 0.5,
) -> DatasetResult:
    result = DatasetResult(name=name, threshold=threshold)

    if not baselines or not test_docs:
        result.errors.append("No data loaded for this dataset")
        return result

    pairs = build_pairs(baselines, test_docs)
    log.info("%s: %d pairs (%d same, %d different)",
             name, len(pairs),
             sum(1 for p in pairs if p.same_author),
             sum(1 for p in pairs if not p.same_author))

    # Load all baselines into Original
    log.info("Loading baselines into Original...")
    for author_id, docs in baselines.items():
        student_id = f"bench_{name}_{author_id}"
        client._delete_student(student_id)  # clear previous run
        for doc in docs:
            ok = client.add_baseline(student_id, doc.text, provenance=doc.source)
            if not ok:
                result.errors.append(f"Failed to add baseline for {author_id}")
        log.info("  Loaded %d docs for %s", len(docs), author_id)

    # Score all pairs
    log.info("Scoring %d pairs...", len(pairs))
    for i, pair in enumerate(pairs):
        student_id = f"bench_{name}_{pair.baseline_author}"
        score = client.score(student_id, pair.test_doc.text)
        if score is None:
            result.errors.append(f"Score failed: {pair.baseline_author} / {pair.test_doc.title}")
            score = 0.5

        pair.predicted_score = score
        pair.predicted_label = score >= threshold

        if (i + 1) % 10 == 0:
            log.info("  Scored %d/%d pairs", i + 1, len(pairs))

    # Compute metrics
    result.pairs = pairs
    result.n_same = sum(1 for p in pairs if p.same_author)
    result.n_different = sum(1 for p in pairs if not p.same_author)

    tp = sum(1 for p in pairs if p.same_author and p.predicted_label)
    fp = sum(1 for p in pairs if not p.same_author and p.predicted_label)
    tn = sum(1 for p in pairs if not p.same_author and not p.predicted_label)
    fn = sum(1 for p in pairs if p.same_author and not p.predicted_label)

    total = len(pairs)
    result.accuracy = (tp + tn) / total if total else 0
    result.precision = tp / (tp + fp) if (tp + fp) else 0
    result.recall = tp / (tp + fn) if (tp + fn) else 0
    f1_denom = result.precision + result.recall
    result.f1 = 2 * result.precision * result.recall / f1_denom if f1_denom else 0

    return result


# ── Report ─────────────────────────────────────────────────────────────────────

def print_report(results: list[DatasetResult]):
    print("\n" + "=" * 70)
    print("  ORIGINAL BENCHMARK RESULTS")
    print("=" * 70)

    all_tp = all_fp = all_tn = all_fn = 0

    for r in results:
        print(f"\n▸ {r.name.upper()}")
        print(f"  Pairs:     {len(r.pairs)} total  ({r.n_same} same-author, {r.n_different} different)")
        print(f"  Accuracy:  {r.accuracy:.1%}")
        print(f"  Precision: {r.precision:.1%}  (of predicted 'same', how many actually were)")
        print(f"  Recall:    {r.recall:.1%}  (of actual 'same', how many did we catch)")
        print(f"  F1:        {r.f1:.1%}")
        if r.errors:
            print(f"  Errors:    {len(r.errors)}")
            for e in r.errors[:3]:
                print(f"    - {e}")

        for p in r.pairs:
            all_tp += 1 if (p.same_author and p.predicted_label) else 0
            all_fp += 1 if (not p.same_author and p.predicted_label) else 0
            all_tn += 1 if (not p.same_author and not p.predicted_label) else 0
            all_fn += 1 if (p.same_author and not p.predicted_label) else 0

    total = all_tp + all_fp + all_tn + all_fn
    if total:
        acc = (all_tp + all_tn) / total
        prec = all_tp / (all_tp + all_fp) if (all_tp + all_fp) else 0
        rec = all_tp / (all_tp + all_fn) if (all_tp + all_fn) else 0
        f1 = 2 * prec * rec / (prec + rec) if (prec + rec) else 0

        print("\n" + "─" * 70)
        print("  OVERALL (all datasets combined)")
        print(f"  Accuracy:  {acc:.1%}")
        print(f"  Precision: {prec:.1%}")
        print(f"  Recall:    {rec:.1%}")
        print(f"  F1:        {f1:.1%}")
        print(f"  Total pairs: {total}  (TP={all_tp} FP={all_fp} TN={all_tn} FN={all_fn})")

    print("\n" + "=" * 70 + "\n")


# ── Main ───────────────────────────────────────────────────────────────────────

DATASETS = {
    "arxiv":      load_arxiv,
    "federalist": load_federalist,
    "reuters":    load_reuters,
    "pan":        load_pan_style,    # tries real PAN 2021, falls back to synthetic
    "pan2021":    load_pan2021,
    "pan2022":    load_pan2022,
    "pan2023":    load_pan2023,
}


def run_synthetic_benchmark(baseline_n: int = 6, test_n: int = 4) -> None:
    """
    Run a full benchmark using synthetically generated feature vectors.
    No network access required.

    Positive class = SUSPICIOUS (cross-author, AI-generated).
    Negative class = AUTHENTIC  (same-author holdouts).

    Classification uses the system's actual action recommendation:
      no_action / monitor           → authentic (negative)
      schedule_conversation/escalate → suspicious (positive)

    AUC is computed from the deviation_score continuous output.
    """
    import numpy as np
    from original.constants import FEATURE_DIM, ALL_FEATURE_CODES
    from original.quantum.state import StudentState, BaselineSample
    from original.quantum.scoring import score as quantum_score

    SUSPICIOUS_ACTIONS = {"schedule_conversation", "escalate"}
    N_AUTHORS   = 10
    N_BASELINE  = baseline_n   # samples per author baseline
    N_HOLDOUTS  = 3            # same-author holdout trials per author

    log.info("SYNTHETIC BENCHMARK — no network access required")
    log.info("Generating %d synthetic authors, FEATURE_DIM=%d", N_AUTHORS, FEATURE_DIM)

    # ── 1. Build author baselines ─────────────────────────────────────────────
    def make_base(seed):
        rng = np.random.default_rng(seed)
        return rng.uniform(0.2, 0.8, FEATURE_DIM)

    def build_state(base, author_seed):
        rng = np.random.default_rng(author_seed + 5000)
        state = StudentState(student_id=f"author_{author_seed}")
        for i in range(N_BASELINE):
            v = np.clip(base + rng.normal(0, 0.04, FEATURE_DIM), 0, 1)
            state.samples.append(BaselineSample(
                text=f"s{i}", vector=v, provenance="proctored", auth_weight=1.0))
        return state

    bases  = [make_base(s * 137 + 7) for s in range(N_AUTHORS)]
    states = [build_state(b, s) for s, b in enumerate(bases)]

    def fd(v):
        return {c: float(v[j]) for j, c in enumerate(ALL_FEATURE_CODES)}

    def run(st, vec):
        r = quantum_score(st, vec, fd(vec))
        return r.authorship.deviation_score, r.recommendation.action

    ttr_i = ALL_FEATURE_CODES.index("type_token_ratio")
    err_i = ALL_FEATURE_CODES.index("error_kl_divergence")

    # ── 2. Collect (true_suspicious, deviation_score) pairs ──────────────────
    # true_suspicious = True  → should be flagged (cross-author or AI)
    # true_suspicious = False → should be authentic  (same-author holdout)
    records = []   # (true_suspicious, dev_score, action, scenario_name)

    # Scenario 1: same-author holdouts (authentic, N_AUTHORS × N_HOLDOUTS)
    for ai in range(N_AUTHORS):
        rng = np.random.default_rng(ai * 333 + 1)
        for _ in range(N_HOLDOUTS):
            v = np.clip(bases[ai] + rng.normal(0, 0.04, FEATURE_DIM), 0, 1)
            D, act = run(states[ai], v)
            records.append((False, D, act, "same-author"))

    # Scenario 2: cross-author impostors (suspicious, N_AUTHORS × N_HOLDOUTS)
    for ai in range(N_AUTHORS):
        imp = (ai + 1) % N_AUTHORS
        rng = np.random.default_rng(ai * 444 + 2)
        for _ in range(N_HOLDOUTS):
            v = np.clip(bases[imp] + rng.normal(0, 0.04, FEATURE_DIM), 0, 1)
            D, act = run(states[ai], v)
            records.append((True, D, act, "cross-author"))

    # Scenario 3: AI uniform — all features 0.5 (N_AUTHORS cases)
    for ai in range(N_AUTHORS):
        v = np.full(FEATURE_DIM, 0.5)
        D, act = run(states[ai], v)
        records.append((True, D, act, "ai-uniform"))

    # Scenario 4: AI jittered (N_AUTHORS cases)
    rng_j = np.random.default_rng(1337)
    for ai in range(N_AUTHORS):
        v = np.clip(np.full(FEATURE_DIM, 0.5) + rng_j.normal(0, 0.025, FEATURE_DIM), 0, 1)
        D, act = run(states[ai], v)
        records.append((True, D, act, "ai-jittered"))

    # Scenario 5: AI surgical — spikes TTR + zeros error fingerprint (N_AUTHORS cases)
    for ai in range(N_AUTHORS):
        v = bases[ai].copy()
        v[ttr_i] = 0.95
        v[err_i] = 0.02
        D, act = run(states[ai], v)
        records.append((True, D, act, "ai-surgical"))

    n_total = len(records)
    log.info("Ran %d test cases across 5 scenarios", n_total)

    # ── 3. Action-based classification metrics ────────────────────────────────
    # Predicted suspicious = action in {schedule_conversation, escalate}
    tp = sum(1 for sus, _, act, _ in records if sus     and act in SUSPICIOUS_ACTIONS)
    fp = sum(1 for sus, _, act, _ in records if not sus and act in SUSPICIOUS_ACTIONS)
    tn = sum(1 for sus, _, act, _ in records if not sus and act not in SUSPICIOUS_ACTIONS)
    fn = sum(1 for sus, _, act, _ in records if sus     and act not in SUSPICIOUS_ACTIONS)

    accuracy  = (tp + tn) / n_total if n_total else 0
    precision = tp / (tp + fp) if (tp + fp) else 0
    recall    = tp / (tp + fn) if (tp + fn) else 0
    f1        = 2*precision*recall / (precision+recall) if (precision+recall) else 0
    fpr       = fp / (fp + tn) if (fp + tn) else 0
    fnr       = fn / (fn + tp) if (fn + tp) else 0

    # ── 4. AUC from continuous deviation_score (higher D = more suspicious) ──
    pos_scores = sorted([D for sus, D, _, _ in records if sus],     reverse=True)
    neg_scores = sorted([D for sus, D, _, _ in records if not sus], reverse=True)
    all_thresh = sorted(set(D for _, D, _, _ in records), reverse=True) + [0.0]

    tpr_pts, fpr_pts = [0.0], [0.0]
    n_pos = sum(1 for sus, _, _, _ in records if sus)
    n_neg = sum(1 for sus, _, _, _ in records if not sus)
    for thresh in all_thresh:
        tp_t = sum(1 for sus, D, _, _ in records if sus     and D >= thresh)
        fp_t = sum(1 for sus, D, _, _ in records if not sus and D >= thresh)
        tpr_pts.append(tp_t / n_pos if n_pos else 0)
        fpr_pts.append(fp_t / n_neg if n_neg else 0)
    tpr_pts.append(1.0); fpr_pts.append(1.0)
    auc = sum(
        (fpr_pts[i] - fpr_pts[i-1]) * (tpr_pts[i] + tpr_pts[i-1]) / 2
        for i in range(1, len(fpr_pts))
    )

    # ── 5. Per-scenario breakdown ─────────────────────────────────────────────
    from collections import defaultdict
    by_scenario = defaultdict(lambda: {"correct": 0, "total": 0, "mean_D": []})
    for sus, D, act, scen in records:
        correct = (sus and act in SUSPICIOUS_ACTIONS) or (not sus and act not in SUSPICIOUS_ACTIONS)
        by_scenario[scen]["correct"] += int(correct)
        by_scenario[scen]["total"]   += 1
        by_scenario[scen]["mean_D"].append(D)

    # ── 6. Print report ───────────────────────────────────────────────────────
    W = 72
    print("\n" + "="*W)
    print("  Ωriginal — SYNTHETIC BENCHMARK REPORT")
    print("="*W)
    print(f"  Authors: {N_AUTHORS}   Baseline samples/author: {N_BASELINE}   "
          f"Feature dim: {FEATURE_DIM}")
    print(f"  Total test cases: {n_total}")
    print()
    print("  ┌──────────────────────────────┬───────┬───────┬──────────┐")
    print("  │ scenario                     │ n     │ ok    │ mean D   │")
    print("  ├──────────────────────────────┼───────┼───────┼──────────┤")
    for scen in ["same-author","cross-author","ai-uniform","ai-jittered","ai-surgical"]:
        row = by_scenario[scen]
        mean_D = np.mean(row["mean_D"]) if row["mean_D"] else 0
        ok  = row["correct"]
        tot = row["total"]
        bar = "✓" if ok==tot else "△" if ok/tot>=0.8 else "✗"
        print(f"  │ {scen:<28s} │ {tot:>5d} │ {ok:>4d}{bar} │ {mean_D:.3f}    │")
    print("  └──────────────────────────────┴───────┴───────┴──────────┘")
    print()
    print("  Classification (action-based: sched_conv / escalate = suspicious)")
    print(f"    Accuracy:   {accuracy:6.1%}    TP={tp:3d}  FP={fp:3d}")
    print(f"    Precision:  {precision:6.1%}    FN={fn:3d}  TN={tn:3d}")
    print(f"    Recall:     {recall:6.1%}")
    print(f"    F1:         {f1:6.1%}")
    print()
    print("  Ranking (deviation_score AUC)")
    print(f"    AUC (ROC):  {auc:6.1%}   (trapezoidal integration over all thresholds)")
    print(f"    FPR:        {fpr:6.1%}   ({fp} same-author texts incorrectly flagged)")
    print(f"    FNR:        {fnr:6.1%}   ({fn} suspicious texts missed entirely)")
    print()
    sep = np.mean([D for sus, D, _, _ in records if not sus])  # mean D for authentic
    sus_d = np.mean([D for sus, D, _, _ in records if sus])     # mean D for suspicious
    print(f"  Score separation:  authentic mean D={sep:.3f}  |  suspicious mean D={sus_d:.3f}")
    print(f"  Gap: {sus_d-sep:+.3f}  ({'STRONG ✓' if sus_d-sep>0.3 else 'MARGINAL'})")
    print()

    if accuracy >= 0.92 and auc >= 0.95 and fpr <= 0.15:
        readiness = "READY FOR PROFESSOR PILOTS  ✓"
    elif accuracy >= 0.85 and auc >= 0.90:
        readiness = "NEEDS MINOR CALIBRATION  △"
    elif auc >= 0.80:
        readiness = "NEEDS CALIBRATION  ✗"
    else:
        readiness = "NOT READY  ✗"

    print(f"  Readiness: {readiness}")
    print("="*W)
    print()


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--synthetic", action="store_true",
                        help="Run synthetic benchmark (no network required)")
    parser.add_argument("--dataset", choices=list(DATASETS.keys()) + ["all"], default="all",
                        help="Dataset to run (default: all). pan=PAN2021+synthetic fallback; pan2021/2022/2023=specific PAN edition")
    parser.add_argument("--api", default="http://localhost:8001", help="Original API base URL")
    parser.add_argument("--baseline-n", type=int, default=4, help="Docs per author for baseline")
    parser.add_argument("--test-n", type=int, default=2, help="Docs per author for testing")
    parser.add_argument("--threshold", type=float, default=0.5, help="Score threshold for same-author prediction")
    parser.add_argument("--output", default=None, help="Save results to JSON file")
    args = parser.parse_args()

    # Handle synthetic benchmark mode
    if args.synthetic:
        run_synthetic_benchmark(baseline_n=args.baseline_n, test_n=args.test_n)
        return

    client = OriginalClient(args.api)

    log.info("Checking Original API at %s...", args.api)
    if not client.health():
        log.error(
            "Original API not reachable at %s\n"
            "Start the server first:  python -m original.api  (or  uvicorn original.api:app --port 8001)",
            args.api
        )
        sys.exit(1)
    log.info("API is healthy ✓")

    datasets_to_run = list(DATASETS.keys()) if args.dataset == "all" else [args.dataset]
    results = []

    for ds_name in datasets_to_run:
        log.info("\n%s Loading %s dataset %s", "─" * 20, ds_name.upper(), "─" * 20)
        loader = DATASETS[ds_name]
        try:
            baselines, test_docs = loader(args.baseline_n, args.test_n)
            result = run_dataset(ds_name, baselines, test_docs, client, threshold=args.threshold)
            results.append(result)
        except Exception as e:
            log.error("Dataset %s failed: %s", ds_name, e, exc_info=True)
            results.append(DatasetResult(name=ds_name, errors=[str(e)]))

    print_report(results)

    if args.output:
        out_path = Path(args.output)
        # Convert dataclasses to dicts for JSON serialization
        serializable = []
        for r in results:
            d = asdict(r)
            # pairs list can be large; summarize
            d["pair_scores"] = [
                {"same": p["same_author"], "score": p["predicted_score"], "correct": p["same_author"] == p["predicted_label"]}
                for p in d.pop("pairs", [])
            ]
            serializable.append(d)
        out_path.write_text(json.dumps(serializable, indent=2))
        log.info("Results saved to %s", out_path)


if __name__ == "__main__":
    main()
