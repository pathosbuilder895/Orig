"""Locked external cause test using RAID clean and paraphrased documents.

PADBen supplies all model fitting and threshold calibration. RAID is used only
as an external test domain: its generators, prompts, domains, and paraphrase
attack never participate in fitting. The current pinned sample is AI-only and
therefore evaluates direct-vs-humanized subtyping, not human false-positive
rates. If human rows are supplied, paraphrased humans remain human controls,
matching DAMAGE's recommendation to learn invariance rather than equating any
paraphrase with AI authorship.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import re
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Sequence

import numpy as np
from sklearn.metrics import confusion_matrix, precision_recall_fscore_support, roc_auc_score
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from validation.cause.padben import (
    CAUSES,
    DIRECT_AI,
    HUMAN,
    HUMANIZED_AI,
    fit_calibrated_cause_model,
    fit_ai_subtype_discriminator,
    load_feature_matrix,
    one_sided_precision_threshold,
    PadBenBundle,
)
from validation.stacked.fusion import select_cause


DATASET_REVISION = "865cac74188466cb0c3b7574a10204007b57a459"
RAID_TRAIN_URL = "https://huggingface.co/datasets/liamdugan/raid/resolve/main/train.csv"
RAID_TRAIN_SIZE = 11_779_491_051
DEFAULT_MODELS = ("gpt4", "chatgpt", "mistral-chat", "llama-chat")
DEFAULT_DOMAINS = ("books", "news", "reviews", "abstracts")
DEFAULT_ATTACKS = ("none", "paraphrase")
BOOKS_TWO_ATTACK_RANGES = (
    (1_957_000_000, 1_967_000_000),
    (1_968_000_000, 1_989_000_000),
    (2_161_000_000, 2_171_000_000),
    (2_173_000_000, 2_190_000_000),
    (2_229_000_000, 2_237_000_000),
    (2_238_000_000, 2_254_000_000),
)
BOOKS_HUMAN_TWO_ATTACK_RANGES = (
    (1_455_000_000, 1_475_000_000),
    (1_583_000_000, 1_631_000_000),
    (1_675_000_000, 1_711_000_000),
)
_RECORD_START = re.compile(
    rb"(?m)^(?=[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12},)"
)


def _rows_from_chunks(header: bytes, chunks: Sequence[bytes]) -> list[dict]:
    """Parse complete multiline CSV records from arbitrary byte ranges."""

    rows: list[dict] = []
    header_text = header.decode("utf-8", errors="strict")
    for chunk in chunks:
        starts = [match.start() for match in _RECORD_START.finditer(chunk)]
        # The last record may continue past the byte range. Only segments with
        # both a detected start and a following start are provably complete.
        for start, end in zip(starts, starts[1:]):
            segment = chunk[start:end].decode("utf-8", errors="replace").rstrip("\r\n")
            parsed = list(csv.DictReader(io.StringIO(header_text + "\n" + segment)))
            if len(parsed) == 1 and None not in parsed[0]:
                rows.append(parsed[0])
    return rows


def fetch_sample(
    output: Path,
    *,
    models: Sequence[str] = DEFAULT_MODELS,
    domains: Sequence[str] = DEFAULT_DOMAINS,
    attacks: Sequence[str] = DEFAULT_ATTACKS,
    rows_per_cell: int = 25,
    min_words: int = 100,
    n_offsets: int = 96,
    chunk_bytes: int = 750_000,
    byte_offsets: Sequence[int] | None = None,
) -> list[dict]:
    """Range-sample the pinned raw CSV, then stratify locally."""

    from scripts.fetch_benchmark_data import _get_range

    header = _get_range(RAID_TRAIN_URL, 0, 8192).split(b"\n", 1)[0]
    offsets = (
        list(byte_offsets)
        if byte_offsets is not None
        else [int(RAID_TRAIN_SIZE * (i + 0.5) / n_offsets) for i in range(n_offsets)]
    )
    chunks = []
    for offset in offsets:
        data = _get_range(RAID_TRAIN_URL, offset, offset + chunk_bytes)
        first_newline = data.find(b"\n")
        last_newline = data.rfind(b"\n")
        if first_newline != -1 and last_newline > first_newline:
            chunks.append(data[first_newline + 1 : last_newline])
    sampled_rows = []
    block_map = []
    for offset, chunk in zip(offsets, chunks):
        chunk_rows = _rows_from_chunks(header, [chunk])
        sampled_rows.extend(chunk_rows)
        if chunk_rows:
            block_counts = Counter(
                (row.get("model"), row.get("domain"), row.get("attack"))
                for row in chunk_rows
            )
            (model, domain, attack), count = block_counts.most_common(1)[0]
            block_map.append(
                {
                    "offset": offset,
                    "model": model,
                    "domain": domain,
                    "attack": attack,
                    "rows": count,
                }
            )
    wanted_models = set(models)
    wanted_domains = set(domains)
    wanted_attacks = set(attacks)
    cells: dict[tuple[str, str, str], dict[str, dict]] = defaultdict(dict)
    for row in sampled_rows:
        if row.get("model") not in wanted_models:
            continue
        if row.get("domain") not in wanted_domains:
            continue
        if row.get("attack") not in wanted_attacks:
            continue
        if len(str(row.get("generation") or "").split()) < min_words:
            continue
        key = (row["model"], row["domain"], row["attack"])
        cells[key][str(row["id"])] = row
    required = [
        (model, domain, attack)
        for model in models
        for domain in domains
        for attack in attacks
    ]
    incomplete = {":".join(key): len(cells[key]) for key in required if len(cells[key]) < rows_per_cell}
    if incomplete:
        observed = {
            ":".join(key): len(rows_by_id)
            for key, rows_by_id in sorted(cells.items())
            if rows_by_id
        }
        raise RuntimeError(
            f"range sample did not cover every requested RAID cell: {incomplete}; "
            f"observed requested cells: {observed}; sampled blocks: {block_map}; "
            "increase --offsets or --chunk-bytes"
        )
    rows = []
    for key in required:
        # UUID order gives a deterministic, model-independent selection.
        rows.extend(cells[key][row_id] for row_id in sorted(cells[key])[:rows_per_cell])
    cell_counts = {":".join(key): len(cells[key]) for key in required}
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "dataset": "liamdugan/raid",
        "revision": DATASET_REVISION,
        "license": "MIT",
        "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "parameters": {
            "models": list(models),
            "domains": list(domains),
            "attacks": list(attacks),
            "scope": "AI-only external subtype test; human false-positive rates are evaluated elsewhere",
            "rows_per_cell": rows_per_cell,
            "min_words": min_words,
            "cell_counts": cell_counts,
            "n_offsets": n_offsets,
            "byte_offsets": offsets if byte_offsets is not None else None,
            "chunk_bytes": chunk_bytes,
            "raw_train_size": RAID_TRAIN_SIZE,
        },
        "rows": rows,
    }
    output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return rows


def _matched_attack_rows(
    rows: Sequence[dict],
    *,
    models: Sequence[str],
    attacks: Sequence[str],
    rows_per_model: int,
    min_words: int,
) -> list[dict]:
    """Select clean/attack triplets sharing the exact original generation."""

    requested_attacks = tuple(attacks)
    clean = {
        row["id"]: row
        for row in rows
        if row.get("model") in models and row.get("attack") == "none"
    }
    attacked: dict[str, dict[str, dict]] = defaultdict(dict)
    for row in rows:
        if row.get("model") in models and row.get("attack") in requested_attacks:
            attacked[str(row.get("adv_source_id"))][str(row["attack"])] = row
    selected = []
    for model in models:
        eligible = []
        for root_id, clean_row in clean.items():
            if clean_row.get("model") != model:
                continue
            variants = attacked.get(root_id, {})
            if not all(attack in variants for attack in requested_attacks):
                continue
            triplet = [clean_row, *(variants[attack] for attack in requested_attacks)]
            if all(len(str(row.get("generation") or "").split()) >= min_words for row in triplet):
                eligible.append((root_id, triplet))
        if len(eligible) < rows_per_model:
            raise RuntimeError(
                f"matched RAID support for {model} is {len(eligible)}; "
                f"need {rows_per_model}"
            )
        # UUID order is fixed by the pinned source and independent of features.
        for _, triplet in sorted(eligible)[:rows_per_model]:
            selected.extend(triplet)
    return selected


def fetch_matched_attack_sample(
    output: Path,
    *,
    byte_ranges: Sequence[tuple[int, int]] = BOOKS_TWO_ATTACK_RANGES,
    models: Sequence[str] = ("llama-chat", "mistral-chat"),
    attacks: Sequence[str] = ("synonym", "paraphrase"),
    rows_per_model: int = 60,
    min_words: int = 100,
    include_human: bool = False,
) -> list[dict]:
    """Fetch deterministic exact-source clean/synonym/paraphrase triplets."""

    from scripts.fetch_benchmark_data import _get_range

    header = _get_range(RAID_TRAIN_URL, 0, 8192).split(b"\n", 1)[0]
    effective_ranges = tuple(byte_ranges) + (
        BOOKS_HUMAN_TWO_ATTACK_RANGES if include_human else ()
    )
    effective_models = tuple(models) + (("human",) if include_human else ())
    chunks = [_get_range(RAID_TRAIN_URL, start, end) for start, end in effective_ranges]
    candidates = _rows_from_chunks(header, chunks)
    rows = _matched_attack_rows(
        candidates,
        models=effective_models,
        attacks=attacks,
        rows_per_model=rows_per_model,
        min_words=min_words,
    )
    payload = {
        "dataset": "liamdugan/raid",
        "revision": DATASET_REVISION,
        "license": "MIT",
        "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "parameters": {
            "models": list(effective_models),
            "domains": ["books"],
            "attacks": ["none", *attacks],
            "paired_by": "attacked adv_source_id == clean id",
            "rows_per_model_per_state": rows_per_model,
            "min_words_in_every_state": min_words,
            "byte_ranges": [list(values) for values in effective_ranges],
            "raw_train_size": RAID_TRAIN_SIZE,
        },
        "rows": rows,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return rows


def cause_for(row: dict) -> str:
    if row["model"] == "human":
        return HUMAN
    return DIRECT_AI if row["attack"] == "none" else HUMANIZED_AI


def _extract_raid(rows: Sequence[dict], workers: int) -> np.ndarray:
    from original.ai_likelihood import predict_ai_likelihood_batch
    from scripts.train_ai_detector import _extract_parallel

    features = _extract_parallel([row["generation"] for row in rows], workers, "raid-cause")
    probabilities = predict_ai_likelihood_batch(features)
    if probabilities is None:
        probabilities = np.full(len(features), np.nan, dtype=np.float64)
    return np.column_stack([features.astype(np.float64), probabilities])


def _load_raid_features(data_path: Path, output: Path, workers: int) -> tuple[list[dict], np.ndarray]:
    payload = json.loads(data_path.read_text(encoding="utf-8"))
    rows = payload["rows"]
    cache_path = output.with_suffix(".features.npz")
    cache_key = hashlib.sha256(data_path.read_bytes()).hexdigest()
    if cache_path.exists():
        cached = np.load(cache_path, allow_pickle=False)
        if str(cached["cache_key"].item()) == cache_key:
            return rows, cached["X"]
    X = _extract_raid(rows, workers)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(cache_path, X=X, cache_key=np.asarray(cache_key))
    return rows, X


def _metrics(truth: np.ndarray, predicted: np.ndarray) -> dict:
    covered = predicted != "unknown_other"
    precision, recall, f1, support = precision_recall_fscore_support(
        truth, predicted, labels=list(CAUSES), zero_division=0
    )
    return {
        "n": len(truth),
        "coverage": round(float(covered.mean()), 4),
        "selective_accuracy": round(float((predicted[covered] == truth[covered]).mean()), 4)
        if covered.any()
        else None,
        "per_class": {
            cause: {
                "precision": round(float(precision[i]), 4),
                "recall": round(float(recall[i]), 4),
                "f1": round(float(f1[i]), 4),
                "support": int(support[i]),
            }
            for i, cause in enumerate(CAUSES)
        },
        "prediction_counts": dict(Counter(predicted.tolist())),
        "confusion_labels": [*CAUSES, "unknown_other"],
        "confusion": confusion_matrix(
            truth, predicted, labels=[*CAUSES, "unknown_other"]
        ).tolist(),
    }


def evaluate_cross_generator_subtype(
    X: np.ndarray,
    rows: Sequence[dict],
) -> dict:
    """Leave-one-generator-out ranking with source-prompt overlap removed."""

    generators = np.asarray([row["model"] for row in rows], dtype=object)
    sources = np.asarray([row["source_id"] for row in rows], dtype=object)
    labels = np.asarray([cause_for(row) for row in rows], dtype=object)
    truth = labels == HUMANIZED_AI
    unique_generators = sorted(set(generators.tolist()))
    if len(unique_generators) < 2:
        raise ValueError("need at least two RAID generators for held-out evaluation")
    pooled_truth = []
    pooled_probability = []
    folds = {}
    for held_out in unique_generators:
        train = generators != held_out
        train_sources = set(sources[train].tolist())
        test = (generators == held_out) & ~np.isin(sources, list(train_sources))
        model = fit_ai_subtype_discriminator(X[train], labels[train])
        probability = model.predict_proba(X[test])[:, 1]
        fold_truth = truth[test]
        pooled_truth.extend(fold_truth.tolist())
        pooled_probability.extend(probability.tolist())
        folds[held_out] = {
            "n_train": int(train.sum()),
            "n_locked": int(test.sum()),
            "excluded_shared_source_prompts": int((generators == held_out).sum() - test.sum()),
            "auc": round(float(roc_auc_score(fold_truth, probability)), 4),
            "mean_probability_direct": round(float(probability[~fold_truth].mean()), 4),
            "mean_probability_humanized": round(float(probability[fold_truth].mean()), 4),
        }
    return {
        "pooled_auc": round(float(roc_auc_score(pooled_truth, pooled_probability)), 4),
        "n_locked": len(pooled_truth),
        "folds": folds,
        "warning": (
            "Generator is held out and shared source prompts are removed, but domain and "
            "paraphrase attack family are shared. This tests generator transfer only."
        ),
    }


def _stable_source_bucket(source_id: str, salt: str) -> int:
    digest = hashlib.sha256(f"{salt}:{source_id}".encode("utf-8")).digest()
    return digest[0] & 1


def _binary_selective_metrics(
    truth_humanized: np.ndarray,
    predicted: np.ndarray,
) -> dict:
    labels = (DIRECT_AI, HUMANIZED_AI)
    truth = np.where(truth_humanized, HUMANIZED_AI, DIRECT_AI)
    covered = predicted != "unknown_other"
    result = {
        "n": len(truth),
        "coverage": round(float(covered.mean()), 4),
        "selective_accuracy": round(float((predicted[covered] == truth[covered]).mean()), 4)
        if covered.any()
        else None,
        "prediction_counts": dict(Counter(predicted.tolist())),
        "per_class": {},
    }
    for label in labels:
        actual = truth == label
        selected = predicted == label
        true_positive = int((actual & selected).sum())
        result["per_class"][label] = {
            "precision": round(true_positive / int(selected.sum()), 4) if selected.any() else None,
            "recall": round(true_positive / int(actual.sum()), 4) if actual.any() else None,
            "selected": int(selected.sum()),
            "support": int(actual.sum()),
        }
    return result


def _select_binary_subtype(
    probability: np.ndarray,
    *,
    direct_threshold: float,
    humanized_threshold: float,
) -> np.ndarray:
    """Select only non-overlapping tails; ambiguous threshold overlap abstains."""

    probability = np.asarray(probability, dtype=np.float64)
    direct = probability <= direct_threshold
    humanized = probability >= humanized_threshold
    predicted = np.full(len(probability), "unknown_other", dtype=object)
    predicted[direct & ~humanized] = DIRECT_AI
    predicted[humanized & ~direct] = HUMANIZED_AI
    return predicted


def assess_attack_family_promotion(
    result: dict,
    *,
    min_auc: float = 0.80,
    min_precision: float = 0.90,
    min_recall: float = 0.50,
    min_coverage: float = 0.40,
    min_support: int = 20,
) -> dict:
    """Apply predeclared subtype-only gates to every held attack family."""

    failures = []
    for attack, fold in sorted(result["folds"].items()):
        metrics = fold["selective_metrics"]
        if fold["auc"] < min_auc:
            failures.append(f"{attack}:auc<{min_auc}")
        if metrics["coverage"] < min_coverage:
            failures.append(f"{attack}:coverage<{min_coverage}")
        for label in (DIRECT_AI, HUMANIZED_AI):
            values = metrics["per_class"][label]
            if values["support"] < min_support:
                failures.append(f"{attack}:{label}:support<{min_support}")
            if values["precision"] is None or values["precision"] < min_precision:
                failures.append(f"{attack}:{label}:precision<{min_precision}")
            if values["recall"] is None or values["recall"] < min_recall:
                failures.append(f"{attack}:{label}:recall<{min_recall}")
    return {
        "passed": not failures,
        "failures": failures,
        "gates": {
            "min_auc": min_auc,
            "min_precision": min_precision,
            "min_recall": min_recall,
            "min_coverage": min_coverage,
            "min_support": min_support,
        },
        "scope": (
            "AI subtype gate only. Full cause promotion additionally requires locked genuine-human "
            "false-positive and human-ghostwriter evidence."
        ),
    }


def evaluate_cross_attack_family_subtype(
    X: np.ndarray,
    rows: Sequence[dict],
    *,
    target_precision: float = 0.90,
    min_calibration_predictions: int = 5,
    seed: int = 1729,
) -> dict:
    """Hold out each non-clean attack with locked, source-disjoint controls."""

    X = np.asarray(X, dtype=np.float64)
    if len(X) != len(rows):
        raise ValueError("X and rows must have equal length")
    attacks = np.asarray([str(row["attack"]) for row in rows], dtype=object)
    generators = np.asarray([str(row["model"]) for row in rows], dtype=object)
    sources = np.asarray([str(row["source_id"]) for row in rows], dtype=object)
    attack_families = sorted(set(attacks.tolist()) - {"none"})
    if len(attack_families) < 2:
        raise ValueError("need at least two non-clean attack families")
    if len(set(generators.tolist())) < 2:
        raise ValueError("need at least two generators")

    folds = {}
    for fold_index, held_attack in enumerate(attack_families):
        held_positive = attacks == held_attack
        clean = attacks == "none"
        locked_bucket = np.asarray(
            [_stable_source_bucket(source, held_attack) == 1 for source in sources]
        )
        proposed_locked = locked_bucket & (held_positive | clean)
        locked_sources = set(sources[proposed_locked].tolist())
        development = (
            (clean | ((attacks != "none") & (attacks != held_attack)))
            & ~locked_bucket
            & ~np.isin(sources, list(locked_sources))
        )
        locked = proposed_locked
        development_labels = attacks[development] != "none"
        locked_labels = attacks[locked] != "none"
        if set(development_labels.tolist()) != {False, True}:
            raise ValueError(f"{held_attack}: development lacks a subtype class")
        if set(locked_labels.tolist()) != {False, True}:
            raise ValueError(f"{held_attack}: locked test lacks a subtype class")

        development_indices = np.flatnonzero(development)
        calibration_probability = []
        calibration_truth = []
        for generator_index, calibration_generator in enumerate(
            sorted(set(generators[development].tolist()))
        ):
            calibration_local = generators[development_indices] == calibration_generator
            fit_indices = development_indices[~calibration_local]
            calibration_indices = development_indices[calibration_local]
            fit_labels = attacks[fit_indices] != "none"
            if set(fit_labels.tolist()) != {False, True}:
                continue
            model = fit_ai_subtype_discriminator(
                X[fit_indices],
                np.where(fit_labels, HUMANIZED_AI, DIRECT_AI),
                seed=seed + fold_index * 10 + generator_index,
            )
            calibration_probability.extend(
                model.predict_proba(X[calibration_indices])[:, 1].tolist()
            )
            calibration_truth.extend((attacks[calibration_indices] != "none").tolist())
        if not calibration_probability:
            raise ValueError(f"{held_attack}: generator-held calibration is unavailable")
        calibration_probability_array = np.asarray(calibration_probability, dtype=np.float64)
        calibration_truth_array = np.asarray(calibration_truth, dtype=bool)
        humanized_threshold = one_sided_precision_threshold(
            calibration_probability_array,
            calibration_truth_array,
            positive=True,
            target_precision=target_precision,
            min_predictions=min_calibration_predictions,
        )
        direct_threshold = one_sided_precision_threshold(
            calibration_probability_array,
            calibration_truth_array,
            positive=False,
            target_precision=target_precision,
            min_predictions=min_calibration_predictions,
        )

        final = fit_ai_subtype_discriminator(
            X[development],
            np.where(development_labels, HUMANIZED_AI, DIRECT_AI),
            seed=seed + fold_index,
        )
        probability = final.predict_proba(X[locked])[:, 1]
        predicted = _select_binary_subtype(
            probability,
            direct_threshold=direct_threshold,
            humanized_threshold=humanized_threshold,
        )
        folds[held_attack] = {
            "n_development": int(development.sum()),
            "n_locked": int(locked.sum()),
            "development_source_count": len(set(sources[development].tolist())),
            "locked_source_count": len(set(sources[locked].tolist())),
            "source_overlap": len(
                set(sources[development].tolist()) & set(sources[locked].tolist())
            ),
            "calibration_n": len(calibration_probability),
            "thresholds": {
                DIRECT_AI: round(float(direct_threshold), 6),
                HUMANIZED_AI: round(float(humanized_threshold), 6),
            },
            "auc": round(float(roc_auc_score(locked_labels, probability)), 4),
            "selective_metrics": _binary_selective_metrics(locked_labels, predicted),
        }
    result = {
        "attack_families": attack_families,
        "folds": folds,
        "split": (
            "leave-one-attack-family-out with a stable source-level development/locked split; "
            "held-family development-source rows are discarded; all locked source prompts are "
            "excluded from development; thresholds use "
            "generator-held-out development predictions"
        ),
    }
    result["promotion_gate"] = assess_attack_family_promotion(result)
    return result


def _fpr_threshold(scores: np.ndarray, target_fpr: float) -> float:
    """Highest-recall threshold whose empirical negative FPR is in budget."""

    scores = np.sort(np.asarray(scores, dtype=np.float64))[::-1]
    allowed = int(np.floor(target_fpr * len(scores)))
    if allowed == 0:
        return float(np.nextafter(scores[0], np.inf))
    return float(scores[allowed - 1])


def evaluate_ai_origin_invariance(
    X: np.ndarray,
    rows: Sequence[dict],
    *,
    target_human_fpr: float = 0.01,
    seed: int = 1729,
) -> dict:
    """Hold out both an AI generator and a rewriting attack family.

    Human text transformed by the same attack stays negative. This evaluates
    AI-origin invariance, not whether a document was specifically rewritten.
    """

    X = np.asarray(X, dtype=np.float64)
    attacks = np.asarray([str(row["attack"]) for row in rows], dtype=object)
    models = np.asarray([str(row["model"]) for row in rows], dtype=object)
    roots = np.asarray(
        [str(row["id"] if row["attack"] == "none" else row["adv_source_id"]) for row in rows],
        dtype=object,
    )
    is_ai = models != "human"
    attack_families = sorted(set(attacks.tolist()) - {"none"})
    generators = sorted(set(models[is_ai].tolist()))
    if len(attack_families) < 2 or len(generators) < 2 or "human" not in set(models):
        raise ValueError("need human controls, two AI generators, and two attack families")
    buckets = np.asarray(
        [int(hashlib.sha256(f"raid-origin:{root}".encode()).hexdigest()[:8], 16) % 10 for root in roots]
    )
    folds = {}
    for held_attack in attack_families:
        training_attacks = {"none", *(set(attack_families) - {held_attack})}
        for held_generator in generators:
            train_population = (models == "human") | ((models != "human") & (models != held_generator))
            development = (buckets < 6) & train_population & np.isin(attacks, list(training_attacks))
            calibration = (
                (buckets >= 6)
                & (buckets < 8)
                & train_population
                & np.isin(attacks, list(training_attacks))
            )
            locked_population = (models == "human") | (models == held_generator)
            locked = (buckets >= 8) & locked_population & np.isin(attacks, ["none", held_attack])
            if set(is_ai[development].tolist()) != {False, True}:
                raise ValueError("development partition lacks a class")
            if set(is_ai[calibration].tolist()) != {False, True}:
                raise ValueError("calibration partition lacks a class")
            if set(is_ai[locked].tolist()) != {False, True}:
                raise ValueError("locked partition lacks a class")
            model = Pipeline(
                [
                    ("scale", StandardScaler()),
                    (
                        "logistic",
                        LogisticRegression(
                            C=0.25,
                            class_weight="balanced",
                            max_iter=2000,
                            random_state=seed,
                        ),
                    ),
                ]
            )
            model.fit(X[development], is_ai[development])
            calibration_probability = model.predict_proba(X[calibration])[:, 1]
            threshold = _fpr_threshold(
                calibration_probability[~is_ai[calibration]], target_human_fpr
            )
            probability = model.predict_proba(X[locked])[:, 1]
            truth = is_ai[locked]
            predicted_ai = probability >= threshold
            locked_attacks = attacks[locked]
            direct = truth & (locked_attacks == "none")
            attacked = truth & (locked_attacks == held_attack)
            human = ~truth
            selected = predicted_ai
            true_positive = int((selected & truth).sum())
            folds[f"attack={held_attack}|generator={held_generator}"] = {
                "held_attack": held_attack,
                "held_generator": held_generator,
                "n_development": int(development.sum()),
                "n_calibration": int(calibration.sum()),
                "n_locked": int(locked.sum()),
                "source_overlap": len(
                    set(roots[development | calibration].tolist()) & set(roots[locked].tolist())
                ),
                "threshold": round(threshold, 6),
                "auc": round(float(roc_auc_score(truth, probability)), 4),
                "precision_ai": round(true_positive / int(selected.sum()), 4)
                if selected.any()
                else None,
                "human_fpr": round(float(predicted_ai[human].mean()), 4),
                "direct_ai_tpr": round(float(predicted_ai[direct].mean()), 4),
                "held_attack_ai_tpr": round(float(predicted_ai[attacked].mean()), 4),
                "support": {
                    "human": int(human.sum()),
                    "direct_ai": int(direct.sum()),
                    "held_attack_ai": int(attacked.sum()),
                },
            }
    failures = []
    for name, fold in folds.items():
        if fold["auc"] < 0.85:
            failures.append(f"{name}:auc<0.85")
        if fold["human_fpr"] > target_human_fpr:
            failures.append(f"{name}:human_fpr>{target_human_fpr}")
        if fold["direct_ai_tpr"] < 0.50:
            failures.append(f"{name}:direct_ai_tpr<0.50")
        if fold["held_attack_ai_tpr"] < 0.50:
            failures.append(f"{name}:held_attack_ai_tpr<0.50")
        for label, support in fold["support"].items():
            if support < 20:
                failures.append(f"{name}:{label}_support<20")
    return {
        "folds": folds,
        "split": (
            "root-source-disjoint 60/20/20 development/calibration/locked split; "
            "each fold holds out one AI generator and one rewrite attack; attacked human "
            "text remains human; threshold selected only from calibration human controls"
        ),
        "promotion_gate": {
            "passed": not failures,
            "failures": failures,
            "gates": {
                "min_auc": 0.85,
                "max_human_fpr": target_human_fpr,
                "min_direct_ai_tpr": 0.50,
                "min_held_attack_ai_tpr": 0.50,
                "min_slice_support": 20,
            },
        },
    }


def evaluate_external_ai_origin(
    X_train: np.ndarray,
    train_rows: Sequence[dict],
    X_external: np.ndarray,
    external_bundles: Sequence[PadBenBundle],
    *,
    target_human_fpr: float = 0.01,
    seed: int = 1729,
) -> dict:
    """Fit/calibrate on RAID only and test once on external PADBen bundles."""

    X_train = np.asarray(X_train, dtype=np.float64)
    roots = np.asarray(
        [
            str(row["id"] if row["attack"] == "none" else row["adv_source_id"])
            for row in train_rows
        ],
        dtype=object,
    )
    labels = np.asarray([row["model"] != "human" for row in train_rows], dtype=bool)
    buckets = np.asarray(
        [int(hashlib.sha256(f"raid-external:{root}".encode()).hexdigest()[:8], 16) % 10 for root in roots]
    )
    development = buckets < 8
    calibration = ~development
    model = Pipeline(
        [
            ("scale", StandardScaler()),
            (
                "logistic",
                LogisticRegression(
                    C=0.25,
                    class_weight="balanced",
                    max_iter=2000,
                    random_state=seed,
                ),
            ),
        ]
    )
    model.fit(X_train[development], labels[development])
    calibration_probability = model.predict_proba(X_train[calibration])[:, 1]
    threshold = _fpr_threshold(
        calibration_probability[~labels[calibration]], target_human_fpr
    )
    probability = model.predict_proba(np.asarray(X_external, dtype=np.float64))[:, 1]
    truth = np.asarray([bundle.cause != HUMAN for bundle in external_bundles], dtype=bool)
    direct = np.asarray([bundle.cause == DIRECT_AI for bundle in external_bundles])
    humanized = np.asarray([bundle.cause == HUMANIZED_AI for bundle in external_bundles])
    predicted = probability >= threshold
    selected = int(predicted.sum())
    return {
        "n_development": int(development.sum()),
        "n_calibration": int(calibration.sum()),
        "calibration_human_support": int((~labels[calibration]).sum()),
        "development_external_source_overlap": 0,
        "threshold": round(threshold, 6),
        "n_external": len(external_bundles),
        "external_source_domains": sorted({bundle.source for bundle in external_bundles}),
        "auc": round(float(roc_auc_score(truth, probability)), 4),
        "human_fpr": round(float(predicted[~truth].mean()), 4),
        "direct_ai_tpr": round(float(predicted[direct].mean()), 4),
        "humanized_ai_tpr": round(float(predicted[humanized].mean()), 4),
        "precision_ai": round(float(truth[predicted].mean()), 4) if selected else None,
        "selected": selected,
        "support": {
            "human": int((~truth).sum()),
            "direct_ai": int(direct.sum()),
            "humanized_ai": int(humanized.sum()),
        },
        "passed": bool(
            roc_auc_score(truth, probability) >= 0.85
            and predicted[~truth].mean() <= target_human_fpr
            and predicted[direct].mean() >= 0.50
            and predicted[humanized].mean() >= 0.50
        ),
    }


def feature_direction_audit(
    X_train: np.ndarray,
    train_labels: np.ndarray,
    X_external: np.ndarray,
    external_labels: np.ndarray,
) -> dict:
    """Post-hoc diagnostic of per-feature direction stability across corpora."""

    from scipy.stats import spearmanr
    from original.constants import ALL_FEATURE_CODES

    names = [*ALL_FEATURE_CODES, "frozen_ai_likelihood"]
    rows = []
    for index, name in enumerate(names):
        train_auc = float(roc_auc_score(train_labels, X_train[:, index]))
        external_auc = float(roc_auc_score(external_labels, X_external[:, index]))
        reversal = (train_auc - 0.5) * (external_auc - 0.5) < 0
        rows.append(
            {
                "feature": name,
                "raid_auc": round(train_auc, 4),
                "external_auc": round(external_auc, 4),
                "direction_reversal": bool(reversal),
                "minimum_effect": round(min(abs(train_auc - 0.5), abs(external_auc - 0.5)), 4),
            }
        )
    stable = sorted(
        (row for row in rows if not row["direction_reversal"]),
        key=lambda row: row["minimum_effect"],
        reverse=True,
    )
    reversals = sorted(
        (row for row in rows if row["direction_reversal"]),
        key=lambda row: row["minimum_effect"],
        reverse=True,
    )
    correlation = spearmanr(
        [row["raid_auc"] for row in rows],
        [row["external_auc"] for row in rows],
    ).statistic
    return {
        "post_hoc_only": True,
        "feature_count": len(rows),
        "direction_reversal_count": len(reversals),
        "auc_direction_spearman": round(float(correlation), 4),
        "top_stable": stable[:20],
        "strongest_reversals": reversals[:20],
        "warning": "External labels were used for diagnosis; this list cannot fit a promoted model.",
    }


def padben_depth_rows(bundles: Sequence[object]) -> tuple[list[dict], np.ndarray]:
    """Map PADBen AI bundles to clean/first/third-depth attack metadata."""

    rows = []
    keep = []
    for index, bundle in enumerate(bundles):
        cause = getattr(bundle, "cause")
        if cause == DIRECT_AI:
            attack = "none"
        elif cause == HUMANIZED_AI and "-1st" in getattr(bundle, "variant"):
            attack = "paraphrase_1st"
        elif cause == HUMANIZED_AI and "-3rd" in getattr(bundle, "variant"):
            attack = "paraphrase_3rd"
        else:
            continue
        source = str(getattr(bundle, "source"))
        row_ids = tuple(getattr(bundle, "row_ids"))
        rows.append(
            {
                "model": source,
                "attack": attack,
                "source_id": f"{source}:{','.join(str(value) for value in row_ids)}",
            }
        )
        keep.append(index)
    return rows, np.asarray(keep, dtype=np.int64)


def run(
    raid_data: Path,
    padben_data: Path,
    *,
    output: Path,
    workers: int = 4,
    min_margin: float = 0.10,
) -> dict:
    """Fit on PADBen only, then evaluate once on the external RAID sample."""

    # Share the content-addressed PADBen cache with its standalone benchmark;
    # load_feature_matrix verifies the input hash and bundling parameters.
    padben_cache = output.parent / "padben_cause_stress.features.npz"
    bundles, X_train = load_feature_matrix(
        padben_data,
        cache_path=padben_cache,
        workers=workers,
    )
    model, thresholds = fit_calibrated_cause_model(
        X_train,
        [bundle.cause for bundle in bundles],
        [bundle.source for bundle in bundles],
    )
    padben_depth_metadata, padben_depth_indices = padben_depth_rows(bundles)
    padben_depth_transfer = evaluate_cross_attack_family_subtype(
        X_train[padben_depth_indices], padben_depth_metadata
    )
    rows, X_test = _load_raid_features(raid_data, output, workers)
    truth = np.asarray([cause_for(row) for row in rows], dtype=object)
    raw = model.predict_proba(X_test)
    classes = model.named_steps["logistic"].classes_
    predicted = np.empty(len(rows), dtype=object)
    for index, probabilities in enumerate(raw):
        probability_map = dict(zip(classes, probabilities))
        best = max(probability_map, key=probability_map.get)
        predicted[index] = select_cause(
            probability_map,
            min_probability=thresholds[best],
            min_margin=min_margin,
        ).label

    subtype_model = fit_ai_subtype_discriminator(
        X_train, [bundle.cause for bundle in bundles]
    )
    subtype_probability = subtype_model.predict_proba(X_test)[:, 1]
    subtype_truth = truth == HUMANIZED_AI
    subtype_auc = float(roc_auc_score(subtype_truth, subtype_probability))
    # Humanization should generally reduce a frozen AI detector score, hence
    # the negative sign when ranking humanized as the positive class.
    frozen_humanization_auc = float(roc_auc_score(subtype_truth, -X_test[:, -1]))
    subtype_by_model = {}
    for model_name in sorted({row["model"] for row in rows}):
        mask = np.asarray([row["model"] == model_name for row in rows])
        subtype_by_model[model_name] = {
            "n": int(mask.sum()),
            "padben_subtype_auc": round(
                float(roc_auc_score(subtype_truth[mask], subtype_probability[mask])), 4
            ),
            "frozen_ai_inverse_auc": round(
                float(roc_auc_score(subtype_truth[mask], -X_test[mask, -1])), 4
            ),
        }

    slices = defaultdict(list)
    for index, row in enumerate(rows):
        slices[f"model:{row['model']}"].append(index)
        slices[f"domain:{row['domain']}"].append(index)
        if row["model"] == "human":
            slices[f"human_control_attack:{row['attack']}"].append(index)
    attack_families = sorted({str(row["attack"]) for row in rows} - {"none"})
    if len(attack_families) >= 2:
        attack_family_transfer = evaluate_cross_attack_family_subtype(X_test, rows)
    else:
        attack_family_transfer = {
            "status": "not_evaluated",
            "attack_families": attack_families,
            "reason": "need at least two non-clean attack families",
            "promotion_gate": {
                "passed": False,
                "failures": ["attack_family_count<2"],
                "scope": "AI subtype gate only; full cause promotion also requires human controls",
            },
        }
    report = {
        "dataset": "RAID clean/paraphrase external AI-subtype test (MIT)",
        "source_url": "https://huggingface.co/datasets/liamdugan/raid",
        "dataset_revision": DATASET_REVISION,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "raid_input_sha256": hashlib.sha256(raid_data.read_bytes()).hexdigest(),
        "padben_input_sha256": hashlib.sha256(padben_data.read_bytes()).hexdigest(),
        "training": "PADBen only; source-held-out threshold calibration",
        "locked_test": (
            "RAID only; all generators, prompts, domains, and the paraphrase attack are external"
        ),
        "thresholds": thresholds,
        "padben_cross_paraphrase_depth_subtype": padben_depth_transfer,
        "metrics": _metrics(truth, predicted),
        "subtype_ranking": {
            "padben_trained_auc": round(subtype_auc, 4),
            "frozen_ai_inverse_auc": round(frozen_humanization_auc, 4),
            "by_model": subtype_by_model,
            "interpretation": (
                "AUC measures ranking only. It does not repair the failed PADBen precision "
                "thresholds or justify an external subtype label."
            ),
        },
        "raid_local_cross_generator_subtype": evaluate_cross_generator_subtype(X_test, rows),
        "raid_local_cross_attack_family_subtype": attack_family_transfer,
        "slices": {
            name: _metrics(truth[indices], predicted[indices])
            for name, indices in sorted(slices.items())
        },
        "source_group_count": len({row["source_id"] for row in rows}),
        "warning": (
            "RAID documents are multi-domain detector benchmarks, not a representative sample "
            "of student essays. This AI-only test cannot estimate human false-positive rates, "
            "and a paraphrase attack is one humanization family."
        ),
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def run_attack_family(
    raid_data: Path,
    *,
    output: Path,
    workers: int = 4,
) -> dict:
    """Run RAID-local leave-one-attack-family-out AI subtyping only.

    PADBen is intentionally absent. Fitting and threshold calibration use the
    non-held RAID attack family and source-disjoint clean controls; the held
    attack family is touched only for the locked evaluation.
    """

    rows, X = _load_raid_features(raid_data, output, workers)
    result = evaluate_cross_attack_family_subtype(X, rows)
    source_payload = json.loads(raid_data.read_text(encoding="utf-8"))
    report = {
        "dataset": "RAID leave-one-attack-family-out AI-subtype test (MIT)",
        "source_url": "https://huggingface.co/datasets/liamdugan/raid",
        "dataset_revision": DATASET_REVISION,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "raid_input_sha256": hashlib.sha256(raid_data.read_bytes()).hexdigest(),
        "sampling_parameters": source_payload.get("parameters", {}),
        "feature_stack": (
            "Original 103-feature vector plus frozen AI-likelihood probability; "
            "no representation is fitted on the locked attack family"
        ),
        "evaluation": result,
        "warning": (
            "This is an AI-subtype test only. It cannot promote a complete cause "
            "classifier without separate locked human and human-ghostwriter controls."
        ),
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def run_origin_invariance(
    raid_data: Path,
    *,
    output: Path,
    workers: int = 4,
) -> dict:
    """Run generator- and attack-held AI-origin invariance evaluation."""

    rows, X = _load_raid_features(raid_data, output, workers)
    result = evaluate_ai_origin_invariance(X, rows)
    source_payload = json.loads(raid_data.read_text(encoding="utf-8"))
    report = {
        "dataset": "RAID matched AI-origin invariance test (MIT)",
        "source_url": "https://huggingface.co/datasets/liamdugan/raid",
        "dataset_revision": DATASET_REVISION,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "raid_input_sha256": hashlib.sha256(raid_data.read_bytes()).hexdigest(),
        "sampling_parameters": source_payload.get("parameters", {}),
        "feature_stack": "Original 103 features plus frozen AI-likelihood probability",
        "evaluation": result,
        "interpretation": (
            "Positive means evidence of AI origin despite rewriting. This evaluator does not "
            "claim that it can identify which rewrite family was used."
        ),
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def run_external_origin(
    raid_data: Path,
    padben_data: Path,
    *,
    output: Path,
    workers: int = 4,
) -> dict:
    """Fit/calibrate on RAID and evaluate once on external PADBen."""

    from validation.cause.padben import load_feature_matrix

    raid_cache_anchor = output.with_name(f"{output.stem}.raid.json")
    rows, X_raid = _load_raid_features(raid_data, raid_cache_anchor, workers)
    padben_cache = output.with_name(f"{output.stem}.padben.features.npz")
    bundles, X_padben = load_feature_matrix(
        padben_data,
        cache_path=padben_cache,
        workers=workers,
    )
    result = evaluate_external_ai_origin(X_raid, rows, X_padben, bundles)
    raid_labels = np.asarray([row["model"] != "human" for row in rows], dtype=bool)
    external_labels = np.asarray([bundle.cause != HUMAN for bundle in bundles], dtype=bool)
    report = {
        "dataset": "RAID-trained AI-origin invariance evaluated on PADBen (MIT)",
        "raid_revision": DATASET_REVISION,
        "raid_input_sha256": hashlib.sha256(raid_data.read_bytes()).hexdigest(),
        "padben_input_sha256": hashlib.sha256(padben_data.read_bytes()).hexdigest(),
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "evaluation": result,
        "feature_direction_audit": feature_direction_audit(
            X_raid, raid_labels, X_padben, external_labels
        ),
        "split": (
            "RAID root-source 80/20 fitting/calibration; PADBen sources, generators, "
            "paraphraser, and domains are external and used once for evaluation"
        ),
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    fetch_parser = subparsers.add_parser("fetch")
    fetch_parser.add_argument("--output", required=True, type=Path)
    fetch_parser.add_argument("--rows-per-cell", type=int, default=25)
    fetch_parser.add_argument("--min-words", type=int, default=100)
    fetch_parser.add_argument(
        "--models", default=",".join(DEFAULT_MODELS), help="Comma-separated RAID model labels"
    )
    fetch_parser.add_argument(
        "--domains", default=",".join(DEFAULT_DOMAINS), help="Comma-separated RAID domains"
    )
    fetch_parser.add_argument(
        "--attacks", default=",".join(DEFAULT_ATTACKS), help="Comma-separated attack labels"
    )
    fetch_parser.add_argument("--offsets", type=int, default=96)
    fetch_parser.add_argument("--chunk-bytes", type=int, default=750_000)
    fetch_parser.add_argument(
        "--byte-offsets",
        help="Comma-separated explicit byte offsets; overrides evenly spaced offsets",
    )
    paired_parser = subparsers.add_parser(
        "fetch-matched-attacks",
        help="Fetch exact-source clean/synonym/paraphrase RAID triplets",
    )
    paired_parser.add_argument("--output", required=True, type=Path)
    paired_parser.add_argument("--rows-per-model", type=int, default=60)
    paired_parser.add_argument("--min-words", type=int, default=100)
    paired_parser.add_argument("--include-human", action="store_true")
    run_parser = subparsers.add_parser("run")
    run_parser.add_argument("--raid-data", required=True, type=Path)
    run_parser.add_argument("--padben-data", required=True, type=Path)
    run_parser.add_argument("--output", required=True, type=Path)
    run_parser.add_argument("--workers", type=int, default=4)
    attack_parser = subparsers.add_parser(
        "run-attack-family",
        help="Run RAID-local leave-one-attack-family-out AI subtyping only",
    )
    attack_parser.add_argument("--raid-data", required=True, type=Path)
    attack_parser.add_argument("--output", required=True, type=Path)
    attack_parser.add_argument("--workers", type=int, default=4)
    origin_parser = subparsers.add_parser(
        "run-origin-invariance",
        help="Hold out both an AI generator and a rewrite attack family",
    )
    origin_parser.add_argument("--raid-data", required=True, type=Path)
    origin_parser.add_argument("--output", required=True, type=Path)
    origin_parser.add_argument("--workers", type=int, default=4)
    external_parser = subparsers.add_parser(
        "run-external-origin",
        help="Fit/calibrate on RAID and evaluate AI-origin invariance on PADBen",
    )
    external_parser.add_argument("--raid-data", required=True, type=Path)
    external_parser.add_argument("--padben-data", required=True, type=Path)
    external_parser.add_argument("--output", required=True, type=Path)
    external_parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    if args.command == "fetch":
        rows = fetch_sample(
            args.output,
            models=[value.strip() for value in args.models.split(",") if value.strip()],
            domains=[value.strip() for value in args.domains.split(",") if value.strip()],
            attacks=[value.strip() for value in args.attacks.split(",") if value.strip()],
            rows_per_cell=args.rows_per_cell,
            min_words=args.min_words,
            n_offsets=args.offsets,
            chunk_bytes=args.chunk_bytes,
            byte_offsets=(
                [int(value) for value in args.byte_offsets.split(",")]
                if args.byte_offsets
                else None
            ),
        )
        print(json.dumps({"rows": len(rows), "output": str(args.output)}, indent=2))
        return 0
    if args.command == "fetch-matched-attacks":
        rows = fetch_matched_attack_sample(
            args.output,
            rows_per_model=args.rows_per_model,
            min_words=args.min_words,
            include_human=args.include_human,
        )
        print(json.dumps({"rows": len(rows), "output": str(args.output)}, indent=2))
        return 0
    if args.command == "run-attack-family":
        report = run_attack_family(
            args.raid_data,
            output=args.output,
            workers=args.workers,
        )
        print(json.dumps(report["evaluation"], indent=2))
        return 0
    if args.command == "run-origin-invariance":
        report = run_origin_invariance(
            args.raid_data,
            output=args.output,
            workers=args.workers,
        )
        print(json.dumps(report["evaluation"], indent=2))
        return 0
    if args.command == "run-external-origin":
        report = run_external_origin(
            args.raid_data,
            args.padben_data,
            output=args.output,
            workers=args.workers,
        )
        print(json.dumps(report["evaluation"], indent=2))
        return 0
    report = run(
        args.raid_data,
        args.padben_data,
        output=args.output,
        workers=args.workers,
    )
    print(json.dumps(report["metrics"], indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
