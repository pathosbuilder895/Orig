"""Build a real-author, topic-disjoint verification corpus from PAN 2020.

PAN is distributed as independent verification pairs.  This builder uses the
author IDs released in the truth file to recover genuine author histories; it
does not join pair-local text nodes into pseudo-authors or invent labels.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from validation.manifest_schema import AIProvider, AuthorshipLabel
from validation.wide._adapter import WideEntry, materialize


ZENODO_RECORD = "5106099"
ZENODO_DOI = "10.5281/zenodo.5106099"
ARCHIVE_NAME = "pan20-authorship-verification-test.zip"
ARCHIVE_MD5 = "655f365ab7b736036bbbee717168012b"
DEFAULT_CACHE = Path(__file__).resolve().parents[2] / ".benchmark_cache" / "pan" / "2020"


@dataclass(frozen=True)
class _Document:
    text: str
    fandom: str
    pair_id: str
    text_sha256: str


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _discover(cache_dir: Path) -> tuple[Path, Path]:
    pairs = sorted(cache_dir.glob("**/*test.jsonl"))
    truth = sorted(cache_dir.glob("**/*truth.jsonl"))
    if len(pairs) != 1 or len(truth) != 1:
        raise FileNotFoundError(
            f"Expected one PAN pair file and one truth file under {cache_dir}; "
            f"found pairs={len(pairs)}, truth={len(truth)}"
        )
    return pairs[0], truth[0]


def _load_histories(pairs_path: Path, truth_path: Path, min_text_chars: int) -> dict[str, list[_Document]]:
    truth = {}
    with truth_path.open(encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            truth[row["id"]] = row

    histories: dict[str, dict[str, _Document]] = defaultdict(dict)
    seen_pairs = set()
    with pairs_path.open(encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            pair_id = row["id"]
            if pair_id in seen_pairs:
                raise ValueError(f"Duplicate PAN pair id: {pair_id}")
            seen_pairs.add(pair_id)
            target = truth.get(pair_id)
            if target is None:
                raise ValueError(f"PAN pair {pair_id} has no truth row")
            texts, fandoms, authors = row.get("pair", []), row.get("fandoms", []), target.get("authors", [])
            if not (len(texts) == len(fandoms) == len(authors) == 2):
                raise ValueError(f"Malformed PAN pair/truth row: {pair_id}")
            if bool(target.get("same")) != (authors[0] == authors[1]):
                raise ValueError(f"PAN label and author IDs disagree: {pair_id}")
            for text, fandom, author in zip(texts, fandoms, authors):
                if len(text) < min_text_chars:
                    continue
                text_hash = _digest(text)
                histories[str(author)].setdefault(
                    text_hash,
                    _Document(text, str(fandom), pair_id, text_hash),
                )
    return {author: list(documents.values()) for author, documents in histories.items()}


def _stable_order(values: Iterable[str], namespace: str) -> list[str]:
    return sorted(values, key=lambda value: (_digest(f"{namespace}:{value}"), value))


def _fixed_window(text: str, max_words: int, seed: str) -> str:
    """Return a deterministic bounded window without favoring story openings."""
    words = text.split()
    if len(words) <= max_words:
        return text
    start = int(_digest(seed)[:16], 16) % (len(words) - max_words + 1)
    return " ".join(words[start : start + max_words])


def build_corpus(
    *,
    corpus_dir: Path,
    manifest_path: Path,
    cache_dir: Path = DEFAULT_CACHE,
    author_count: int = 12,
    baselines: int = 3,
    probes: int = 3,
    min_text_chars: int = 800,
    max_words: int = 2500,
) -> dict:
    """Materialize deterministic authors with disjoint baseline/probe fandoms."""
    if author_count < 2 or baselines < 1 or probes < 1:
        raise ValueError("author_count must be >=2 and baseline/probe counts must be positive")
    pairs_path, truth_path = _discover(cache_dir)
    histories = _load_histories(pairs_path, truth_path, min_text_chars)

    eligible = {}
    for author, documents in histories.items():
        by_fandom: dict[str, list[_Document]] = defaultdict(list)
        for document in documents:
            by_fandom[document.fandom].append(document)
        usable = {f: ds for f, ds in by_fandom.items() if len(ds) >= max(baselines, probes)}
        if len(usable) >= 2:
            eligible[author] = usable
    chosen = _stable_order(eligible, f"pan20-authors:{ZENODO_RECORD}")[:author_count]
    if len(chosen) < author_count:
        raise RuntimeError(f"Requested {author_count} authors but only {len(chosen)} are eligible")

    entries = []
    author_meta = {}
    all_hashes = set()
    for raw_author in chosen:
        public_author = f"pan20_{_digest(f'{ZENODO_RECORD}:{raw_author}')[:12]}"
        fandoms = _stable_order(eligible[raw_author], f"pan20-fandoms:{raw_author}")[:2]
        baseline_fandom, probe_fandom = fandoms
        baseline_docs = sorted(eligible[raw_author][baseline_fandom], key=lambda d: d.text_sha256)[:baselines]
        probe_docs = sorted(eligible[raw_author][probe_fandom], key=lambda d: d.text_sha256)[:probes]
        selected = [(d, True) for d in baseline_docs] + [(d, False) for d in probe_docs]
        for document, is_baseline in selected:
            if document.text_sha256 in all_hashes:
                raise ValueError("A PAN text was assigned to more than one author")
            all_hashes.add(document.text_sha256)
            window = _fixed_window(document.text, max_words, document.text_sha256)
            window_hash = _digest(window)
            entries.append(
                WideEntry(
                    author_id=public_author,
                    label=AuthorshipLabel.AUTHENTIC,
                    text=window,
                    prompt=document.fandom,
                    is_baseline=is_baseline,
                    ai_provider=AIProvider.NONE,
                    source_id=document.pair_id,
                    notes=(
                        f"PAN 2020 pair={document.pair_id}; source_text_sha256={document.text_sha256}; "
                        f"window_sha256={window_hash}; max_words={max_words}; "
                        f"role={'baseline' if is_baseline else 'probe'}; fandom={document.fandom}"
                    ),
                )
            )
        author_meta[public_author] = {
            "source": "PAN 2020 authorship verification test",
            "zenodo_doi": ZENODO_DOI,
            "baseline_fandom": baseline_fandom,
            "probe_fandom": probe_fandom,
            "topic_disjoint": baseline_fandom != probe_fandom,
            "selection": "deterministic SHA-256 ordering",
        }

    stats = materialize(
        entries,
        corpus_dir=corpus_dir,
        manifest_path=manifest_path,
        description="PAN 2020 real-author, cross-fandom authorship verification corpus",
        min_baseline_per_author=baselines,
        min_scoring_per_author=probes,
        author_meta=author_meta,
    )
    stats.update(
        {
            "eligible_authors": len(eligible),
            "topic_disjoint_authors": sum(m["topic_disjoint"] for m in author_meta.values()),
            "unique_text_sha256": len(all_hashes),
            "zenodo_record": ZENODO_RECORD,
            "zenodo_doi": ZENODO_DOI,
            "archive_name": ARCHIVE_NAME,
            "archive_md5": ARCHIVE_MD5,
            "max_words_per_document": max_words,
        }
    )
    return stats
