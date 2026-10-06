"""bluebook_rules.py — pure Bluebook self-serve rules (no I/O).

Kept free of FastAPI and the repository so each rule is testable on its own:
exam availability windows, free-tier caps, product-dependent response
shaping, warnings validation, and the CSV export.

See docs/superpowers/specs/2026-09-17-bluebook-standalone-backend-design.md
(Section 3 and the 2026-09-28 amendment).
"""

from __future__ import annotations

import csv
import io
from datetime import UTC, datetime

# ── Free-tier caps (self-serve workspaces only) ───────────────────────────────
SELF_SERVE_PLAN = "self_serve"
MAX_ENROLLED_STUDENTS = 200
MAX_EXAMS = 50
MAX_SUBMISSIONS_PER_MONTH = 500

# ── Input bounds ──────────────────────────────────────────────────────────────
MAX_TEXT_CHARS = 200_000
MAX_WARNINGS = 500
MAX_ROSTER_BATCH = 500
MAX_QUESTIONS = 20
MAX_QUESTION_CHARS = 8000
MAX_MARK_CHARS = 20
MAX_FEEDBACK_CHARS = 5000
_WARNING_FIELD_CHARS = 40

# Fields only a tenant that bought Original may see: they are Original's
# stylometric and AI readings. Keys as the repository's submission dicts
# spell them.
SCORE_FIELDS = ("stylometric", "aiScore")


def is_self_serve(tenant: dict | None) -> bool:
    return bool(tenant) and (tenant.get("meta") or {}).get("plan") == SELF_SERVE_PLAN


# ── Time ──────────────────────────────────────────────────────────────────────


def now_utc() -> datetime:
    return datetime.now(UTC)


def parse_instant(value) -> datetime | None:
    """ISO-8601 string -> aware UTC datetime. Empty/None -> None. A naive
    value is taken as UTC. Raises ValueError on anything unparseable."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        dt = datetime.fromisoformat(str(value).strip().replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def month_start(now: datetime) -> datetime:
    return now.astimezone(UTC).replace(day=1, hour=0, minute=0, second=0, microsecond=0)


# ── Exam availability ─────────────────────────────────────────────────────────

DRAFT, UPCOMING, OPEN, CLOSED = "draft", "upcoming", "open", "closed"


def exam_state(exam: dict, now: datetime) -> str:
    """draft | upcoming | open | closed.

    DRAFT status is never visible to students. A NULL ``opens_at`` means open
    as soon as the exam leaves DRAFT; a NULL ``closes_at`` means it never
    auto-closes. ``CLOSED``/``ARCHIVED`` status closes it regardless.
    """
    status = (exam.get("status") or "DRAFT").upper()
    if status == "DRAFT":
        return DRAFT
    if status in ("CLOSED", "ARCHIVED"):
        return CLOSED
    opens = parse_instant(exam.get("opens_at"))
    closes = parse_instant(exam.get("closes_at"))
    if opens is not None and now < opens:
        return UPCOMING
    if closes is not None and now >= closes:
        return CLOSED
    return OPEN


def session_seconds(exam: dict, now: datetime, default_minutes: int = 90) -> int:
    """Sitting length in seconds: the exam duration, clipped so the pinned
    deadline never passes ``closes_at``. Never below 60 seconds, matching
    the existing session route's floor."""
    try:
        minutes = int(exam.get("duration") or default_minutes)
    except (TypeError, ValueError):
        minutes = default_minutes
    seconds = max(60, minutes * 60)
    closes = parse_instant(exam.get("closes_at"))
    if closes is not None:
        seconds = min(seconds, int((closes - now).total_seconds()))
    return max(60, seconds)


# ── Response shaping ──────────────────────────────────────────────────────────


def shape_for_products(rec: dict, products) -> dict:
    """Drop Original's readings from a submission when the tenant lacks it."""
    if "original" in products:
        return rec
    return {k: v for k, v in rec.items() if k not in SCORE_FIELDS}


GRADE_FIELDS = ("mark", "feedback", "graded_at")


def student_view(rec: dict, released: bool = False) -> dict:
    """A submission as its own author sees it: never any score, whatever the
    tenant bought (scores are for staff judgement, not a student display),
    never who graded it, and the mark and feedback only once the teacher has
    released results for the exam."""
    out = {k: v for k, v in rec.items() if k not in SCORE_FIELDS}
    out.pop("tenant_id", None)
    out.pop("graded_by", None)
    out["results_released"] = bool(released)
    if not released:
        for k in GRADE_FIELDS:
            out.pop(k, None)
    return out


# ── Questions and answers ─────────────────────────────────────────────────────


def clean_questions(raw) -> list[str]:
    """Validate an exam's question list: strings, at most MAX_QUESTIONS, each
    at most MAX_QUESTION_CHARS. Blank entries are dropped. Raises ValueError."""
    if raw is None:
        return []
    if not isinstance(raw, list) or not all(isinstance(q, str) for q in raw):
        raise ValueError("questions must be a list of text")
    out = [q.strip() for q in raw if q.strip()]
    if len(out) > MAX_QUESTIONS:
        raise ValueError(f"at most {MAX_QUESTIONS} questions")
    if any(len(q) > MAX_QUESTION_CHARS for q in out):
        raise ValueError(f"each question must be under {MAX_QUESTION_CHARS} characters")
    return out


def joined_prompt(questions: list[str]) -> str:
    """The single-prompt form older clients read: one question as-is, several
    numbered one per paragraph."""
    if len(questions) <= 1:
        return questions[0] if questions else ""
    return "\n\n".join(f"{i + 1}. {q}" for i, q in enumerate(questions))


def clean_answers(raw) -> list[str]:
    """Validate a submission's answers: strings, at most MAX_QUESTIONS.
    Raises ValueError."""
    if raw is None:
        return []
    if not isinstance(raw, list) or not all(isinstance(a, str) for a in raw):
        raise ValueError("answers must be a list of text")
    if len(raw) > MAX_QUESTIONS:
        raise ValueError(f"at most {MAX_QUESTIONS} answers")
    return list(raw)


def joined_answers(answers: list[str]) -> str:
    """The single-text form of a multi-answer submission (export, Original)."""
    if len(answers) <= 1:
        return answers[0] if answers else ""
    return "\n\n".join(f"Question {i + 1}.\n{a}" for i, a in enumerate(answers))


# ── Warnings ──────────────────────────────────────────────────────────────────


def clean_warnings(raw) -> list[dict]:
    """Validate the lockdown warnings a client reports with a seal.

    Each item must be an object with a ``type`` string; ``at`` is optional.
    Both are truncated. Anything else raises ValueError, as does a list
    longer than MAX_WARNINGS."""
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ValueError("warnings must be a list")
    if len(raw) > MAX_WARNINGS:
        raise ValueError(f"at most {MAX_WARNINGS} warnings")
    out = []
    for item in raw:
        if not isinstance(item, dict) or not isinstance(item.get("type"), str):
            raise ValueError("each warning needs a string 'type'")
        entry = {"type": item["type"][:_WARNING_FIELD_CHARS]}
        if item.get("at") is not None:
            entry["at"] = str(item["at"])[:_WARNING_FIELD_CHARS]
        out.append(entry)
    return out


# ── Export ────────────────────────────────────────────────────────────────────

CSV_COLUMNS = (
    "submission_id",
    "student_id",
    "name",
    "email",
    "submitted_at",
    "word_count",
    "time_min",
    "late",
    "warning_count",
    "status",
    "mark",
    "feedback",
    "text",
)


def _csv_safe(value) -> str:
    """Neutralise spreadsheet formula injection: a cell a student controls
    (their text, their name) must not start with = + - @ or a tab/CR."""
    s = "" if value is None else str(value)
    if s and s[0] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + s
    return s


def submissions_csv(submissions: list[dict], people: dict[str, dict]) -> str:
    """CSV of one exam's submissions. ``people`` maps student_id -> user.
    A multi-question exam also gets one ``answer_N`` column per question."""
    n_answers = max((len(s.get("answers") or []) for s in submissions), default=0)
    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(list(CSV_COLUMNS) + [f"answer_{i + 1}" for i in range(n_answers)])
    for sub in submissions:
        person = people.get(sub.get("student_id") or "") or {}
        answers = list(sub.get("answers") or [])
        writer.writerow(
            [
                _csv_safe(sub.get("id")),
                _csv_safe(sub.get("student_id")),
                _csv_safe(person.get("name") or sub.get("candidate")),
                _csv_safe(person.get("email")),
                _csv_safe(sub.get("created_at")),
                sub.get("words") or 0,
                sub.get("timeMin") or 0,
                int(bool(sub.get("late"))),
                len(sub.get("warnings") or []),
                _csv_safe(sub.get("status")),
                _csv_safe(sub.get("mark")),
                _csv_safe(sub.get("feedback")),
                _csv_safe(sub.get("text")),
            ]
            + [_csv_safe(a) for a in answers]
            + [""] * (n_answers - len(answers))
        )
    return buf.getvalue()
