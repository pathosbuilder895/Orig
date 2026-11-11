"""Fetch and clean papers author by author, screened candidates only.

    python -m validation.scholarly.fetch --collection humanities --limit-authors 50

Reads ``candidates/<collection>.json`` (written by ``screen.py``; this script
never queries a catalogue), downloads full texts into a git-ignored cache,
cleans them (``clean.py``) and writes ``manifest/<collection>.json``.

Early stops, both directions (``decide``):
  * done    : ``max_papers`` usable papers in hand (default 12).
  * abandon : usable so far + candidates still untried < 6. The author is
              dropped from the manifest and logged with the reason.
Resumable: every paper outcome is appended to ``<cache>/<collection>/state.jsonl``
and skipped on the next run. Rate limited per host (arXiv: one request per
3 seconds, one connection, per its API terms); generic User-Agent, no contact
details. Only text is kept; PDFs are never stored.
"""
from __future__ import annotations

import argparse
import hashlib
import http.client
import json
import os
import sys
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional
from urllib.parse import quote, urlparse

from . import clean, policy
from .schema import ScholarlyManifest, ScholarlyPaper

HERE = Path(__file__).resolve().parent
USER_AGENT = "scholarly-corpus-builder/0.1"  # generic by design
DEFAULT_CACHE = Path(os.environ.get("SCHOLARLY_CACHE", HERE / "cache"))
MAX_PDF_BYTES = 40 * 1024 * 1024
HOST_INTERVAL = {"arxiv.org": 3.2, "export.arxiv.org": 3.2}  # arXiv API terms: 1 req / 3 s
DEFAULT_INTERVAL = 1.0


# ------------------------------------------------------------- stop logic --
def decide(n_ok: int, n_tried: int, n_total: int,
           min_ok: int = policy.MIN_USABLE_PAPERS, max_ok: int = policy.MAX_USABLE_PAPERS) -> str:
    """'done' | 'abandon' | 'continue' for one author after ``n_tried`` papers."""
    if n_ok >= max_ok:
        return "done"
    remaining = n_total - n_tried
    if n_ok + remaining < min_ok:
        return "abandon"
    if remaining == 0:
        return "done"  # exhausted with n_ok >= min_ok (else abandoned above)
    return "continue"


# ----------------------------------------------------------------- results --
@dataclass
class PaperResult:
    work_id: str
    author_id: str
    status: str            # "ok" or "fail"
    reason: str = ""       # http_403, not_pdf, too_short, not_english, duplicate, ...
    words: int = 0
    sha: str = ""
    seconds: float = 0.0
    requests: int = 0
    text: Optional[str] = field(default=None, repr=False)

    def record(self) -> dict:
        d = {k: getattr(self, k) for k in ("work_id", "author_id", "status", "reason", "words", "sha", "seconds", "requests")}
        d["ts"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        return d


@dataclass
class AuthorOutcome:
    author_id: str
    status: str            # "usable" | "abandoned"
    reason: str
    ok: List[str]          # work ids kept (in fetch order)
    tried: int
    results: List[PaperResult]


def shingles(text: str, k: int = 6) -> set:
    w = text.lower().split()
    return {hash(tuple(w[i:i + k])) for i in range(0, max(len(w) - k + 1, 0), 3)}


def is_duplicate(text: str, others: List[set], threshold: float = 0.25) -> bool:
    s = shingles(text)
    if not s:
        return False
    for o in others:
        if o and len(s & o) / min(len(s), len(o)) >= threshold:
            return True
    return False


def paper_order(author: dict) -> List[dict]:
    """Deterministic fetch order: papers on non-arXiv hosts first (they fetch in parallel; arXiv
    is limited to one request per 3 seconds for the whole run), then by a hash of the work id,
    never by year or rank, so the choice of which papers to try is neutral."""
    return sorted(author["papers"], key=lambda p: (urlparse(p["url"]).netloc.lower().endswith("arxiv.org"),
                                                   hashlib.sha256(p["work_id"].encode()).hexdigest()))


def process_author(author: dict, fetch_one: Callable[[dict], PaperResult],
                   done_state: Dict[str, PaperResult], on_result: Callable[[PaperResult], None] = lambda r: None,
                   min_ok: int = policy.MIN_USABLE_PAPERS, max_ok: int = policy.MAX_USABLE_PAPERS) -> AuthorOutcome:
    """Fetch one author's papers until done or hopeless.

    ``fetch_one(paper)`` returns a PaperResult; ``done_state`` holds results from
    earlier runs (their texts are re-read through ``fetch_one``'s cache by the
    caller, so only the outcome is needed here). Duplicate versions are judged
    by the caller's fetch_one via shared shingle state.
    """
    papers = paper_order(author)
    ok: List[str] = []
    results: List[PaperResult] = []
    tried = 0
    for p in papers:
        verdict = decide(len(ok), tried, len(papers), min_ok, max_ok)
        if verdict == "done":
            break
        if verdict == "abandon":
            break
        prev = done_state.get(p["work_id"])
        r = prev if prev is not None else fetch_one(p)
        if prev is None:
            on_result(r)
        results.append(r)
        tried += 1
        if r.status == "ok":
            ok.append(r.work_id)
    verdict = decide(len(ok), tried, len(papers), min_ok, max_ok)
    if verdict == "abandon" or len(ok) < min_ok:
        fails = {}
        for r in results:
            if r.status != "ok":
                fails[r.reason] = fails.get(r.reason, 0) + 1
        why = f"only {len(ok)} usable after {tried}/{len(papers)} candidates; failures {fails}"
        return AuthorOutcome(author["author_id"], "abandoned", why, ok, tried, results)
    return AuthorOutcome(author["author_id"], "usable", "ok", ok, tried, results)


# -------------------------------------------------------------- networking --
class HostLimiter:
    def __init__(self, intervals: Dict[str, float] = HOST_INTERVAL, default: float = DEFAULT_INTERVAL):
        self.intervals, self.default = intervals, default
        self._last: Dict[str, float] = {}
        self._lock = threading.Lock()
        self._host_locks: Dict[str, threading.Lock] = {}

    def wait(self, host: str) -> None:
        with self._lock:
            hl = self._host_locks.setdefault(host, threading.Lock())
        with hl:  # one connection per host at a time (arXiv terms), spaced by the interval
            gap = self.intervals.get(host, self.default)
            now = time.monotonic()
            sleep = self._last.get(host, 0) + gap - now
            if sleep > 0:
                time.sleep(sleep)
            self._last[host] = time.monotonic()


def http_get(url: str, limiter: HostLimiter, timeout: int = 60, tries: int = 2):
    """(status_or_reason, bytes|None, requests_made)."""
    url = quote(url, safe=":/?&=%#+@,;~!$'()*[]")  # spaces etc. in publisher paths
    host = urlparse(url).netloc.lower()
    reqs = 0
    reason = "error"
    for attempt in range(tries):
        limiter.wait(host)
        reqs += 1
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/pdf,*/*;q=0.5"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                body = r.read(MAX_PDF_BYTES + 1)
            if len(body) > MAX_PDF_BYTES:
                return "too_large", None, reqs
            return "ok", body, reqs
        except urllib.error.HTTPError as e:
            reason = f"http_{e.code}"
            if e.code in (429, 503):
                time.sleep(5 * (attempt + 1))
                continue
            return reason, None, reqs
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError, ValueError, http.client.HTTPException):
            reason = "network"
            time.sleep(2)
    return reason, None, reqs


class Fetcher:
    def __init__(self, collection: str, cache: Path, limiter: Optional[HostLimiter] = None):
        self.collection, self.cache = collection, cache
        self.limiter = limiter or HostLimiter()
        self.texts = cache / collection / "texts"
        self.tmp = cache / collection / "tmp"
        self._shingles: Dict[str, Dict[str, set]] = {}
        self._lock = threading.Lock()

    def text_path(self, author_id: str, work_id: str) -> Path:
        return self.texts / author_id / f"{work_id}.txt"

    def _peers(self, author_id: str) -> Dict[str, set]:
        with self._lock:
            if author_id not in self._shingles:
                d = {}
                for f in (self.texts / author_id).glob("*.txt") if (self.texts / author_id).exists() else []:
                    d[f.stem] = shingles(f.read_text(encoding="utf-8"))
                self._shingles[author_id] = d
            return self._shingles[author_id]

    def __call__(self, paper: dict, author_id: str) -> PaperResult:
        t0 = time.time()
        wid = paper["work_id"]
        res = PaperResult(wid, author_id, "fail")
        status, body, reqs = http_get(paper["url"], self.limiter)
        res.requests = reqs
        try:
            if status != "ok":
                res.reason = status
            else:
                ex = clean.pdf_bytes_to_extraction(body, self.tmp, name=f"{author_id}_{wid}")
                text = None if ex is None else ex.text
                if ex is None:
                    res.reason = "not_pdf"
                elif ex.raw_words < 100:
                    res.reason = "no_text"            # scanned PDF, no text layer
                elif len(text.split()) >= 300 and not clean.is_english(text):
                    res.reason = "not_english"        # prose that remains is not English
                elif len(text.split()) < 300 and ex.raw_stopword < 0.17:
                    res.reason = "not_english"        # almost nothing left AND the raw text is not English
                elif len(text.split()) < policy.MIN_PROSE_WORDS:
                    res.reason, res.words = "too_short", len(text.split())
                else:
                    peers = self._peers(author_id)
                    if is_duplicate(text, list(peers.values())):
                        res.reason = "duplicate"
                    else:
                        res.status, res.words = "ok", len(text.split())
                        res.sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
                        p = self.text_path(author_id, wid)
                        p.parent.mkdir(parents=True, exist_ok=True)
                        p.write_text(text, encoding="utf-8")
                        peers[wid] = shingles(text)
        except clean.PdfToolMissing:
            raise
        except Exception as e:  # a malformed PDF must cost one paper, not the run
            res.reason = f"extract_error:{type(e).__name__}"
        res.seconds = round(time.time() - t0, 2)
        return res


# ---------------------------------------------------------------- state io --
def load_state(path: Path) -> Dict[str, PaperResult]:
    out: Dict[str, PaperResult] = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                d = json.loads(line)
                out[d["work_id"]] = PaperResult(**{k: d[k] for k in
                    ("work_id", "author_id", "status", "reason", "words", "sha", "seconds", "requests")})
    return out


class StateWriter:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self._f = path.open("a", encoding="utf-8")
        self._lock = threading.Lock()

    def __call__(self, r: PaperResult) -> None:
        with self._lock:
            self._f.write(json.dumps(r.record()) + "\n")
            self._f.flush()


# ---------------------------------------------------------------- manifest --
def build_manifest(collection: str, authors: List[dict], state: Dict[str, PaperResult],
                   max_ok: int = policy.MAX_USABLE_PAPERS, min_ok: int = policy.MIN_USABLE_PAPERS):
    """Manifest of usable papers of usable authors, plus the dropped-author log."""
    papers, dropped = [], []
    seen_hash: Dict[str, str] = {}   # one text, one paper: the same PDF can sit under two catalogue works
    for a in authors:
        results = [state[p["work_id"]] for p in paper_order(a) if p["work_id"] in state]
        ok = [r for r in results if r.status == "ok"]
        ok = [r for r in ok if seen_hash.get(r.sha, a["author_id"]) == a["author_id"]][:max_ok]
        if len(ok) < min_ok:
            # logged as dropped only when truly hopeless; an author interrupted mid-run is neither
            if results and decide(len(ok), len(results), len(a["papers"]), min_ok, max_ok) == "abandon":
                dropped.append({"author_id": a["author_id"], "n_candidates": a["n_candidates"],
                                "tried": len(results), "usable": len(ok),
                                "reason": "fewer than %d usable papers" % min_ok})
            continue
        meta = {p["work_id"]: p for p in a["papers"]}
        for r in ok:
            seen_hash.setdefault(r.sha, a["author_id"])
            m = meta[r.work_id]
            papers.append(ScholarlyPaper(
                source="openalex", source_paper_id=r.work_id, author_id=a["author_id"],
                year=m["year"], field=m["field"], licence=m["licence"], url=m["url"],
                word_count=r.words, text_sha256=r.sha, partition=policy.partition_of(a["author_id"])))
    papers.sort(key=lambda p: (p.author_id, p.source_paper_id))
    manifest = ScholarlyManifest(collection=collection, created_at=time.strftime("%Y-%m-%d"), papers=papers)
    return manifest, dropped


def run(collection: str, cache: Path, limit_authors: int, start_rank: int, workers: int,
        max_papers: int, partitions: List[str], out_dir: Path) -> dict:
    cand = json.loads((HERE / "candidates" / f"{collection}.json").read_text(encoding="utf-8"))
    authors = [a for a in cand["authors"] if a["rank"] > start_rank and a["partition"] in partitions][:limit_authors]
    state_path = cache / collection / "state.jsonl"
    state = load_state(state_path)
    writer = StateWriter(state_path)
    fetcher = Fetcher(collection, cache)
    outcomes: List[AuthorOutcome] = []

    def work(a: dict) -> AuthorOutcome:
        return process_author(a, lambda p: fetcher(p, a["author_id"]), state, writer, max_ok=max_papers)

    t0 = time.time()
    all_authors = [a for a in cand["authors"]]

    def write_manifest():
        # covers every author with state, not only this run's slice; rewritten as the run
        # progresses so an interrupted run still leaves a valid, complete-authors-only manifest
        seen = [a for a in all_authors if any(p["work_id"] in state for p in a["papers"])]
        m, d = build_manifest(collection, seen, state, max_ok=max_papers)
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / f"{collection}.json").write_text(m.model_dump_json(indent=None) + "\n", encoding="utf-8")
        (out_dir / f"{collection}_dropped.json").write_text(json.dumps(d, separators=(",", ":")) + "\n", encoding="utf-8")
        return m, d

    with ThreadPoolExecutor(max_workers=workers) as ex:
        for i, o in enumerate(ex.map(work, authors), 1):
            outcomes.append(o)
            for r in o.results:
                state.setdefault(r.work_id, r)
            if i % 10 == 0:
                print(f"  {i}/{len(authors)} authors, {sum(x.status == 'usable' for x in outcomes)} usable", flush=True)
            if i % 100 == 0:
                write_manifest()
    manifest, dropped = write_manifest()
    return {"authors_run": len(authors), "usable_this_run": sum(o.status == "usable" for o in outcomes),
            "abandoned_this_run": sum(o.status == "abandoned" for o in outcomes),
            "manifest_authors": len(manifest.authors()), "manifest_papers": len(manifest.papers),
            "dropped_total": len(dropped), "seconds": round(time.time() - t0)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--collection", choices=("humanities", "science"), required=True)
    ap.add_argument("--limit-authors", type=int, default=50)
    ap.add_argument("--start-rank", type=int, default=0, help="skip authors ranked at or above this rank")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--max-papers", type=int, default=policy.MAX_USABLE_PAPERS)
    ap.add_argument("--partitions", nargs="+", default=list(policy.PARTITIONS), choices=policy.PARTITIONS)
    ap.add_argument("--cache", type=Path, default=DEFAULT_CACHE)
    ap.add_argument("--out-dir", type=Path, default=HERE / "manifest")
    a = ap.parse_args(argv)
    print(json.dumps(run(a.collection, a.cache, a.limit_authors, a.start_rank, a.workers,
                         a.max_papers, a.partitions, a.out_dir), indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
