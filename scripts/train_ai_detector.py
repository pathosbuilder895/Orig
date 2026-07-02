"""
scripts/train_ai_detector.py — train + evaluate the AI-likelihood detector.

The second scoring mode. PR #21's diagnostic proved Original's 103 features
carry real human-vs-AI signal (AUC 0.7402 with a plain classifier at only
n_train=1000, vs 0.6091 for the production per-student Born-rule path); the
bottleneck was the scoring method, which had never seen a labeled example.
This script trains the corpus-level classifier that closes that gap and
freezes it into a committed artifact `original/data/ai_detector_v1.joblib`
that `original/ai_likelihood.py` loads at runtime.

Subcommands (run in this order):

    extract        Extract 103-dim feature matrices from the cached
                   AuTexTification TSVs into .npz caches (parallel; the
                   expensive step — ~8 min per split at 8 workers).
    train          Train the calibrated classifier on the full official
                   train split, select thresholds from train-OOF
                   probabilities, write the artifact.
    eval           Score the official test split ONCE with the frozen
                   artifact. Writes the JSON evidence report.
    eval-raid      Cross-dataset check on the cached RAID sample.
    eval-m4        Cross-dataset check on cached M4 JSONL (optional fetch).
    eval-seminary  The in-domain check that matters for the pilot:
                   20 Claude theology essays vs authentic seminary essays,
                   with ghostwritten and historical prose as separate
                   false-positive rows.

Design decisions (argued in the plan / MODEL_CARD.md):
  - Primary model: isotonic-calibrated HistGradientBoosting — strongest
    sklearn-native tabular model, 1-5 MB artifact, honest predict_proba.
  - Model selection (HGB vs RF fallback) uses train-OOF AUC so the official
    test split is touched exactly once, by the frozen artifact.
  - Thresholds t_elevated / t_strong are the 5% / 1% FPR operating points
    on train-OOF probabilities of HUMAN rows — Neyman-Pearson style, no
    test leakage.
  - y convention: 1 = generated/AI. AI-likelihood is predict_proba[:, 1].
  - Trains on the `text` column only, never `prompt`.

Usage:
    .venv/bin/python scripts/train_ai_detector.py extract --split train --workers 8
    .venv/bin/python scripts/train_ai_detector.py extract --split test  --workers 8
    .venv/bin/python scripts/train_ai_detector.py train
    .venv/bin/python scripts/train_ai_detector.py eval --report validation/diagnostics/ai_detector_eval_$(date +%F).json
    .venv/bin/python scripts/train_ai_detector.py eval-raid
    .venv/bin/python scripts/train_ai_detector.py eval-seminary
"""

from __future__ import annotations

import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent
sys.path.insert(0, str(_ROOT))

# Lock env BEFORE any original.* import (see validation/benchmark/reproducibility.py).
from validation.benchmark.reproducibility import lock_environment  # noqa: E402
ENV_LOCK = lock_environment()

import argparse      # noqa: E402
import csv           # noqa: E402
import hashlib       # noqa: E402
import json          # noqa: E402
import subprocess    # noqa: E402
import time          # noqa: E402
from concurrent.futures import ProcessPoolExecutor  # noqa: E402
from datetime import datetime, timezone             # noqa: E402
from typing import Dict, List, Optional, Sequence   # noqa: E402

import numpy as np   # noqa: E402

AUTEXT_DIR = _ROOT / ".benchmark_cache" / "autextification"
RAID_CSV = _ROOT / ".benchmark_cache" / "raid" / "raid_sample.csv"
M4_DIR = _ROOT / ".benchmark_cache" / "m4"
SEMINARY_CORPUS = _ROOT / "validation" / "corpus"
SEMINARY_MANIFEST = _ROOT / "validation" / "manifest.json"
DEFAULT_ARTIFACT = _ROOT / "original" / "data" / "ai_detector_v1.joblib"

SEED = 1729
SCHEMA_VERSION = 1
DATASET_NAME = "autextification-2023-en-subtask1"
ARTIFACT_SIZE_GATE_MB = 10.0
N_REFERENCE_VECTORS = 8


# ── Shared helpers ────────────────────────────────────────────────────────────

def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _git_sha() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=_ROOT,
            capture_output=True, text=True, timeout=10,
        ).stdout.strip()
    except Exception:
        return "unknown"


def _worker_init() -> None:
    """Each extraction worker locks its own environment before importing original.*"""
    from validation.benchmark.reproducibility import lock_environment as _lock
    _lock()


def _extract_one(text: str) -> List[float]:
    from original.features.pipeline import feature_vector
    return feature_vector(text).tolist()


def _extract_parallel(texts: Sequence[str], workers: int, label: str) -> np.ndarray:
    """(n, FEATURE_DIM) float32 matrix via the production feature pipeline."""
    from original.constants import FEATURE_DIM
    X = np.zeros((len(texts), FEATURE_DIM), dtype=np.float32)
    t0 = time.perf_counter()
    if workers <= 1:
        for i, text in enumerate(texts):
            X[i] = _extract_one(text)
            if (i + 1) % 500 == 0:
                print(f"  [{label}] {i+1}/{len(texts)} "
                      f"({time.perf_counter()-t0:.0f}s)", file=sys.stderr, flush=True)
    else:
        with ProcessPoolExecutor(max_workers=workers, initializer=_worker_init) as ex:
            for i, row in enumerate(ex.map(_extract_one, texts, chunksize=16)):
                X[i] = row
                if (i + 1) % 500 == 0:
                    print(f"  [{label}] {i+1}/{len(texts)} "
                          f"({time.perf_counter()-t0:.0f}s)", file=sys.stderr, flush=True)
    print(f"  [{label}] done: {len(texts)} rows in {time.perf_counter()-t0:.0f}s",
          file=sys.stderr, flush=True)
    return X


def _load_tsv_rows(tsv_path: Path) -> List[dict]:
    with open(tsv_path, encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f, delimiter="\t"))


def _features_npz_path(split: str) -> Path:
    return AUTEXT_DIR / f"features_v1_{split}.npz"


def _load_cached_features(split: str) -> dict:
    """Load an .npz cache, refusing to run if the source TSV changed."""
    npz_path = _features_npz_path(split)
    sidecar = npz_path.with_suffix(".json")
    if not npz_path.exists() or not sidecar.exists():
        raise FileNotFoundError(
            f"No feature cache for split={split!r}. Run: "
            f".venv/bin/python scripts/train_ai_detector.py extract --split {split}"
        )
    meta = json.loads(sidecar.read_text())
    tsv = AUTEXT_DIR / f"{split}.tsv"
    current = _sha256(tsv)
    if meta["source_sha256"] != current:
        raise RuntimeError(
            f"Stale feature cache: {tsv.name} sha256 {current[:12]}… does not match "
            f"sidecar {meta['source_sha256'][:12]}…. Re-run extract --split {split}."
        )
    data = np.load(npz_path, allow_pickle=False)
    return {"X": data["X"], "y": data["y"], "row_id": data["row_id"],
            "domain": data["domain"], "model": data["model"], "meta": meta}


def _tpr_fpr_at_threshold(y: np.ndarray, probs: np.ndarray, thr: float) -> Dict[str, float]:
    pred = probs >= thr
    pos, neg = y == 1, y == 0
    tpr = float(pred[pos].mean()) if pos.any() else float("nan")
    fpr = float(pred[neg].mean()) if neg.any() else float("nan")
    return {"threshold": round(float(thr), 6), "tpr": round(tpr, 4), "fpr": round(fpr, 4)}


def _tpr_at_fpr(y: np.ndarray, probs: np.ndarray, target_fpr: float) -> Optional[float]:
    """Exact TPR at the largest threshold whose FPR ≤ target."""
    neg = probs[y == 0]
    pos = probs[y == 1]
    if neg.size == 0 or pos.size == 0:
        return None
    thr = np.quantile(neg, 1.0 - target_fpr, method="higher")
    return round(float((pos >= thr).mean()), 4)


def _bootstrap_auc_ci(y: np.ndarray, probs: np.ndarray, n_boot: int = 1000,
                      seed: int = SEED) -> Optional[List[float]]:
    """Stratified bootstrap 95% CI (resample pos/neg pools separately)."""
    from sklearn.metrics import roc_auc_score
    pos_idx = np.flatnonzero(y == 1)
    neg_idx = np.flatnonzero(y == 0)
    if pos_idx.size == 0 or neg_idx.size == 0:
        return None
    rng = np.random.default_rng(seed)
    aucs = np.empty(n_boot)
    for b in range(n_boot):
        p = rng.choice(pos_idx, pos_idx.size, replace=True)
        n = rng.choice(neg_idx, neg_idx.size, replace=True)
        idx = np.concatenate([p, n])
        aucs[b] = roc_auc_score(y[idx], probs[idx])
    lo, hi = np.percentile(aucs, [2.5, 97.5])
    return [round(float(lo), 4), round(float(hi), 4)]


def _metric_block(y: np.ndarray, probs: np.ndarray,
                  thresholds: Dict[str, float]) -> Dict[str, object]:
    from sklearn.metrics import roc_auc_score, accuracy_score, brier_score_loss
    block: Dict[str, object] = {
        "n": int(y.size),
        "n_human": int((y == 0).sum()),
        "n_ai": int((y == 1).sum()),
    }
    if (y == 0).any() and (y == 1).any():
        block["auc"] = round(float(roc_auc_score(y, probs)), 4)
        block["brier"] = round(float(brier_score_loss(y, probs)), 4)
        block["accuracy_at_0.5"] = round(float(accuracy_score(y, probs >= 0.5)), 4)
        block["tpr_at_fpr_05"] = _tpr_at_fpr(y, probs, 0.05)
        block["tpr_at_fpr_01"] = _tpr_at_fpr(y, probs, 0.01)
    block["at_t_elevated"] = _tpr_fpr_at_threshold(y, probs, thresholds["elevated"])
    block["at_t_strong"] = _tpr_fpr_at_threshold(y, probs, thresholds["strong"])
    return block


def _load_artifact(model_path: Path) -> dict:
    import joblib
    art = joblib.load(model_path)
    from original.constants import ALL_FEATURE_CODES
    if art["feature_codes"] != list(ALL_FEATURE_CODES):
        raise RuntimeError("Artifact feature_codes do not match ALL_FEATURE_CODES — "
                           "retrain against this checkout.")
    return art


def _write_report(report: dict, out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2) + "\n")
    print(f"  report → {out_path}")


# ── extract ───────────────────────────────────────────────────────────────────

def cmd_extract(args: argparse.Namespace) -> int:
    from original.constants import FEATURE_DIM
    tsv = AUTEXT_DIR / f"{args.split}.tsv"
    if not tsv.exists():
        print(f"[extract] {tsv} not cached. Run: "
              f"python scripts/fetch_benchmark_data.py --autextification", file=sys.stderr)
        return 1
    rows = _load_tsv_rows(tsv)
    if args.limit:
        rows = rows[: args.limit]
    print(f"[extract] split={args.split} rows={len(rows)} workers={args.workers}",
          file=sys.stderr)

    texts = [(r.get("text") or "").strip() for r in rows]
    X = _extract_parallel(texts, args.workers, f"autext-{args.split}")
    y = np.array([1 if (r.get("label") or "").lower() == "generated" else 0
                  for r in rows], dtype=np.int8)
    row_id = np.array([r.get("id") or "" for r in rows])
    domain = np.array([(r.get("domain") or "unknown").lower() for r in rows])
    model = np.array([(r.get("model") or "").strip() for r in rows])

    npz_path = _features_npz_path(args.split)
    np.savez_compressed(npz_path, X=X, y=y, row_id=row_id, domain=domain, model=model)
    sidecar = {
        "source_sha256": _sha256(tsv),
        "n_rows": len(rows),
        "n_human": int((y == 0).sum()),
        "n_ai": int((y == 1).sum()),
        "feature_dim": FEATURE_DIM,
        "limit": args.limit,
        "extracted_at": datetime.now(timezone.utc).isoformat(),
    }
    npz_path.with_suffix(".json").write_text(json.dumps(sidecar, indent=2) + "\n")
    print(f"[extract] wrote {npz_path} ({npz_path.stat().st_size/1e6:.1f} MB) "
          f"human={sidecar['n_human']} ai={sidecar['n_ai']}")
    return 0


# ── train ─────────────────────────────────────────────────────────────────────

def _oof_probs(estimator, X: np.ndarray, y: np.ndarray) -> np.ndarray:
    from sklearn.model_selection import cross_val_predict
    return cross_val_predict(estimator, X, y, cv=5, method="predict_proba",
                             n_jobs=1)[:, 1]


def cmd_train(args: argparse.Namespace) -> int:
    import joblib
    import sklearn
    from sklearn.calibration import CalibratedClassifierCV
    from sklearn.ensemble import HistGradientBoostingClassifier, RandomForestClassifier
    from sklearn.linear_model import LogisticRegression
    from sklearn.metrics import roc_auc_score, brier_score_loss
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler
    from original.constants import (ALL_FEATURE_CODES, TIER17_CODES,
                                    MUSICAL_COMPARISON_CODES, COMPARISON_CODES)

    cache = _load_cached_features("train")
    X, y = cache["X"].astype(np.float64), cache["y"].astype(np.int8)
    print(f"[train] n={len(y)} human={(y==0).sum()} ai={(y==1).sum()}")

    def _hgb():
        return CalibratedClassifierCV(
            HistGradientBoostingClassifier(max_iter=300, learning_rate=0.08,
                                           early_stopping=True, random_state=SEED),
            method="isotonic", cv=5)

    candidates = {
        "hgb_isotonic": _hgb(),
        "rf_depth12": RandomForestClassifier(n_estimators=200, max_depth=12,
                                             random_state=SEED, n_jobs=-1),
        "logreg": make_pipeline(StandardScaler(),
                                LogisticRegression(max_iter=2000, random_state=SEED)),
    }

    # Model selection on train-OOF only — the official test split stays untouched
    # until `eval` scores the frozen artifact exactly once.
    oof: Dict[str, np.ndarray] = {}
    oof_metrics: Dict[str, Dict[str, float]] = {}
    for name, est in candidates.items():
        print(f"[train] OOF cross_val_predict: {name}…", file=sys.stderr)
        t0 = time.perf_counter()
        probs = _oof_probs(est, X, y)
        oof[name] = probs
        oof_metrics[name] = {
            "oof_auc": round(float(roc_auc_score(y, probs)), 4),
            "oof_brier": round(float(brier_score_loss(y, probs)), 4),
        }
        print(f"[train]   {name}: {oof_metrics[name]} "
              f"({time.perf_counter()-t0:.0f}s)", file=sys.stderr)

    primary = "hgb_isotonic"
    if oof_metrics["rf_depth12"]["oof_auc"] > oof_metrics[primary]["oof_auc"] + 0.01:
        primary = "rf_depth12"   # mechanical fallback rule from the plan
    print(f"[train] selected primary: {primary}")

    # Thresholds: Neyman-Pearson operating points on OOF probs of HUMAN rows.
    human_oof = oof[primary][y == 0]
    thresholds = {
        "elevated": float(np.quantile(human_oof, 0.95, method="higher")),  # 5% FPR
        "strong":   float(np.quantile(human_oof, 0.99, method="higher")),  # 1% FPR
    }
    print(f"[train] thresholds (train-OOF): {thresholds}")

    # Fit the shipped model on the FULL train split.
    model = {"hgb_isotonic": _hgb(),
             "rf_depth12": candidates["rf_depth12"],
             "logreg": candidates["logreg"]}[primary]
    print(f"[train] fitting {primary} on full train split…", file=sys.stderr)
    model.fit(X, y)

    human_X = X[y == 0]
    reference_vectors = X[:N_REFERENCE_VECTORS].copy()
    reference_probs = model.predict_proba(reference_vectors)[:, 1]

    artifact = {
        "schema_version": SCHEMA_VERSION,
        "model": model,
        "model_name": primary,
        "feature_codes": list(ALL_FEATURE_CODES),
        "masked_codes": list(TIER17_CODES) + list(MUSICAL_COMPARISON_CODES)
                        + list(COMPARISON_CODES),
        "thresholds": thresholds,
        # std floored at 0.02 (normalized [0,1] features) so near-constant
        # features can't produce absurd indicator z-scores downstream.
        "human_centroid": human_X.mean(axis=0),
        "human_std": np.maximum(human_X.std(axis=0), 0.02),
        "reference_vectors": reference_vectors,
        "reference_probs": reference_probs,
        "provenance": {
            "trained_at": datetime.now(timezone.utc).isoformat(),
            "git_sha": _git_sha(),
            "sklearn_version": sklearn.__version__,
            "numpy_version": np.__version__,
            "seed": SEED,
            "dataset": {
                "name": DATASET_NAME,
                "train_sha256": cache["meta"]["source_sha256"],
                "n_train": int(len(y)),
                "n_human": int((y == 0).sum()),
                "n_ai": int((y == 1).sum()),
            },
            "selection": "train-OOF AUC (test split untouched until eval)",
            "oof_metrics": oof_metrics,
        },
    }

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(artifact, out, compress=3)
    size_mb = out.stat().st_size / 1e6
    print(f"[train] artifact → {out} ({size_mb:.2f} MB)")
    if size_mb > ARTIFACT_SIZE_GATE_MB:
        print(f"[train] FAIL: artifact exceeds {ARTIFACT_SIZE_GATE_MB} MB gate — "
              f"halve max_iter/depth and retrain.", file=sys.stderr)
        return 1
    return 0


# ── eval (official AuTexTification test split — touched exactly once) ─────────

def cmd_eval(args: argparse.Namespace) -> int:
    art = _load_artifact(Path(args.model))
    cache = _load_cached_features("test")
    X, y = cache["X"].astype(np.float64), cache["y"]
    probs = art["model"].predict_proba(X)[:, 1]
    thresholds = art["thresholds"]

    overall = _metric_block(y, probs, thresholds)
    per_domain = {}
    for d in sorted(set(cache["domain"].tolist())):
        m = cache["domain"] == d
        per_domain[d] = _metric_block(y[m], probs[m], thresholds)
    per_generator = {}
    for g in sorted(set(cache["model"].tolist())):
        if g in ("", "NO-MODEL"):
            continue
        m = cache["model"] == g
        per_generator[g] = {
            "n": int(m.sum()),
            "tpr_at_t_elevated": round(float((probs[m] >= thresholds["elevated"]).mean()), 4),
            "tpr_at_t_strong": round(float((probs[m] >= thresholds["strong"]).mean()), 4),
        }

    report = {
        "dataset": f"{DATASET_NAME} (official test split, frozen model + thresholds)",
        "note": ("The official test split is DELIBERATELY cross-domain: train "
                 "domains are legal/tweets/wiki, test domains are news/reviews "
                 "(IberLEF 2023 shared-task design). The train-OOF metrics are "
                 "the in-distribution numbers (comparable to papers that use a "
                 "random split, e.g. StyloAI); this test block is the harder "
                 "unseen-domain generalization number. Both are honest answers "
                 "to different questions."),
        "artifact": str(args.model),
        "model_name": art["model_name"],
        "provenance": {k: v for k, v in art["provenance"].items() if k != "oof_metrics"},
        "oof_metrics_train": art["provenance"]["oof_metrics"],
        "references": {
            "styloai_paper": {"auc": 0.88, "accuracy": 0.81,
                              "source": "arxiv.org/html/2405.10129v1"},
            "original_production_born_rule": {"auc": 0.6091, "source": "PR #20"},
            "diagnostic_rf_n1000": {"auc": 0.7402, "source": "PR #21"},
        },
        "overall": overall,
        "per_domain": per_domain,
        "per_generator_tpr": per_generator,
        "env": ENV_LOCK.__dict__,
    }
    _write_report(report, Path(args.report))
    print(f"[eval] overall: AUC={overall.get('auc')} Brier={overall.get('brier')} "
          f"acc@0.5={overall.get('accuracy_at_0.5')} "
          f"TPR@FPR5%={overall.get('tpr_at_fpr_05')} TPR@FPR1%={overall.get('tpr_at_fpr_01')}")
    return 0


# ── eval-raid ─────────────────────────────────────────────────────────────────

def cmd_eval_raid(args: argparse.Namespace) -> int:
    if not RAID_CSV.exists():
        print(f"[eval-raid] {RAID_CSV} not cached. Run: "
              f"python scripts/fetch_benchmark_data.py --raid", file=sys.stderr)
        return 1
    art = _load_artifact(Path(args.model))
    csv.field_size_limit(sys.maxsize)
    rows = []
    with open(RAID_CSV, encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            text = (r.get("generation") or "").strip()
            model = (r.get("model") or "").strip().lower()
            if len(text) < 10 or not model:
                continue
            rows.append({"text": text, "model": model,
                         "domain": (r.get("domain") or "unknown").lower()})
    if args.limit:
        rows = rows[: args.limit]
    print(f"[eval-raid] rows={len(rows)}", file=sys.stderr)

    X = _extract_parallel([r["text"] for r in rows], args.workers, "raid")
    y = np.array([0 if r["model"] == "human" else 1 for r in rows], dtype=np.int8)
    probs = art["model"].predict_proba(X.astype(np.float64))[:, 1]
    thresholds = art["thresholds"]

    per_generator = {}
    models = np.array([r["model"] for r in rows])
    for g in sorted(set(models.tolist())):
        m = models == g
        per_generator[g] = {
            "n": int(m.sum()),
            "flag_rate_at_t_elevated": round(float((probs[m] >= thresholds["elevated"]).mean()), 4),
            "flag_rate_at_t_strong": round(float((probs[m] >= thresholds["strong"]).mean()), 4),
        }

    report = {
        "dataset": "raid_sample (cross-dataset transfer, frozen model + thresholds)",
        "artifact": str(args.model),
        "note": ("RAID sample is generations-heavy; AUC is only reported when both "
                 "classes are present in usable volume. flag_rate for model=human "
                 "IS the false-positive rate."),
        "overall": _metric_block(y, probs, thresholds),
        "per_generator": per_generator,
        "env": ENV_LOCK.__dict__,
    }
    _write_report(report, Path(args.report))
    print(f"[eval-raid] overall: {report['overall']}")
    return 0


# ── eval-m4 ───────────────────────────────────────────────────────────────────

def cmd_eval_m4(args: argparse.Namespace) -> int:
    files = sorted(M4_DIR.glob("*.jsonl")) if M4_DIR.exists() else []
    if not files:
        print(f"[eval-m4] M4 not cached at {M4_DIR}. Run: "
              f"python scripts/fetch_benchmark_data.py --m4", file=sys.stderr)
        return 1
    art = _load_artifact(Path(args.model))
    rows = []
    per_file_cap = max(50, (args.limit or 4000) // max(len(files), 1))
    for path in files:
        n_taken = 0
        with open(path, encoding="utf-8") as f:
            for line in f:
                if n_taken >= per_file_cap:
                    break
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                text = (rec.get("text") or "").strip()
                if len(text) < 10:
                    continue
                rows.append({"text": text,
                             "y": 1 if int(rec.get("label", 0)) == 1 else 0,
                             "source": path.stem})
                n_taken += 1
    print(f"[eval-m4] rows={len(rows)} from {len(files)} files", file=sys.stderr)

    X = _extract_parallel([r["text"] for r in rows], args.workers, "m4")
    y = np.array([r["y"] for r in rows], dtype=np.int8)
    probs = art["model"].predict_proba(X.astype(np.float64))[:, 1]
    thresholds = art["thresholds"]

    sources = np.array([r["source"] for r in rows])
    per_source = {s: _metric_block(y[sources == s], probs[sources == s], thresholds)
                  for s in sorted(set(sources.tolist()))}

    report = {
        "dataset": "m4 (cross-dataset transfer, frozen model + thresholds)",
        "artifact": str(args.model),
        "overall": _metric_block(y, probs, thresholds),
        "per_source_file": per_source,
        "env": ENV_LOCK.__dict__,
    }
    _write_report(report, Path(args.report))
    print(f"[eval-m4] overall: {report['overall']}")
    return 0


# ── eval-seminary (the in-domain check that matters) ──────────────────────────

def cmd_eval_seminary(args: argparse.Namespace) -> int:
    art = _load_artifact(Path(args.model))
    manifest = json.loads(SEMINARY_MANIFEST.read_text())
    entries = manifest["entries"]

    groups: Dict[str, List[str]] = {
        "ai_generated": [],          # 20 Claude theology essays — TPR target
        "seminary_authentic": [],    # authentic student essays — the FPR that matters
        "ghostwritten": [],          # human-written by someone else — must NOT flag
        "historical_authentic": [],  # archaic public-author prose — known stress case
    }
    for e in entries:
        path = SEMINARY_CORPUS / e["filename"]
        if not path.exists():
            continue
        if e["label"] == "ai_generated":
            groups["ai_generated"].append(str(path))
        elif e["label"] == "ghostwritten":
            groups["ghostwritten"].append(str(path))
        elif e["label"] == "authentic" and e["author_id"].startswith("seminary"):
            groups["seminary_authentic"].append(str(path))
        elif e["label"] == "authentic":
            groups["historical_authentic"].append(str(path))

    texts, group_of = [], []
    for g, paths in groups.items():
        for p in paths:
            texts.append(Path(p).read_text(encoding="utf-8", errors="replace"))
            group_of.append(g)
    print(f"[eval-seminary] " +
          " ".join(f"{g}={len(v)}" for g, v in groups.items()), file=sys.stderr)

    X = _extract_parallel(texts, args.workers, "seminary")
    probs = art["model"].predict_proba(X.astype(np.float64))[:, 1]
    thresholds = art["thresholds"]
    group_arr = np.array(group_of)

    def _flag_rates(mask: np.ndarray) -> Dict[str, object]:
        p = probs[mask]
        return {
            "n": int(mask.sum()),
            "median_prob": round(float(np.median(p)), 4) if mask.any() else None,
            "flag_rate_at_t_elevated": round(float((p >= thresholds["elevated"]).mean()), 4)
                                       if mask.any() else None,
            "flag_rate_at_t_strong": round(float((p >= thresholds["strong"]).mean()), 4)
                                     if mask.any() else None,
        }

    # Primary AUC: authentic seminary essays vs the 20 AI essays.
    core = np.isin(group_arr, ["seminary_authentic", "ai_generated"])
    y_core = (group_arr[core] == "ai_generated").astype(np.int8)
    p_core = probs[core]
    core_block = _metric_block(y_core, p_core, thresholds)
    core_block["auc_bootstrap_ci_95"] = _bootstrap_auc_ci(y_core, p_core)

    report = {
        "dataset": "seminary corpus (IN-DOMAIN transfer — the pilot's actual register)",
        "note": ("Only seminary_authentic vs ai_generated measures the pilot "
                 "register. The 'ghostwritten' group is Madison's Federalist "
                 "papers scored against Hamilton's baseline — genuinely human "
                 "but ARCHAIC prose, so its flag rate belongs with "
                 "historical_authentic as the known archaic-register stress "
                 "case, NOT as a modern-ghostwriter control. High flag rates "
                 "on both archaic groups are the documented failure mode of a "
                 "model trained on modern tweets/legal/wiki text."),
        "artifact": str(args.model),
        "core_seminary_vs_ai": core_block,
        "per_group": {g: _flag_rates(group_arr == g) for g in groups},
        "enablement_gate": {
            "rule": "in-domain AUC >= 0.85 AND flag_rate_at_t_elevated <= 0.05 "
                    "on seminary_authentic (see MODEL_CARD.md)",
            "auc_ok": bool(core_block.get("auc", 0) >= 0.85),
            "fpr_ok": None,  # filled below
        },
        "env": ENV_LOCK.__dict__,
    }
    sem_fpr = report["per_group"]["seminary_authentic"]["flag_rate_at_t_elevated"]
    report["enablement_gate"]["fpr_ok"] = (sem_fpr is not None and sem_fpr <= 0.05)
    report["enablement_gate"]["passes"] = bool(
        report["enablement_gate"]["auc_ok"] and report["enablement_gate"]["fpr_ok"])

    _write_report(report, Path(args.report))
    print(f"[eval-seminary] core AUC={core_block.get('auc')} "
          f"CI95={core_block.get('auc_bootstrap_ci_95')} "
          f"seminary FPR@elevated={sem_fpr} "
          f"gate_passes={report['enablement_gate']['passes']}")
    return 0


# ── CLI ───────────────────────────────────────────────────────────────────────

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    today = datetime.now(timezone.utc).date().isoformat()
    diag = _ROOT / "validation" / "diagnostics"

    p = sub.add_parser("extract", help="Extract feature matrices to .npz cache.")
    p.add_argument("--split", choices=["train", "test"], required=True)
    p.add_argument("--workers", type=int, default=8)
    p.add_argument("--limit", type=int, default=None,
                   help="Row cap for smoke tests (recorded in the sidecar).")
    p.set_defaults(fn=cmd_extract)

    p = sub.add_parser("train", help="Train + calibrate, select thresholds, write artifact.")
    p.add_argument("--out", default=str(DEFAULT_ARTIFACT))
    p.set_defaults(fn=cmd_train)

    p = sub.add_parser("eval", help="Score the official test split once (frozen model).")
    p.add_argument("--model", default=str(DEFAULT_ARTIFACT))
    p.add_argument("--report", default=str(diag / f"ai_detector_eval_{today}.json"))
    p.set_defaults(fn=cmd_eval)

    p = sub.add_parser("eval-raid", help="Cross-dataset check on the RAID sample.")
    p.add_argument("--model", default=str(DEFAULT_ARTIFACT))
    p.add_argument("--report", default=str(diag / f"ai_detector_eval_raid_{today}.json"))
    p.add_argument("--workers", type=int, default=8)
    p.add_argument("--limit", type=int, default=None)
    p.set_defaults(fn=cmd_eval_raid)

    p = sub.add_parser("eval-m4", help="Cross-dataset check on cached M4 JSONL.")
    p.add_argument("--model", default=str(DEFAULT_ARTIFACT))
    p.add_argument("--report", default=str(diag / f"ai_detector_eval_m4_{today}.json"))
    p.add_argument("--workers", type=int, default=8)
    p.add_argument("--limit", type=int, default=4000)
    p.set_defaults(fn=cmd_eval_m4)

    p = sub.add_parser("eval-seminary", help="IN-DOMAIN check: seminary essays vs Claude essays.")
    p.add_argument("--model", default=str(DEFAULT_ARTIFACT))
    p.add_argument("--report", default=str(diag / f"ai_detector_eval_seminary_{today}.json"))
    p.add_argument("--workers", type=int, default=8)
    p.set_defaults(fn=cmd_eval_seminary)

    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
