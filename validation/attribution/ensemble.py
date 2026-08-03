"""
validation/attribution/ensemble.py — agreement routing across attribution
engines. 2-of-N agree → attribute, naming the engines; otherwise None →
"unknown — manual review". Never forces a top-1 answer.
"""
from __future__ import annotations

from collections import Counter
from itertools import combinations


def ensemble_vote(predictions: dict[str, str]) -> tuple[str | None, str]:
    if not predictions:
        return None, "no engine predictions — manual review"
    counts = Counter(predictions.values())
    top_author, top_count = counts.most_common(1)[0]
    if top_count >= 2:
        agreeing = sorted(e for e, p in predictions.items() if p == top_author)
        return top_author, f"{top_count}-of-{len(predictions)} agree ({', '.join(agreeing)})"
    return None, "engines disagree — manual review"


def pairwise_agreement(per_essay_predictions: list[dict[str, str]]) -> dict[str, float]:
    if not per_essay_predictions:
        return {}
    engines = sorted(per_essay_predictions[0])
    out: dict[str, float] = {}
    for a, b in combinations(engines, 2):
        matches = sum(1 for row in per_essay_predictions if row[a] == row[b])
        out[f"{a}|{b}"] = matches / len(per_essay_predictions)
    return out
