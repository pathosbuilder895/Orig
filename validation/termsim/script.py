"""Deterministic 15-week TermSim curriculum script generation.

Events name intent, not text: a document role ("home" = the persona's main
body of work, "away" = a held-out work by the same author) plus an ordinal,
resolved by personas.CorpusTextResolver. That separation is what makes the
scenarios controlled contrasts:

- HONEST draws home-work only, except one scripted mid-term curriculum
  shift (an away-work submission) when the persona has a second work —
  the cross-topic event every real term contains.
- TRANSFER is the SAME persona writing from a held-out work all term
  (baselines never covered it) — same author, shifted material. This is a
  work/topic transfer; a true cross-genre same-author corpus is not
  committable (Plan 02's Lewis corpus), so genre transfer stays out of v1.
- GHOST swaps in a different persona (same corpus register when possible)
  from a sampled onset week.
"""
from __future__ import annotations

import hashlib
import json
import random

SCENARIOS = ("HONEST", "GHOST", "AI", "HYBRID", "COLDSTART", "TRANSFER")
CURRICULUM_SHIFT_WEEK = 7

# Each cohort is ONE tenant with mixed scenarios (the plan's "each student is
# assigned exactly one"), so null pools and priors are built from a realistic
# mixed class rather than a tenant of identical scenarios. HONEST is
# deliberately over-represented — it is the denominator of T-1/T-3/T-4 —
# and GHOST comes second for T-2's detection floor.
SCENARIO_PATTERN = ("HONEST", "GHOST", "COLDSTART", "HONEST", "AI", "TRANSFER",
                    "HONEST", "GHOST", "COLDSTART", "HONEST", "HYBRID", "TRANSFER")


def _persona_meta(personas) -> list[dict]:
    """Accept manifest persona dicts (or ids, for capability-free scripts)."""
    meta = []
    for p in personas or []:
        if isinstance(p, str):
            meta.append({"id": p, "n_groups": 1})
        else:
            meta.append({"id": p["id"], "n_groups": p.get("n_groups", 1)})
    return meta


def generate(seed: int, cohort_sizes=(3, 8, 25), weeks=15,
             personas: list | None = None,
             scenarios: tuple[str, ...] = SCENARIOS) -> list[dict]:
    rng = random.Random(seed)
    meta = _persona_meta(personas)
    multi_work = [m for m in meta if m["n_groups"] >= 2]
    events = []
    for cohort_size in cohort_sizes:
        tenant = f"termsim-cohort-{cohort_size}"
        coldstart_ordinal = 0
        for index in range(cohort_size):
            scenario = SCENARIO_PATTERN[index % len(SCENARIO_PATTERN)]
            if scenario == "COLDSTART":
                coldstart_ordinal += 1
            if scenario not in scenarios:
                continue
            student = f"{tenant}:student-{index:03d}"
            # Seeded, not a modulo of (cohort_size, index): a fixed formula
            # here would make every scenario whose script never otherwise
            # touches rng (HONEST, COLDSTART, TRANSFER's own persona pick)
            # bit-identical across seeds, defeating the point of running
            # multiple seeds — cross-seed "stability" would just be
            # re-measuring the same cohort three times.
            if scenario == "TRANSFER" and multi_work:
                chosen = multi_work[rng.randrange(len(multi_work))]
            elif meta:
                chosen = meta[rng.randrange(len(meta))]
            else:
                chosen = {"id": None, "n_groups": 1}
            persona, n_groups = chosen["id"], chosen["n_groups"]
            same_register = [m["id"] for m in meta
                             if m["id"] != persona and str(m["id"]).split(":")[0]
                             == str(persona).split(":")[0]]
            alternatives = same_register or [m["id"] for m in meta
                                             if m["id"] != persona]
            substitute = (alternatives[rng.randrange(len(alternatives))]
                          if alternatives else persona)
            # COLDSTART alternates 1/2 onboarding baselines (below both
            # TRAJECTORY_MIN_SAMPLES and the measured-sigma regime);
            # everything else gets the modal pilot profile of 3.
            baseline_count = (1 + (coldstart_ordinal - 1) % 2
                              if scenario == "COLDSTART" else 3)
            for number in range(baseline_count):
                events.append({"tenant": tenant, "student": student, "week": 0,
                               "kind": "baseline", "scenario": scenario,
                               "authenticated": True, "persona": persona,
                               "source_persona": persona, "source_kind": "persona",
                               "doc_role": "home", "doc_number": number})
            onset = rng.randint(5, 9) if scenario in {"GHOST", "AI", "HYBRID"} else None
            for number, week in enumerate(range(1, weeks, 2)):
                after_onset = onset is not None and week >= onset
                transfer = scenario == "TRANSFER"
                shift = (not transfer and not after_onset and n_groups >= 2
                         and week == CURRICULUM_SHIFT_WEEK)
                away = transfer or shift
                if scenario == "GHOST" and after_onset:
                    source_persona = substitute
                else:
                    source_persona = persona
                if scenario == "AI" and after_onset:
                    source_kind = "ai"
                elif scenario == "HYBRID" and after_onset:
                    source_kind = "mechanical-paraphrase"
                else:
                    source_kind = "persona"
                events.append({"tenant": tenant, "student": student, "week": week,
                               "kind": "score", "scenario": scenario,
                               "onset_week": onset, "after_onset": after_onset,
                               "proxy": scenario == "HYBRID",
                               "persona": persona,
                               "source_persona": source_persona,
                               "source_kind": source_kind,
                               "doc_role": "away" if away else "home",
                               # Home submissions continue past the onboarding
                               # draws; away pools are disjoint so they start at 0.
                               "doc_number": (baseline_count + number) if not away
                               else (number if transfer else 0),
                               "curriculum_shift": shift,
                               "genre_covered_by_baseline": not away})
    return sorted(events, key=lambda e: (e["week"], e["tenant"], e["student"], e["kind"]))


def dumps(events: list[dict]) -> str:
    return json.dumps(events, sort_keys=True, separators=(",", ":"))


def script_hash(events: list[dict]) -> str:
    return hashlib.sha256(dumps(events).encode()).hexdigest()
