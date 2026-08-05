"""Binary same-author verification + Delta ablation on the 400-writer
Gutenberg corpus -- a second, independent locked cohort from the PAN
ablation (validation/verify/pan_stack_delta.py), same question: does adding
Burrows' Delta improve recall at a defensible false-positive rate.

Matched-pair binary design (not full-pool ranking): every probe gets
exactly one genuine trial (against its own author) and one deterministic
impostor trial (against one specific different author, offset by 1 in the
locked author list) -- mirrors this repo's existing "binary source-matched
authentication protocol" (see docs/research/CROSS_WORK_AUTHORSHIP_FINDINGS_
2026-08-04.md), which is a balanced 1:1 genuine:impostor construction,
deliberately not the ~1:99 pool-relative imbalance a full cross-product
would give.

Reuses existing infrastructure rather than rebuilding it: pair_signals /
EmbeddingCache / _load_embedder (gutenberg_peer_identity.py,
pan_luar_expert.py) for LUAR + character + content-reduced signals,
delta_trial_signals (this session's new module) for Delta, and
fit_grouped_fusion (validation/stacked/fusion.py) for the same
author-grouped logistic fusion pan_stack_delta.py uses.

    .venv/bin/python -m validation.verify.gutenberg_verify_delta
"""

from __future__ import annotations

from validation.benchmark.reproducibility import lock_environment

ENV_LOCK = lock_environment()

import dataclasses
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from validation.stacked.fusion import Trial, assert_no_group_overlap, fit_grouped_fusion
from validation.verify.binary_auc import auc
from validation.verify.delta_signals import delta_trial_signals
from validation.verify.gutenberg_corpus import load_authors
from validation.verify.gutenberg_peer_identity import pair_signals
from validation.verify.pan_luar_expert import EmbeddingCache, _load_embedder, embed_partitions
from validation.verify.pan_stack import trial_id
from validation.verify.pan_style_expert import SEED, _fit_representations, _threshold_at_fpr

DEFAULT_MANIFEST = Path(".benchmark_cache/gutenberg_authorship/manifest.json")
DEFAULT_EMBEDDING_CACHE = Path(".benchmark_cache/luar/pan_gutenberg_luar_embeddings.npz")


def _matched_trials(authors, matrix: np.ndarray, offset: int = 1):
    """One genuine + one deterministic impostor trial per probe, from a
    pair_signals(authors, authors, ...) matrix of shape (n_probes, n_authors, 3)."""
    n = len(authors)
    genuine, impostor = [], []
    for row in range(matrix.shape[0]):
        source_idx = row // 3
        probe_index = row % 3
        target_idx_impostor = (source_idx + offset) % n
        genuine.append((authors[source_idx].author_id, authors[source_idx].author_id, probe_index, matrix[row, source_idx]))
        impostor.append(
            (authors[target_idx_impostor].author_id, authors[source_idx].author_id, probe_index, matrix[row, target_idx_impostor])
        )
    return genuine, impostor


def _build_trials(authors, matrix, delta_rows):
    genuine, impostor = _matched_trials(authors, matrix)
    trials = []
    for label, rows in ((1, genuine), (0, impostor)):
        for target_id, source_id, probe_index, (luar, char, content) in rows:
            identifier = trial_id(target_id, source_id, probe_index)
            delta = delta_rows[identifier]
            trials.append(
                Trial(
                    trial_id=identifier,
                    author_id=target_id,
                    work_id=f"{source_id}:probe-{probe_index}",
                    label=label,
                    signals={
                        "luar_cosine": float(luar),
                        "character_similarity": float(char),
                        "content_reduced_similarity": float(content),
                        "delta_neg_distance": delta["delta_neg_distance"],
                        "delta_peer_z": delta["delta_peer_z"],
                    },
                )
            )
    return trials


def run(
    *,
    manifest_path: Path = DEFAULT_MANIFEST,
    embedding_cache_path: Path = DEFAULT_EMBEDDING_CACHE,
    output_path: Path | None = None,
    n_development: int = 200,
    n_calibration: int = 100,
    n_locked: int = 100,
) -> dict:
    all_authors = load_authors(manifest_path)
    if len(all_authors) < n_development + n_calibration + n_locked:
        raise ValueError("manifest does not contain enough authors for this split")
    development = all_authors[:n_development]
    calibration = all_authors[n_development : n_development + n_calibration]
    locked = all_authors[n_development + n_calibration : n_development + n_calibration + n_locked]
    partitions = {"development": development, "calibration": calibration, "locked": locked}

    print("[gutenberg-verify-delta] fitting character/content representations...", file=sys.stderr)
    char_vectorizer, style_scaler = _fit_representations(development)

    print("[gutenberg-verify-delta] embedding partitions (LUAR)...", file=sys.stderr)
    cache = EmbeddingCache(embedding_cache_path)
    embedded = embed_partitions(partitions, cache=cache, embedder=_load_embedder())

    print("[gutenberg-verify-delta] building Delta profiles...", file=sys.stderr)
    delta = delta_trial_signals(partitions)

    trials = {}
    for name, authors in partitions.items():
        matrix = pair_signals(
            authors, authors, embedded[name], embedded[name], char_vectorizer, style_scaler
        )
        trials[name] = _build_trials(authors, matrix, delta[name])
        n_genuine = sum(t.label == 1 for t in trials[name])
        n_impostor = sum(t.label == 0 for t in trials[name])
        print(f"[gutenberg-verify-delta] {name}: {n_genuine} genuine, {n_impostor} impostor", file=sys.stderr)

    assert_no_group_overlap(trials["development"], trials["locked"])
    assert_no_group_overlap(trials["calibration"], trials["locked"])

    base_signals = ("luar_cosine", "character_similarity", "content_reduced_similarity")
    delta_signal_names = base_signals + ("delta_neg_distance", "delta_peer_z")

    def _run_fusion(signal_names, target_fpr=(0.01, 0.05, 0.10)):
        fusion = fit_grouped_fusion(
            trials["development"], signal_names=signal_names, n_splits=5, seed=SEED
        )
        calibration_probability = fusion.predict(trials["calibration"])
        locked_probability = fusion.predict(trials["locked"])
        calibration_labels = np.asarray([t.label for t in trials["calibration"]], dtype=np.int8)
        locked_labels = np.asarray([t.label for t in trials["locked"]], dtype=np.int8)
        thresholds = {
            str(t): _threshold_at_fpr(calibration_labels, calibration_probability, t)
            for t in target_fpr
        }
        operating = {}
        for target, threshold in thresholds.items():
            predicted = locked_probability >= threshold
            tp = int(np.sum(predicted & (locked_labels == 1)))
            fp = int(np.sum(predicted & (locked_labels == 0)))
            n_pos = int(np.sum(locked_labels == 1))
            n_neg = int(np.sum(locked_labels == 0))
            operating[target] = {
                "threshold": threshold,
                "precision": tp / max(1, tp + fp),
                "recall": tp / max(1, n_pos),
                "fpr": fp / max(1, n_neg),
                "n_locked_genuine": n_pos,
                "n_locked_impostor": n_neg,
            }
        logistic = fusion.estimator.named_steps["logistic"]
        return {
            "signal_names": list(signal_names),
            "standardized_coefficients": logistic.coef_[0].tolist(),
            "locked_auc": float(auc(locked_labels, locked_probability)),
            "locked_operating_points": operating,
        }

    print("[gutenberg-verify-delta] fitting fusion WITHOUT delta...", file=sys.stderr)
    without_delta = _run_fusion(base_signals)
    print("[gutenberg-verify-delta] fitting fusion WITH delta...", file=sys.stderr)
    with_delta = _run_fusion(delta_signal_names)

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "environment": ENV_LOCK.__dict__,
        "corpus": "400-writer Gutenberg (validation/verify/gutenberg_corpus.py)",
        "split": {"development": n_development, "calibration": n_calibration, "locked": n_locked},
        "trial_design": "matched 1:1 genuine:impostor (deterministic offset-1 impostor pairing)",
        "without_delta": without_delta,
        "with_delta": with_delta,
        "comparison": {
            "auc_delta": with_delta["locked_auc"] - without_delta["locked_auc"],
            "recall_at_1pct_fpr_delta": (
                with_delta["locked_operating_points"]["0.01"]["recall"]
                - without_delta["locked_operating_points"]["0.01"]["recall"]
            ),
        },
    }
    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


if __name__ == "__main__":
    result = run(
        output_path=Path("validation/benchmarks/2026-08-05/gutenberg_verify_delta_ablation.json")
    )
    print(json.dumps(result["comparison"], indent=2))
    for label in ("without_delta", "with_delta"):
        op = result[label]["locked_operating_points"]
        print(
            f"{label}: AUC={result[label]['locked_auc']:.4f} "
            f"recall@1%={op['0.01']['recall']:.3f} recall@5%={op['0.05']['recall']:.3f}"
        )
