"""Leave-one-genre-out validation of the Original stylometric scoring pipeline
against a public-domain C.S. Lewis corpus (genuine, cross-genre) vs a
G.K. Chesterton corpus (impostor pool), sweeping scoring flags.

Companion to validation/public_authors/ -- see README.md for how this
differs from that harness (it isolates the genre-shift axis for a single
author rather than testing top-1 attribution across an author roster).
Calls into original/quantum + original/features directly, in-memory,
bypassing api.py/store.py entirely.
"""
import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent.parent
sys.path.insert(0, str(_ROOT))

import numpy as np
from sklearn.metrics import roc_auc_score

from original.quantum.state import StudentState, BaselineSample
from original.quantum.scoring import score, ScoringConfig
from original.quantum.null_pool import fit_impostor_gaussian
from original.constants import ALL_FEATURE_CODES

HERE = Path(__file__).parent
LEWIS_GENRES = ["narnia", "space_trilogy", "theology", "memoir", "essays", "satire"]

CONFIGS = {
    "baseline": dict(),
    "length_adaptive": dict(length_adaptive_weights=True),
    "null_impostor": dict(null_model="impostor"),
    "both": dict(length_adaptive_weights=True, null_model="impostor"),
}


def load():
    vectors = np.load(HERE / "vectors.npy")
    meta = json.loads((HERE / "vectors_meta.json").read_text())
    for m, v in zip(meta, vectors):
        m["vector"] = v
    return meta


def make_state(records, label):
    st = StudentState(student_id=label)
    for r in records:
        st.add_sample(BaselineSample(
            text="", vector=r["vector"], provenance="proctored", auth_weight=1.0,
            assignment=r["chunk_id"], genre=r["genre"],
        ))
    return st


def score_all(state, records, config, impostor_stats):
    devs, llrs = [], []
    for r in records:
        vec = r["vector"]
        fdict = {code: float(v) for code, v in zip(ALL_FEATURE_CODES, vec)}
        result = score(
            state, vec, fdict, submission_id=r["chunk_id"],
            n_tokens=r["word_count"], impostor_stats=impostor_stats,
            scoring_config=ScoringConfig(**config),
        )
        devs.append(result.authorship.deviation_score)
        llrs.append(result.authorship.llr_deviation_score)
    return devs, llrs


def auc_or_none(genuine, impostor):
    if not genuine or not impostor or any(x is None for x in genuine + impostor):
        return None
    y = [0] * len(genuine) + [1] * len(impostor)
    scores = genuine + impostor
    try:
        return roc_auc_score(y, scores)
    except ValueError:
        return None


def main():
    records = load()
    lewis = [r for r in records if r["author"] == "lewis"]
    chesterton = [r for r in records if r["author"] == "chesterton"]

    # split Chesterton into calibration (fit impostor gaussian) / test (measure specificity)
    # by parity of position within its own work, so both halves cover every work evenly
    by_work: dict[str, list] = {}
    for r in chesterton:
        by_work.setdefault(r["work"], []).append(r)
    calib, test_impostor = [], []
    for work, rs in by_work.items():
        for i, r in enumerate(rs):
            (calib if i % 2 == 0 else test_impostor).append(r)

    print(f"Lewis chunks: {len(lewis)}  Chesterton calib/test: {len(calib)}/{len(test_impostor)}\n")

    impostor_calib_vectors = [r["vector"] for r in calib]
    impostor_stats = fit_impostor_gaussian(impostor_calib_vectors)

    results = []
    for genre in LEWIS_GENRES:
        held_out = [r for r in lewis if r["genre"] == genre]
        cross_baseline_records = [r for r in lewis if r["genre"] != genre]
        if not held_out or not cross_baseline_records:
            print(f"[skip] {genre}: held_out={len(held_out)} baseline={len(cross_baseline_records)}")
            continue

        # same-genre control: 70/30 split within the bucket itself (upper bound)
        n_bucket = len(held_out)
        split = max(1, int(n_bucket * 0.7))
        same_genre_baseline_records = held_out[:split]
        same_genre_held_out = held_out[split:]
        if not same_genre_held_out:
            same_genre_held_out = held_out[-1:]
            same_genre_baseline_records = held_out[:-1]

        cross_state = make_state(cross_baseline_records, f"lewis_cross_{genre}")
        same_state = make_state(same_genre_baseline_records, f"lewis_same_{genre}")

        for config_name, config in CONFIGS.items():
            imp_stats = impostor_stats if config.get("null_model") == "impostor" else None

            cross_genuine_dev, cross_genuine_llr = score_all(cross_state, held_out, config, imp_stats)
            cross_impostor_dev, cross_impostor_llr = score_all(cross_state, test_impostor, config, imp_stats)

            same_genuine_dev, same_genuine_llr = score_all(same_state, same_genre_held_out, config, imp_stats)
            same_impostor_dev, same_impostor_llr = score_all(same_state, test_impostor, config, imp_stats)

            row = {
                "genre": genre,
                "config": config_name,
                "n_held_out": len(held_out),
                "n_baseline": len(cross_baseline_records),
                "cross_dev_auc": auc_or_none(cross_genuine_dev, cross_impostor_dev),
                "cross_llr_auc": auc_or_none(cross_genuine_llr, cross_impostor_llr),
                "same_dev_auc": auc_or_none(same_genuine_dev, same_impostor_dev),
                "same_llr_auc": auc_or_none(same_genuine_llr, same_impostor_llr),
                "cross_genuine_dev_mean": float(np.mean(cross_genuine_dev)),
                "cross_impostor_dev_mean": float(np.mean(cross_impostor_dev)),
            }
            results.append(row)

            def fmt(x):
                return f"{x:.4f}" if x is not None else "  n/a "

            print(f"{genre:15s} {config_name:16s} cross_dev_auc={fmt(row['cross_dev_auc'])}  "
                  f"cross_llr_auc={fmt(row['cross_llr_auc'])}  same_dev_auc={fmt(row['same_dev_auc'])}  "
                  f"genuine_mean={row['cross_genuine_dev_mean']:.3f}  impostor_mean={row['cross_impostor_dev_mean']:.3f}")

    (HERE / "sweep_results.json").write_text(json.dumps(results, indent=1))

    print("\n=== Mean AUC per config (averaged across genre buckets) ===")
    for config_name in CONFIGS:
        rows = [r for r in results if r["config"] == config_name]
        cross_dev = [r["cross_dev_auc"] for r in rows if r["cross_dev_auc"] is not None]
        cross_llr = [r["cross_llr_auc"] for r in rows if r["cross_llr_auc"] is not None]
        same_dev = [r["same_dev_auc"] for r in rows if r["same_dev_auc"] is not None]
        print(f"{config_name:16s} cross_dev_auc={np.mean(cross_dev):.4f}  "
              f"cross_llr_auc={(np.mean(cross_llr) if cross_llr else float('nan')):.4f}  "
              f"same_dev_auc={np.mean(same_dev):.4f}  (n_buckets={len(rows)})")


if __name__ == "__main__":
    main()
