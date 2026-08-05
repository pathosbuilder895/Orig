"""Selective joint cause stack: claimed author, human impostor, or AI origin.

The stack intentionally consumes only two independently calibrated evidence
axes: peer-aligned claimed-author probability and frozen AI-likelihood
probability. Author partitions, RAID source roots, generator, and rewrite
family are disjoint at the locked test.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import time
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Sequence

import joblib
import numpy as np
from scipy.sparse import vstack
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import confusion_matrix, precision_recall_fscore_support
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from original.ai_likelihood import predict_ai_likelihood_batch
from original.style_authorship import DEFAULT_ARTIFACT_PATH, _profile
from scripts.train_ai_detector import _extract_parallel
from validation.cause.padben import DIRECT_AI, HUMAN, HUMANIZED_AI, load_feature_matrix
from validation.verify.pan_style_expert import StyleAuthor, load_author_partitions


CLAIMED_AUTHOR = "claimed_author"
HUMAN_IMPOSTOR = "human_impostor"
UNKNOWN = "unknown_other"
AI_ORIGIN = "ai_origin_unknown_subtype"
CAUSES = (CLAIMED_AUTHOR, HUMAN_IMPOSTOR, DIRECT_AI, HUMANIZED_AI)


@dataclass(frozen=True)
class CauseTrial:
    partition: str
    claimed_author: str
    source_group: str
    cause: str
    text: str
    style_probability: float
    ai_probability: float
    best_alternative_probability: float = 0.0
    alternative_over_claimed_margin: float = 0.0
    general_impostors_score: float = 0.0
    best_alternative_author: str | None = None
    true_source_author: str | None = None
    best_alternative_runner_up_margin: float = 0.0

    def signals(self) -> tuple[float, ...]:
        style = float(np.clip(self.style_probability, 1e-6, 1 - 1e-6))
        ai = float(np.clip(self.ai_probability, 1e-6, 1 - 1e-6))
        return (
            style,
            ai,
            self.best_alternative_probability,
            self.alternative_over_claimed_margin,
            self.general_impostors_score,
            math.log(style / (1 - style)),
            math.log(ai / (1 - ai)),
            (1 - style) * ai,
            (1 - style) * self.best_alternative_probability,
        )


def _style_evidence(
    texts_and_claims: Sequence[tuple[str, int]],
    authors: Sequence[StyleAuthor],
    artifact: dict,
) -> np.ndarray:
    profiles = [_profile(list(author.baselines), artifact) for author in authors]
    centroid_matrix = vstack([profile[0] for profile in profiles]).tocsr()
    vocabulary_size = centroid_matrix.shape[1]
    mask_rng = np.random.default_rng(1729)
    feature_masks = (
        mask_rng.random((vocabulary_size, 64), dtype=np.float32) < 0.30
    ).astype(np.float32)
    centroid_subset_norm = np.sqrt(
        np.maximum(centroid_matrix.power(2) @ feature_masks, 1e-12)
    )
    evidence = []
    for text, claimed_index in texts_and_claims:
        probe_char = artifact["character_vectorizer"].transform([text])
        from original.style_authorship import content_reduced_signature

        probe_style = artifact["style_scaler"].transform(
            content_reduced_signature(text).reshape(1, -1)
        )[0]
        raw_character = np.asarray(
            [float((probe_char @ profile[0].T).toarray()[0, 0]) for profile in profiles]
        )
        raw_style = np.asarray(
            [-float(np.mean(np.abs(probe_style - profile[1]))) for profile in profiles]
        )
        probabilities = []
        for target_index in range(len(authors)):
            peer_mask = np.arange(len(authors)) != target_index
            signals = np.asarray(
                [
                    [
                        raw_character[target_index],
                        raw_style[target_index],
                        (raw_character[target_index] - raw_character[peer_mask].mean())
                        / max(raw_character[peer_mask].std(), 1e-9),
                        (raw_style[target_index] - raw_style[peer_mask].mean())
                        / max(raw_style[peer_mask].std(), 1e-9),
                    ]
                ]
            )
            probabilities.append(float(artifact["calibrator"].predict_proba(signals)[0, 1]))
        claimed_probability = probabilities[claimed_index]
        alternative_index = max(
            (index for index in range(len(probabilities)) if index != claimed_index),
            key=lambda index: probabilities[index],
        )
        alternative_probability = probabilities[alternative_index]
        runner_up_alternative = max(
            probabilities[index]
            for index in range(len(probabilities))
            if index not in {claimed_index, alternative_index}
        )
        numerator = centroid_matrix.multiply(probe_char) @ feature_masks
        probe_subset_norm = np.sqrt(
            np.maximum(np.asarray(probe_char.power(2) @ feature_masks).ravel(), 1e-12)
        )
        subset_similarity = np.asarray(numerator) / (
            centroid_subset_norm * probe_subset_norm[None, :]
        )
        comparison_rng = np.random.default_rng(
            int(hashlib.sha256(text.encode()).hexdigest()[:16], 16)
        )
        claimed_wins = []
        for iteration in range(feature_masks.shape[1]):
            competitors = comparison_rng.random(len(authors)) < 0.50
            competitors[claimed_index] = False
            if not competitors.any():
                competitors[(claimed_index + 1) % len(authors)] = True
            claimed_wins.append(
                subset_similarity[claimed_index, iteration]
                > float(np.max(subset_similarity[competitors, iteration]))
            )
        general_impostors_score = float(np.mean(claimed_wins))
        evidence.append(
            (
                claimed_probability,
                alternative_probability,
                alternative_probability - claimed_probability,
                general_impostors_score,
                float(alternative_index),
                alternative_probability - runner_up_alternative,
            )
        )
    return np.asarray(evidence, dtype=np.float64)


def _ai_probability_map(
    texts: Sequence[str],
    *,
    cache_path: Path,
    workers: int,
) -> dict[str, float]:
    unique = {}
    for text in texts:
        unique.setdefault(hashlib.sha256(text.encode()).hexdigest(), text)
    hashes = sorted(unique)
    cache_key = hashlib.sha256("".join(hashes).encode()).hexdigest()
    if cache_path.exists():
        cached = np.load(cache_path, allow_pickle=False)
        if str(cached["cache_key"].item()) == cache_key:
            return dict(zip(cached["hashes"].tolist(), cached["probabilities"].tolist()))
    features = _extract_parallel([unique[value] for value in hashes], workers, "joint-cause")
    probabilities = predict_ai_likelihood_batch(features)
    if probabilities is None:
        raise RuntimeError("frozen AI-likelihood artifact unavailable")
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        cache_path,
        cache_key=np.asarray(cache_key),
        hashes=np.asarray(hashes),
        probabilities=np.asarray(probabilities),
    )
    return dict(zip(hashes, probabilities.tolist()))


def _root_bucket(root: str) -> int:
    return int(hashlib.sha256(f"joint-cause:{root}".encode()).hexdigest()[:8], 16) % 10


def _raid_partition(rows: Sequence[dict], partition: str) -> list[tuple[str, str, str]]:
    """Return (cause, source_group, text) with generator/attack lock."""

    selected = []
    for row in rows:
        root = str(row["id"] if row["attack"] == "none" else row["adv_source_id"])
        bucket = _root_bucket(root)
        if partition == "development":
            eligible = row["model"] == "llama-chat" and bucket < 8
            cause = DIRECT_AI if row["attack"] == "none" else HUMANIZED_AI
            eligible &= row["attack"] in {"none", "synonym"}
        elif partition == "calibration":
            eligible = row["model"] == "llama-chat" and bucket >= 8
            cause = DIRECT_AI if row["attack"] == "none" else HUMANIZED_AI
            eligible &= row["attack"] in {"none", "synonym"}
        else:
            eligible = row["model"] == "mistral-chat"
            cause = DIRECT_AI if row["attack"] == "none" else HUMANIZED_AI
            eligible &= row["attack"] in {"none", "paraphrase"}
        if eligible:
            selected.append((cause, f"raid:{root}", str(row["generation"])))
    return selected


def build_trials(
    authors: Sequence[StyleAuthor],
    raid_rows: Sequence[dict],
    *,
    partition: str,
    artifact: dict,
    ai_cache_path: Path,
    workers: int,
    impostor_authors: Sequence[StyleAuthor] | None = None,
) -> list[CauseTrial]:
    if impostor_authors is not None and len(impostor_authors) != len(authors):
        raise ValueError("impostor_authors must align one-to-one with claimed authors")
    specifications: list[tuple[str, str, str, int, str | None]] = []
    for author_index, author in enumerate(authors):
        impostor = (
            impostor_authors[author_index]
            if impostor_authors is not None
            else authors[(author_index + 1) % len(authors)]
        )
        for probe_index, text in enumerate(author.probes):
            specifications.append(
                (
                    CLAIMED_AUTHOR,
                    f"pan:{author.author_id}:{probe_index}",
                    text,
                    author_index,
                    author.author_id,
                )
            )
        for probe_index, text in enumerate(impostor.probes):
            specifications.append(
                (
                    HUMAN_IMPOSTOR,
                    f"pan:{impostor.author_id}:{probe_index}",
                    text,
                    author_index,
                    impostor.author_id,
                )
            )
    ai_rows = _raid_partition(raid_rows, partition)
    for index, (cause, source, text) in enumerate(ai_rows):
        specifications.append((cause, source, text, index % len(authors), None))
    texts = [row[2] for row in specifications]
    ai_map = _ai_probability_map(texts, cache_path=ai_cache_path, workers=workers)
    style = _style_evidence([(row[2], row[3]) for row in specifications], authors, artifact)
    return [
        CauseTrial(
            partition=partition,
            claimed_author=authors[claimed_index].author_id,
            source_group=source,
            cause=cause,
            text=text,
            style_probability=float(style[index, 0]),
            ai_probability=float(ai_map[hashlib.sha256(text.encode()).hexdigest()]),
            best_alternative_probability=float(style[index, 1]),
            alternative_over_claimed_margin=float(style[index, 2]),
            general_impostors_score=float(style[index, 3]),
            best_alternative_author=authors[int(style[index, 4])].author_id,
            true_source_author=true_source_author,
            best_alternative_runner_up_margin=float(style[index, 5]),
        )
        for index, (cause, source, text, claimed_index, true_source_author) in enumerate(
            specifications
        )
    ]


def build_padben_external_trials(
    authors: Sequence[StyleAuthor],
    padben_data: Path,
    *,
    artifact: dict,
    feature_cache: Path,
    workers: int,
) -> list[CauseTrial]:
    """Map completely external PADBen bundles to claimed PAN authors."""

    bundles, X = load_feature_matrix(
        padben_data,
        cache_path=feature_cache,
        workers=workers,
    )
    specifications = [
        (bundle.text, index % len(authors)) for index, bundle in enumerate(bundles)
    ]
    style = _style_evidence(specifications, authors, artifact)
    return [
        CauseTrial(
            partition="external_padben",
            claimed_author=authors[index % len(authors)].author_id,
            source_group=f"padben:{bundle.source}:{','.join(map(str, bundle.row_ids))}",
            cause=(
                HUMAN_IMPOSTOR
                if bundle.cause == HUMAN
                else DIRECT_AI
                if bundle.cause == DIRECT_AI
                else HUMANIZED_AI
            ),
            text=bundle.text,
            style_probability=float(style[index, 0]),
            ai_probability=float(X[index, -1]),
            best_alternative_probability=float(style[index, 1]),
            alternative_over_claimed_margin=float(style[index, 2]),
            general_impostors_score=float(style[index, 3]),
            best_alternative_author=authors[int(style[index, 4])].author_id,
            true_source_author=None,
            best_alternative_runner_up_margin=float(style[index, 5]),
        )
        for index, bundle in enumerate(bundles)
    ]


def _matrix(trials: Sequence[CauseTrial]) -> np.ndarray:
    return np.asarray([trial.signals() for trial in trials], dtype=np.float64)


def _precision_thresholds(
    labels: np.ndarray,
    probability: np.ndarray,
    classes: np.ndarray,
    *,
    target_precision: float = 0.90,
    min_predictions: int = 10,
) -> dict[str, float]:
    thresholds = {}
    for class_index, label in enumerate(classes):
        candidates = sorted(set(probability[:, class_index].tolist()), reverse=True)
        retained = []
        for threshold in candidates:
            selected = probability[:, class_index] >= threshold
            if int(selected.sum()) < min_predictions:
                continue
            precision = float((labels[selected] == label).mean())
            if precision >= target_precision:
                retained.append(threshold)
        thresholds[str(label)] = float(min(retained)) if retained else 1.01
    return thresholds


def _binary_precision_threshold(
    truth: np.ndarray,
    scores: np.ndarray,
    *,
    target_precision: float = 0.90,
    min_predictions: int = 10,
) -> float:
    retained = []
    for threshold in sorted(set(scores.tolist()), reverse=True):
        selected = scores >= threshold
        if int(selected.sum()) < min_predictions:
            continue
        if float(truth[selected].mean()) >= target_precision:
            retained.append(threshold)
    return float(min(retained)) if retained else 1.01


def evaluate_hierarchical_evidence(
    calibration: Sequence[CauseTrial],
    locked: Sequence[CauseTrial],
    *,
    strict_style_threshold: float,
) -> dict:
    """Frozen author gate, then selective human-impostor vs AI-origin evidence."""

    calibration_style = np.asarray([trial.style_probability for trial in calibration])
    calibration_ai = np.asarray([trial.ai_probability for trial in calibration])
    calibration_causes = np.asarray([trial.cause for trial in calibration], dtype=object)
    calibration_unclaimed = calibration_style < strict_style_threshold
    ai_truth = np.isin(calibration_causes, [DIRECT_AI, HUMANIZED_AI])
    impostor_truth = calibration_causes == HUMAN_IMPOSTOR
    ai_threshold = _binary_precision_threshold(
        ai_truth[calibration_unclaimed], calibration_ai[calibration_unclaimed]
    )
    calibration_alternative = np.asarray(
        [trial.best_alternative_probability for trial in calibration]
    )
    calibration_impostors = np.asarray([trial.general_impostors_score for trial in calibration])
    impostor_score = (
        (1.0 - calibration_style)
        * (1.0 - calibration_ai)
        * calibration_alternative
        * (1.0 - calibration_impostors)
    )
    calibration_human_only = calibration_unclaimed & (calibration_ai < ai_threshold)
    impostor_threshold = _binary_precision_threshold(
        impostor_truth[calibration_human_only], impostor_score[calibration_human_only]
    )

    locked_style = np.asarray([trial.style_probability for trial in locked])
    locked_ai = np.asarray([trial.ai_probability for trial in locked])
    locked_cause = np.asarray([trial.cause for trial in locked], dtype=object)
    truth = np.where(
        locked_cause == CLAIMED_AUTHOR,
        CLAIMED_AUTHOR,
        np.where(locked_cause == HUMAN_IMPOSTOR, HUMAN_IMPOSTOR, AI_ORIGIN),
    )
    predicted = np.full(len(locked), UNKNOWN, dtype=object)
    claimed = locked_style >= strict_style_threshold
    ai_candidate = (~claimed) & (locked_ai >= ai_threshold)
    locked_alternative = np.asarray([trial.best_alternative_probability for trial in locked])
    locked_impostors = np.asarray([trial.general_impostors_score for trial in locked])
    locked_impostor_score = (
        (1.0 - locked_style)
        * (1.0 - locked_ai)
        * locked_alternative
        * (1.0 - locked_impostors)
    )
    impostor_candidate = (~claimed) & (locked_impostor_score >= impostor_threshold)
    predicted[claimed] = CLAIMED_AUTHOR
    predicted[ai_candidate & ~impostor_candidate] = AI_ORIGIN
    predicted[impostor_candidate & ~ai_candidate] = HUMAN_IMPOSTOR
    labels = (CLAIMED_AUTHOR, HUMAN_IMPOSTOR, AI_ORIGIN)
    precision, recall, f1, support = precision_recall_fscore_support(
        truth, predicted, labels=list(labels), zero_division=0
    )
    per_class = {
        label: {
            "precision": round(float(precision[index]), 4),
            "recall": round(float(recall[index]), 4),
            "f1": round(float(f1[index]), 4),
            "support": int(support[index]),
            "selected": int((predicted == label).sum()),
        }
        for index, label in enumerate(labels)
    }
    failures = []
    for label, values in per_class.items():
        if values["precision"] < 0.90:
            failures.append(f"{label}:precision<0.90")
        if values["recall"] < 0.50:
            failures.append(f"{label}:recall<0.50")
    covered = predicted != UNKNOWN
    return {
        "strict_style_threshold": strict_style_threshold,
        "ai_origin_threshold": ai_threshold,
        "human_impostor_threshold": impostor_threshold,
        "coverage": round(float(covered.mean()), 4),
        "selective_accuracy": round(float((truth[covered] == predicted[covered]).mean()), 4)
        if covered.any()
        else None,
        "per_class": per_class,
        "prediction_counts": dict(Counter(predicted.tolist())),
        "confusion_labels": [*labels, UNKNOWN],
        "confusion": confusion_matrix(truth, predicted, labels=[*labels, UNKNOWN]).tolist(),
        "promotion_gate": {"passed": not failures, "failures": failures},
        "scope": (
            "AI origin merges direct and humanized AI. It does not claim rewrite provenance."
        ),
    }


def evaluate_selective_stack(
    development: Sequence[CauseTrial],
    calibration: Sequence[CauseTrial],
    locked: Sequence[CauseTrial],
    *,
    min_margin: float = 0.10,
) -> tuple[dict, Pipeline, dict[str, float]]:
    model = Pipeline(
        [
            ("scale", StandardScaler()),
            (
                "logistic",
                LogisticRegression(
                    C=0.25,
                    class_weight="balanced",
                    max_iter=2000,
                    random_state=1729,
                ),
            ),
        ]
    )
    development_labels = np.asarray([trial.cause for trial in development], dtype=object)
    model.fit(_matrix(development), development_labels)
    classes = model.named_steps["logistic"].classes_
    calibration_labels = np.asarray([trial.cause for trial in calibration], dtype=object)
    calibration_probability = model.predict_proba(_matrix(calibration))
    thresholds = _precision_thresholds(calibration_labels, calibration_probability, classes)
    truth = np.asarray([trial.cause for trial in locked], dtype=object)
    probability = model.predict_proba(_matrix(locked))
    predicted = np.full(len(locked), UNKNOWN, dtype=object)
    for index, row in enumerate(probability):
        order = np.argsort(row)[::-1]
        best, runner_up = order[:2]
        label = str(classes[best])
        if row[best] >= thresholds[label] and row[best] - row[runner_up] >= min_margin:
            predicted[index] = label
    precision, recall, f1, support = precision_recall_fscore_support(
        truth, predicted, labels=list(CAUSES), zero_division=0
    )
    per_class = {
        label: {
            "precision": round(float(precision[index]), 4),
            "recall": round(float(recall[index]), 4),
            "f1": round(float(f1[index]), 4),
            "support": int(support[index]),
            "selected": int((predicted == label).sum()),
        }
        for index, label in enumerate(CAUSES)
    }
    covered = predicted != UNKNOWN
    failures = []
    for label, values in per_class.items():
        if values["support"] < 40:
            failures.append(f"{label}:support<40")
        if values["precision"] < 0.90:
            failures.append(f"{label}:precision<0.90")
        if values["recall"] < 0.50:
            failures.append(f"{label}:recall<0.50")
    report = {
        "n_development": len(development),
        "n_calibration": len(calibration),
        "n_locked": len(locked),
        "development_counts": dict(Counter(trial.cause for trial in development)),
        "calibration_counts": dict(Counter(trial.cause for trial in calibration)),
        "locked_counts": dict(Counter(trial.cause for trial in locked)),
        "thresholds": thresholds,
        "coverage": round(float(covered.mean()), 4),
        "selective_accuracy": round(float((predicted[covered] == truth[covered]).mean()), 4)
        if covered.any()
        else None,
        "per_class": per_class,
        "prediction_counts": dict(Counter(predicted.tolist())),
        "confusion_labels": [*CAUSES, UNKNOWN],
        "confusion": confusion_matrix(truth, predicted, labels=[*CAUSES, UNKNOWN]).tolist(),
        "promotion_gate": {"passed": not failures, "failures": failures},
    }
    return report, model, thresholds


def assess_enrolled_peer_gate(report: dict) -> dict:
    metrics = report["per_class"][HUMAN_IMPOSTOR]
    conditions = {
        "precision_at_least_0_90": metrics["precision"] >= 0.90,
        "recall_at_least_0_30": metrics["recall"] >= 0.30,
        "support_at_least_100": metrics["support"] >= 100,
    }
    return {
        "scope": "closed enrolled comparison pool only",
        "outside_pool_policy": "unknown_writer",
        "passed": all(conditions.values()),
        "conditions": conditions,
    }


def evaluate_enrolled_peer_identity(
    calibration: Sequence[CauseTrial],
    locked_known: Sequence[CauseTrial],
    locked_outside: Sequence[CauseTrial],
    *,
    calibration_eligible: np.ndarray | None = None,
    known_eligible: np.ndarray | None = None,
    outside_eligible: np.ndarray | None = None,
) -> dict:
    """Name a peer only when calibration supports that exact candidate."""

    def candidate_scores(rows: Sequence[CauseTrial]) -> np.ndarray:
        return np.asarray(
            [
                (1.0 - row.ai_probability)
                * row.best_alternative_probability
                * max(row.best_alternative_runner_up_margin, 0.0)
                for row in rows
            ],
            dtype=np.float64,
        )

    calibration_truth = np.asarray(
        [
            row.cause == HUMAN_IMPOSTOR
            and row.best_alternative_author == row.true_source_author
            for row in calibration
        ]
    )
    calibration_eligible = (
        np.ones(len(calibration), dtype=bool)
        if calibration_eligible is None
        else np.asarray(calibration_eligible, dtype=bool)
    )
    threshold = _binary_precision_threshold(
        calibration_truth[calibration_eligible],
        candidate_scores(calibration)[calibration_eligible],
        target_precision=0.90,
        min_predictions=10,
    )

    def evaluate(
        rows: Sequence[CauseTrial], eligibility: np.ndarray | None, *, outside: bool
    ) -> dict:
        scores = candidate_scores(rows)
        eligibility = (
            np.ones(len(rows), dtype=bool)
            if eligibility is None
            else np.asarray(eligibility, dtype=bool)
        )
        selected = eligibility & (scores >= threshold)
        human_impostor = np.asarray([row.cause == HUMAN_IMPOSTOR for row in rows])
        correct = np.asarray(
            [
                row.cause == HUMAN_IMPOSTOR
                and row.best_alternative_author == row.true_source_author
                for row in rows
            ]
        )
        named = int(selected.sum())
        return {
            "selected": named,
            "top1_identity_accuracy_before_abstention": round(
                float(correct[human_impostor].mean()), 4
            ),
            "cause_gate_selected": int(eligibility.sum()),
            "cause_gate_exact_identity_precision": round(
                float(correct[eligibility].mean()), 4
            )
            if eligibility.any()
            else None,
            "precision_exact_identity": round(float(correct[selected].mean()), 4)
            if named
            else None,
            "recall_exact_identity": round(
                float((selected & correct).sum() / max(1, human_impostor.sum())), 4
            ),
            "outside_writer_naming_rate": round(float(selected[human_impostor].mean()), 4)
            if outside
            else None,
            "support_human_impostor": int(human_impostor.sum()),
        }

    known = evaluate(locked_known, known_eligible, outside=False)
    outside = evaluate(locked_outside, outside_eligible, outside=True)
    conditions = {
        "known_precision_at_least_0_90": known["precision_exact_identity"] is not None
        and known["precision_exact_identity"] >= 0.90,
        "known_recall_at_least_0_30": known["recall_exact_identity"] >= 0.30,
        "outside_naming_rate_at_most_0_01": outside["outside_writer_naming_rate"] <= 0.01,
    }
    return {
        "threshold": threshold,
        "known_enrolled_peer": known,
        "outside_pool": outside,
        "outside_pool_policy": "unknown_writer",
        "promotion_gate": {"passed": all(conditions.values()), "conditions": conditions},
    }


def _selective_class_mask(
    model: Pipeline,
    thresholds: dict[str, float],
    rows: Sequence[CauseTrial],
    label: str,
    *,
    min_margin: float = 0.10,
) -> np.ndarray:
    probability = model.predict_proba(_matrix(rows))
    classes = model.named_steps["logistic"].classes_
    result = np.zeros(len(rows), dtype=bool)
    for index, values in enumerate(probability):
        order = np.argsort(values)[::-1]
        best, runner_up = order[:2]
        predicted = str(classes[best])
        result[index] = (
            predicted == label
            and values[best] >= thresholds[predicted]
            and values[best] - values[runner_up] >= min_margin
        )
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raid-data", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--padben-data", type=Path)
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    raid_payload = json.loads(args.raid_data.read_text(encoding="utf-8"))
    raid_rows = raid_payload["rows"]
    artifact = joblib.load(DEFAULT_ARTIFACT_PATH)
    author_sets = {}
    for name, excluded in (("development", 0), ("calibration", 40), ("locked", 80)):
        author_sets[name] = load_author_partitions(
            n_development=120,
            n_calibration=40,
            n_locked=40,
            prior_locked_authors=12,
            post_calibration_excluded_authors=excluded,
        )["locked"]
    outside_impostors = load_author_partitions(
        n_development=120,
        n_calibration=40,
        n_locked=40,
        prior_locked_authors=12,
        post_calibration_excluded_authors=120,
    )["locked"]
    trials = {}
    for name in ("development", "calibration", "locked"):
        trials[name] = build_trials(
            author_sets[name],
            raid_rows,
            partition=name,
            artifact=artifact,
            ai_cache_path=args.output.with_name(f"{args.output.stem}.{name}.features.npz"),
            workers=args.workers,
        )
    report, model, thresholds = evaluate_selective_stack(
        trials["development"], trials["calibration"], trials["locked"]
    )
    hierarchy = evaluate_hierarchical_evidence(
        trials["calibration"],
        trials["locked"],
        strict_style_threshold=float(artifact["strict_threshold"]),
    )
    outside_locked_trials = build_trials(
        author_sets["locked"],
        raid_rows,
        partition="locked_out_of_cohort",
        artifact=artifact,
        ai_cache_path=args.output.with_name(
            f"{args.output.stem}.locked_out_of_cohort.features.npz"
        ),
        workers=args.workers,
        impostor_authors=outside_impostors,
    )
    outside_report, _, _ = evaluate_selective_stack(
        trials["development"], trials["calibration"], outside_locked_trials
    )
    outside_hierarchy = evaluate_hierarchical_evidence(
        trials["calibration"],
        outside_locked_trials,
        strict_style_threshold=float(artifact["strict_threshold"]),
    )
    enrolled_peer_identity = evaluate_enrolled_peer_identity(
        trials["calibration"],
        trials["locked"],
        outside_locked_trials,
        calibration_eligible=_selective_class_mask(
            model, thresholds, trials["calibration"], HUMAN_IMPOSTOR
        ),
        known_eligible=_selective_class_mask(
            model, thresholds, trials["locked"], HUMAN_IMPOSTOR
        ),
        outside_eligible=_selective_class_mask(
            model, thresholds, outside_locked_trials, HUMAN_IMPOSTOR
        ),
    )
    external_hierarchy = None
    if args.padben_data is not None:
        external_trials = build_padben_external_trials(
            author_sets["locked"],
            args.padben_data,
            artifact=artifact,
            feature_cache=args.output.with_name(f"{args.output.stem}.padben.features.npz"),
            workers=args.workers,
        )
        external_hierarchy = evaluate_hierarchical_evidence(
            trials["calibration"],
            external_trials,
            strict_style_threshold=float(artifact["strict_threshold"]),
        )
    payload = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "raid_input_sha256": hashlib.sha256(args.raid_data.read_bytes()).hexdigest(),
        "padben_input_sha256": (
            hashlib.sha256(args.padben_data.read_bytes()).hexdigest()
            if args.padben_data is not None
            else None
        ),
        "style_artifact": str(DEFAULT_ARTIFACT_PATH),
        "style_vocabulary_sha256": artifact["vocabulary_sha256"],
        "signal_order": [
            "style_probability",
            "ai_probability",
            "best_alternative_probability",
            "alternative_over_claimed_margin",
            "general_impostors_score",
            "style_logit",
            "ai_logit",
            "style_discrepancy_x_ai_probability",
            "style_discrepancy_x_alternative_probability",
        ],
        "split": (
            "three disjoint fresh 40-author PAN partitions; RAID development/calibration use "
            "disjoint llama-chat roots with none/synonym; locked uses mistral-chat roots with "
            "none/paraphrase"
        ),
        "evaluation": report,
        "hierarchical_evaluation": hierarchy,
        "out_of_cohort_ghostwriter_evaluation": outside_report,
        "out_of_cohort_ghostwriter_hierarchical_evaluation": outside_hierarchy,
        "external_padben_hierarchical_evaluation": external_hierarchy,
        "enrolled_peer_ghostwriter_gate": assess_enrolled_peer_gate(report),
        "enrolled_peer_identity_evaluation": enrolled_peer_identity,
        "trial_examples": {
            name: [
                {key: value for key, value in asdict(trial).items() if key != "text"}
                for trial in values[:8]
            ]
            for name, values in trials.items()
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
