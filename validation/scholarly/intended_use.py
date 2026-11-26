"""Intended-use evaluation of the existing scorer on the scholarly corpus. Not a gate.

For each author: a baseline from 4 past papers, 2 held-out new papers by the same author
(honest) and 5 new papers by other authors (probes), scored with the flags-off scorer
(``ScoringConfig()`` defaults, every research flag unset). Humanities and science are run
separately and never pooled.

Two steps, in this order, so a threshold exists before any partition is scored against it:

    python -m validation.scholarly.intended_use calibrate --collection humanities
    python -m validation.scholarly.intended_use develop   --collection humanities

``calibrate`` reads the ``calibration`` partition only and writes
``intended_use_thresholds_<collection>.json``: per length configuration, the
``deviation_score`` threshold giving a 5% honest flag rate there (95th percentile of
calibration honest scores, seeds pooled). ``develop`` reads the ``development`` partition
only and reports the product's own flag rates, the AUC, and the rates at the calibration
threshold (the out-of-sample check). Nothing here can open ``locked_test``.

Reuses ``baseline._score_all`` / ``metrics`` / ``bootstrap`` / ``CONFIGS``; adds seed
pooling by author, a process pool over authors, and a full research-flag reset.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np

_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_ROOT))

HERE = Path(__file__).resolve().parent
ALLOWED_PARTITIONS = ("development", "calibration")   # locked_test is unreachable from here
SEEDS = (7, 11, 23)
TARGET_HONEST_FLAG = 0.05

# Every score-changing or report-attaching research flag in CLAUDE.md's table. Unset = the
# documented default (off), which is what "flags-off" means here.
RESEARCH_FLAGS = (
    "CONTEXT_MANIFEST_ENABLED", "ADAPTIVE_WEIGHTS_ENABLED", "GENRE_INVARIANT_WEIGHTS_ENABLED",
    "GENRE_RESOLVER_V2", "AMPLITUDE_SCORING_ENABLED", "SECRET_KEY", "BAYESIAN_PRIOR_ENABLED",
    "PRIOR_WEIGHT", "NULL_MODEL", "LLR_ACTION_MODE", "COHORT_PRIOR_FALLBACK",
    "LENGTH_ADAPTIVE_WEIGHTS", "TYPICALITY_POOLED_CALIBRATION", "TOPIC_VARIANCE_INFLATION",
    "CHARACTERISTIC_WEIGHTS", "RANK_REMEDIATION", "AI_LIKELIHOOD_ENABLED", "AI_LIKELIHOOD_SHADOW",
    "AI_LIKELIHOOD_MODEL_PATH", "FUSED_SCORE_ENABLED", "FUSED_SCORE_SHADOW", "FUSED_SCORE_MODEL_PATH",
    "EVIDENCE_PASSAGES_ENABLED", "PRELIMINARY_SCORE_ENABLED", "LONGITUDINAL_DRIFT_ENABLED",
    "STYLE_AUTHORSHIP_ENABLED", "STYLE_AUTHORSHIP_MODEL_PATH",
)


def reset_research_flags() -> dict:
    """Unset every research flag (call before the scorer is imported). Returns what was removed."""
    return {k: os.environ.pop(k) for k in RESEARCH_FLAGS if k in os.environ}


def check_partition(partition: str) -> str:
    if partition not in ALLOWED_PARTITIONS:
        raise ValueError(f"intended_use reads only {ALLOWED_PARTITIONS}; {partition!r} is not allowed here")
    return partition


def pool_by_author(runs: list[list[dict]]) -> list[dict]:
    """Merge per-seed per-author results so each author is one bootstrap unit carrying all
    of its documents from every seed."""
    merged: dict[str, dict] = {}
    for run in runs:
        for a in run:
            m = merged.setdefault(a["author"], {"author": a["author"], "honest": [], "honest_flag": [],
                                                "probe": [], "probe_flag": []})
            for k in ("honest", "honest_flag", "probe", "probe_flag"):
                m[k].extend(a[k])
    return [merged[k] for k in sorted(merged)]


def pick_threshold(per_author: list[dict], target: float = TARGET_HONEST_FLAG) -> float:
    """deviation_score threshold with at most ``target`` honest documents above it."""
    h = np.array([s for a in per_author for s in a["honest"]], dtype=float)
    if h.size == 0:
        raise ValueError("no honest scores to calibrate on")
    return float(np.quantile(h, 1.0 - target, method="higher"))


def rates_at(per_author: list[dict], threshold: float) -> dict:
    h = np.array([s for a in per_author for s in a["honest"]], dtype=float)
    p = np.array([s for a in per_author for s in a["probe"]], dtype=float)
    return {"honest_flag_rate": float((h > threshold).mean()), "other_writer_catch_rate": float((p > threshold).mean())}


def bootstrap_at(per_author: list[dict], threshold: float, n_boot: int = 1000, seed: int = 0) -> dict:
    rng = np.random.default_rng(seed)
    n = len(per_author)
    out = {"honest_flag_rate": [], "other_writer_catch_rate": []}
    for _ in range(n_boot):
        r = rates_at([per_author[j] for j in rng.integers(0, n, n)], threshold)
        for k in out:
            out[k].append(r[k])
    return {k: [round(float(np.quantile(v, 0.025)), 4), round(float(np.quantile(v, 0.975)), 4)] for k, v in out.items()}


def _score_one(args):
    trial, n_tokens = args
    from .baseline import _score_all
    return _score_all(trial, n_tokens)


def score_partition(collection: str, partition: str, past_w: int, new_w: int, seed: int,
                    workers: int) -> tuple[list[dict], dict]:
    from .loader import load_trials
    ts = load_trials(collection, check_partition(partition), n_past=4, n_new=2, past_words=past_w,
                     new_words=new_w, n_probes=5, seed=seed)
    with ProcessPoolExecutor(max_workers=workers) as ex:
        per_author = list(ex.map(_score_one, [(t, new_w) for t in ts.trials], chunksize=2))
    return per_author, ts.skipped


def _summ(per_author: list[dict], n_boot: int) -> dict:
    from .baseline import bootstrap, metrics
    m = metrics(per_author)
    m["n_authors"] = len(per_author)
    m["ci95_author_bootstrap"] = bootstrap(per_author, n_boot, 0)
    return {k: (round(v, 4) if isinstance(v, float) else v) for k, v in m.items()}


def run(step: str, collection: str, workers: int, n_boot: int, seeds=SEEDS) -> dict:
    removed = reset_research_flags()
    from .baseline import CONFIGS
    partition = "calibration" if step == "calibrate" else "development"
    thr_path = HERE / f"intended_use_thresholds_{collection}.json"
    thresholds = None
    if step == "develop":
        if not thr_path.exists():
            raise SystemExit("run the calibrate step first: thresholds must exist before development is scored")
        thresholds = json.loads(thr_path.read_text(encoding="utf-8"))["thresholds"]
    out = {"collection": collection, "partition": partition, "step": step, "date": time.strftime("%Y-%m-%d"),
           "scorer": "ScoringConfig() defaults; every research flag in CLAUDE.md unset",
           "flags_removed_from_environment": sorted(removed), "seeds": list(seeds),
           "n_past": 4, "n_new": 2, "n_probes": 5, "configs": {}, "skipped": {}}
    for name, past_w, new_w in CONFIGS:
        runs, t0 = [], time.time()
        cfg = {"per_seed": {}}
        for seed in seeds:
            per_author, skipped = score_partition(collection, partition, past_w, new_w, seed, workers)
            runs.append(per_author)
            cfg["per_seed"][str(seed)] = _summ(per_author, n_boot)
            out["skipped"].update({f"{name}/seed{seed}/{a}": why for a, why in skipped.items()})
        pooled = pool_by_author(runs)
        cfg["pooled"] = _summ(pooled, n_boot)
        if step == "calibrate":
            thr = pick_threshold(pooled)
            cfg["threshold_deviation_score"] = round(thr, 6)
            cfg["at_threshold_in_sample"] = {**{k: round(v, 4) for k, v in rates_at(pooled, thr).items()},
                                             "ci95_author_bootstrap": bootstrap_at(pooled, thr, n_boot)}
        else:
            thr = thresholds[name]
            cfg["threshold_from_calibration"] = thr
            cfg["at_calibration_threshold"] = {**{k: round(v, 4) for k, v in rates_at(pooled, thr).items()},
                                               "ci95_author_bootstrap": bootstrap_at(pooled, thr, n_boot)}
        cfg["seconds"] = round(time.time() - t0)
        out["configs"][name] = cfg
        print(name, json.dumps({k: v for k, v in cfg.items() if k != "per_seed"}), flush=True)
    if step == "calibrate":
        thr_path.write_text(json.dumps({
            "collection": collection, "chosen_on": "calibration", "date": out["date"],
            "rule": f"95th percentile of calibration honest deviation_score (seeds {list(seeds)} pooled); "
                    "flag = score strictly above threshold; target honest flag rate 5%",
            "thresholds": {k: v["threshold_deviation_score"] for k, v in out["configs"].items()},
        }, indent=1) + "\n", encoding="utf-8")
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("step", choices=("calibrate", "develop"))
    ap.add_argument("--collection", choices=("humanities", "science"), required=True)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--n-boot", type=int, default=1000)
    a = ap.parse_args(argv)
    res = run(a.step, a.collection, a.workers, a.n_boot)
    out = HERE / f"intended_use_{a.collection}_{res['partition']}_{res['date']}.json"
    out.write_text(json.dumps(res, indent=1) + "\n", encoding="utf-8")
    print("wrote", out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
