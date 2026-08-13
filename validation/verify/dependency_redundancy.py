"""Post-hoc redundancy analysis for the Phase 5A dependency candidates.

**Descriptive only. This does NOT feed gate G-P5a**, whose criteria were
pre-registered and committed before any result was seen (see
``dependency_probe.py``). Nothing here can add a feature to the frozen list or
remove one from it. It exists because a pairwise ``|r| < 0.90`` test answers a
weaker question than the one that actually matters for Phase 5B's cost:

    pairwise:      "is this candidate a near-copy of one existing feature?"
    here:          "is this candidate predictable from the existing vector
                    *as a whole*?"

A feature can sit at r = 0.6 against every one of the 109 production features
individually and still be a near-exact linear combination of four of them, in
which case adding it buys the ensemble nothing while paying the full Phase 5B
cascade (a protected-surface edit to ``original/constants.py``, retraining the
committed AI-detector artifact that fails closed on feature-code mismatch, two
hard-coded dimension literals, and a baseline re-extraction).

Method
------
Cross-validated coefficient of determination, candidate regressed on existing
features. Two reference sets:

* ``tier5`` -- the seven tier-5 POS/shallow-syntax features, the nearest
  neighbours of these candidates in the production vector.
* ``full`` -- the whole 109-dim production vector, read from the existing
  content-addressed ``FeatureCache``; all 720 PAN development documents are
  already in it, so this costs nothing beyond the parse the probe needs anyway.
  Constant columns (tiers 17 and 18 are in ``DISABLED_FEATURE_GROUPS`` and sit
  at the 0.5 placeholder in every document) are dropped before fitting -- they
  carry no information and only make the design matrix rank-deficient.

Folds are **grouped by author** (author index modulo 5), so a candidate cannot
be "predicted" using the same author's other documents. In-sample R² with 109
predictors on 720 rows would be optimistic by construction; the cross-validated
number is what a new document would actually see. R² is reported on pooled
out-of-fold predictions and is clipped at 0 for reporting (a negative
out-of-fold R² means "worse than predicting the mean", i.e. not predictable).

Reading the number
------------------
High CV R² (say > 0.8) means the existing vector already contains this
candidate in disguise. Low CV R² means it is carrying something the vector
does not have -- which is a necessary condition for it to be worth adding, not
a sufficient one; a feature can be both novel and useless, which is what
G-P5a.1 and G-P5a.2 are for.

Determinism: no RNG; folds are a deterministic function of the sorted author
ordering.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

from validation.verify.dependency_probe import (
    DEFAULT_N_AUTHORS,
    REPO_ROOT,
    TIER5_CODES,
    build_pairs,
    extract_corpus,
    icc1,
    load_pan_documents,
    ranked_auc,
)
from validation.verify.dependency_signals import CANDIDATE_CODES

N_FOLDS = 5
DEFAULT_RESULTS_PATH = REPO_ROOT / "validation/verify/dependency_redundancy_results.json"


def _in_sample_r2(target: np.ndarray, predictors: np.ndarray) -> float:
    """Ordinary least squares R² on the same rows it was fitted on.

    This is the OPTIMISTIC bound: with 80-odd predictors it will absorb a
    slice of pure noise, so it overstates how redundant a candidate is. It is
    reported because the pair of bounds is more informative than either alone,
    and because if even the optimistic number is low the candidate is
    unambiguously carrying something new.
    """
    if predictors.size == 0 or target.std() == 0:
        return 0.0
    design = np.column_stack([predictors, np.ones(len(target))])
    coefficients, *_ = np.linalg.lstsq(design, target, rcond=None)
    residual = target - design @ coefficients
    ss_total = float(((target - target.mean()) ** 2).sum())
    if ss_total == 0:
        return 0.0
    return max(0.0, 1.0 - float((residual**2).sum()) / ss_total)


def _cv_r2(target: np.ndarray, predictors: np.ndarray, folds: np.ndarray) -> float:
    """Pooled out-of-fold R² with author-grouped folds.

    Ridge rather than plain OLS, over standardised predictors: with ~80
    non-constant production features against ~576 training rows, unpenalised
    least squares is badly enough conditioned that its out-of-fold error can
    exceed the variance of the target, which would report every candidate as
    "not predictable" for a numerical reason rather than a stylometric one --
    that is exactly what a first pass at 20 authors did. The penalty strength
    is chosen inside each training fold by ``RidgeCV``'s leave-one-out
    generalised CV over a fixed alpha grid, so no held-out row participates in
    choosing it and no seed is involved.
    """
    from sklearn.linear_model import RidgeCV
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler

    if predictors.size == 0 or target.std() == 0:
        return 0.0
    predicted = np.empty_like(target)
    for fold in np.unique(folds):
        test = folds == fold
        train = ~test
        if train.sum() <= 2 or test.sum() == 0:
            return float("nan")
        model = make_pipeline(
            StandardScaler(), RidgeCV(alphas=np.logspace(-3, 4, 15))
        )
        model.fit(predictors[train], target[train])
        predicted[test] = model.predict(predictors[test])
    ss_residual = float(((target - predicted) ** 2).sum())
    ss_total = float(((target - target.mean()) ** 2).sum())
    if ss_total == 0:
        return 0.0
    return max(0.0, 1.0 - ss_residual / ss_total)


def run(n_authors: int = DEFAULT_N_AUTHORS, results_path: Path = DEFAULT_RESULTS_PATH) -> dict:
    from validation.verify.feature_cache import FeatureCache, _text_key

    documents = load_pan_documents(n_authors)
    candidates, tier5_values = extract_corpus(documents, with_tier5=True, label="redundancy")

    cache = FeatureCache()
    missing = [d for d in documents if _text_key(d.text) not in cache.values]
    if missing:
        raise RuntimeError(
            f"{len(missing)} of {len(documents)} documents are absent from the 109-dim "
            "feature cache; run a pan_stack ablation first or extend the cache"
        )
    full_vectors = np.array([cache.values[_text_key(d.text)] for d in documents], dtype=np.float64)
    live = full_vectors.std(axis=0) > 0
    live_vectors = full_vectors[:, live]

    authors = sorted({d.author_id for d in documents})
    author_index = np.array([authors.index(d.author_id) for d in documents])
    folds = author_index % N_FOLDS

    tier5_matrix = np.column_stack([tier5_values[code] for code in TIER5_CODES])

    # ── Calibration baseline ────────────────────────────────────────────────
    # The number G-P5a.1 could not supply: what does an AUC of 0.60 on this
    # metric actually mean? Scoring the SEVEN FEATURES ALREADY IN THE VECTOR
    # through the identical pair construction answers it. If the existing
    # tier-5 features land in the same band, a candidate at 0.60 is an
    # ordinary stylometric feature, not a discovery -- and "ordinary" is not
    # a reason to pay the Phase 5B cascade.
    left, right, labels = build_pairs(documents)
    reference = {}
    for code in TIER5_CODES:
        values = tier5_values[code]
        reference[code] = {
            "auc": ranked_auc(labels, -np.abs(values[left] - values[right])),
            "icc1": icc1(values, author_index),
        }

    rows = {}
    for code in CANDIDATE_CODES:
        target = candidates[code]
        rows[code] = {
            "cv_r2_on_tier5": _cv_r2(target, tier5_matrix, folds),
            "cv_r2_on_full_vector": _cv_r2(target, live_vectors, folds),
            "in_sample_r2_on_full_vector": _in_sample_r2(target, live_vectors),
        }

    report = {
        "schema": "validation.dependency_redundancy.v1",
        "status": "descriptive only -- does not feed gate G-P5a",
        "n_documents": len(documents),
        "n_authors": len(authors),
        "n_live_production_features": int(live.sum()),
        "n_folds": N_FOLDS,
        "fold_rule": "author index modulo 5 over the sorted author ordering",
        "features": rows,
        "existing_tier5_reference": reference,
        "n_same_author_pairs": int((labels == 1).sum()),
        "n_different_author_pairs": int((labels == 0).sum()),
    }
    results_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    return report


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    report = run(n_authors=int(argv[0]) if argv else DEFAULT_N_AUTHORS)
    print()
    print(
        f"{'feature':<28}{'CV R^2 | tier5':>16}{'CV R^2 | 109-dim':>18}"
        f"{'in-sample R^2':>16}"
    )
    print("-" * 78)
    for code in CANDIDATE_CODES:
        row = report["features"][code]
        print(
            f"{code:<28}{row['cv_r2_on_tier5']:>16.3f}{row['cv_r2_on_full_vector']:>18.3f}"
            f"{row['in_sample_r2_on_full_vector']:>16.3f}"
        )
    print("-" * 78)
    print(
        f"{report['n_documents']} documents, {report['n_authors']} authors, "
        f"{report['n_live_production_features']} non-constant production features"
    )
    print("\ncalibration baseline -- features ALREADY in the vector, same metric:")
    print(f"{'existing tier-5 feature':<28}{'AUC':>8}{'ICC1':>8}")
    print("-" * 44)
    for code, row in sorted(
        report["existing_tier5_reference"].items(), key=lambda kv: -kv[1]["auc"]
    ):
        print(f"{code:<28}{row['auc']:>8.3f}{row['icc1']:>8.3f}")
    print("-" * 44)
    print(f"\nwrote {DEFAULT_RESULTS_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
