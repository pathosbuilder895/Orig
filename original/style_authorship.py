"""Peer-aligned, report-only modern authorship consistency expert.

The module is imported only when ``STYLE_AUTHORSHIP_ENABLED=1``.  It never
changes Original's quantum score, recommendation, or action. Missing text,
cohort support, stale artifacts, and inference errors all return ``None``.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import threading
import warnings
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from scipy.sparse import csr_matrix

from .principal import tenant_of
from .quantum.state import StudentState

log = logging.getLogger(__name__)
DEFAULT_ARTIFACT_PATH = Path(__file__).parent / "data" / "style_authorship_v1.joblib"
EXPECTED_SCHEMA_VERSION = 1
SIGNATURE_VERSION = 1
EXPECTED_SIGNAL_ORDER = [
    "character",
    "content_reduced",
    "peer_z_character",
    "peer_z_content_reduced",
]
MIN_BASELINES = 3
MIN_PEER_PROFILES = 10
MIN_WORDS = 300

WORD_RE = re.compile(r"[A-Za-z]+(?:'[A-Za-z]+)?")
SENTENCE_RE = re.compile(r"[.!?]+")
FUNCTION_WORDS = tuple(
    """a about above after again against all am an and any are aren't as at be because
    been before being below between both but by can can't cannot could couldn't did didn't
    do does doesn't doing don't down during each few for from further had hadn't has hasn't
    have haven't having he he'd he'll he's her here here's hers herself him himself his how
    how's i i'd i'll i'm i've if in into is isn't it it's its itself just me more most mustn't
    my myself no nor not of off on once only or other ought our ours ourselves out over own
    same shall shan't she she'd she'll she's should shouldn't so some such than that that's
    the their theirs them themselves then there there's these they they'd they'll they're
    they've this those through to too under until up very was wasn't we we'd we'll we're we've
    were weren't what what's when when's where where's which while who who's whom why why's
    will with won't would wouldn't you you'd you'll you're you've your yours yourself
    yourselves""".split()
)
PUNCTUATION = tuple(",.;:!?—-()[]{}\"'…")


@dataclass(frozen=True)
class StyleAuthorshipResult:
    probability_same_author: float
    band: str
    consistent_at_strict_threshold: bool
    strict_threshold: float
    peer_profiles: int
    baseline_samples: int
    model_version: str
    trained_on: str


def content_reduced_signature(text: str) -> np.ndarray:
    """Fixed function-word, punctuation, word-length, and rhythm signature."""
    matched = WORD_RE.findall(text)
    words = [word.lower() for word in matched]
    word_count = max(len(words), 1)
    counts = Counter(words)
    function_rates = [counts[word] / word_count for word in FUNCTION_WORDS]
    char_count = max(len(text), 1)
    punctuation_rates = [text.count(mark) / char_count for mark in PUNCTUATION]
    length_hist = np.zeros(15, dtype=np.float64)
    for word in words:
        length_hist[min(len(word), 15) - 1] += 1
    length_hist /= word_count
    sentences = [piece for piece in SENTENCE_RE.split(text) if piece.strip()]
    sentence_lengths = np.asarray(
        [len(WORD_RE.findall(piece)) for piece in sentences], dtype=np.float64
    )
    if sentence_lengths.size:
        rhythm = [
            float(np.mean(sentence_lengths)) / 100.0,
            float(np.std(sentence_lengths)) / 100.0,
            float(np.median(sentence_lengths)) / 100.0,
            float(np.percentile(sentence_lengths, 90)) / 100.0,
        ]
    else:
        rhythm = [0.0] * 4
    casing = [
        sum(1 for word in matched if word.isupper()) / word_count,
        sum(1 for word in matched if word[:1].isupper()) / word_count,
    ]
    return np.asarray(function_rates + punctuation_rates + length_hist.tolist() + rhythm + casing)


def vocabulary_sha256(vectorizer) -> str:
    payload = json.dumps(
        sorted((str(token), int(index)) for token, index in vectorizer.vocabulary_.items()),
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


_UNLOADED, _READY, _FAILED = 0, 1, 2
_state = _UNLOADED
_artifact: dict | None = None
_lock = threading.Lock()


def _artifact_path() -> Path:
    override = os.environ.get("STYLE_AUTHORSHIP_MODEL_PATH", "").strip()
    return Path(override) if override else DEFAULT_ARTIFACT_PATH


def _fail(reason: str) -> None:
    global _state, _artifact
    log.warning("Style-authorship expert disabled: %s (path=%s)", reason, _artifact_path())
    _state, _artifact = _FAILED, None


def _load_artifact() -> None:
    global _state, _artifact
    try:
        import joblib

        path = _artifact_path()
        if not path.exists():
            _fail("artifact not found")
            return
        with warnings.catch_warnings():
            try:
                from sklearn.exceptions import InconsistentVersionWarning

                warnings.simplefilter("error", InconsistentVersionWarning)
            except ImportError:
                pass
            artifact = joblib.load(path)
        if (
            not isinstance(artifact, dict)
            or artifact.get("schema_version") != EXPECTED_SCHEMA_VERSION
        ):
            _fail("artifact schema mismatch")
            return
        if artifact.get("signature_version") != SIGNATURE_VERSION:
            _fail("content-reduced signature version mismatch")
            return
        if artifact.get("signal_order") != EXPECTED_SIGNAL_ORDER:
            _fail("signal order mismatch")
            return
        if vocabulary_sha256(artifact["character_vectorizer"]) != artifact.get("vocabulary_sha256"):
            _fail("character vocabulary checksum mismatch")
            return
        reference = np.asarray(artifact["reference_signals"], dtype=np.float64)
        expected = np.asarray(artifact["reference_probabilities"], dtype=np.float64)
        got = artifact["calibrator"].predict_proba(reference)[:, 1]
        if float(np.max(np.abs(got - expected))) > 1e-8:
            _fail("reference prediction drift")
            return
        threshold = float(artifact["strict_threshold"])
        if not 0.5 < threshold < 1.0:
            _fail("invalid strict threshold")
            return
        _artifact, _state = artifact, _READY
    except Exception as exc:  # noqa: BLE001
        _fail(f"{type(exc).__name__}: {exc}")


def _ensure_loaded() -> bool:
    global _state
    if _state == _READY:
        return True
    if _state == _FAILED:
        return False
    with _lock:
        if _state == _UNLOADED:
            _load_artifact()
    return _state == _READY


def warm() -> bool:
    return _ensure_loaded()


def reset_for_tests() -> None:
    global _state, _artifact
    with _lock:
        _state, _artifact = _UNLOADED, None


def _authenticated_texts(state: StudentState) -> list[str]:
    texts = [
        sample.text
        for sample in state.samples
        if sample.auth_weight > 0
        and isinstance(sample.text, str)
        and len(sample.text.split()) >= MIN_WORDS
    ]
    return texts[-MIN_BASELINES:]


def _profile(texts: list[str], artifact: dict) -> tuple[csr_matrix, np.ndarray]:
    char = artifact["character_vectorizer"].transform(texts)
    centroid = csr_matrix(char.mean(axis=0))
    norm = float(np.sqrt(centroid.multiply(centroid).sum()))
    centroid = centroid / max(norm, 1e-12)
    style = artifact["style_scaler"].transform(
        np.stack([content_reduced_signature(text) for text in texts])
    )
    return centroid, style.mean(axis=0)


def predict_style_authorship(
    text: str,
    claimed_state: StudentState,
    states: Iterable[StudentState],
) -> StyleAuthorshipResult | None:
    """Return same-author consistency evidence or abstain with ``None``."""
    try:
        if len(text.split()) < MIN_WORDS or not _ensure_loaded():
            return None
        artifact = _artifact
        assert artifact is not None
        claimed_texts = _authenticated_texts(claimed_state)
        if len(claimed_texts) < MIN_BASELINES:
            return None
        claimed_tenant = tenant_of(claimed_state.student_id)
        peers = []
        for state in states:
            if (
                state.student_id == claimed_state.student_id
                or tenant_of(state.student_id) != claimed_tenant
            ):
                continue
            peer_texts = _authenticated_texts(state)
            if len(peer_texts) >= MIN_BASELINES:
                peers.append(peer_texts)
        if len(peers) < MIN_PEER_PROFILES:
            return None

        claimed_char, claimed_style = _profile(claimed_texts, artifact)
        peer_profiles = [_profile(peer_texts, artifact) for peer_texts in peers]
        probe_char = artifact["character_vectorizer"].transform([text])
        probe_style = artifact["style_scaler"].transform(
            content_reduced_signature(text).reshape(1, -1)
        )[0]
        raw_character = float((probe_char @ claimed_char.T).toarray()[0, 0])
        raw_style = -float(np.mean(np.abs(probe_style - claimed_style)))
        peer_character = np.asarray(
            [float((probe_char @ profile[0].T).toarray()[0, 0]) for profile in peer_profiles]
        )
        peer_style = np.asarray(
            [-float(np.mean(np.abs(probe_style - profile[1]))) for profile in peer_profiles]
        )
        aligned_character = (raw_character - peer_character.mean()) / max(
            peer_character.std(), 1e-9
        )
        aligned_style = (raw_style - peer_style.mean()) / max(peer_style.std(), 1e-9)
        signals = np.asarray(
            [[raw_character, raw_style, aligned_character, aligned_style]], dtype=np.float64
        )
        probability = float(artifact["calibrator"].predict_proba(signals)[0, 1])
        threshold = float(artifact["strict_threshold"])
        consistent = bool(probability >= threshold)
        provenance = artifact.get("provenance", {})
        return StyleAuthorshipResult(
            probability_same_author=round(probability, 4),
            band="consistent" if consistent else "inconclusive",
            consistent_at_strict_threshold=consistent,
            strict_threshold=round(threshold, 4),
            peer_profiles=len(peers),
            baseline_samples=len(claimed_texts),
            model_version=f"v{artifact['schema_version']}",
            trained_on=provenance.get("dataset", "PAN 2020 authorship verification"),
        )
    except Exception as exc:  # noqa: BLE001
        log.warning(
            "Style-authorship prediction failed (%s: %s); returning None", type(exc).__name__, exc
        )
        return None
