"""Official PAN authorship-verification scorecard for Original's verifiers.

Measurement only. Nothing here is imported by the live API, and no score,
constant, threshold or flag is changed or refit on a test pair. Three frozen
verifiers are scored with the official PAN measures
(:mod:`validation.verify.pan_official_metrics`) on the PAN 2020 and PAN 2021
authorship-verification test sets.

Verifiers, and how each becomes a PAN score in [0, 1] (above 0.5 = same author):

``deviation_score``
    The live scorer (``original.quantum.scoring.score``) under the pilot
    configuration that ``lock_environment`` pins (``NULL_MODEL=none``, context
    manifest and adaptive weights off). PAN score = 1 - deviation_score. A
    second row moves the decision point to the live ``no_action`` boundary
    (deviation 0.40) with a monotone piecewise-linear map, which leaves AUC
    unchanged and changes only the thresholded measures.
``fused_score_v1``
    The committed artifact ``original/data/fused_score_v1.json`` through the
    production entry point ``predict_fused_score_with_reason``. PAN score =
    1 - probability_different_author; an abstention is 0.5.
``luar_style_fusion``
    The validation-only LUAR + style cross-channel interaction fusion
    (``cross_channel_interactions`` in ``pan_luar_expert.py``). It has no
    saved artifact: it is refit deterministically from the same 120 PAN 2020
    development authors, and before any test pair is scored it must reproduce
    the calibration and lock AUCs recorded in the committed
    ``pan_auth_luar_*_lock100.json`` files.

Protocols:

``pair_strict``
    PAN's format exactly: one known text, one unknown text, nothing else.
    Every verifier needs three approved baselines (and two need an enrolled
    peer pool), so each abstains on every pair and scores 0.5.
``pair_split3``
    The smallest change that lets each verifier run on a PAN pair. The known
    text's 2,500-word window is split into three contiguous equal parts used
    as three baselines; the unknown text's window is the probe. Peer profiles
    come from 99 of the 100 PAN 2020 calibration authors (author-disjoint from
    every scored pair). This is NOT PAN's protocol: it is a documented
    adaptation, reported next to the strict row.
``lock_3baseline``
    The repo's own protocol: 100 authors, three cross-topic baseline documents
    each, a closed enrolled pool, one matched impostor per genuine trial. PAN
    2020: the committed 100-author lock; PAN 2021: the committed open-set lock
    (99 PAN 2021 authors plus one PAN 2020 tail author).

Every document is the repo's deterministic 2,500-word window
(``pan_corpus._fixed_window``), as in every earlier PAN run here.

Stages. LUAR needs torch, transformers 4.x and einops; the rest does not, and
the deviation score must run without sentence-transformers to match the
pilot's TF-IDF fallback, so the stages run in different environments::

    .benchmark_cache/luar-venv/bin/python -m validation.verify.pan_official_scorecard embed
    .venv/bin/python -m validation.verify.pan_official_scorecard features
    .venv/bin/python -m validation.verify.pan_official_scorecard score
    .venv/bin/python -m validation.verify.pan_official_scorecard report
"""

from __future__ import annotations

from validation.benchmark.reproducibility import lock_environment

ENV_LOCK = lock_environment()

import argparse
import itertools
import json
import math
import platform
import subprocess
import sys
import time
import warnings
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Sequence

import numpy as np
from scipy.sparse import csr_matrix, vstack

from validation.verify.pan_corpus import ZENODO_DOI, ZENODO_RECORD, _digest, _discover, _fixed_window
from validation.verify.pan_luar_expert import (
    MAX_TOKENS,
    MODEL_ID,
    MODEL_REVISION,
    PAN21_ARCHIVE,
    PAN21_ARCHIVE_MD5,
    EmbeddingCache,
    LuarTrial,
    _episode_key,
    _labels as _luar_labels,
    build_calibrator,
    embed_partitions,
    fit_lda_metric,
    fit_plda,
    lda_score_matrix,
    matched_trials,
    plda_score_matrix,
    score_partition,
    signal_matrix,
)
from validation.verify.pan_official_metrics import UNANSWERED, evaluate_all
from validation.verify.pan_style_expert import (
    SEED,
    StyleAuthor,
    _eligible_authors,
    _fit_representations,
    _score_partition,
    load_author_partitions,
    style_margin_only_signals,
)

ROOT = Path(__file__).resolve().parents[2]
PAN_CACHE = ROOT / ".benchmark_cache" / "pan"
LUAR_PARTITION_CACHE = ROOT / ".benchmark_cache" / "luar" / "pan_luar_embeddings.npz"
LUAR_PAIR_CACHE = ROOT / ".benchmark_cache" / "luar" / "pan_official_pair_embeddings.npz"
LUAR_PAIR_META = LUAR_PAIR_CACHE.with_suffix(".meta.json")
FEATURE_CACHE = ROOT / ".benchmark_cache" / "features" / "pan_official_vectors.npz"
ANSWERS_DIR = PAN_CACHE / "official_answers"
DEFAULT_OUTPUT = ROOT / "validation" / "verify" / "pan_official_scorecard.json"

MAX_WORDS = 2500
SPLITS = 3
N_REFERENCE_AUTHORS = 99
LUAR_VARIANT = "cross_channel_interactions"
LUAR_COLUMNS = tuple(range(14))
REPRODUCTION_TOLERANCE = 0.005
BOOTSTRAP_B = 1000
NO_ACTION_UPPER = 0.40  # ACTION_THRESHOLDS["no_action"][1]; checked at score time

DATASETS = {
    "pan20": {
        "cache_dir": PAN_CACHE / "2020",
        "archive": "pan20-authorship-verification-test.zip",
        "md5": "655f365ab7b736036bbbee717168012b",
        "committed_lock": ROOT / "validation" / "verify" / "pan_auth_luar_matched_cal100_lock100.json",
        "description": "PAN 2020 closed-set test (authors and fandoms seen in PAN's training set)",
    },
    "pan21": {
        "cache_dir": PAN_CACHE / "2021",
        "archive": PAN21_ARCHIVE,
        "md5": PAN21_ARCHIVE_MD5,
        "committed_lock": ROOT / "validation" / "verify" / "pan_auth_luar_pan21_open_lock100.json",
        "description": "PAN 2021 open-set test (authors and fandoms unseen in PAN's training set)",
    },
}

PUBLISHED_TARGETS = {
    # pan.webis.de task pages, read 2026-10-21. PAN 2020 published four
    # measures and its "overall" is their mean (no Brier); PAN 2021 added Brier.
    "pan20": {
        "system": "boenninghoff20-large (PAN 2020 winner)",
        "auc": 0.969,
        "c@1": 0.928,
        "f_05_u": 0.907,
        "F1": 0.936,
        "overall": 0.935,
        "overall_measures": 4,
    },
    "pan21": {
        "system": "boenninghoff21-large (PAN 2021 task page, preliminary)",
        "auc": 0.9869,
        "c@1": 0.9502,
        "F1": 0.9524,
        "f_05_u": 0.9378,
        "brier": 0.9452,
        "overall": 0.9545,
        "overall_measures": 5,
    },
    "pan23": {
        "system": "Ibrahim et al. (PAN 2023 cross-discourse winner); cngdist baseline",
        "source": "as quoted in the task brief; the PAN 2023 task page hides its results table",
        "auc": 0.616,
        "overall": 0.623,
        "baseline_cngdist_auc": 0.516,
        "baseline_cngdist_overall": 0.595,
    },
}


# ── Data ──────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class OfficialPair:
    pair_id: str
    label: int
    authors: tuple[str, str]
    known: str
    unknown: str


def window(text: str) -> str:
    return _fixed_window(text, MAX_WORDS, _digest(text))


def split_known(text: str, parts: int = SPLITS) -> tuple[str, ...]:
    """Split one document into ``parts`` contiguous, near-equal word runs."""

    words = text.split()
    if len(words) < parts:
        raise ValueError(f"cannot split {len(words)} words into {parts} parts")
    bounds = [len(words) * index // parts for index in range(parts + 1)]
    return tuple(" ".join(words[start:end]) for start, end in zip(bounds, bounds[1:]))


def load_official_pairs(cache_dir: Path, *, limit: int | None = None) -> list[OfficialPair]:
    """Every official test pair, in file order, with both texts windowed."""

    pairs_path, truth_path = _discover(cache_dir)
    truth = {}
    with truth_path.open(encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            truth[row["id"]] = row
    pairs = []
    with pairs_path.open(encoding="utf-8") as handle:
        for line in handle:
            row = json.loads(line)
            target = truth.get(row["id"])
            if target is None:
                raise ValueError(f"PAN pair {row['id']} has no truth row")
            texts, authors = row.get("pair", []), target.get("authors", [])
            if len(texts) != 2 or len(authors) != 2:
                raise ValueError(f"malformed PAN pair {row['id']}")
            if bool(target["same"]) != (authors[0] == authors[1]):
                raise ValueError(f"PAN label and author ids disagree: {row['id']}")
            pairs.append(
                OfficialPair(
                    pair_id=row["id"],
                    label=int(bool(target["same"])),
                    authors=(str(authors[0]), str(authors[1])),
                    known=window(texts[0]),
                    unknown=window(texts[1]),
                )
            )
            if limit is not None and len(pairs) >= limit:
                break
    return pairs


def public_author_id(raw_author: str) -> str:
    return f"pan20_{_digest(f'{ZENODO_RECORD}:{raw_author}')[:12]}"


def load_partitions() -> dict[str, list[StyleAuthor]]:
    """The committed fitting splits and both committed locks, rebuilt exactly."""

    cache_2020 = DATASETS["pan20"]["cache_dir"]
    fitted = load_author_partitions(
        cache_dir=cache_2020,
        n_development=120,
        n_calibration=100,
        n_locked=100,
        prior_locked_authors=12,
        post_calibration_excluded_authors=120,
    )
    external = load_author_partitions(
        cache_dir=DATASETS["pan21"]["cache_dir"],
        n_development=0,
        n_calibration=0,
        n_locked=99,
        prior_locked_authors=0,
        post_calibration_excluded_authors=0,
        probe_samples=1,
    )
    tail = load_author_partitions(
        cache_dir=cache_2020,
        n_development=0,
        n_calibration=0,
        n_locked=1,
        prior_locked_authors=452,
        post_calibration_excluded_authors=0,
    )["locked"][0]
    pan21_lock = list(external["locked"]) + [
        StyleAuthor(
            author_id=tail.author_id,
            baseline_fandom=tail.baseline_fandom,
            probe_fandom=tail.probe_fandom,
            baselines=tail.baselines,
            probes=(tail.probes[0],),
        )
    ]
    partitions = {
        "development": fitted["development"],
        "calibration": fitted["calibration"],
        "pan20_lock": fitted["locked"],
        "pan21_lock": pan21_lock,
    }
    for dataset, lock_name in (("pan20", "pan20_lock"), ("pan21", "pan21_lock")):
        committed = json.loads(DATASETS[dataset]["committed_lock"].read_text())
        expected = committed["protocol"]["partition_authors"]
        for name, rebuilt in (
            ("development", partitions["development"]),
            ("calibration", partitions["calibration"]),
            ("locked", partitions[lock_name]),
        ):
            if [author.author_id for author in rebuilt] != expected[name]:
                raise RuntimeError(
                    f"rebuilt {name} authors differ from {DATASETS[dataset]['committed_lock'].name}"
                )
    return partitions


def reference_authors(partitions: dict[str, list[StyleAuthor]]) -> list[StyleAuthor]:
    return list(partitions["calibration"][:N_REFERENCE_AUTHORS])


def pan20_author_groups() -> dict[str, list[str]]:
    """Raw PAN 2020 author ids by how earlier repo work used them."""

    ordered = [
        author
        for author, _ in _eligible_authors(
            DATASETS["pan20"]["cache_dir"], min_text_chars=800, baseline_samples=3, probe_samples=3
        )
    ]
    return {
        "development": ordered[12:132],
        "calibration": ordered[132:232],
        "prior_lock_12": ordered[:12],
        "post_calibration_skipped_120": ordered[232:352],
        "lock_100": ordered[352:452],
        "pan21_lock_tail_author": ordered[452:453],
        "local_threshold_43": ordered[453:496],
    }


def exclusions(
    dataset: str,
    pairs: Sequence[OfficialPair],
    groups: dict[str, list[str]],
    partitions: dict[str, list[StyleAuthor]],
) -> tuple[list[OfficialPair], dict]:
    """Drop pairs with an author from a fitting split; report everything else."""

    fitting = {"development", "calibration"}
    for name in fitting:
        rebuilt = [author.author_id for author in partitions[name]]
        if [public_author_id(raw) for raw in groups[name]] != rebuilt:
            raise RuntimeError(f"raw {name} authors do not map to the rebuilt partition")
    membership = {raw: name for name, raws in groups.items() for raw in raws}
    kept, excluded_by = [], Counter()
    touched = Counter()
    for pair in pairs:
        names = {membership[a] for a in pair.authors if a in membership}
        hit = sorted(names & fitting)
        if hit:
            excluded_by["+".join(hit)] += 1
            continue
        kept.append(pair)
        for name in sorted(names):
            touched[name] += 1
    fitting_texts = {
        _digest(text)
        for name in fitting
        for author in partitions[name]
        for text in author.baselines + author.probes
    }
    leaked = sum(
        1
        for pair in kept
        if _digest(pair.known) in fitting_texts or _digest(pair.unknown) in fitting_texts
    )
    if leaked:
        raise RuntimeError(f"{dataset}: {leaked} kept pairs reuse a fitting-split text")
    return kept, {
        "rule": (
            "exclude a pair if either text's author is in the PAN 2020 development split "
            "(fits the LUAR fusion, its PLDA/LDA/style representations and fused_score_v1) "
            "or the calibration split (selects the LUAR variant and threshold; fused_score_v1 "
            "held-out; the pair_split3 peer pool)"
        ),
        "official_pairs": len(pairs),
        "excluded_pairs": sum(excluded_by.values()),
        "excluded_by_split": dict(sorted(excluded_by.items())),
        "evaluated_pairs": len(kept),
        "evaluated_same_author": sum(pair.label for pair in kept),
        "kept_pairs_touching_evaluation_only_authors": dict(sorted(touched.items())),
        "kept_pairs_reusing_a_fitting_text": leaked,
    }


# ── LUAR embeddings ───────────────────────────────────────────────────────────


def pair_episodes(pairs: Sequence[OfficialPair]) -> list[tuple[str, ...]]:
    episodes = []
    for pair in pairs:
        chunks = split_known(pair.known)
        episodes.append(chunks)
        episodes.extend((chunk,) for chunk in chunks)
        episodes.append((pair.unknown,))
    return episodes


def embed_episodes(
    episodes: Sequence[tuple[str, ...]],
    *,
    cache: EmbeddingCache,
    embedder: Callable[[Sequence[Sequence[str]]], np.ndarray],
    documents_per_batch: int = 32,
    save_every: int = 20_000,
) -> int:
    """Embed every missing episode, saving the cache every ``save_every``."""

    missing: dict[int, dict[str, tuple[str, ...]]] = {}
    for episode in episodes:
        key = _episode_key(episode)
        if key not in cache.values:
            missing.setdefault(len(episode), {})[key] = episode
    total = sum(len(group) for group in missing.values())
    done = since_save = 0
    started = time.perf_counter()
    for length in sorted(missing):
        group = list(missing[length].values())
        batch_size = max(1, documents_per_batch // length)
        for start in range(0, len(group), batch_size):
            batch = group[start : start + batch_size]
            vectors = embedder(batch)
            if vectors.shape != (len(batch), 512):
                raise ValueError(f"embedder returned {vectors.shape}")
            for episode, vector in zip(batch, vectors):
                cache.put(episode, vector)
            done += len(batch)
            since_save += len(batch)
            if since_save >= save_every:
                cache.save()
                since_save = 0
            if done % 2000 < len(batch) or done == total:
                rate = done / max(time.perf_counter() - started, 1e-9)
                print(f"[embed] {done}/{total} episodes ({rate:.1f}/s)", file=sys.stderr, flush=True)
    if total:
        cache.save()
    return total


def _cache_only_embedder(_episodes):
    raise RuntimeError("LUAR embedding missing from cache: run the embed stage first")


def _partition_dicts(partitions):
    return (
        {
            "development": partitions["development"],
            "calibration": partitions["calibration"],
            "locked": partitions["pan20_lock"],
        },
        {"locked": partitions["pan21_lock"]},
    )


def embed_all_partitions(partitions, embedder) -> dict[str, dict[str, object]]:
    """LUAR embeddings for every partition, via the committed code path."""

    cache = EmbeddingCache(LUAR_PARTITION_CACHE)
    first, second = _partition_dicts(partitions)
    embedded = embed_partitions(first, cache=cache, embedder=embedder)
    embedded_21 = embed_partitions(second, cache=cache, embedder=embedder)
    return {
        "development": embedded["development"],
        "calibration": embedded["calibration"],
        "pan20_lock": embedded["locked"],
        "pan21_lock": embedded_21["locked"],
    }


# ── LUAR + style fusion ───────────────────────────────────────────────────────


@dataclass
class LuarFusion:
    plda: object
    lda: object
    style_vectorizer: object
    style_scaler: object
    calibrator: object


def fit_luar_fusion(partitions, embedded) -> LuarFusion:
    """``run_experiment``'s fit, step for step, for the committed variant only."""

    development = partitions["development"]
    plda = fit_plda(embedded["development"])
    lda = fit_lda_metric(embedded["development"])
    exhaustive = score_partition(development, embedded["development"], plda, lda)
    vectorizer, scaler = _fit_representations(development)
    style = _score_partition(development, vectorizer, scaler)
    matrix = np.column_stack((signal_matrix(exhaustive), style_margin_only_signals(style)))
    calibrator = build_calibrator(interactions=True)
    calibrator.fit(matrix[:, LUAR_COLUMNS], _luar_labels(exhaustive))
    return LuarFusion(plda, lda, vectorizer, scaler, calibrator)


def partition_trials(
    fusion: LuarFusion, authors: Sequence[StyleAuthor], embedded_partition
) -> tuple[list[LuarTrial], np.ndarray]:
    """Matched trials and their fused probabilities, as ``run_experiment`` scores them."""

    exhaustive = score_partition(authors, embedded_partition, fusion.plda, fusion.lda)
    style = _score_partition(authors, fusion.style_vectorizer, fusion.style_scaler)
    matrix = np.column_stack((signal_matrix(exhaustive), style_margin_only_signals(style)))
    positions = {trial: index for index, trial in enumerate(exhaustive)}
    evaluated = matched_trials(exhaustive)
    indices = [positions[trial] for trial in evaluated]
    probability = fusion.calibrator.predict_proba(matrix[indices][:, LUAR_COLUMNS])[:, 1]
    return evaluated, probability


def _unit(values: np.ndarray, axis: int = -1) -> np.ndarray:
    values = np.asarray(values, dtype=np.float64)
    return values / np.maximum(np.linalg.norm(values, axis=axis, keepdims=True), 1e-12)


def _char_centroids(rows, n_baselines: int):
    centroids = []
    for index in range(rows.shape[0] // n_baselines):
        centroid = csr_matrix(rows[index * n_baselines : (index + 1) * n_baselines].mean(axis=0))
        norm = math.sqrt(float(centroid.multiply(centroid).sum()))
        centroids.append(centroid / max(norm, 1e-12))
    return vstack(centroids)


def pair_luar_signals(
    fusion: LuarFusion,
    *,
    claimed_episode: np.ndarray,
    claimed_documents: np.ndarray,
    probes: np.ndarray,
    claimed_texts: Sequence[Sequence[str]],
    probe_texts: Sequence[str],
    reference_episode: np.ndarray,
    reference_documents: np.ndarray,
    reference_texts: Sequence[Sequence[str]],
    chunk: int = 512,
) -> np.ndarray:
    """The 14 fusion signals for each claimed profile against its own probe.

    Row ``p`` is what ``signal_matrix`` and ``style_margin_only_signals``
    produce for the trial (claimed ``p``, probe ``p``) in a block whose other
    targets are the reference authors. Shapes: ``claimed_episode`` (P, 512),
    ``claimed_documents`` (P, B, 512), ``probes`` (P, 512), ``reference_episode``
    (R, 512), ``reference_documents`` (R, B, 512).
    """

    from original.style_authorship import content_reduced_signature

    n = len(probes)
    probe_unit = _unit(probes)
    raw = np.sum(_unit(claimed_episode) * probe_unit, axis=1)
    peer_raw = probe_unit @ _unit(reference_episode).T
    zscore = (raw - peer_raw.mean(axis=1)) / np.maximum(peer_raw.std(axis=1), 1e-9)
    margin = raw - peer_raw.max(axis=1)

    documents = _unit(claimed_documents)
    per_document = np.einsum("pd,pbd->pb", probe_unit, documents)
    cohesion = np.einsum("pbd,pcd->pbc", documents, documents)
    upper = np.triu_indices(documents.shape[1], k=1)
    cohesion_pairs = cohesion[:, upper[0], upper[1]]
    consistency = np.column_stack(
        (
            per_document.mean(axis=1),
            per_document.min(axis=1),
            per_document.std(axis=1),
            cohesion_pairs.mean(axis=1),
            cohesion_pairs.min(axis=1),
            per_document.mean(axis=1) - cohesion_pairs.mean(axis=1),
        )
    )

    probes32 = np.asarray(probes, dtype=np.float32)
    docs32 = np.asarray(claimed_documents, dtype=np.float32)
    plda = np.empty(n)
    lda = np.empty(n)
    for index in range(n):
        single = {"baseline_documents": docs32[index : index + 1].copy(), "probes": probes32[index : index + 1, None, :].copy()}
        plda[index] = plda_score_matrix(fusion.plda, single)[0, 0, 0]
        lda[index] = lda_score_matrix(fusion.lda, single)[0, 0, 0]
    peer_lda = lda_score_matrix(
        fusion.lda,
        {
            "baseline_documents": np.asarray(reference_documents, dtype=np.float32).copy(),
            "probes": probes32[:, None, :].copy(),
        },
    )[:, 0, :]
    lda_margin = lda - peer_lda.max(axis=1)

    n_baselines = len(claimed_texts[0])
    vectorizer, scaler = fusion.style_vectorizer, fusion.style_scaler
    claimed_flat = [text for texts in claimed_texts for text in texts]
    reference_flat = [text for texts in reference_texts for text in texts]
    probe_char = vectorizer.transform(list(probe_texts))
    claimed_centroids = _char_centroids(vectorizer.transform(claimed_flat), n_baselines)
    reference_centroids = _char_centroids(vectorizer.transform(reference_flat), n_baselines)
    char_claimed = np.asarray(probe_char.multiply(claimed_centroids).sum(axis=1)).ravel()
    char_peer = (probe_char @ reference_centroids.T).toarray()
    char_margin = char_claimed - char_peer.max(axis=1)

    def styled(texts):
        return scaler.transform(np.stack([content_reduced_signature(text) for text in texts]))

    probe_style = styled(probe_texts)
    claimed_style = styled(claimed_flat).reshape(n, n_baselines, -1).mean(axis=1)
    reference_style = styled(reference_flat).reshape(len(reference_texts), n_baselines, -1).mean(axis=1)
    style_claimed = -np.mean(np.abs(probe_style - claimed_style), axis=1)
    style_peer_max = np.empty(n)
    for start in range(0, n, chunk):
        block = probe_style[start : start + chunk]
        style_peer_max[start : start + chunk] = (
            -np.mean(np.abs(block[:, None, :] - reference_style[None, :, :]), axis=2)
        ).max(axis=1)
    style_margin = style_claimed - style_peer_max

    return np.column_stack(
        (raw, zscore, margin, consistency, plda, lda, lda_margin, char_margin, style_margin)
    )


# ── Original's verifiers ──────────────────────────────────────────────────────


def _state(student_id: str, texts: Sequence[str], vectors: dict, assignment: str):
    from original.quantum.state import BaselineSample, StudentState

    return StudentState(
        student_id=student_id,
        samples=[
            BaselineSample(
                text=text,
                vector=vectors[text],
                provenance="verified",
                auth_weight=1.0,
                assignment=assignment,
                submitted_at="2026-01-01",
            )
            for text in texts
        ],
    )


def anchored_deviation_score(deviation: float, boundary: float = NO_ACTION_UPPER) -> float:
    """Monotone map putting PAN's 0.5 at the live ``no_action`` boundary."""

    if deviation < boundary:
        return 0.5 + 0.5 * (boundary - deviation) / boundary
    return 0.5 - 0.5 * min(deviation - boundary, 1.0 - boundary) / (1.0 - boundary)


class OriginalVerifiers:
    """deviation_score and fused_score_v1 for one claimed profile at a time."""

    def __init__(self, vectors: dict):
        from original.constants import ACTION_THRESHOLDS, ALL_FEATURE_CODES
        from original.fusion.artifact import load_artifact
        from original.quantum.scoring import ScoringConfig

        if ACTION_THRESHOLDS["no_action"][1] != NO_ACTION_UPPER:
            raise RuntimeError("live no_action boundary moved; update NO_ACTION_UPPER")
        self.config = ScoringConfig.from_env()
        if self.config.null_model != "none":
            raise RuntimeError("pilot config requires NULL_MODEL=none")
        if load_artifact() is None:
            raise RuntimeError("fused_score_v1 artifact failed to load")
        self.codes = ALL_FEATURE_CODES
        self.vectors = vectors
        self.fused_reasons: Counter = Counter()

    def state(self, student_id: str, texts: Sequence[str], assignment: str):
        return _state(student_id, texts, self.vectors, assignment)

    def deviation(self, state, probe: str, submission_id: str) -> float:
        from original.quantum.scoring import score

        vector = self.vectors[probe]
        result = score(
            state,
            vector,
            dict(zip(self.codes, vector)),
            submission_id=submission_id,
            n_tokens=len(probe.split()),
            scoring_config=self.config,
        )
        return float(result.authorship.deviation_score)

    def fused(self, state, probe: str, peers: Sequence) -> float:
        from original.fusion.expert import predict_fused_score_with_reason

        result, reason, _, _ = predict_fused_score_with_reason(
            probe, state, peers, probe_vector=self.vectors[probe]
        )
        self.fused_reasons[reason] += 1
        if result is None:
            return UNANSWERED
        return 1.0 - float(result.probability_different_author)


# ── Scoring ───────────────────────────────────────────────────────────────────


def bootstrap_interval(labels: np.ndarray, scores: np.ndarray, *, seed: int = SEED) -> dict:
    """Trial-level percentile 95% intervals for AUC and overall.

    Trials share authors and texts, so these intervals ignore that clustering
    and are narrower than an author-level resample would give.
    """

    rng = np.random.default_rng(seed)
    n = len(labels)
    draws = {"auc": [], "overall": []}
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        for _ in range(BOOTSTRAP_B):
            index = rng.integers(0, n, size=n)
            if labels[index].min() == labels[index].max():
                continue
            result = evaluate_all(labels[index], scores[index], digits=None)
            draws["auc"].append(result["auc"])
            draws["overall"].append(result["overall"])
    return {
        name: [round(float(np.percentile(values, 2.5)), 3), round(float(np.percentile(values, 97.5)), 3)]
        for name, values in draws.items()
    }


def summarize(labels: Sequence[int], scores: Sequence[float], *, extra: dict | None = None) -> dict:
    labels = np.asarray(labels, dtype=np.float64)
    scores = np.asarray(scores, dtype=np.float64)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        metrics = evaluate_all(labels, scores)
    row = {
        "metrics": metrics,
        "n": int(len(labels)),
        "n_same_author": int(labels.sum()),
        "n_unanswered": int(np.sum(scores == UNANSWERED)),
        "ci95_trial_bootstrap": bootstrap_interval(labels, scores)
        if np.sum(scores != UNANSWERED)
        else None,
    }
    if extra:
        row.update(extra)
    return row


def write_answers(dataset: str, protocol: str, model: str, ids: Sequence[str], scores: Sequence[float]):
    target = ANSWERS_DIR / dataset / protocol / model
    target.mkdir(parents=True, exist_ok=True)
    with (target / "answers.jsonl").open("w", encoding="utf-8") as handle:
        for problem_id, value in zip(ids, scores):
            handle.write(json.dumps({"id": problem_id, "value": float(value)}) + "\n")


def write_truth(dataset: str, protocol: str, ids: Sequence[str], labels: Sequence[int]):
    target = ANSWERS_DIR / dataset / protocol
    target.mkdir(parents=True, exist_ok=True)
    with (target / "truth.jsonl").open("w", encoding="utf-8") as handle:
        for problem_id, label in zip(ids, labels):
            handle.write(json.dumps({"id": problem_id, "same": bool(label)}) + "\n")


def strict_protocol(dataset: str, pairs: Sequence[OfficialPair], verifiers: OriginalVerifiers) -> dict:
    """PAN's own format. Records the live reason each verifier abstains."""

    from original.fusion.peers import MIN_BASELINES
    from original.routers._shared import DEFAULT_MIN_BASELINE_SAMPLES

    first = pairs[0]
    one_known = verifiers.state(f"pan-strict-{first.pair_id}", [first.known], "known")
    verifiers.fused_reasons.clear()
    verifiers.fused(one_known, first.unknown, [])
    fused_reason = dict(verifiers.fused_reasons)
    reasons = {
        "deviation_score": (
            f"the live score route returns insufficient_baseline below "
            f"{DEFAULT_MIN_BASELINE_SAMPLES} approved baselines; a PAN pair gives one"
        ),
        "fused_score_v1": (
            f"needs {MIN_BASELINES} baselines and 8 same-tenant peers; "
            f"live entry point on one known text returned {sorted(fused_reason)}"
        ),
        "luar_style_fusion": (
            "its baseline-cohesion signals need at least two baseline documents and "
            "its peer-margin signals need an enrolled pool; a PAN pair gives neither"
        ),
    }
    if DEFAULT_MIN_BASELINE_SAMPLES <= 1 or MIN_BASELINES <= 1 or "hit" in fused_reason:
        raise RuntimeError("a verifier no longer abstains on one known text; revisit pair_strict")
    labels = [pair.label for pair in pairs]
    ids = [pair.pair_id for pair in pairs]
    write_truth(dataset, "pair_strict", ids, labels)
    models = {}
    for model, reason in reasons.items():
        scores = [UNANSWERED] * len(pairs)
        write_answers(dataset, "pair_strict", model, ids, scores)
        models[model] = summarize(labels, scores, extra={"abstain_reason": reason})
    return {"n_pairs": len(pairs), "models": models}


def split3_protocol(
    dataset: str,
    pairs: Sequence[OfficialPair],
    *,
    references: Sequence[StyleAuthor],
    reference_embedded: dict,
    fusion: LuarFusion,
    pair_cache: EmbeddingCache,
    verifiers: OriginalVerifiers,
) -> dict:
    labels = [pair.label for pair in pairs]
    ids = [pair.pair_id for pair in pairs]
    chunks = [split_known(pair.known) for pair in pairs]
    probe_texts = [pair.unknown for pair in pairs]

    def embedding(episode):
        vector = pair_cache.get(episode)
        if vector is None:
            _cache_only_embedder(episode)
        return vector

    luar_probability = fusion.calibrator.predict_proba(
        pair_luar_signals(
            fusion,
            claimed_episode=np.stack([embedding(parts) for parts in chunks]),
            claimed_documents=np.stack([[embedding((part,)) for part in parts] for parts in chunks]),
            probes=np.stack([embedding((text,)) for text in probe_texts]),
            claimed_texts=chunks,
            probe_texts=probe_texts,
            reference_episode=np.asarray(reference_embedded["baseline"]),
            reference_documents=np.asarray(reference_embedded["baseline_documents"]),
            reference_texts=[author.baselines for author in references],
        )[:, LUAR_COLUMNS]
    )[:, 1]

    peer_states = [
        verifiers.state(author.author_id, author.baselines, author.baseline_fandom)
        for author in references
    ]
    deviation, fused = [], []
    verifiers.fused_reasons.clear()
    started = time.perf_counter()
    for index, (pair, parts) in enumerate(zip(pairs, chunks)):
        state = verifiers.state(f"pan-known-{pair.pair_id}", parts, "known")
        deviation.append(verifiers.deviation(state, pair.unknown, pair.pair_id))
        fused.append(verifiers.fused(state, pair.unknown, peer_states))
        if (index + 1) % 1000 == 0:
            rate = (index + 1) / (time.perf_counter() - started)
            print(f"[score] {dataset} pair_split3 {index + 1}/{len(pairs)} ({rate:.1f}/s)", file=sys.stderr, flush=True)
    deviation = np.asarray(deviation)
    scores = {
        "deviation_score": 1.0 - deviation,
        "deviation_score_no_action_boundary": np.asarray([anchored_deviation_score(d) for d in deviation]),
        "fused_score_v1": np.asarray(fused),
        "luar_style_fusion": luar_probability,
    }
    write_truth(dataset, "pair_split3", ids, labels)
    models = {}
    for model, values in scores.items():
        write_answers(dataset, "pair_split3", model, ids, values)
        extra = {"fused_outcomes": dict(sorted(verifiers.fused_reasons.items()))} if model == "fused_score_v1" else None
        models[model] = summarize(labels, values, extra=extra)
    return {
        "n_pairs": len(pairs),
        "reference_pool": f"PAN 2020 calibration authors 1-{len(references)}",
        "models": models,
    }


def lock_protocol(
    dataset: str,
    authors: Sequence[StyleAuthor],
    embedded_partition,
    *,
    fusion: LuarFusion,
    verifiers: OriginalVerifiers,
) -> dict:
    trials, luar_probability = partition_trials(fusion, authors, embedded_partition)
    by_id = {author.author_id: author for author in authors}
    states = {
        author.author_id: verifiers.state(author.author_id, author.baselines, author.baseline_fandom)
        for author in authors
    }
    peers = list(states.values())
    labels, ids, deviation, fused = [], [], [], []
    verifiers.fused_reasons.clear()
    for trial in trials:
        probe = by_id[trial.source_author].probes[trial.probe_index]
        state = states[trial.target_author]
        identifier = f"{trial.target_author}|{trial.source_author}|probe-{trial.probe_index}"
        labels.append(trial.label)
        ids.append(identifier)
        deviation.append(verifiers.deviation(state, probe, identifier))
        fused.append(verifiers.fused(state, probe, peers))
    deviation = np.asarray(deviation)
    scores = {
        "deviation_score": 1.0 - deviation,
        "deviation_score_no_action_boundary": np.asarray([anchored_deviation_score(d) for d in deviation]),
        "fused_score_v1": np.asarray(fused),
        "luar_style_fusion": luar_probability,
    }
    write_truth(dataset, "lock_3baseline", ids, labels)
    models = {}
    for model, values in scores.items():
        write_answers(dataset, "lock_3baseline", model, ids, values)
        extra = {"fused_outcomes": dict(sorted(verifiers.fused_reasons.items()))} if model == "fused_score_v1" else None
        models[model] = summarize(labels, values, extra=extra)
    return {
        "n_trials": len(trials),
        "n_authors": len(authors),
        "probes_per_author": sorted({len(author.probes) for author in authors}),
        "peer_pool": "the other lock authors (closed set; fused_score_v1 takes 8 by sha256(author id))",
        "models": models,
    }


def reproduce_committed_luar(fusion, partitions, embedded) -> dict:
    """Check the refit fusion against the AUCs recorded when it was committed."""

    from sklearn.metrics import roc_auc_score

    checks = {}
    calibration_trials, calibration_probability = partition_trials(
        fusion, partitions["calibration"], embedded["calibration"]
    )
    for dataset, lock in (("pan20", "pan20_lock"), ("pan21", "pan21_lock")):
        committed = json.loads(DATASETS[dataset]["committed_lock"].read_text())
        if committed["selected_variant"] != LUAR_VARIANT:
            raise RuntimeError(f"{dataset}: committed variant is not {LUAR_VARIANT}")
        trials, probability = partition_trials(fusion, partitions[lock], embedded[lock])
        for split, rows, values, expected in (
            ("calibration", calibration_trials, calibration_probability, committed["metrics"]["calibration"]["auc"]),
            ("locked", trials, probability, committed["metrics"]["locked"]["auc"]),
        ):
            observed = round(float(roc_auc_score(_luar_labels(rows), values)), 6)
            checks[f"{dataset}_{split}"] = {"committed_auc": expected, "reproduced_auc": observed}
    worst = max(abs(row["committed_auc"] - row["reproduced_auc"]) for row in checks.values())
    if worst > REPRODUCTION_TOLERANCE:
        raise RuntimeError(f"LUAR fusion does not reproduce its committed AUCs: {checks}")
    return {"tolerance": REPRODUCTION_TOLERANCE, "max_abs_difference": round(worst, 6), "checks": checks}


# ── Stages ────────────────────────────────────────────────────────────────────


def sample_order(pairs: Sequence[OfficialPair]) -> list[OfficialPair]:
    """A fixed pseudo-random order, so any prefix is a uniform sample of pairs."""

    return sorted(pairs, key=lambda pair: _digest(f"pan-official-sample:{pair.pair_id}"))


def _evaluated_pairs(
    limit: int | None, partitions, sample: int | None = None
) -> tuple[dict[str, list[OfficialPair]], dict]:
    groups = pan20_author_groups()
    evaluated, reports = {}, {}
    for dataset, spec in DATASETS.items():
        pairs = load_official_pairs(spec["cache_dir"], limit=limit)
        kept, report = exclusions(dataset, pairs, groups, partitions)
        if dataset == "pan21":
            raws = {raw for names in groups.values() for raw in names}
            report["pan21_authors_in_any_pan20_group"] = sum(
                1 for pair in pairs for author in set(pair.authors) if author in raws
            )
        kept = sample_order(kept)
        if sample is not None and sample < len(kept):
            kept = kept[:sample]
            report["sampled_pairs"] = sample
        evaluated[dataset], reports[dataset] = kept, report
        print(f"[{dataset}] {report['evaluated_pairs']}/{report['official_pairs']} pairs kept", file=sys.stderr)
    return evaluated, reports


def stage_embed(limit: int | None) -> None:
    import torch
    import transformers

    from validation.verify.pan_luar_expert import _load_embedder

    partitions = load_partitions()
    embedder = _load_embedder()
    embed_all_partitions(partitions, embedder)
    evaluated, _ = _evaluated_pairs(limit, partitions)
    cache = EmbeddingCache(LUAR_PAIR_CACHE)
    for dataset in ("pan21", "pan20"):
        embed_episodes(pair_episodes(evaluated[dataset]), cache=cache, embedder=embedder)
    LUAR_PAIR_META.write_text(
        json.dumps(
            {
                "model_id": MODEL_ID,
                "model_revision": MODEL_REVISION,
                "max_tokens": MAX_TOKENS,
                "torch": torch.__version__,
                "transformers": transformers.__version__,
                "device": "mps" if torch.backends.mps.is_available() else "cpu",
            },
            indent=2,
        )
    )


def _feature_texts(partitions, evaluated) -> list[str]:
    texts = []
    for name in ("calibration", "pan20_lock", "pan21_lock"):
        for author in partitions[name]:
            texts.extend(author.baselines)
            texts.extend(author.probes)
    for pairs in evaluated.values():
        if pairs:
            texts.append(pairs[0].known)  # one-known state for the pair_strict check
    # Round-robin across datasets, each already in sample order, so a run
    # stopped part-way leaves the same prefix of every dataset extracted.
    for row in itertools.zip_longest(*evaluated.values()):
        for pair in row:
            if pair is not None:
                texts.extend(split_known(pair.known))
                texts.append(pair.unknown)
    return texts


def stage_features(limit: int | None, workers: int | None, sample: int | None = None) -> None:
    from validation.verify.feature_cache import extract_many

    partitions = load_partitions()
    evaluated, _ = _evaluated_pairs(limit, partitions, sample)
    extract_many(
        _feature_texts(partitions, evaluated),
        cache_path=FEATURE_CACHE,
        max_workers=workers,
        save_every=2000,
        progress_label="pan-official",
    )


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True).stdout.strip()


def stage_score(limit: int | None, output: Path, sample: int | None = None) -> dict:
    import sklearn
    import spacy

    from validation.verify.feature_cache import FeatureCache, extract_many

    partitions = load_partitions()
    evaluated, exclusion_reports = _evaluated_pairs(limit, partitions, sample)
    vectors = extract_many(
        _feature_texts(partitions, evaluated),
        cache=FeatureCache(FEATURE_CACHE),
        cache_path=FEATURE_CACHE,
        save_every=2000,
        progress_label="pan-official",
    )
    embedded = embed_all_partitions(partitions, _cache_only_embedder)
    fusion = fit_luar_fusion(partitions, embedded)
    reproduction = reproduce_committed_luar(fusion, partitions, embedded)
    print(f"[score] LUAR reproduction: {reproduction}", file=sys.stderr)

    references = reference_authors(partitions)
    reference_embedded = {
        "baseline": np.asarray(embedded["calibration"]["baseline"])[:N_REFERENCE_AUTHORS],
        "baseline_documents": np.asarray(embedded["calibration"]["baseline_documents"])[:N_REFERENCE_AUTHORS],
    }
    pair_cache = EmbeddingCache(LUAR_PAIR_CACHE)
    verifiers = OriginalVerifiers(vectors)

    datasets = {}
    for dataset, spec in DATASETS.items():
        pairs = evaluated[dataset]
        lock = f"{dataset}_lock"
        datasets[dataset] = {
            "source": {
                "zenodo_doi": ZENODO_DOI,
                "archive": spec["archive"],
                "archive_md5": spec["md5"],
                "description": spec["description"],
            },
            "exclusions": exclusion_reports[dataset],
            "protocols": {
                "pair_strict": strict_protocol(dataset, pairs, verifiers),
                "pair_split3": split3_protocol(
                    dataset,
                    pairs,
                    references=references,
                    reference_embedded=reference_embedded,
                    fusion=fusion,
                    pair_cache=pair_cache,
                    verifiers=verifiers,
                ),
                "lock_3baseline": lock_protocol(
                    dataset, partitions[lock], embedded[lock], fusion=fusion, verifiers=verifiers
                ),
            },
        }

    luar_meta = json.loads(LUAR_PAIR_META.read_text()) if LUAR_PAIR_META.exists() else None
    result = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "commit": _git("rev-parse", "HEAD"),
        "limit": limit,
        "sample": sample,
        "environment": {
            "python": platform.python_version(),
            "numpy": np.__version__,
            "scikit_learn": sklearn.__version__,
            "spacy": spacy.__version__,
            "scoring_flags": dict(sorted(ENV_LOCK.scoring_flags.items())),
            "model_hub_offline": ENV_LOCK.model_hub_offline,
            "luar_embedding": luar_meta,
        },
        "preprocessing": {
            "window": f"pan_corpus._fixed_window(text, {MAX_WORDS}, sha256(text)) on every document",
            "pair_known_text": "PAN pair[0]; pair[1] is the unknown text",
            "pair_split3": f"known window split into {SPLITS} contiguous near-equal word runs",
        },
        "score_mapping": {
            "deviation_score": "1 - deviation_score",
            "deviation_score_no_action_boundary": (
                f"piecewise-linear, monotone; deviation {NO_ACTION_UPPER} (live no_action "
                "upper bound) maps to 0.5"
            ),
            "fused_score_v1": "1 - probability_different_author; abstention = 0.5",
            "luar_style_fusion": "calibrated logistic P(same author)",
        },
        "luar_reproduction": reproduction,
        "published_targets": PUBLISHED_TARGETS,
        "datasets": datasets,
        "pan23": {
            "status": "not obtained",
            "reason": (
                "PAN 2023 cross-discourse data (Aston 100 Idiolects) is released only through a "
                "FoLD account and a per-user 'Request Item' data request; PAN 2022's Zenodo "
                "record 6337151 is restricted. Requires an owner decision and an account."
            ),
        },
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    return result


MODEL_LABELS = {
    "deviation_score": "deviation_score (live), PAN score = 1 - deviation",
    "deviation_score_no_action_boundary": "deviation_score (live), decision at no_action boundary 0.40",
    "fused_score_v1": "fused_score_v1 (committed artifact)",
    "luar_style_fusion": "LUAR + style interaction fusion (validation-only)",
}


def markdown_tables(result: dict) -> str:
    """One table per dataset and protocol, straight from the result JSON."""

    lines = []
    columns = ("auc", "c@1", "F1", "f_05_u", "brier", "overall", "overall_pan20_master")
    header = "| Verifier | n | unanswered | AUROC | c@1 | F1 | F0.5u | Brier (1-) | overall (5) | overall (4) | AUROC 95% CI |"
    for dataset, block in result["datasets"].items():
        target = result["published_targets"][dataset]
        for protocol, rows in block["protocols"].items():
            lines += ["", f"**{dataset} / {protocol}**", "", header, "|" + "---|" * header.count(" | ") + "---|"]
            for model, row in rows["models"].items():
                metrics = row["metrics"]
                interval = row["ci95_trial_bootstrap"]
                cells = [MODEL_LABELS[model], str(row["n"]), str(row["n_unanswered"])]
                cells += [f"{metrics[name]:.3f}" for name in columns]
                cells.append(f"{interval['auc'][0]:.3f}-{interval['auc'][1]:.3f}" if interval else "n/a")
                lines.append("| " + " | ".join(cells) + " |")
            published = [
                f"{target[name]:.4g}" if name in target else "" for name in ("auc", "c@1", "F1", "f_05_u", "brier")
            ]
            overall = f"{target['overall']:.4g}"
            five, four = (overall, "") if target["overall_measures"] == 5 else ("", overall)
            lines.append(
                f"| published: {target['system']} (PAN protocol, all pairs) | | | "
                + " | ".join(published)
                + f" | {five} | {four} | |"
            )
    return "\n".join(lines).lstrip()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("stage", choices=("embed", "features", "score", "report"))
    parser.add_argument("--limit", type=int, help="first N official pairs per dataset (smoke runs)")
    parser.add_argument("--workers", type=int, help="feature-extraction processes")
    parser.add_argument(
        "--sample", type=int, help="score a fixed pseudo-random N of the kept pairs per dataset"
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    if args.stage == "embed":
        stage_embed(args.limit)
    elif args.stage == "features":
        stage_features(args.limit, args.workers, args.sample)
    elif args.stage == "report":
        print(markdown_tables(json.loads(args.output.read_text())))
    else:
        result = stage_score(args.limit, args.output, args.sample)
        for dataset, block in result["datasets"].items():
            for protocol, rows in block["protocols"].items():
                for model, row in rows["models"].items():
                    print(dataset, protocol, model, row["metrics"], f"unanswered={row['n_unanswered']}")


if __name__ == "__main__":
    main()
