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
    never_claimed = sorted({e["label"] for e in entries} - set(claimed))

    # A class the model NEVER predicts is not "perfect precision" — it is an
    # unusable class, and it must drag the minimum to zero rather than drop
    # silently out of the dict the minimum is taken over. Without this, the
    # precision leg is passable by never claiming the hard class: abstaining
    # on one CLASS is not the same as abstaining overall, so the abstention
    # ceiling does not catch it.
    #
    # This mirrors derive.py's choose_threshold exactly (`minimum = 0.0 if
    # len(scored) < len(fit["classes"])`). The two must agree: a threshold
    # rejected at derivation for silencing a class cannot be one the gate
    # then accepts.
    min_precision = 0.0 if never_claimed else (min(per_class.values()) if per_class else 0.0)

    return {
        "n_holdout": len(entries),
        "n_claimed": sum(claimed.values()),
        "n_abstained": n_abstained,
        "abstention_rate": n_abstained / len(entries) if entries else 0.0,
        "per_class_precision": per_class,
        "per_class_claimed": dict(claimed),
        "min_precision": min_precision,
        "min_precision_zeroed_by_unclaimed": bool(never_claimed),
        "classes_never_claimed": never_claimed,
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
    0.014 to 0.528 on the same model. G5 in validation/calibration_gate.py
    already takes a majority over K seeded draws for exactly this reason;
    this is the same discipline.
    """
    # Featurise ONCE. Signals are a pure function of the text, so they are
    # identical across permutations — only the labels change. Re-extracting
    # them per draw cost ~287 document featurisations x n_permutations
    # (~5,700 for the default 20) inside both run_all() and the test suite.
    entries = derive.load_entries()
    corpus = _featurise_once(entries)
    if len(corpus["authors"]) == 0 or corpus["n_holdout"] == 0:
        return {
            "accuracy": None,
            "accuracy_per_draw": [],
            "chance": None,
            "n_classes": corpus["n_classes"],
            "n_permutations": 0,
            "n_holdout": corpus["n_holdout"],
            "n_authors_total": len(corpus["author_label"]),
            "mean_authors_retaining_true_label": 0.0,
            "permutation": {},
        }

    accuracies: list[float] = []
    permutations: list[dict] = []
    retained: list[int] = []
    for offset in range(max(0, n_permutations)):
        draw = _one_shuffled_draw(corpus, seed + offset)
        accuracies.append(draw["accuracy"])
        permutations.append(draw["permutation"])
        retained.append(draw["authors_retaining_true_label"])

    n_classes = corpus["n_classes"]
    return {
        "accuracy": float(np.mean(accuracies)) if accuracies else None,
        "accuracy_per_draw": accuracies,
        "chance": 1.0 / n_classes if n_classes else None,
        "n_classes": n_classes,
        "n_permutations": len(accuracies),
        "n_holdout": corpus["n_holdout"],
        # Authors that happened to keep their true label under the uniform
        # permutation. Expected, not a defect — see _permute_labels — but
        # reported so the small excess over chance is attributable.
        "n_authors_total": len(corpus["author_label"]),
        "mean_authors_retaining_true_label": (
            float(np.mean(retained)) if retained else 0.0
        ),
        "permutation": permutations[0] if permutations else {},
    }


# Cached across calls within a process, keyed on the labels file's digest so
# a re-derive or a relabel invalidates it. shuffled_control is called more
# than once per process — by the gate, and repeatedly by the test suite — and
# each call would otherwise re-extract signals from every labelled document.
_FEATURE_CACHE: dict[str, dict] = {}


def _labels_digest() -> str:
    import hashlib

    return hashlib.sha256(derive.LABELS.read_bytes()).hexdigest()


def _featurise_once(entries: list[dict]) -> dict:
    """Signals, author and split for every labelled document, extracted once."""
    key = _labels_digest()
    cached = _FEATURE_CACHE.get(key)
    if cached is not None:
        return cached
    X, y = derive.featurise(entries, allow_holdout=True)
    authors = np.array([e["author"] for e in entries])
    is_derivation = np.array([e["split"] == "derivation" for e in entries])
    corpus = {
        "X": X,
        "y": y,
        "authors": authors,
        "is_derivation": is_derivation,
        "n_classes": len(set(y.tolist())),
        "n_holdout": int((~is_derivation).sum()),
        "author_label": {e["author"]: e["label"] for e in entries},
    }
    _FEATURE_CACHE[key] = corpus
    return corpus


def _permute_labels(author_label: dict[str, str], rng: random.Random) -> tuple[dict, int]:
    """
    Assign each author a label drawn from the same multiset, uniformly at
    random. Returns the assignment and how many authors happened to keep
    their true label.

    UNIFORM, not deranged — and that is a deliberate correction of an earlier
    attempt at this. Forcing zero fixed points by construction (group by
    label, rotate by the largest group) maps whole true classes onto single
    wrong labels, so the permuted labelling is merely a RENAMING of the real
    classes and stays perfectly learnable. Measured: that construction sent
    the control to 0.621 against 0.333 chance, which reads as "the model
    still predicts" but is really "a consistent relabelling is trivially
    learnable". The null has to scramble authors of the same class onto
    DIFFERENT labels, which uniform assignment does and a block rotation
    does not.

    Fixed points are therefore expected and are not corrected for. Under a
    model that uses no genre information, accuracy sits at chance whether or
    not an author kept its label; under a model that does use genre, the few
    retained authors are predicted correctly and lift the mean slightly above
    chance. That small excess is a property of the null, not a flaw in it,
    and it is what the +0.10 margin on G8's control leg accommodates. The
    count is reported so the excess is attributable rather than mysterious.
    """
    authors = sorted(author_label)
    labels = [author_label[a] for a in authors]
    rng.shuffle(labels)
    assignment = dict(zip(authors, labels, strict=True))
    retained = sum(1 for a, lbl in assignment.items() if lbl == author_label[a])
    return assignment, retained


def _one_shuffled_draw(corpus: dict, seed: int) -> dict:
    """One permuted-label re-fit over the pre-extracted signal matrix."""
    rng = random.Random(seed)
    label_of, retained = _permute_labels(corpus["author_label"], rng)

    y_shuffled = np.array([label_of[a] for a in corpus["authors"]])
    train, test = corpus["is_derivation"], ~corpus["is_derivation"]

    fit = derive.fit_from_matrix(corpus["X"][train], y_shuffled[train])
    proba = derive.probabilities(fit, corpus["X"][test])
    predicted = np.asarray(fit["classes"])[proba.argmax(axis=1)]
    truth = y_shuffled[test]

    return {
        "accuracy": float((predicted == truth).mean()) if len(truth) else 0.0,
        "authors_retaining_true_label": retained,
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
