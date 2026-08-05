"""PADBen adapter and domain-held-out cause-classification stress test.

PADBen is sentence-level. We bundle adjacent records from the same source only
to give Original's document features enough text; the resulting numbers are a
stress test, not an essay-level promotion result. Variants sharing source rows
remain in the same bundle and therefore the same fold.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

import numpy as np
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import confusion_matrix, f1_score, precision_recall_fscore_support
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from validation.stacked.fusion import select_cause


HUMAN = "human"
DIRECT_AI = "direct_ai"
HUMANIZED_AI = "humanized_ai"
CAUSES = (HUMAN, DIRECT_AI, HUMANIZED_AI)

TYPE_FIELDS = {
    HUMAN: ("human_original_text(type1)", "human_paraphrased_text(type3)"),
    DIRECT_AI: ("llm_generated_text(type2)",),
    HUMANIZED_AI: (
        "llm_paraphrased_generated_text(type5)-1st",
        "llm_paraphrased_generated_text(type5)-3rd",
    ),
}


@dataclass(frozen=True)
class PadBenBundle:
    bundle_id: str
    source: str
    cause: str
    variant: str
    row_ids: tuple[int, ...]
    text: str


def bundle_padben_records(
    records: Sequence[dict],
    *,
    rows_per_bundle: int = 12,
    max_bundles_per_source_variant: int | None = None,
) -> list[PadBenBundle]:
    """Bundle same-source sentences while preserving paired group identity."""

    if rows_per_bundle < 2:
        raise ValueError("rows_per_bundle must be at least 2")
    by_source: dict[str, list[dict]] = {}
    for record in records:
        source = str(record.get("dataset_source") or "unknown")
        by_source.setdefault(source, []).append(record)

    bundles: list[PadBenBundle] = []
    for source, rows in sorted(by_source.items()):
        rows = sorted(rows, key=lambda row: int(row["idx"]))
        blocks = [rows[i : i + rows_per_bundle] for i in range(0, len(rows), rows_per_bundle)]
        blocks = [block for block in blocks if len(block) == rows_per_bundle]
        if max_bundles_per_source_variant is not None:
            blocks = blocks[:max_bundles_per_source_variant]
        for block_number, block in enumerate(blocks):
            ids = tuple(int(row["idx"]) for row in block)
            paired_group = f"{source}:{block_number:05d}"
            for cause, fields in TYPE_FIELDS.items():
                for field in fields:
                    parts = [str(row.get(field) or "").strip() for row in block]
                    if any(not part for part in parts):
                        continue
                    # Preserve iteration depth (1st vs 3rd); collapsing at the
                    # first parenthesis made two materially different attacks
                    # indistinguishable in reports.
                    variant = field
                    bundles.append(
                        PadBenBundle(
                            bundle_id=f"{paired_group}:{variant}",
                            source=source,
                            cause=cause,
                            variant=variant,
                            row_ids=ids,
                            text=" ".join(parts),
                        )
                    )
    return bundles


def _model(seed: int) -> Pipeline:
    return Pipeline(
        [
            ("impute", SimpleImputer(strategy="median", add_indicator=True)),
            ("scale", StandardScaler()),
            (
                "logistic",
                LogisticRegression(
                    C=0.25,
                    class_weight="balanced",
                    max_iter=2500,
                    random_state=seed,
                ),
            ),
        ]
    )


def evaluate_cause_matrix(
    X: np.ndarray,
    labels: Sequence[str],
    sources: Sequence[str],
    *,
    min_probability: float = 0.60,
    min_margin: float = 0.10,
    target_precision: float = 0.90,
    min_calibration_predictions: int = 5,
    seed: int = 1729,
) -> dict:
    """Leave-one-source-domain-out evaluation with selective abstention."""

    X = np.asarray(X, dtype=np.float64)
    y = np.asarray(labels, dtype=object)
    groups = np.asarray(sources, dtype=object)
    unique_sources = sorted(set(groups.tolist()))
    if len(unique_sources) < 2:
        raise ValueError("need at least two source domains")
    if set(y.tolist()) != set(CAUSES):
        raise ValueError(f"expected exactly causes {CAUSES}")
    if len(X) != len(y) or len(y) != len(groups):
        raise ValueError("X, labels, and sources must have equal length")

    predicted = np.empty(len(y), dtype=object)
    confidence = np.zeros(len(y), dtype=np.float64)
    folds: dict[str, dict] = {}
    for fold_index, held_out in enumerate(unique_sources):
        test = groups == held_out
        train = ~test
        if set(y[train].tolist()) != set(CAUSES):
            raise ValueError(f"training without {held_out} lacks a cause class")
        # Inner source-held-out predictions choose per-cause thresholds. This
        # avoids tuning abstention on the outer test domain. With only three
        # PADBen domains each inner model trains on one domain, deliberately a
        # harsh estimate of cross-domain precision.
        calibration_probs: list[np.ndarray] = []
        calibration_y: list[np.ndarray] = []
        train_sources = sorted(set(groups[train].tolist()))
        for inner_index, calibration_source in enumerate(train_sources):
            inner_cal = groups == calibration_source
            inner_train = train & ~inner_cal
            if set(y[inner_train].tolist()) != set(CAUSES):
                continue
            inner = _model(seed + fold_index * 10 + inner_index)
            inner.fit(X[inner_train], y[inner_train])
            inner_raw = inner.predict_proba(X[inner_cal])
            inner_classes = inner.named_steps["logistic"].classes_
            aligned = np.zeros((int(inner_cal.sum()), len(CAUSES)), dtype=np.float64)
            for class_index, cause in enumerate(CAUSES):
                aligned[:, class_index] = inner_raw[:, list(inner_classes).index(cause)]
            calibration_probs.append(aligned)
            calibration_y.append(y[inner_cal])
        thresholds = _precision_thresholds(
            np.concatenate(calibration_probs),
            np.concatenate(calibration_y),
            target_precision=target_precision,
            min_predictions=min_calibration_predictions,
            floor=min_probability,
        )

        model = _model(seed + fold_index)
        model.fit(X[train], y[train])
        probs = model.predict_proba(X[test])
        classes = model.named_steps["logistic"].classes_
        test_indices = np.flatnonzero(test)
        abstained = 0
        for local_index, row_index in enumerate(test_indices):
            probability_map = dict(zip(classes, probs[local_index]))
            best_label = max(probability_map, key=probability_map.get)
            decision = select_cause(
                probability_map,
                min_probability=thresholds[best_label],
                min_margin=min_margin,
            )
            predicted[row_index] = decision.label
            confidence[row_index] = decision.probability
            abstained += int(decision.abstained)
        folds[held_out] = {
            "n": int(test.sum()),
            "abstained": abstained,
            "precision_calibrated_thresholds": thresholds,
        }

    covered = predicted != "unknown_other"
    macro_all = f1_score(y, predicted, labels=list(CAUSES), average="macro", zero_division=0)
    macro_covered = (
        f1_score(y[covered], predicted[covered], labels=list(CAUSES), average="macro", zero_division=0)
        if covered.any()
        else 0.0
    )
    precision, recall, f1, support = precision_recall_fscore_support(
        y, predicted, labels=list(CAUSES), zero_division=0
    )
    return {
        "n": len(y),
        "sources": unique_sources,
        "coverage": round(float(covered.mean()), 4),
        "selective_accuracy": round(float((predicted[covered] == y[covered]).mean()), 4)
        if covered.any()
        else None,
        "macro_f1_with_abstention_as_error": round(float(macro_all), 4),
        "macro_f1_covered": round(float(macro_covered), 4),
        "per_class": {
            cause: {
                "precision": round(float(precision[i]), 4),
                "recall": round(float(recall[i]), 4),
                "f1": round(float(f1[i]), 4),
                "support": int(support[i]),
            }
            for i, cause in enumerate(CAUSES)
        },
        "confusion_labels": [*CAUSES, "unknown_other"],
        "confusion": confusion_matrix(
            y, predicted, labels=[*CAUSES, "unknown_other"]
        ).tolist(),
        "prediction_counts": dict(Counter(predicted.tolist())),
        "mean_confidence": round(float(confidence.mean()), 4),
        "folds": folds,
    }


def evaluate_ai_subtypes(
    X: np.ndarray,
    labels: Sequence[str],
    sources: Sequence[str],
    *,
    frozen_ai_index: int = -1,
    frozen_ai_threshold: float = 0.738126,
    target_precision: float = 0.90,
    min_predictions: int = 5,
    seed: int = 1729,
) -> dict:
    """Nested source-held-out direct-vs-humanized selective classifier."""

    X = np.asarray(X, dtype=np.float64)
    labels = np.asarray(labels, dtype=object)
    sources = np.asarray(sources, dtype=object)
    keep = np.isin(labels, [DIRECT_AI, HUMANIZED_AI])
    X, labels, sources = X[keep], labels[keep], sources[keep]
    y = labels == HUMANIZED_AI
    predicted = np.full(len(y), "unknown_other", dtype=object)
    fold_details = {}

    for outer_index, held_out in enumerate(sorted(set(sources.tolist()))):
        test = sources == held_out
        outer_train = ~test
        inner_prob, inner_y, inner_ai = [], [], []
        for inner_index, calibration_source in enumerate(sorted(set(sources[outer_train]))):
            calibration = sources == calibration_source
            train = outer_train & ~calibration
            model = _model(seed + outer_index * 10 + inner_index)
            model.fit(X[train], y[train])
            # _model's labels are bool; probability for True is class index 1.
            inner_prob.extend(model.predict_proba(X[calibration])[:, 1].tolist())
            inner_y.extend(y[calibration].tolist())
            inner_ai.extend(X[calibration, frozen_ai_index].tolist())
        inner_prob = np.asarray(inner_prob)
        inner_y = np.asarray(inner_y, dtype=bool)
        inner_ai = np.asarray(inner_ai)

        humanized_threshold = one_sided_precision_threshold(
            inner_prob,
            inner_y,
            positive=True,
            target_precision=target_precision,
            min_predictions=min_predictions,
        )
        direct_eligible = inner_ai >= frozen_ai_threshold
        direct_threshold = one_sided_precision_threshold(
            inner_prob[direct_eligible],
            inner_y[direct_eligible],
            positive=False,
            target_precision=target_precision,
            min_predictions=min_predictions,
        )

        final = _model(seed + outer_index)
        final.fit(X[outer_train], y[outer_train])
        indices = np.flatnonzero(test)
        probabilities = final.predict_proba(X[test])[:, 1]
        for local, row_index in enumerate(indices):
            if probabilities[local] >= humanized_threshold:
                predicted[row_index] = HUMANIZED_AI
            elif (
                X[row_index, frozen_ai_index] >= frozen_ai_threshold
                and probabilities[local] <= direct_threshold
            ):
                predicted[row_index] = DIRECT_AI
        fold_details[held_out] = {
            "n": int(test.sum()),
            "humanized_threshold": round(float(humanized_threshold), 6),
            "direct_max_humanized_probability": round(float(direct_threshold), 6),
        }

    covered = predicted != "unknown_other"
    per_class = {}
    for cause, truth in ((DIRECT_AI, ~y), (HUMANIZED_AI, y)):
        selected = predicted == cause
        per_class[cause] = {
            "precision": round(float((truth[selected]).mean()), 4) if selected.any() else None,
            "recall": round(float(selected[truth].mean()), 4),
            "selected": int(selected.sum()),
            "support": int(truth.sum()),
        }
    return {
        "n": len(y),
        "coverage": round(float(covered.mean()), 4),
        "selective_accuracy": round(float((predicted[covered] == labels[covered]).mean()), 4)
        if covered.any()
        else None,
        "per_class": per_class,
        "prediction_counts": dict(Counter(predicted.tolist())),
        "folds": fold_details,
        "frozen_ai_threshold": frozen_ai_threshold,
        "target_calibration_precision": target_precision,
    }


def one_sided_precision_threshold(
    probabilities: np.ndarray,
    y_humanized: np.ndarray,
    *,
    positive: bool,
    target_precision: float,
    min_predictions: int,
) -> float:
    """Largest-coverage threshold satisfying precision on inner calibration."""

    if probabilities.size == 0:
        return 1.01 if positive else -0.01
    candidates = sorted(set(probabilities.tolist()))
    best: tuple[int, float] | None = None
    for threshold in candidates:
        selected = probabilities >= threshold if positive else probabilities <= threshold
        count = int(selected.sum())
        if count < min_predictions:
            continue
        truth = y_humanized if positive else ~y_humanized
        if float(truth[selected].mean()) < target_precision:
            continue
        candidate = (count, float(threshold))
        if best is None or count > best[0]:
            best = candidate
    if best is None:
        return 1.01 if positive else -0.01
    return best[1]


def _precision_thresholds(
    probabilities: np.ndarray,
    labels: np.ndarray,
    *,
    target_precision: float,
    min_predictions: int,
    floor: float,
) -> dict[str, float]:
    """Select thresholds using calibration domains only, never outer test."""

    top = probabilities.argmax(axis=1)
    thresholds: dict[str, float] = {}
    for class_index, cause in enumerate(CAUSES):
        eligible = top == class_index
        candidates = sorted(set(probabilities[eligible, class_index].tolist()))
        best: tuple[int, float] | None = None
        for threshold in candidates:
            threshold = max(float(threshold), floor)
            selected = eligible & (probabilities[:, class_index] >= threshold)
            count = int(selected.sum())
            if count < min_predictions:
                continue
            precision = float((labels[selected] == cause).mean())
            if precision >= target_precision:
                candidate = (count, threshold)
                if best is None or candidate[0] > best[0] or (
                    candidate[0] == best[0] and candidate[1] < best[1]
                ):
                    best = candidate
        thresholds[cause] = round(best[1], 6) if best is not None else 1.01
    return thresholds


def _extract(bundles: Sequence[PadBenBundle], workers: int) -> np.ndarray:
    from original.ai_likelihood import predict_ai_likelihood_batch
    from scripts.train_ai_detector import _extract_parallel

    features = _extract_parallel([bundle.text for bundle in bundles], workers, "padben-cause")
    probabilities = predict_ai_likelihood_batch(features)
    if probabilities is None:
        probabilities = np.full(len(features), np.nan, dtype=np.float64)
    return np.column_stack([features.astype(np.float64), probabilities])


def load_feature_matrix(
    data_path: Path,
    *,
    cache_path: Path,
    rows_per_bundle: int = 12,
    max_bundles_per_source_variant: int = 40,
    workers: int = 4,
) -> tuple[list[PadBenBundle], np.ndarray]:
    """Build bundles and load or extract their content-addressed features."""

    records = json.loads(data_path.read_text(encoding="utf-8"))
    bundles = bundle_padben_records(
        records,
        rows_per_bundle=rows_per_bundle,
        max_bundles_per_source_variant=max_bundles_per_source_variant,
    )
    cache_key = hashlib.sha256(
        (
            hashlib.sha256(data_path.read_bytes()).hexdigest()
            + f":{rows_per_bundle}:{max_bundles_per_source_variant}"
        ).encode()
    ).hexdigest()
    if cache_path.exists():
        cached = np.load(cache_path, allow_pickle=False)
        if str(cached["cache_key"].item()) == cache_key:
            return bundles, cached["X"]
    X = _extract(bundles, workers)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(cache_path, X=X, cache_key=np.asarray(cache_key))
    return bundles, X


def fit_calibrated_cause_model(
    X: np.ndarray,
    labels: Sequence[str],
    sources: Sequence[str],
    *,
    min_probability: float = 0.60,
    target_precision: float = 0.90,
    min_calibration_predictions: int = 5,
    seed: int = 1729,
) -> tuple[Pipeline, dict[str, float]]:
    """Fit a final model with thresholds from source-held-out predictions."""

    X = np.asarray(X, dtype=np.float64)
    y = np.asarray(labels, dtype=object)
    groups = np.asarray(sources, dtype=object)
    calibration_probabilities: list[np.ndarray] = []
    calibration_labels: list[np.ndarray] = []
    for index, held_out in enumerate(sorted(set(groups.tolist()))):
        calibration = groups == held_out
        train = ~calibration
        if set(y[train].tolist()) != set(CAUSES):
            continue
        model = _model(seed + index)
        model.fit(X[train], y[train])
        raw = model.predict_proba(X[calibration])
        classes = model.named_steps["logistic"].classes_
        aligned = np.zeros((int(calibration.sum()), len(CAUSES)), dtype=np.float64)
        for class_index, cause in enumerate(CAUSES):
            aligned[:, class_index] = raw[:, list(classes).index(cause)]
        calibration_probabilities.append(aligned)
        calibration_labels.append(y[calibration])
    if not calibration_probabilities:
        raise ValueError("source-held calibration could not retain all cause classes")
    thresholds = _precision_thresholds(
        np.concatenate(calibration_probabilities),
        np.concatenate(calibration_labels),
        target_precision=target_precision,
        min_predictions=min_calibration_predictions,
        floor=min_probability,
    )
    final = _model(seed + 1000)
    final.fit(X, y)
    return final, thresholds


def fit_ai_subtype_discriminator(
    X: np.ndarray,
    labels: Sequence[str],
    *,
    seed: int = 1729,
) -> Pipeline:
    """Fit direct-vs-humanized ranking on PADBen AI rows only."""

    X = np.asarray(X, dtype=np.float64)
    y_labels = np.asarray(labels, dtype=object)
    keep = np.isin(y_labels, [DIRECT_AI, HUMANIZED_AI])
    if set(y_labels[keep].tolist()) != {DIRECT_AI, HUMANIZED_AI}:
        raise ValueError("need both direct_ai and humanized_ai rows")
    model = _model(seed)
    model.fit(X[keep], y_labels[keep] == HUMANIZED_AI)
    return model


def run(
    data_path: Path,
    *,
    output: Path,
    rows_per_bundle: int = 12,
    max_bundles_per_source_variant: int = 40,
    workers: int = 4,
) -> dict:
    cache_path = output.with_suffix(".features.npz")
    bundles, X = load_feature_matrix(
        data_path,
        cache_path=cache_path,
        rows_per_bundle=rows_per_bundle,
        max_bundles_per_source_variant=max_bundles_per_source_variant,
        workers=workers,
    )
    metrics = evaluate_cause_matrix(
        X,
        [bundle.cause for bundle in bundles],
        [bundle.source for bundle in bundles],
    )
    subtype_metrics = evaluate_ai_subtypes(
        X,
        [bundle.cause for bundle in bundles],
        [bundle.source for bundle in bundles],
    )
    report = {
        "dataset": "PADBen data.json (MIT), bundled sentence-level stress test",
        "source_url": "https://huggingface.co/datasets/JonathanZha/PADBen",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "method": {
            "rows_per_bundle": rows_per_bundle,
            "max_bundles_per_source_variant": max_bundles_per_source_variant,
            "feature_count": int(X.shape[1]),
            "features": "Original 103 features + frozen AI-likelihood probability",
            "split": "leave-one-dataset_source-out; paired variants share source fold",
            "warning": (
                "PADBen records are sentences. Bundles stabilize document features but "
                "are not natural essays and cannot support production promotion."
            ),
        },
        "input_sha256": hashlib.sha256(data_path.read_bytes()).hexdigest(),
        "bundle_counts": dict(Counter(bundle.cause for bundle in bundles)),
        "variant_counts": dict(Counter(bundle.variant for bundle in bundles)),
        "metrics": metrics,
        "ai_subtype_metrics": subtype_metrics,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", required=True, type=Path, help="PADBen data/data.json")
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--rows-per-bundle", type=int, default=12)
    parser.add_argument("--max-bundles", type=int, default=40)
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    os.environ.setdefault("AI_LIKELIHOOD_ENABLED", "1")
    report = run(
        args.data,
        output=args.output,
        rows_per_bundle=args.rows_per_bundle,
        max_bundles_per_source_variant=args.max_bundles,
        workers=args.workers,
    )
    print(json.dumps(report["metrics"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
