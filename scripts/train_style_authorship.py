#!/usr/bin/env python3
"""Build the pinned peer-aligned PAN style-authorship artifact."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import joblib
import sklearn
from sklearn.linear_model import LogisticRegression
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from original.style_authorship import (
    EXPECTED_SIGNAL_ORDER,
    SIGNATURE_VERSION,
    vocabulary_sha256,
)
from validation.verify.pan_corpus import ARCHIVE_MD5, ZENODO_DOI
from validation.verify.pan_style_expert import (
    SEED,
    _fit_representations,
    _labels,
    _score_partition,
    _threshold_at_fpr,
    load_author_partitions,
    peer_aligned_signals,
)


OUTPUT = Path("original/data/style_authorship_v1.joblib")


def build_artifact() -> dict:
    partitions = load_author_partitions(
        n_development=120,
        n_calibration=40,
        n_locked=12,
    )
    vectorizer, scaler = _fit_representations(partitions["development"])
    development = _score_partition(partitions["development"], vectorizer, scaler)
    calibration = _score_partition(partitions["calibration"], vectorizer, scaler)
    model = Pipeline(
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
    development_signals = peer_aligned_signals(development)
    model.fit(development_signals, _labels(development))
    calibration_probability = model.predict_proba(peer_aligned_signals(calibration))[:, 1]
    strict_threshold = _threshold_at_fpr(_labels(calibration), calibration_probability, 0.01)
    reference = development_signals[:8]
    return {
        "schema_version": 1,
        "signature_version": SIGNATURE_VERSION,
        "model_name": "peer-aligned-style-authorship-v1",
        "signal_order": EXPECTED_SIGNAL_ORDER,
        "character_vectorizer": vectorizer,
        "style_scaler": scaler,
        "calibrator": model,
        "strict_threshold": strict_threshold,
        "vocabulary_sha256": vocabulary_sha256(vectorizer),
        "reference_signals": reference,
        "reference_probabilities": model.predict_proba(reference)[:, 1],
        "provenance": {
            # Fixed to the locked experiment date so rebuilding identical data
            # and code does not change the artifact merely because wall time did.
            "trained_at": "2026-08-04T00:00:00+00:00",
            "dataset": "PAN 2020 authorship verification test",
            "zenodo_doi": ZENODO_DOI,
            "archive_md5": ARCHIVE_MD5,
            "development_authors": [a.author_id for a in partitions["development"]],
            "calibration_authors": [a.author_id for a in partitions["calibration"]],
            "sklearn_version": sklearn.__version__,
            "validation_reports": [
                "pan_style_peer_aligned_fresh40a.json",
                "pan_style_peer_aligned_fresh40b.json",
            ],
        },
    }


if __name__ == "__main__":
    artifact = build_artifact()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(artifact, OUTPUT, compress=3)
    print(json.dumps({"path": str(OUTPUT), "threshold": artifact["strict_threshold"], "vocabulary_sha256": artifact["vocabulary_sha256"]}, indent=2))
