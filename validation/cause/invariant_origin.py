"""Domain-held, sign-constrained AI-origin fusion research harness.

Feature selection uses development domains only. A feature is retained only
when its AI-vs-human AUC direction agrees in every development domain and has a
minimum effect there. Retained features are oriented so larger always means
more AI-like, then fused with non-negative logistic weights. This prevents the
meta-model from exploiting a direction that is already known to be unstable in
its own development domains.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

import numpy as np
from scipy.optimize import minimize
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from original.constants import ALL_FEATURE_CODES
from validation.cause.padben import DIRECT_AI, HUMAN, HUMANIZED_AI, load_feature_matrix
from validation.cause.raid import _fpr_threshold, _load_raid_features


FEATURE_NAMES = (*ALL_FEATURE_CODES, "frozen_ai_likelihood")


@dataclass(frozen=True)
class OriginRows:
    X: np.ndarray
    labels: np.ndarray
    domains: np.ndarray
    sources: np.ndarray
    variants: np.ndarray


class NonNegativeLogistic:
    """Small L2-regularized logistic model with non-negative feature weights."""

    def __init__(self, l2: float = 0.25):
        self.l2 = l2
        self.intercept_: float | None = None
        self.coef_: np.ndarray | None = None

    def fit(self, X: np.ndarray, y: np.ndarray) -> "NonNegativeLogistic":
        X = np.asarray(X, dtype=np.float64)
        y = np.asarray(y, dtype=np.float64)

        def objective(theta: np.ndarray) -> tuple[float, np.ndarray]:
            intercept, weights = theta[0], theta[1:]
            logits = intercept + X @ weights
            probability = 1.0 / (1.0 + np.exp(-np.clip(logits, -40, 40)))
            loss = float(np.mean(np.logaddexp(0.0, logits) - y * logits))
            loss += self.l2 * float(weights @ weights) / 2.0
            residual = probability - y
            gradient = np.r_[residual.mean(), X.T @ residual / len(X) + self.l2 * weights]
            return loss, gradient

        initial = np.zeros(X.shape[1] + 1, dtype=np.float64)
        fitted = minimize(
            objective,
            initial,
            method="L-BFGS-B",
            jac=True,
            bounds=[(None, None), *[(0.0, None)] * X.shape[1]],
        )
        if not fitted.success:
            raise RuntimeError(f"non-negative logistic fit failed: {fitted.message}")
        self.intercept_ = float(fitted.x[0])
        self.coef_ = fitted.x[1:]
        return self

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        if self.coef_ is None or self.intercept_ is None:
            raise RuntimeError("model is not fitted")
        logits = self.intercept_ + np.asarray(X, dtype=np.float64) @ self.coef_
        positive = 1.0 / (1.0 + np.exp(-np.clip(logits, -40, 40)))
        return np.column_stack([1.0 - positive, positive])


def stable_feature_orientation(
    X: np.ndarray,
    labels: np.ndarray,
    domains: np.ndarray,
    *,
    min_effect: float = 0.02,
) -> tuple[np.ndarray, np.ndarray, list[dict]]:
    """Select features with consistent AUC direction in every input domain."""

    selected = []
    orientations = []
    audit = []
    for feature_index, name in enumerate(FEATURE_NAMES):
        aucs = []
        for domain in sorted(set(domains.tolist())):
            mask = domains == domain
            values = X[mask, feature_index]
            finite = np.isfinite(values)
            if set(labels[mask][finite].tolist()) != {False, True}:
                aucs = []
                break
            aucs.append(float(roc_auc_score(labels[mask][finite], values[finite])))
        if not aucs:
            continue
        signs = np.sign(np.asarray(aucs) - 0.5)
        stable = bool(np.all(signs > 0) or np.all(signs < 0))
        effect = min(abs(value - 0.5) for value in aucs)
        if stable and effect >= min_effect:
            selected.append(feature_index)
            orientations.append(1.0 if signs[0] > 0 else -1.0)
            audit.append(
                {
                    "feature": name,
                    "development_aucs": [round(value, 4) for value in aucs],
                    "orientation": "higher_is_ai" if signs[0] > 0 else "lower_is_ai",
                    "minimum_effect": round(effect, 4),
                }
            )
    if not selected:
        raise ValueError("no direction-stable features passed the development gate")
    return np.asarray(selected, dtype=np.int64), np.asarray(orientations), audit


def _source_bucket(source: str, held_domain: str) -> int:
    payload = f"invariant-origin:{held_domain}:{source}".encode()
    return int(hashlib.sha256(payload).hexdigest()[:8], 16) % 10


def _metrics(labels: np.ndarray, probability: np.ndarray, threshold: float, variants: np.ndarray) -> dict:
    selected = probability >= threshold
    human = ~labels
    true_positive = int((selected & labels).sum())
    result = {
        "n": len(labels),
        "auc": round(float(roc_auc_score(labels, probability)), 4),
        "human_fpr": round(float(selected[human].mean()), 4),
        "ai_tpr": round(float(selected[labels].mean()), 4),
        "precision_ai": round(true_positive / int(selected.sum()), 4) if selected.any() else None,
        "support": {"human": int(human.sum()), "ai": int(labels.sum())},
        "variant_tpr": {},
    }
    for variant in sorted(set(variants[labels].tolist())):
        mask = labels & (variants == variant)
        result["variant_tpr"][variant] = {
            "support": int(mask.sum()),
            "tpr": round(float(selected[mask].mean()), 4),
        }
    return result


def _local_human_operating_point(
    labels: np.ndarray,
    probability: np.ndarray,
    variants: np.ndarray,
    sources: np.ndarray,
    held_domain: str,
    target_human_fpr: float,
) -> dict:
    """Threshold on disjoint authenticated humans; evaluate on remaining sources."""

    local_bucket = np.asarray(
        [
            int(hashlib.sha256(f"local-human:{held_domain}:{source}".encode()).hexdigest()[:8], 16)
            % 10
            for source in sources
        ]
    )
    calibration_human = (~labels) & (local_bucket < 3)
    calibration_sources = set(sources[calibration_human].tolist())
    locked = ~np.isin(sources, list(calibration_sources))
    if not calibration_human.any() or set(labels[locked].tolist()) != {False, True}:
        raise ValueError(f"{held_domain}: local human calibration split lacks support")
    threshold = _fpr_threshold(probability[calibration_human], target_human_fpr)
    return {
        "threshold": round(threshold, 6),
        "calibration_human_support": int(calibration_human.sum()),
        "calibration_locked_source_overlap": len(
            calibration_sources & set(sources[locked].tolist())
        ),
        **_metrics(labels[locked], probability[locked], threshold, variants[locked]),
    }


def evaluate_domain_held(
    data: OriginRows,
    *,
    target_human_fpr: float = 0.01,
    min_effect: float = 0.02,
) -> dict:
    """Leave each complete corpus/domain out of all fitting and calibration."""

    folds = {}
    for held_domain in sorted(set(data.domains.tolist())):
        training_domain = data.domains != held_domain
        buckets = np.asarray([_source_bucket(source, held_domain) for source in data.sources])
        development = training_domain & (buckets < 8)
        calibration = training_domain & (buckets >= 8)
        locked = ~training_domain
        selected, orientation, audit = stable_feature_orientation(
            data.X[development],
            data.labels[development],
            data.domains[development],
            min_effect=min_effect,
        )
        imputer = SimpleImputer(strategy="median")
        scaler = StandardScaler()
        X_development = scaler.fit_transform(
            imputer.fit_transform(data.X[development][:, selected]) * orientation
        )
        X_calibration = scaler.transform(
            imputer.transform(data.X[calibration][:, selected]) * orientation
        )
        X_locked = scaler.transform(imputer.transform(data.X[locked][:, selected]) * orientation)
        constrained = NonNegativeLogistic().fit(X_development, data.labels[development])
        calibration_probability = constrained.predict_proba(X_calibration)[:, 1]
        threshold = _fpr_threshold(
            calibration_probability[~data.labels[calibration]], target_human_fpr
        )
        probability = constrained.predict_proba(X_locked)[:, 1]

        baseline = Pipeline(
            [
                ("impute", SimpleImputer(strategy="median", add_indicator=True)),
                ("scale", StandardScaler()),
                (
                    "logistic",
                    LogisticRegression(
                        C=0.25,
                        class_weight="balanced",
                        max_iter=2000,
                        random_state=1729,
                    ),
                ),
            ]
        )
        baseline.fit(data.X[development], data.labels[development])
        baseline_calibration = baseline.predict_proba(data.X[calibration])[:, 1]
        baseline_threshold = _fpr_threshold(
            baseline_calibration[~data.labels[calibration]], target_human_fpr
        )
        baseline_probability = baseline.predict_proba(data.X[locked])[:, 1]
        frozen_threshold = _fpr_threshold(
            data.X[calibration][~data.labels[calibration], -1], target_human_fpr
        )
        locked_labels = data.labels[locked]
        locked_variants = data.variants[locked]
        locked_sources = data.sources[locked]
        folds[held_domain] = {
            "n_development": int(development.sum()),
            "n_calibration": int(calibration.sum()),
            "n_locked": int(locked.sum()),
            "locked_source_overlap": len(
                set(data.sources[development | calibration].tolist())
                & set(data.sources[locked].tolist())
            ),
            "selected_feature_count": len(selected),
            "selected_features": audit,
            "positive_weights": {
                audit[index]["feature"]: round(float(weight), 6)
                for index, weight in enumerate(constrained.coef_)
                if weight > 1e-8
            },
            "constrained": {
                "threshold": round(threshold, 6),
                **_metrics(data.labels[locked], probability, threshold, data.variants[locked]),
            },
            "constrained_local_human_calibration": _local_human_operating_point(
                locked_labels,
                probability,
                locked_variants,
                locked_sources,
                held_domain,
                target_human_fpr,
            ),
            "unconstrained_all_features": {
                "threshold": round(baseline_threshold, 6),
                **_metrics(
                    data.labels[locked], baseline_probability, baseline_threshold, data.variants[locked]
                ),
            },
            "unconstrained_local_human_calibration": _local_human_operating_point(
                locked_labels,
                baseline_probability,
                locked_variants,
                locked_sources,
                held_domain,
                target_human_fpr,
            ),
            "frozen_ai_likelihood": {
                "threshold": round(frozen_threshold, 6),
                **_metrics(
                    data.labels[locked], data.X[locked, -1], frozen_threshold, data.variants[locked]
                ),
            },
            "frozen_local_human_calibration": _local_human_operating_point(
                locked_labels,
                data.X[locked, -1],
                locked_variants,
                locked_sources,
                held_domain,
                target_human_fpr,
            ),
        }
    return {
        "folds": folds,
        "split": (
            "entire-domain locked test; source-hashed 80/20 fitting/calibration in remaining "
            "domains; feature stability, orientation, imputation, scaling, weights, and "
            "thresholds use development/calibration domains only"
        ),
    }


def load_combined(
    raid_data: Path,
    padben_data: Path,
    *,
    output: Path,
    workers: int,
) -> OriginRows:
    raid_anchor = output.with_name(f"{output.stem}.raid.json")
    raid_rows, X_raid = _load_raid_features(raid_data, raid_anchor, workers)
    bundles, X_padben = load_feature_matrix(
        padben_data,
        cache_path=output.with_name(f"{output.stem}.padben.features.npz"),
        workers=workers,
    )
    raid_labels = np.asarray([row["model"] != "human" for row in raid_rows], dtype=bool)
    raid_domains = np.asarray(["raid:books"] * len(raid_rows), dtype=object)
    raid_sources = np.asarray(
        [str(row["id"] if row["attack"] == "none" else row["adv_source_id"]) for row in raid_rows],
        dtype=object,
    )
    raid_variants = np.asarray(
        ["human" if row["model"] == "human" else str(row["attack"]) for row in raid_rows],
        dtype=object,
    )
    padben_labels = np.asarray([bundle.cause != HUMAN for bundle in bundles], dtype=bool)
    padben_domains = np.asarray([f"padben:{bundle.source}" for bundle in bundles], dtype=object)
    padben_sources = np.asarray(
        [f"padben:{bundle.source}:{','.join(map(str, bundle.row_ids))}" for bundle in bundles],
        dtype=object,
    )
    padben_variants = np.asarray(
        [
            "human"
            if bundle.cause == HUMAN
            else "direct_ai"
            if bundle.cause == DIRECT_AI
            else bundle.variant
            for bundle in bundles
        ],
        dtype=object,
    )
    return OriginRows(
        X=np.vstack([X_raid, X_padben]),
        labels=np.r_[raid_labels, padben_labels],
        domains=np.r_[raid_domains, padben_domains],
        sources=np.r_[raid_sources, padben_sources],
        variants=np.r_[raid_variants, padben_variants],
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--raid-data", required=True, type=Path)
    parser.add_argument("--padben-data", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    data = load_combined(args.raid_data, args.padben_data, output=args.output, workers=args.workers)
    result = evaluate_domain_held(data)
    report = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "raid_input_sha256": hashlib.sha256(args.raid_data.read_bytes()).hexdigest(),
        "padben_input_sha256": hashlib.sha256(args.padben_data.read_bytes()).hexdigest(),
        "feature_count": data.X.shape[1],
        "evaluation": result,
        "warning": (
            "PADBen domains share one benchmark construction and paraphraser. Domain-held "
            "success would not substitute for a new humanizer-family locked test."
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({name: fold["constrained"] for name, fold in result["folds"].items()}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
