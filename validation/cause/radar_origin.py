"""Validation-only RADAR adversarial AI-origin transfer diagnostic.

The released RADAR-Vicuna-7B detector is non-commercial.  It is used here only
to test whether adversarial paraphrase training supplies an independent signal
that transfers to Original's external locks.  It must never be packaged in a
production artifact.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

import numpy as np
from sklearn.metrics import roc_auc_score

from validation.cause.faid import (
    COLLABORATIVE,
    DIRECT_AI,
    HUMAN,
    REVISION as FAID_REVISION,
    _local_human_calibration,
    fetch_test_split,
    load_locked_trials,
)
from validation.cause.raid import _fpr_threshold


MODEL_ID = "TrustSafeAI/RADAR-Vicuna-7B"
MODEL_REVISION = "4ff1f23a69a36aa1df47b0933be6279f1b896c9b"
MODEL_LICENSE = "non-commercial (Vicuna-derived); validation only"
MODEL_WEIGHTS_SHA256 = "4ea32c4a31b7004364df4fe672c5c763f3d5f32b7514aaeb2b5e47653bc89792"
MAX_TOKENS = 512
CACHE_SCHEMA = "original.radar_origin.v1"


@dataclass(frozen=True)
class OriginTrial:
    text: str
    cause: str
    source: str
    variant: str

    @property
    def is_ai(self) -> bool:
        return self.cause != HUMAN


def _text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def score_texts(
    texts: Sequence[str],
    *,
    cache_path: Path,
    model_path: Path | None = None,
    device: str | None = None,
    batch_size: int = 8,
) -> np.ndarray:
    """Return both class probabilities, caching by text and pinned model."""

    import torch
    from transformers import AutoModelForSequenceClassification, AutoTokenizer

    hashes = [_text_hash(text) for text in texts]
    cached: dict[str, np.ndarray] = {}
    if cache_path.exists():
        with np.load(cache_path, allow_pickle=False) as archive:
            metadata = json.loads(str(archive["metadata"].item()))
            if metadata.get("schema") != CACHE_SCHEMA:
                raise ValueError("incompatible RADAR score cache")
            cached = {
                str(key): np.asarray(value, dtype=np.float32)
                for key, value in zip(archive["hashes"].tolist(), archive["probabilities"])
            }
    missing = [(hash_value, text) for hash_value, text in zip(hashes, texts) if hash_value not in cached]
    if missing:
        selected_device = device or ("mps" if torch.backends.mps.is_available() else "cpu")
        source = str(model_path) if model_path is not None else MODEL_ID
        load_kwargs = {"local_files_only": True} if model_path is not None else {
            "revision": MODEL_REVISION
        }
        tokenizer = AutoTokenizer.from_pretrained(source, **load_kwargs)
        model = AutoModelForSequenceClassification.from_pretrained(
            source, **load_kwargs
        ).eval().to(selected_device)
        for start in range(0, len(missing), batch_size):
            batch = missing[start : start + batch_size]
            inputs = tokenizer(
                [text for _, text in batch],
                return_tensors="pt",
                padding=True,
                truncation=True,
                max_length=MAX_TOKENS,
            ).to(selected_device)
            with torch.inference_mode():
                probability = torch.softmax(model(**inputs).logits, dim=1).float().cpu().numpy()
            if probability.shape != (len(batch), 2):
                raise ValueError(f"RADAR returned unexpected shape {probability.shape}")
            for (hash_value, _), row in zip(batch, probability):
                cached[hash_value] = row.astype(np.float32)
            _save_cache(cache_path, cached)
    return np.stack([cached[hash_value] for hash_value in hashes])


def _save_cache(path: Path, values: dict[str, np.ndarray]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    keys = sorted(values)
    temporary = path.with_suffix(path.suffix + ".tmp.npz")
    np.savez_compressed(
        temporary,
        metadata=json.dumps(
            {
                "schema": CACHE_SCHEMA,
                "model_id": MODEL_ID,
                "model_revision": MODEL_REVISION,
                "max_tokens": MAX_TOKENS,
            },
            sort_keys=True,
        ),
        hashes=np.asarray(keys),
        probabilities=np.stack([values[key] for key in keys]),
    )
    temporary.replace(path)


def load_raid_trials(path: Path) -> list[OriginTrial]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = payload["rows"] if isinstance(payload, dict) else payload
    trials = []
    for row in rows:
        root = str(row["id"] if row["attack"] == "none" else row["adv_source_id"])
        trials.append(
            OriginTrial(
                text=str(row["generation"]),
                cause=HUMAN if row["model"] == "human" else DIRECT_AI,
                source=f"raid:{root}",
                variant="human" if row["model"] == "human" else str(row["attack"]),
            )
        )
    return trials


def load_padben_task5(
    path: Path, *, bundles_per_class: int = 160, rows_per_bundle: int = 12
) -> list[OriginTrial]:
    """Build deterministic document-length PADBen deep-paraphrase bundles."""

    rows = json.loads(path.read_text(encoding="utf-8"))
    trials = []
    for label, cause, variant in (
        (0, HUMAN, "human_original"),
        (1, DIRECT_AI, "third_iteration_paraphrase"),
    ):
        selected = sorted(
            (row for row in rows if int(row["label"]) == label),
            key=lambda row: hashlib.sha256(str(row["sentence"]).encode()).hexdigest(),
        )
        required = bundles_per_class * rows_per_bundle
        if len(selected) < required:
            raise ValueError(f"PADBen label {label}: need {required} rows, found {len(selected)}")
        for bundle_index in range(bundles_per_class):
            block = selected[
                bundle_index * rows_per_bundle : (bundle_index + 1) * rows_per_bundle
            ]
            trials.append(
                OriginTrial(
                    text=" ".join(str(row["sentence"]).strip() for row in block),
                    cause=cause,
                    source=f"padben-task5:{label}:{bundle_index}",
                    variant=variant,
                )
            )
    return trials


def _source_bucket(source: str) -> int:
    return int(hashlib.sha256(f"radar-calibration:{source}".encode()).hexdigest()[:8], 16) % 10


def orient_and_calibrate(
    trials: Sequence[OriginTrial], probabilities: np.ndarray, *, target_fpr: float = 0.01
) -> dict:
    """Choose class orientation on RAID development and threshold on disjoint humans."""

    labels = np.asarray([trial.is_ai for trial in trials], dtype=bool)
    buckets = np.asarray([_source_bucket(trial.source) for trial in trials])
    development = buckets < 7
    calibration_human = (~labels) & (buckets >= 7)
    if set(labels[development].tolist()) != {False, True} or not calibration_human.any():
        raise ValueError("RADAR orientation/calibration lacks source-disjoint support")
    aucs = [roc_auc_score(labels[development], probabilities[development, index]) for index in range(2)]
    ai_class = int(np.argmax(aucs))
    score = probabilities[:, ai_class]
    threshold = _fpr_threshold(score[calibration_human], target_fpr)
    return {
        "ai_class_index": ai_class,
        "development_auc": float(aucs[ai_class]),
        "threshold": float(threshold),
        "development_source_support": len(set(trial.source for i, trial in enumerate(trials) if development[i])),
        "calibration_human_source_support": len(
            set(trial.source for i, trial in enumerate(trials) if calibration_human[i])
        ),
        "calibration_human_rows": int(calibration_human.sum()),
        "source_overlap": len(
            {trial.source for i, trial in enumerate(trials) if development[i]}
            & {trial.source for i, trial in enumerate(trials) if calibration_human[i]}
        ),
    }


def summarize(trials: Sequence[OriginTrial], score: np.ndarray, threshold: float) -> dict:
    labels = np.asarray([trial.is_ai for trial in trials], dtype=bool)
    selected = score >= threshold
    tp = int(np.sum(selected & labels))
    result = {
        "n": len(trials),
        "auc": round(float(roc_auc_score(labels, score)), 6),
        "precision": round(tp / max(1, int(selected.sum())), 6) if selected.any() else None,
        "recall": round(float(selected[labels].mean()), 6),
        "human_fpr": round(float(selected[~labels].mean()), 6),
        "selected": int(selected.sum()),
        "support": {"human": int((~labels).sum()), "ai_involvement": int(labels.sum())},
        "variant_recall": {},
    }
    variants = np.asarray([trial.variant for trial in trials], dtype=object)
    for variant in sorted(set(variants[labels].tolist())):
        mask = labels & (variants == variant)
        result["variant_recall"][variant] = {
            "support": int(mask.sum()), "recall": round(float(selected[mask].mean()), 6)
        }
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raid-data", required=True, type=Path)
    parser.add_argument("--faid-dir", required=True, type=Path)
    parser.add_argument("--padben-task5", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--device")
    parser.add_argument("--model-path", type=Path)
    parser.add_argument("--batch-size", type=int, default=8)
    args = parser.parse_args()

    fetch_test_split(args.faid_dir)
    raid = load_raid_trials(args.raid_data)
    faid_rows = load_locked_trials(args.faid_dir)
    faid = [
        OriginTrial(
            trial.text,
            trial.cause,
            f"faid:{trial.source_file}:{trial.row_index}",
            trial.cause if trial.cause == COLLABORATIVE else trial.family,
        )
        for trial in faid_rows
    ]
    padben = load_padben_task5(args.padben_task5) if args.padben_task5 else []
    all_trials = [*raid, *faid, *padben]
    probability = score_texts(
        [trial.text for trial in all_trials],
        cache_path=args.output.with_suffix(".scores.npz"),
        model_path=args.model_path,
        device=args.device,
        batch_size=args.batch_size,
    )
    calibration = orient_and_calibrate(raid, probability[: len(raid)])
    ai_class = calibration["ai_class_index"]
    threshold = calibration["threshold"]
    faid_end = len(raid) + len(faid)
    faid_score = probability[len(raid) : faid_end, ai_class]
    faid_result = summarize(faid, faid_score, threshold)
    local_human = _local_human_calibration(
        faid_rows, faid_score, two_sided=False
    )
    local_precision_denominator = (
        local_human["human_fpr"] * local_human["locked_human_support"]
        + local_human["direct_ai_recall"] * 320
        + local_human["collaborative_recall"] * 320
    )
    local_true_positive = (
        local_human["direct_ai_recall"] * 320
        + local_human["collaborative_recall"] * 320
    )
    local_precision = local_true_positive / max(local_precision_denominator, 1e-12)
    local_human["precision_ai_involvement"] = round(float(local_precision), 6)
    gates = {
        "precision_at_least_0_90": faid_result["precision"] is not None
        and faid_result["precision"] >= 0.90,
        "recall_at_least_0_50": faid_result["recall"] >= 0.50,
        "human_fpr_at_most_0_01": faid_result["human_fpr"] <= 0.01,
        "commercially_usable_model": False,
    }
    local_conditions = {
        "precision_at_least_0_90": local_precision >= 0.90,
        "direct_recall_at_least_0_50": local_human["direct_ai_recall"] >= 0.50,
        "collaborative_recall_at_least_0_50": local_human["collaborative_recall"] >= 0.50,
        "human_fpr_at_most_0_01": local_human["human_fpr"] <= 0.01,
        "commercially_usable_model": False,
    }
    report = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "model": {
            "id": MODEL_ID,
            "revision": MODEL_REVISION,
            "license": MODEL_LICENSE,
            "max_tokens": MAX_TOKENS,
            "weights_sha256": MODEL_WEIGHTS_SHA256,
        },
        "inputs": {
            "raid_sha256": hashlib.sha256(args.raid_data.read_bytes()).hexdigest(),
            "faid_revision": FAID_REVISION,
            "padben_task5_sha256": (
                hashlib.sha256(args.padben_task5.read_bytes()).hexdigest()
                if args.padben_task5
                else None
            ),
        },
        "calibration": calibration,
        "external_faid": faid_result,
        "external_faid_local_human_calibration": local_human,
        "external_padben_task5": (
            summarize(padben, probability[faid_end:, ai_class], threshold) if padben else None
        ),
        "promotion_gate": {
            "passed": all(gates.values()),
            "conditions": gates,
            "local_human_conditions": local_conditions,
            "decision": "validation_only",
        },
        "warning": "RADAR checkpoint license prohibits commercial production use.",
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"external_faid": faid_result, "promotion_gate": report["promotion_gate"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
