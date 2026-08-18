"""Behavioral tests for the manual FERPA-deletion CLI (branch-coverage part 3, task 1).

``original/cli/delete_student.py`` is 0% covered. It targets the DORMANT v1
SQLAlchemy stack (``original/db/models``) via a raw ``Session`` -- a
completely separate persistence layer from the LIVE stack's
``store.py``/``postgres_repository.py``. The module's own header docstring
already disclaims it: "NOT the live FERPA deletion path ... Do not treat
this CLI as authoritative for student data deletion." The live path is
``DELETE /students/{id}`` (``original/routers/students.py`` ->
``store.delete_student``/``postgres_repository.delete_student``), which is
extensively covered elsewhere (``tests/test_pilot_lockdown.py``,
``tests/test_repository_contract.py``, ``tests/test_persistence_error_arms.py``,
``tests/test_store_fidelity.py``, ``tests/fusion/test_persistence.py``).
Nothing here touches that path or any real data -- see the ``v1_session``
fixture below.

*** REAL BUG FOUND, 2026-08-18 ***
``delete_student_data()``'s first two delete steps build queries shaped like
``session.query(InstructorDecision).join(Submission).filter(...).delete(...)``
(and the identical shape for ``ScoringResult``, delete_student.py:167-182).
SQLAlchemy's ORM ``Query`` API unconditionally forbids calling
``.delete()``/``.update()`` on a ``Query`` that has already had ``.join()``
called on it:

    sqlalchemy.exc.InvalidRequestError: Can't call Query.update() or
    Query.delete() when join(), outerjoin(), select_from(), or from_self()
    has been called

This is a query-construction-time check, independent of whether any row
would actually match -- it fires even against completely empty tables (see
the reproduction referenced in .superpowers/sdd/p3-task-1-report.md). That
means every confirmed deletion (``force=True`` or typed "DELETE") for every
student, with or without associated decisions/scores, is caught by the
``except SQLAlchemyError`` handler, rolled back, and reported as "Database
error during deletion" -- ``delete_student_data()`` can never return
``True`` through this code path, and by extension ``main()`` can never
return exit code 0 for a real deletion, on the pinned SQLAlchemy
(requirements.txt pins 2.0.51; reproduced here on the installed 2.0.35 --
this ``Query.delete()`` restriction is a stable, version-independent part of
the ORM Query API, not a recent regression, so this is not expected to be a
version artifact).

Practical fallout for this test file: every line past the first delete step
-- the per-count "if count > 0" print arms, the final success prints, and
the ``log.info`` call (delete_student.py:173-226) -- is unreachable through
this function as it ships today. No ``# pragma: no cover`` was added for
that region; it is a real, honestly-reported coverage gap caused by a real
bug, not an intentionally-excluded branch. See
.superpowers/sdd/p3-task-1-report.md for the full writeup.

The two tests that assert the *intended* (bug-free) behavior keep their
original, un-softened assertions and are marked ``xfail(strict=True)`` so a
real fix flips them to an XPASS failure that demands this comment (and the
report) be updated. Separate, passing tests characterize the actual current
behavior without asserting it is correct.
"""

from __future__ import annotations

from datetime import datetime

import pytest

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


class TestDeleteStudentData:
    def test_unknown_student_returns_false(self, v1_session):
        assert cli.delete_student_data("no-such-id", force=True) is False

    @pytest.mark.xfail(
        strict=True,
        reason=(
            "REAL BUG (see module docstring): "
            "session.query(InstructorDecision).join(Submission).delete() raises "
            "sqlalchemy.exc.InvalidRequestError because Query.delete() forbids a "
            "prior .join(). Confirmed deletions always fail today -- this test "
            "encodes the correct/intended behavior, deliberately not softened."
        ),
    )
    def test_force_delete_removes_every_associated_record(self, v1_session):
        from original.db.models import BaselineSample, Student, Submission

        sid = _seed_v1_student(v1_session)
        assert cli.delete_student_data(sid, force=True) is True
        assert v1_session.query(Student).filter_by(id=sid).count() == 0
        assert v1_session.query(Submission).filter_by(student_id=sid).count() == 0
        assert v1_session.query(BaselineSample).filter_by(student_id=sid).count() == 0

    def test_force_delete_currently_fails_and_deletes_nothing(self, v1_session):
        """Characterizes the ACTUAL current behavior (the inverse of the
        xfail'd test above, which encodes the correct/intended behavior).
        This one passes for real and pins down that a confirmed deletion
        attempt (1) returns False, not True, and (2) leaves every record
        untouched -- session.rollback() undoes the attempt cleanly, so a
        student with real associated data is never left partially/orphaned-
        deleted by this bug, it's just never deleted at all."""
        from original.db.models import BaselineSample, Student, StudentEnrollment, Submission

        sid = _seed_v1_student(v1_session)
        assert cli.delete_student_data(sid, force=True) is False
        assert v1_session.query(Student).filter_by(id=sid).count() == 1
        assert v1_session.query(Submission).filter_by(student_id=sid).count() == 1
        assert v1_session.query(BaselineSample).filter_by(student_id=sid).count() == 1
        assert v1_session.query(StudentEnrollment).filter_by(student_id=sid).count() == 1

    def test_declined_confirmation_deletes_nothing(self, v1_session, monkeypatch):
        from original.db.models import Student

        sid = _seed_v1_student(v1_session)
        monkeypatch.setattr("builtins.input", lambda _: "no")
        assert cli.delete_student_data(sid, force=False) is False
        assert v1_session.query(Student).filter_by(id=sid).count() == 1

    @pytest.mark.xfail(
        strict=True,
        reason="Same underlying join()+delete() bug as test_force_delete_removes_every_associated_record.",
    )
    def test_typed_DELETE_confirms(self, v1_session, monkeypatch):
        sid = _seed_v1_student(v1_session)
        monkeypatch.setattr("builtins.input", lambda _: "DELETE")
        assert cli.delete_student_data(sid, force=False) is True

    def test_typed_DELETE_passes_the_gate_then_hits_the_same_bug(self, v1_session, monkeypatch):
        """Isolates the confirmation-prompt behavior (input() is consulted,
        "DELETE" is accepted, the gate opens) from the unrelated DB bug that
        fires once deletion actually starts."""
        sid = _seed_v1_student(v1_session)
        monkeypatch.setattr("builtins.input", lambda _: "DELETE")
        assert cli.delete_student_data(sid, force=False) is False

    def test_hard_delete_flag_hits_the_same_bug_as_soft_delete(self, v1_session):
        """hard_delete is accepted by delete_student_data()'s signature but
        never read anywhere in its body (grep confirms no other reference)
        -- it selects no branch. Both arms currently observe the same
        (buggy) outcome; this documents that rather than assuming a
        soft-delete audit-trail arm exists."""
        sid = _seed_v1_student(v1_session)
        assert cli.delete_student_data(sid, hard_delete=True, force=True) is False
        assert cli.delete_student_data(sid, hard_delete=False, force=True) is False

    def test_sqlalchemy_error_branch_reports_and_rolls_back(self, v1_session, capsys):
        """Directly exercises the ``except SQLAlchemyError`` branch -- the
        same branch the join()+delete() bug hits organically -- and asserts
        the user-facing error message."""
        sid = _seed_v1_student(v1_session)
        assert cli.delete_student_data(sid, force=True) is False
        err = capsys.readouterr().err
        assert "Database error during deletion" in err

    def test_generic_exception_branch_reports_and_rolls_back(self, v1_session, monkeypatch, capsys):
        """Forces a non-SQLAlchemyError exception to reach the second
        ``except Exception`` handler, which the organic SQLAlchemy bug above
        does NOT exercise (InvalidRequestError is a SQLAlchemyError subclass,
        caught by the more specific handler first) -- this is the only way
        to reach this branch without a second, unrelated bug."""

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

    def test_confirmed_force_delete_of_real_student_currently_returns_1(self, v1_session):
        """Would be the exit-0 "success" arm once the join()+delete() bug
        above is fixed; documents the actual current outcome instead of
        softening it -- see TestDeleteStudentData's matching pair."""
        sid = _seed_v1_student(v1_session)
        assert cli.main(["--student-id", sid, "--confirm", "--force"]) == 1

    @pytest.mark.xfail(
        strict=True,
        reason="Same underlying join()+delete() bug; main() can never return 0 today.",
    )
    def test_confirmed_force_delete_of_real_student_returns_0_on_success(self, v1_session):
        sid = _seed_v1_student(v1_session)
        assert cli.main(["--student-id", sid, "--confirm", "--force"]) == 0

    def test_hard_delete_flag_is_accepted_and_threaded_through(self, v1_session):
        sid = _seed_v1_student(v1_session)
        assert cli.main(["--student-id", sid, "--confirm", "--force", "--hard-delete"]) == 1
