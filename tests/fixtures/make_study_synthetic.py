"""
Regenerate tests/fixtures/study_synthetic.csv.

    python tests/fixtures/make_study_synthetic.py

FICTIONAL DATA. Every row is invented by this script: 20 synthetic students
("synth-01" to "synth-20"), two natural and two shadow attempts scored against
each, with made-up scores and feature values. It exists so the study analysis
and proposal scripts can be tested end to end. No number derived from it says
anything about Original or about students (NORTH_STAR rule 2).

Shape, chosen to exercise every branch of validation/study_eval.py:
  - natural scores centre near 79, shadow near 63, plus a per-student offset
    (so attempts cluster by student, as real ones do);
  - synth-01 and synth-02 have 2 approved reference samples, so every attempt
    scored against them is INCONCLUSIVE (NORTH_STAR rule 3);
  - one natural attempt is unscored (SUBMITTED with no score);
  - baseline sizes 2-12 and word counts 90-900 cover every report bin;
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
import random
from pathlib import Path

SEED = 20261013
OUT = Path(__file__).resolve().parent / "study_synthetic.csv"
STRICT = 70
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
    "writer_student_id",
    "study_label",
    "imitated_student_id",
    "claimed_student_id",
    "status",
    "consistency_score",
    "baseline_size",
    "word_count",
] + [f"f_{c}" for c in FEATURES]


def build() -> str:
    rng = random.Random(SEED)
    offsets = {s: rng.gauss(0.0, 4.0) for s in STUDENTS}
    rows = []
    n = 0
    for i, claimed in enumerate(STUDENTS):
        base = BASELINE_SIZES[i]
        attempts = [("natural", claimed, None), ("natural", claimed, None)]
        for step in (1, 5):
            attempts.append(("shadow", STUDENTS[(i + step) % len(STUDENTS)], claimed))
        for label, writer, imitated in attempts:
            n += 1
            centre = 79.0 if label == "natural" else 63.0
            sd = 8.0 if label == "natural" else 11.0
            score = max(0, min(100, round(rng.gauss(centre + offsets[claimed], sd))))
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
                status, score_text = "INCONCLUSIVE", ""
            elif claimed == "synth-07" and label == "natural" and n % 2 == 0:
                status, score_text = "SUBMITTED", ""
            else:
                status = "FLAGGED" if score < STRICT else "SUBMITTED"
                score_text = str(score)
            rows.append(
                [
                    f"sub-{n:03d}",
                    "synth-exam-1",
                    writer,
                    label,
                    imitated or "",
                    claimed,
                    status,
                    score_text,
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
