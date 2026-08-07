"""
validation/plato/tier_profile.py — per-tier movement away from an early baseline.

Builds a baseline from a chosen set of dialogues (default: Apology, Crito,
Gorgias — all early-period Jowett) and reports, for every other dialogue, how
far each of the 17 feature tiers has moved away from that baseline.

Two views, deliberately kept side by side:

  * ``tier |z|`` — the raw measurement. For each tier, the mean absolute
    z-score of a dialogue's chunks against the baseline distribution. This is
    what the feature space actually sees, before any scoring machinery.

  * ``deviation_score`` / ``action`` — what the product concludes, obtained by
    running the real ``original.quantum.scoring.score()`` against a real
    ``StudentState``. This is the number a professor would be shown.

The gap between the two columns is the point. Tier movement can be large while
the deviation score stays flat, because scoring winsorises z at ±4, divides by
``n_active``, squashes through ``tanh(rms_z / 1.5)``, and then multiplies by
0.75 whenever the trajectory reads as "growth".

The baseline uses the same adaptive standard-deviation floor as production
(``StudentState.baseline_std``: ``max(std, max(0.005, 0.15/sqrt(N)))``), so the
z-scores here are comparable to what the live system computes rather than being
an idealised version of it.

    python -m validation.plato.tier_profile
    python -m validation.plato.tier_profile --normalise
    python -m validation.plato.tier_profile --baseline apology,crito,gorgias
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Sequence

import numpy as np

from validation.plato import features as F
from validation.plato.chronology import GROUP_NAMES, by_slug

from original.constants import ALL_FEATURE_CODES, FEATURE_DIM, FEATURE_TIER  # noqa: E402

DEFAULT_BASELINE = ["apology", "crito", "gorgias"]

# Tier labels, for a readable table.
TIER_LABEL: Dict[int, str] = {
    0: "comparison",
    1: "surface",
    2: "discourse",
    3: "rhetorical",
    4: "char/punct",
    5: "POS/syntax",
    6: "idiosyncratic",
    7: "AI markers",
    8: "prosodic",
    9: "argument",
    10: "semantic",
    11: "error ecology",
    12: "tension arc",
    13: "prosodic depth",
    14: "error topology",
    15: "lexical arch",
    16: "citation",
    17: "behavioral",
}


def _baseline_std(V: np.ndarray) -> np.ndarray:
    """Mirror StudentState.baseline_std, including the adaptive floor."""
    n = len(V)
    if n < 2:
        return np.full(V.shape[1], 0.15)
    floor = max(0.005, 0.15 / np.sqrt(n))
    return np.maximum(V.std(axis=0), floor)


def _active_mask(V: np.ndarray) -> np.ndarray:
    """Mirror StudentState.active_feature_mask.

    Without this, features that saturate at the NORM_BOUNDS produce meaningless
    z-scores: every baseline chunk clips to the same bound, so the standard
    deviation is zero, the adaptive floor takes over at 0.0327, and a flip to
    the opposite bound reads as |z| = 1/0.0327 = 30.6. On this corpus that
    affects real features — ``sentence_length_variance`` is pinned at 1.0 for
    the whole early baseline and 0.0 for the Timaeus, which is a clipping
    artefact rather than a 30-sigma stylistic difference.

    Production excludes exactly these, so an analysis that omits the mask does
    not describe what the product does.
    """
    if len(V) < 2:
        return np.ones(V.shape[1], dtype=bool)
    stuck_neutral = np.all(np.abs(V - 0.5) < 0.002, axis=0)
    zero_freq = np.all(V < 0.005, axis=0)
    constant = V.std(axis=0) < 0.008
    return ~(stuck_neutral | zero_freq | constant)


def compute(
    normalised: bool = False,
    baseline_slugs: Sequence[str] = DEFAULT_BASELINE,
    force: bool = False,
) -> dict:
    manifest = F.load_manifest()
    X, entries = F.build_matrix(manifest, force=force, normalised=normalised)

    rows_by_slug: Dict[str, List[int]] = defaultdict(list)
    for i, e in enumerate(entries):
        if e["translator"] == "jowett":
            rows_by_slug[e["slug"]].append(i)

    missing = [s for s in baseline_slugs if s not in rows_by_slug]
    if missing:
        raise SystemExit(f"baseline dialogues not in corpus: {missing}")

    base_idx = [i for s in baseline_slugs for i in rows_by_slug[s]]
    B = X[base_idx]
    mu, sd = B.mean(axis=0), _baseline_std(B)

    tiers = np.array([FEATURE_TIER.get(c, -1) for c in ALL_FEATURE_CODES])
    # Use the SAME active-feature mask production uses, or saturated features
    # dominate every z-score with clipping artefacts. See _active_mask.
    live = _active_mask(B)

    results = []
    for slug, idx in rows_by_slug.items():
        d = by_slug(slug)
        Z = np.abs((X[idx] - mu) / sd)  # (n_chunks, FEATURE_DIM)
        per_tier = {}
        for t in sorted(set(tiers)):
            sel = (tiers == t) & live
            if not sel.any():
                continue
            per_tier[int(t)] = float(Z[:, sel].mean())
        results.append(
            {
                "slug": slug,
                "title": d.title,
                "group": GROUP_NAMES.get(d.group) if d.group else "spurious",
                "rank": d.group if d.group else 9,
                "high_confidence": d.high_confidence,
                "is_baseline": slug in baseline_slugs,
                "n_chunks": len(idx),
                "mean_abs_z": float(Z[:, live].mean()),
                "per_tier": per_tier,
            }
        )

    results.sort(key=lambda r: (r["rank"], -r["mean_abs_z"]))
    saturated = [
        ALL_FEATURE_CODES[i] for i in range(len(ALL_FEATURE_CODES)) if not live[i]
    ]
    return {
        "normalised": normalised,
        "baseline": list(baseline_slugs),
        "n_baseline_chunks": len(base_idx),
        "n_active_features": int(live.sum()),
        "n_masked_features": int((~live).sum()),
        "masked_features": saturated,
        "results": results,
    }


def score_with_product(
    normalised: bool = False, baseline_slugs: Sequence[str] = DEFAULT_BASELINE
) -> Dict[str, dict]:
    """Run the real scoring path so the product's own verdict sits beside the tiers."""
    from original.quantum.scoring import score
    from original.quantum.state import BaselineSample, StudentState

    manifest = F.load_manifest()
    X, entries = F.build_matrix(manifest, normalised=normalised)
    corpus = Path(__file__).resolve().parent / "corpus"

    rows: Dict[str, List[int]] = defaultdict(list)
    for i, e in enumerate(entries):
        if e["translator"] == "jowett":
            rows[e["slug"]].append(i)

    samples = []
    for s in baseline_slugs:
        for i in rows[s]:
            samples.append(
                BaselineSample(
                    text=(corpus / entries[i]["filename"]).read_text(encoding="utf-8"),
                    vector=X[i],
                    provenance="verified",
                    auth_weight=1.0,
                    assignment=entries[i]["title"],
                    submitted_at="2026-01-01",
                )
            )
    state = StudentState(student_id="plato", samples=samples)

    out: Dict[str, dict] = {}
    for slug, idx in rows.items():
        devs, actions = [], []
        for i in idx:
            fd = {c: float(v) for c, v in zip(ALL_FEATURE_CODES, X[i])}
            r = score(state, X[i], fd, submission_id=entries[i]["filename"])
            devs.append(float(r.authorship.deviation_score))
            actions.append(r.recommendation.action)
        out[slug] = {
            "mean_deviation": round(float(np.mean(devs)), 4),
            "max_deviation": round(float(np.max(devs)), 4),
            "actions": {a: actions.count(a) for a in sorted(set(actions))},
        }
    return out


def render(rep: dict, product: Dict[str, dict] | None = None) -> str:
    tiers_present = sorted({t for r in rep["results"] for t in r["per_tier"]})
    L = [
        "",
        f"Per-tier movement from an early baseline "
        f"({'NORMALISED' if rep['normalised'] else 'RAW'} text)",
        f"baseline: {', '.join(rep['baseline'])}  ({rep['n_baseline_chunks']} chunks)",
        f"active features: {rep['n_active_features']}/{FEATURE_DIM}  "
        f"({rep['n_masked_features']} masked as constant/saturated in the baseline)",
        "",
        "values = mean |z| of the dialogue's chunks against the baseline distribution",
        "",
    ]
    hdr = f"{'dialogue':<15}{'grp':<7}" + "".join(f"T{t:<4}" for t in tiers_present) + f"{'ALL':>6}"
    if product:
        hdr += f"{'dev':>7}  action"
    L.append(hdr)
    L.append("─" * len(hdr))
    last = None
    for r in rep["results"]:
        if last is not None and r["group"] != last:
            L.append("·" * len(hdr))
        last = r["group"]
        mark = "*" if r["is_baseline"] else " "
        row = f"{r['slug'][:14]:<14}{mark}{r['group'][:6]:<7}"
        for t in tiers_present:
            v = r["per_tier"].get(t)
            row += f"{v:<5.1f}" if v is not None else "  .  "
        row += f"{r['mean_abs_z']:>6.2f}"
        if product and r["slug"] in product:
            p = product[r["slug"]]
            top = max(p["actions"], key=p["actions"].get)
            row += f"{p['mean_deviation']:>7.3f}  {top}"
        L.append(row)
    L += ["", "* = baseline dialogue", ""]
    L.append("tier key: " + "  ".join(f"T{t}={TIER_LABEL.get(t, '?')}" for t in tiers_present))

    # Group means — the headline.
    L += ["", "mean |z| by chronology group (baseline dialogues excluded):", ""]
    for g in ("early", "middle", "late", "spurious"):
        sel = [r for r in rep["results"] if r["group"] == g and not r["is_baseline"]]
        if not sel:
            continue
        line = f"  {g:<9} n={len(sel):<3}"
        for t in tiers_present:
            vals = [r["per_tier"][t] for r in sel if t in r["per_tier"]]
            line += f"{np.mean(vals):<5.1f}" if vals else "  .  "
        line += f"{np.mean([r['mean_abs_z'] for r in sel]):>6.2f}"
        if product:
            devs = [product[r["slug"]]["mean_deviation"] for r in sel if r["slug"] in product]
            if devs:
                line += f"{np.mean(devs):>7.3f}"
        L.append(line)
    return "\n".join(L) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--normalise", action="store_true")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--baseline", default=",".join(DEFAULT_BASELINE))
    ap.add_argument("--no-product", action="store_true", help="Skip the real scoring pass.")
    ap.add_argument("--out", type=Path)
    a = ap.parse_args(argv)

    slugs = [s.strip() for s in a.baseline.split(",") if s.strip()]
    rep = compute(normalised=a.normalise, baseline_slugs=slugs, force=a.force)
    product = None if a.no_product else score_with_product(a.normalise, slugs)
    print(render(rep, product))
    if a.out:
        a.out.parent.mkdir(parents=True, exist_ok=True)
        a.out.write_text(json.dumps({"tiers": rep, "product": product}, indent=2))
        print(f"wrote {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
