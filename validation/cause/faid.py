"""Checksum-pinned FAIDSet external lock for AI and human--LLM collaboration.

Only the upstream test split is used.  FAID's collaborative class is not
silently renamed "humanized AI": it is a broader, independently collected
class that tests whether signals transfer to partially human-authored text.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
import urllib.request
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

import numpy as np
from sklearn.metrics import roc_auc_score

from original.ai_likelihood import predict_ai_likelihood_batch
from scripts.train_ai_detector import _extract_parallel
from validation.cause.zero_shot_origin import score_texts, threshold_at_fpr


REVISION = "e2927dd1218b32767b212f822366c01bd406f5b3"
BASE_URL = f"https://huggingface.co/datasets/ngocminhta/FAIDSet/resolve/{REVISION}"
HUMAN = "human"
DIRECT_AI = "direct_ai"
COLLABORATIVE = "human_llm_collaborative"
FAMILIES = ("gpt", "gemini", "llama", "deepseek")
FILES = {
    "human.jsonl": ("FAIDSet-original-format/human-text/test.jsonl", "2572ab37ecb82478b5b157bff9a1c7bb8c839aa3d5f454e3ad225a6342f51403"),
    "gpt.jsonl": ("FAIDSet-original-format/gpt-text/test.jsonl", "1543ae049c4ac662999d7f20e828a4e3ca0068f414f458b3f32e954a0ddfea19"),
    "gemini.jsonl": ("FAIDSet-original-format/gemini-text/test.jsonl", "f0167a4fe433b74b0b974d92767adfcebb5b4b186ce5292e420e828a1b219b92"),
    "llama.jsonl": ("FAIDSet-original-format/llama-text/test.jsonl", "bdcda0c1f633844f11c1546111bbfd2521e91648db291d0aa35e04bad74220b0"),
    "deepseek.jsonl": ("FAIDSet-original-format/deepseek-text/test.jsonl", "6dc21e18c6133815a331f3ce01fe4a916564166dbf2b5e2a058ac9f5b77ffe9e"),
    "human-gpt.jsonl": ("FAIDSet-original-format/human---gpt-text/test.jsonl", "0756456aed67824be5058deca8c9fe8ca752995f7896980cc464f988a8cf3d80"),
    "human-gemini.jsonl": ("FAIDSet-original-format/human---gemini-text/test.jsonl", "6d2b01f6b963c18f602d77a4ed503e619d3439851e2a0b3c2ad3eba0dbb6adf4"),
    "human-llama.jsonl": ("FAIDSet-original-format/human---llama-text/test.jsonl", "07fdc71bf32fb44b14bf90e7bc1d63fa1126c917f3a3b803ddad965bc32cf752"),
    "human-deepseek.jsonl": ("FAIDSet-original-format/human---deepseek-text/test.jsonl", "4faeb257c6463971d1a32206de894fc450aaec5a331c1f5520433e8d6507287d"),
}


@dataclass(frozen=True)
class FaidTrial:
    cause: str
    family: str
    text: str
    source_file: str
    row_index: int


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fetch_test_split(output_dir: Path) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest = {}
    for name, (relative, expected) in FILES.items():
        target = output_dir / name
        if not target.exists() or _sha256(target) != expected:
            urllib.request.urlretrieve(f"{BASE_URL}/{relative}", target)
        actual = _sha256(target)
        if actual != expected:
            raise RuntimeError(f"checksum mismatch for {name}: {actual}")
        manifest[name] = {"relative_path": relative, "sha256": actual}
    payload = {"dataset": "ngocminhta/FAIDSet", "revision": REVISION, "files": manifest}
    (output_dir / "manifest.json").write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return payload


def _eligible_english(text: str, min_words: int) -> bool:
    letters = [char for char in text if char.isalpha()]
    ascii_ratio = sum(char.isascii() for char in letters) / max(1, len(letters))
    return ascii_ratio >= 0.98 and len(re.findall(r"[A-Za-z]+(?:'[A-Za-z]+)?", text)) >= min_words


def _deterministic_take(rows: Sequence[FaidTrial], count: int) -> list[FaidTrial]:
    ordered = sorted(rows, key=lambda row: hashlib.sha256(row.text.encode()).hexdigest())
    if len(ordered) < count:
        raise ValueError(f"need {count} eligible rows, found {len(ordered)}")
    return ordered[:count]


def load_locked_trials(data_dir: Path, *, per_family: int = 80, min_words: int = 80) -> list[FaidTrial]:
    def read(name: str, cause: str, family: str) -> list[FaidTrial]:
        rows = []
        for index, line in enumerate((data_dir / name).read_text(encoding="utf-8").splitlines()):
            text = str(json.loads(line)["text"]).strip()
            if _eligible_english(text, min_words):
                rows.append(FaidTrial(cause, family, text, name, index))
        return rows

    trials = []
    human = read("human.jsonl", HUMAN, "human")
    trials.extend(_deterministic_take(human, per_family * len(FAMILIES)))
    for family in FAMILIES:
        trials.extend(_deterministic_take(read(f"{family}.jsonl", DIRECT_AI, family), per_family))
        trials.extend(_deterministic_take(read(f"human-{family}.jsonl", COLLABORATIVE, family), per_family))
    hashes = [hashlib.sha256(trial.text.encode()).hexdigest() for trial in trials]
    if len(hashes) != len(set(hashes)):
        raise ValueError("FAID locked trials contain duplicate texts")
    return trials


def _summarize(trials: Sequence[FaidTrial], scores: np.ndarray, threshold: float) -> dict:
    causes = np.asarray([trial.cause for trial in trials], dtype=object)
    selected = scores >= threshold
    ai = causes != HUMAN
    report = {
        "auc_any_ai_involvement": round(float(roc_auc_score(ai, scores)), 4),
        "auc_direct_ai_vs_human": round(
            float(roc_auc_score(ai[causes != COLLABORATIVE], scores[causes != COLLABORATIVE])), 4
        ),
        "auc_collaborative_vs_human": round(
            float(roc_auc_score(ai[causes != DIRECT_AI], scores[causes != DIRECT_AI])), 4
        ),
        "threshold": threshold,
        "human_fpr": round(float(selected[causes == HUMAN].mean()), 4),
        "direct_ai_recall": round(float(selected[causes == DIRECT_AI].mean()), 4),
        "collaborative_recall": round(float(selected[causes == COLLABORATIVE].mean()), 4),
    }
    report["by_family"] = {}
    for family in FAMILIES:
        mask = np.asarray([trial.family == family for trial in trials])
        report["by_family"][family] = {
            "direct_ai_recall": round(float(selected[mask & (causes == DIRECT_AI)].mean()), 4),
            "collaborative_recall": round(float(selected[mask & (causes == COLLABORATIVE)].mean()), 4),
        }
    return report


def _local_human_calibration(
    trials: Sequence[FaidTrial],
    scores: np.ndarray,
    *,
    two_sided: bool,
) -> dict:
    """Calibrate on one hash-disjoint half of local human controls only."""

    causes = np.asarray([trial.cause for trial in trials], dtype=object)
    human = causes == HUMAN
    calibration = np.asarray(
        [
            human[index]
            and int(hashlib.sha256(trial.text.encode()).hexdigest()[:8], 16) % 2 == 0
            for index, trial in enumerate(trials)
        ]
    )
    locked = ~calibration
    if two_sided:
        center = float(np.median(scores[calibration]))
        scale = float(np.median(np.abs(scores[calibration] - center)))
        scale = max(scale, 1e-9)
        evidence = np.abs(scores - center) / scale
    else:
        center, scale = None, None
        evidence = scores
    threshold = threshold_at_fpr(evidence[calibration], target_fpr=0.01)
    report = _summarize(
        [trial for index, trial in enumerate(trials) if locked[index]],
        evidence[locked],
        threshold,
    )
    report.update(
        {
            "calibration_human_support": int(calibration.sum()),
            "locked_human_support": int((locked & human).sum()),
            "two_sided": two_sided,
            "center": center,
            "scale_mad": scale,
        }
    )
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    fetch = subparsers.add_parser("fetch")
    fetch.add_argument("--output-dir", required=True, type=Path)
    run = subparsers.add_parser("run")
    run.add_argument("--data-dir", required=True, type=Path)
    run.add_argument("--output", required=True, type=Path)
    run.add_argument("--workers", type=int, default=4)
    run.add_argument("--per-family", type=int, default=80)
    run.add_argument("--ai-threshold", required=True, type=float)
    run.add_argument("--curvature-threshold", type=float)
    run.add_argument("--curvature-model", default="EleutherAI/gpt-neo-2.7B")
    run.add_argument("--device", default="mps")
    args = parser.parse_args()
    if args.command == "fetch":
        print(json.dumps(fetch_test_split(args.output_dir), indent=2))
        return 0

    fetch_test_split(args.data_dir)
    trials = load_locked_trials(args.data_dir, per_family=args.per_family)
    texts = [trial.text for trial in trials]
    trial_hashes = np.asarray([hashlib.sha256(text.encode()).hexdigest() for text in texts])
    signal_path = args.output.with_suffix(".signals.npz")
    ai_scores = None
    if signal_path.exists():
        cached = np.load(signal_path, allow_pickle=False)
        if "trial_hashes" in cached and np.array_equal(cached["trial_hashes"], trial_hashes):
            ai_scores = cached["ai_likelihood"]
    if ai_scores is None:
        features = _extract_parallel(texts, args.workers, "faid-external-lock")
        ai_scores = predict_ai_likelihood_batch(features)
        if ai_scores is None:
            raise RuntimeError("frozen AI-likelihood artifact unavailable")
    payload = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "dataset_revision": REVISION,
        "scope": "untouched FAIDSet test split; collaborative is not equated with humanized AI",
        "n": len(trials),
        "counts": dict(Counter(trial.cause for trial in trials)),
        "frozen_ai_likelihood": _summarize(trials, np.asarray(ai_scores), args.ai_threshold),
        "locally_calibrated_ai_likelihood": _local_human_calibration(
            trials, np.asarray(ai_scores), two_sided=False
        ),
    }
    curvature = None
    if args.curvature_threshold is not None:
        curvature = score_texts(
            texts,
            model_name=args.curvature_model,
            cache_path=args.output.with_suffix(".curvature_scores.npz"),
            device=args.device,
            max_tokens=256,
        )
        payload["probability_curvature"] = _summarize(trials, curvature, args.curvature_threshold)
        payload["locally_calibrated_curvature_anomaly"] = _local_human_calibration(
            trials, curvature, two_sided=True
        )
    signal_payload = {
        "trial_hashes": trial_hashes,
        "ai_likelihood": np.asarray(ai_scores),
    }
    if curvature is not None:
        signal_payload["curvature"] = curvature
    np.savez_compressed(args.output.with_suffix(".signals.npz"), **signal_payload)
    signal_gates = {}
    for signal, report in payload.items():
        if not isinstance(report, dict) or "human_fpr" not in report:
            continue
        failures = []
        if report["human_fpr"] > 0.01:
            failures.append("human_fpr>0.01")
        if min(report["direct_ai_recall"], report["collaborative_recall"]) < 0.50:
            failures.append("recall<0.50")
        signal_gates[signal] = {"passed": not failures, "failures": failures}
    payload["promotion_gate"] = {
        "passed": any(gate["passed"] for gate in signal_gates.values()),
        "signals": signal_gates,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
