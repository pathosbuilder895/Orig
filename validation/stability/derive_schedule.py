"""
derive_schedule.py — re-derive LENGTH_WEIGHT_SCHEDULE from a per-tier
stability summary.

Implements the exact recipe documented in the
original/constants.py::LENGTH_WEIGHT_SCHEDULE comment block:

  short  : F(500, tier) / median(F(500, ·) over measurable tiers),
           clipped to [0.5, 2.0].
  medium : midpoint of the clipped short factor and 1.0 (halfway back
           toward the identity used at "long").
  long   : identity (1.0 everywhere) — never derived.

  Tiers with no measurable text-only features (11, 12 — flag "n/a")
  take the 0.5 floor ("mute heavily"); tiers absent from the study
  (0 comparison, 17 behavioral) take a neutral 1.0 raw factor.

  Each bucket is then rescaled by a single scalar so that
  sum((TIER_WEIGHTS × factor)²) across the FEATURE_DIM features equals
  sum(TIER_WEIGHTS²) — Σ(w²)-preservation. This means the flag cannot
  inflate or deflate the tanh-calibrated rms_z on average; it only
  redistributes weight across tiers. (The mean-normalisation step the
  old comment describes is absorbed by this rescale: composing
  "divide by the mean" with "rescale to satisfy Σ(w²)" yields the
  same final factors as rescaling the raw clipped factors directly.)

Usage:
    .venv/bin/python -m validation.stability.derive_schedule \
        validation/stability/2026-08-01/per_tier_summary.csv

Validate the recipe against the committed 2026-06-30 factors first:
    .venv/bin/python -m validation.stability.derive_schedule \
        validation/stability/2026-06-30/per_tier_summary.csv --check-against-constants
"""

from __future__ import annotations

import argparse
import csv
import statistics
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_ROOT))

from original.constants import (  # noqa: E402
    ALL_FEATURE_CODES,
    FEATURE_TIER,
    LENGTH_WEIGHT_SCHEDULE,
    TIER_WEIGHTS,
)

CLIP_LO, CLIP_HI = 0.5, 2.0
ALL_TIERS = sorted(TIER_WEIGHTS)  # 0..17

# Features per tier, from the canonical feature list (Σ = FEATURE_DIM).
N_FEATURES_BY_TIER = {
    t: sum(1 for c in ALL_FEATURE_CODES if FEATURE_TIER.get(c, 0) == t)
    for t in ALL_TIERS
}


def read_f500(csv_path: Path) -> dict[int, float | None]:
    """Return tier → mean F(500), None for 'n/a' tiers (no measurable features)."""
    out: dict[int, float | None] = {}
    with csv_path.open() as fh:
        for row in csv.DictReader(fh):
            tier = int(row["tier"])
            out[tier] = None if row["flag"] == "n/a" else float(row["mean_F_500"])
    return out


def raw_short_factors(f500: dict[int, float | None]) -> dict[int, float]:
    measurable = [v for v in f500.values() if v is not None and v > 0]
    med = statistics.median(measurable)
    raw: dict[int, float] = {}
    for t in ALL_TIERS:
        if t not in f500:            # tier absent from the study (0, 17)
            raw[t] = 1.0
        elif f500[t] is None or f500[t] == 0:   # "n/a" — mute heavily
            raw[t] = CLIP_LO
        else:
            raw[t] = min(CLIP_HI, max(CLIP_LO, f500[t] / med))
    return raw


def sum_w2_rescale(raw: dict[int, float]) -> float:
    """Scalar s such that factors raw/s preserve Σ(w²) over the FEATURE_DIM features."""
    num = sum(
        N_FEATURES_BY_TIER[t] * (TIER_WEIGHTS[t] * raw[t]) ** 2 for t in ALL_TIERS
    )
    den = sum(N_FEATURES_BY_TIER[t] * TIER_WEIGHTS[t] ** 2 for t in ALL_TIERS)
    return (num / den) ** 0.5


def derive(csv_path: Path) -> dict[str, dict[int, float]]:
    f500 = read_f500(csv_path)
    short_raw = raw_short_factors(f500)
    medium_raw = {t: (v + 1.0) / 2.0 for t, v in short_raw.items()}

    schedule: dict[str, dict[int, float]] = {}
    for bucket, raw in (("short", short_raw), ("medium", medium_raw)):
        s = sum_w2_rescale(raw)
        schedule[bucket] = {t: round(raw[t] / s, 2) for t in ALL_TIERS}
        print(f"# {bucket}: Σ(w²)-preserving rescale = 1 / {s:.4f}", file=sys.stderr)
    schedule["long"] = {t: 1.0 for t in ALL_TIERS}
    return schedule


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("csv_path", type=Path)
    p.add_argument(
        "--check-against-constants",
        action="store_true",
        help="Compare derived factors with the committed LENGTH_WEIGHT_SCHEDULE "
        "(use with the CSV the committed schedule was derived from).",
    )
    args = p.parse_args()

    schedule = derive(args.csv_path)

    for bucket in ("short", "medium"):
        print(f'    "{bucket}": {{')
        for t in ALL_TIERS:
            print(f"        {t}: {schedule[bucket][t]:.2f},")
        print("    },")

    if args.check_against_constants:
        worst = 0.0
        for bucket in ("short", "medium"):
            for t in ALL_TIERS:
                got, want = schedule[bucket][t], LENGTH_WEIGHT_SCHEDULE[bucket][t]
                diff = abs(got - want)
                worst = max(worst, diff)
                marker = "" if diff <= 0.011 else "   <-- MISMATCH"
                print(
                    f"check {bucket:6s} tier {t:2d}: derived {got:.2f} "
                    f"committed {want:.2f}{marker}",
                    file=sys.stderr,
                )
        print(f"check: max |derived - committed| = {worst:.3f}", file=sys.stderr)
        return 0 if worst <= 0.011 else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
