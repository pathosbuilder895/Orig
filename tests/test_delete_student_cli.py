"""Behavioral tests for the manual FERPA-deletion CLI (branch-coverage part 3, task 1).

``original/cli/delete_student.py`` was 0% covered. It targets the DORMANT v1
SQLAlchemy stack (``original/db/models``) via a raw ``Session`` -- a
completely separate persistence layer from the LIVE stack's
``store.py``/``postgres_repository.py``. Despite the module's own header
docstring hedging ("NOT the live FERPA deletion path"), it is the
documented manual FERPA-deletion tool (CLAUDE.md/pyproject) and the stated
reason the v1 db stack is kept alive at all -- per controller decision, it
is fixed here rather than removed; removal remains on the humans' WS-6
schedule. Nothing here touches real data -- see the ``v1_session`` fixture
below.

*** REAL BUG FOUND AND FIXED, 2026-08-18 ***
``delete_student_data()``'s first two delete steps built queries shaped
like ``session.query(InstructorDecision).join(Submission).filter(...)
.delete(...)`` (and the identical shape for ``ScoringResult``). SQLAlchemy's
ORM ``Query`` API unconditionally forbids calling ``.delete()``/``.update()``
on a ``Query`` that has already had ``.join()`` called on it
(``sqlalchemy.exc.InvalidRequestError``) -- a query-construction-time check,
independent of whether any row would actually match. That meant every
confirmed deletion, for every student, was caught by the
``except SQLAlchemyError`` handler, rolled back, and reported as "Database
error during deletion" -- ``delete_student_data()`` could never return
``True``, and ``main()`` could never return exit code 0, for a real
deletion, regardless of ``--force``/``--hard-delete``. Fixed by filtering on
a subquery of the student's submission ids instead of joining
(``InstructorDecision.submission_id.in_(...)`` /
``ScoringResult.submission_id.in_(...)``) -- see
``delete_student.py``'s "Submission ids for this student" comment. Full
writeup, including the pre-fix reproduction and BLOCKED report, in
.superpowers/sdd/p3-task-1-report.md.

``hard_delete`` is accepted by ``delete_student_data()``'s signature but
still never read anywhere in its body (confirmed by grep) -- left as-is per
controller decision (documented-parameter semantics are a product
question, not something to silently change while fixing an unrelated
bug); both arms currently perform the same full deletion.
"""

from __future__ import annotations

from datetime import datetime

import pytest
from sqlalchemy.exc import SQLAlchemyError

from original.cli import delete_student as cli


@pytest.fixture
def v1_session(tmp_path, monkeypatch):
    """A throwaway sqlite-backed v1 session, patched into the CLI module.

    ``original.db.base.Base`` is the v1 declarative base (confirmed by
    reading original/db/base.py -- it's a plain ``declarative_base()``, no
    other name is exported). Its metadata already has every v1 model class
    registered by the time this fixture runs, because
    ``from original.cli import delete_student as cli`` above transitively
    imports ``original.db.models.__init__``, which imports every v1 model
    module (student/course/institution/baseline/submission/user).

    Patching ``cli._get_db_session`` (rather than the real
    ``original.db.session.SessionLocal``) means the CLI's own
    ``init_db()``/module-level engine is never touched -- that real engine
    defaults to ``postgresql://original:original@localhost:5432/original_db``
    (original/core/config.py), though tests/conftest.py's
    ``DATABASE_URL=sqlite:///:memory:`` safety-net default would catch any
    stray use of it even if this patch were somehow missing. Nothing in this
    file ever points at ``profiles.db`` or a real database.
    """
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from original.db.base import Base

    engine = create_engine(f"sqlite:///{tmp_path}/v1.db")
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    monkeypatch.setattr(cli, "_get_db_session", lambda: session)
    yield session
    session.close()


def _seed_institution_and_course(session, suffix):
    """FK scaffolding: Student.institution_id and StudentEnrollment.course_id
    are both NOT NULL (original/db/models/student.py), so a bare Student row
    isn't enough."""
    from original.db.models import Course, Institution

    institution = Institution(
        id=f"inst-{suffix}", name=f"Institution {suffix}", subdomain=f"sub-{suffix}"
    )
    session.add(institution)
    course = Course(
        id=f"course-{suffix}",
        name="Test Course",
        code="TST101",
        institution_id=institution.id,
        semester="Fall 2026",
    )
    session.add(course)
    return institution, course


def _seed_v1_student(session, sid="00000000-0000-0000-0000-000000000001"):
    """Seed a student with one baseline sample, one submission, and one
    enrollment. Kwargs reconciled against the actual v1 models (not the
    brief's illustrative sketch): Submission has no ``text`` column (it
    stores ``text_hash``/``word_count``/``char_count``, not raw text) and
    BaselineSample requires ``assignment``, ``text_hash`` (unique),
    ``feature_vector`` (NOT NULL JSON), ``auth_weight``, ``word_count``,
    ``submitted_at``, and ``model_version`` -- none of which the brief's
    sketch declared.
    """
    from original.db.models import BaselineSample, Student, StudentEnrollment, Submission

    institution, course = _seed_institution_and_course(session, sid)
    student = Student(
        id=sid,
        external_id="ext-1",
        full_name="Test Student",
        email="test-student@example.edu",
        institution_id=institution.id,
    )
    session.add(student)
    session.add(
        BaselineSample(
            student_id=sid,
            assignment="Essay 1",
            text_hash=f"baseline-hash-{sid}",
            feature_vector={},
            auth_weight=1.0,
            word_count=100,
            submitted_at=datetime.utcnow(),
            model_version="v1",
        )
    )
    session.add(
        Submission(
            id=f"sub-{sid}",
            student_id=sid,
            assignment="Essay 1",
            text_hash=f"submission-hash-{sid}",
            word_count=100,
            char_count=500,
            submitted_at=datetime.utcnow(),
        )
    )
    session.add(StudentEnrollment(student_id=sid, course_id=course.id))
    session.commit()
    return sid


def _seed_v1_student_with_scoring_and_decision(session, sid="00000000-0000-0000-0000-000000000002"):
    """Extends ``_seed_v1_student`` with one ``ScoringResult`` and one
    ``InstructorDecision`` on its submission -- the shape needed to exercise
    the *True* arm of the ``decision_count``/``scoring_count`` "if count > 0"
    print gates (delete_student.py, steps 1-2), which the plain
    ``_seed_v1_student`` shape (zero of each) never reaches."""
    from original.db.models import InstructorDecision, ScoringResult

    _seed_v1_student(session, sid=sid)
    session.add(
        ScoringResult(
            submission_id=f"sub-{sid}",
            model_version="v1",
            deviation_score=0.1,
            authorship_probability=0.9,
            recommended_action="clear",
            baseline_confidence={},
            full_result={},
            feature_vector={},
            scored_at=datetime.utcnow(),
        )
    )
    session.add(InstructorDecision(submission_id=f"sub-{sid}", action="clear"))
    session.commit()
    return sid


def _seed_bare_student(session, sid="00000000-0000-0000-0000-000000000003"):
    """A student with an Institution but no course, submissions, baseline
    samples, or enrollments -- exercises the *False* arm of every
    "if <count> > 0" print gate in delete_student_data()."""
    from original.db.models import Institution, Student

    institution = Institution(id=f"inst-{sid}", name=f"Institution {sid}", subdomain=f"sub-{sid}")
    session.add(institution)
    session.add(
        Student(
            id=sid,
            external_id="ext-bare",
            full_name="Bare Student",
            email="bare-student@example.edu",
            institution_id=institution.id,
        )
    )
    session.commit()
    return sid


class TestDeleteStudentData:
    def test_unknown_student_returns_false(self, v1_session):
        assert cli.delete_student_data("no-such-id", force=True) is False

    def test_force_delete_removes_every_associated_record(self, v1_session):
        from original.db.models import BaselineSample, Student, Submission

        sid = _seed_v1_student(v1_session)
        assert cli.delete_student_data(sid, force=True) is True
        assert v1_session.query(Student).filter_by(id=sid).count() == 0
        assert v1_session.query(Submission).filter_by(student_id=sid).count() == 0
        assert v1_session.query(BaselineSample).filter_by(student_id=sid).count() == 0

    def test_force_delete_removes_scoring_results_and_instructor_decisions(self, v1_session):
        """Covers the True arm of the decision_count/scoring_count print
        gates via the subquery-based deletes -- also the arms that
        exercised the pre-fix bug most directly, since it fired regardless
        of whether these rows existed."""
        from original.db.models import (
            InstructorDecision,
            ScoringResult,
            Student,
            Submission,
        )

        sid = _seed_v1_student_with_scoring_and_decision(v1_session)
        assert cli.delete_student_data(sid, force=True) is True
        assert v1_session.query(Student).filter_by(id=sid).count() == 0
        assert v1_session.query(Submission).filter_by(student_id=sid).count() == 0
        assert v1_session.query(ScoringResult).count() == 0
        assert v1_session.query(InstructorDecision).count() == 0

    def test_force_delete_of_bare_student_with_no_associated_records(self, v1_session):
        """Covers the False arm of every "if <count> > 0" print gate --
        submissions/baselines/enrollments/decisions/scoring all zero for a
        student who has nothing beyond the Student row itself."""
        from original.db.models import Student

        sid = _seed_bare_student(v1_session)
        assert cli.delete_student_data(sid, force=True) is True
        assert v1_session.query(Student).filter_by(id=sid).count() == 0

    def test_declined_confirmation_deletes_nothing(self, v1_session, monkeypatch):
        from original.db.models import Student

        sid = _seed_v1_student(v1_session)
        monkeypatch.setattr("builtins.input", lambda _: "no")
        assert cli.delete_student_data(sid, force=False) is False
        assert v1_session.query(Student).filter_by(id=sid).count() == 1

    def test_typed_delete_confirms(self, v1_session, monkeypatch):
        sid = _seed_v1_student(v1_session)
        monkeypatch.setattr("builtins.input", lambda _: "DELETE")
        assert cli.delete_student_data(sid, force=False) is True

    def test_hard_delete_flag_is_accepted_but_changes_no_behavior(self, v1_session):
        """hard_delete is accepted by delete_student_data()'s signature but
        never read anywhere in its body (grep confirms no other reference)
        -- it selects no branch, both arms perform full deletion. Left as-is
        per controller decision (a product question, not a bug this task
        fixes). Uses two independently-seeded students since the first
        call's success removes the row the second call would otherwise
        target."""
        from original.db.models import Student

        sid_hard = _seed_v1_student(v1_session, sid="10000000-0000-0000-0000-000000000001")
        assert cli.delete_student_data(sid_hard, hard_delete=True, force=True) is True
        assert v1_session.query(Student).filter_by(id=sid_hard).count() == 0

        sid_soft = _seed_v1_student(v1_session, sid="10000000-0000-0000-0000-000000000002")
        assert cli.delete_student_data(sid_soft, hard_delete=False, force=True) is True
        assert v1_session.query(Student).filter_by(id=sid_soft).count() == 0

    def test_sqlalchemy_error_branch_reports_and_rolls_back(self, v1_session, monkeypatch, capsys):
        """Directly exercises the ``except SQLAlchemyError`` branch by
        forcing session.commit() to fail after every delete step has run
        but before anything is persisted. Asserts both the user-facing
        error message and the rollback safety net: a genuine (simulated)
        DB failure here leaves the student and every associated record
        untouched, not partially deleted."""
        from original.db.models import BaselineSample, Student, Submission

        sid = _seed_v1_student(v1_session)

        def _boom():
            raise SQLAlchemyError("simulated commit failure")

        monkeypatch.setattr(v1_session, "commit", _boom)
        assert cli.delete_student_data(sid, force=True) is False
        err = capsys.readouterr().err
        assert "Database error during deletion" in err

        # Only .commit was patched; the real .rollback() ran inside the
        # except block, so v1_session is safe to query again here and
        # confirms nothing was actually persisted (the rollback undid the
        # in-transaction deletes).
        assert v1_session.query(Student).filter_by(id=sid).count() == 1
        assert v1_session.query(Submission).filter_by(student_id=sid).count() == 1
        assert v1_session.query(BaselineSample).filter_by(student_id=sid).count() == 1

    def test_generic_exception_branch_reports_and_rolls_back(self, v1_session, monkeypatch, capsys):
        """Forces a non-SQLAlchemyError exception to reach the second
        ``except Exception`` handler -- there is no organic trigger for this
        arm (every real failure path in the function is a SQLAlchemyError
        subclass), so this deliberately, minimally monkeypatches an
        internal print helper to raise."""

        def _boom(*_args, **_kwargs):
            raise RuntimeError("boom")

        sid = _seed_v1_student(v1_session)
        monkeypatch.setattr(cli, "_print_info", _boom)
        assert cli.delete_student_data(sid, force=True) is False
        err = capsys.readouterr().err
        assert "Unexpected error" in err

        from original.db.models import Student

        assert v1_session.query(Student).filter_by(id=sid).count() == 1


class TestConfirmDeletion:
    def test_force_skips_the_prompt(self):
        assert cli._confirm_deletion("sid", "Name", force=True) is True

    def test_named_and_unnamed_prompts(self, monkeypatch, capsys):
        monkeypatch.setattr("builtins.input", lambda _: "DELETE")
        assert cli._confirm_deletion("sid-1", "Alice", force=False) is True
        assert "Alice" in capsys.readouterr().out

        monkeypatch.setattr("builtins.input", lambda _: "DELETE")
        assert cli._confirm_deletion("sid-2", None, force=False) is True
        assert "Student ID: sid-2" in capsys.readouterr().out

        monkeypatch.setattr("builtins.input", lambda _: "delete")  # wrong case
        assert cli._confirm_deletion("sid-3", None, force=False) is False


class TestMain:
    def test_missing_confirm_flag_returns_1(self, v1_session, capsys):
        sid = _seed_v1_student(v1_session)
        assert cli.main(["--student-id", sid]) == 1
        err = capsys.readouterr().err
        assert "--confirm flag is required" in err

    def test_missing_required_student_id_exits_2(self):
        with pytest.raises(SystemExit) as exc_info:
            cli.main(["--confirm"])
        assert exc_info.value.code == 2

    def test_confirmed_force_delete_of_unknown_student_returns_1(self, v1_session):
        assert cli.main(["--student-id", "no-such-id", "--confirm", "--force"]) == 1

    def test_confirmed_force_delete_of_real_student_returns_0_on_success(self, v1_session):
        sid = _seed_v1_student(v1_session)
        assert cli.main(["--student-id", sid, "--confirm", "--force"]) == 0

    def test_hard_delete_flag_is_accepted_and_threaded_through(self, v1_session):
        sid = _seed_v1_student(v1_session)
        assert cli.main(["--student-id", sid, "--confirm", "--force", "--hard-delete"]) == 0
