"""
validation/diagnostics/autext_feature_probe.py — features vs. scoring method.

PR #20 measured AUC=0.6091 on AuTexTification via Original's PRODUCTION
scoring path — the per-student Born-rule density matrix, comparing each
submission to a 3-essay baseline. That is far below StyloAI's reported
0.88 AUC / 81% accuracy on the identical corpus using a supervised
Random Forest.

That comparison conflates two different things:

  1. Original's FEATURES — the 103-dim stylometric vector
     (original/features/pipeline.py:feature_vector).
  2. Original's SCORING METHOD — a density-matrix identity-verification
     mechanism that has never seen a single labeled human-vs-AI example.
     It was never trained for this task; it approximates it by proxy
     ("does this match one specific person's baseline?").

This script separates them. In parallel, on the SAME train/test split:

  A. Extract Original's 103 features for each row, train a
     RandomForestClassifier (StyloAI's own classifier choice) directly
     on those features.
  B. Extract a classifier-agnostic, feature-set-agnostic stylometric
     baseline — TF-IDF character 3-5-grams, the same family of signal
     classic Burrows'-Delta-style authorship work uses, independent of
     Original's tier design — and train the SAME RandomForestClassifier
     on that.

Interpretation:
  - If (A) gets close to StyloAI's 0.88: Original's FEATURES are fine.
    The production scoring method (per-student Born-rule density
    matrix, never trained on this task) is the bottleneck — an
    architecture question, not a feature-engineering one.
  - If (A) is still far below 0.88 (and/or below (B)): the 103 feature
    tiers themselves lack short-text AI-detection signal relative to a
    generic character-n-gram baseline — a bigger lift (new features).

Usage:
    python -m validation.diagnostics.autext_feature_probe --n-train 1000 --n-test 400
"""

from __future__ import annotations

# Lock env BEFORE any original.* import.
from validation.benchmark.reproducibility import lock_environment  # noqa: E402
ENV_LOCK = lock_environment()

import argparse
import csv
import json
import random
import sys
import time
from pathlib import Path
from typing import List, Tuple

import numpy as np

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent.parent
sys.path.insert(0, str(_ROOT))

from original.features.pipeline import feature_vector
from original.constants import FEATURE_DIM

AUTEXT_DIR = _ROOT / ".benchmark_cache" / "autextification"
BENCHMARK_SEED = 1729


def _load_rows(tsv_path: Path) -> List[dict]:
    with open(tsv_path, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f, delimiter="\t"))


def _stratified_sample(rows: List[dict], n: int, seed: int) -> List[dict]:
    """Balanced human/generated sample, drawn from all domains pooled."""
    rng = random.Random(seed)
    human = [r for r in rows if (r.get("label") or "").lower() == "human"]
    generated = [r for r in rows if (r.get("label") or "").lower() == "generated"]
    half = n // 2
    rng.shuffle(human)
    rng.shuffle(generated)
    sample = human[:half] + generated[:half]
    rng.shuffle(sample)
    return sample


def _extract_original_features(rows: List[dict], label: str) -> np.ndarray:
    """(n, FEATURE_DIM) matrix via Original's production feature pipeline."""
    X = np.zeros((len(rows), FEATURE_DIM), dtype=np.float64)
    t0 = time.perf_counter()
    for i, row in enumerate(rows):
        X[i] = feature_vector(row["text"])
        if (i + 1) % 100 == 0:
            elapsed = time.perf_counter() - t0
            print(f"  [{label}] {i+1}/{len(rows)} features extracted "
                  f"({elapsed:.0f}s elapsed)", file=sys.stderr, flush=True)
    return X


def _y(rows: List[dict]) -> np.ndarray:
    return np.array([1 if (r.get("label") or "").lower() == "human" else 0
                     for r in rows], dtype=np.int8)


def run(*, n_train: int, n_test: int, seed: int = BENCHMARK_SEED,
       out_path: Path = None) -> dict:
    from sklearn.ensemble import RandomForestClassifier
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.metrics import roc_auc_score, accuracy_score, brier_score_loss

    print("[probe] loading AuTexTification TSVs…", file=sys.stderr)
    train_rows_all = _load_rows(AUTEXT_DIR / "train.tsv")
    test_rows_all = _load_rows(AUTEXT_DIR / "test.tsv")
    if not train_rows_all or not test_rows_all:
        raise FileNotFoundError(
            f"AuTexTification not cached at {AUTEXT_DIR}. Run: "
            f"python scripts/fetch_benchmark_data.py --autextification"
        )

    train_rows = _stratified_sample(train_rows_all, n_train, seed)
    test_rows = _stratified_sample(test_rows_all, n_test, seed + 1)
    print(f"[probe] train={len(train_rows)} test={len(test_rows)} "
          f"(balanced human/generated, pooled across domains)", file=sys.stderr)

    y_train, y_test = _y(train_rows), _y(test_rows)

    # ── A. Original's 103 features ──
    print("[probe] extracting Original's 103 features (train)…", file=sys.stderr)
    Xa_train = _extract_original_features(train_rows, "original-train")
    print("[probe] extracting Original's 103 features (test)…", file=sys.stderr)
    Xa_test = _extract_original_features(test_rows, "original-test")

    clf_a = RandomForestClassifier(n_estimators=200, random_state=seed, n_jobs=-1)
    clf_a.fit(Xa_train, y_train)
    proba_a = clf_a.predict_proba(Xa_test)[:, 1]
    pred_a = (proba_a >= 0.5).astype(np.int8)

    result_a = {
        "auc": round(float(roc_auc_score(y_test, proba_a)), 4),
        "accuracy": round(float(accuracy_score(y_test, pred_a)), 4),
        "brier": round(float(brier_score_loss(y_test, proba_a)), 4),
    }
    print(f"[probe] (A) Original 103 features + RandomForest: {result_a}", file=sys.stderr)

    # ── B. TF-IDF character n-gram baseline (feature-set-agnostic) ──
    print("[probe] fitting TF-IDF char-ngram baseline…", file=sys.stderr)
    vec = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5), max_features=3000)
    Xb_train = vec.fit_transform([r["text"] for r in train_rows])
    Xb_test = vec.transform([r["text"] for r in test_rows])

    clf_b = RandomForestClassifier(n_estimators=200, random_state=seed, n_jobs=-1)
    clf_b.fit(Xb_train, y_train)
    proba_b = clf_b.predict_proba(Xb_test)[:, 1]
    pred_b = (proba_b >= 0.5).astype(np.int8)

    result_b = {
        "auc": round(float(roc_auc_score(y_test, proba_b)), 4),
        "accuracy": round(float(accuracy_score(y_test, pred_b)), 4),
        "brier": round(float(brier_score_loss(y_test, proba_b)), 4),
    }
    print(f"[probe] (B) TF-IDF char-ngram + RandomForest: {result_b}", file=sys.stderr)

    # ── Feature importance from (A) — which of Original's 103 features
    #    actually carry AI-detection signal, for follow-up. ──
    from original.constants import ALL_FEATURE_CODES
    importances = sorted(
        zip(ALL_FEATURE_CODES, clf_a.feature_importances_),
        key=lambda kv: -kv[1],
    )[:15]

    summary = {
        "n_train": len(train_rows),
        "n_test": len(test_rows),
        "seed": seed,
        "styloai_reference": {"auc": 0.88, "accuracy": 0.81,
                              "source": "arxiv.org/html/2405.10129v1"},
        "original_production_reference": {
            "auc": 0.6091, "brier": 0.2771,
            "source": "PR #20, validation/wide/autextification.py, "
                     "Born-rule per-student scoring",
        },
        "A_original_features_rf": result_a,
        "B_tfidf_char_ngram_rf": result_b,
        "top_15_feature_importances_A": [
            {"feature": f, "importance": round(float(imp), 4)}
            for f, imp in importances
        ],
        "env": ENV_LOCK.__dict__,
    }

    if out_path:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(summary, indent=2))

    print()
    print("┌─────────────────────────────────────────────────────────────────┐")
    print("│  AuTexTification: features vs. scoring method                    │")
    print(f"│  train={len(train_rows):<5} test={len(test_rows):<5}                                          │")
    print("│                                                                    │")
    print(f"│  StyloAI (paper, full 33k train)     AUC=0.8800  acc=0.8100      │")
    print(f"│  Original production (PR #20)        AUC=0.6091  Brier=0.2771    │")
    print(f"│  (A) Original 103 feat + RF (n={n_train:<5})  AUC={result_a['auc']:.4f}  acc={result_a['accuracy']:.4f}  │")
    print(f"│  (B) TF-IDF char-ngram + RF (n={n_train:<5})  AUC={result_b['auc']:.4f}  acc={result_b['accuracy']:.4f}  │")
    print("│                                                                    │")
    verdict = ("features are fine — scoring method is the bottleneck"
              if result_a["auc"] >= result_b["auc"] - 0.03
              else "features lack signal relative to a generic baseline")
    print(f"│  Verdict: {verdict}")
    print("└─────────────────────────────────────────────────────────────────┘")
    if out_path:
        print(f"  Report: {out_path}")

    return summary


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--n-train", type=int, default=1000,
                    help="Balanced train sample size (default 1000).")
    ap.add_argument("--n-test", type=int, default=400,
                    help="Balanced test sample size (default 400).")
    ap.add_argument("--out", type=Path,
                    default=_ROOT / "validation" / "diagnostics" /
                            "autext_feature_probe_2026-07-02.json")
    args = ap.parse_args(argv)
    try:
        run(n_train=args.n_train, n_test=args.n_test, out_path=args.out)
    except Exception as e:
        print(f"[probe] FAIL: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
