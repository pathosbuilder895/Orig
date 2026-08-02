"""
Tier-by-tier probe of the combined (DNA-weighted + impostor-relative) score.

Part 1 (instant): the top-3 DNA features WITHIN each tier -- grains of sand
that the global top-25 hides because their tier-mates are noisy.

Part 2: variant sweep on the combined route (llr AUC, leakage-free folds):
  - references: static weights, dna, dna^2, dna^3
  - top-k hard selection on dna^2
  - per-tier-top2 (tier-diverse selection)
  - leave-one-tier-out from dna^2: AUC drop = that tier carries real signal;
    AUC rise = the ranking is keeping noise from it
  - boost variants for tiers the ablation flags

Model-selection caveat: this sweep reads the test AUC many times; whatever
wins here is a hypothesis for the multi-author corpus, not a final config.
"""
import json
import sys
from collections import defaultdict
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent.parent
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_HERE))  # for `from dna_analysis import ...`

import numpy as np
from sklearn.metrics import roc_auc_score

from original.quantum.state import StudentState, BaselineSample
from original.quantum.scoring import score, ScoringConfig
from original.quantum.null_pool import fit_impostor_gaussian
from original.constants import ALL_FEATURE_CODES, FEATURE_TIER

from dna_analysis import dna_stats, LEWIS_GENRES, TIER_LABELS

HERE = Path(__file__).parent
EPS = 1e-3

TIER_OF = np.array([FEATURE_TIER.get(c, -1) for c in ALL_FEATURE_CODES])


def load():
    vectors = np.load(HERE / "vectors.npy")
    meta = json.loads((HERE / "vectors_meta.json").read_text())
    return vectors, meta


def make_state(records, label):
    st = StudentState(student_id=label)
    for r, v in records:
        st.add_sample(BaselineSample(
            text="", vector=v, provenance="proctored", auth_weight=1.0,
            assignment=r["chunk_id"], genre=r["genre"],
        ))
    return st


def llr_scores(state, items, weights, imp_stats):
    out = []
    for r, v in items:
        fdict = {c: float(x) for c, x in zip(ALL_FEATURE_CODES, v)}
        res = score(state, v, fdict, submission_id=r["chunk_id"], n_tokens=r["word_count"],
                    adaptive_weights=weights, impostor_stats=imp_stats,
                    scoring_config=ScoringConfig(null_model="impostor"))
        out.append(res.authorship.llr_deviation_score)
    return out


def auc(g, i):
    return roc_auc_score([0] * len(g) + [1] * len(i), g + i)


def main():
    vectors, meta = load()
    lewis = [(m, vectors[i]) for i, m in enumerate(meta) if m["author"] == "lewis"]
    chesterton = [(m, vectors[i]) for i, m in enumerate(meta) if m["author"] == "chesterton"]
    by_work = {}
    for item in chesterton:
        by_work.setdefault(item[0]["work"], []).append(item)
    calib, test_impostor = [], []
    for work, items in by_work.items():
        for i, item in enumerate(items):
            (calib if i % 2 == 0 else test_impostor).append(item)
    imp_stats = fit_impostor_gaussian([v for _, v in calib])

    # ── Part 1: top-3 DNA features per tier (full-corpus stats, display only) ──
    full_stats = dna_stats(vectors, meta)
    d_full = full_stats["dna"]
    print("=== Top-3 DNA features per tier (grains hidden by noisy tier-mates) ===")
    per_tier = defaultdict(list)
    for i, code in enumerate(ALL_FEATURE_CODES):
        per_tier[TIER_OF[i]].append((d_full[i], code))
    for t in sorted(per_tier):
        top3 = sorted(per_tier[t], reverse=True)[:3]
        tops = ", ".join(f"{c}={v:.2f}" for v, c in top3 if v > 0)
        print(f"  tier {t:>2} {TIER_LABELS.get(t, '?'):28s} {tops if tops else '(all dead)'}")

    # ── Part 2: fold setup ────────────────────────────────────────────────────
    folds = []
    for genre in LEWIS_GENRES:
        held_out = [it for it in lewis if it[0]["genre"] == genre]
        baseline_items = [it for it in lewis if it[0]["genre"] != genre]
        fold_vecs = np.stack([v for _, v in baseline_items] + [v for _, v in calib])
        fold_meta = [m for m, _ in baseline_items] + [m for m, _ in calib]
        stats = dna_stats(fold_vecs, fold_meta, genres=[g for g in LEWIS_GENRES if g != genre])
        folds.append({
            "genre": genre,
            "state": make_state(baseline_items, f"probe_{genre}"),
            "held_out": held_out,
            "dna": stats["dna"].astype(np.float64),
        })

    live_tiers = sorted({int(t) for i, t in enumerate(TIER_OF) if d_full[i] > 0})

    def norm(w):
        return w / (w.mean() + EPS)

    variants: dict[str, callable] = {
        "static": lambda d: None,
        "dna^1": lambda d: norm(d),
        "dna^2": lambda d: norm(d ** 2),
        "dna^3": lambda d: norm(d ** 3),
        "top20(dna^2)": lambda d: norm(np.where(d >= np.sort(d)[-20], d ** 2, 0.0)),
        "top40(dna^2)": lambda d: norm(np.where(d >= np.sort(d)[-40], d ** 2, 0.0)),
    }

    def per_tier_top2(d):
        w = np.zeros_like(d)
        for t in live_tiers:
            idx = np.where(TIER_OF == t)[0]
            best = idx[np.argsort(-d[idx])[:2]]
            w[best] = d[best] ** 2
        return norm(w)

    variants["tier_top2(dna^2)"] = per_tier_top2

    for t in live_tiers:
        variants[f"drop_t{t}"] = (lambda tt: lambda d: norm(np.where(TIER_OF == tt, 0.0, d ** 2)))(t)

    results = {}
    for name, fn in variants.items():
        aucs = []
        for f in folds:
            w = fn(f["dna"])
            g = llr_scores(f["state"], f["held_out"], w, imp_stats)
            i = llr_scores(f["state"], test_impostor, w, imp_stats)
            aucs.append(auc(g, i))
        results[name] = aucs
        print(f"[done] {name:20s} mean={np.mean(aucs):.4f}", flush=True)

    ref = np.mean(results["dna^2"])
    print(f"\n=== Variant sweep (combined dna-weight + llr route; reference dna^2 = {ref:.4f}) ===")
    print(f"{'variant':22s} {'mean_auc':>8s} {'delta':>7s}   per-fold")
    for name, aucs in sorted(results.items(), key=lambda kv: -np.mean(kv[1])):
        m = np.mean(aucs)
        delta = m - ref
        fold_str = " ".join(f"{a:.3f}" for a in aucs)
        print(f"{name:22s} {m:8.4f} {delta:+7.4f}   {fold_str}")

    print("\nInterpretation: drop_tX below reference = tier X carries real sand;")
    print("drop_tX above reference = tier X's dna-ranked features are noise on this corpus.")
    print("CAVEAT: many variants read the same test AUC -- winner is a hypothesis for")
    print("the multi-author corpus, not a final config.")


if __name__ == "__main__":
    main()
