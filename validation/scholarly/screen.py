"""Metadata-only author screen. Downloads no paper.

    python -m validation.scholarly.screen --collection humanities
    python -m validation.scholarly.screen --collection science

Enumerates single-author OpenAlex works in the collection's fields, keeps the
ones that pass the per-paper metadata rules (``openalex.compact_work``), groups
them by OpenAlex author id, applies the wrong-author-merge guards
(``openalex.author_verdict``), keeps authors with at least
``policy.MIN_SCREEN_CANDIDATES`` candidates, ranks them by candidate count, and
writes ``candidates/<collection>.json``. That file is the reviewable screen;
``fetch.py`` reads it and never queries OpenAlex.

OpenAlex needs an API key for cursor paging (free; see docs/research/
2026-11-11-scholarly-corpus-sources.md). Set OPENALEX_API_KEY, or run where the
network layer injects one.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import policy
from .openalex import OpenAlexClient, author_verdict, compact_work, post_rules

HERE = Path(__file__).resolve().parent

# OpenAlex "fields". Humanities = Arts and Humanities. Science = the natural and
# formal sciences (no medicine, no social science): the two are never mixed.
COLLECTION_FIELDS = {
    "humanities": ["12"],
    "science": ["11", "13", "15", "16", "17", "19", "21", "22", "23", "24", "25", "26", "28", "30", "31"],
}
_LIC = "|".join(sorted(policy.PERMITTED_LICENCES))


def passes(collection: str, year: int) -> list[str]:
    """OpenAlex filters, one per pass, for one publication year."""
    fields = "|".join(COLLECTION_FIELDS[collection])
    base = (f"authors_count:1,language:en,has_orcid:true,is_paratext:false,is_retracted:false,"
            f"primary_topic.field.id:{fields},publication_year:{year}")
    out = [f"{base},type:article,best_oa_location.license:{_LIC},primary_location.source.type:journal"]
    if collection == "science":  # arXiv: research-use terms, any licence
        out.append(f"{base},type:article|preprint,locations.source.id:{policy.ARXIV_SOURCE_ID}")
    return out


def scan_year(client: OpenAlexClient, collection: str, year: int, ckpt: Path) -> tuple[dict, Counter]:
    """One year's candidates. Each (pass, year) is checkpointed to ``ckpt`` (git-ignored) so a
    crash or an exhausted budget never throws away paid-for requests."""
    by_author: dict[str, dict[str, dict]] = defaultdict(dict)
    stats: Counter = Counter()
    for k, filt in enumerate(passes(collection, year)):
        f = ckpt / f"{collection}_{year}_{k}.json"
        if f.exists():
            saved = json.loads(f.read_text(encoding="utf-8"))
        else:
            kept, scanned = [], 0
            for w in client.iter_works(filt):
                scanned += 1
                c = compact_work(w)
                if c is not None:
                    kept.append(c)
            saved = {"scanned": scanned, "kept": kept}
            ckpt.mkdir(parents=True, exist_ok=True)
            f.write_text(json.dumps(saved, separators=(",", ":"), ensure_ascii=False), encoding="utf-8")
        kept = [c for c in saved["kept"] if post_rules(c, collection)]
        stats["works_scanned"] += saved["scanned"]
        stats["works_failed_paper_rules"] += saved["scanned"] - len(kept)
        for c in kept:
            by_author[c["author_id"]][c["work_id"]] = c
    return by_author, stats


CKPT = HERE / "cache" / "screen"


def build(collection: str, years: range, workers: int, keep_top: int = 0, max_listed: int = 0) -> dict:
    client = OpenAlexClient(api_key=os.environ.get("OPENALEX_API_KEY") or None)
    merged: dict[str, dict[str, dict]] = defaultdict(dict)
    stats: Counter = Counter()
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for by_author, st in ex.map(lambda y: scan_year(client, collection, y, CKPT), years):
            stats.update(st)
            for aid, works in by_author.items():
                merged[aid].update(works)
    kept, reasons = [], Counter()
    for aid, works in merged.items():
        ok, why, papers = author_verdict(list(works.values()))
        reasons[why] += 1
        if not ok:
            continue
        subs = Counter(p["subfield"] for p in papers if p.get("subfield"))
        yrs = [p["year"] for p in papers if p.get("year")]
        n_candidates = len(papers)
        if max_listed and len(papers) > max_listed:  # list non-arXiv papers first, then a hash order
            papers = sorted(papers, key=lambda p: (p["host"] == "arXiv",
                                                   hashlib.sha256(p["work_id"].encode()).hexdigest()))[:max_listed]
            papers.sort(key=lambda p: (p.get("year") or 0, p["work_id"]))
        kept.append({
            "author_id": aid,
            "name": papers[0]["author_name"],
            "orcid": papers[0]["orcids"][0],
            "n_candidates": n_candidates,
            "years": [min(yrs), max(yrs)] if yrs else None,
            "subfields": dict(subs.most_common()),
            "partition": policy.partition_of(aid),
            "papers": [{k: p[k] for k in ("work_id", "title", "year", "pages", "licence", "url", "field")}
                       for p in papers],
        })
    kept.sort(key=lambda a: (-a["n_candidates"], a["author_id"]))
    for i, a in enumerate(kept, 1):
        a["rank"] = i
    total_kept = len(kept)
    if keep_top:  # the committed list holds the top of the ranking only (size); ranks are unchanged
        kept = kept[:keep_top]
    return {
        "meta": {
            "collection": collection,
            "policy_version": policy.POLICY_VERSION,
            "screened_on": time.strftime("%Y-%m-%d"),
            "source": "OpenAlex works API (CC0), cursor-paged; no full text downloaded",
            "fields": COLLECTION_FIELDS[collection],
            "years": [years.start, years.stop - 1],
            "min_candidates": policy.MIN_SCREEN_CANDIDATES,
            "requests": client.requests,
            "seconds": round(time.time() - t0),
            "funnel": {
                "works_scanned": stats["works_scanned"],
                "works_failed_paper_rules": stats["works_failed_paper_rules"],
                "authors_with_any_candidate": len(merged),
                "author_verdicts": dict(reasons),
                "authors_kept": total_kept,
                "authors_listed": len(kept),
                "candidate_papers_listed": sum(len(a["papers"]) for a in kept),
            },
        },
        "authors": kept,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--collection", choices=sorted(COLLECTION_FIELDS), required=True)
    ap.add_argument("--first-year", type=int, default=1995)
    ap.add_argument("--last-year", type=int, default=int(time.strftime("%Y")))
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--out", type=Path, default=None)
    ap.add_argument("--max-listed", type=int, default=0, help="list at most N papers per author (n_candidates stays the true count)")
    ap.add_argument("--keep-top", type=int, default=0, help="write only the top N ranked authors")
    a = ap.parse_args(argv)
    result = build(a.collection, range(a.first_year, a.last_year + 1), a.workers, a.keep_top, a.max_listed)
    out = a.out or HERE / "candidates" / f"{a.collection}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, separators=(",", ":"), ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(result["meta"], indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
