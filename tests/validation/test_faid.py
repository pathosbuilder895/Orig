import json

import numpy as np

from validation.cause.faid import (
    COLLABORATIVE,
    DIRECT_AI,
    HUMAN,
    _local_human_calibration,
    load_locked_trials,
)


def _write(path, prefix: str, count: int) -> None:
    rows = []
    for index in range(count):
        text = f"{prefix} {index} " + " ".join(f"word{item}" for item in range(90))
        rows.append(json.dumps({"text": text}))
    path.write_text("\n".join(rows) + "\n", encoding="utf-8")


def test_locked_trials_are_balanced_unique_and_deterministic(tmp_path) -> None:
    _write(tmp_path / "human.jsonl", "human", 12)
    for family in ("gpt", "gemini", "llama", "deepseek"):
        _write(tmp_path / f"{family}.jsonl", f"direct {family}", 4)
        _write(tmp_path / f"human-{family}.jsonl", f"collaborative {family}", 4)
    first = load_locked_trials(tmp_path, per_family=3)
    second = load_locked_trials(tmp_path, per_family=3)
    assert first == second
    assert len(first) == 36
    assert sum(row.cause == HUMAN for row in first) == 12
    assert sum(row.cause == DIRECT_AI for row in first) == 12
    assert sum(row.cause == COLLABORATIVE for row in first) == 12
    assert len({row.text for row in first}) == len(first)


def test_local_human_calibration_never_uses_ai_for_threshold(tmp_path) -> None:
    _write(tmp_path / "human.jsonl", "human", 80)
    for family in ("gpt", "gemini", "llama", "deepseek"):
        _write(tmp_path / f"{family}.jsonl", f"direct {family}", 4)
        _write(tmp_path / f"human-{family}.jsonl", f"collaborative {family}", 4)
    trials = load_locked_trials(tmp_path, per_family=3)
    scores = np.asarray([0.0 if row.cause == HUMAN else 100.0 for row in trials])
    report = _local_human_calibration(trials, scores, two_sided=False)
    assert report["human_fpr"] == 0.0
    assert report["direct_ai_recall"] == 1.0
    assert report["collaborative_recall"] == 1.0
