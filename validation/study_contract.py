"""
validation/study_contract.py, the CSV contract for the natural/shadow study.

One CSV row is one sealed Collections submission that took part in the study
(docs/research/STUDY_PROTOCOL_2026-10.md). A **natural** row is a student
writing as themselves; a **shadow** row is a student deliberately writing as
another, named student (the *imitated* student). Both kinds are scored against
the **claimed** student's baseline: the writer's own for a natural row, the
imitated student's for a shadow row. That is what makes the study an
impersonation test rather than a "write unlike yourself" test.

This module is the ONE place the column names live. `validation/study_eval.py`
and `scripts/propose_thresholds.py` build against it, not against the export
code, so if the export's header differs, this file is what changes.

Columns (contract version ``study-csv-v1``):

  required
    submission_id        unique per row (the Collections submission id)
    writer_student_id    pseudonymous id of the person who wrote the text
    study_label          ``natural`` | ``shadow`` (case-insensitive)
    status               the stored seal status: SUBMITTED | FLAGGED | INCONCLUSIVE
    consistency_score    0-100, higher = more consistent with the claimed
                         student's baseline (Collections stores it as
                         ``ai_score``; ``demo/bluebook/Exam.jsx``
                         ``bbScoreWithOriginal``). Blank when INCONCLUSIVE.
    baseline_size        approved reference samples the claimed student had
                         when the row was scored
    word_count           words in the submission

  optional
    imitated_student_id  required (and != writer) on a shadow row, blank on a
                         natural row
    claimed_student_id   whose baseline the row was scored against. Derived
                         when absent (writer for natural, imitated for
                         shadow); validated against that rule when present
    exam_id, deviation_score, llr_deviation_score, authorship_probability,
    scored_at            carried through, never required
    f_<feature_code>     one column per extracted feature (``ALL_FEATURE_CODES``
                         names). Only the feature-importance section reads them.

Unambiguous aliases are accepted and reported (``ai_score`` /
``aiScore`` -> consistency_score, ``words`` -> word_count, ``label`` ->
study_label). ``student_id`` is NOT aliased: in a shadow row it could mean the
writer or the claimed student, and guessing wrong would silently invert the
study.

A SUBMITTED or FLAGGED row with a blank score is **unscored** (the score call
failed or Original was off): it is counted and reported, then left out of
every rate, never treated as inconclusive or as a pass.
"""

from __future__ import annotations

import csv
import hashlib
import io
import math
from dataclasses import dataclass, field
from pathlib import Path

CONTRACT_VERSION = "study-csv-v1"

LABEL_NATURAL = "natural"
LABEL_SHADOW = "shadow"
LABELS = (LABEL_NATURAL, LABEL_SHADOW)

STATUS_SUBMITTED = "SUBMITTED"
STATUS_FLAGGED = "FLAGGED"
STATUS_INCONCLUSIVE = "INCONCLUSIVE"
STATUSES = (STATUS_SUBMITTED, STATUS_FLAGGED, STATUS_INCONCLUSIVE)

REQUIRED_COLUMNS = (
    "submission_id",
    "writer_student_id",
    "study_label",
    "status",
    "consistency_score",
    "baseline_size",
    "word_count",
)
OPTIONAL_COLUMNS = (
    "imitated_student_id",
    "claimed_student_id",
    "exam_id",
    "deviation_score",
    "llr_deviation_score",
    "authorship_probability",
    "scored_at",
)
FEATURE_PREFIX = "f_"

# Header spelling -> contract column. Only names that cannot mean anything
# else; see the module docstring for why student_id is not here.
ALIASES = {
    "ai_score": "consistency_score",
    "aiScore": "consistency_score",
    "words": "word_count",
    "label": "study_label",
}

SCORE_MIN, SCORE_MAX = 0.0, 100.0


class StudyContractError(ValueError):
    """The CSV does not meet the contract. Carries every problem found, not
    just the first, so one export round-trip can fix them all."""

    def __init__(self, problems: list[str]):
        self.problems = list(problems)
        shown = "\n  - ".join(self.problems[:25])
        more = f"\n  ... and {len(self.problems) - 25} more" if len(self.problems) > 25 else ""
        super().__init__(f"study CSV does not meet {CONTRACT_VERSION}:\n  - {shown}{more}")


@dataclass(frozen=True)
class StudyRow:
    submission_id: str
    writer_student_id: str
    claimed_student_id: str
    imitated_student_id: str | None
    label: str
    status: str
    score: float | None
    baseline_size: int
    word_count: int
    exam_id: str | None = None
    deviation_score: float | None = None
    features: dict[str, float | None] = field(default_factory=dict)

    @property
    def inconclusive(self) -> bool:
        return self.status == STATUS_INCONCLUSIVE

    @property
    def unscored(self) -> bool:
        """Not INCONCLUSIVE, yet carries no score."""
        return not self.inconclusive and self.score is None

    @property
    def conclusive(self) -> bool:
        return not self.inconclusive and self.score is not None


@dataclass(frozen=True)
class StudyData:
    rows: tuple[StudyRow, ...]
    feature_codes: tuple[str, ...]
    aliases_applied: dict[str, str]
    warnings: tuple[str, ...]
    sha256: str
    source_name: str


def _blank(v: str | None) -> bool:
    return v is None or str(v).strip() == ""


def _float(v: str | None) -> float | None:
    if _blank(v):
        return None
    x = float(str(v).strip())
    if not math.isfinite(x):
        raise ValueError(f"not a finite number: {v!r}")
    return x


def _int(v: str | None) -> int:
    x = _float(v)
    if x is None:
        raise ValueError("blank")
    if x != int(x) or x < 0:
        raise ValueError(f"not a non-negative whole number: {v!r}")
    return int(x)


def load_study_csv(path: str | Path) -> StudyData:
    """Read and validate a study CSV. Raises StudyContractError listing every
    contract violation; returns rows sorted by submission_id so every
    downstream number is independent of the export's row order."""
    path = Path(path)
    raw = path.read_bytes()
    return parse_study_csv(raw, source_name=path.name)


def parse_study_csv(raw: bytes, source_name: str = "<memory>") -> StudyData:
    from original.constants import ALL_FEATURE_CODES

    known_codes = set(ALL_FEATURE_CODES)
    text = raw.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))
    header = [h.strip() for h in (reader.fieldnames or [])]

    problems: list[str] = []
    warnings: list[str] = []
    aliases_applied: dict[str, str] = {}
    rename: dict[str, str] = {}
    for h in header:
        target = ALIASES.get(h)
        if target is not None:
            if target in header:
                problems.append(f"both {h!r} and its contract name {target!r} are present")
            else:
                rename[h] = target
                aliases_applied[h] = target
        else:
            rename[h] = h
    columns = set(rename.values())
    missing = [c for c in REQUIRED_COLUMNS if c not in columns]
    if missing:
        problems.append(f"missing required column(s): {', '.join(missing)}")

    feature_cols = sorted(c for c in columns if c.startswith(FEATURE_PREFIX))
    feature_codes: list[str] = []
    for c in feature_cols:
        code = c[len(FEATURE_PREFIX) :]
        if code in known_codes:
            feature_codes.append(code)
        else:
            warnings.append(f"ignoring {c!r}: {code!r} is not in ALL_FEATURE_CODES")
    if problems:
        raise StudyContractError(problems)

    rows: list[StudyRow] = []
    seen_ids: set[str] = set()
    for line_no, raw_row in enumerate(reader, start=2):
        r = {rename.get(k.strip(), k.strip()): v for k, v in raw_row.items() if k is not None}
        where = f"line {line_no}"
        row_problems: list[str] = []

        sid = (r.get("submission_id") or "").strip()
        if not sid:
            row_problems.append(f"{where}: blank submission_id")
        elif sid in seen_ids:
            row_problems.append(f"{where}: duplicate submission_id {sid!r}")
        seen_ids.add(sid)

        writer = (r.get("writer_student_id") or "").strip()
        if not writer:
            row_problems.append(f"{where}: blank writer_student_id")

        label = (r.get("study_label") or "").strip().lower()
        if label not in LABELS:
            row_problems.append(
                f"{where}: study_label must be natural or shadow, got {r.get('study_label')!r}"
            )

        imitated = (r.get("imitated_student_id") or "").strip() or None
        if label == LABEL_SHADOW:
            if imitated is None:
                row_problems.append(f"{where}: shadow row without imitated_student_id")
            elif imitated == writer:
                row_problems.append(f"{where}: shadow row imitates its own writer")
        elif label == LABEL_NATURAL and imitated is not None:
            row_problems.append(f"{where}: natural row names an imitated_student_id")

        expected_claimed = imitated if label == LABEL_SHADOW else writer
        claimed = (r.get("claimed_student_id") or "").strip() or expected_claimed
        if claimed and expected_claimed and claimed != expected_claimed:
            row_problems.append(
                f"{where}: claimed_student_id {claimed!r} should be "
                f"{'the imitated student' if label == LABEL_SHADOW else 'the writer'} "
                f"({expected_claimed!r})"
            )

        status = (r.get("status") or "").strip().upper()
        if status not in STATUSES:
            row_problems.append(
                f"{where}: status must be one of {', '.join(STATUSES)}, got {r.get('status')!r}"
            )

        try:
            score = _float(r.get("consistency_score"))
            if score is not None and not SCORE_MIN <= score <= SCORE_MAX:
                row_problems.append(f"{where}: consistency_score {score} is outside 0-100")
        except ValueError as e:
            row_problems.append(f"{where}: consistency_score {e}")
            score = None
        if status == STATUS_INCONCLUSIVE and score is not None:
            warnings.append(f"{where}: INCONCLUSIVE row carries a score; the score is ignored")
            score = None

        try:
            baseline_size = _int(r.get("baseline_size"))
        except ValueError as e:
            row_problems.append(f"{where}: baseline_size {e}")
            baseline_size = 0
        try:
            word_count = _int(r.get("word_count"))
        except ValueError as e:
            row_problems.append(f"{where}: word_count {e}")
            word_count = 0

        try:
            deviation = _float(r.get("deviation_score"))
        except ValueError as e:
            row_problems.append(f"{where}: deviation_score {e}")
            deviation = None

        feats: dict[str, float | None] = {}
        for code in feature_codes:
            try:
                feats[code] = _float(r.get(FEATURE_PREFIX + code))
            except ValueError as e:
                row_problems.append(f"{where}: {FEATURE_PREFIX}{code} {e}")
                feats[code] = None

        if row_problems:
            problems.extend(row_problems)
            continue
        rows.append(
            StudyRow(
                submission_id=sid,
                writer_student_id=writer,
                claimed_student_id=claimed,
                imitated_student_id=imitated,
                label=label,
                status=status,
                score=score,
                baseline_size=baseline_size,
                word_count=word_count,
                exam_id=(r.get("exam_id") or "").strip() or None,
                deviation_score=deviation,
                features=feats,
            )
        )

    if problems:
        raise StudyContractError(problems)
    if not rows:
        raise StudyContractError(["the CSV has a header but no rows"])

    rows.sort(key=lambda x: x.submission_id)
    return StudyData(
        rows=tuple(rows),
        feature_codes=tuple(feature_codes),
        aliases_applied=dict(sorted(aliases_applied.items())),
        warnings=tuple(warnings),
        sha256=hashlib.sha256(raw).hexdigest(),
        source_name=source_name,
    )
