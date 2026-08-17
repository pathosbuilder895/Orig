# Branch Coverage Part 3 — Security, CLI & Support Modules Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Read `2026-08-17-branch-coverage-index.md` §Global Constraints first — they all apply here.

**Goal:** Close the 208 missing branches in the worst-covered cluster (50.48%). It hides the two highest-stakes zero-coverage tools in the repo: `original/cli/delete_student.py` — the **documented manual FERPA-deletion path** — and `original/cli/security_audit.py`, plus the fully-untested `student_auth.verify_launch_token` (8/8) that gates Bluebook exam launches.

**Architecture:** Three tiers by stakes. (1) Security/compliance tools get real behavioral suites (deletion actually deletes; the audit actually flags). (2) Live-stack support modules (`student_auth`, `voice`, `explainer`, `tension_arc`, `baseline_requests`, `principal`, `backup`, `users`, `_env`) get ordinary branch tests. (3) Dormant-v1 leftovers (`core/config.py`, `core/logging.py`, `core/security.py`) get thin reachability tests only — they are kept alive solely because the CLIs import them (see `pyproject.toml`'s extend-exclude comment); do not build them out.

**Tech Stack:** pytest, monkeypatch, tmp_path, sqlite in-memory for the v1 session; no new dependencies.

**Baseline data:** `2026-08-17-branch-coverage-baseline.md` §other.

## Global Constraints (additional to the index's)

- The v1 CLIs use the DORMANT SQLAlchemy stack (`original/db/`, v1 models) — point them at a throwaway sqlite URL via env/monkeypatch; never at `profiles.db` or any real store.
- `_confirm_deletion` reads `input()` — tests monkeypatch `builtins.input`, never bypass the confirmation logic itself (it IS the branch under test).
- `student_auth` token tests mint their own tokens with the module's own signing helpers and a test `SECRET_KEY` (conftest sets one) — never embed a hardcoded signed token blob that rots when the scheme changes.

## Measured gap tables (2026-08-17)

| File | Branch % | Missing | Fully-untaken functions |
|---|---|---|---|
| `cli/security_audit.py` | 0.00 | 76 | every check: `check_raw_sql` 14, `check_jwt_config` 10, `check_database_security` 10, `print_summary` 8, `check_rate_limiting` 8, `check_tls_readiness` 6, `run_all_checks` 4, `check_pip_audit` 4, `check_input_validation` 4, `check_cors_configuration` 4, `_print_info` 2, module 2 |
| `cli/delete_student.py` | 0.00 | 22 | `delete_student_data` 14/14, `_confirm_deletion` 4/4, `main` 2/2, module 2/2 |
| `tension_arc.py` | 77.14 | 16 | `_classify_move` 3/12, module 3/4, `_authenticity_signal` 2/2, `_arc_flag` 2/8, `_analyze_paragraph` 2/6, singles |
| `core/config.py` | 0.00 | 16 | `Settings.validate_production_secrets` 14/14, `ALLOWED_ORIGINS` 2/2 |
| `_env.py` | 0.00 | 14 | `load_env_file` 14/14 |
| `explainer.py` | 59.38 | 13 | `explain` 10/26, `_delta_intensity` 3/6 |
| `voice.py` | 76.09 | 11 | `project_headline` 3/8, `project_submission_result` 2/14, `_clamp01` 2/4, singles |
| `student_auth.py` | 60.71 | 11 | `verify_launch_token` **8/8**, `verify_proctor_attestation` 2/10, `verify_session` 1/10 |
| `core/logging.py` | 0.00 | 10 | `JSONFormatter.format` 6/6, `configure_logging` 2/2, `RequestLoggingMiddleware.dispatch` 2/2 |
| `core/security.py` | 0.00 | 8 | `_docs_relaxed_csp` 6/6, `SecurityHeadersMiddleware.dispatch` 2/2 |
| `baseline_requests.py` | 76.92 | 6 | `mark_failed` 2/4, `_persist_snapshot` 2/2, singles |
| `principal.py` / `backup.py` / `users.py` | — | 2+2+1 | singles |

---

### Task 1: FERPA deletion CLI — `cli/delete_student.py` (worked example)

**Files:**
- Create: `tests/test_delete_student_cli.py`

**Interfaces:**
- Consumes: `original.cli.delete_student.delete_student_data(student_id, hard_delete=False, force=False)` and `_confirm_deletion(student_id, student_name, force)`; the v1 models (`Student`, `Submission`, `BaselineSample`, `StudentEnrollment`, `ScoringResult`, `InstructorDecision`) via a sqlite-backed session.
- Produces: a `_seed_v1_student(session)` helper later steps reuse.

This is a compliance tool at 0%: nobody has ever verified under test that "delete" deletes, that cascades reach scoring results and decisions, or that the confirmation gate holds.

- [ ] **Step 1: Build the isolated v1 database fixture**

Read `original/cli/delete_student.py:1-78` for `_get_db_session()`'s wiring, then:

```python
"""Behavioral tests for the manual FERPA-deletion CLI (branch-coverage part 3)."""

from __future__ import annotations

import pytest

from original.cli import delete_student as cli


@pytest.fixture
def v1_session(tmp_path, monkeypatch):
    """A throwaway sqlite-backed v1 session, patched into the CLI module."""
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from original.db.base import Base  # v1 declarative base

    engine = create_engine(f"sqlite:///{tmp_path}/v1.db")
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    monkeypatch.setattr(cli, "_get_db_session", lambda: session)
    yield session
    session.close()
```

(Adjust the `Base` import to whatever `original/db/base.py` actually exports — verify before writing; if the models need an institution/course scaffold for FK integrity, seed those in the helper below.)

- [ ] **Step 2: Write the failing behavioral tests**

```python
def _seed_v1_student(session, sid="00000000-0000-0000-0000-000000000001"):
    from original.db.models import (
        BaselineSample, Student, StudentEnrollment, Submission,
    )
    student = Student(id=sid, full_name="Test Student", external_id="ext-1")
    session.add(student)
    session.add(BaselineSample(student_id=sid, text="baseline text"))
    session.add(Submission(id="sub-1", student_id=sid, text="submission text"))
    session.add(StudentEnrollment(student_id=sid))
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

    def test_declined_confirmation_deletes_nothing(self, v1_session, monkeypatch):
        from original.db.models import Student
        sid = _seed_v1_student(v1_session)
        monkeypatch.setattr("builtins.input", lambda _: "no")
        assert cli.delete_student_data(sid, force=False) is False
        assert v1_session.query(Student).filter_by(id=sid).count() == 1

    def test_typed_DELETE_confirms(self, v1_session, monkeypatch):
        sid = _seed_v1_student(v1_session)
        monkeypatch.setattr("builtins.input", lambda _: "DELETE")
        assert cli.delete_student_data(sid, force=False) is True


class TestConfirmDeletion:
    def test_force_skips_the_prompt(self):
        assert cli._confirm_deletion("sid", "Name", force=True) is True

    def test_named_and_unnamed_prompts(self, monkeypatch, capsys):
        monkeypatch.setattr("builtins.input", lambda _: "DELETE")
        assert cli._confirm_deletion("sid-1", "Alice", force=False) is True
        assert "Alice" in capsys.readouterr().out
        monkeypatch.setattr("builtins.input", lambda _: "delete")  # wrong case
        assert cli._confirm_deletion("sid-2", None, force=False) is False
```

Model constructor kwargs above are illustrative of the v1 schema read on 2026-08-17 (`full_name`, `external_id` are real — `delete_student.py:137`); reconcile every kwarg against `original/db/models/` before running, and give `Submission`/`BaselineSample` whatever NOT-NULL columns the models declare.

- [ ] **Step 3: Run**

Run: `.venv/bin/python -m pytest tests/test_delete_student_cli.py -q`
Expected: PASS after kwarg reconciliation; a `test_force_delete_removes_every_associated_record` failure is a REAL FERPA finding — escalate it in the session summary, do not soften the assertion.

- [ ] **Step 4: Cover the remaining arms** — `hard_delete=True` vs soft-delete audit-trail arm (read `delete_student.py:199-303` first), the per-count `if count > 0` print arms (seed a student with zero decisions), and `main`'s argparse arms (invoke `cli.main(["--force", sid])` style per its signature).

- [ ] **Step 5: Verify + commit**

```bash
.venv/bin/python -m pytest tests/test_delete_student_cli.py -q \
  --cov=original.cli.delete_student --cov-branch --cov-report=term-missing
git add tests/test_delete_student_cli.py
git commit -m "Add behavioral tests for the FERPA delete-student CLI (was 0% covered)"
```

---

### Task 2: `cli/security_audit.py` (76 missing, 0%)

- [ ] Read the module; each `check_*` inspects repo/config state and appends findings. For each check write a pair: one fixture arrangement that PASSES the check and one that triggers its finding arm (e.g. `check_jwt_config` with a strong vs default `SECRET_KEY` env; `check_raw_sql` against a tmp tree containing a seeded `execute("SELECT ... %s" % x)` offender vs a clean tree — point its scan root at `tmp_path` via its parameter or monkeypatch).
- [ ] `run_all_checks` + `print_summary`: run with all-green and with ≥1 finding; assert the exit/summary arms.
- [ ] Verify (`--cov=original.cli.security_audit --cov-branch`) + commit `"Add security-audit CLI check tests (was 0% covered)"`.

### Task 3: `student_auth.py` — launch/session/attestation token arms (11)

- [ ] `verify_launch_token` 8/8: valid token; expired; wrong signature; malformed/truncated; each documented claim-check arm. Mint with the module's own issue/sign helper under conftest's `SECRET_KEY`.
- [ ] `verify_proctor_attestation`'s 2 and `verify_session`'s 1 remaining arms (extract exact lines with the index snippet).
- [ ] Verify + commit `"Add student-auth token verification branch tests"`.

### Task 4: `_env.py` + `voice.py` + `explainer.py` + `tension_arc.py` + `baseline_requests.py` + singles (62)

- [ ] `load_env_file` 14/14: file absent; blank lines; comments; `export KEY=v`; quoted values; malformed lines; existing-env-not-overwritten arm — one tmp_path `.env` fixture per arm.
- [ ] `voice.py`/`explainer.py`: pure projection functions — table-driven tests over the score/flag combinations that select each untaken phrase/intensity arm (extract exact lines first; `_clamp01` 2/4 wants out-of-range inputs both sides).
- [ ] `tension_arc.py`: module-level 3/4 are import-fallback arms (optional model deps) — cover via monkeypatched import failure in a subprocess or `importlib.reload` under a blocked import; `_classify_move`/`_arc_flag`/`_analyze_paragraph` arms are input-shape driven.
- [ ] `baseline_requests.py`: `mark_failed` on absent request, `_persist_snapshot` failure arm, `record` duplicate arm.
- [ ] `principal.py`/`backup.py`/`users.py` singles: bad principal token, missing backup dir, `verify_password` mismatch.
- [ ] Verify + commit per module cluster.

### Task 5: Dormant-v1 thin reachability (`core/config.py`, `core/logging.py`, `core/security.py`) (34)

- [ ] ONE test file `tests/test_dormant_core_reachability.py`: `Settings.validate_production_secrets` all 14 arms are secret-strength ladder checks — instantiate `Settings` with each offending value and assert the raise/pass; `JSONFormatter.format` with/without exc_info and extras; `_docs_relaxed_csp` docs-path vs api-path arms via a minimal Starlette app. Do NOT expand scope beyond making each arm run once — deletion of this surface is already planned (see `pyproject.toml`).
- [ ] Verify + commit `"Add thin reachability tests for the dormant v1 core modules"`.

### Task 6: Sweep + part completion

- [ ] Re-measure; the cluster must reach ≥95% branch or carry justified annotations; drain partials; update the index dashboard; apply the CI ratchet; commit `"Record part 3 security-cli-support branch-coverage completion"`.

## Self-Review Notes

- Task 1's assertions were written from the actual deletion sequence read on 2026-08-17 (`delete_student.py:106-198`): decisions→scoring→submissions→baselines ordering, `full_name`/`external_id` attributes, the `'DELETE'` exact-match confirmation. The declared verify-then-reconcile points are the model constructor kwargs and `main`'s argv signature — both live in files this plan deliberately did not fully read.
- Tier boundaries matter: if a Task 5 module grows real coverage needs, that is scope creep — flag it, don't build it.
