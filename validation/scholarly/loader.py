"""Trials from the scholarly corpus, in the shape the existing harnesses use.

``ScholarlyTrial`` carries ``student_id``, ``baseline`` (past papers) and
``honest`` (held-out new papers) like ``validation/short_regime/corpus.Trial``,
plus ``probes``: other-author texts cut to the same length as the new papers.

Guarantees:
  * An author with fewer than ``policy.MIN_USABLE_PAPERS`` usable papers is
    refused (``ThinAuthorError``); it can never enter a trial silently.
  * No document is on both sides: a paper is a past paper or a new paper, never
    both, and a probe is another author's paper.
  * The ``locked_test`` partition cannot be loaded without naming a
    pre-registered study; the opening is appended to ``LOCKED_OPENINGS.tsv``.
"""
from __future__ import annotations

import hashlib
import json
import random
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

from . import policy
from .schema import ScholarlyManifest, ScholarlyPaper

HERE = Path(__file__).resolve().parent
LOCKED_LOG = HERE / "LOCKED_OPENINGS.tsv"


class ThinAuthorError(ValueError):
    """An author has too few usable papers (or cached texts) for a complete test."""


class LockedPartitionError(PermissionError):
    """The locked_test partition was requested without a pre-registered study id."""


@dataclass(frozen=True)
class ScholarlyTrial:
    student_id: str
    baseline: List[str]            # past papers, cut to past_words
    honest: List[str]              # held-out new papers by the same author, cut to new_words
    probes: List[str]              # other authors' papers, cut to new_words
    baseline_ids: List[str] = field(default_factory=list)
    honest_ids: List[str] = field(default_factory=list)
    probe_sources: List[str] = field(default_factory=list)   # author id of each probe


@dataclass
class TrialSet:
    trials: List[ScholarlyTrial]
    skipped: Dict[str, str]        # author id -> why no trial was built (never silent)


def load_manifest(collection: str, manifest_dir: Optional[Path] = None) -> ScholarlyManifest:
    path = (manifest_dir or HERE / "manifest") / f"{collection}.json"
    return ScholarlyManifest.model_validate_json(path.read_text(encoding="utf-8"))


def _rank(seed: int, key: str) -> str:
    return hashlib.sha256(f"{seed}:{key}".encode()).hexdigest()


def cut_words(text: str, n: int, rng: random.Random) -> str:
    """``n`` consecutive words starting at a paragraph boundary (seeded).

    Raises ValueError when the text has fewer than ``n`` words.
    """
    paras = [p for p in text.split("\n\n") if p.strip()]
    total = sum(len(p.split()) for p in paras)
    if total < n:
        raise ValueError(f"text has {total} words, fewer than the {n} requested")
    starts = []
    left = total
    for i, p in enumerate(paras):
        if left >= n:
            starts.append(i)
        left -= len(p.split())
    i = rng.choice(starts)
    words = " ".join(paras[i:]).split()
    return " ".join(words[:n])


def _read(cache: Path, collection: str, p: ScholarlyPaper) -> str:
    f = cache / collection / "texts" / p.author_id / f"{p.source_paper_id}.txt"
    if not f.exists():
        raise ThinAuthorError(f"cached text missing for {p.author_id}/{p.source_paper_id}; rerun fetch.py")
    text = f.read_text(encoding="utf-8")
    if hashlib.sha256(text.encode("utf-8")).hexdigest() != p.text_sha256:
        raise ThinAuthorError(f"cache for {p.author_id}/{p.source_paper_id} does not match the manifest hash")
    return text


def _open_locked(collection: str, study: Optional[str]) -> None:
    if not study or not study.strip():
        raise LockedPartitionError(
            "locked_test is opened once per pre-registered study: pass allow_locked_for='<study id>'")
    with LOCKED_LOG.open("a", encoding="utf-8") as f:
        f.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S')}\t{collection}\t{study.strip()}\n")


def load_trials(collection: str, partition: str, *, n_past: int = 4, n_new: int = 2,
                past_words: int = 1200, new_words: int = 300, n_probes: int = 5, seed: int = 7,
                manifest: Optional[ScholarlyManifest] = None, cache: Optional[Path] = None,
                max_authors: Optional[int] = None, allow_locked_for: Optional[str] = None,
                _opening_logged: bool = False) -> TrialSet:
    """Build trials for the authors of one partition.

    Authors that cannot supply ``n_past + n_new`` papers long enough for the
    requested cuts are reported in ``TrialSet.skipped`` with the reason.
    """
    if partition not in policy.PARTITIONS:
        raise ValueError(f"partition must be one of {policy.PARTITIONS}")
    if partition == "locked_test" and not _opening_logged:
        _open_locked(collection, allow_locked_for)
    if n_past + n_new < 2 or n_past < 1 or n_new < 1:
        raise ValueError("need at least one past and one new paper")
    if n_past + n_new > policy.MAX_USABLE_PAPERS:
        raise ValueError("n_past + n_new exceeds the per-author paper cap")
    manifest = manifest or load_manifest(collection)
    if cache is None:
        from .fetch import DEFAULT_CACHE
        cache = DEFAULT_CACHE
    by_author = manifest.authors()
    ids = manifest.authors_in(partition)
    if max_authors is not None:
        ids = sorted(ids, key=lambda a: _rank(seed, a))[:max_authors]

    trials: List[ScholarlyTrial] = []
    skipped: Dict[str, str] = {}
    for aid in ids:
        papers = by_author[aid]
        if len(papers) < policy.MIN_USABLE_PAPERS:
            raise ThinAuthorError(f"author {aid} has {len(papers)} usable papers; "
                                  f"the floor is {policy.MIN_USABLE_PAPERS}")
        try:
            texts = {p.source_paper_id: _read(cache, collection, p) for p in papers}
        except ThinAuthorError as e:   # a rotted link or stale cache costs this author, not the run
            skipped[aid] = f"unusable cache: {e}"
            continue
        order = sorted(papers, key=lambda p: _rank(seed, p.source_paper_id))
        rng = random.Random(_rank(seed, aid))
        past = [p for p in order if p.word_count >= past_words][:n_past]
        rest = [p for p in order if p not in past and p.word_count >= new_words]
        new = rest[:n_new]
        if len(past) < n_past or len(new) < n_new:
            skipped[aid] = (f"cannot cut {n_past} past papers of {past_words} words and "
                            f"{n_new} new papers of {new_words} words from its {len(papers)} papers")
            continue
        trials.append(ScholarlyTrial(
            student_id=aid,
            baseline=[cut_words(texts[p.source_paper_id], past_words, rng) for p in past],
            honest=[cut_words(texts[p.source_paper_id], new_words, rng) for p in new],
            probes=[], baseline_ids=[p.source_paper_id for p in past],
            honest_ids=[p.source_paper_id for p in new]))

    # other-author probes: another author's held-out new paper, never the same author
    final: List[ScholarlyTrial] = []
    for t in trials:
        others = sorted((o for o in trials if o.student_id != t.student_id),
                        key=lambda o: _rank(seed, f"{t.student_id}>{o.student_id}"))[:n_probes]
        final.append(ScholarlyTrial(
            t.student_id, t.baseline, t.honest, [o.honest[0] for o in others],
            t.baseline_ids, t.honest_ids, [o.student_id for o in others]))
    return TrialSet(final, skipped)


def load_trial_grid(collection: str, partition: str, grid, *, allow_locked_for: Optional[str] = None,
                    **kwargs) -> Dict[tuple, TrialSet]:
    """Every (config name, past words, new words, seed) trial set of one partition, opened ONCE.

    ``grid`` is an iterable of (name, past_words, new_words, seed). For ``locked_test`` the
    pre-registered study id is checked and the opening is logged exactly once for the whole
    grid, so one study run leaves one line per collection in ``LOCKED_OPENINGS.tsv``."""
    grid = list(grid)
    if partition == "locked_test":
        _open_locked(collection, allow_locked_for)
    return {(name, seed): load_trials(collection, partition, past_words=pw, new_words=nw, seed=seed,
                                      allow_locked_for=allow_locked_for, _opening_logged=True, **kwargs)
            for name, pw, nw, seed in grid}
