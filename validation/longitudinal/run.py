"""Evaluate whether drift adjustment reduces genuine chronological false alarms.

Input uses the normal validation manifest shape with one required addition:
every eligible authentic entry must have ``submitted_at`` (ISO date).  Entries
are ordered chronologically per author; each held-out essay is scored using
only earlier authentic essays.

Example:
    .venv/bin/python -m validation.longitudinal.run \
      --corpus validation/student_corpus \
      --manifest validation/student_manifest.json \
      --output validation/benchmarks/longitudinal.json

This runner never updates production thresholds.  Its report is evidence for
or against a later promotion decision.
"""

from __future__ import annotations

import argparse
import json
import random
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

import numpy as np

from original.constants import ALL_FEATURE_CODES
from original.features.pipeline import feature_vector
from original.quantum.longitudinal import LongitudinalConfig, analyze_longitudinal_drift
from original.quantum.scoring import ScoringConfig, score
from original.quantum.state import BaselineSample, StudentState


@dataclass
class ProbeResult:
    author_id: str
    filename: str
    submitted_at: str
    static_deviation: float
    predicted_current_deviation: float | None
    drift_relief: float | None
    selected_model: str
    interpretation: str


def _parse_date(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _rate(values: list[float], threshold: float) -> float | None:
    return sum(value >= threshold for value in values) / len(values) if values else None


def _summary(results: list[ProbeResult]) -> dict:
    static = [result.static_deviation for result in results]
    current = [
        result.predicted_current_deviation
        for result in results
        if result.predicted_current_deviation is not None
    ]
    thresholds = (0.40, 0.60, 0.75)
    return {
        "n_probes": len(results),
        "n_longitudinal_eligible": len(current),
        "mean_static_deviation": float(np.mean(static)) if static else None,
        "mean_predicted_current_deviation": float(np.mean(current)) if current else None,
        "mean_drift_relief": float(
            np.mean([r.drift_relief for r in results if r.drift_relief is not None])
        )
        if current
        else None,
        "genuine_flag_rate": {
            str(threshold): {
                "static": _rate(static, threshold),
                "drift_adjusted": _rate(current, threshold),
            }
            for threshold in thresholds
        },
        "selected_models": {
            model: sum(result.selected_model == model for result in results)
            for model in sorted({result.selected_model for result in results})
        },
        "interpretations": {
            label: sum(result.interpretation == label for result in results)
            for label in sorted({result.interpretation for result in results})
        },
    }


def _permutation_false_selection(
    samples: list[BaselineSample],
    *,
    repeats: int,
    seed: int,
    config: LongitudinalConfig,
) -> float | None:
    """Estimate how often arbitrary chronology selects gradual drift."""
    if len(samples) < config.min_samples_for_trend or repeats <= 0:
        return None
    rng = random.Random(seed)
    selected = 0
    dated = sorted(samples, key=lambda sample: _parse_date(sample.submitted_at))
    dates = [sample.submitted_at for sample in dated]
    probe = dated[-1].vector
    for _ in range(repeats):
        shuffled = list(dated)
        rng.shuffle(shuffled)
        state = StudentState("permutation")
        for sample, submitted_at in zip(shuffled, dates):
            state.add_sample(
                BaselineSample(
                    text=sample.text,
                    vector=sample.vector,
                    provenance=sample.provenance,
                    auth_weight=sample.auth_weight,
                    submitted_at=submitted_at,
                    word_count=sample.word_count,
                    assignment=sample.assignment,
                    genre=sample.genre,
                )
            )
        analysis = analyze_longitudinal_drift(
            state, probe, submitted_at=dates[-1], config=config
        )
        selected += bool(analysis and analysis.selected_model == "gradual_drift")
    return selected / repeats


def run(
    corpus: Path,
    manifest_path: Path,
    *,
    permutation_repeats: int = 200,
    seed: int = 20260804,
) -> dict:
    manifest = json.loads(manifest_path.read_text())
    entries: dict[str, list[dict]] = defaultdict(list)
    for entry in manifest.get("entries", []):
        if entry.get("label") != "authentic" or not entry.get("submitted_at"):
            continue
        entries[entry["author_id"]].append(entry)

    config = LongitudinalConfig(enabled=True)
    results: list[ProbeResult] = []
    permutation_rates: dict[str, float | None] = {}
    for author_id, author_entries in sorted(entries.items()):
        author_entries.sort(key=lambda entry: _parse_date(entry["submitted_at"]))
        samples: list[BaselineSample] = []
        for entry in author_entries:
            text = (corpus / entry["filename"]).read_text(errors="replace")
            vector = feature_vector(text)
            samples.append(
                BaselineSample(
                    text=text,
                    vector=vector,
                    provenance="verified",
                    auth_weight=1.0,
                    assignment=entry.get("prompt", ""),
                    submitted_at=entry["submitted_at"],
                    word_count=entry.get("word_count") or len(text.split()),
                    genre=entry.get("genre"),
                )
            )

        for probe_index in range(config.min_samples_for_trend, len(samples)):
            state = StudentState(author_id, samples=list(samples[:probe_index]))
            probe_sample = samples[probe_index]
            probe_vector = probe_sample.vector
            feature_dict = {
                code: float(value)
                for code, value in zip(ALL_FEATURE_CODES, probe_vector)
            }
            static = score(
                state,
                probe_vector,
                feature_dict,
                submission_id=author_entries[probe_index]["filename"],
                n_tokens=probe_sample.word_count or 300,
                scoring_config=ScoringConfig(),
            )
            analysis = analyze_longitudinal_drift(
                state,
                probe_vector,
                submitted_at=probe_sample.submitted_at,
                submission_genre=probe_sample.genre,
                config=config,
            )
            results.append(
                ProbeResult(
                    author_id=author_id,
                    filename=author_entries[probe_index]["filename"],
                    submitted_at=probe_sample.submitted_at,
                    static_deviation=static.authorship.deviation_score,
                    predicted_current_deviation=(
                        analysis.predicted_current_deviation if analysis else None
                    ),
                    drift_relief=analysis.drift_relief if analysis else None,
                    selected_model=analysis.selected_model if analysis else "disabled",
                    interpretation=analysis.interpretation if analysis else "disabled",
                )
            )

        permutation_rates[author_id] = _permutation_false_selection(
            samples,
            repeats=permutation_repeats,
            seed=seed,
            config=config,
        )

    return {
        "model_version": "longitudinal-ridge-v1",
        "manifest": str(manifest_path),
        "seed": seed,
        "permutation_repeats": permutation_repeats,
        "summary": _summary(results),
        "permutation_false_drift_selection_by_author": permutation_rates,
        "results": [asdict(result) for result in results],
        "limitations": [
            "Genuine chronological probes only; pair with matched-peer impostor verification.",
            "Thresholds are reported, never updated automatically.",
            "Authors without ISO submitted_at metadata are excluded.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--permutations", type=int, default=200)
    parser.add_argument("--seed", type=int, default=20260804)
    args = parser.parse_args()
    report = run(
        args.corpus,
        args.manifest,
        permutation_repeats=args.permutations,
        seed=args.seed,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report["summary"], indent=2))


if __name__ == "__main__":
    main()
