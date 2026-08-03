"""
validation/plato/calibration_probe.py — why does authentic text get flagged?

Every work in the Plato corpus scores between 0.54 and 0.76, including the
dialogues that BUILT the baseline. Nothing ever reaches ``no_action``. This
probe asks whether that is a property of the corpus or of the scoring scale.

The arithmetic under test
-------------------------
``score()`` computes, per submission::

    z        = (submission - baseline_mean) / baseline_std
    rms_z    = sqrt( sum( clip(z,-4,4) * tier_weight * active )^2 / n_active )
    deviation = tanh(rms_z / 1.5)

Inverting ``ACTION_THRESHOLDS`` through that tanh gives the rms_z each verdict
band actually requires::

    no_action              deviation < 0.40   ->  rms_z < 0.635
    monitor                          < 0.60   ->  rms_z < 1.040
    schedule_conversation            < 0.75   ->  rms_z < 1.462
    escalate                         >= 0.75  ->  rms_z >= 1.462

A submission drawn from the same distribution as its own baseline has
E[z^2] = 1, so its rms_z is approximately the root-mean-square tier weight —
about 1.15 for this feature set. That lands at deviation ~0.65, which is
``schedule_conversation``. If that holds empirically, then a perfectly
authentic sample is expected to be flagged, and the finding is about the scale
rather than about Plato.

Three tests, in increasing order of favourability to the system:

  A. leave-one-out WITHIN a single dialogue — baseline is the other chunks of
     the very same work. The most authentic case that can exist.
  B. leave-one-out against the three-dialogue early baseline.
  C. the spurious Eryxias, for contrast.

    python -m validation.plato.calibration_probe
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, List

import numpy as np

from validation.plato import features as F
from validation.plato.tier_profile import _active_mask, _baseline_std

from original.constants import (  # noqa: E402
    ACTION_THRESHOLDS,
    ALL_FEATURE_CODES,
    FEATURE_TIER,
    TIER_WEIGHTS,
)

TANH_DIVISOR = 1.5
Z_CLIP = 4.0

_WEIGHTS = np.array(
    [TIER_WEIGHTS.get(FEATURE_TIER.get(c, 1), 1.0) for c in ALL_FEATURE_CODES],
    dtype=float,
)


def rms_z_for_action(threshold: float) -> float:
    """Invert deviation = tanh(rms_z / 1.5)."""
    if threshold >= 1.0:
        return float("inf")
    return TANH_DIVISOR * math.atanh(threshold)


def _rms_z(vec: np.ndarray, mu: np.ndarray, sd: np.ndarray, active: np.ndarray) -> float:
    z = np.clip((vec - mu) / sd, -Z_CLIP, Z_CLIP)
    zw = z * _WEIGHTS * active
    n = max(1, int(active.sum()))
    return float(np.sqrt((zw**2).sum() / n))


def _deviation(rms: float) -> float:
    return float(np.tanh(rms / TANH_DIVISOR))


def _action(dev: float) -> str:
    for name, (lo, hi) in ACTION_THRESHOLDS.items():
        if lo <= dev < hi:
            return name
    return "escalate"


def run(normalised: bool = False) -> dict:
    X, entries = F.build_matrix(normalised=normalised)
    rows: Dict[str, List[int]] = defaultdict(list)
    for i, e in enumerate(entries):
        if e["translator"] == "jowett":
            rows[e["slug"]].append(i)

    # ── Test A: leave-one-out inside a single dialogue ──────────────────────
    a_results = []
    for slug, idx in sorted(rows.items()):
        if len(idx) < 4:
            continue
        for held in idx:
            rest = [i for i in idx if i != held]
            B = X[rest]
            mu, sd, act = B.mean(axis=0), _baseline_std(B), _active_mask(B)
            r = _rms_z(X[held], mu, sd, act)
            a_results.append({"slug": slug, "rms_z": r, "deviation": _deviation(r)})

    # ── Test B: leave-one-out against the 3-dialogue early baseline ─────────
    base_slugs = ["apology", "crito", "gorgias"]
    base_idx = [i for s in base_slugs for i in rows[s]]
    b_results = []
    for held in base_idx:
        rest = [i for i in base_idx if i != held]
        B = X[rest]
        mu, sd, act = B.mean(axis=0), _baseline_std(B), _active_mask(B)
        r = _rms_z(X[held], mu, sd, act)
        b_results.append(
            {"slug": entries[held]["slug"], "rms_z": r, "deviation": _deviation(r)}
        )

    # ── Test C: Eryxias against that same baseline ─────────────────────────
    B = X[base_idx]
    mu, sd, act = B.mean(axis=0), _baseline_std(B), _active_mask(B)
    c_results = [
        {"slug": "eryxias", "rms_z": (r := _rms_z(X[i], mu, sd, act)), "deviation": _deviation(r)}
        for i in rows["eryxias"]
    ]

    def summarise(rs):
        if not rs:
            return {}
        d = [x["deviation"] for x in rs]
        z = [x["rms_z"] for x in rs]
        acts = [_action(x) for x in d]
        return {
            "n": len(rs),
            "mean_rms_z": round(float(np.mean(z)), 4),
            "mean_deviation": round(float(np.mean(d)), 4),
            "min_deviation": round(float(np.min(d)), 4),
            "max_deviation": round(float(np.max(d)), 4),
            "actions": {a: acts.count(a) for a in sorted(set(acts))},
            "pct_flagged": round(100.0 * sum(1 for a in acts if a != "no_action") / len(acts), 1),
        }

    rms_weight = float(np.sqrt((_WEIGHTS[act] ** 2).mean()))
    return {
        "normalised": normalised,
        "thresholds_in_rms_z": {
            name: round(rms_z_for_action(hi), 4) for name, (lo, hi) in ACTION_THRESHOLDS.items()
        },
        "rms_tier_weight": round(rms_weight, 4),
        "predicted_deviation_for_in_distribution_sample": round(_deviation(rms_weight), 4),
        "predicted_action": _action(_deviation(rms_weight)),
        "A_within_dialogue_loo": summarise(a_results),
        "B_three_dialogue_baseline_loo": summarise(b_results),
        "C_eryxias": summarise(c_results),
        "A_per_dialogue": {
            s: round(float(np.mean([x["deviation"] for x in a_results if x["slug"] == s])), 4)
            for s in sorted({x["slug"] for x in a_results})
        },
    }


def render(r: dict) -> str:
    L = [
        "",
        f"Scoring-scale calibration probe ({'NORMALISED' if r['normalised'] else 'RAW'})",
        "",
        "What rms_z each verdict band requires (inverting tanh(rms_z/1.5)):",
    ]
    for name, v in r["thresholds_in_rms_z"].items():
        L.append(f"    {name:<24} deviation < ...  ->  rms_z < {v:.3f}")
    L += [
        "",
        f"  RMS tier weight for the active feature set ....... {r['rms_tier_weight']:.3f}",
        "",
        "  A sample drawn from its OWN baseline distribution has E[z^2]=1, so its",
        f"  expected rms_z is that weight, {r['rms_tier_weight']:.3f}, giving",
        f"  deviation = {r['predicted_deviation_for_in_distribution_sample']:.3f}"
        f"  ->  {r['predicted_action'].upper()}",
        "",
        "── measured ──────────────────────────────────────────────────────",
    ]
    for key, label in (
        ("A_within_dialogue_loo", "A. leave-one-out WITHIN one dialogue"),
        ("B_three_dialogue_baseline_loo", "B. leave-one-out vs 3-dialogue baseline"),
        ("C_eryxias", "C. Eryxias (spurious) vs same baseline"),
    ):
        s = r[key]
        if not s:
            continue
        L += [
            f"  {label}",
            f"      n={s['n']}  mean rms_z={s['mean_rms_z']:.3f}  "
            f"mean deviation={s['mean_deviation']:.3f}  "
            f"range [{s['min_deviation']:.3f}, {s['max_deviation']:.3f}]",
            f"      flagged: {s['pct_flagged']:.0f}%   {s['actions']}",
            "",
        ]
    L += ["  per-dialogue mean deviation, test A (own work, own baseline):", ""]
    items = sorted(r["A_per_dialogue"].items(), key=lambda kv: kv[1])
    for s, v in items:
        L.append(f"      {s:<16}{v:.3f}  {_action(v)}")
    return "\n".join(L) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--normalise", action="store_true")
    ap.add_argument("--out", type=Path)
    a = ap.parse_args(argv)
    r = run(normalised=a.normalise)
    print(render(r))
    if a.out:
        a.out.write_text(json.dumps(r, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
