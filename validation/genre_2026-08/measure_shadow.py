"""
What would GENRE_RESOLVER_V2 change?

Runs v1 and v2 over a corpus and reports the label-shift matrix and the
abstention rate. Stage 1 of
docs/superpowers/specs/2026-08-08-genre-resolution-design.md.

Run:
    .venv/bin/python validation/genre_2026-08/measure_shadow.py

The abstention rate is the number that decides whether Stage 2's five-class
set fits the traffic it will see. On the committed corpora it is expected to
be high — v1 puts 86% of documents in rule 8's terminal else, and v2 refuses
to inherit that guess. On real student submissions it is unknown until
shadow mode runs in the pilot, which is the whole reason shadow exists.

This measures the CORPUS, not production. It is not a substitute for the
pilot shadow run; it sizes the change before anyone turns the flag on.
"""

from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_ROOT))

from original.constants import GENRE_UNKNOWN  # noqa: E402
from original.context import genre_v2  # noqa: E402
from original.context.resolvers import _resolve_genre_v1  # noqa: E402

MIN_WORDS = 100


def summarise(paths) -> dict:
    """Label distributions under v1 and v2, plus the shift matrix between
    them. Documents under MIN_WORDS words are skipped: both resolvers key on
    per-sentence and per-word rates that are meaningless on a fragment."""
    v1_counts: Counter = Counter()
    v2_counts: Counter = Counter()
    shift: Counter = Counter()
    n = 0
    for path in paths:
        text = Path(path).read_text(errors="ignore")
        if len(text.split()) < MIN_WORDS:
            continue
        before = _resolve_genre_v1(text).get("primary")
        after = genre_v2.resolve(text).get("primary")
        v1_counts[before] += 1
        v2_counts[after] += 1
        shift[f"{before} -> {after}"] += 1
        n += 1
    return {
        "n": n,
        "v1_distribution": dict(v1_counts),
        "v2_distribution": dict(v2_counts),
        "abstention_rate": (v2_counts[GENRE_UNKNOWN] / n) if n else 0.0,
        "shift_matrix": dict(shift),
    }


def _corpus_paths() -> list[Path]:
    paths = sorted((_ROOT / "validation" / "corpus").glob("*.txt"))
    paths += sorted((_ROOT / "validation" / "public_authors" / "corpus").rglob("*.txt"))
    paths += sorted(
        (_ROOT / "validation" / "public_authors" / "cross_work_corpus").rglob("*.txt")
    )
    return paths


def main() -> None:
    out = summarise(_corpus_paths())
    print(f"documents scored: {out['n']}  (>= {MIN_WORDS} words)")
    print(f"v2 abstention rate: {out['abstention_rate']:.1%}\n")

    def _fmt(dist: dict) -> str:
        total = sum(dist.values()) or 1
        return ", ".join(
            f"{k}={v} ({v / total:.0%})"
            for k, v in sorted(dist.items(), key=lambda kv: -kv[1])
        )

    print("v1:", _fmt(out["v1_distribution"]))
    print("v2:", _fmt(out["v2_distribution"]))
    print("\nlabel shifts:")
    for key, count in sorted(out["shift_matrix"].items(), key=lambda kv: -kv[1]):
        print(f"  {key:52s} {count}")


if __name__ == "__main__":
    main()
