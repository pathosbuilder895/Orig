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
# G8 is a CONJUNCTION: precision >= 0.80 AND abstention <= 0.50. A selector
# that optimises one leg alone is misaligned with the criterion it will be
# judged by, and this one broke both ways before it was fixed — the smallest
# threshold clearing the floor left no transfer margin (derivation 0.820 ->
# hold-out 0.714), while the argmax of precision overshot an 0.80 bar and
# spent 58% abstention doing it. Selection now targets the conjunction:
# maximise the floored leg SUBJECT TO the ceilinged one, on derivation only.
_ABSTENTION_CEILING = 0.50


class HoldoutTouchedError(RuntimeError):
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
            raise HoldoutTouchedError(
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
    X, y = featurise(entries, allow_holdout=allow_holdout)
    return fit_from_matrix(X, y)


def fit_from_matrix(X: np.ndarray, y: np.ndarray) -> dict:
    """
    The actual fit, over an already-featurised matrix.

    Split out so the author-shuffled control can re-fit 20 permutations
    without re-extracting signals from every document 20 times: the signals
    are a pure function of the text and identical across permutations, only
    `y` changes. fit_from_entries delegates here, so there is still exactly
    ONE fitting path and the control cannot drift from the real derivation.
    """
    from sklearn.linear_model import LogisticRegression

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


def _out_of_fold_predictions(entries: list[dict]) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    Leave-one-AUTHOR-out predictions over the derivation split.

    Threshold selection on in-sample predictions is biased: the model has
    already seen every document it is being scored on, so precision looks
    better than it will be on anyone new, and the threshold chosen against it
    is systematically too low. Holding out one author at a time reproduces
    the thing the threshold has to survive — an unseen writer — using only
    derivation data. The real hold-out is still never touched.

    Leave-one-AUTHOR-out rather than leave-one-document-out for the same
    reason the top-level split is author-disjoint: a document-level fold
    leaves the same author's other documents in training, so the estimate
    inherits exactly the author-recognition shortcut it is meant to exclude.
    """
    authors = sorted({e["author"] for e in entries})
    truth: list[str] = []
    predicted: list[str] = []
    confidence: list[float] = []
    for held_out in authors:
        train = [e for e in entries if e["author"] != held_out]
        test = [e for e in entries if e["author"] == held_out]
        if not train or not test:
            continue
        if len({e["label"] for e in train}) < 2:
            continue  # a single-class fold cannot fit a classifier
        fold = fit_from_entries(train)
        X, y = featurise(test)
        proba = probabilities(fold, X)
        classes = np.asarray(fold["classes"])
        predicted.extend(classes[proba.argmax(axis=1)].tolist())
        confidence.extend(proba.max(axis=1).tolist())
        truth.extend(y.tolist())
    return np.asarray(truth), np.asarray(predicted), np.asarray(confidence)


def _precision_at(truth, predicted, confidence, threshold, classes):
    """Per-class out-of-fold precision at one threshold, plus its minimum.

    A class claimed nowhere scores None and drags the minimum to 0.0 — an
    unusable class is not perfect precision. Shared by the search below and
    by the re-measurement that follows a fallback, so the two cannot compute
    it differently.
    """
    claimed = confidence >= threshold
    per_class: dict[str, float | None] = {}
    for cls in classes:
        mask = claimed & (predicted == cls)
        per_class[cls] = float((truth[mask] == cls).mean()) if mask.sum() else None
    scored = [v for v in per_class.values() if v is not None]
    if not scored:
        return per_class, 0.0
    minimum = 0.0 if len(scored) < len(classes) else min(scored)
    return per_class, minimum


def choose_threshold(fit: dict, entries: list[dict]) -> tuple[float, dict]:
    """
    Smallest threshold at which every claimed class reaches the precision
    floor under LEAVE-ONE-AUTHOR-OUT cross-validation on the derivation
    split. Returns (threshold, per-class out-of-fold precision).

    Selected here and frozen. The hold-out never informs it.
    """
    truth, predicted, confidence = _out_of_fold_predictions(entries)

    # Maximise out-of-fold minimum per-class precision subject to staying
    # under the abstention ceiling. Ties break toward the SMALLER threshold,
    # since abstention rises monotonically and coverage the gate does not need
    # is still coverage lost.
    best_threshold = None
    best_per_class: dict[str, float | None] = {}
    best_min = -1.0
    fallback = (_THRESHOLD_GRID[0], {}, -1.0)
    for threshold in _THRESHOLD_GRID:
        claimed = confidence >= threshold
        if not claimed.any():
            break
        per_class, minimum = _precision_at(
            truth, predicted, confidence, threshold, fit["classes"]
        )
        if not any(v is not None for v in per_class.values()):
            continue
        if minimum > fallback[2]:
            fallback = (threshold, per_class, minimum)
        abstention = float(1.0 - claimed.mean())
        if abstention <= _ABSTENTION_CEILING and minimum > best_min:
            best_threshold, best_per_class, best_min = threshold, per_class, minimum

    if best_threshold is None:
        # Nothing stayed under the abstention ceiling. Report the best
        # available so the gate receives real numbers rather than nothing.
        best_threshold, best_per_class, best_min = fallback

    unclaimable = sorted(c for c, v in best_per_class.items() if v is None)
    meets_floor = not unclaimable and best_min >= _PRECISION_FLOOR

    # When the floor is unreachable, every threshold ties at minimum 0.0 and
    # the argmax above degenerates to the first grid point (0.25) — which
    # would ship a model claiming a label at 25% confidence. A criterion that
    # is not working must not be used to pick a number: fall back to the
    # conservative constant and say so in the artifact.
    threshold_source = "out-of-fold precision floor"
    if not meets_floor:
        from original.constants import GENRE_CONFIDENCE_MIN

        best_threshold = GENRE_CONFIDENCE_MIN
        threshold_source = "default constant (precision floor unreachable)"
        # Re-measure at the threshold actually being SHIPPED. Previously the
        # diagnostics kept the numbers from the rejected candidate, so the
        # artifact recorded confidence_min=0.55 beside a min_precision
        # measured somewhere else entirely, and G8 consumed the pair as if
        # they described one model.
        best_per_class, best_min = _precision_at(
            truth, predicted, confidence, best_threshold, fit["classes"]
        )
        unclaimable = sorted(c for c, v in best_per_class.items() if v is None)

    return best_threshold, {
        "threshold_source": threshold_source,
        "per_class": best_per_class,
        "min_precision": best_min,
        "unclaimable_classes": unclaimable,
        "meets_precision_floor": meets_floor,
        "precision_floor": _PRECISION_FLOOR,
    }


def build_artifact() -> dict:
    entries = load_entries("derivation")
    fit = fit_from_entries(entries)
    threshold, oof = choose_threshold(fit, entries)

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
        "out_of_fold": oof,
        "meets_precision_floor": oof["meets_precision_floor"],
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
    print(f"confidence_min: {artifact['confidence_min']}  "
          f"({artifact['out_of_fold']['threshold_source']})")
    oof = artifact["out_of_fold"]
    print("leave-one-author-out per-class precision (derivation):")
    for cls, value in sorted(oof["per_class"].items()):
        shown = f"{value:.3f}" if value is not None else "NEVER CLAIMED"
        print(f"  {cls:20s} {shown}")
    print(f"minimum:        {oof['min_precision']:.3f}  (floor {oof['precision_floor']})")
    print(f"meets floor:    {oof['meets_precision_floor']}")
    if oof["unclaimable_classes"]:
        print(f"UNCLAIMABLE:    {oof['unclaimable_classes']}")


if __name__ == "__main__":
    main()
