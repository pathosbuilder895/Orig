"""
validation/experiment.py — config-as-data for validation runs.

A number detached from what it measured is how "1.0 (passes)" migrated
from a verification benchmark into an attribution gate table. Every runner
builds an ExperimentSpec at startup and embeds it under an "experiment"
key in its report JSON; diff_specs() explains why two runs disagree, and
refuses to compare runs that answer different questions.
"""
from __future__ import annotations

import subprocess
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

# _SCORING_FLAG_DEFAULTS is a private name in validation.benchmark.reproducibility.
# lock_environment() DOES return a public frozen dataclass (_EnvLockReport) whose
# `scoring_flags` field carries the same {flag: pinned_value} mapping — but
# obtaining it means calling lock_environment() again, which reseeds
# random/numpy and re-writes every pinned env var, silently clobbering any
# intentional POST-lock override a runner made on purpose (e.g.
# validation/verify/run_null_model.py setting NULL_MODEL=impostor after its
# own lock_environment() call — see reproducibility.py's docstring). A spec
# builder must not have that side effect. The static defaults dict is exactly
# what every runner's own single lock_environment() call already pinned into
# os.environ at process start, so reading it here (read-only, no re-lock) is
# the safe choice — it documents "what the benchmark assumed", which is the
# same thing _EnvLockReport.scoring_flags would say, without the footgun.
from validation.benchmark.reproducibility import BENCHMARK_SEED, _SCORING_FLAG_DEFAULTS

VALID_TASKS = {
    "verification",      # is this typical for this author?
    "attribution",       # which of N candidate authors?
    "drift",             # is change over time plausibly evolution?
    "weight_derivation", # Fisher-ratio tier weights
    "calibration_suite", # the G1-G6 gate battery (mixed tasks, one run)
}


@dataclass(frozen=True)
class ExperimentSpec:
    task: str
    git_sha: str
    seed: int
    env_lock: dict[str, str]
    corpora: dict[str, dict]
    windowing: dict
    features: dict
    aggregation: dict
    thresholds: dict
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds")
    )


def _git_sha() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True, text=True, check=True, timeout=10,
        ).stdout.strip()
    except Exception:
        return "unknown"


def _feature_summary() -> dict:
    from original.constants import ALL_FEATURE_CODES
    from validation.measurability import status

    # Sort codes first so status_counts accumulates in a fixed order —
    # ALL_FEATURE_CODES is already a fixed list (not a set), so this is
    # belt-and-suspenders determinism, not a fix for observed nondeterminism.
    counts: dict[str, int] = {}
    for code in ALL_FEATURE_CODES:
        counts[status(code).value] = counts.get(status(code).value, 0) + 1
    return {"total": len(ALL_FEATURE_CODES), "status_counts": counts}


def summarize_author_docs(author_docs: dict[str, list[str]], provenance: str) -> dict:
    docs = [d for ds in author_docs.values() for d in ds]
    return {
        "n_authors": len(author_docs),
        "n_documents": len(docs),
        "total_words": sum(len(d.split()) for d in docs),
        # sorted(): author_docs may arrive as a defaultdict or be built from
        # a set/dict-comprehension whose insertion order isn't guaranteed
        # stable across processes — sort explicitly so two runs over the
        # same authors always serialize identically (diff_specs must not
        # report a spurious docs_per_author reordering as a change).
        "docs_per_author": {a: len(ds) for a, ds in sorted(author_docs.items())},
        "provenance": provenance,
    }


def build_spec(
    task: str,
    corpora: dict[str, dict],
    windowing: dict,
    aggregation: dict,
    thresholds: dict,
) -> ExperimentSpec:
    if task not in VALID_TASKS:
        raise ValueError(f"unknown task {task!r}; must be one of {sorted(VALID_TASKS)}")
    return ExperimentSpec(
        task=task,
        git_sha=_git_sha(),
        seed=BENCHMARK_SEED,
        env_lock=dict(_SCORING_FLAG_DEFAULTS),
        corpora=corpora,
        windowing=windowing,
        features=_feature_summary(),
        aggregation=aggregation,
        thresholds=thresholds,
    )


def spec_to_dict(spec: ExperimentSpec) -> dict:
    return asdict(spec)


def _flatten(d: Any, prefix: str = "") -> dict[str, Any]:
    out: dict[str, Any] = {}
    if isinstance(d, dict):
        for k, v in d.items():
            out.update(_flatten(v, f"{prefix}{k}."))
    else:
        out[prefix[:-1]] = d
    return out


def diff_specs(a: dict, b: dict) -> list[str]:
    if a.get("task") != b.get("task"):
        raise ValueError(
            f"refusing to compare different tasks: {a.get('task')!r} vs {b.get('task')!r} "
            "— these runs answer different questions"
        )
    fa, fb = _flatten(a), _flatten(b)
    changes = []
    for key in sorted(set(fa) | set(fb)):
        if key == "created_at" or key == "git_sha":
            continue
        va, vb = fa.get(key, "<absent>"), fb.get(key, "<absent>")
        if va != vb:
            changes.append(f"{key}: {va} != {vb}")
    return changes
