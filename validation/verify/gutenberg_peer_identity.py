"""Closed-pool enrolled-peer identity evaluation on Gutenberg writers.

The experiment deliberately separates broad authorship inconsistency from exact
identity.  A writer is named only when the best enrolled LUAR baseline is both
top-ranked and confidence calibration supports naming; writers outside the
comparison pool must remain ``unknown_writer``.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from scipy.sparse import csr_matrix, vstack

from validation.verify.gutenberg_corpus import load_authors
from validation.verify.pan_luar_expert import EmbeddingCache, _load_embedder, embed_partitions
from validation.verify.pan_style_expert import _fit_representations, content_reduced_signature


def _normalise(values: np.ndarray, axis: int) -> np.ndarray:
    return values / np.maximum(np.linalg.norm(values, axis=axis, keepdims=True), 1e-12)


def pair_signals(
    enrolled_authors,
    source_authors,
    enrolled_embeddings: dict[str, object],
    source_embeddings: dict[str, object],
    char_vectorizer,
    style_scaler,
) -> np.ndarray:
    """Return rectangular LUAR/character/content-reduced candidate signals."""
    baselines = _normalise(np.asarray(enrolled_embeddings["baseline"], dtype=float), 1)
    probes = _normalise(np.asarray(source_embeddings["probes"], dtype=float), 2)
    flat = probes.reshape(-1, probes.shape[-1])
    luar = flat @ baselines.T

    baseline_texts = [text for author in enrolled_authors for text in author.baselines]
    probe_texts = [text for author in source_authors for text in author.probes]
    baseline_char = char_vectorizer.transform(baseline_texts)
    probe_char = char_vectorizer.transform(probe_texts)
    baseline_style = style_scaler.transform(
        np.stack([content_reduced_signature(text) for text in baseline_texts])
    )
    probe_style = style_scaler.transform(
        np.stack([content_reduced_signature(text) for text in probe_texts])
    )
    char_centroids = []
    style_centroids = []
    for index in range(len(enrolled_authors)):
        block = slice(index * 3, (index + 1) * 3)
        centroid = csr_matrix(baseline_char[block].mean(axis=0))
        norm = np.sqrt(float(centroid.multiply(centroid).sum()))
        char_centroids.append(centroid / max(norm, 1e-12))
        style_centroids.append(baseline_style[block].mean(axis=0))
    char = (probe_char @ vstack(char_centroids).T).toarray()
    content = -np.mean(
        np.abs(probe_style[:, None, :] - np.stack(style_centroids)[None, :, :]), axis=2
    )
    return np.stack((luar, char, content), axis=2)


def identity_features_from_scores(
    ranking_scores: np.ndarray,
    pair_values: np.ndarray,
    enrolled_embeddings: dict[str, object],
    source_embeddings: dict[str, object],
) -> tuple[np.ndarray, np.ndarray]:
    """Return confidence features and top candidate from learned pair scores."""
    documents = _normalise(np.asarray(enrolled_embeddings["baseline_documents"], dtype=float), 2)
    probes = _normalise(np.asarray(source_embeddings["probes"], dtype=float), 2)
    flat = probes.reshape(-1, probes.shape[-1])
    similarities = ranking_scores
    order = np.argsort(ranking_scores, axis=1)[:, ::-1]
    top = order[:, 0]
    runner = order[:, 1]
    row = np.arange(len(flat))
    top_score = similarities[row, top]
    runner_score = similarities[row, runner]
    peer_mean = similarities.mean(axis=1)
    peer_std = np.maximum(similarities.std(axis=1), 1e-9)

    selected_documents = documents[top]
    document_scores = np.einsum("nd,nbd->nb", flat, selected_documents)
    cohesion = np.einsum("nbd,ncd->nbc", selected_documents, selected_documents)
    upper = np.triu_indices(selected_documents.shape[1], k=1)
    cohesion_values = cohesion[:, upper[0], upper[1]]
    features = np.column_stack(
        (
            top_score,
            top_score - runner_score,
            (top_score - peer_mean) / peer_std,
            pair_values[row, top, 0],
            pair_values[row, top, 1],
            pair_values[row, top, 2],
            document_scores.mean(axis=1),
            document_scores.min(axis=1),
            document_scores.std(axis=1),
            cohesion_values.mean(axis=1),
            cohesion_values.min(axis=1),
            document_scores.mean(axis=1) - cohesion_values.mean(axis=1),
        )
    )
    return features, top


def identity_features(
    enrolled_embeddings: dict[str, object], source_embeddings: dict[str, object]
) -> tuple[np.ndarray, np.ndarray]:
    """Compatibility helper using raw LUAR cosine as the ranking score."""
    baselines = _normalise(np.asarray(enrolled_embeddings["baseline"], dtype=float), 1)
    probes = _normalise(np.asarray(source_embeddings["probes"], dtype=float), 2)
    luar = probes.reshape(-1, probes.shape[-1]) @ baselines.T
    return identity_features_from_scores(
        luar, np.repeat(luar[:, :, None], 3, axis=2), enrolled_embeddings, source_embeddings
    )


def _fit_confidence(X: np.ndarray, y: np.ndarray) -> Pipeline:
    model = Pipeline(
        (
            ("scale", StandardScaler()),
            (
                "logistic",
                LogisticRegression(C=0.25, class_weight="balanced", max_iter=2_000),
            ),
        )
    )
    model.fit(X, y)
    return model


def select_threshold(
    known_correct: np.ndarray,
    known_probability: np.ndarray,
    outside_probability: np.ndarray,
    *,
    min_precision: float = 0.90,
    max_outside_rate: float = 0.01,
) -> float:
    candidates = np.r_[np.nextafter(max(known_probability.max(), outside_probability.max()), np.inf),
                       np.unique(np.r_[known_probability, outside_probability])]
    best = None
    for threshold in candidates:
        known_selected = known_probability >= threshold
        outside_selected = outside_probability >= threshold
        named = int(known_selected.sum())
        precision = float(known_correct[known_selected].mean()) if named else 1.0
        outside_rate = float(outside_selected.mean())
        recall = float((known_selected & known_correct).sum() / len(known_correct))
        if precision >= min_precision and outside_rate <= max_outside_rate:
            key = (recall, named, threshold)
            if best is None or key > best[0]:
                best = (key, float(threshold))
    if best is None:
        return float(np.nextafter(max(known_probability.max(), outside_probability.max()), np.inf))
    return best[1]


def select_two_axis_rule(
    known_correct: np.ndarray,
    known_probability: np.ndarray,
    known_margin: np.ndarray,
    outside_probability: np.ndarray,
    outside_margin: np.ndarray,
    *,
    max_outside_rate: float,
) -> tuple[float, float]:
    """Select confidence and uniqueness thresholds on calibration only."""
    probability_grid = np.r_[
        np.nextafter(max(known_probability.max(), outside_probability.max()), np.inf),
        np.unique(np.r_[known_probability, outside_probability]),
    ]
    margin_grid = np.r_[0.0, np.unique(np.r_[known_margin, outside_margin])]
    best = None
    for probability_threshold in probability_grid:
        probability_known = known_probability >= probability_threshold
        probability_outside = outside_probability >= probability_threshold
        for margin_threshold in margin_grid:
            selected_known = probability_known & (known_margin >= margin_threshold)
            selected_outside = probability_outside & (outside_margin >= margin_threshold)
            precision = (
                float(known_correct[selected_known].mean()) if selected_known.any() else 1.0
            )
            outside_rate = float(selected_outside.mean())
            recall = float((selected_known & known_correct).sum() / len(known_correct))
            if precision >= 0.90 and outside_rate <= max_outside_rate:
                key = (recall, int(selected_known.sum()), probability_threshold, margin_threshold)
                if best is None or key > best[0]:
                    best = (key, float(probability_threshold), float(margin_threshold))
    if best is None:
        return float(np.nextafter(probability_grid.max(), np.inf)), float("inf")
    return best[1], best[2]


def _evaluate(
    correct: np.ndarray,
    probability: np.ndarray,
    threshold: float,
    *,
    outside: bool,
    margin: np.ndarray | None = None,
    margin_threshold: float = 0.0,
) -> dict:
    selected = probability >= threshold
    if margin is not None:
        selected &= margin >= margin_threshold
    return {
        "support": int(len(correct)),
        "selected": int(selected.sum()),
        "top1_accuracy": float(correct.mean()) if not outside else None,
        "precision_exact_identity": (
            float(correct[selected].mean()) if selected.any() and not outside else None
        ),
        "recall_exact_identity": (
            float((selected & correct).sum() / len(correct)) if not outside else None
        ),
        "outside_writer_naming_rate": float(selected.mean()) if outside else None,
    }


def run(
    manifest_path: Path,
    embedding_cache_path: Path,
    output_path: Path | None = None,
    calibration_outside_naming_budget: int = 1,
) -> dict:
    authors = load_authors(manifest_path)
    if len(authors) < 400:
        raise ValueError("peer identity protocol requires 400 manifest authors")
    partitions = {
        "development_enrolled": authors[:50],
        "development_outside": authors[100:150],
        "calibration_enrolled": authors[50:100],
        "calibration_outside": authors[150:200],
        "locked_outside": authors[-200:-100],
        "locked_enrolled": authors[-100:],
    }
    cache = EmbeddingCache(embedding_cache_path)
    embedded = embed_partitions(partitions, cache=cache, embedder=_load_embedder())

    char_vectorizer, style_scaler = _fit_representations(partitions["development_enrolled"])
    development_pairs = pair_signals(
        partitions["development_enrolled"],
        partitions["development_enrolled"],
        embedded["development_enrolled"],
        embedded["development_enrolled"],
        char_vectorizer,
        style_scaler,
    )
    pair_truth = np.zeros(development_pairs.shape[:2], dtype=bool)
    pair_truth[np.arange(len(pair_truth)), np.repeat(np.arange(50), 3)] = True
    ranker = _fit_confidence(development_pairs.reshape(-1, 3), pair_truth.ravel())

    def ranked_features(enrolled: str, source: str) -> tuple[np.ndarray, np.ndarray]:
        values = pair_signals(
            partitions[enrolled],
            partitions[source],
            embedded[enrolled],
            embedded[source],
            char_vectorizer,
            style_scaler,
        )
        scores = ranker.predict_proba(values.reshape(-1, 3))[:, 1].reshape(values.shape[:2])
        return identity_features_from_scores(
            scores, values, embedded[enrolled], embedded[source]
        )

    def known(name: str) -> tuple[np.ndarray, np.ndarray]:
        features, top = ranked_features(name, name)
        truth = np.repeat(np.arange(len(partitions[name])), 3)
        return features, top == truth

    def outside(enrolled: str, source: str) -> np.ndarray:
        return ranked_features(enrolled, source)[0]

    dev_known_X, dev_correct = known("development_enrolled")
    dev_outside_X = outside("development_enrolled", "development_outside")
    model = _fit_confidence(
        np.vstack((dev_known_X, dev_outside_X)),
        np.r_[dev_correct, np.zeros(len(dev_outside_X), dtype=bool)],
    )

    cal_known_X, cal_correct = known("calibration_enrolled")
    cal_outside_X = outside("calibration_enrolled", "calibration_outside")
    cal_known_probability = model.predict_proba(cal_known_X)[:, 1]
    cal_outside_probability = model.predict_proba(cal_outside_X)[:, 1]
    if calibration_outside_naming_budget < 0:
        raise ValueError("calibration outside naming budget must be non-negative")
    threshold = select_threshold(
        cal_correct,
        cal_known_probability,
        cal_outside_probability,
        max_outside_rate=calibration_outside_naming_budget / len(cal_outside_probability),
    )

    lock_known_X, lock_correct = known("locked_enrolled")
    lock_outside_X = outside("locked_enrolled", "locked_outside")
    lock_known_probability = model.predict_proba(lock_known_X)[:, 1]
    lock_outside_probability = model.predict_proba(lock_outside_X)[:, 1]
    calibration_known = _evaluate(
        cal_correct,
        cal_known_probability,
        threshold,
        outside=False,
    )
    calibration_outside = _evaluate(
        np.zeros(len(cal_outside_probability), dtype=bool),
        cal_outside_probability,
        threshold,
        outside=True,
    )
    locked_known = _evaluate(
        lock_correct,
        lock_known_probability,
        threshold,
        outside=False,
    )
    locked_outside = _evaluate(
        np.zeros(len(lock_outside_probability), dtype=bool),
        lock_outside_probability,
        threshold,
        outside=True,
    )
    conditions = {
        "known_precision_at_least_0_90": locked_known["precision_exact_identity"] is not None
        and locked_known["precision_exact_identity"] >= 0.90,
        "known_recall_at_least_0_30": locked_known["recall_exact_identity"] >= 0.30,
        "outside_naming_rate_at_most_0_01": locked_outside["outside_writer_naming_rate"] <= 0.01,
        "at_least_100_enrolled_writers": len(partitions["locked_enrolled"]) >= 100,
    }
    result = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "protocol": {
            "partition_authors": {name: [a.author_id for a in rows] for name, rows in partitions.items()},
            "three_baselines_and_three_probes": True,
            "outside_pool_policy": "unknown_writer",
            "selection": "confidence model fit on development; threshold selected on calibration only",
            "calibration_outside_naming_budget": calibration_outside_naming_budget,
        },
        "model": {
            "identity_ranker": "top enrolled learned pair score",
            "pair_ranker": "development-fitted LUAR/character/content-reduced logistic",
            "confidence_features": 12,
            "threshold": threshold,
        },
        "calibration": {"known": calibration_known, "outside": calibration_outside},
        "locked": {"known": locked_known, "outside": locked_outside},
        "promotion_gate": {
            "passed": all(conditions.values()),
            "conditions": conditions,
            "decision": "eligible_for_report_only_review" if all(conditions.values()) else "validation_only",
        },
    }
    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, default=Path(".benchmark_cache/gutenberg_authorship/manifest.json"))
    parser.add_argument("--embedding-cache", type=Path, default=Path(".benchmark_cache/luar/pan_gutenberg_luar_embeddings.npz"))
    parser.add_argument("--output", type=Path, default=Path("validation/verify/gutenberg_peer_identity_lock100.json"))
    parser.add_argument("--calibration-outside-naming-budget", type=int, default=1)
    args = parser.parse_args()
    result = run(
        args.manifest,
        args.embedding_cache,
        args.output,
        calibration_outside_naming_budget=args.calibration_outside_naming_budget,
    )
    print(json.dumps(result["promotion_gate"], indent=2))


if __name__ == "__main__":
    main()
