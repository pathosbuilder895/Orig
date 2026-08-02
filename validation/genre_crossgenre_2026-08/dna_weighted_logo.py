"""
Does weighting the deviation score by measured genre-invariance ("DNA
weights") fix cross-genre recognition AT THE SOURCE — without the impostor
pool at scoring time?

Leakage protocol, per leave-one-genre-out fold:
  - DNA stats computed from the 5 BASELINE genres only (held-out genre never
    touches the weight derivation) and the Chesterton CALIBRATION half.
  - The Chesterton TEST half is scored, never fitted.
Compared against: static tier weights (production default), and the
llr_deviation_score route from the earlier study.
"""
import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent.parent
sys.path.insert(0, str(_ROOT))
sys.path.insert(0, str(_HERE))  # for `from dna_analysis import ...`

import numpy as np
from sklearn.metrics import roc_auc_score

from original.quantum.state import StudentState, BaselineSample
from original.quantum.scoring import score, ScoringConfig
from original.constants import ALL_FEATURE_CODES

from dna_analysis import dna_stats, LEWIS_GENRES

HERE = Path(__file__).parent
EPS = 1e-3


def load():
    vectors = np.load(HERE / "vectors.npy")
    meta = json.loads((HERE / "vectors_meta.json").read_text())
    return vectors, meta


def make_state(records, vectors, label):
    st = StudentState(student_id=label)
    for r, v in records:
        st.add_sample(BaselineSample(
            text="", vector=v, provenance="proctored", auth_weight=1.0,
            assignment=r["chunk_id"], genre=r["genre"],
        ))
    return st


def score_all(state, items, weights):
    out = []
    for r, v in items:
        fdict = {code: float(x) for code, x in zip(ALL_FEATURE_CODES, v)}
        result = score(
            state, v, fdict, submission_id=r["chunk_id"],
            n_tokens=r["word_count"], adaptive_weights=weights,
            scoring_config=ScoringConfig(),
        )
        out.append(result.authorship.deviation_score)
    return out


def auc(genuine, impostor):
    y = [0] * len(genuine) + [1] * len(impostor)
    return roc_auc_score(y, genuine + impostor)


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

    print(f"Lewis: {len(lewis)}  Chesterton calib/test: {len(calib)}/{len(test_impostor)}\n")
    print(f"{'held-out genre':15s} {'static AUC':>10s} {'dna AUC':>8s} {'n_held':>7s}")

    static_aucs, dna_aucs = [], []
    for genre in LEWIS_GENRES:
        held_out = [it for it in lewis if it[0]["genre"] == genre]
        baseline_items = [it for it in lewis if it[0]["genre"] != genre]
        if not held_out or not baseline_items:
            continue

        # ── leakage-free DNA weights: only baseline genres + calib half ──
        fold_vecs = np.stack([v for _, v in baseline_items] + [v for _, v in calib])
        fold_meta = [m for m, _ in baseline_items] + [m for m, _ in calib]
        fold_genres = [g for g in LEWIS_GENRES if g != genre]
        stats = dna_stats(fold_vecs, fold_meta, genres=fold_genres)
        w = stats["dna"].astype(np.float64)
        w = w / (w.mean() + EPS)  # scale-free for AUC; keeps rms_z in a sane range

        state = make_state(baseline_items, None, f"lewis_dna_{genre}")

        static_genuine = score_all(state, held_out, None)
        static_imp = score_all(state, test_impostor, None)
        dna_genuine = score_all(state, held_out, w)
        dna_imp = score_all(state, test_impostor, w)

        a_static = auc(static_genuine, static_imp)
        a_dna = auc(dna_genuine, dna_imp)
        static_aucs.append(a_static)
        dna_aucs.append(a_dna)
        print(f"{genre:15s} {a_static:10.4f} {a_dna:8.4f} {len(held_out):>7d}")

    print(f"\n{'MEAN':15s} {np.mean(static_aucs):10.4f} {np.mean(dna_aucs):8.4f}")
    print("\n(static = production _TIER_WEIGHT_VECTOR; dna = leakage-free genre-invariance weights.")
    print(" Reference points from the earlier study: raw static AUC 0.387, llr route 0.863.)")


if __name__ == "__main__":
    main()
