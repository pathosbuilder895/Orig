"""
Read a production shadow log and report what GENRE_RESOLVER_V2 would change.

Run:
    render logs --tail 100000 | .venv/bin/python validation/genre_2026-08/read_shadow_log.py
    .venv/bin/python validation/genre_2026-08/read_shadow_log.py path/to/app.log

This exists to answer the one question no corpus can. Every number reported
for the genre classifier so far — 1.000 minimum per-class precision, 33.3%
abstention, G8 passing — was measured on 19th-century published prose plus 25
seminary papers. The rollout waits on a different question: **what fraction
of REAL student submissions does v2 abstain on?**

If pilot `d` clusters heavily in `unknown`, the three-class set is wrong for
student writing and no amount of corpus performance rescues it. That is the
trap GENRE_INVARIANT_WEIGHTS_ENABLED fell into — built, tested, and unable to
fire — and the reason the spec says to run shadow first.

Shadow is inert: `primary` still comes from v1, so nothing downstream moves.
It only writes one INFO line per resolver call:

    genre_shadow v1=<label> v2=<label> v2_confidence=<float>

To collect it, set GENRE_RESOLVER_V2=shadow on the deployment and let normal
traffic run. Every baseline ingestion and every scored submission emits a
line (students_baseline.py and students_scoring.py both call resolve_genre).
"""

from __future__ import annotations

import re
import sys
from collections import Counter
from pathlib import Path

# Anchored on `genre_shadow` rather than on line start: Render prefixes each
# line with a timestamp and stream name, and pytest's caplog does not.
_LINE_RE = re.compile(
    r"genre_shadow\s+v1=(?P<v1>\S+)\s+v2=(?P<v2>\S+)\s+v2_confidence=(?P<conf>[0-9.]+)"
)


def parse_line(line: str) -> tuple[str, str, float] | None:
    """`(v1_label, v2_label, v2_confidence)`, or None for any other line."""
    match = _LINE_RE.search(line or "")
    if not match:
        return None
    try:
        confidence = float(match.group("conf"))
    except ValueError:
        return None
    return match.group("v1"), match.group("v2"), confidence


def summarise(lines) -> dict:
    """
    Label distributions, the v1->v2 shift matrix, and the abstention rate.

    Deliberately the same shape as measure_shadow.summarise, so the pilot
    number and the corpus number can be read side by side.
    """
    import statistics

    from original.constants import GENRE_UNKNOWN

    v1_counts: Counter = Counter()
    v2_counts: Counter = Counter()
    shift: Counter = Counter()
    claimed_confidence: list[float] = []
    n = 0

    for line in lines:
        parsed = parse_line(line)
        if parsed is None:
            continue
        v1, v2, confidence = parsed
        v1_counts[v1] += 1
        v2_counts[v2] += 1
        shift[f"{v1} -> {v2}"] += 1
        if v2 != GENRE_UNKNOWN:
            claimed_confidence.append(confidence)
        n += 1

    return {
        "n": n,
        # A zero abstention rate means "shadow ran and always claimed" only
        # if shadow ran at all. Without this flag the two are indistinguishable
        # in the headline number, and only one of them is a measurement.
        "no_shadow_lines_found": n == 0,
        "v1_distribution": dict(v1_counts),
        "v2_distribution": dict(v2_counts),
        "abstention_rate": (v2_counts[GENRE_UNKNOWN] / n) if n else 0.0,
        "shift_matrix": dict(shift),
        "claimed_confidence_median": (
            statistics.median(claimed_confidence) if claimed_confidence else None
        ),
        "n_claimed": len(claimed_confidence),
    }


def main() -> int:
    _ROOT = Path(__file__).resolve().parent.parent.parent
    sys.path.insert(0, str(_ROOT))

    if len(sys.argv) > 1:
        lines = Path(sys.argv[1]).read_text(errors="ignore").splitlines()
    else:
        lines = sys.stdin.read().splitlines()

    out = summarise(lines)
    if out["no_shadow_lines_found"]:
        print(
            "No `genre_shadow` lines found.\n\n"
            "This is NOT an abstention rate of zero — it means shadow mode was "
            "not running, the log window does not cover it, or the log level "
            "excludes INFO. Set GENRE_RESOLVER_V2=shadow on the deployment and "
            "let traffic run before reading this."
        )
        return 1

    print(f"shadow observations: {out['n']}")
    print(f"v2 abstention rate:  {out['abstention_rate']:.1%}   "
          f"(claimed {out['n_claimed']})")
    if out["claimed_confidence_median"] is not None:
        print(f"median confidence on claimed labels: "
              f"{out['claimed_confidence_median']:.3f}")

    def _fmt(dist: dict) -> str:
        total = sum(dist.values()) or 1
        return ", ".join(
            f"{k}={v} ({v / total:.0%})"
            for k, v in sorted(dist.items(), key=lambda kv: -kv[1])
        )

    print("\nv1 (live):   " + _fmt(out["v1_distribution"]))
    print("v2 (shadow): " + _fmt(out["v2_distribution"]))
    print("\nlabel shifts:")
    for key, count in sorted(out["shift_matrix"].items(), key=lambda kv: -kv[1])[:20]:
        print(f"  {key:52s} {count}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
