"""Assemble operating-point trials from the committed validation corpus.

One author = one pseudo-student. Baseline and honest chunks are disjoint
slices of the author's concatenated text. Impostor scoring is done by the
runner (author A's honest chunks scored against author B's baseline), so
this module only produces same-author material plus labeled attack probes.
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from pathlib import Path

SEMINARY = [f"seminary_{i:02d}" for i in range(1, 6)]
BIG_AUTHORS = ["burke", "douglass", "lincoln", "paine"]


@dataclass(frozen=True)
class Trial:
    student_id: str
    baseline: list[str]
    honest: list[str]


def _chunks(text: str, words: int) -> list[str]:
    w = text.split()
    return [
        " ".join(w[i : i + words])
        for i in range(0, len(w) - words + 1, words)
    ]


def _author_text(corpus_dir: Path, prefix: str) -> str:
    files = sorted(corpus_dir.glob(f"{prefix}_*.txt"))
    return "\n".join(f.read_text(encoding="utf-8") for f in files)


def build_pools(corpus_dir: Path, words: int = 500) -> dict[str, list[str]]:
    pools: dict[str, list[str]] = {}
    for author in SEMINARY + BIG_AUTHORS:
        cs = _chunks(_author_text(corpus_dir, author), words)
        if len(cs) >= 3:  # baseline-only OK; serve as impostor/attack targets
            pools[author] = cs
    return pools


def build_trials(
    pools: dict[str, list[str]],
    n_baseline: int = 3,
    max_honest: int = 30,
    seed: int = 7,
) -> list[Trial]:
    trials = []
    for author in sorted(pools):
        cs = pools[author]
        rng = random.Random(f"{seed}:{author}")
        idx = list(range(len(cs)))
        rng.shuffle(idx)
        base_idx = idx[:n_baseline]
        honest_idx = idx[n_baseline : n_baseline + max_honest]
        trials.append(
            Trial(
                student_id=author,
                baseline=[cs[i] for i in base_idx],
                honest=[cs[i] for i in honest_idx],
            )
        )
    return trials


def attack_probes(corpus_dir: Path, words: int = 500) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for kind in ("ai", "ghost"):
        text = _author_text(corpus_dir, kind)
        out[kind] = _chunks(text, words)
    return out
