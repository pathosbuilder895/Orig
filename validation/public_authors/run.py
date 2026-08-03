"""
validation/public_authors/run.py — Test 2 orchestrator (real-documents validation).

Reads the public-author corpus + manifest, builds a baseline for each
author, scores every held-out essay against ALL author baselines, and
reports the attribution matrix + confusion matrix + per-author metrics.

Correct attribution = the lowest IMPOSTOR-CALIBRATED deviation. Raw
deviation_score is z-normalized against each candidate's OWN baseline_std
(original/quantum/scoring.py:599), so raw deviations from different
candidate profiles are on incomparable scales — the loosest-baseline
candidate becomes an argmin black hole. We therefore calibrate: each
candidate's reference distribution is built by scoring every OTHER
eligible author's BASELINE documents against it, and each held-out essay
is attributed by argmin of (dev - ref_mean) / ref_std. Reference sets are
baseline-docs-only — held-out essays never inform the calibration.
Top-1 accuracy ≥ 0.7 across the corpus is the pass criterion.

Run:
    python -m validation.public_authors.run
    python -m validation.public_authors.run --report-dir /tmp/my_run
    python -m validation.public_authors.run --only chesterton,emerson

Authors with fewer than 3 baseline samples are skipped with a clear
warning (validation/corpus_policy.py; Task 8), and any document below the
300-word attribution floor is dropped from both the baseline and scored
pools before eligibility is decided. The corpus can be expanded by adding
URLs to build_corpus.py.

The math is unchanged: every score comes from
``original.quantum.scoring.score()`` via the in-memory FastAPI client.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import statistics
import sys
import time
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

import numpy as np

# Resolve project root so original.* imports work.
_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent.parent
sys.path.insert(0, str(_ROOT))

# Lock the env BEFORE any original.* import.
from validation.benchmark.reproducibility import lock_environment  # noqa: E402

_MANIFEST = _HERE / "manifest.json"
_CORPUS_DIR = _HERE / "corpus"


# ── Data ─────────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class AttributionResult:
    """One held-out essay scored against every author baseline."""

    filename: str
    true_author: str
    predicted_author: str  # impostor-calibrated argmin (raw argmin on fallback)
    predicted_author_raw: str  # raw-deviation argmin (the pre-fix rule)
    correct: bool
    deviations: Dict[str, float] = field(default_factory=dict)  # per-author deviation
    calibrated_scores: Dict[str, float] = field(default_factory=dict)  # per-author z
    rank_of_true: int = 0  # calibrated rank; 1 = correct, 2 = runner-up, …
    rank_of_true_raw: int = 0  # rank under the raw-deviation ordering
    word_count: int = 0
    scoring_time_ms: float = 0.0
    error: Optional[str] = None
    # Task 11: three independent engines scored on the SAME essay, plus the
    # 2-of-3 agreement verdict. engine_predictions is {} when an engine
    # raised on this essay (see run()'s exception-handling note) — that
    # essay is excluded from the ensemble/per-engine summary stats so every
    # engine's denominator stays comparable, but it still appears here.
    engine_predictions: Dict[str, str] = field(default_factory=dict)
    ensemble_author: Optional[str] = None
    ensemble_basis: str = ""


# ── Attribution rule (pure — unit-tested in tests/test_public_authors_attribution.py) ─


def calibrated_attribution(
    deviations: Dict[str, float],
    ref_stats: Dict[str, Tuple[float, float]],
) -> Tuple[str, Dict[str, float]]:
    """
    Impostor-calibrated attribution. Converts raw per-candidate deviations
    to calibrated z-scores z = (dev - ref_mean[cand]) / ref_std[cand] and
    returns (argmin candidate, calibrated scores). ref_stats maps each
    candidate to (ref_mean, ref_std) of the deviations that OTHER authors'
    baseline documents earn against that candidate — putting all candidates
    on a common "how unusual is this deviation for you?" scale. ref_std is
    floored at 1e-6 so a degenerate reference set cannot divide by zero.
    """
    calibrated = {
        cand: (dev - ref_stats[cand][0]) / max(ref_stats[cand][1], 1e-6)
        for cand, dev in deviations.items()
    }
    predicted = sorted(calibrated.items(), key=lambda kv: kv[1])[0][0]
    return predicted, calibrated


def rank_of(scores: Dict[str, float], author: str) -> int:
    """Rank of `author` under ascending `scores` (1 = best match; 0 = absent)."""
    ranked = sorted(scores.items(), key=lambda kv: kv[1])
    return next((i + 1 for i, (a, _) in enumerate(ranked) if a == author), 0)


# ── The orchestrator ────────────────────────────────────────────────────────


def run(
    *,
    manifest_path: Path = _MANIFEST,
    corpus_dir: Path = _CORPUS_DIR,
    only: Optional[Set[str]] = None,
    report_dir: Optional[Path] = None,
) -> dict:
    """
    Run Test 2 end-to-end. Returns a report dict.

    Args:
        manifest_path: path to the public-authors manifest.
        corpus_dir: root of the corpus tree.
        only: optional set of author_ids to include; others are skipped.
        report_dir: where to write the report.{json,md} + CSVs. Defaults
                    to validation/benchmarks/<YYYY-MM-DD>/public_authors/.
    """
    env = lock_environment()

    # Late import — must be after env lock.
    import run as _run_module  # the project's run.py at repo root
    from fastapi.testclient import TestClient

    with open(manifest_path) as f:
        manifest = json.load(f)

    # Group entries by author.
    by_author: Dict[str, dict] = defaultdict(lambda: {"baseline": [], "scored": []})
    for e in manifest["entries"]:
        key = "baseline" if e["is_baseline"] else "scored"
        by_author[e["author_id"]][key].append(e)

    # Task 8: corpus policy — short documents are verification-only (never
    # attribution material, whether used to BUILD a candidate's baseline or
    # SCORED as a held-out probe — a 6-17 word TOC stub is exactly what
    # corrupted 2 of 9 profiles before the chunker fix), and a candidate
    # with too few baseline documents is a stub profile that must never be
    # attributed against. Both floors go through the same shared policy
    # module every runner will use, not a bespoke check here.
    from validation.corpus_policy import (
        ATTRIBUTION_MIN_BASELINE_DOCS,
        ATTRIBUTION_MIN_WORDS,
        check_attribution_pool,
    )

    word_counts = {e["filename"]: e["word_count"] for e in manifest["entries"]}
    baseline_counts = {a: len(items["baseline"]) for a, items in by_author.items()}
    policy_violations = check_attribution_pool(word_counts, baseline_counts)
    short_docs = {v.subject for v in policy_violations if v.kind == "short_document"}
    if short_docs:
        # Drop sub-floor documents from BOTH pools before anything downstream
        # (baseline construction, the experiment-spec corpus summary, and the
        # eligibility filter below) ever sees them.
        for items in by_author.values():
            items["baseline"] = [e for e in items["baseline"] if e["filename"] not in short_docs]
            items["scored"] = [e for e in items["scored"] if e["filename"] not in short_docs]
        # Dropping short docs can itself thin a baseline further — recheck
        # both floors against what remains (mirrors the Bayesian-prior
        # self-exclusion re-check in validation store.py's genre pool).
        baseline_counts = {a: len(items["baseline"]) for a, items in by_author.items()}
        policy_violations = check_attribution_pool(word_counts, baseline_counts)
    for v in policy_violations:
        print(f"  ⚠ corpus policy: {v.kind} — {v.subject}: {v.detail}", file=sys.stderr)
    # Thin-baseline authors leave the CANDIDATE pool — never attribute
    # against a stub profile — but the run continues on whoever remains;
    # this feeds the SAME skipped_authors mechanism as every other
    # exclusion reason below, not a parallel abort path.
    thin_baseline_authors = {v.subject for v in policy_violations if v.kind == "thin_baseline"}

    # Filter to authors with the required minimum AND any --only filter.
    # Computed BEFORE the experiment-spec corpus summary below (Task 11) so
    # that summary narrows to the pool actually scored, not the whole
    # manifest — a run narrowed by --only or thinned by corpus policy must
    # report what it measured, not what the raw manifest contains.
    eligible: List[str] = []
    skipped_authors: List[Tuple[str, str]] = []
    for aid, items in sorted(by_author.items()):
        if only is not None and aid not in only:
            skipped_authors.append((aid, "filtered by --only"))
            continue
        if aid in thin_baseline_authors:
            skipped_authors.append(
                (
                    aid,
                    f"thin baseline: {len(items['baseline'])} baseline documents "
                    f"< required {ATTRIBUTION_MIN_BASELINE_DOCS} (corpus policy)",
                )
            )
            continue
        if not items["scored"]:
            skipped_authors.append((aid, "no held-out scored essays"))
            continue
        eligible.append(aid)

    # Task 7: summarize the ELIGIBLE authors' baseline/scored doc lists for
    # the experiment spec. Narrowed to `eligible` (Task 11) rather than the
    # full manifest — otherwise a run narrowed by --only or by corpus policy
    # would report a bigger corpus than it actually measured. Still built
    # before the "len(eligible) < 2" error path below returns, so the spec
    # is attachable even then (an empty eligible set just summarizes to zero
    # authors/documents, which is the honest answer on that path).
    # sorted(): by_author is a defaultdict populated in manifest-entry
    # order, which is corpus-file order, not an author-name order — sort so
    # two runs over the same manifest serialize docs_per_author identically
    # regardless of entry order.
    from validation.experiment import build_spec, spec_to_dict, summarize_author_docs

    eligible_set = set(eligible)
    scored_author_docs: Dict[str, List[str]] = {
        aid: [
            (corpus_dir / e["filename"]).read_text(encoding="utf-8")
            for e in items["baseline"] + items["scored"]
        ]
        for aid, items in sorted(by_author.items())
        if aid in eligible_set
    }
    experiment_corpora = {
        "public_authors": summarize_author_docs(scored_author_docs, "real_historical")
    }
    experiment_windowing = {"source": "public_authors corpus documents as-is"}
    experiment_thresholds = {
        "g3_top1": 0.7,
        # Task 8: the corpus-policy floors this run enforced — visible in
        # every report diff per validation/corpus_policy.py's own docstring.
        "attribution_min_words": ATTRIBUTION_MIN_WORDS,
        "attribution_min_baseline_docs": ATTRIBUTION_MIN_BASELINE_DOCS,
    }

    if len(eligible) < 2:
        msg = (
            f"Need at least 2 eligible authors for an attribution test; "
            f"got {len(eligible)}. Expand the corpus by adding URLs to "
            f"validation/public_authors/build_corpus.py and re-running."
        )
        print(f"\n⚠ {msg}\n", file=sys.stderr)
        if not eligible:
            spec = build_spec(
                task="attribution",
                corpora=experiment_corpora,
                windowing=experiment_windowing,
                aggregation={"attribution_rule": "not_computed (error path)"},
                thresholds=experiment_thresholds,
            )
            return {
                "error": msg,
                "skipped_authors": skipped_authors,
                "experiment": spec_to_dict(spec),
            }

    client = TestClient(_run_module.load_legacy_demo_app())

    # ── 1. Build each author's baseline. We use a unique student_id per
    #      author so the scorer can address each one separately.
    print(f"Eligible authors: {eligible}", file=sys.stderr)
    print(f"Skipped: {skipped_authors}", file=sys.stderr)
    print(f"\nBuilding baselines…", file=sys.stderr)
    for aid in eligible:
        sid = f"demo:pa_{aid}"
        for entry in by_author[aid]["baseline"]:
            text = (corpus_dir / entry["filename"]).read_text(encoding="utf-8")
            r = client.post(
                f"/students/{sid}/baseline",
                json={
                    "text": text,
                    "provenance": "verified",
                    "assignment": entry["prompt"],
                    "submitted_at": "2026-01-01",
                },
            )
            if r.status_code != 200:
                print(
                    f"  ⚠ {aid} baseline {entry['filename']}: {r.status_code} {r.text[:120]}",
                    file=sys.stderr,
                )
        print(
            f"  {aid}: {len(by_author[aid]['baseline'])} baseline samples uploaded", file=sys.stderr
        )

    # ── 2. Build each candidate's impostor reference distribution: score
    #      every OTHER eligible author's BASELINE documents against the
    #      candidate. Held-out essays are never scored here, so the
    #      calibration involves zero test-set leakage. The resulting
    #      (ref_mean, ref_std) per candidate puts all candidates on a common
    #      scale — raw deviation_score is z-normalized against each
    #      candidate's OWN baseline_std, so raw values are not cross-author
    #      comparable (the loosest baseline becomes an argmin black hole).
    print(f"\nBuilding impostor reference distributions…", file=sys.stderr)
    ref_stats: Dict[str, Tuple[float, float]] = {}
    ref_detail: Dict[str, dict] = {}
    ref_warnings: List[str] = []
    for candidate in eligible:
        cand_sid = f"demo:pa_{candidate}"
        ref_devs: List[float] = []
        for other in eligible:
            if other == candidate:
                continue
            for entry in by_author[other]["baseline"]:
                text = (corpus_dir / entry["filename"]).read_text(encoding="utf-8")
                rr = client.post(
                    f"/students/{cand_sid}/score",
                    json={
                        "text": text,
                        "assignment": entry["prompt"],
                        "submission_id": f"ref:{entry['filename']}",
                    },
                )
                if rr.status_code == 200:
                    ref_devs.append(float(rr.json()["authorship"]["deviation_score"]))
        if len(ref_devs) < 5:
            ref_warnings.append(
                f"{candidate}: only {len(ref_devs)} reference points (need ≥5)"
            )
            print(f"  ⚠ {ref_warnings[-1]}", file=sys.stderr)
            continue
        ref_stats[candidate] = (statistics.mean(ref_devs), statistics.stdev(ref_devs))
        ref_detail[candidate] = {
            "ref_mean": round(ref_stats[candidate][0], 4),
            "ref_std": round(ref_stats[candidate][1], 4),
            "n_reference_points": len(ref_devs),
        }
        print(
            f"  {candidate}: n={len(ref_devs)}, "
            f"ref_mean={ref_stats[candidate][0]:.4f}, ref_std={ref_stats[candidate][1]:.4f}",
            file=sys.stderr,
        )
    # Any under-populated reference set ⇒ fall back to raw argmin for the
    # whole run (a partial calibration would mix incomparable rules).
    calibration_ok = len(ref_stats) == len(eligible)
    attribution_method = "impostor_calibrated_z" if calibration_ok else "raw_argmin_fallback"
    if not calibration_ok:
        print(
            f"  ⚠ falling back to raw argmin for the whole run "
            f"({len(ref_warnings)} candidate(s) under-populated)",
            file=sys.stderr,
        )

    # ── 2b. Task 11: build the two independent engines' baseline inputs
    #      ONCE, from the SAME baseline docs the deviation engine used
    #      above — not per essay, since feature_vector() costs ~650ms/call
    #      (~27 baseline docs here ≈ 18s total; inside the per-essay loop
    #      that would be repeated for every held-out essay).
    print(f"\nBuilding cosine-delta / MFW-delta baseline inputs…", file=sys.stderr)
    from original.features.pipeline import feature_vector
    from validation.attribution.delta import cosine_delta_attribution, mfw_delta_attribution
    from validation.attribution.ensemble import ensemble_vote, pairwise_agreement
    from validation.measurability import measurable_indices

    feature_idx = measurable_indices("public_authors")
    baseline_texts: Dict[str, List[str]] = {
        a: [
            (corpus_dir / entry["filename"]).read_text(encoding="utf-8")
            for entry in by_author[a]["baseline"]
        ]
        for a in eligible
    }
    baseline_matrices: Dict[str, np.ndarray] = {
        a: np.vstack([feature_vector(doc) for doc in docs])
        for a, docs in baseline_texts.items()
    }

    # ── 3. For each held-out essay, score it against EVERY author baseline
    #      and attribute by argmin CALIBRATED score (raw argmin on fallback).
    #      Also run the two independent engines (cosine-delta, MFW-delta) on
    #      the identical essay and vote a 2-of-3 ensemble verdict.
    #
    #      Exception policy (Task 11): cosine_delta_attribution and
    #      mfw_delta_attribution both raise ValueError on degenerate input
    #      (e.g. non-finite feature values, an empty pooled vocabulary).
    #      Silently dropping an essay from just the ONE engine that raised —
    #      while keeping it in the other two engines' accuracy denominators
    #      — would make the side-by-side comparison dishonest (each
    #      engine's "n" would mean a different set of essays). We also
    #      don't want one bad essay to kill the whole benchmark. So: if
    #      EITHER delta engine raises on an essay, the WHOLE essay is
    #      excluded from the per-engine/ensemble comparison (engine_agreement,
    #      per_engine_top1, ensemble_coverage/accuracy) — never from just one
    #      engine's count — and the exclusion is recorded in
    #      summary["engine_exceptions"] so it's visible in the report, not
    #      silently absorbed into a smaller denominator. The deviation-
    #      calibrated engine's own top1_accuracy (the pre-existing summary
    #      field) is unaffected: it is computed the same way as before this
    #      task for every held-out essay regardless of the delta engines.
    print(
        f"\nScoring {sum(len(by_author[a]['scored']) for a in eligible)} held-out essays "
        f"against {len(eligible)} authors…",
        file=sys.stderr,
    )
    results: List[AttributionResult] = []
    engine_exceptions: List[dict] = []
    for true_author in eligible:
        for entry in by_author[true_author]["scored"]:
            text = (corpus_dir / entry["filename"]).read_text(encoding="utf-8")
            wc = entry["word_count"]
            t0 = time.perf_counter()
            devs: Dict[str, float] = {}
            err: Optional[str] = None
            for candidate in eligible:
                cand_sid = f"demo:pa_{candidate}"
                rr = client.post(
                    f"/students/{cand_sid}/score",
                    json={
                        "text": text,
                        "assignment": entry["prompt"],
                        "submission_id": entry["filename"],
                    },
                )
                if rr.status_code != 200:
                    err = f"{candidate}: {rr.status_code}"
                    devs[candidate] = float("nan")
                else:
                    devs[candidate] = float(rr.json()["authorship"]["deviation_score"])
            elapsed_ms = (time.perf_counter() - t0) * 1000.0
            # Raw rule (pre-fix): sort by deviation ascending — lowest = best.
            predicted_raw = sorted(devs.items(), key=lambda kv: kv[1])[0][0]
            rank_raw = rank_of(devs, true_author)
            if calibration_ok:
                predicted, calibrated = calibrated_attribution(devs, ref_stats)
                rank_cal = rank_of(calibrated, true_author)
            else:
                predicted, calibrated = predicted_raw, {}
                rank_cal = rank_raw

            # Task 11: run the two independent engines on the SAME essay
            # text and vote. See the exception-policy note above section 3.
            try:
                essay_vec = feature_vector(text)
                cos_pred, _cos_dists = cosine_delta_attribution(
                    baseline_matrices, essay_vec, feature_idx
                )
                mfw_pred, _mfw_deltas = mfw_delta_attribution(baseline_texts, text)
                engine_predictions = {
                    "deviation_calibrated": predicted,
                    "cosine_delta": cos_pred,
                    "mfw_delta": mfw_pred,
                }
                ensemble_author, ensemble_basis = ensemble_vote(engine_predictions)
            except ValueError as exc:
                engine_predictions = {}
                ensemble_author = None
                ensemble_basis = f"excluded from ensemble: {exc}"
                engine_exceptions.append({"filename": entry["filename"], "error": str(exc)})
                print(f"  ⚠ engine exception on {entry['filename']}: {exc}", file=sys.stderr)

            results.append(
                AttributionResult(
                    filename=entry["filename"],
                    true_author=true_author,
                    predicted_author=predicted,
                    predicted_author_raw=predicted_raw,
                    correct=(predicted == true_author),
                    deviations={a: round(d, 4) for a, d in devs.items()},
                    calibrated_scores={a: round(z, 4) for a, z in calibrated.items()},
                    rank_of_true=rank_cal,
                    rank_of_true_raw=rank_raw,
                    word_count=wc,
                    scoring_time_ms=round(elapsed_ms, 2),
                    error=err,
                    engine_predictions=engine_predictions,
                    ensemble_author=ensemble_author,
                    ensemble_basis=ensemble_basis,
                )
            )
            print(
                f"  {entry['filename']}: true={true_author}, "
                f"predicted={predicted} {'✓' if predicted==true_author else '✗'} "
                f"(rank {rank_cal}, raw={predicted_raw}) | ensemble={ensemble_author} "
                f"({ensemble_basis})",
                file=sys.stderr,
            )

    # ── 4. Aggregate metrics.
    top1_accuracy = sum(1 for r in results if r.correct) / max(1, len(results))
    top1_accuracy_raw = sum(
        1 for r in results if r.predicted_author_raw == r.true_author
    ) / max(1, len(results))
    mean_rank = sum(r.rank_of_true for r in results) / max(1, len(results))
    mean_rank_raw = sum(r.rank_of_true_raw for r in results) / max(1, len(results))
    per_author = defaultdict(lambda: {"n": 0, "correct": 0})
    for r in results:
        per_author[r.true_author]["n"] += 1
        if r.correct:
            per_author[r.true_author]["correct"] += 1

    confusion: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for r in results:
        confusion[r.true_author][r.predicted_author] += 1

    # ── 4b. Task 11: per-engine / ensemble aggregation.
    #
    #      n_scored_essays is the held-out essay count BEHIND
    #      top1_accuracy — i.e. len(results), the same denominator
    #      top1_accuracy already uses above. This is deliberately NOT
    #      narrowed to the engine-comparison subset below: G3
    #      (validation/calibration_gate.py's evaluate_g3_attribution) reads
    #      summary["n_scored_essays"] together with summary["top1_accuracy"]
    #      to reconstruct `successes = round(top1_accuracy * n_essays)` for
    #      its Wilson-interval informativeness check, which only holds if
    #      n_essays is top1_accuracy's own denominator.
    n_scored_essays = len(results)

    #      The per-engine/ensemble comparison below is restricted to
    #      `scorable` — essays where ALL THREE engines produced a
    #      prediction (see the exception-policy note above the per-essay
    #      loop) — so every engine's accuracy denominator, the pairwise
    #      agreement, and the ensemble coverage/accuracy all share the SAME
    #      n rather than three different, incomparable ones. That n is
    #      recorded per-stat (per_engine_top1[engine]["n"]) and may be
    #      SMALLER than n_scored_essays above if any essay was excluded.
    from validation.power import wilson_interval

    scorable = [r for r in results if r.engine_predictions]
    n_comparable = len(scorable)
    per_engine_top1: Dict[str, dict] = {}
    if scorable:
        for engine in scorable[0].engine_predictions:
            hits = sum(1 for r in scorable if r.engine_predictions[engine] == r.true_author)
            lo, hi = wilson_interval(hits, n_comparable)
            # Every accuracy travels with its interval: at n as small as
            # these corpora give us, the CI is wide enough that two engines
            # differing by 0.1-0.15 can be statistically indistinguishable.
            # Carrying the interval keeps the side-by-side table from being
            # read as a ranking it cannot support.
            per_engine_top1[engine] = {
                "accuracy": round(hits / n_comparable, 4),
                "wilson_ci_95": [round(lo, 4), round(hi, 4)],
                "n": n_comparable,
            }
    covered = [r for r in scorable if r.ensemble_author is not None]
    ensemble_coverage = (len(covered) / n_comparable) if n_comparable else None
    ensemble_accuracy_on_covered = (
        sum(1 for r in covered if r.ensemble_author == r.true_author) / len(covered)
        if covered
        else None
    )
    engine_agreement = pairwise_agreement([r.engine_predictions for r in scorable])

    # ── 5. Build report dict + write to disk.
    if report_dir is None:
        import datetime

        report_dir = (
            _ROOT
            / "validation"
            / "benchmarks"
            / datetime.date.today().isoformat()
            / "public_authors"
        )
    report_dir.mkdir(parents=True, exist_ok=True)

    spec = build_spec(
        task="attribution",
        corpora=experiment_corpora,
        windowing=experiment_windowing,
        aggregation={"attribution_rule": attribution_method},
        thresholds=experiment_thresholds,
    )

    report = {
        "dataset_label": "public_authors",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "environment": env.__dict__,
        "experiment": spec_to_dict(spec),
        "summary": {
            "eligible_authors": eligible,
            "n_eligible_authors": len(eligible),
            "n_held_out_essays": len(results),
            "top1_accuracy": round(top1_accuracy, 4),
            "top1_accuracy_raw_argmin": round(top1_accuracy_raw, 4),
            "mean_rank_of_true_author": round(mean_rank, 3),
            "mean_rank_raw_argmin": round(mean_rank_raw, 3),
            "attribution_method": attribution_method,
            "method_note": (
                "Attribution = argmin over candidates of the impostor-calibrated "
                "z-score (deviation - ref_mean[cand]) / ref_std[cand]; each "
                "candidate's reference distribution is the deviations of every "
                "OTHER eligible author's baseline documents scored against that "
                "candidate. Reference sets are baseline-docs-only — held-out "
                "essays never inform the calibration. Raw deviation_score is "
                "z-normalized against each candidate's own baseline_std, so raw "
                "values are not cross-author comparable."
                if calibration_ok
                else "Fell back to raw argmin for the whole run: at least one "
                "candidate had fewer than 5 impostor reference points (see "
                "reference_warnings)."
            ),
            "reference_warnings": ref_warnings,
            "skipped_authors": skipped_authors,
            # Task 8: corpus-policy narrowing is a different measurement from
            # accuracy over the full manifest — make it visible in the report,
            # not just on stderr.
            "dropped_short_documents": sorted(short_docs),
            "corpus_policy_violations": [asdict(v) for v in policy_violations],
            # Task 11: three-engine side-by-side + 2-of-3 ensemble routing.
            # n_scored_essays is G3's informativeness input (Task 6) — the
            # held-out essay count BEHIND top1_accuracy (len(results); see
            # the comment above where n_scored_essays is computed for why
            # it is NOT narrowed to the engine-comparison subset). The
            # per_engine_top1 / ensemble_coverage / engine_agreement stats
            # below use their OWN shared "n" (n_comparable), which may be
            # smaller if engine_exceptions excluded any essay.
            "n_scored_essays": n_scored_essays,
            "per_engine_top1": per_engine_top1,
            "ensemble_coverage": (
                round(ensemble_coverage, 4) if ensemble_coverage is not None else None
            ),
            "ensemble_accuracy_on_covered": (
                round(ensemble_accuracy_on_covered, 4)
                if ensemble_accuracy_on_covered is not None
                else None
            ),
            "engine_agreement": {k: round(v, 4) for k, v in engine_agreement.items()},
            # Essays excluded from the three-engine comparison above because
            # a delta engine raised ValueError on degenerate input (empty
            # feature-index list, empty pooled vocabulary, non-finite
            # values, < 2 usable candidates) — excluded from ALL THREE
            # engines' denominators, never from just the one that raised
            # (see the exception-policy note above the per-essay loop).
            "engine_exceptions": engine_exceptions,
        },
        "reference_stats": ref_detail,
        "per_author": {
            a: {
                "n_scored": c["n"],
                "n_correct": c["correct"],
                "accuracy": round(c["correct"] / max(1, c["n"]), 4),
            }
            for a, c in per_author.items()
        },
        "results": [asdict(r) for r in results],
        "confusion": {true_a: dict(preds) for true_a, preds in confusion.items()},
    }
    (report_dir / "report.json").write_text(json.dumps(report, indent=2))
    _write_attribution_csv(report_dir / "attribution_matrix.csv", results, eligible)
    _write_confusion_csv(report_dir / "confusion.csv", confusion, eligible)
    (report_dir / "report.md").write_text(_render_markdown(report))

    print(f"\n┌─────────────────────────────────────────────────┐", file=sys.stderr)
    print(f"│  Top-1 attribution accuracy: {top1_accuracy:.2%}              │", file=sys.stderr)
    print(f"│  Mean rank of true author:   {mean_rank:.2f}                │", file=sys.stderr)
    print(f"│  Method: {attribution_method}", file=sys.stderr)
    print(f"│  (raw argmin: {top1_accuracy_raw:.2%}, mean rank {mean_rank_raw:.2f})", file=sys.stderr)
    for engine, stats in per_engine_top1.items():
        lo, hi = stats["wilson_ci_95"]
        print(
            f"│  {engine}: {stats['accuracy']:.2%} (95% CI [{lo:.2f}, {hi:.2f}], n={stats['n']})",
            file=sys.stderr,
        )
    if ensemble_coverage is not None:
        print(
            f"│  Ensemble: coverage {ensemble_coverage:.2%}, "
            f"accuracy on covered {ensemble_accuracy_on_covered:.2%}",
            file=sys.stderr,
        )
    print(f"│  Reports: {report_dir}", file=sys.stderr)
    print(f"└─────────────────────────────────────────────────┘", file=sys.stderr)
    return report


# ── Helpers ─────────────────────────────────────────────────────────────────


def _write_attribution_csv(
    path: Path, results: List[AttributionResult], eligible: List[str]
) -> None:
    """Row = held-out essay; cols = deviation to each author baseline + verdict."""
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(
            [
                "filename",
                "true_author",
                "predicted_author",
                "predicted_raw",
                "correct",
                "rank_of_true",
                "rank_of_true_raw",
                "word_count",
                *[f"dev_to_{a}" for a in eligible],
            ]
        )
        for r in results:
            w.writerow(
                [
                    r.filename,
                    r.true_author,
                    r.predicted_author,
                    r.predicted_author_raw,
                    "yes" if r.correct else "no",
                    r.rank_of_true,
                    r.rank_of_true_raw,
                    r.word_count,
                    *[r.deviations.get(a, "") for a in eligible],
                ]
            )


def _write_confusion_csv(
    path: Path, confusion: Dict[str, Dict[str, int]], eligible: List[str]
) -> None:
    """Row = true author; col = predicted author."""
    with open(path, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["true \\ predicted", *eligible])
        for true_a in eligible:
            row = [true_a]
            for pred_a in eligible:
                row.append(confusion.get(true_a, {}).get(pred_a, 0))
            w.writerow(row)


def _render_markdown(report: dict) -> str:
    s = report["summary"]
    lines = []
    lines.append("# Public-author validation — Test 2 report")
    lines.append("")
    lines.append(f"_Generated {report['generated_at']}_")
    lines.append("")
    lines.append("## Summary")
    lines.append("")
    lines.append(f"- **Top-1 attribution accuracy**: {s['top1_accuracy']:.2%}")
    lines.append(f"- **Mean rank of true author**: {s['mean_rank_of_true_author']}")
    if "attribution_method" in s:
        lines.append(f"- **Attribution method**: {s['attribution_method']}")
    if "top1_accuracy_raw_argmin" in s:
        lines.append(
            f"- **Raw-argmin comparison (pre-fix rule)**: "
            f"top-1 {s['top1_accuracy_raw_argmin']:.2%}, "
            f"mean rank {s.get('mean_rank_raw_argmin', 'n/a')}"
        )
    if s.get("method_note"):
        lines.append(f"- **Method note**: {s['method_note']}")
    if s.get("reference_warnings"):
        lines.append(
            f"- **Reference warnings**: {'; '.join(s['reference_warnings'])}"
        )
    lines.append(
        f"- **Eligible authors**: {s['n_eligible_authors']} — {', '.join(s['eligible_authors'])}"
    )
    lines.append(f"- **Held-out essays scored**: {s['n_held_out_essays']}")
    if s.get("skipped_authors"):
        lines.append(
            f"- **Skipped authors**: {len(s['skipped_authors'])} — see report.json for reasons"
        )
    if s.get("dropped_short_documents"):
        lines.append(
            f"- **Dropped short documents (corpus policy)**: "
            f"{len(s['dropped_short_documents'])} — {', '.join(s['dropped_short_documents'])}"
        )
    lines.append("")
    lines.append("## Per-author accuracy")
    lines.append("")
    lines.append("| author | n | correct | accuracy |")
    lines.append("|---|---|---|---|")
    for a, c in sorted(report["per_author"].items()):
        lines.append(f"| {a} | {c['n_scored']} | {c['n_correct']} | {c['accuracy']:.2%} |")
    lines.append("")
    lines.append("## Confusion matrix")
    lines.append("")
    authors = s["eligible_authors"]
    lines.append("| true \\ predicted | " + " | ".join(authors) + " |")
    lines.append("|" + "---|" * (len(authors) + 1))
    for ta in authors:
        row = [ta]
        for pa in authors:
            row.append(str(report["confusion"].get(ta, {}).get(pa, 0)))
        lines.append("| " + " | ".join(row) + " |")
    lines.append("")
    if s.get("per_engine_top1"):
        lines.append("## Three-engine side-by-side (Task 11)")
        lines.append("")
        _comparable_n = next(iter(s["per_engine_top1"].values()))["n"]
        lines.append(
            f"n_scored_essays (held out, all authors) = {s['n_scored_essays']}; "
            f"n comparable across all three engines below = {_comparable_n} "
            "(narrower only if engine_exceptions excluded any essay). Read the "
            "CIs before comparing rows — at this n they are wide."
        )
        lines.append("")
        lines.append("| engine | accuracy | 95% Wilson CI | n |")
        lines.append("|---|---|---|---|")
        for engine, stats in s["per_engine_top1"].items():
            lo, hi = stats["wilson_ci_95"]
            lines.append(
                f"| {engine} | {stats['accuracy']:.2%} | [{lo:.2f}, {hi:.2f}] | {stats['n']} |"
            )
        lines.append("")
        if s.get("ensemble_coverage") is not None:
            acc = s.get("ensemble_accuracy_on_covered")
            acc_str = f"{acc:.2%}" if acc is not None else "n/a"
            lines.append(
                f"- **Ensemble (2-of-3 agreement) coverage**: {s['ensemble_coverage']:.2%}"
            )
            lines.append(f"- **Ensemble accuracy on covered essays**: {acc_str}")
        if s.get("engine_agreement"):
            lines.append("- **Pairwise agreement**:")
            for pair, rate in s["engine_agreement"].items():
                lines.append(f"  - {pair}: {rate:.2%}")
        if s.get("engine_exceptions"):
            lines.append(
                f"- **Essays excluded from the three-engine comparison** "
                f"(a delta engine raised on degenerate input): "
                f"{len(s['engine_exceptions'])} — see report.json for detail"
            )
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


# ── CLI ─────────────────────────────────────────────────────────────────────


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    ap.add_argument("--only", help="Comma-separated list of author_ids to include.")
    ap.add_argument(
        "--report-dir",
        type=Path,
        help="Where to write reports. Defaults to "
        "validation/benchmarks/<YYYY-MM-DD>/public_authors/",
    )
    args = ap.parse_args(argv)
    only = set(a.strip() for a in args.only.split(",")) if args.only else None
    report = run(only=only, report_dir=args.report_dir)
    return 0 if "error" not in report else 1


if __name__ == "__main__":
    sys.exit(main())
