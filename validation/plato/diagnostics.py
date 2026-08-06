"""
validation/plato/diagnostics.py — why the translator gate lands where it does.

Two decompositions that together explain the gate result. Both were written to
diagnose a gate FAILURE, and both are reported regardless of outcome, because
they are the substantive findings of Phase 1.

1. ``variance_decomposition`` — noise-corrected effect sizes.

   The headline gate compares raw mean distances, but both quantities contain
   the same within-group noise floor, which flatters whichever is smaller.
   Subtracting the floor gives the effect actually attributable to each factor,
   and exposes the fact that the gate trio (Apology / Crito / Phaedo — the
   Trial-and-Death sequence) has NEGATIVE between-dialogue separation: its
   members are less distinguishable from each other than chunks drawn from a
   single one of them. A gate whose signal term is negative is measuring
   nothing, so the trio was a bad operationalisation of "different source text".

2. ``tier_decomposition`` — where each contrast lives in feature space.

   Squared Euclidean distance decomposes additively over features, so each
   tier's share of a contrast is directly computable. This is what showed that
   translator separation concentrates in Tier 4 (punctuation) while
   chronological separation concentrates in Tiers 1 and 5 (lexis and syntax) —
   the evidence that the translator gap is substantially edition convention.

    python -m validation.plato.diagnostics
    python -m validation.plato.diagnostics --normalise
"""

from __future__ import annotations

import argparse
import itertools
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Sequence

import numpy as np

from validation.plato import features as F
from validation.plato.chronology import CARY_DIALOGUES, EARLY, LATE, by_slug

from original.constants import ALL_FEATURE_CODES, FEATURE_TIER  # noqa: E402


def _rows_by_group(entries: Sequence[dict]) -> Dict[tuple, List[int]]:
    out: Dict[tuple, List[int]] = defaultdict(list)
    for i, e in enumerate(entries):
        out[(e["slug"], e["translator"])].append(i)
    return out


def _mean_pairwise(Z: np.ndarray, A: Sequence[int], B: Sequence[int] | None = None) -> float:
    if B is None:
        if len(A) < 2:
            return float("nan")
        d = [np.linalg.norm(Z[i] - Z[j]) for i, j in itertools.combinations(A, 2)]
    else:
        d = [np.linalg.norm(Z[i] - Z[j]) for i in A for j in B]
    return float(np.mean(d)) if d else float("nan")


def variance_decomposition(Z: np.ndarray, entries: Sequence[dict]) -> dict:
    """Noise-corrected effect sizes for translator vs source text."""
    groups = _rows_by_group(entries)

    within = float(
        np.nanmean([_mean_pairwise(Z, r) for r in groups.values() if len(r) >= 2])
    )

    tr = {}
    for s in CARY_DIALOGUES:
        j, c = groups.get((s, "jowett"), []), groups.get((s, "cary"), [])
        if j and c:
            tr[s] = _mean_pairwise(Z, j, c)
    between_translator = float(np.mean(list(tr.values())))

    jow = {s: r for (s, t), r in groups.items() if t == "jowett" and r}

    def pair_mean(pred) -> float:
        vals = []
        for a, b in itertools.combinations(sorted(jow), 2):
            try:
                da, db = by_slug(a), by_slug(b)
            except KeyError:
                continue
            if da.group is None or db.group is None:
                continue
            if pred(da, db):
                vals.append(_mean_pairwise(Z, jow[a], jow[b]))
        return float(np.mean(vals)) if vals else float("nan")

    trio = float(
        np.mean(
            [
                _mean_pairwise(Z, jow[a], jow[b])
                for a, b in itertools.combinations(CARY_DIALOGUES, 2)
                if a in jow and b in jow
            ]
        )
    )
    all_pairs = pair_mean(lambda a, b: True)
    far_pairs = pair_mean(lambda a, b: {a.group, b.group} == {EARLY, LATE})

    et = between_translator - within
    out = {
        "within_noise_floor": round(within, 4),
        "between_translator": round(between_translator, 4),
        "translator_effect": round(et, 4),
        "per_dialogue_translator_gap": {k: round(v, 4) for k, v in tr.items()},
        "source_effects": {},
    }
    for label, raw in (
        ("gate_trio", trio),
        ("all_ranked_pairs", all_pairs),
        ("early_vs_late_pairs", far_pairs),
    ):
        eff = raw - within
        out["source_effects"][label] = {
            "raw_distance": round(raw, 4),
            "effect": round(eff, 4),
            "ratio_vs_translator": round(eff / et, 4) if et else float("nan"),
        }
    return out


def tier_decomposition(Z: np.ndarray, entries: Sequence[dict], mask: np.ndarray) -> dict:
    """Each tier's share of the translator contrast and the chronology contrast."""
    codes = [c for c, k in zip(ALL_FEATURE_CODES, mask) if k]
    tiers = [FEATURE_TIER.get(c, -1) for c in codes]
    groups = _rows_by_group(entries)

    def centroid(keys) -> np.ndarray | None:
        idx = [i for k in keys for i in groups.get(k, [])]
        return Z[idx].mean(axis=0) if idx else None

    j = centroid([(s, "jowett") for s in CARY_DIALOGUES])
    c = centroid([(s, "cary") for s in CARY_DIALOGUES])
    slugs = {e["slug"] for e in entries}
    early = [(s, "jowett") for s in slugs if _group(s) == EARLY]
    late = [(s, "jowett") for s in slugs if _group(s) == LATE]
    e_c, l_c = centroid(early), centroid(late)

    d_tr = (j - c) ** 2
    d_ch = (e_c - l_c) ** 2
    tt, tc = float(d_tr.sum()), float(d_ch.sum())

    by_tier: Dict[str, dict] = {}
    agg_t, agg_c = defaultdict(float), defaultdict(float)
    for t, a, b in zip(tiers, d_tr, d_ch):
        agg_t[t] += a
        agg_c[t] += b
    for t in sorted(agg_t):
        st, sc = agg_t[t] / tt, agg_c[t] / tc
        by_tier[f"T{t}"] = {
            "n_features": sum(1 for x in tiers if x == t),
            "translator_share": round(st, 4),
            "chronology_share": round(sc, 4),
            "ratio": round(st / sc, 3) if sc > 1e-9 else None,
        }

    top = lambda d, tot: [  # noqa: E731
        {"code": codes[i], "tier": f"T{tiers[i]}", "share": round(float(d[i] / tot), 4)}
        for i in np.argsort(-d)[:10]
    ]
    return {
        "total_squared_separation": {"translator": round(tt, 3), "chronology": round(tc, 3)},
        "by_tier": by_tier,
        "top_translator_features": top(d_tr, tt),
        "top_chronology_features": top(d_ch, tc),
    }


def _group(slug: str):
    try:
        return by_slug(slug).group
    except KeyError:
        return None


def run(normalised: bool = False, force: bool = False) -> dict:
    manifest = F.load_manifest()
    X, entries = F.build_matrix(manifest, force=force, normalised=normalised)
    mask = F.informative_mask(X)
    Z = F.standardise(X, mask)
    return {
        "normalised": normalised,
        "n_chunks": len(entries),
        "n_active_features": int(mask.sum()),
        "variance": variance_decomposition(Z, entries),
        "tiers": tier_decomposition(Z, entries, mask),
    }


def render(r: dict) -> str:
    v, t = r["variance"], r["tiers"]
    L = [
        "",
        f"Plato diagnostics  ({'NORMALISED' if r['normalised'] else 'RAW'} text, "
        f"{r['n_chunks']} chunks, {r['n_active_features']} active features)",
        "",
        "── noise-corrected effect sizes ──────────────────────────────────",
        f"  within-group noise floor            {v['within_noise_floor']:8.4f}",
        f"  translator effect (Jowett↔Cary)     {v['translator_effect']:8.4f}",
    ]
    for label, d in v["source_effects"].items():
        L.append(
            f"  source effect: {label:<22}{d['effect']:8.4f}   "
            f"ratio vs translator {d['ratio_vs_translator']:6.2f}"
        )
    L += ["", "── where each contrast lives ─────────────────────────────────────",
          f"  {'tier':<6}{'n':>4}{'translator':>13}{'chronology':>13}{'ratio':>9}"]
    for tier, d in t["by_tier"].items():
        ratio = f"{d['ratio']:.2f}" if d["ratio"] is not None else "—"
        flag = "  <<<" if d["translator_share"] > 0.15 and (d["ratio"] or 0) > 1.5 else ""
        L.append(
            f"  {tier:<6}{d['n_features']:>4}{d['translator_share']:>12.1%}"
            f"{d['chronology_share']:>13.1%}{ratio:>9}{flag}"
        )
    L += ["", "  top translator features: "
          + ", ".join(f"{f['code']}({f['share']:.0%})" for f in t["top_translator_features"][:5]),
          "  top chronology features: "
          + ", ".join(f"{f['code']}({f['share']:.0%})" for f in t["top_chronology_features"][:5]),
          ""]
    return "\n".join(L)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--normalise", action="store_true")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--out", type=Path)
    a = ap.parse_args(argv)
    r = run(normalised=a.normalise, force=a.force)
    print(render(r))
    if a.out:
        a.out.parent.mkdir(parents=True, exist_ok=True)
        a.out.write_text(json.dumps(r, indent=2))
        print(f"wrote {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
