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
and `scripts/propose_thresholds.py` build against it, and
`tests/test_study_eval_on_export.py` checks the export
(`original.study_export`) against it.

Columns (contract version ``study-csv-v2``, the shared contract):

  required
    submission_id        unique per row (the Collections submission id)
    student_id           the WRITER: pseudonymous id of the person who wrote
                         the text. Never the claimed student on a shadow row.
    study_label          ``natural`` | ``shadow`` (case-insensitive). A row
                         with a blank label was never labelled: it is left out
                         and counted, with a warning.
    verdict              SUBMITTED | FLAGGED | INCONCLUSIVE, the Collections
                         verdict from scoring against the CLAIMED student's
                         baseline (for a shadow row the imitated student's, NOT
                         the seal-time status, which Collections computes
                         against the writer's own baseline). INCONCLUSIVE when
                         that baseline had fewer than 3 approved samples.
    deviation_score      the primary score: Original's deviation from the
                         claimed student's baseline, 0-1. Direction in
                         SCORE_DIRECTION: HIGHER means LESS consistent. Blank
                         when INCONCLUSIVE.
    baseline_count       approved reference samples the claimed student had
                         when the row was scored
    word_count           words in the submission

  optional
    imitated_student_id  required (and != student_id) on a shadow row, blank
                         on a natural row
    claimed_student_id   whose baseline the row was scored against. Derived
                         when absent (student_id for natural, imitated for
                         shadow); validated against that rule when present
    authorship_probability
                         Born-rule probability the live Collections flag rule
                         reads; when present the eval checks the verdict
                         against that rule
    exam_id, llr_deviation_score, scored_at, engine_version,
    threshold_version    carried through, never required
    f_<feature_code>     one column per extracted feature (``ALL_FEATURE_CODES``
                         names). Only the feature-importance section reads them.

Aliases kept from ``study-csv-v1`` because they cannot mean anything else, and
reported when applied: ``writer_student_id`` -> student_id, ``baseline_size``
-> baseline_count, ``words`` -> word_count, ``label`` -> study_label. Two v1
names are refused rather than aliased:

  - ``status``: a submission's stored status is its seal-time status, scored
    against the WRITER's baseline. For a shadow row that is the wrong
    baseline, so it is never read as the verdict.
  - ``consistency_score`` / ``ai_score`` / ``aiScore``: v1's 0-100 Collections
    score is 100 x authorship_probability, a different quantity from
    deviation_score, so it cannot be converted into one.

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

CONTRACT_VERSION = "study-csv-v2"

# The primary score, and its direction stated once. deviation_score is
# Original's D_adjusted (original/quantum/scoring.py, clipped to [0, 1]): it
# grows as a text moves away from the claimed student's baseline, so a HIGHER
# score reads LESS like the claimed student. The study's flag rule follows:
# flag when deviation_score >= cut-off, the same [lower, upper) convention as
# ACTION_THRESHOLDS. Nothing in the study needs a higher-is-more-consistent
# score; anything that ever does derives it in code (SCORE_MAX - score), never
# from a column. study_eval records this direction in its report and
# propose_thresholds refuses a report made under any other.
SCORE_COLUMN = "deviation_score"
SCORE_DIRECTION = "higher_is_less_consistent"
SCORE_MIN, SCORE_MAX = 0.0, 1.0

LABEL_NATURAL = "natural"
LABEL_SHADOW = "shadow"
LABELS = (LABEL_NATURAL, LABEL_SHADOW)

VERDICT_SUBMITTED = "SUBMITTED"
VERDICT_FLAGGED = "FLAGGED"
VERDICT_INCONCLUSIVE = "INCONCLUSIVE"
VERDICTS = (VERDICT_SUBMITTED, VERDICT_FLAGGED, VERDICT_INCONCLUSIVE)

REQUIRED_COLUMNS = (
    "submission_id",
    "student_id",
    "study_label",
    "verdict",
    SCORE_COLUMN,
    "baseline_count",
    "word_count",
)
OPTIONAL_COLUMNS = (
    "imitated_student_id",
    "claimed_student_id",
    "authorship_probability",
    "exam_id",
    "llr_deviation_score",
    "scored_at",
    "engine_version",
    "threshold_version",
)
FEATURE_PREFIX = "f_"

# Header spelling -> contract column. Only names that cannot mean anything
# else; see the module docstring for the v1 names that are refused instead.
ALIASES = {
    "writer_student_id": "student_id",
    "baseline_size": "baseline_count",
    "words": "word_count",
    "label": "study_label",
}
REFUSED_V1_SCORE_COLUMNS = ("consistency_score", "ai_score", "aiScore")

# Approved reference samples below which Original reads INCONCLUSIVE
# (original/baseline_integrity.py readiness, via style_authorship.MIN_BASELINES;
# pinned to it by tests/test_study_gate.py).
MIN_READY_BASELINE = 3


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
    student_id: str
    claimed_student_id: str
    imitated_student_id: str | None
    label: str
    verdict: str
    deviation_score: float | None
    baseline_count: int
    word_count: int
    exam_id: str | None = None
    authorship_probability: float | None = None
    features: dict[str, float | None] = field(default_factory=dict)

    @property
    def inconclusive(self) -> bool:
        return self.verdict == VERDICT_INCONCLUSIVE

    @property
    def unscored(self) -> bool:
        """Not INCONCLUSIVE, yet carries no score."""
        return not self.inconclusive and self.deviation_score is None

    @property
    def conclusive(self) -> bool:
        return not self.inconclusive and self.deviation_score is not None

    @property
    def verdict_flagged(self) -> bool:
        return self.verdict == VERDICT_FLAGGED


@dataclass(frozen=True)
class StudyData:
    rows: tuple[StudyRow, ...]
    feature_codes: tuple[str, ...]
    aliases_applied: dict[str, str]
    warnings: tuple[str, ...]
    sha256: str
    source_name: str
    unlabelled: int = 0


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


def _header_problems(columns: set[str]) -> list[str]:
    problems = []
    missing = [c for c in REQUIRED_COLUMNS if c not in columns]
    if "verdict" in missing and "status" in columns:
        problems.append(
            "no verdict column: 'status' is not read as one, because a submission's "
            "stored status is scored against the writer's own baseline, which is the "
            "wrong baseline for a shadow row"
        )
        missing.remove("verdict")
    v1_scores = [c for c in REFUSED_V1_SCORE_COLUMNS if c in columns]
    if SCORE_COLUMN in missing and v1_scores:
        problems.append(
            f"no {SCORE_COLUMN} column: {', '.join(v1_scores)} is the study-csv-v1 "
            "0-100 Collections score (100 x authorship_probability), a different "
            f"quantity that cannot be converted into {SCORE_COLUMN}; re-export"
        )
        missing.remove(SCORE_COLUMN)
    if missing:
        problems.append(f"missing required column(s): {', '.join(missing)}")
    return problems


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
    claimed_by: dict[str, str] = {}
    for h in header:
        target = ALIASES.get(h, h)
        if target in claimed_by:
            problems.append(
                f"header columns {claimed_by[target]!r} and {h!r} both map to {target!r}"
            )
            continue
        claimed_by[target] = h
        rename[h] = target
        if target != h:
            aliases_applied[h] = target
    columns = set(rename.values())
    problems.extend(_header_problems(columns))
    ignored_v1 = [c for c in REFUSED_V1_SCORE_COLUMNS if c in columns]
    if SCORE_COLUMN in columns and ignored_v1:
        warnings.append(
            f"ignoring {', '.join(ignored_v1)}: the v1 Collections score, not {SCORE_COLUMN}"
        )

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
    unlabelled: list[str] = []
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

        label = (r.get("study_label") or "").strip().lower()
        if not label and not row_problems:
            unlabelled.append(where)
            continue
        if label not in LABELS:
            row_problems.append(
                f"{where}: study_label must be natural or shadow, got {r.get('study_label')!r}"
            )

        writer = (r.get("student_id") or "").strip()
        if not writer:
            row_problems.append(f"{where}: blank student_id (the writer)")

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

        verdict = (r.get("verdict") or "").strip().upper()
        if verdict not in VERDICTS:
            row_problems.append(
                f"{where}: verdict must be one of {', '.join(VERDICTS)}, got {r.get('verdict')!r}"
            )

        try:
            score = _float(r.get(SCORE_COLUMN))
            if score is not None and not SCORE_MIN <= score <= SCORE_MAX:
                row_problems.append(
                    f"{where}: {SCORE_COLUMN} {score} is outside {SCORE_MIN:g}-{SCORE_MAX:g}"
                )
        except ValueError as e:
            row_problems.append(f"{where}: {SCORE_COLUMN} {e}")
            score = None
        if verdict == VERDICT_INCONCLUSIVE and score is not None:
            warnings.append(f"{where}: INCONCLUSIVE row carries a score; the score is ignored")
            score = None

        try:
            baseline_count = _int(r.get("baseline_count"))
        except ValueError as e:
            row_problems.append(f"{where}: baseline_count {e}")
            baseline_count = 0
        if verdict == VERDICT_INCONCLUSIVE and baseline_count >= MIN_READY_BASELINE:
            warnings.append(
                f"{where}: INCONCLUSIVE with {baseline_count} approved samples; was the verdict "
                "computed against the writer's baseline instead of the claimed student's?"
            )
        elif (
            verdict in (VERDICT_SUBMITTED, VERDICT_FLAGGED)
            and score is not None
            and baseline_count < MIN_READY_BASELINE
        ):
            warnings.append(
                f"{where}: scored with only {baseline_count} approved samples (fewer than "
                f"{MIN_READY_BASELINE}); was the verdict computed against the writer's baseline?"
            )
        try:
            word_count = _int(r.get("word_count"))
        except ValueError as e:
            row_problems.append(f"{where}: word_count {e}")
            word_count = 0

        try:
            prob = _float(r.get("authorship_probability"))
            if prob is not None and not 0.0 <= prob <= 1.0:
                row_problems.append(f"{where}: authorship_probability {prob} is outside 0-1")
        except ValueError as e:
            row_problems.append(f"{where}: authorship_probability {e}")
            prob = None

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
                student_id=writer,
                claimed_student_id=claimed,
                imitated_student_id=imitated,
                label=label,
                verdict=verdict,
                deviation_score=score,
                baseline_count=baseline_count,
                word_count=word_count,
                exam_id=(r.get("exam_id") or "").strip() or None,
                authorship_probability=prob,
                features=feats,
            )
        )

    if problems:
        raise StudyContractError(problems)
    if unlabelled:
        shown = ", ".join(unlabelled[:10]) + (" ..." if len(unlabelled) > 10 else "")
        warnings.append(
            f"{len(unlabelled)} row(s) have no study_label and were left out ({shown}); "
            "label them in the exam view's study panel and re-export"
        )
    if not rows:
        raise StudyContractError(["the CSV has no labelled rows"])

    writers = {r.student_id for r in rows}
    for imitated in sorted(
        {r.imitated_student_id for r in rows if r.imitated_student_id} - writers
    ):
        warnings.append(
            f"imitated student {imitated!r} never appears as a writer: a typo, or a withdrawal?"
        )

    rows.sort(key=lambda x: x.submission_id)
    return StudyData(
        rows=tuple(rows),
        feature_codes=tuple(feature_codes),
        aliases_applied=dict(sorted(aliases_applied.items())),
        warnings=tuple(warnings),
        sha256=hashlib.sha256(raw).hexdigest(),
        source_name=source_name,
        unlabelled=len(unlabelled),
    )
