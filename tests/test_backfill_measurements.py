"""scripts/backfill_measurements.py (ADR-014): dry run by default, explicit
confirm to write, idempotent, never touches ``vector``, skips a student whose
papers changed mid-run, same on SQLite and Postgres, never run automatically."""

from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

import numpy as np
import pytest

from original.constants import FEATURE_DIM
from original.features import feature_flags as ff
from original.quantum.state import BaselineSample, StudentState
from original.repository import get_repository, reset_repository

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "backfill_measurements", ROOT / "scripts" / "backfill_measurements.py"
)
bf = importlib.util.module_from_spec(_spec)
sys.modules["backfill_measurements"] = bf  # dataclasses look their module up
_spec.loader.exec_module(bf)


def _postgres_available() -> bool:
    if not os.environ.get("DATABASE_URL", "").startswith("postgresql"):
        return False
    from original.db import postgres_session

    try:
        postgres_session.reset_engine()
        with postgres_session.get_engine().connect():
            return True
    except Exception:
        return False


@pytest.fixture(params=["sqlite", pytest.param("postgres", marks=pytest.mark.postgres)])
def repo(request, store_reset):
    reset_repository()
    if request.param == "sqlite":
        yield get_repository()
    else:
        if not _postgres_available():
            pytest.skip("uninformative — no reachable Postgres; set DATABASE_URL to run")
        from original.db import postgres_session
        from original.db.models.live import LiveBase
        from original.postgres_repository import PostgresRepository

        engine = postgres_session.get_engine()
        LiveBase.metadata.create_all(bind=engine)
        with engine.begin() as conn:
            for table in reversed(LiveBase.metadata.sorted_tables):
                conn.execute(table.delete())
        yield PostgresRepository()
    reset_repository()


def _state(sid: str, texts: list[str]) -> StudentState:
    st = StudentState(student_id=sid)
    for i, t in enumerate(texts):
        st.add_sample(
            BaselineSample(
                text=t,
                vector=np.full(FEATURE_DIM, 0.5),
                provenance="verified",
                auth_weight=1.0,
                assignment=f"A{i}",
            )
        )
    return st


class Extract:
    """A stand-in extractor that records which measurement it ran under."""

    def __init__(self):
        self.calls: list[str] = []

    def __call__(self, text):
        self.calls.append(ff.current_measurement())
        if text == "boom":
            raise RuntimeError("bad paper")
        return np.full(FEATURE_DIM, 0.25)


def test_dry_run_writes_nothing(repo):
    repo.put(_state("t:a", ["one", "two"]))
    ex = Extract()
    report = bf.backfill(repo, "fs2+matter", apply=False, extract=ex)
    assert (report.students, report.papers, report.to_measure, report.measured) == (1, 2, 2, 0)
    assert ex.calls == []
    assert all(s.extra_vectors is None for s in repo.get("t:a").samples)
    report = bf.backfill(repo, "fs2+matter", apply=False, measure_in_dry_run=True, extract=ex)
    assert ex.calls == ["fs2+matter", "fs2+matter"]
    assert all(s.extra_vectors is None for s in repo.get("t:a").samples)
    assert "DRY RUN" in "\n".join(report.lines())


def test_apply_is_idempotent_and_keeps_vector(repo):
    repo.put(_state("t:a", ["one", "two"]))
    repo.put(_state("t:b", ["three", ""]))
    ex = Extract()
    first = bf.backfill(repo, "fs2", apply=True, extract=ex)
    assert (first.measured, first.written_students, first.no_text) == (3, 2, 1)
    a = repo.get("t:a")
    assert all(np.array_equal(s.vector, np.full(FEATURE_DIM, 0.5)) for s in a.samples)
    assert all(
        np.array_equal(s.extra_vectors["fs2"], np.full(FEATURE_DIM, 0.25)) for s in a.samples
    )
    ex.calls.clear()
    second = bf.backfill(repo, "fs2", apply=True, extract=ex)
    assert (second.measured, second.written_students, second.already) == (
        0,
        0,
        3,
    ) and ex.calls == []
    third = bf.backfill(repo, "matter", apply=True, students=["t:a"], extract=ex)
    assert third.measured == 2 and set(repo.get("t:a").samples[0].extra_vectors) == {
        "fs2",
        "matter",
    }
    assert "students written: 1" in "\n".join(third.lines())


def test_failures_missing_students_and_changes_are_reported(repo):
    repo.put(_state("t:a", ["one", "boom"]))
    report = bf.backfill(repo, "fs2", apply=True, students=["t:a", "t:nobody"], extract=Extract())
    assert report.failed == ["t:a#1", "t:nobody (not found)"] and report.measured == 1
    assert "failed: 2" in "\n".join(report.lines())

    repo.put(_state("t:c", ["x", "y"]))

    class Racing(Extract):
        def __call__(self, text):
            if text == "y":  # a paper is added while the backfill runs
                st = repo.get("t:c")
                st.add_sample(
                    BaselineSample(
                        text="z",
                        vector=np.zeros(FEATURE_DIM),
                        provenance="verified",
                        auth_weight=1.0,
                    )
                )
                repo.put(st)
            return super().__call__(text)

    report = bf.backfill(repo, "fs2", apply=True, students=["t:c"], extract=Racing())
    assert report.changed == ["t:c"] and report.measured == 0
    assert all(s.extra_vectors is None for s in repo.get("t:c").samples)
    assert "papers changed during the run" in "\n".join(report.lines())


def test_wrong_length_vector_is_a_failure(repo):
    repo.put(_state("t:a", ["one"]))
    report = bf.backfill(repo, "fs2", apply=True, extract=lambda t: np.zeros(3))
    assert report.failed == ["t:a#0"]
    with pytest.raises(ValueError, match="unknown measurement"):
        bf.backfill(repo, "v1", apply=False)


def test_main_needs_explicit_confirm(repo, capsys, monkeypatch):
    repo.put(_state("t:a", ["one"]))
    monkeypatch.setattr(
        bf, "backfill", lambda *a, **k: (_ for _ in ()).throw(AssertionError("ran"))
    )
    with pytest.raises(SystemExit):
        bf.main(["--apply"], repo=repo)
    with pytest.raises(SystemExit):
        bf.main(["--apply", "--measurement", "fs2", "--confirm", "fs2+matter"], repo=repo)
    assert "nothing was written" in capsys.readouterr().err


def test_main_dry_run_and_apply(repo, capsys, monkeypatch):
    repo.put(_state("t:a", ["one"]))
    real = bf.backfill
    monkeypatch.setattr(bf, "backfill", lambda *a, **k: real(*a, **k, extract=Extract()))
    assert bf.main([], repo=repo) == 0
    assert "DRY RUN" in capsys.readouterr().out
    assert bf.main(["--apply", "--confirm", "fs2+matter"], repo=repo) == 0
    assert "fs2+matter" in repo.get("t:a").samples[0].extra_vectors
    assert bf.main(["--student", "t:missing"], repo=repo) == 1


def test_main_uses_the_configured_repository(store_reset, capsys):
    reset_repository()
    try:
        assert bf.main([]) == 0
        assert "backend: sqlite" in capsys.readouterr().out
    finally:
        reset_repository()


def test_real_extraction_under_the_named_measurement(repo):
    text = (Path(__file__).parent / "fixtures" / "paper_matter" / "mla_docx.txt").read_text(
        encoding="utf-8"
    )
    repo.put(_state("t:a", [text]))
    bf.backfill(repo, "fs2+matter", apply=True)
    from original.features.pipeline import feature_vector

    with ff.measuring("fs2+matter"):
        expected = feature_vector(text)
    assert np.allclose(repo.get("t:a").samples[0].extra_vectors["fs2+matter"], expected)


def test_nothing_runs_the_backfill_automatically():
    """Not in the deploy, start scripts or CI, and no app code imports or spawns it."""
    places = [
        ROOT / "render.yaml",
        ROOT / "Dockerfile.demo",
        ROOT / "run.py",
        ROOT / "Makefile",
        *ROOT.glob(".github/workflows/*.yml"),
        *ROOT.glob("scripts/*.sh"),
    ]
    for path in places:
        if path.is_file():
            assert "backfill_measurements" not in path.read_text(
                encoding="utf-8", errors="ignore"
            ), path
    import re

    spawn = re.compile(
        r"import\s+backfill_measurements|from\s+\S*backfill_measurements|"
        r"(?:subprocess|os\.system|Popen|run_path)\W[^\n]*backfill_measurements"
    )
    for path in ROOT.glob("original/**/*.py"):
        assert not spawn.search(path.read_text(encoding="utf-8")), path
