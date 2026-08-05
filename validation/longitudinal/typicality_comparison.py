"""Does trend_aware_typicality change same-author recognition / impostor
rejection versus the flat, recency-weighted reference `state.loo_distances`
uses today?

NOT a locked benchmark -- two authors, a handful of trials. Real
chronological corpora at a scale that could support an accuracy/FPR claim
don't exist yet (see build_typicality_corpus.py's docstring). This answers
a narrower, honest question: on real dated prose, does the new mechanism
move in the expected direction -- reading a genuine LATER work as MORE
typical than the flat model does, without becoming more permissive of a
different author's writing?

Run from the repository root:
    .venv/bin/python -m validation.longitudinal.typicality_comparison
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from original.features.pipeline import feature_vector  # noqa: E402
from original.quantum.longitudinal import (  # noqa: E402
    LongitudinalConfig,
    trend_aware_typicality,
)
from original.quantum.state import BaselineSample, StudentState  # noqa: E402
from original.quantum.typicality import band_from_p, p_central, p_far  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
MANIFEST = Path(__file__).with_name("typicality_manifest.json")
CORPUS = Path(__file__).with_name("typicality_corpus")
OUTPUT = Path(__file__).with_name("typicality_comparison_report.json")

N_PROBES_HELD_OUT = 2  # last N works per author become probes; the rest is baseline


def _flat_reading(state: StudentState, submission_vector) -> dict:
    loo = state.loo_distances
    if len(loo) < 2:
        return {"eligible": False, "reason": "insufficient_loo_samples"}
    # Mirror scoring.py's plain-z-score submission distance (not the full
    # Born-rule pipeline -- this isolates the reference-point comparison,
    # which is the only thing trend_aware_typicality changes).
    import numpy as np

    from original.constants import FEATURE_DIM
    from original.quantum.state import RECENCY_DECAY

    contributing = [s for s in state.samples if s.auth_weight > 0]
    n = len(contributing)
    weights = np.array([RECENCY_DECAY ** (n - 1 - i) for i in range(n)])
    vectors = np.stack([s.vector for s in contributing])
    mean = (weights[:, None] * vectors).sum(axis=0) / weights.sum()
    std = np.maximum(vectors.std(axis=0), max(0.005, 0.15 / (n**0.5)))
    z = np.clip((submission_vector - mean) / std, -4.0, 4.0)
    rms_z = float(np.sqrt(np.mean(z**2)))

    pf = p_far(rms_z, loo)
    pc = p_central(rms_z, loo)
    return {
        "eligible": True,
        "p_far": pf,
        "p_central": pc,
        "band": band_from_p(pf, pc),
        "loo_n": len(loo),
    }


def run() -> dict:
    manifest = json.loads(MANIFEST.read_text())
    by_author: dict[str, list[dict]] = {}
    for entry in manifest["entries"]:
        by_author.setdefault(entry["author_id"], []).append(entry)
    for entries in by_author.values():
        entries.sort(key=lambda e: e["submitted_at"])

    config = LongitudinalConfig(enabled=True, min_samples_for_trend=6, min_span_days=60)

    states: dict[str, StudentState] = {}
    probes: dict[str, list[dict]] = {}
    vectors_cache: dict[str, "list"] = {}
    for author_id, entries in by_author.items():
        history, held_out = entries[:-N_PROBES_HELD_OUT], entries[-N_PROBES_HELD_OUT:]
        samples = []
        vecs = {}
        for entry in history:
            text = (CORPUS / entry["filename"]).read_text(encoding="utf-8")
            vector = feature_vector(text)
            vecs[entry["filename"]] = vector
            samples.append(
                BaselineSample(
                    text=text,
                    vector=vector,
                    provenance="verified",
                    auth_weight=1.0,
                    assignment=entry["prompt"],
                    submitted_at=entry["submitted_at"],
                    word_count=entry["word_count"],
                    genre=entry["genre"],
                )
            )
        states[author_id] = StudentState(author_id, samples=samples)
        vectors_cache[author_id] = vecs
        probes[author_id] = held_out

    results = {"genuine": [], "impostor": []}
    for target_author, state in states.items():
        for probe_author, entries in probes.items():
            for entry in entries:
                text = (CORPUS / entry["filename"]).read_text(encoding="utf-8")
                vector = feature_vector(text)
                flat = _flat_reading(state, vector)
                trend = trend_aware_typicality(
                    state,
                    vector,
                    submitted_at=entry["submitted_at"],
                    submission_genre=entry["genre"],
                    config=config,
                )
                row = {
                    "target_author": target_author,
                    "probe_author": probe_author,
                    "probe_title": entry["prompt"],
                    "probe_date": entry["submitted_at"],
                    "flat": flat,
                    "trend_aware": trend.to_dict() if trend is not None else None,
                }
                bucket = "genuine" if probe_author == target_author else "impostor"
                results[bucket].append(row)

    def _band_counts(rows, key):
        counts: dict[str, int] = {}
        for row in rows:
            reading = row[key]
            band = reading.get("band") if reading and reading.get("eligible") else "ineligible"
            counts[band] = counts.get(band, 0) + 1
        return counts

    summary = {
        "n_genuine_trials": len(results["genuine"]),
        "n_impostor_trials": len(results["impostor"]),
        "flat_genuine_bands": _band_counts(results["genuine"], "flat"),
        "trend_aware_genuine_bands": _band_counts(results["genuine"], "trend_aware"),
        "flat_impostor_bands": _band_counts(results["impostor"], "flat"),
        "trend_aware_impostor_bands": _band_counts(results["impostor"], "trend_aware"),
        "caveat": (
            "n is far too small to support an accuracy/FPR claim -- this is a "
            "direction check, not a locked benchmark. See module docstring."
        ),
    }
    report = {"summary": summary, "trials": results}
    OUTPUT.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    return report


if __name__ == "__main__":
    result = run()
    print(json.dumps(result["summary"], indent=2))
    print(f"\nwrote {OUTPUT.relative_to(ROOT)}")
