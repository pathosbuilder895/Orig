"""Group-aware calibration and fusion for independent authorship signals.

This is deliberately validation-only.  It produces out-of-fold probabilities
for honest evaluation and a final estimator for a separately locked test set;
it does not alter Original's production score or action.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

import numpy as np
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import GroupKFold
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler


EPS = 1e-6


@dataclass(frozen=True)
class Trial:
    """One verification trial. `label=1` means the claim is genuine."""

    trial_id: str
    author_id: str
    work_id: str
    label: int
    signals: Mapping[str, float | None]


@dataclass(frozen=True)
class FusionFit:
    signal_names: tuple[str, ...]
    oof_probability: np.ndarray
    estimator: Pipeline
    fold_by_trial: np.ndarray

    def predict(self, trials: Sequence[Trial]) -> np.ndarray:
        matrix = _matrix(trials, self.signal_names)
        return self.estimator.predict_proba(matrix)[:, 1]


@dataclass(frozen=True)
class CauseDecision:
    label: str
    probability: float
    margin: float
    abstained: bool


def _pipeline(seed: int) -> Pipeline:
    # Indicators are appended for every raw channel.  Median imputation then
    # cannot accidentally encode "detector unavailable" as a negative result.
    return Pipeline(
        [
            ("impute", SimpleImputer(strategy="median", add_indicator=True)),
            ("scale", StandardScaler()),
            (
                "logistic",
                LogisticRegression(
                    C=0.5,
                    class_weight="balanced",
                    max_iter=2000,
                    random_state=seed,
                ),
            ),
        ]
    )


def _matrix(trials: Sequence[Trial], names: Sequence[str]) -> np.ndarray:
    return np.asarray(
        [
            [np.nan if trial.signals.get(name) is None else float(trial.signals[name]) for name in names]
            for trial in trials
        ],
        dtype=np.float64,
    )


def assert_no_group_overlap(
    development: Sequence[Trial],
    locked: Sequence[Trial],
) -> None:
    """Reject author or work leakage across development and locked sets."""

    dev_authors = {t.author_id for t in development}
    locked_authors = {t.author_id for t in locked}
    author_overlap = dev_authors & locked_authors
    if author_overlap:
        raise ValueError(f"author leakage: {sorted(author_overlap)}")

    dev_works = {t.work_id for t in development}
    locked_works = {t.work_id for t in locked}
    work_overlap = dev_works & locked_works
    if work_overlap:
        raise ValueError(f"work leakage: {sorted(work_overlap)}")


def fit_grouped_fusion(
    trials: Sequence[Trial],
    *,
    signal_names: Sequence[str] | None = None,
    n_splits: int = 5,
    seed: int = 1729,
) -> FusionFit:
    """Fit regularized fusion and return author-disjoint OOF predictions.

    Base-expert values supplied here must themselves be out-of-fold whenever
    those experts were learned. The function refuses folds lacking either
    class, since probabilities from such a fold are not calibrated evidence.
    """

    if not trials:
        raise ValueError("need at least one trial")
    labels = np.asarray([t.label for t in trials], dtype=np.int8)
    if set(labels.tolist()) != {0, 1}:
        raise ValueError("trials must contain genuine and impostor labels")
    groups = np.asarray([t.author_id for t in trials], dtype=object)
    unique_groups = np.unique(groups)
    if len(unique_groups) < 2:
        raise ValueError("need at least two author groups")
    splits = min(int(n_splits), len(unique_groups))
    if splits < 2:
        raise ValueError("n_splits must be at least two")

    names = tuple(signal_names or sorted({name for t in trials for name in t.signals}))
    if not names:
        raise ValueError("need at least one signal")
    X = _matrix(trials, names)
    oof = np.full(len(trials), np.nan, dtype=np.float64)
    fold_by_trial = np.full(len(trials), -1, dtype=np.int16)

    for fold, (train_idx, test_idx) in enumerate(
        GroupKFold(n_splits=splits).split(X, labels, groups)
    ):
        if len(np.unique(labels[train_idx])) != 2:
            raise ValueError(f"fold {fold} training partition lacks a class")
        model = _pipeline(seed + fold)
        model.fit(X[train_idx], labels[train_idx])
        oof[test_idx] = model.predict_proba(X[test_idx])[:, 1]
        fold_by_trial[test_idx] = fold

    if np.isnan(oof).any() or (fold_by_trial < 0).any():
        raise RuntimeError("not every trial received an out-of-fold prediction")

    final = _pipeline(seed)
    final.fit(X, labels)
    return FusionFit(names, oof, final, fold_by_trial)


def cllr(labels: Sequence[int], probability_genuine: Sequence[float]) -> float:
    """Log-likelihood-ratio cost; 0 is perfect, 1 is uninformative.

    Calibrated posterior odds are likelihood ratios under equal class priors.
    """

    y = np.asarray(labels, dtype=np.int8)
    p = np.clip(np.asarray(probability_genuine, dtype=np.float64), EPS, 1 - EPS)
    if not np.any(y == 1) or not np.any(y == 0):
        raise ValueError("Cllr requires both hypotheses")
    lr = p / (1.0 - p)
    same = np.log2(1.0 + 1.0 / lr[y == 1]).mean()
    different = np.log2(1.0 + lr[y == 0]).mean()
    return float(0.5 * (same + different))


def select_cause(
    probabilities: Mapping[str, float],
    *,
    min_probability: float = 0.70,
    min_margin: float = 0.15,
) -> CauseDecision:
    """Choose an alternative cause only when confidence and margin suffice."""

    if not probabilities:
        return CauseDecision("unknown_other", 0.0, 0.0, True)
    ordered = sorted(
        ((str(label), float(value)) for label, value in probabilities.items()),
        key=lambda item: item[1],
        reverse=True,
    )
    best_label, best = ordered[0]
    second = ordered[1][1] if len(ordered) > 1 else 0.0
    margin = best - second
    abstain = best < min_probability or margin < min_margin
    return CauseDecision(
        "unknown_other" if abstain else best_label,
        best,
        margin,
        abstain,
    )
