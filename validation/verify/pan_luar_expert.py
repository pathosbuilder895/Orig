"""Validation-only LUAR authorship expert on the PAN cross-topic lock.

The pretrained LUAR-MUD model represents an author episode (one or more
documents) as a 512-dimensional vector.  We represent each claimed author by
their three authenticated baseline documents and each probe by one document,
then calibrate cosine and enrolled-peer-relative signals using author-disjoint
development and calibration partitions.

Nothing in this module is imported by the live API.
"""

from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import math
import types
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Sequence

import numpy as np
from sklearn.linear_model import LogisticRegression
from sklearn.discriminant_analysis import LinearDiscriminantAnalysis
from sklearn.metrics import roc_auc_score
from sklearn.covariance import LedoitWolf
from sklearn.decomposition import PCA
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sklearn.preprocessing import PolynomialFeatures

from validation.stacked.fusion import cllr
from validation.verify.binary_auc import brier, tpr_at_fpr
from validation.verify.pan_corpus import DEFAULT_CACHE, ZENODO_DOI, ZENODO_RECORD
from validation.verify.pan_style_expert import (
    SEED,
    StyleAuthor,
    _fit_representations,
    _operating_result,
    _score_partition,
    _threshold_at_constraints,
    load_author_partitions,
    style_margin_only_signals,
)


MODEL_ID = "rrivera1849/LUAR-MUD"
MODEL_REVISION = "1c11d29789851d629e42455570780ec3cec89e6a"
MAX_TOKENS = 512
CACHE_SCHEMA = "original.pan_luar_embeddings.v1"
PAN21_ARCHIVE = "pan21-authorship-verification-test.zip"
PAN21_ARCHIVE_MD5 = "117a355b5ef649a02f15334d63564103"


@dataclass(frozen=True)
class LuarTrial:
    target_author: str
    source_author: str
    probe_index: int
    cosine_similarity: float
    baseline_mean_similarity: float = 0.0
    baseline_min_similarity: float = 0.0
    baseline_similarity_std: float = 0.0
    baseline_cohesion_mean: float = 0.0
    baseline_cohesion_min: float = 0.0
    plda_log_likelihood_ratio: float = 0.0
    lda_similarity: float = 0.0

    @property
    def label(self) -> int:
        return int(self.target_author == self.source_author)


def _episode_key(documents: Sequence[str]) -> str:
    digest = hashlib.sha256()
    digest.update(CACHE_SCHEMA.encode())
    digest.update(MODEL_ID.encode())
    digest.update(MODEL_REVISION.encode())
    digest.update(str(MAX_TOKENS).encode())
    for document in documents:
        encoded = document.encode("utf-8")
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)
    return digest.hexdigest()


class EmbeddingCache:
    """Content-addressed cache with model provenance embedded in every key."""

    def __init__(self, path: Path):
        self.path = path
        self.values: dict[str, np.ndarray] = {}
        if path.exists():
            with np.load(path, allow_pickle=False) as archive:
                metadata = json.loads(str(archive["metadata"].item()))
                if metadata.get("schema") != CACHE_SCHEMA:
                    raise ValueError("incompatible LUAR embedding cache schema")
                keys = archive["keys"].tolist()
                vectors = archive["vectors"]
                self.values = {
                    str(key): np.asarray(vector, dtype=np.float32)
                    for key, vector in zip(keys, vectors)
                }

    def get(self, documents: Sequence[str]) -> np.ndarray | None:
        return self.values.get(_episode_key(documents))

    def put(self, documents: Sequence[str], vector: np.ndarray) -> None:
        value = np.asarray(vector, dtype=np.float32)
        if value.shape != (512,) or not np.isfinite(value).all():
            raise ValueError(f"invalid LUAR embedding shape/value: {value.shape}")
        self.values[_episode_key(documents)] = value

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        keys = sorted(self.values)
        vectors = np.stack([self.values[key] for key in keys]) if keys else np.empty((0, 512))
        temporary = self.path.with_suffix(self.path.suffix + ".tmp.npz")
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
            keys=np.asarray(keys),
            vectors=vectors.astype(np.float32),
        )
        temporary.replace(self.path)


def _load_embedder(device: str | None = None) -> Callable[[Sequence[Sequence[str]]], np.ndarray]:
    try:
        import torch
        from transformers import AutoModel, AutoTokenizer
    except ImportError as exc:  # pragma: no cover - optional heavyweight path
        raise RuntimeError("LUAR validation requires torch and transformers") from exc

    selected = device or ("mps" if torch.backends.mps.is_available() else "cpu")
    tokenizer = AutoTokenizer.from_pretrained(MODEL_ID, revision=MODEL_REVISION)
    model = AutoModel.from_pretrained(
        MODEL_ID,
        revision=MODEL_REVISION,
        trust_remote_code=True,
    ).eval().to(selected)

    # The pinned LUAR implementation calls ``mask.type(token.type())``. Newer
    # PyTorch returns ``torch.mps.FloatTensor`` there, which ``Tensor.type`` no
    # longer accepts. Preserve the exact pooling math with device-safe ``to``.
    def compatible_mean_pooling(self, token_embeddings, attention_mask):
        expanded = attention_mask.unsqueeze(-1).expand_as(token_embeddings).to(
            dtype=token_embeddings.dtype
        )
        return (token_embeddings * expanded).sum(dim=1) / expanded.sum(dim=1).clamp(
            min=1e-9
        )

    model.mean_pooling = types.MethodType(compatible_mean_pooling, model)

    def embed(episodes: Sequence[Sequence[str]]) -> np.ndarray:
        if not episodes:
            return np.empty((0, 512), dtype=np.float32)
        episode_length = len(episodes[0])
        if episode_length < 1 or any(len(episode) != episode_length for episode in episodes):
            raise ValueError("each LUAR batch must have a constant positive episode length")
        flattened = [document for episode in episodes for document in episode]
        inputs = tokenizer(
            flattened,
            return_tensors="pt",
            padding=True,
            max_length=MAX_TOKENS,
            truncation=True,
        ).to(selected)
        for name in ("input_ids", "attention_mask"):
            inputs[name] = inputs[name].reshape(len(episodes), episode_length, -1)
        with torch.inference_mode():
            output = model(**inputs, document_batch_size=8)
        return output.detach().float().cpu().numpy()

    return embed


def embed_partitions(
    partitions: dict[str, Sequence[StyleAuthor]],
    *,
    cache: EmbeddingCache,
    embedder: Callable[[Sequence[Sequence[str]]], np.ndarray],
    batch_size: int = 8,
) -> dict[str, dict[str, object]]:
    """Embed baseline episodes and probes, incrementally persisting the cache."""

    needed: dict[str, tuple[str, ...]] = {}
    for authors in partitions.values():
        for author in authors:
            needed[_episode_key(author.baselines)] = author.baselines
            for baseline in author.baselines:
                episode = (baseline,)
                needed[_episode_key(episode)] = episode
            for probe in author.probes:
                episode = (probe,)
                needed[_episode_key(episode)] = episode

    missing_by_length: dict[int, list[tuple[str, ...]]] = defaultdict(list)
    for key, episode in needed.items():
        if key not in cache.values:
            missing_by_length[len(episode)].append(episode)
    for episode_length in sorted(missing_by_length):
        episodes = missing_by_length[episode_length]
        for start in range(0, len(episodes), batch_size):
            batch = episodes[start : start + batch_size]
            vectors = embedder(batch)
            if vectors.shape != (len(batch), 512):
                raise ValueError(f"embedder returned {vectors.shape}, expected {(len(batch), 512)}")
            for episode, vector in zip(batch, vectors):
                cache.put(episode, vector)
            cache.save()

    result = {}
    for partition, authors in partitions.items():
        result[partition] = {
            "baseline": np.stack([cache.get(author.baselines) for author in authors]),
            "baseline_documents": np.stack(
                [[cache.get((baseline,)) for baseline in author.baselines] for author in authors]
            ),
            "probes": np.stack(
                [[cache.get((probe,)) for probe in author.probes] for author in authors]
            ),
        }
    return result


@dataclass(frozen=True)
class PldaModel:
    mean: np.ndarray
    pca: PCA
    between_covariance: np.ndarray
    within_covariance: np.ndarray


def fit_lda_metric(embeddings: dict[str, object], *, dimensions: int = 64):
    baseline = np.asarray(embeddings["baseline_documents"], dtype=np.float64)
    probes = np.asarray(embeddings["probes"], dtype=np.float64)
    documents = np.concatenate((baseline, probes), axis=1)
    documents /= np.maximum(np.linalg.norm(documents, axis=2, keepdims=True), 1e-12)
    X = documents.reshape(-1, documents.shape[-1])
    y = np.repeat(np.arange(documents.shape[0]), documents.shape[1])
    model = LinearDiscriminantAnalysis(
        solver="eigen",
        shrinkage="auto",
        n_components=min(dimensions, documents.shape[0] - 1),
    )
    model.fit(X, y)
    return model


def lda_score_matrix(model, embeddings: dict[str, object]) -> np.ndarray:
    baseline = np.asarray(embeddings["baseline_documents"], dtype=np.float64)
    probes = np.asarray(embeddings["probes"], dtype=np.float64)
    baseline /= np.maximum(np.linalg.norm(baseline, axis=2, keepdims=True), 1e-12)
    probes /= np.maximum(np.linalg.norm(probes, axis=2, keepdims=True), 1e-12)
    baseline_projected = model.transform(baseline.reshape(-1, baseline.shape[-1])).reshape(
        baseline.shape[0], baseline.shape[1], -1
    )
    baseline_centroids = baseline_projected.mean(axis=1)
    probe_projected = model.transform(probes.reshape(-1, probes.shape[-1])).reshape(
        probes.shape[0], probes.shape[1], -1
    )
    baseline_centroids /= np.maximum(
        np.linalg.norm(baseline_centroids, axis=1, keepdims=True), 1e-12
    )
    probe_projected /= np.maximum(
        np.linalg.norm(probe_projected, axis=2, keepdims=True), 1e-12
    )
    return probe_projected @ baseline_centroids.T


def fit_plda(embeddings: dict[str, object], *, dimensions: int = 64) -> PldaModel:
    """Fit a regularized two-covariance model on development authors only."""

    baseline = np.asarray(embeddings["baseline_documents"], dtype=np.float64)
    probes = np.asarray(embeddings["probes"], dtype=np.float64)
    documents = np.concatenate((baseline, probes), axis=1)
    documents /= np.maximum(np.linalg.norm(documents, axis=2, keepdims=True), 1e-12)
    flat = documents.reshape(-1, documents.shape[-1])
    mean = flat.mean(axis=0)
    pca = PCA(n_components=min(dimensions, len(flat) - 1), random_state=SEED)
    projected = pca.fit_transform(flat - mean).reshape(documents.shape[0], documents.shape[1], -1)
    author_means = projected.mean(axis=1)
    residuals = (projected - author_means[:, None, :]).reshape(-1, projected.shape[-1])
    within = LedoitWolf().fit(residuals).covariance_
    observed_means = LedoitWolf().fit(author_means).covariance_
    latent_between = observed_means - within / documents.shape[1]
    eigenvalues, eigenvectors = np.linalg.eigh(latent_between)
    floor = max(1e-6, float(np.trace(observed_means)) / observed_means.shape[0] * 1e-4)
    between = (eigenvectors * np.maximum(eigenvalues, floor)) @ eigenvectors.T
    return PldaModel(mean, pca, between, within)


def plda_score_matrix(model: PldaModel, embeddings: dict[str, object]) -> np.ndarray:
    """Score every probe against every three-document baseline by log Bayes factor."""

    baseline = np.asarray(embeddings["baseline_documents"], dtype=np.float64)
    probes = np.asarray(embeddings["probes"], dtype=np.float64)
    baseline /= np.maximum(np.linalg.norm(baseline, axis=2, keepdims=True), 1e-12)
    probes /= np.maximum(np.linalg.norm(probes, axis=2, keepdims=True), 1e-12)
    baseline_projected = model.pca.transform(
        (baseline.reshape(-1, baseline.shape[-1]) - model.mean)
    ).reshape(baseline.shape[0], baseline.shape[1], -1).mean(axis=1)
    probe_projected = model.pca.transform(
        (probes.reshape(-1, probes.shape[-1]) - model.mean)
    ).reshape(probes.shape[0], probes.shape[1], -1)

    baseline_covariance = model.between_covariance + model.within_covariance / baseline.shape[1]
    probe_covariance = model.between_covariance + model.within_covariance
    joint = np.block(
        [
            [baseline_covariance, model.between_covariance],
            [model.between_covariance, probe_covariance],
        ]
    )
    inverse_joint = np.linalg.inv(joint)
    inverse_baseline = np.linalg.inv(baseline_covariance)
    inverse_probe = np.linalg.inv(probe_covariance)
    sign_joint, logdet_joint = np.linalg.slogdet(joint)
    sign_baseline, logdet_baseline = np.linalg.slogdet(baseline_covariance)
    sign_probe, logdet_probe = np.linalg.slogdet(probe_covariance)
    if min(sign_joint, sign_baseline, sign_probe) <= 0:
        raise ValueError("PLDA covariance is not positive definite")

    scores = np.empty((probes.shape[0], probes.shape[1], baseline.shape[0]))
    for source in range(probes.shape[0]):
        for probe_index in range(probes.shape[1]):
            probe = probe_projected[source, probe_index]
            for target, claimed in enumerate(baseline_projected):
                stacked = np.concatenate((claimed, probe))
                same_quadratic = float(stacked @ inverse_joint @ stacked)
                different_quadratic = float(
                    claimed @ inverse_baseline @ claimed + probe @ inverse_probe @ probe
                )
                scores[source, probe_index, target] = -0.5 * (
                    same_quadratic
                    - different_quadratic
                    + logdet_joint
                    - logdet_baseline
                    - logdet_probe
                )
    return scores


def score_partition(
    authors: Sequence[StyleAuthor],
    embeddings: dict[str, object],
    plda_model: PldaModel | None = None,
    lda_model=None,
) -> list[LuarTrial]:
    baseline = np.asarray(embeddings["baseline"], dtype=np.float64)
    baseline_documents = np.asarray(embeddings["baseline_documents"], dtype=np.float64)
    probes = np.asarray(embeddings["probes"], dtype=np.float64)
    baseline /= np.maximum(np.linalg.norm(baseline, axis=1, keepdims=True), 1e-12)
    baseline_documents /= np.maximum(
        np.linalg.norm(baseline_documents, axis=2, keepdims=True), 1e-12
    )
    probes /= np.maximum(np.linalg.norm(probes, axis=2, keepdims=True), 1e-12)
    scores = probes @ baseline.T
    document_scores = np.einsum("spd,tbd->sptb", probes, baseline_documents)
    cohesion = baseline_documents @ np.swapaxes(baseline_documents, 1, 2)
    upper = np.triu_indices(baseline_documents.shape[1], k=1)
    cohesion_pairs = cohesion[:, upper[0], upper[1]]
    plda_scores = (
        plda_score_matrix(plda_model, embeddings)
        if plda_model is not None
        else np.zeros_like(scores)
    )
    lda_scores = (
        lda_score_matrix(lda_model, embeddings) if lda_model is not None else np.zeros_like(scores)
    )
    trials = []
    for s, source in enumerate(authors):
        for probe_index in range(probes.shape[1]):
            for t, target in enumerate(authors):
                per_document = document_scores[s, probe_index, t]
                trials.append(
                    LuarTrial(
                        target.author_id,
                        source.author_id,
                        probe_index,
                        float(scores[s, probe_index, t]),
                        float(per_document.mean()),
                        float(per_document.min()),
                        float(per_document.std()),
                        float(cohesion_pairs[t].mean()),
                        float(cohesion_pairs[t].min()),
                        float(plda_scores[s, probe_index, t]),
                        float(lda_scores[s, probe_index, t]),
                    )
                )
    return trials


def matched_trials(trials: Sequence[LuarTrial]) -> list[LuarTrial]:
    authors = sorted({trial.target_author for trial in trials})
    by_key = {(t.target_author, t.source_author, t.probe_index): t for t in trials}
    matched = []
    for index, target in enumerate(authors):
        impostor = authors[(index + 1) % len(authors)]
        probes = sorted(t.probe_index for t in trials if t.target_author == t.source_author == target)
        for probe in probes:
            matched.extend((by_key[(target, target, probe)], by_key[(target, impostor, probe)]))
    return matched


def signal_matrix(trials: Sequence[LuarTrial]) -> np.ndarray:
    raw = np.asarray([trial.cosine_similarity for trial in trials], dtype=np.float64)
    zscore = np.zeros_like(raw)
    margin = np.zeros_like(raw)
    grouped: dict[tuple[str, int], list[int]] = defaultdict(list)
    for index, trial in enumerate(trials):
        grouped[(trial.source_author, trial.probe_index)].append(index)
    for indices in grouped.values():
        block = raw[indices]
        for local, global_index in enumerate(indices):
            peers = np.delete(block, local)
            zscore[global_index] = (raw[global_index] - peers.mean()) / max(peers.std(), 1e-9)
            margin[global_index] = raw[global_index] - peers.max()
    consistency = np.asarray(
        [
            [
                trial.baseline_mean_similarity,
                trial.baseline_min_similarity,
                trial.baseline_similarity_std,
                trial.baseline_cohesion_mean,
                trial.baseline_cohesion_min,
                trial.baseline_mean_similarity - trial.baseline_cohesion_mean,
            ]
            for trial in trials
        ],
        dtype=np.float64,
    )
    plda = np.asarray([trial.plda_log_likelihood_ratio for trial in trials], dtype=np.float64)
    lda = np.asarray([trial.lda_similarity for trial in trials], dtype=np.float64)
    lda_margin = np.zeros_like(lda)
    for indices in grouped.values():
        block = lda[indices]
        for local, global_index in enumerate(indices):
            lda_margin[global_index] = lda[global_index] - np.delete(block, local).max()
    return np.column_stack((raw, zscore, margin, consistency, plda, lda, lda_margin))


def _labels(trials: Sequence[LuarTrial]) -> np.ndarray:
    return np.asarray([trial.label for trial in trials], dtype=np.int8)


def _summary(labels: np.ndarray, probability: np.ndarray) -> dict:
    return {
        "auc": round(float(roc_auc_score(labels, probability)), 6),
        "brier": round(float(brier(labels, probability)), 6),
        "cllr": round(float(cllr(labels, probability)), 6),
        "tpr_at_fpr": {
            str(value): round(float(tpr_at_fpr(labels, probability, value)), 6)
            for value in (0.01, 0.05, 0.10)
        },
    }


def build_calibrator(*, interactions: bool = False) -> Pipeline:
    steps = [("scale", StandardScaler())]
    if interactions:
        steps.extend(
            [
                (
                    "interactions",
                    PolynomialFeatures(degree=2, interaction_only=True, include_bias=False),
                ),
                ("interaction_scale", StandardScaler()),
            ]
        )
    steps.append(
        (
            "logistic",
            LogisticRegression(
                C=0.05 if interactions else 0.5,
                class_weight="balanced",
                max_iter=3000,
                random_state=SEED,
            ),
        )
    )
    return Pipeline(steps)


def fit_stratified_thresholds(
    labels: np.ndarray,
    scores: np.ndarray,
    reliability: np.ndarray,
    *,
    strata: int = 3,
    max_fpr: float = 0.01,
    target_precision: float = 0.90,
) -> dict:
    """Allocate a global false-positive budget across baseline-reliability strata."""

    labels = np.asarray(labels, dtype=np.int8)
    scores = np.asarray(scores, dtype=np.float64)
    reliability = np.asarray(reliability, dtype=np.float64)
    cutpoints = np.quantile(reliability, np.arange(1, strata) / strata).tolist()
    assignments = np.digitize(reliability, cutpoints, right=True)
    total_negatives = int(np.sum(labels == 0))
    false_positive_budget = int(math.floor(max_fpr * total_negatives))
    choices = []
    for stratum in range(strata):
        mask = assignments == stratum
        negatives = np.sort(scores[mask & (labels == 0)])[::-1]
        if not len(negatives):
            raise ValueError("each uncertainty stratum needs negative calibration support")
        options = []
        for allowed in range(false_positive_budget + 1):
            threshold = (
                float(np.nextafter(negatives[0], np.inf))
                if allowed == 0
                else float(negatives[min(allowed - 1, len(negatives) - 1)])
            )
            selected = mask & (scores >= threshold)
            options.append(
                {
                    "threshold": threshold,
                    "tp": int(np.sum(selected & (labels == 1))),
                    "fp": int(np.sum(selected & (labels == 0))),
                }
            )
        choices.append(options)
    feasible = []
    for combination in itertools.product(*choices):
        tp = sum(option["tp"] for option in combination)
        fp = sum(option["fp"] for option in combination)
        if fp > false_positive_budget or tp < 10:
            continue
        if tp / (tp + fp) < target_precision:
            continue
        feasible.append((tp, -fp, combination))
    if not feasible:
        raise ValueError("no stratified thresholds satisfy calibration constraints")
    _, _, selected = max(feasible, key=lambda row: (row[0], row[1]))
    return {
        "cutpoints": cutpoints,
        "thresholds": [option["threshold"] for option in selected],
        "calibration_true_positive": sum(option["tp"] for option in selected),
        "calibration_false_positive": sum(option["fp"] for option in selected),
    }


def apply_stratified_thresholds(
    scores: np.ndarray, reliability: np.ndarray, rule: dict
) -> np.ndarray:
    assignments = np.digitize(reliability, rule["cutpoints"], right=True)
    thresholds = np.asarray(rule["thresholds"], dtype=np.float64)
    return np.asarray(scores) >= thresholds[assignments]


def operating_from_selection(labels: np.ndarray, selected: np.ndarray) -> dict:
    labels = np.asarray(labels, dtype=np.int8)
    selected = np.asarray(selected, dtype=bool)
    positives = labels == 1
    negatives = ~positives
    tp = int(np.sum(selected & positives))
    fp = int(np.sum(selected & negatives))
    return {
        "tpr": tp / int(positives.sum()),
        "fpr": fp / int(negatives.sum()),
        "precision": tp / (tp + fp) if tp + fp else None,
        "selected": int(selected.sum()),
        "true_positive": tp,
        "false_positive": fp,
        "n_genuine": int(positives.sum()),
        "n_impostor": int(negatives.sum()),
    }


def run_experiment(
    *,
    cache_dir: Path = DEFAULT_CACHE,
    embedding_cache_path: Path = Path(".benchmark_cache/luar/pan_luar_embeddings.npz"),
    output_path: Path | None = None,
    locked_cache_dir: Path | None = None,
    locked_supplement_cache_dir: Path | None = None,
    local_threshold_cache_dir: Path | None = None,
    external_manifest_path: Path | None = None,
    external_domain_refit: bool = False,
    calibration_false_positive_budget: int | None = None,
    embedder: Callable[[Sequence[Sequence[str]]], np.ndarray] | None = None,
    n_development: int = 120,
    n_calibration: int = 100,
    n_locked: int = 100,
    prior_locked_authors: int = 12,
    post_calibration_excluded_authors: int = 120,
) -> dict:
    if calibration_false_positive_budget is not None and calibration_false_positive_budget < 0:
        raise ValueError("calibration false-positive budget must be non-negative")
    if locked_cache_dir is None and external_manifest_path is None:
        partitions = load_author_partitions(
            cache_dir=cache_dir,
            n_development=n_development,
            n_calibration=n_calibration,
            n_locked=n_locked,
            prior_locked_authors=prior_locked_authors,
            post_calibration_excluded_authors=post_calibration_excluded_authors,
        )
        lock_source = "PAN 2020 test, held after development/calibration/exclusions"
    else:
        fitting = load_author_partitions(
            cache_dir=cache_dir,
            n_development=n_development,
            n_calibration=n_calibration,
            n_locked=0,
            prior_locked_authors=prior_locked_authors,
            post_calibration_excluded_authors=0,
        )
        if external_manifest_path is not None:
            if locked_cache_dir is not None or locked_supplement_cache_dir is not None:
                raise ValueError("external manifest cannot be combined with PAN lock sources")
            from validation.verify.gutenberg_corpus import load_authors

            external_authors = load_authors(external_manifest_path)
            required_authors = 3 * n_locked if external_domain_refit else n_locked
            if len(external_authors) < required_authors:
                raise ValueError("external manifest lacks requested locked authors")
            locked_authors = list(external_authors[-n_locked:])
        else:
            primary_locked_authors = n_locked - (1 if locked_supplement_cache_dir else 0)
            external = load_author_partitions(
                cache_dir=locked_cache_dir,
                n_development=0,
                n_calibration=0,
                n_locked=primary_locked_authors,
                prior_locked_authors=0,
                post_calibration_excluded_authors=0,
                probe_samples=1,
            )
            locked_authors = list(external["locked"])
        if locked_supplement_cache_dir is not None:
            supplement = load_author_partitions(
                cache_dir=locked_supplement_cache_dir,
                n_development=0,
                n_calibration=0,
                n_locked=1,
                prior_locked_authors=452,
                post_calibration_excluded_authors=0,
            )
            supplemental_author = supplement["locked"][0]
            locked_authors.append(
                StyleAuthor(
                    author_id=supplemental_author.author_id,
                    baseline_fandom=supplemental_author.baseline_fandom,
                    probe_fandom=supplemental_author.probe_fandom,
                    baselines=supplemental_author.baselines,
                    probes=(supplemental_author.probes[0],),
                )
            )
        partitions = {
            "development": fitting["development"],
            "calibration": fitting["calibration"],
            "locked": locked_authors,
        }
        if external_manifest_path is not None and external_domain_refit:
            local_fit = n_locked // 2
            partitions["development"] = list(external_authors[:local_fit])
            partitions["calibration"] = list(external_authors[local_fit:n_locked])
        elif external_manifest_path is not None and len(external_authors) >= 2 * n_locked:
            partitions["local_threshold"] = list(external_authors[-2 * n_locked : -n_locked])
        elif local_threshold_cache_dir is not None:
            local_threshold = load_author_partitions(
                cache_dir=local_threshold_cache_dir,
                n_development=0,
                n_calibration=0,
                n_locked=43,
                prior_locked_authors=453,
                post_calibration_excluded_authors=0,
            )
            partitions["local_threshold"] = local_threshold["locked"]
        fitting_ids = {
            author.author_id
            for name in ("development", "calibration")
            for author in partitions[name]
        }
        external_ids = {
            author.author_id
            for name in ("locked", "local_threshold")
            if name in partitions
            for author in partitions[name]
        }
        overlap = fitting_ids & external_ids
        if overlap:
            raise ValueError(f"external lock overlaps fitting authors: {sorted(overlap)}")
        lock_source = (
            "Project Gutenberg: final untouched 100-author block after local 50/50 fit/calibration and two viewed 100-author exclusions"
            if external_manifest_path is not None and external_domain_refit
            else "Project Gutenberg: second 100-author block, three baseline and three probe works"
            if external_manifest_path is not None
            else "PAN 2021 open-set test: unseen PAN 2020 authors and topics"
        )
    cache = EmbeddingCache(embedding_cache_path)
    embedded = embed_partitions(
        partitions, cache=cache, embedder=embedder or _load_embedder()
    )
    plda_model = fit_plda(embedded["development"])
    lda_model = fit_lda_metric(embedded["development"])
    exhaustive = {
        name: score_partition(partitions[name], embedded[name], plda_model, lda_model)
        for name in partitions
    }
    style_vectorizer, style_scaler = _fit_representations(partitions["development"])
    style_exhaustive = {
        name: _score_partition(partitions[name], style_vectorizer, style_scaler)
        for name in partitions
    }
    evaluated = {name: matched_trials(rows) for name, rows in exhaustive.items()}
    matrices = {
        name: np.column_stack(
            (signal_matrix(rows), style_margin_only_signals(style_exhaustive[name]))
        )
        for name, rows in exhaustive.items()
    }
    positions = {
        name: {trial: index for index, trial in enumerate(rows)}
        for name, rows in exhaustive.items()
    }

    # Variants are fixed before locked evaluation. Selection uses calibration
    # recall subject to the product precision/FPR constraints, then only that
    # selected variant is applied to the lock.
    variants = {
        "cosine": (0,),
        "peer_relative": (0, 1, 2),
        "margin": (2,),
        "baseline_consistency": (0, 3, 4, 5, 6, 7, 8),
        "plda": (9,),
        "lda": (10, 11),
        "cosine_style_margin": (0, 12, 13),
        "peer_relative_style_margin": (0, 1, 2, 12, 13),
        "consistency_style_margin": (0, 3, 4, 5, 6, 7, 8, 12, 13),
        "plda_style_margin": (9, 12, 13),
        "plda_consistency_style_margin": (0, 3, 4, 5, 6, 7, 8, 9, 12, 13),
        "lda_style_margin": (10, 11, 12, 13),
        "lda_consistency_style_margin": (0, 3, 4, 5, 6, 7, 8, 10, 11, 12, 13),
        "cross_channel_interactions": tuple(range(14)),
    }
    candidates = {}
    fitted = {}
    for name, columns in variants.items():
        model = build_calibrator(interactions=name == "cross_channel_interactions")
        model.fit(matrices["development"][:, columns], _labels(exhaustive["development"]))
        cal_indices = [positions["calibration"][t] for t in evaluated["calibration"]]
        cal_probability = model.predict_proba(matrices["calibration"][cal_indices][:, columns])[:, 1]
        labels = _labels(evaluated["calibration"])
        calibration_max_fpr = (
            calibration_false_positive_budget / int(np.sum(labels == 0))
            if calibration_false_positive_budget is not None
            else 0.01
        )
        threshold = _threshold_at_constraints(
            labels, cal_probability, max_fpr=calibration_max_fpr
        )
        operating = _operating_result(labels, cal_probability, threshold)
        candidates[name] = {
            "columns": list(columns),
            "metrics": _summary(labels, cal_probability),
            "threshold": threshold,
            "operating_point": operating,
        }
        fitted[name] = model

    eligible = [
        name
        for name, row in candidates.items()
        if row["operating_point"]["precision"] is not None
        and row["operating_point"]["precision"] >= 0.90
        and row["operating_point"]["fpr"] <= 0.01
    ]
    selected = max(
        eligible or list(candidates),
        key=lambda name: (
            candidates[name]["operating_point"]["tpr"],
            candidates[name]["metrics"]["auc"],
            name,
        ),
    )
    model = fitted[selected]
    columns = tuple(candidates[selected]["columns"])
    threshold = candidates[selected]["threshold"]

    probabilities = {}
    metrics = {}
    operating = {}
    for name in ("development", "calibration", "locked"):
        rows = evaluated[name]
        indices = [positions[name][trial] for trial in rows]
        probability = model.predict_proba(matrices[name][indices][:, columns])[:, 1]
        labels = _labels(rows)
        probabilities[name] = probability
        metrics[name] = {**_summary(labels, probability), "n_trials": len(rows)}
        operating[name] = _operating_result(labels, probability, threshold)

    calibration_indices = [positions["calibration"][trial] for trial in evaluated["calibration"]]
    locked_indices = [positions["locked"][trial] for trial in evaluated["locked"]]
    # Column 6 is baseline-pair cohesion mean: a label-free reliability signal
    # repeated for every claim against the same authenticated baseline.
    stratified_rule = fit_stratified_thresholds(
        _labels(evaluated["calibration"]),
        probabilities["calibration"],
        matrices["calibration"][calibration_indices, 6],
    )
    stratified_calibration = operating_from_selection(
        _labels(evaluated["calibration"]),
        apply_stratified_thresholds(
            probabilities["calibration"],
            matrices["calibration"][calibration_indices, 6],
            stratified_rule,
        ),
    )
    stratified_locked = operating_from_selection(
        _labels(evaluated["locked"]),
        apply_stratified_thresholds(
            probabilities["locked"],
            matrices["locked"][locked_indices, 6],
            stratified_rule,
        ),
    )
    use_stratified = (
        calibration_false_positive_budget is None
        and stratified_calibration["tpr"] > operating["calibration"]["tpr"]
    )

    calibration_labels = _labels(evaluated["calibration"])
    locked_labels = _labels(evaluated["locked"])
    fpr_sensitivity = {}
    for false_positive_budget in range(4):
        target_fpr = false_positive_budget / int(np.sum(calibration_labels == 0))
        sensitivity_threshold = _threshold_at_constraints(
            calibration_labels,
            probabilities["calibration"],
            max_fpr=target_fpr,
        )
        key = f"{false_positive_budget}_of_{int(np.sum(calibration_labels == 0))}"
        fpr_sensitivity[key] = {
            "calibration_max_fpr": target_fpr,
            "threshold": sensitivity_threshold,
            "calibration": _operating_result(
                calibration_labels, probabilities["calibration"], sensitivity_threshold
            ),
            "locked": _operating_result(
                locked_labels, probabilities["locked"], sensitivity_threshold
            ),
        }

    local_threshold_result = None
    if "local_threshold" in partitions:
        local_rows = matched_trials(exhaustive["local_threshold"])
        local_indices = [positions["local_threshold"][trial] for trial in local_rows]
        local_probability = model.predict_proba(
            matrices["local_threshold"][local_indices][:, columns]
        )[:, 1]
        local_labels = _labels(local_rows)
        local_threshold_value = _threshold_at_constraints(
            local_labels, local_probability, max_fpr=0.01
        )
        local_threshold_result = {
            "authors": len(partitions["local_threshold"]),
            "threshold": local_threshold_value,
            "calibration": _operating_result(
                local_labels, local_probability, local_threshold_value
            ),
            "locked": _operating_result(
                locked_labels, probabilities["locked"], local_threshold_value
            ),
            "author_overlap_with_lock": len(
                {author.author_id for author in partitions["local_threshold"]}
                & {author.author_id for author in partitions["locked"]}
            ),
        }

    strict = (
        local_threshold_result["locked"]
        if local_threshold_result is not None
        else stratified_locked
        if use_stratified
        else operating["locked"]
    )
    conditions = {
        "locked_precision_at_least_0_90": strict["precision"] is not None
        and strict["precision"] >= 0.90,
        "locked_recall_at_least_0_50": strict["tpr"] >= 0.50,
        "locked_fpr_at_most_0_01": strict["fpr"] <= 0.01,
        "at_least_100_locked_authors": n_locked >= 100,
        "at_least_3_authenticated_baselines": all(
            len(author.baselines) >= 3 for author in partitions["locked"]
        ),
    }
    result = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": {"zenodo_doi": ZENODO_DOI, "zenodo_record": ZENODO_RECORD},
        "model": {
            "id": MODEL_ID,
            "revision": MODEL_REVISION,
            "license": "Apache-2.0",
            "max_tokens": MAX_TOKENS,
            "embedding_cache": str(embedding_cache_path),
            "signal_order": [
                "luar_cosine",
                "luar_peer_z",
                "luar_claimed_minus_best_peer",
                "luar_probe_to_baselines_mean",
                "luar_probe_to_baselines_min",
                "luar_probe_to_baselines_std",
                "luar_baseline_pair_cohesion_mean",
                "luar_baseline_pair_cohesion_min",
                "luar_probe_mean_minus_baseline_cohesion_mean",
                "luar_plda_log_likelihood_ratio",
                "luar_lda_similarity",
                "luar_lda_claimed_minus_best_peer",
                "character_claimed_minus_best_peer",
                "content_reduced_claimed_minus_best_peer",
            ],
        },
        "protocol": {
            "partition_sizes": {name: len(rows) for name, rows in partitions.items()},
            "partition_authors": {
                name: [author.author_id for author in rows] for name, rows in partitions.items()
            },
            "prior_locked_authors_excluded": prior_locked_authors,
            "post_calibration_excluded_authors": post_calibration_excluded_authors,
            "baseline_documents": 3,
            "probe_documents_per_locked_author": sorted(
                {len(author.probes) for author in partitions["locked"]}
            ),
            "evaluation": "binary source-matched: one deterministic impostor per genuine",
            "selection": "variant and threshold selected on calibration authors only",
            "lock_source": lock_source,
            "locked_cache_dir": str(locked_cache_dir) if locked_cache_dir else None,
            "locked_supplement_cache_dir": (
                str(locked_supplement_cache_dir) if locked_supplement_cache_dir else None
            ),
            "local_threshold_cache_dir": (
                str(local_threshold_cache_dir) if local_threshold_cache_dir else None
            ),
            "external_manifest_path": (
                str(external_manifest_path) if external_manifest_path else None
            ),
            "external_domain_refit": external_domain_refit,
            "calibration_false_positive_budget": calibration_false_positive_budget,
            "external_lock_archive": PAN21_ARCHIVE if locked_cache_dir else None,
            "external_lock_archive_md5": PAN21_ARCHIVE_MD5 if locked_cache_dir else None,
        },
        "candidate_calibration_results": candidates,
        "selected_variant": selected,
        "metrics": metrics,
        "operating_points": operating,
        "uncertainty_stratified_operating_rule": {
            "selected": use_stratified,
            "reliability_signal": "luar_baseline_pair_cohesion_mean",
            "rule": stratified_rule,
            "calibration": stratified_calibration,
            "locked": stratified_locked,
        },
        "calibration_fpr_sensitivity": fpr_sensitivity,
        "local_threshold_operating_rule": local_threshold_result,
        "promotion_gate": {
            "passed": all(conditions.values()),
            "conditions": conditions,
            "decision": "eligible_for_report_only_review"
            if all(conditions.values())
            else "validation_only",
        },
    }
    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE)
    parser.add_argument(
        "--embedding-cache", type=Path, default=Path(".benchmark_cache/luar/pan_luar_embeddings.npz")
    )
    parser.add_argument(
        "--locked-cache-dir",
        type=Path,
        help="Optional external author pool used only as the locked partition",
    )
    parser.add_argument(
        "--locked-supplement-cache-dir",
        type=Path,
        help="Optional source for one additional untouched locked author",
    )
    parser.add_argument(
        "--local-threshold-cache-dir",
        type=Path,
        help="Optional author-disjoint local cohort used only to refit the threshold",
    )
    parser.add_argument(
        "--external-manifest",
        type=Path,
        help="Optional 200-author Gutenberg manifest: first 100 calibrate threshold, last 100 lock",
    )
    parser.add_argument(
        "--external-domain-refit",
        action="store_true",
        help="Fit/select on the first 50/50 manifest authors, exclude the viewed middle 100, and lock the final 100",
    )
    parser.add_argument(
        "--calibration-fp-budget",
        type=int,
        help="Optional pre-registered absolute false-positive budget for variant thresholds",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("validation/verify/pan_auth_luar_matched_cal100_lock100.json"),
    )
    args = parser.parse_args()
    result = run_experiment(
        cache_dir=args.cache_dir,
        embedding_cache_path=args.embedding_cache,
        output_path=args.output,
        locked_cache_dir=args.locked_cache_dir,
        locked_supplement_cache_dir=args.locked_supplement_cache_dir,
        local_threshold_cache_dir=args.local_threshold_cache_dir,
        external_manifest_path=args.external_manifest,
        external_domain_refit=args.external_domain_refit,
        calibration_false_positive_budget=args.calibration_fp_budget,
    )
    print(json.dumps({"selected": result["selected_variant"], "gate": result["promotion_gate"]}, indent=2))


if __name__ == "__main__":
    main()
