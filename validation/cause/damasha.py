"""Evaluate windowed AI-mixture evidence on DAMASHA/MAS boundary labels.

The evaluator uses a development half to choose a mixed-document range
threshold from pure human/pure AI controls, then reports recall and boundary
error on untouched rows. It is validation-only and does not alter API output.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from sklearn.metrics import roc_auc_score
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler


START = "<AI_Start>"
END = "</AI_End>"


@dataclass(frozen=True)
class MixedRecord:
    row_id: int
    human: str
    ai: str

    @property
    def mixed(self) -> str:
        return f"{self.human} {self.ai}".strip()

    @property
    def boundary_word(self) -> int:
        return len(self.human.split())


def parse_mixed_text(text: str, row_id: int) -> MixedRecord | None:
    if START not in text:
        return None
    human, ai = text.split(START, 1)
    ai = ai.split(END, 1)[0]
    human = re.sub(r"<[^>]+>", " ", human).strip()
    ai = re.sub(r"<[^>]+>", " ", ai).strip()
    if len(human.split()) < 40 or len(ai.split()) < 40:
        return None
    return MixedRecord(row_id=row_id, human=human, ai=ai)


def load_records(path: Path, limit: int) -> list[MixedRecord]:
    csv.field_size_limit(10_000_000)
    records = []
    with path.open(encoding="utf-8", newline="", errors="replace") as handle:
        for row_id, row in enumerate(csv.DictReader(handle)):
            parsed = parse_mixed_text(row.get("hybrid_text", ""), row_id)
            if parsed is not None:
                records.append(parsed)
            if len(records) >= limit:
                break
    return records


def windows(text: str, size: int = 80, step: int = 40) -> list[tuple[int, int, str]]:
    words = text.split()
    if len(words) <= size:
        return [(0, len(words), text)]
    starts = list(range(0, len(words) - size + 1, step))
    tail = len(words) - size
    if starts[-1] != tail:
        starts.append(tail)
    return [(start, start + size, " ".join(words[start : start + size])) for start in starts]


def _features_and_ai_probabilities(texts: list[str], workers: int) -> tuple[np.ndarray, np.ndarray]:
    from original.ai_likelihood import predict_ai_likelihood_batch
    from scripts.train_ai_detector import _extract_parallel

    X = _extract_parallel(texts, workers, "damasha-mixed")
    probabilities = predict_ai_likelihood_batch(X)
    if probabilities is None:
        probabilities = np.full(len(X), np.nan, dtype=np.float64)
    return X.astype(np.float64), probabilities


def run(
    data_path: Path,
    *,
    output: Path,
    limit: int = 60,
    window_size: int = 80,
    step: int = 40,
    workers: int = 4,
) -> dict:
    records = load_records(data_path, limit)
    if len(records) < 20:
        raise ValueError("need at least 20 valid mixed records")

    texts: list[str] = []
    index: list[tuple[int, str, int, int]] = []
    for record_index, record in enumerate(records):
        for kind, text in (("human", record.human), ("ai", record.ai), ("mixed", record.mixed)):
            for start, end, window_text in windows(text, window_size, step):
                texts.append(window_text)
                index.append((record_index, kind, start, end))
    cache_path = output.with_suffix(".features.npz")
    cache_key = hashlib.sha256(
        (
            hashlib.sha256(data_path.read_bytes()).hexdigest()
            + f":{limit}:{window_size}:{step}:{len(texts)}"
        ).encode()
    ).hexdigest()
    if cache_path.exists():
        cached = np.load(cache_path, allow_pickle=False)
        if str(cached["cache_key"].item()) == cache_key:
            X = cached["X"]
            frozen_probabilities = cached["frozen_probabilities"]
        else:
            X, frozen_probabilities = _features_and_ai_probabilities(texts, workers)
            np.savez_compressed(
                cache_path,
                X=X,
                frozen_probabilities=frozen_probabilities,
                cache_key=np.asarray(cache_key),
            )
    else:
        X, frozen_probabilities = _features_and_ai_probabilities(texts, workers)
        np.savez_compressed(
            cache_path,
            X=X,
            frozen_probabilities=frozen_probabilities,
            cache_key=np.asarray(cache_key),
        )

    training_rows = {i for i, record in enumerate(records) if record.row_id % 4 == 0}
    calibration_rows = {i for i, record in enumerate(records) if record.row_id % 4 == 2}
    locked = [i for i, record in enumerate(records) if record.row_id % 2 == 1]
    train_indices, train_labels = [], []
    for window_index, (record_index, kind, _start, _end) in enumerate(index):
        if record_index not in training_rows or kind not in ("human", "ai"):
            continue
        train_indices.append(window_index)
        train_labels.append(1 if kind == "ai" else 0)
    learned = make_pipeline(
        StandardScaler(),
        LogisticRegression(C=0.10, class_weight="balanced", max_iter=2500, random_state=1729),
    )
    augmented = np.column_stack([X, frozen_probabilities])
    learned.fit(augmented[train_indices], np.asarray(train_labels, dtype=np.int8))
    probabilities = learned.predict_proba(augmented)[:, 1]

    by_document: dict[tuple[int, str], list[tuple[int, int, float]]] = {}
    window_truth, window_score = [], []
    for metadata, probability in zip(index, probabilities):
        record_index, kind, start, end = metadata
        by_document.setdefault((record_index, kind), []).append((start, end, float(probability)))
        if kind == "human":
            window_truth.append(0)
            window_score.append(probability)
        elif kind == "ai":
            window_truth.append(1)
            window_score.append(probability)

    control_ranges = []
    for record_index in sorted(calibration_rows):
        for kind in ("human", "ai"):
            values = [row[2] for row in by_document[(record_index, kind)]]
            control_ranges.append(max(values) - min(values))
    range_threshold = float(np.quantile(control_ranges, 0.95, method="higher"))

    locked_mixed_ranges = []
    locked_control_ranges = []
    boundary_errors = []
    locked_window_truth, locked_window_score = [], []
    for record_index in locked:
        for kind in ("human", "ai"):
            values = [row[2] for row in by_document[(record_index, kind)]]
            locked_control_ranges.append(max(values) - min(values))
            locked_window_truth.extend([1 if kind == "ai" else 0] * len(values))
            locked_window_score.extend(values)
        rows = sorted(by_document[(record_index, "mixed")])
        values = [row[2] for row in rows]
        locked_mixed_ranges.append(max(values) - min(values))
        if len(rows) >= 2:
            # DAMASHA rows in this file are Human→AI. Estimate one structured
            # change point by maximizing right-mean minus left-mean, which is
            # less sensitive to one noisy adjacent window than argmax(diff).
            split_scores = [
                float(np.mean(values[split:]) - np.mean(values[:split]))
                for split in range(1, len(values))
            ]
            split = int(np.argmax(split_scores)) + 1
            predicted_boundary = (rows[split - 1][1] + rows[split][0]) / 2
            boundary_errors.append(abs(predicted_boundary - records[record_index].boundary_word))

    operating_points = {}
    for label, quantile in (("q90", 0.90), ("q95", 0.95), ("max_control", 1.0)):
        threshold = float(np.quantile(control_ranges, quantile, method="higher"))
        operating_points[label] = {
            "threshold": round(threshold, 6),
            "locked_mixed_recall": round(
                float(np.mean(np.asarray(locked_mixed_ranges) >= threshold)), 4
            ),
            "locked_control_false_positive_rate": round(
                float(np.mean(np.asarray(locked_control_ranges) >= threshold)), 4
            ),
        }

    report = {
        "dataset": "DAMASHA/MAS clean mixed-authorship subset (CC-BY-4.0)",
        "source_url": "https://huggingface.co/datasets/saiteja33/DAMASHA",
        "input_sha256": hashlib.sha256(data_path.read_bytes()).hexdigest(),
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "n_records": len(records),
        "n_training": len(training_rows),
        "n_calibration": len(calibration_rows),
        "n_locked": len(locked),
        "window_size": window_size,
        "window_step": step,
        "range_threshold_from_development_controls": round(range_threshold, 6),
        "frozen_ai_detector_pure_window_auc_all_rows": round(
            float(roc_auc_score(window_truth, [frozen_probabilities[i] for i, metadata in enumerate(index) if metadata[1] in ("human", "ai")])),
            4,
        ),
        "learned_window_expert_auc_locked": round(
            float(roc_auc_score(locked_window_truth, locked_window_score)), 4
        ),
        "locked_mixed_recall": operating_points["q95"]["locked_mixed_recall"],
        "locked_control_false_positive_rate": operating_points["q95"][
            "locked_control_false_positive_rate"
        ],
        "operating_points": operating_points,
        "boundary_median_absolute_error_words": round(float(np.median(boundary_errors)), 2),
        "boundary_p90_absolute_error_words": round(float(np.quantile(boundary_errors, 0.9)), 2),
        "warning": (
            "All source documents are constructed mixed texts. Pure controls are their isolated "
            "segments, and this evaluation does not establish student-essay performance."
        ),
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--limit", type=int, default=60)
    parser.add_argument("--window-size", type=int, default=80)
    parser.add_argument("--step", type=int, default=40)
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    report = run(
        args.data,
        output=args.output,
        limit=args.limit,
        window_size=args.window_size,
        step=args.step,
        workers=args.workers,
    )
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
