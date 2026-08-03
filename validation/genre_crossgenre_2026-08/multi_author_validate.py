"""
Multi-author generalization test of the Lewis-derived DNA weights.

The weights are FROZEN — computed once from the Lewis/Chesterton corpus
(genre-invariance x author-separation) and never touched by this corpus.
If they still improve discrimination among 11 different authors, the
"grains of sand" are general authorial DNA, not Lewis-specific quirks.

Protocol, per author A (leave-target-out impostor pools, same-tenant style):
  - A's chunks: 60% baseline / 40% held-out genuine
  - impostor gaussian: OTHER authors' baseline halves (A never enters it)
  - scored: A's held-out (genuine) vs other authors' held-out (impostors)
  - AUC per author for: static raw, static llr, dna^1 llr, dna^2 llr
"""
import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent.parent
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_HERE))

import numpy as np
from sklearn.metrics import roc_auc_score

from original.quantum.state import StudentState, BaselineSample
from original.quantum.scoring import score, ScoringConfig
from original.quantum.null_pool import fit_impostor_gaussian
from original.constants import ALL_FEATURE_CODES

from dna_analysis import dna_stats

HERE = Path(__file__).parent
EPS = 1e-3
BASELINE_FRAC = 0.6


def main():
    # ── frozen Lewis-derived DNA weights ──────────────────────────────────────
    lewis_vectors = np.load(HERE / "vectors.npy")
    lewis_meta = json.loads((HERE / "vectors_meta.json").read_text())
    d = dna_stats(lewis_vectors, lewis_meta)["dna"].astype(np.float64)
    w1 = d / (d.mean() + EPS)          # dna^1
    w2 = (d ** 2) / ((d ** 2).mean() + EPS)  # dna^2

    # ── public-authors corpus ─────────────────────────────────────────────────
    vectors = np.load(HERE / "pa_vectors.npy")
    meta = json.loads((HERE / "pa_meta.json").read_text())
    authors = sorted({m["author"] for m in meta})
    by_author = {a: [(m, vectors[i]) for i, m in enumerate(meta) if m["author"] == a]
                 for a in authors}

    splits = {}
    for a, items in by_author.items():
        n_base = max(3, int(len(items) * BASELINE_FRAC))
        splits[a] = {"baseline": items[:n_base], "held_out": items[n_base:]}

    def state_for(a):
        st = StudentState(student_id=f"pa:{a}")
        for m, v in splits[a]["baseline"]:
            st.add_sample(BaselineSample(text="", vector=v, provenance="proctored",
                                         auth_weight=1.0, assignment=m["chunk_id"]))
        return st

    def run(state, items, weights, imp_stats, use_llr):
        out = []
        for m, v in items:
            fdict = {c: float(x) for c, x in zip(ALL_FEATURE_CODES, v)}
            cfg = ScoringConfig(null_model="impostor") if use_llr else ScoringConfig()
            res = score(state, v, fdict, submission_id=m["chunk_id"],
                        n_tokens=m["word_count"], adaptive_weights=weights,
                        impostor_stats=imp_stats if use_llr else None,
                        scoring_config=cfg)
            out.append(res.authorship.llr_deviation_score if use_llr
                       else res.authorship.deviation_score)
        return out

    def auc(g, i):
        return roc_auc_score([0] * len(g) + [1] * len(i), g + i)

    CONFIGS = [
        ("static_raw", None, False),
        ("static_llr", None, True),
        ("dna1_llr", w1, True),
        ("dna2_llr", w2, True),
    ]

    results = {name: [] for name, _, _ in CONFIGS}
    print(f"{'author':12s} " + " ".join(f"{n:>11s}" for n, _, _ in CONFIGS))
    for a in authors:
        st = state_for(a)
        genuine_items = splits[a]["held_out"]
        impostor_items = [it for b in authors if b != a for it in splits[b]["held_out"]]
        pool_vecs = [v for b in authors if b != a for _, v in splits[b]["baseline"]]
        imp_stats = fit_impostor_gaussian(pool_vecs)

        row = []
        for name, w, use_llr in CONFIGS:
            g = run(st, genuine_items, w, imp_stats, use_llr)
            i = run(st, impostor_items, w, imp_stats, use_llr)
            val = auc(g, i)
            results[name].append(val)
            row.append(val)
        print(f"{a:12s} " + " ".join(f"{v:11.4f}" for v in row), flush=True)

    print(f"\n{'MEAN':12s} " + " ".join(f"{np.mean(results[n]):11.4f}" for n, _, _ in CONFIGS))
    print(f"{'MIN':12s} " + " ".join(f"{np.min(results[n]):11.4f}" for n, _, _ in CONFIGS))
    print("\n(weights frozen from the Lewis corpus; this corpus never touched their derivation)")


if __name__ == "__main__":
    main()
