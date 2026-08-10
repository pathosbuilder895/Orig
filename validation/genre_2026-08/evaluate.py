"""
Evaluate the genre classifier on the author-disjoint hold-out, and run the
author-shuffled control.

Run:
    .venv/bin/python validation/genre_2026-08/evaluate.py

Two questions, and the second matters more than the first.

1. On documents by authors the model never saw, how often is a CLAIMED label
   right? Precision is reported per class and the minimum is the headline:
   an average lets one class sit at 0.4 while the mean clears the bar, and
   the consequence of a wrong label is per-class (creative_fiction mutes tier
   16, academic genres expand the anchor set).

2. Is this a genre classifier or an author classifier? The corpus confounds
   the two — every Dickens document is one author AND one genre. Permuting
   genre labels ACROSS authors and re-fitting answers it directly: if the
   model was keying on authorial style, it will still predict well under
   permuted labels, because the thing it learned did not depend on the label
   being genre in the first place.

Abstentions are not counted as errors. Precision is over claimed labels only
— punishing abstention would penalise exactly the honesty the design is
built on. The abstention RATE is reported alongside so that honesty cannot
be taken to extremes: a model that abstains on everything scores perfect
precision and classifies nothing.
"""

from __future__ import annotations

import random
import sys
from collections import Counter, defaultdict
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent.parent
sys.path.insert(0, str(_ROOT))

import numpy as np  # noqa: E402

from original.constants import GENRE_UNKNOWN  # noqa: E402
from original.context import genre_v2  # noqa: E402

sys.path.insert(0, str(_HERE))
import derive  # noqa: E402

SEED = 1729


def evaluate_holdout() -> dict:
    """Precision per claimed class on the author-disjoint hold-out."""
    entries = derive.load_entries("holdout")
    claimed: Counter = Counter()
    correct: Counter = Counter()
    n_abstained = 0

    for entry in entries:
        text = (_ROOT / entry["path"]).read_text(errors="ignore")
        predicted = genre_v2.predict(text)["primary"]
        if predicted == GENRE_UNKNOWN:
            n_abstained += 1
            continue
        claimed[predicted] += 1
        if predicted == entry["label"]:
            correct[predicted] += 1

    per_class = {cls: correct[cls] / claimed[cls] for cls in sorted(claimed)}
    return {
        "n_holdout": len(entries),
        "n_claimed": sum(claimed.values()),
        "n_abstained": n_abstained,
        "abstention_rate": n_abstained / len(entries) if entries else 0.0,
        "per_class_precision": per_class,
        "per_class_claimed": dict(claimed),
        "min_precision": min(per_class.values()) if per_class else 0.0,
        "classes_never_claimed": sorted(
            {e["label"] for e in entries} - set(claimed)
        ),
    }


def shuffled_control(seed: int = SEED, n_permutations: int = 20) -> dict:
    """
    Permute genre labels ACROSS authors, re-fit, and score. Averaged over
    `n_permutations` seeded draws.

    The permutation is applied per author, not per document: every document
    by one author keeps a single (wrong) label. A per-document shuffle would
    destroy the author/genre correlation being tested and make the control
    vacuous — the model would fail for the trivial reason that its training
    labels were internally inconsistent, telling us nothing about whether it
    keys on authors.

    AVERAGED, because a single permutation is one draw from a null
    distribution and its accuracy is noisy: a draw that happens to map most
    authors of one true class onto the same wrong label leaves real structure
    for the model to find, and scores above chance for a reason that has
    nothing to do with author-keying. Measured here, single draws ranged from
    0.06 to 0.35 on the same model. G5 in validation/calibration_gate.py
    already takes a majority over K seeded draws for exactly this reason;
    this is the same discipline.
    """
    accuracies: list[float] = []
    permutations: list[dict] = []
    for offset in range(n_permutations):
        result = _one_shuffled_draw(seed + offset)
        accuracies.append(result["accuracy"])
        permutations.append(result["permutation"])
    n_classes = result["n_classes"]
    return {
        "accuracy": float(np.mean(accuracies)),
        "accuracy_per_draw": accuracies,
        "chance": 1.0 / n_classes,
        "n_permutations": n_permutations,
        "n_holdout": result["n_holdout"],
        "permutation": permutations[0],
    }


def _one_shuffled_draw(seed: int) -> dict:
    """One permuted-label re-fit. See shuffled_control for why it is averaged."""
    entries = derive.load_entries()
    rng = random.Random(seed)

    by_author: dict[str, list[dict]] = defaultdict(list)
    for entry in entries:
        by_author[entry["author"]].append(entry)

    authors = sorted(by_author)
    original = [by_author[a][0]["label"] for a in authors]
    permuted = original[:]
    # Derange where possible so the control is not partly the real mapping.
    for _ in range(64):
        rng.shuffle(permuted)
        if all(p != o for p, o in zip(permuted, original, strict=True)):
            break
    label_of = dict(zip(authors, permuted, strict=True))

    shuffled = [
        {**entry, "label": label_of[entry["author"]]}
        for entry in entries
    ]
    derivation = [e for e in shuffled if e["split"] == "derivation"]
    holdout = [e for e in shuffled if e["split"] == "holdout"]

    fit = derive.fit_from_entries(derivation)
    X, y = derive.featurise(holdout, allow_holdout=True)
    proba = derive.probabilities(fit, X)
    predicted = np.asarray(fit["classes"])[proba.argmax(axis=1)]

    return {
        "accuracy": float((predicted == y).mean()) if len(y) else 0.0,
        "n_classes": len({e["label"] for e in entries}),
        "n_holdout": len(holdout),
        "permutation": label_of,
    }


def main() -> None:
    holdout = evaluate_holdout()
    print("=== hold-out (author-disjoint) ===")
    print(f"documents:       {holdout['n_holdout']}")
    print(f"claimed:         {holdout['n_claimed']}")
    print(f"abstained:       {holdout['n_abstained']} ({holdout['abstention_rate']:.1%})")
    print("per-class precision (claimed labels only):")
    for cls, value in sorted(holdout["per_class_precision"].items()):
        print(f"  {cls:20s} {value:.3f}  (n={holdout['per_class_claimed'][cls]})")
    if holdout["classes_never_claimed"]:
        print(f"  never claimed:  {holdout['classes_never_claimed']}")
    print(f"MINIMUM precision: {holdout['min_precision']:.3f}")

    control = shuffled_control()
    print("\n=== author-shuffled control ===")
    print(
        f"mean accuracy over {control['n_permutations']} permutations: "
        f"{control['accuracy']:.3f}   chance: {control['chance']:.3f}"
    )
    print(
        f"per-draw range: {min(control['accuracy_per_draw']):.3f} – "
        f"{max(control['accuracy_per_draw']):.3f}"
    )
    verdict = "collapses to chance (good)" if control["accuracy"] <= control["chance"] + 0.10 else (
        "STILL PREDICTS — the model may be keying on authors"
    )
    print(f"verdict: {verdict}")


if __name__ == "__main__":
    main()
