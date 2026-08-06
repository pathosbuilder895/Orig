"""Author-disjoint PAN style experts for modern cross-topic verification.

This module is validation-only.  It fits representation/calibration on
development authors, selects operating points on separate calibration authors,
and evaluates once on the 12 locked authors used by ``pan_corpus.py``.
"""

from __future__ import annotations

import json
import math
import re
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

import numpy as np
from scipy.sparse import csr_matrix, vstack
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from original.style_authorship import FUNCTION_WORDS, content_reduced_signature
from validation.stacked.fusion import cllr
from validation.verify.binary_auc import auc, brier, tpr_at_fpr
from validation.verify.pan_corpus import (
    DEFAULT_CACHE,
    ZENODO_DOI,
    ZENODO_RECORD,
    _digest,
    _discover,
    _fixed_window,
    _load_histories,
    _stable_order,
)


SEED = 1729


@dataclass(frozen=True)
class StyleAuthor:
    author_id: str
    baseline_fandom: str
    probe_fandom: str
    baselines: tuple[str, ...]
    probes: tuple[str, ...]


@dataclass(frozen=True)
class TrialScores:
    target_author: str
    source_author: str
    probe_index: int
    char_similarity: float
    content_reduced_similarity: float
    function_sequence_similarity: float = 0.0

    @property
    def label(self) -> int:
        return int(self.target_author == self.source_author)


def _eligible_authors(
    cache_dir: Path,
    *,
    min_text_chars: int,
    baseline_samples: int,
    probe_samples: int,
) -> list[tuple[str, dict]]:
    pairs, truth = _discover(cache_dir)
    histories = _load_histories(pairs, truth, min_text_chars)
    eligible = {}
    for author, documents in histories.items():
        by_fandom = defaultdict(list)
        for document in documents:
            by_fandom[document.fandom].append(document)
        usable = {name: docs for name, docs in by_fandom.items() if len(docs) >= probe_samples}
        if any(
            len(fandom_docs) >= baseline_samples
            and any(other != name for other in usable)
            for name, fandom_docs in usable.items()
        ):
            eligible[author] = usable
    return [(author, eligible[author]) for author in _stable_order(eligible, f"pan20-authors:{ZENODO_RECORD}")]


def load_author_partitions(
    *,
    cache_dir: Path = DEFAULT_CACHE,
    n_development: int = 120,
    n_calibration: int = 40,
    n_locked: int = 12,
    samples: int = 3,
    probe_samples: int | None = None,
    max_words: int = 2500,
    min_text_chars: int = 800,
    prior_locked_authors: int = 0,
    post_calibration_excluded_authors: int = 0,
) -> dict[str, list[StyleAuthor]]:
    """Recover deterministic authors; locked authors are selected first.

    Selecting locked first preserves the exact twelve-author set already used
    by ``validation/pan20_cross_fandom/manifest.json``. Development and
    calibration authors are subsequent, disjoint entries in the same stable
    SHA-256 ordering.
    """
    probe_samples = samples if probe_samples is None else probe_samples
    if samples < 1 or probe_samples < 1:
        raise ValueError("baseline and probe sample counts must be positive")
    ordered = _eligible_authors(
        cache_dir,
        min_text_chars=min_text_chars,
        baseline_samples=samples,
        probe_samples=probe_samples,
    )
    required = (
        prior_locked_authors
        + n_locked
        + n_development
        + n_calibration
        + post_calibration_excluded_authors
    )
    if len(ordered) < required:
        raise RuntimeError(f"need {required} eligible authors; found {len(ordered)}")

    def convert(rows: Sequence[tuple[str, dict]]) -> list[StyleAuthor]:
        result = []
        for raw_author, by_fandom in rows:
            fandoms = _stable_order(by_fandom, f"pan20-fandoms:{raw_author}")
            pairs = [
                (baseline_fandom, probe_fandom)
                for baseline_fandom in fandoms
                for probe_fandom in fandoms
                if baseline_fandom != probe_fandom
                and len(by_fandom[baseline_fandom]) >= samples
                and len(by_fandom[probe_fandom]) >= probe_samples
            ]
            baseline_fandom, probe_fandom = pairs[0]
            baseline_docs = sorted(by_fandom[baseline_fandom], key=lambda d: d.text_sha256)[:samples]
            probe_docs = sorted(by_fandom[probe_fandom], key=lambda d: d.text_sha256)[
                :probe_samples
            ]
            result.append(
                StyleAuthor(
                    author_id=f"pan20_{_digest(f'{ZENODO_RECORD}:{raw_author}')[:12]}",
                    baseline_fandom=baseline_fandom,
                    probe_fandom=probe_fandom,
                    baselines=tuple(_fixed_window(d.text, max_words, d.text_sha256) for d in baseline_docs),
                    probes=tuple(_fixed_window(d.text, max_words, d.text_sha256) for d in probe_docs),
                )
            )
        return result

    if prior_locked_authors:
        # Preserve the original lock at the head of the stable ordering, then
        # reuse the exact same development/calibration authors and take a
        # genuinely untouched lock after both fitting partitions.
        development_start = prior_locked_authors
        development_rows = ordered[development_start : development_start + n_development]
        calibration_start = development_start + n_development
        calibration_rows = ordered[calibration_start : calibration_start + n_calibration]
        locked_start = calibration_start + n_calibration + post_calibration_excluded_authors
        locked_rows = ordered[locked_start : locked_start + n_locked]
    else:
        locked_rows = ordered[:n_locked]
        development_rows = ordered[n_locked : n_locked + n_development]
        calibration_rows = ordered[n_locked + n_development : required]
    partitions = {
        "development": convert(development_rows),
        "calibration": convert(calibration_rows),
        "locked": convert(locked_rows),
    }
    assert_partition_integrity(partitions)
    return partitions


def assert_partition_integrity(partitions: dict[str, Sequence[StyleAuthor]]) -> None:
    seen = set()
    for partition_name, authors in partitions.items():
        ids = {author.author_id for author in authors}
        if len(ids) != len(authors):
            raise ValueError(f"duplicate author inside {partition_name}")
        overlap = seen & ids
        if overlap:
            raise ValueError(f"author leakage into {partition_name}: {sorted(overlap)}")
        seen |= ids
        for author in authors:
            if author.baseline_fandom == author.probe_fandom:
                raise ValueError(f"topic leakage for {author.author_id}")


def _fit_representations(
    development: Sequence[StyleAuthor], *, char_max_features: int = 30_000
):
    baseline_texts = [text for author in development for text in author.baselines]
    char_vectorizer = TfidfVectorizer(
        analyzer="char",
        ngram_range=(3, 5),
        min_df=2,
        max_features=char_max_features,
        sublinear_tf=True,
        norm="l2",
        dtype=np.float32,
    )
    char_vectorizer.fit(baseline_texts)
    scaler = StandardScaler()
    scaler.fit(np.stack([content_reduced_signature(text) for text in baseline_texts]))
    return char_vectorizer, scaler


def content_masked_sequence(text: str) -> str:
    """Remove topics while retaining function words, punctuation, and word shapes."""

    tokens = re.findall(r"[A-Za-z]+(?:'[A-Za-z]+)?|[^\w\s]", text)
    function_words = set(FUNCTION_WORDS)
    return " ".join(
        token.lower()
        if token.lower() in function_words or not token[:1].isalpha()
        else f"W{min(len(token), 12)}"
        for token in tokens
    )


def _fit_function_sequence(development: Sequence[StyleAuthor]) -> TfidfVectorizer:
    vectorizer = TfidfVectorizer(
        analyzer="word",
        ngram_range=(1, 4),
        min_df=2,
        max_features=30_000,
        sublinear_tf=True,
        norm="l2",
        dtype=np.float32,
    )
    vectorizer.fit(
        [content_masked_sequence(text) for author in development for text in author.baselines]
    )
    return vectorizer


def _score_partition(
    authors: Sequence[StyleAuthor],
    char_vectorizer: TfidfVectorizer,
    scaler: StandardScaler,
    function_vectorizer: TfidfVectorizer | None = None,
) -> list[TrialScores]:
    baseline_texts = [text for author in authors for text in author.baselines]
    probe_texts = [text for author in authors for text in author.probes]
    baseline_char = char_vectorizer.transform(baseline_texts)
    probe_char = char_vectorizer.transform(probe_texts)
    baseline_style = scaler.transform(np.stack([content_reduced_signature(t) for t in baseline_texts]))
    probe_style = scaler.transform(np.stack([content_reduced_signature(t) for t in probe_texts]))

    n_baselines = len(authors[0].baselines)
    n_probes = len(authors[0].probes)
    char_centroids = []
    style_centroids = []
    for index in range(len(authors)):
        b_slice = slice(index * n_baselines, (index + 1) * n_baselines)
        char_centroid = csr_matrix(baseline_char[b_slice].mean(axis=0))
        norm = math.sqrt(float(char_centroid.multiply(char_centroid).sum()))
        char_centroids.append(char_centroid / max(norm, 1e-12))
        style_centroids.append(np.mean(baseline_style[b_slice], axis=0))
    char_centroid_matrix = vstack(char_centroids)
    style_centroid_matrix = np.stack(style_centroids)

    char_scores = (probe_char @ char_centroid_matrix.T).toarray()
    # Negative Burrows Delta: larger values mean more stylistically similar.
    style_scores = -np.mean(
        np.abs(probe_style[:, None, :] - style_centroid_matrix[None, :, :]), axis=2
    )
    if function_vectorizer is not None:
        baseline_function = function_vectorizer.transform(
            [content_masked_sequence(text) for text in baseline_texts]
        )
        probe_function = function_vectorizer.transform(
            [content_masked_sequence(text) for text in probe_texts]
        )
        function_centroids = []
        for index in range(len(authors)):
            b_slice = slice(index * n_baselines, (index + 1) * n_baselines)
            centroid = csr_matrix(baseline_function[b_slice].mean(axis=0))
            norm = math.sqrt(float(centroid.multiply(centroid).sum()))
            function_centroids.append(centroid / max(norm, 1e-12))
        function_scores = (probe_function @ vstack(function_centroids).T).toarray()
    else:
        function_scores = np.zeros_like(char_scores)
    trials = []
    for source_index, source in enumerate(authors):
        for probe_offset in range(n_probes):
            probe_index = source_index * n_probes + probe_offset
            for target_index, target in enumerate(authors):
                trials.append(
                    TrialScores(
                        target_author=target.author_id,
                        source_author=source.author_id,
                        probe_index=probe_offset,
                        char_similarity=float(char_scores[probe_index, target_index]),
                        content_reduced_similarity=float(style_scores[probe_index, target_index]),
                        function_sequence_similarity=float(
                            function_scores[probe_index, target_index]
                        ),
                    )
                )
    return trials


def _labels(trials: Sequence[TrialScores]) -> np.ndarray:
    return np.asarray([trial.label for trial in trials], dtype=np.int8)


def matched_verification_trials(trials: Sequence[TrialScores]) -> list[TrialScores]:
    """Return one source-matched impostor trial per genuine trial.

    Identification evaluates every possible target. Binary verification instead
    compares each claimed author with their genuine probe and one deterministic
    different-author probe at the same probe offset.
    """

    authors = sorted({trial.target_author for trial in trials})
    by_key = {
        (trial.target_author, trial.source_author, trial.probe_index): trial
        for trial in trials
    }
    matched = []
    for target_index, target in enumerate(authors):
        impostor_source = authors[(target_index + 1) % len(authors)]
        probe_indices = sorted(
            {
                trial.probe_index
                for trial in trials
                if trial.target_author == target and trial.source_author == target
            }
        )
        for probe_index in probe_indices:
            matched.append(by_key[(target, target, probe_index)])
            matched.append(by_key[(target, impostor_source, probe_index)])
    return matched


def _signals(trials: Sequence[TrialScores]) -> np.ndarray:
    return np.asarray(
        [[trial.char_similarity, trial.content_reduced_similarity] for trial in trials],
        dtype=np.float64,
    )


def peer_aligned_signals(trials: Sequence[TrialScores]) -> np.ndarray:
    """Append leave-one-target-out cohort z-scores for each style signal.

    For a real submission, the claimed-profile similarity is meaningful only
    relative to similarities against available peer profiles. No ground-truth
    label enters this normalization.
    """
    raw = _signals(trials)
    aligned = np.zeros_like(raw)
    grouped = defaultdict(list)
    for index, trial in enumerate(trials):
        grouped[(trial.source_author, trial.probe_index)].append(index)
    for indices in grouped.values():
        if len(indices) < 3:
            raise ValueError("peer alignment requires at least three target profiles")
        block = raw[indices]
        for local_index, global_index in enumerate(indices):
            peers = np.delete(block, local_index, axis=0)
            mean = peers.mean(axis=0)
            std = peers.std(axis=0)
            aligned[global_index] = (raw[global_index] - mean) / np.maximum(std, 1e-9)
    return np.concatenate([raw, aligned], axis=1)


def alternative_aware_signals(trials: Sequence[TrialScores]) -> np.ndarray:
    """Add positive best-alternative margins and population ranks.

    Unlike a low claimed-author score, a negative margin says that a concrete
    enrolled peer matches better.  All values are computed per probe without
    using its ground-truth author label.
    """

    peer_aligned = peer_aligned_signals(trials)
    raw = peer_aligned[:, :2]
    alternative = np.zeros_like(raw)
    ranks = np.zeros_like(raw)
    grouped = defaultdict(list)
    for index, trial in enumerate(trials):
        grouped[(trial.source_author, trial.probe_index)].append(index)
    for indices in grouped.values():
        block = raw[indices]
        for local_index, global_index in enumerate(indices):
            others = np.delete(block, local_index, axis=0)
            alternative[global_index] = raw[global_index] - others.max(axis=0)
            ranks[global_index] = np.mean(block <= raw[global_index], axis=0)
    return np.concatenate([peer_aligned, alternative, ranks], axis=1)


def alternative_margin_signals(trials: Sequence[TrialScores]) -> np.ndarray:
    """Peer-aligned signals plus claimed-minus-best-enrolled-peer margins."""

    return alternative_aware_signals(trials)[:, :6]


def style_margin_only_signals(trials: Sequence[TrialScores]) -> np.ndarray:
    """Character and content-reduced claimed-minus-best-peer margins only."""

    return alternative_aware_signals(trials)[:, 4:6]


def function_sequence_signals(trials: Sequence[TrialScores]) -> np.ndarray:
    """Three style axes, peer z-scores, and best-alternative margins."""

    raw = np.asarray(
        [
            [
                trial.char_similarity,
                trial.content_reduced_similarity,
                trial.function_sequence_similarity,
            ]
            for trial in trials
        ],
        dtype=np.float64,
    )
    aligned = np.zeros_like(raw)
    margins = np.zeros_like(raw)
    grouped = defaultdict(list)
    for index, trial in enumerate(trials):
        grouped[(trial.source_author, trial.probe_index)].append(index)
    for indices in grouped.values():
        block = raw[indices]
        for local_index, global_index in enumerate(indices):
            peers = np.delete(block, local_index, axis=0)
            aligned[global_index] = (raw[global_index] - peers.mean(axis=0)) / np.maximum(
                peers.std(axis=0), 1e-9
            )
            margins[global_index] = raw[global_index] - peers.max(axis=0)
    return np.concatenate([raw, aligned, margins], axis=1)


def function_margin_signals(trials: Sequence[TrialScores]) -> np.ndarray:
    """Only claimed-minus-best-peer margins, eliminating cohort-level offsets."""

    return function_sequence_signals(trials)[:, 6:9]


def _metric_summary(labels: np.ndarray, scores: np.ndarray) -> dict:
    return {
        "auc": round(float(roc_auc_score(labels, scores)), 6),
        "brier": round(brier(labels, scores), 6) if np.all((scores >= 0) & (scores <= 1)) else None,
        "cllr": round(cllr(labels, scores), 6) if np.all((scores > 0) & (scores < 1)) else None,
        "tpr_at_fpr": {
            str(target): round(float(tpr_at_fpr(labels, scores, target)), 6)
            for target in (0.01, 0.05, 0.10)
        },
    }


def _per_author_auc(trials: Sequence[TrialScores], scores: np.ndarray) -> dict:
    grouped = defaultdict(list)
    for trial, score_value in zip(trials, scores):
        grouped[trial.target_author].append((trial.label, float(score_value)))
    values = []
    by_author = {}
    for author in sorted(grouped):
        labels = np.asarray([row[0] for row in grouped[author]], dtype=np.int8)
        author_scores = np.asarray([row[1] for row in grouped[author]], dtype=np.float64)
        value = auc(labels, author_scores)
        values.append(value)
        by_author[author] = round(value, 6)
    return {
        "median": round(float(np.median(values)), 6),
        "iqr": [
            round(float(np.percentile(values, 25)), 6),
            round(float(np.percentile(values, 75)), 6),
        ],
        "by_author": by_author,
    }


def _wilson_interval(successes: int, total: int, z: float = 1.959963984540054) -> list[float] | None:
    if total <= 0:
        return None
    rate = successes / total
    denominator = 1.0 + z * z / total
    centre = (rate + z * z / (2 * total)) / denominator
    margin = z * math.sqrt(rate * (1 - rate) / total + z * z / (4 * total * total)) / denominator
    return [max(0.0, centre - margin), min(1.0, centre + margin)]


def _threshold_at_fpr(labels: np.ndarray, scores: np.ndarray, target_fpr: float) -> float:
    negatives = np.sort(scores[labels == 0])
    if negatives.size == 0:
        raise ValueError("threshold selection requires negative trials")
    allowed = int(math.floor(target_fpr * negatives.size))
    if allowed == 0:
        return float(np.nextafter(negatives[-1], np.inf))
    return float(np.nextafter(negatives[-allowed], np.inf))


def _threshold_at_constraints(
    labels: np.ndarray,
    scores: np.ndarray,
    *,
    target_precision: float = 0.90,
    max_fpr: float = 0.01,
    min_true_positives: int = 10,
) -> float:
    """Largest-coverage calibration threshold satisfying all product gates."""

    labels = np.asarray(labels, dtype=np.int8)
    scores = np.asarray(scores, dtype=np.float64)
    positives = labels == 1
    negatives = ~positives
    retained = []
    for threshold in sorted(set(scores.tolist()), reverse=True):
        selected = scores >= threshold
        true_positive = int(np.sum(selected & positives))
        false_positive = int(np.sum(selected & negatives))
        if true_positive < min_true_positives:
            continue
        precision = true_positive / max(1, true_positive + false_positive)
        fpr = false_positive / max(1, int(negatives.sum()))
        if precision >= target_precision and fpr <= max_fpr:
            retained.append((true_positive, float(threshold)))
    if not retained:
        return float(np.nextafter(scores.max(), np.inf))
    return max(retained, key=lambda row: (row[0], -row[1]))[1]


def _operating_result(labels: np.ndarray, scores: np.ndarray, threshold: float) -> dict:
    selected = scores >= threshold
    positives = labels == 1
    negatives = ~positives
    tp = int(np.sum(selected & positives))
    fp = int(np.sum(selected & negatives))
    n_positive = int(positives.sum())
    n_negative = int(negatives.sum())
    return {
        "threshold": threshold,
        "tpr": tp / n_positive,
        "tpr_wilson_95": _wilson_interval(tp, n_positive),
        "fpr": fp / n_negative,
        "fpr_wilson_95": _wilson_interval(fp, n_negative),
        "precision": float(np.mean(labels[selected])) if np.any(selected) else None,
        "selected": int(selected.sum()),
        "true_positive": tp,
        "false_positive": fp,
        "n_genuine": n_positive,
        "n_impostor": n_negative,
    }


def run_experiment(
    *,
    cache_dir: Path = DEFAULT_CACHE,
    output_path: Path | None = None,
    n_development: int = 120,
    n_calibration: int = 40,
    n_locked: int = 12,
    prior_locked_authors: int = 0,
    post_calibration_excluded_authors: int = 0,
    peer_aligned: bool = False,
    alternative_aware: bool = False,
    alternative_margin: bool = False,
    matched_evaluation: bool = False,
    function_sequence: bool = False,
    function_margin_only: bool = False,
    style_margin_only: bool = False,
    char_max_features: int = 30_000,
) -> dict:
    partitions = load_author_partitions(
        cache_dir=cache_dir,
        n_development=n_development,
        n_calibration=n_calibration,
        n_locked=n_locked,
        prior_locked_authors=prior_locked_authors,
        post_calibration_excluded_authors=post_calibration_excluded_authors,
    )
    vectorizer, scaler = _fit_representations(
        partitions["development"], char_max_features=char_max_features
    )
    function_vectorizer = (
        _fit_function_sequence(partitions["development"])
        if function_sequence or function_margin_only
        else None
    )
    development = _score_partition(
        partitions["development"], vectorizer, scaler, function_vectorizer
    )
    calibration = _score_partition(
        partitions["calibration"], vectorizer, scaler, function_vectorizer
    )
    locked = _score_partition(partitions["locked"], vectorizer, scaler, function_vectorizer)

    calibrator = Pipeline(
        [
            ("scale", StandardScaler()),
            (
                "logistic",
                LogisticRegression(
                    C=0.5,
                    class_weight="balanced",
                    max_iter=2000,
                    random_state=SEED,
                ),
            ),
        ]
    )
    if sum(
        (
            alternative_aware,
            alternative_margin,
            function_sequence,
            function_margin_only,
            style_margin_only,
        )
    ) > 1:
        raise ValueError("choose one alternative signal variant")
    if style_margin_only:
        signal_matrix = style_margin_only_signals
    elif function_margin_only:
        signal_matrix = function_margin_signals
    elif function_sequence:
        signal_matrix = function_sequence_signals
    elif alternative_aware:
        signal_matrix = alternative_aware_signals
    elif alternative_margin:
        signal_matrix = alternative_margin_signals
    else:
        signal_matrix = peer_aligned_signals if peer_aligned else _signals
    calibrator.fit(signal_matrix(development), _labels(development))
    calibration_evaluation = (
        matched_verification_trials(calibration) if matched_evaluation else calibration
    )
    locked_evaluation = matched_verification_trials(locked) if matched_evaluation else locked
    calibration_signal_full = signal_matrix(calibration)
    locked_signal_full = signal_matrix(locked)
    calibration_positions = {trial: index for index, trial in enumerate(calibration)}
    locked_positions = {trial: index for index, trial in enumerate(locked)}
    probability = {
        "development": calibrator.predict_proba(signal_matrix(development))[:, 1],
        "calibration": calibrator.predict_proba(
            calibration_signal_full[
                [calibration_positions[trial] for trial in calibration_evaluation]
            ]
        )[:, 1],
        "locked": calibrator.predict_proba(
            locked_signal_full[[locked_positions[trial] for trial in locked_evaluation]]
        )[:, 1],
    }
    trial_sets = {
        "development": development,
        "calibration": calibration_evaluation,
        "locked": locked_evaluation,
    }

    thresholds = {
        "0.01": _threshold_at_constraints(
            _labels(calibration_evaluation), probability["calibration"]
        ),
        "0.05": _threshold_at_fpr(
            _labels(calibration_evaluation), probability["calibration"], 0.05
        ),
        "0.1": _threshold_at_fpr(
            _labels(calibration_evaluation), probability["calibration"], 0.10
        ),
    }
    result = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": {"zenodo_doi": ZENODO_DOI, "zenodo_record": ZENODO_RECORD},
        "partition_authors": {name: [a.author_id for a in rows] for name, rows in partitions.items()},
        "partition_sizes": {name: len(rows) for name, rows in partitions.items()},
        "prior_locked_authors_excluded": prior_locked_authors,
        "post_calibration_excluded_authors": post_calibration_excluded_authors,
        "evaluation_protocol": (
            "binary source-matched: one deterministic impostor per genuine"
            if matched_evaluation
            else "exhaustive target identification: every source against every target"
        ),
        "feature_model": {
            "character": "TF-IDF character 3-5 grams, development baselines only",
            "content_reduced": "z-scored function words, punctuation, word lengths, sentence rhythm",
            "character_vocabulary_size": len(vectorizer.vocabulary_),
            "function_sequence_vocabulary_size": (
                len(function_vectorizer.vocabulary_) if function_vectorizer is not None else None
            ),
            "calibrator_signal_order": (
                [
                    "character",
                    "content_reduced",
                    "function_sequence",
                    "peer_z_character",
                    "peer_z_content_reduced",
                    "peer_z_function_sequence",
                    "alternative_margin_character",
                    "alternative_margin_content_reduced",
                    "alternative_margin_function_sequence",
                ]
                if function_sequence
                else [
                    "alternative_margin_character",
                    "alternative_margin_content_reduced",
                ]
                if style_margin_only
                else [
                    "alternative_margin_character",
                    "alternative_margin_content_reduced",
                    "alternative_margin_function_sequence",
                ]
                if function_margin_only
                else
                [
                    "character",
                    "content_reduced",
                    "peer_z_character",
                    "peer_z_content_reduced",
                    "alternative_margin_character",
                    "alternative_margin_content_reduced",
                    "population_rank_character",
                    "population_rank_content_reduced",
                ]
                if alternative_aware
                else [
                    "character",
                    "content_reduced",
                    "peer_z_character",
                    "peer_z_content_reduced",
                    "alternative_margin_character",
                    "alternative_margin_content_reduced",
                ]
                if alternative_margin
                else
                ["character", "content_reduced", "peer_z_character", "peer_z_content_reduced"]
                if peer_aligned
                else ["character", "content_reduced"]
            ),
            "calibrator_standardized_coefficients": calibrator.named_steps["logistic"].coef_[0].tolist(),
            "calibrator_intercept": float(calibrator.named_steps["logistic"].intercept_[0]),
        },
        "metrics": {},
        "calibration_thresholds": thresholds,
        "calibration_operating_points": {},
        "locked_operating_points": {},
    }
    for name, trials in trial_sets.items():
        labels = _labels(trials)
        result["metrics"][name] = {
            "character_auc": round(float(roc_auc_score(labels, _signals(trials)[:, 0])), 6),
            "content_reduced_auc": round(float(roc_auc_score(labels, _signals(trials)[:, 1])), 6),
            "calibrated_fusion": _metric_summary(labels, probability[name]),
            "fusion_per_author_auc": _per_author_auc(trials, probability[name]),
            "n_trials": len(trials),
            "n_genuine": int(labels.sum()),
            "n_impostor": int(len(labels) - labels.sum()),
        }
    locked_labels = _labels(locked_evaluation)
    for target, threshold in thresholds.items():
        result["calibration_operating_points"][target] = _operating_result(
            _labels(calibration_evaluation), probability["calibration"], threshold
        )
        result["locked_operating_points"][target] = _operating_result(
            locked_labels, probability["locked"], threshold
        )
    strict = result["locked_operating_points"]["0.01"]
    locked_metric = result["metrics"]["locked"]["calibrated_fusion"]
    gates = {
        "auc_at_least_0_85": locked_metric["auc"] >= 0.85,
        "cllr_below_1": locked_metric["cllr"] < 1.0,
        "locked_fpr_at_most_0_01": strict["fpr"] <= 0.01,
        "locked_precision_at_least_0_90": (
            strict["precision"] is not None and strict["precision"] >= 0.90
        ),
        "locked_recall_at_least_0_50": strict["tpr"] >= 0.50,
        "at_least_100_locked_authors": n_locked >= 100,
        "at_least_100_locked_genuine_trials": int(locked_labels.sum()) >= 100,
    }
    result["promotion_gate"] = {
        "passed": all(gates.values()),
        "conditions": gates,
        "decision": "validation_only" if not all(gates.values()) else "eligible_for_report_only_review",
    }
    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


if __name__ == "__main__":
    report = run_experiment(
        output_path=Path("validation/benchmarks/2026-08-04/pan_style_expert.json")
    )
    print(json.dumps({"locked": report["metrics"]["locked"], "operating": report["locked_operating_points"]}, indent=2))
