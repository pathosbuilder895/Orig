"""Deterministic 15-week TermSim curriculum script generation."""
from __future__ import annotations

import hashlib
import json
import random

SCENARIOS = ("HONEST", "GHOST", "AI", "HYBRID", "COLDSTART", "TRANSFER")


def generate(seed: int, cohort_sizes=(3, 8, 25), weeks=15) -> list[dict]:
    rng = random.Random(seed)
    events = []
    for cohort_size in cohort_sizes:
        tenant = f"termsim-{cohort_size}"
        for index in range(cohort_size):
            student = f"{tenant}:student-{index:03d}"
            scenario = SCENARIOS[index % len(SCENARIOS)]
            baseline_count = 2 if scenario == "COLDSTART" else 3
            for number in range(baseline_count):
                events.append({"tenant": tenant, "student": student, "week": 0,
                               "kind": "baseline", "document_index": number,
                               "scenario": scenario, "authenticated": True})
            onset = rng.randint(5, 9) if scenario in {"GHOST", "AI", "HYBRID"} else None
            for number, week in enumerate(range(1, weeks, 2)):
                events.append({"tenant": tenant, "student": student, "week": week,
                               "kind": "score", "document_index": baseline_count + number,
                               "scenario": scenario, "onset_week": onset,
                               "after_onset": onset is not None and week >= onset,
                               "proxy": scenario == "HYBRID"})
    return sorted(events, key=lambda e: (e["week"], e["tenant"], e["student"], e["kind"]))


def dumps(events: list[dict]) -> str:
    return json.dumps(events, sort_keys=True, separators=(",", ":"))


def script_hash(events: list[dict]) -> str:
    return hashlib.sha256(dumps(events).encode()).hexdigest()
