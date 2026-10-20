"""
Regenerate tests/fixtures/study_synthetic.csv.

    python tests/fixtures/make_study_synthetic.py

FICTIONAL DATA. Every row is invented by this script: 20 synthetic students
("synth-01" to "synth-20"), two natural and two shadow attempts scored against
each, with made-up scores and feature values. It exists so the study analysis
and proposal scripts can be tested end to end. No number derived from it says
anything about Original or about students (NORTH_STAR rule 2).

Columns follow validation/study_contract.py, contract study-csv-v2.

Shape, chosen to exercise every branch of validation/study_eval.py:
  - deviation_score (higher = less consistent) centres near 0.25 on natural
    attempts and 0.44 on shadow ones, plus a per-student offset (so attempts
    cluster by student, as real ones do). The spread is chosen so the
    in-sample cut-off meets the 5% cap and the leave-one-student-out re-run
    does not (tests/test_propose_thresholds.py shows why G-S1 reads only the
    latter);
  - authorship_probability sits near 1.06 - deviation_score, and the verdict
    follows the live Collections rule on it (FLAGGED when
    round(100 x probability) < 70, Exam.jsx), so the eval's verdict check
    finds no disagreement;
  - synth-01 and synth-02 have 2 approved reference samples, so every attempt
    scored against them is INCONCLUSIVE (NORTH_STAR rule 3);
  - one natural attempt is unscored (SUBMITTED with no score);
  - baseline counts 2-12 and word counts 90-900 cover every report bin;
  - two feature columns are shifted on shadow attempts, four are noise, and
    two are non-measurable (a comparison code and the structurally blank
    catastrophe_index) so the measurability exclusion runs.

Uses the standard-library random module with a fixed seed, so the bytes do
not depend on the numpy version; tests/test_study_eval.py checks that
regenerating gives the committed file exactly.
"""

from __future__ import annotations

import csv
import io
import math
import random
from pathlib import Path

SEED = 20261013
OUT = Path(__file__).resolve().parent / "study_synthetic.csv"
LIVE_FLAG_BELOW = 70  # demo/bluebook/Exam.jsx bbSealStatus
NATURAL = (0.25, 0.10)  # deviation_score centre and sd
SHADOW = (0.44, 0.12)
PROB_SHIFT = 0.06  # authorship_probability ~ 1 - deviation_score + PROB_SHIFT
OFFSET_SD = 0.04  # per-student offset
STUDENTS = [f"synth-{i:02d}" for i in range(1, 21)]
BASELINE_SIZES = [2, 2, 3, 3, 4, 4, 5, 5, 6, 6, 7, 8, 8, 9, 10, 10, 11, 12, 12, 12]
FEATURES = {
    # code: (natural mean, sd, shadow shift)
    "type_token_ratio": (0.52, 0.05, 0.0),
    "mean_sentence_length": (19.0, 3.0, 4.5),
    "function_word_ratio": (0.47, 0.03, 0.0),
    "avg_word_length": (4.7, 0.25, 0.0),
    "hedging_density": (0.020, 0.006, -0.008),
    "discourse_marker_density": (0.031, 0.008, 0.0),
    "char_trigram_profile_divergence": (0.5, 0.0, 0.0),
    "catastrophe_index": (0.5, 0.0, 0.0),
}
HEADER = [
    "submission_id",
    "exam_id",
    "student_id",
    "study_label",
    "imitated_student_id",
    "claimed_student_id",
    "verdict",
    "deviation_score",
    "authorship_probability",
    "baseline_count",
    "word_count",
] + [f"f_{c}" for c in FEATURES]


def _clip(x: float) -> float:
    return max(0.0, min(1.0, x))


def _collections_score(prob: float) -> int:
    """Math.round(prob * 100), as Exam.jsx does (halves round up)."""
    return max(0, min(100, math.floor(prob * 100 + 0.5)))


def build() -> str:
    rng = random.Random(SEED)
    offsets = {s: rng.gauss(0.0, OFFSET_SD) for s in STUDENTS}
    rows = []
    n = 0
    for i, claimed in enumerate(STUDENTS):
        base = BASELINE_SIZES[i]
        attempts = [("natural", claimed, None), ("natural", claimed, None)]
        for step in (1, 5):
            attempts.append(("shadow", STUDENTS[(i + step) % len(STUDENTS)], claimed))
        for label, writer, imitated in attempts:
            n += 1
            centre, sd = NATURAL if label == "natural" else SHADOW
            deviation = _clip(rng.gauss(centre + offsets[claimed], sd))
            prob = _clip(1.0 - deviation + PROB_SHIFT + rng.gauss(0.0, 0.02))
            feats = {}
            for code, (mu, f_sd, shift) in FEATURES.items():
                v = (
                    mu
                    + (shift if label == "shadow" else 0.0)
                    + (rng.gauss(0.0, f_sd) if f_sd else 0.0)
                )
                feats[code] = f"{v:.4f}"
            words = rng.randint(90, 900)
            if base < 3:
                verdict, score_text, prob_text = "INCONCLUSIVE", "", ""
            elif claimed == "synth-07" and label == "natural" and n % 2 == 0:
                verdict, score_text, prob_text = "SUBMITTED", "", ""
            else:
                flagged = _collections_score(prob) < LIVE_FLAG_BELOW
                verdict = "FLAGGED" if flagged else "SUBMITTED"
                score_text, prob_text = f"{deviation:.4f}", f"{prob:.4f}"
            rows.append(
                [
                    f"sub-{n:03d}",
                    "synth-exam-1",
                    writer,
                    label,
                    imitated or "",
                    claimed,
                    verdict,
                    score_text,
                    prob_text,
                    base,
                    words,
                ]
                + [feats[c] for c in FEATURES]
            )
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(HEADER)
    w.writerows(rows)
    return buf.getvalue()


if __name__ == "__main__":
    OUT.write_text(build())
    print(f"wrote {OUT}")
