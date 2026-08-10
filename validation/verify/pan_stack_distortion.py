"""Does a topic-masked (POSNoise) distortion channel improve the pan_stack
same-author fusion?

Same discipline as pan_stack_delta.py / pan_stack_lambdag.py /
pan_stack_compression.py: identical development / calibration / locked author
split, identical base signals (raw/peer probability + LUAR-family
character/content similarity), and the identical fusion helper
(``fit_grouped_fusion``, fixed C=0.5). Only the added signal set differs
between arms.

    .venv/bin/python -m validation.verify.pan_stack_distortion


PRE-REGISTRATION -- written and committed before any locked number was read
=========================================================================

Gate **G-P2** as specified in the phase plan has two halves:

(a) *Primary, cross-genre.* "On the crossgenre harness, the distorted
    channel's same-author/cross-genre FPR must beat the raw channel's at
    matched TPR." This is the criterion that actually tests the phase's
    hypothesis, because only that corpus has the genre shift the channel is
    meant to survive.

(b) *Guard, PAN.* "On PAN, stacked cllr must not regress."

Half (a) **cannot be evaluated in this repository**: the Lewis/Chesterton
crossgenre corpus is not committed (copyright) and
``validation/genre_crossgenre_2026-08/raw/`` is absent. It is not merely
unrun; there is no lawful way to run it here.
``validation/genre_crossgenre_2026-08/distort_corpus.py`` is written and
committed so that half (a) is a single command for anyone who has the corpus.

This module therefore evaluates half (b) only, and reports G-P2 as
**uninformative** rather than as a pass, following the repo's three-valued
gate convention (``validation/calibration_gate.py``): a gate whose criterion
is unreachable at the current corpus never yields a pass. Passing the guard
is *not* evidence the channel works; it only means the channel did no harm on
a corpus that does not contain the failure mode being targeted.

The pre-registered arm for half (b), fixed before any locked partition was
scored, is:

    with_distorted_divergence  =  BASE_SIGNALS + ("distorted_divergence",)

evaluated against ``base_only`` on the locked partition, with the criterion:

    locked stacked cllr must not regress   (delta_cllr <= 0.0)

Two supporting quantities are reported alongside it and are **not** part of
the gate: delta AUC and delta recall @ 1% FPR. They are reported because a
cllr-only guard is passed trivially by an inert signal, and a reader needs to
see whether the channel moved anything at all.

Every other arm below (``with_distorted_delta``, ``with_distortion_all``) is
**exploratory and unclaimed**. Phase 1's lesson is explicit on this point: its
unregistered zlib-NCD arm cleared all three of that phase's bars and was
deliberately not claimed, because a criterion applied after seeing locked
results is not a held-out criterion. The same line holds here. If an
unregistered arm looks good, it needs a fresh pre-registration against a
locked set that has not been read by this study.

Hyperparameters (character-LM order, peer-pool size) are selected on the
``fusion_development`` partition alone -- see ``HYPERPARAMETER_PROVENANCE``.
The locked partition is read once, at scoring time, and never used to choose
anything.
"""

from __future__ import annotations

from validation.benchmark.reproducibility import lock_environment

ENV_LOCK = lock_environment()

import dataclasses
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path

import numpy as np

from validation.stacked.fusion import assert_no_group_overlap, fit_grouped_fusion
from validation.verify.distortion_signals import (
    SIGNAL_NAMES,
    abstention_rate,
    distortion_trial_signals,
)
from validation.verify.pan_corpus import DEFAULT_CACHE
from validation.verify.pan_stack import _summary, combine_trials, original_trial_signals
from validation.verify.pan_style_expert import (
    SEED,
    _fit_representations,
    _score_partition,
    _threshold_at_fpr,
    load_author_partitions,
)

BASE_SIGNALS = (
    "raw_probability",
    "peer_probability",
    "character_similarity",
    "content_reduced_similarity",
)

#: The single pre-registered gate arm for G-P2 half (b). Do not edit this to
#: match a result -- that is the whole point of it being a module constant.
GATE_ARM = "with_distorted_divergence"
GATE_SIGNALS = BASE_SIGNALS + ("distorted_divergence",)

HYPERPARAMETER_PROVENANCE = (
    "order=4, peer_pool_chars=200000, inherited from Phase 1's "
    "fusion_development selection (validation/verify/pan_stack_compression.py) "
    "and re-checked on the same fusion_development partition by "
    "sweep_development() in this module. The locked partition was not scored "
    "during selection. Both arms of the contrast necessarily share these "
    "values: the divergence isolates masking only if the estimator is "
    "otherwise identical between arms. "
    "Re-check result (standalone development AUC of the pre-registered gate "
    "signal distorted_divergence, 2026-08-10): order 3 -> 0.744/0.747 "
    "(matched/200k peer pool), order 4 -> 0.817/0.814, order 5 -> 0.815/0.821. "
    "Order 3 is clearly worse; orders 4 and 5 are indistinguishable (0.814 vs "
    "0.821 across 20 development authors) and the peer-pool size barely moves "
    "anything. Phase 1's order=4/200k was therefore KEPT rather than re-tuned "
    "to the nominal development maximum: chasing a 0.007 AUC difference at "
    "this partition size is noise-fitting, and holding the value fixed keeps "
    "this ablation directly comparable to the compression run. Abstention was "
    "0.000 for all four signals at all six configurations."
)


def _merge(trials, *signal_row_dicts):
    merged = []
    for trial in trials:
        signals = dict(trial.signals)
        for rows in signal_row_dicts:
            missing = [t.trial_id for t in trials if t.trial_id not in rows][:3]
            if missing:
                raise ValueError(f"signal missing for trials, e.g. {missing}")
            signals.update(rows[trial.trial_id])
        merged.append(dataclasses.replace(trial, signals=signals))
    return merged


def _load(
    *,
    cache_dir: Path,
    n_style_development: int,
    n_fusion_development: int,
    n_threshold_calibration: int,
    n_locked: int,
):
    partitions = load_author_partitions(
        cache_dir=cache_dir,
        n_development=n_style_development,
        n_calibration=n_fusion_development + n_threshold_calibration,
        n_locked=n_locked,
    )
    fusion_authors = partitions["calibration"][:n_fusion_development]
    threshold_authors = partitions["calibration"][n_fusion_development:]
    return partitions, fusion_authors, threshold_authors, partitions["locked"]


def sweep_development(
    *,
    cache_dir: Path = DEFAULT_CACHE,
    n_style_development: int = 120,
    n_fusion_development: int = 20,
    n_threshold_calibration: int = 20,
    n_locked: int = 12,
    orders: tuple[int, ...] = (3, 4, 5),
    peer_pools: tuple[int | None, ...] = (None, 200_000),
) -> dict:
    """Standalone-signal AUC on ``fusion_development`` ONLY.

    Selection happens here and nowhere else. The locked partition is not
    loaded into any scoring call in this function.
    """
    from sklearn.metrics import roc_auc_score

    partitions, fusion_authors, _, _ = _load(
        cache_dir=cache_dir,
        n_style_development=n_style_development,
        n_fusion_development=n_fusion_development,
        n_threshold_calibration=n_threshold_calibration,
        n_locked=n_locked,
    )
    scoring = {"fusion_development": fusion_authors}
    vectorizer, scaler = _fit_representations(partitions["development"])
    style_trials = {"fusion_development": _score_partition(fusion_authors, vectorizer, scaler)}
    original = original_trial_signals(scoring, peer_reference=list(fusion_authors))
    base = combine_trials(style_trials["fusion_development"], original["fusion_development"])
    labels = np.asarray([t.label for t in base], dtype=np.int8)

    results = {}
    for order in orders:
        for peer_pool in peer_pools:
            rows = distortion_trial_signals(
                scoring, order=order, peer_pool_chars=peer_pool
            )["fusion_development"]
            key = f"order={order},peer_pool={peer_pool}"
            results[key] = {}
            for name in SIGNAL_NAMES:
                values = np.asarray(
                    [
                        rows[t.trial_id][name]
                        if rows[t.trial_id][name] is not None
                        else np.nan
                        for t in base
                    ],
                    dtype=float,
                )
                usable = ~np.isnan(values)
                if usable.sum() < 2 or len(set(labels[usable].tolist())) < 2:
                    results[key][name] = None
                    continue
                auc = float(roc_auc_score(labels[usable], values[usable]))
                # Report the orientation-free discriminative strength; the
                # fusion recovers sign itself, so a signal at AUC 0.2 is as
                # informative as one at 0.8.
                results[key][name] = {"auc": auc, "auc_oriented": max(auc, 1.0 - auc)}
            results[key]["abstention_rate"] = {
                name: abstention_rate(rows, name) for name in SIGNAL_NAMES
            }
            print(f"[sweep] {key}: {json.dumps(results[key])}", file=sys.stderr)
    return results


def run(
    *,
    cache_dir: Path = DEFAULT_CACHE,
    output_path: Path | None = None,
    n_style_development: int = 120,
    n_fusion_development: int = 20,
    n_threshold_calibration: int = 20,
    n_locked: int = 12,
    distortion_order: int = 4,
    peer_pool_chars: int | None = 200_000,
    fusion_fn=fit_grouped_fusion,
) -> dict:
    partitions, fusion_authors, threshold_authors, locked_authors = _load(
        cache_dir=cache_dir,
        n_style_development=n_style_development,
        n_fusion_development=n_fusion_development,
        n_threshold_calibration=n_threshold_calibration,
        n_locked=n_locked,
    )
    scoring_partitions = {
        "fusion_development": fusion_authors,
        "threshold_calibration": threshold_authors,
        "locked": locked_authors,
    }

    print("[pan-stack-distortion] fitting style representations...", file=sys.stderr)
    vectorizer, scaler = _fit_representations(partitions["development"])
    style_trials = {
        name: _score_partition(authors, vectorizer, scaler)
        for name, authors in scoring_partitions.items()
    }
    peer_reference = list(fusion_authors) + list(threshold_authors) + list(locked_authors)
    print("[pan-stack-distortion] scoring Original signals...", file=sys.stderr)
    original = original_trial_signals(scoring_partitions, peer_reference=peer_reference)
    print("[pan-stack-distortion] masking + building character LMs...", file=sys.stderr)
    distortion = distortion_trial_signals(
        scoring_partitions, order=distortion_order, peer_pool_chars=peer_pool_chars
    )

    base_combined = {
        name: combine_trials(style_trials[name], original[name]) for name in scoring_partitions
    }
    distortion_combined = {
        name: _merge(base_combined[name], distortion[name]) for name in scoring_partitions
    }
    assert_no_group_overlap(base_combined["fusion_development"], base_combined["locked"])
    assert_no_group_overlap(base_combined["threshold_calibration"], base_combined["locked"])

    arms = {
        "base_only": (base_combined, BASE_SIGNALS),
        GATE_ARM: (distortion_combined, GATE_SIGNALS),
        # Exploratory, unclaimed -- see the module docstring.
        "with_distorted_delta": (
            distortion_combined,
            BASE_SIGNALS + ("distorted_delta",),
        ),
        "with_distortion_all": (distortion_combined, BASE_SIGNALS + SIGNAL_NAMES),
    }

    def _run_fusion(combined, signal_names, target_fpr=(0.01, 0.05, 0.10)):
        fusion = fusion_fn(
            combined["fusion_development"], signal_names=signal_names, n_splits=5, seed=SEED
        )
        calibration_probability = fusion.predict(combined["threshold_calibration"])
        locked_probability = fusion.predict(combined["locked"])
        calibration_labels = np.asarray(
            [t.label for t in combined["threshold_calibration"]], dtype=np.int8
        )
        locked_labels = np.asarray([t.label for t in combined["locked"]], dtype=np.int8)
        thresholds = {
            str(t): _threshold_at_fpr(calibration_labels, calibration_probability, t)
            for t in target_fpr
        }
        operating = {}
        for target, threshold in thresholds.items():
            predicted = locked_probability >= threshold
            tp = int(np.sum(predicted & (locked_labels == 1)))
            fp = int(np.sum(predicted & (locked_labels == 0)))
            n_pos = int(np.sum(locked_labels == 1))
            n_neg = int(np.sum(locked_labels == 0))
            operating[target] = {
                "threshold": threshold,
                "precision": tp / max(1, tp + fp),
                "recall": tp / max(1, n_pos),
                "fpr": fp / max(1, n_neg),
                "n_locked_genuine": n_pos,
                "n_locked_impostor": n_neg,
            }
        logistic = fusion.estimator.named_steps["logistic"]
        return {
            "signal_names": list(signal_names),
            "standardized_coefficients": logistic.coef_[0].tolist(),
            "fusion_development_oof": _summary(
                combined["fusion_development"], fusion.oof_probability
            ),
            "locked_summary": _summary(combined["locked"], locked_probability),
            "locked_operating_points": operating,
        }

    results = {}
    for name, (combined, signal_names) in arms.items():
        print(f"[pan-stack-distortion] fitting fusion: {name}...", file=sys.stderr)
        results[name] = _run_fusion(combined, signal_names)

    base = results["base_only"]

    def _deltas(candidate: dict) -> dict:
        return {
            "delta_auc": candidate["locked_summary"]["auc"] - base["locked_summary"]["auc"],
            "delta_cllr": candidate["locked_summary"]["cllr"] - base["locked_summary"]["cllr"],
            "delta_recall_at_1pct_fpr": (
                candidate["locked_operating_points"]["0.01"]["recall"]
                - base["locked_operating_points"]["0.01"]["recall"]
            ),
            "delta_recall_at_5pct_fpr": (
                candidate["locked_operating_points"]["0.05"]["recall"]
                - base["locked_operating_points"]["0.05"]["recall"]
            ),
        }

    gate_deltas = _deltas(results[GATE_ARM])
    pan_guard_met = bool(gate_deltas["delta_cllr"] <= 0.0)

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "environment": ENV_LOCK.__dict__,
        "partitions": {
            name: [a.author_id for a in rows] for name, rows in scoring_partitions.items()
        },
        "hyperparameters": {
            "n_style_development": n_style_development,
            "n_fusion_development": n_fusion_development,
            "n_threshold_calibration": n_threshold_calibration,
            "n_locked": n_locked,
            "distortion_order": distortion_order,
            "peer_pool_chars": peer_pool_chars,
            "fusion_fn": fusion_fn.__name__,
            "seed": SEED,
            "provenance": HYPERPARAMETER_PROVENANCE,
        },
        "abstention_rate": {
            partition: {
                signal: abstention_rate(distortion[partition], signal)
                for signal in SIGNAL_NAMES
            }
            for partition in scoring_partitions
        },
        **results,
        "comparison": {
            "gate_G_P2": {
                "pre_registered_arm": GATE_ARM,
                "crossgenre_primary": {
                    "criterion": (
                        "distorted channel's same-author/cross-genre FPR beats "
                        "the raw channel's at matched TPR"
                    ),
                    "status": "NOT_EVALUABLE",
                    "reason": (
                        "validation/genre_crossgenre_2026-08/raw/ is absent -- the "
                        "Lewis/Chesterton corpus is not committed (copyright). "
                        "distort_corpus.py is committed so this is one command for "
                        "anyone holding the corpus."
                    ),
                },
                "pan_guard": {
                    "criterion": "locked stacked cllr does not regress (delta_cllr <= 0)",
                    "met": pan_guard_met,
                    **gate_deltas,
                },
                "verdict": "UNINFORMATIVE",
                "verdict_reason": (
                    "The primary cross-genre criterion could not be evaluated at "
                    "this corpus, so no pass is available. Per the repo's "
                    "three-valued gate convention a gate whose criterion is "
                    "unreachable downgrades to uninformative and must never be "
                    "quoted as a pass. The PAN half is a do-no-harm guard on a "
                    "corpus that does not contain the cross-topic failure mode "
                    "this channel targets."
                ),
            },
            "unclaimed_exploratory_arms": {
                "note": (
                    "NOT pre-registered and NOT claimable. Reported for "
                    "completeness only. Applying a criterion to these after "
                    "seeing locked results would convert the locked partition "
                    "into a tuning set -- the exact failure Phase 1 refused for "
                    "its zlib-NCD arm."
                ),
                "with_distorted_delta": _deltas(results["with_distorted_delta"]),
                "with_distortion_all": _deltas(results["with_distortion_all"]),
            },
        },
    }
    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return report


if __name__ == "__main__":
    if "--sweep" in sys.argv:
        sweep = sweep_development()
        out = Path(
            f"validation/benchmarks/{date.today().isoformat()}/"
            f"pan_stack_distortion_development_sweep.json"
        )
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(sweep, indent=2), encoding="utf-8")
        print(json.dumps(sweep, indent=2))
        raise SystemExit(0)

    result = run(
        output_path=Path(
            f"validation/benchmarks/{date.today().isoformat()}/"
            f"pan_stack_distortion_ablation.json"
        )
    )
    for label in ("base_only", GATE_ARM, "with_distorted_delta", "with_distortion_all"):
        summary = result[label]["locked_summary"]
        op = result[label]["locked_operating_points"]
        print(
            f"{label:28s} AUC={summary['auc']:.4f} cllr={summary['cllr']:.4f} "
            f"recall@1%={op['0.01']['recall']:.3f} recall@5%={op['0.05']['recall']:.3f}"
        )
    print()
    print(json.dumps(result["comparison"]["gate_G_P2"], indent=2))
    print("G-P2:", result["comparison"]["gate_G_P2"]["verdict"])
