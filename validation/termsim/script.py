"""Deterministic 15-week TermSim curriculum script generation."""
from __future__ import annotations

import hashlib
import json
import random

SCENARIOS = ("HONEST", "GHOST", "AI", "HYBRID", "COLDSTART", "TRANSFER")


def generate(seed: int, cohort_sizes=(3, 8, 25), weeks=15,
             persona_ids: list[str] | None = None) -> list[dict]:
    rng = random.Random(seed)
    events = []
    for cohort_size in cohort_sizes:
        tenant = f"termsim-{cohort_size}"
        for index in range(cohort_size):
            student = f"{tenant}:student-{index:03d}"
            scenario = SCENARIOS[index % len(SCENARIOS)]
            persona = persona_ids[(cohort_size + index) % len(persona_ids)] if persona_ids else None
            alternatives = [p for p in (persona_ids or []) if p != persona]
            substitute = alternatives[rng.randrange(len(alternatives))] if alternatives else persona
            baseline_count = 2 if scenario == "COLDSTART" else 3
            for number in range(baseline_count):
                events.append({"tenant": tenant, "student": student, "week": 0,
                               "kind": "baseline", "document_index": number,
                               "scenario": scenario, "authenticated": True,
                               "persona": persona, "source_persona": persona})
            onset = rng.randint(5, 9) if scenario in {"GHOST", "AI", "HYBRID"} else None
            for number, week in enumerate(range(1, weeks, 2)):
                events.append({"tenant": tenant, "student": student, "week": week,
                               "kind": "score", "document_index": baseline_count + number,
                               "scenario": scenario, "onset_week": onset,
                               "after_onset": onset is not None and week >= onset,
                               "proxy": scenario == "HYBRID",
                               "persona": persona,
                               "source_persona": (
                                   substitute if scenario in {"GHOST", "TRANSFER"}
                                   and (scenario == "TRANSFER" or (onset is not None and week >= onset))
                                   else persona
                               ),
                               "source_kind": (
                                   "ai" if scenario == "AI" and onset is not None and week >= onset
                                   else "mechanical-paraphrase" if scenario == "HYBRID"
                                   and onset is not None and week >= onset else "persona"
                               ),
                               "genre_covered_by_baseline": scenario != "TRANSFER"})
    return sorted(events, key=lambda e: (e["week"], e["tenant"], e["student"], e["kind"]))


def dumps(events: list[dict]) -> str:
    return json.dumps(events, sort_keys=True, separators=(",", ":"))


def script_hash(events: list[dict]) -> str:
    return hashlib.sha256(dumps(events).encode()).hexdigest()
