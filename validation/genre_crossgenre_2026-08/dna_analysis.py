"""
Which features are the author's DNA — stable across an author's genres,
yet still separating them from another author?

For every feature f:
  genre_drift(f)   = std of Lewis's per-genre means      (how much the feature
                     moves when the SAME author changes register)
  within_noise(f)  = pooled within-genre std for Lewis    (chunk-to-chunk noise)
  separation(f)    = |mean_lewis - mean_chesterton|       (author signal)

  dna_score(f) = separation / (genre_drift + within_noise + eps)

High dna_score = the fine-grained sand: barely moves across Narnia vs theology
vs memoir, but sits at a different level than Chesterton. Low = a genre
chameleon or pure noise. Aggregated per tier to test the hand-assigned
TIER_WEIGHTS priors against measured cross-genre reality.

Caveat printed with results: separation here is Lewis-vs-Chesterton only; a
2-author estimate of "author signal" is directional, not definitive.
"""
import json
import sys
from collections import defaultdict
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent.parent
sys.path.insert(0, str(_ROOT))

import numpy as np

from original.constants import ALL_FEATURE_CODES, FEATURE_TIER, TIER_WEIGHTS

HERE = Path(__file__).parent
EPS = 1e-3
LEWIS_GENRES = ["narnia", "space_trilogy", "theology", "memoir", "essays", "satire"]

TIER_LABELS = {
    0: "comparison (meta)", 1: "surface stylometrics", 2: "discourse structure",
    3: "rhetorical/register", 4: "char/punct fingerprint", 5: "POS/syntax",
    6: "idiosyncratic", 7: "AI detection", 8: "prosodic rhythm",
    9: "argument topology", 10: "semantic gravity", 11: "error ecology",
    12: "tension arc", 13: "prosodic depth (clausulae)", 14: "error topology",
    15: "lexical architecture", 16: "citation fingerprint", 17: "behavioral biometrics",
}


def load():
    vectors = np.load(HERE / "vectors.npy")
    meta = json.loads((HERE / "vectors_meta.json").read_text())
    return vectors, meta


def dna_stats(vectors, meta, genres=LEWIS_GENRES):
    """Per-feature stats. Returns dict arrays keyed by stat name, shape (D,)."""
    lewis_idx = [i for i, m in enumerate(meta) if m["author"] == "lewis" and m["genre"] in genres]
    chest_idx = [i for i, m in enumerate(meta) if m["author"] == "chesterton"]

    L = vectors[lewis_idx]  # (Nl, D)
    C = vectors[chest_idx]  # (Nc, D)
    lewis_genres_arr = np.array([meta[i]["genre"] for i in lewis_idx])

    genre_means = []
    within_stds = []
    for g in genres:
        sel = L[lewis_genres_arr == g]
        if len(sel) == 0:
            continue
        genre_means.append(sel.mean(axis=0))
        within_stds.append(sel.std(axis=0))
    genre_means = np.stack(genre_means)          # (G, D)
    within_noise = np.stack(within_stds).mean(axis=0)  # (D,)

    genre_drift = genre_means.std(axis=0)        # (D,)
    separation = np.abs(L.mean(axis=0) - C.mean(axis=0))  # (D,)

    dna = separation / (genre_drift + within_noise + EPS)
    # dead features: stuck near neutral for both authors -> no signal at all
    dead = (L.std(axis=0) < 0.002) & (np.abs(L.mean(axis=0) - 0.5) < 0.01)

    return {
        "genre_drift": genre_drift,
        "within_noise": within_noise,
        "separation": separation,
        "dna": np.where(dead, 0.0, dna),
        "dead": dead,
    }


def main():
    vectors, meta = load()
    stats = dna_stats(vectors, meta)

    order = np.argsort(-stats["dna"])
    print("=== Top 25 authorial-DNA features (stable across Lewis's genres, separates from Chesterton) ===")
    print(f"{'rank':>4} {'feature':38s} {'tier':>4}  {'dna':>6}  {'separation':>10}  {'genre_drift':>11}  {'within_noise':>12}")
    for rank, i in enumerate(order[:25], 1):
        code = ALL_FEATURE_CODES[i]
        t = FEATURE_TIER.get(code, -1)
        print(f"{rank:>4} {code:38s} {t:>4}  {stats['dna'][i]:6.2f}  {stats['separation'][i]:10.4f}  "
              f"{stats['genre_drift'][i]:11.4f}  {stats['within_noise'][i]:12.4f}")

    print("\n=== Bottom 15 (genre chameleons / noise — worst live features) ===")
    live = [i for i in order if not stats["dead"][i]]
    for rank, i in enumerate(live[-15:], 1):
        code = ALL_FEATURE_CODES[i]
        t = FEATURE_TIER.get(code, -1)
        print(f"{rank:>4} {code:38s} {t:>4}  {stats['dna'][i]:6.2f}  {stats['separation'][i]:10.4f}  "
              f"{stats['genre_drift'][i]:11.4f}  {stats['within_noise'][i]:12.4f}")

    n_dead = int(stats["dead"].sum())
    print(f"\n({n_dead} dead features excluded: stuck at neutral 0.5 for this corpus)")

    # ── Tier aggregation vs the hand-assigned TIER_WEIGHTS priors ──────────────
    by_tier = defaultdict(list)
    for i, code in enumerate(ALL_FEATURE_CODES):
        if not stats["dead"][i]:
            by_tier[FEATURE_TIER.get(code, -1)].append(stats["dna"][i])

    print("\n=== Per-tier: measured DNA score vs hand-assigned TIER_WEIGHTS prior ===")
    print(f"{'tier':>4}  {'label':28s} {'n_live':>6}  {'median_dna':>10}  {'max_dna':>8}  {'prior_weight':>12}  verdict")
    rows = []
    for t in sorted(by_tier):
        vals = np.array(by_tier[t])
        rows.append((t, float(np.median(vals)), float(vals.max()), len(vals)))
    med_of_medians = float(np.median([r[1] for r in rows]))
    for t, med, mx, n in sorted(rows, key=lambda r: -r[1]):
        prior = TIER_WEIGHTS.get(t, float("nan"))
        if med > 1.5 * med_of_medians and prior < 1.2:
            verdict = "UNDERWEIGHTED by prior"
        elif med < 0.6 * med_of_medians and prior >= 1.2:
            verdict = "OVERWEIGHTED by prior"
        else:
            verdict = ""
        print(f"{t:>4}  {TIER_LABELS.get(t, '?'):28s} {n:>6}  {med:>10.3f}  {mx:>8.2f}  {prior:>12.1f}  {verdict}")

    np.save(HERE / "dna_scores.npy", stats["dna"])
    print(f"\nSaved per-feature dna scores to dna_scores.npy")
    print("\nCAVEAT: separation is measured against ONE contrast author (Chesterton).")
    print("Rankings are directional; a multi-author corpus is needed before reweighting production.")


if __name__ == "__main__":
    main()
