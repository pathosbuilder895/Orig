"""Pure deployment-outcome metrics over TermSim event dictionaries."""
from __future__ import annotations

import math
from collections import defaultdict

_ACTION = {"no_action": 0, "monitor": 1, "schedule_conversation": 2, "escalate": 3}


def wilson(successes: int, n: int) -> list[float] | None:
    if n == 0:
        return None
    z = 1.96
    p = successes / n
    denominator = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denominator
    half = z * math.sqrt((p * (1 - p) + z * z / (4 * n)) / n) / denominator
    return [max(0.0, centre - half), min(1.0, centre + half)]


def rate(successes: int, n: int) -> dict:
    return {"successes": successes, "n": n, "rate": successes / n if n else None,
            "wilson_ci95": wilson(successes, n)}


def _at_least(action: str, threshold: str) -> bool:
    return _ACTION.get(action, 0) >= _ACTION[threshold]


def compute(events: list[dict]) -> dict:
    honest_by_student: dict[str, list[dict]] = defaultdict(list)
    for event in events:
        if event.get("scenario") == "HONEST" and event.get("kind") == "score":
            honest_by_student[event["student"]].append(event)
    honest_term = {}
    for threshold in ("monitor", "schedule_conversation", "escalate"):
        flagged = sum(
            any(_at_least(e["action"], threshold) for e in student_events)
            for student_events in honest_by_student.values()
        )
        honest_term[threshold] = rate(flagged, len(honest_by_student))

    detections = {}
    for scenario in ("GHOST", "AI", "HYBRID"):
        scenario_events = [e for e in events if e.get("scenario") == scenario
                           and e.get("kind") == "score" and e.get("after_onset")]
        by_student: dict[str, list[dict]] = defaultdict(list)
        for event in scenario_events:
            by_student[event["student"]].append(event)
        detections[scenario] = {}
        for threshold in ("monitor", "schedule_conversation"):
            delays = []
            for student_events in by_student.values():
                ordered = sorted(student_events, key=lambda e: e["week"])
                hit = next((e for e in ordered if _at_least(e["action"], threshold)), None)
                if hit:
                    delays.append(hit["week"] - hit["onset_week"])
            detections[scenario][threshold] = {
                "caught": rate(len(delays), len(by_student)),
                "median_delay_weeks_among_caught": (
                    sorted(delays)[len(delays) // 2] if delays else None
                ),
                "censored": len(by_student) - len(delays),
            }

    growth = []
    for student_events in honest_by_student.values():
        points = [(e.get("baseline_count"), e.get("deviation_score")) for e in student_events]
        points = [(float(x), float(y)) for x, y in points if x is not None and y is not None]
        if len(points) >= 2 and len({x for x, _ in points}) > 1:
            x_mean = sum(x for x, _ in points) / len(points)
            y_mean = sum(y for _, y in points) / len(points)
            growth.append(sum((x-x_mean)*(y-y_mean) for x, y in points)
                          / sum((x-x_mean)**2 for x, _ in points))
    return {
        "honest_term_flag_probability": honest_term,
        "time_to_detection": detections,
        "baseline_growth_slope": {
            "n_students": len(growth),
            "mean": sum(growth) / len(growth) if growth else None,
            "per_student": growth,
        },
    }
