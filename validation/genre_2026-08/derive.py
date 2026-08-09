"""
Derive the genre classifier from the hand-labelled corpus.

Run:
    .venv/bin/python validation/genre_2026-08/derive.py

Reads the DERIVATION split only. The hold-out is never opened here — there is
an explicit guard that raises if a hold-out path is touched, because "I was
careful" is not a property anyone can check later.

Writes original/data/genre_model_v1.json: a multinomial logistic regression
as plain coefficients plus a standardiser, NOT a pickled estimator.
Deliberately, and for three reasons: the artifact is committed to git and a
pickle there is a code-execution surface; inference becomes pure numpy, so
the resolver gains no sklearn runtime dependency (sklearn is absent from the
base requirements.txt); and coefficients stay diffable in review.

scikit-learn is used HERE and nowhere else in the genre path.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent.parent
sys.path.insert(0, str(_ROOT))

import numpy as np  # noqa: E402

from original.context.genre_v2 import SIGNAL_ORDER, signal_vector  # noqa: E402

LABELS = _HERE / "labels.json"
CODEBOOK = _HERE / "CODEBOOK.md"
OUT = _ROOT / "original" / "data" / "genre_model_v1.json"

SCHEMA_VERSION = 1
SEED = 1729

# Candidate abstention thresholds, scanned low to high. The chosen value is
# the SMALLEST that reaches the per-class precision floor on the derivation
# split — smallest because every increment buys precision with abstention,
# and abstaining more than necessary is its own failure.
_THRESHOLD_GRID = [round(0.25 + 0.01 * i, 2) for i in range(71)]  # 0.25 .. 0.95
_PRECISION_FLOOR = 0.80


class HoldoutTouched(RuntimeError):
    """Raised if derivation reads a hold-out document."""


def load_entries(split: str | None = None) -> list[dict]:
    payload = json.loads(LABELS.read_text())
    expected = hashlib.sha256(CODEBOOK.read_bytes()).hexdigest()
    if payload.get("codebook_sha256") != expected:
        raise RuntimeError(
            "labels.json was written against a different CODEBOOK.md. Re-examine "
            "the labels against the current definitions rather than re-deriving."
        )
    entries = payload["entries"]
    if split is not None:
        entries = [e for e in entries if e["split"] == split]
    return entries


def featurise(entries: list[dict], *, allow_holdout: bool = False):
    """Signal matrix and label vector for `entries`."""
    rows, labels = [], []
    for entry in entries:
        if not allow_holdout and entry["split"] == "holdout":
            raise HoldoutTouched(
                f"derivation tried to read a hold-out document: {entry['path']}"
            )
        text = (_ROOT / entry["path"]).read_text(errors="ignore")
        rows.append(signal_vector(text))
        labels.append(entry["label"])
    return np.asarray(rows, dtype=np.float64), np.asarray(labels)


def fit_from_entries(entries: list[dict], *, allow_holdout: bool = False) -> dict:
    """
    Fit the standardiser and the multinomial, returning a plain dict.

    Exposed so the author-shuffled control (validation/genre_2026-08/
    evaluate.py) can re-fit on permuted labels through exactly this path
    rather than a parallel implementation that might differ.
    """
    from sklearn.linear_model import LogisticRegression

    X, y = featurise(entries, allow_holdout=allow_holdout)
    mean = X.mean(axis=0)
    scale = X.std(axis=0)
    # A zero-variance column would divide by zero and, worse, silently make
    # its coefficient meaningless. 1.0 leaves the column as a constant offset.
    scale[scale <= 0.0] = 1.0
    Xs = (X - mean) / scale

    model = LogisticRegression(
        max_iter=5000,
        class_weight="balanced",  # creative_fiction has 12 documents to scholarly_essay's 40
        random_state=SEED,
    )
    model.fit(Xs, y)
    return {
        "classes": [str(c) for c in model.classes_],
        "mean": mean.tolist(),
        "scale": scale.tolist(),
        "coef": model.coef_.tolist(),
        "intercept": model.intercept_.tolist(),
        "_X": X,
        "_y": y,
    }


def probabilities(fit: dict, X: np.ndarray) -> np.ndarray:
    """Softmax over standardised inputs — the exact arithmetic inference uses."""
    Xs = (X - np.asarray(fit["mean"])) / np.asarray(fit["scale"])
    z = Xs @ np.asarray(fit["coef"]).T + np.asarray(fit["intercept"])
    z = z - z.max(axis=1, keepdims=True)
    e = np.exp(z)
    return e / e.sum(axis=1, keepdims=True)


def choose_threshold(fit: dict) -> tuple[float, dict]:
    """
    Smallest threshold on the DERIVATION split at which every claimed class
    reaches the precision floor. Returns (threshold, per-class precision).

    Selected here and frozen; the hold-out never informs it.
    """
    proba = probabilities(fit, fit["_X"])
    classes = np.asarray(fit["classes"])
    predicted = classes[proba.argmax(axis=1)]
    confidence = proba.max(axis=1)
    truth = fit["_y"]

    best: tuple[float, dict] | None = None
    for threshold in _THRESHOLD_GRID:
        claimed = confidence >= threshold
        if not claimed.any():
            break
        per_class = {}
        for cls in fit["classes"]:
            mask = claimed & (predicted == cls)
            if mask.sum() == 0:
                per_class[cls] = None
                continue
            per_class[cls] = float((truth[mask] == cls).mean())
        scored = [v for v in per_class.values() if v is not None]
        # Every class must still be claimed somewhere, and all must clear the
        # floor. A threshold that silences a class entirely is not a pass.
        if len(scored) == len(fit["classes"]) and min(scored) >= _PRECISION_FLOOR:
            best = (threshold, per_class)
            break
    if best is None:
        raise RuntimeError(
            "no threshold on the derivation split reaches a per-class precision "
            f"of {_PRECISION_FLOOR}. The signals do not separate these classes; "
            "do not lower the floor to manufacture a pass."
        )
    return best


def build_artifact() -> dict:
    entries = load_entries("derivation")
    fit = fit_from_entries(entries)
    threshold, per_class = choose_threshold(fit)

    # Reference rows for drift detection: the first derivation document of
    # each of the three largest classes, chosen deterministically.
    from collections import Counter

    order = [c for c, _ in Counter(fit["_y"].tolist()).most_common(3)]
    reference_idx = [int(np.where(fit["_y"] == cls)[0][0]) for cls in order]
    reference_signals = fit["_X"][reference_idx]
    reference_probabilities = probabilities(fit, reference_signals)

    return {
        "schema_version": SCHEMA_VERSION,
        "signal_order": list(SIGNAL_ORDER),
        "classes": fit["classes"],
        "mean": fit["mean"],
        "scale": fit["scale"],
        "coef": fit["coef"],
        "intercept": fit["intercept"],
        "confidence_min": threshold,
        "derivation_per_class_precision": per_class,
        "n_derivation": len(entries),
        "reference_signals": reference_signals.tolist(),
        "reference_probabilities": reference_probabilities.tolist(),
        "codebook_sha256": hashlib.sha256(CODEBOOK.read_bytes()).hexdigest(),
        "labels_sha256": hashlib.sha256(LABELS.read_bytes()).hexdigest(),
    }


def main() -> None:
    artifact = build_artifact()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(artifact, indent=1) + "\n")
    print(f"wrote {OUT.relative_to(_ROOT)}")
    print(f"classes:        {artifact['classes']}")
    print(f"n_derivation:   {artifact['n_derivation']}")
    print(f"confidence_min: {artifact['confidence_min']}")
    print("derivation per-class precision:")
    for cls, value in sorted(artifact["derivation_per_class_precision"].items()):
        print(f"  {cls:20s} {value:.3f}")


if __name__ == "__main__":
    main()
