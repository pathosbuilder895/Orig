"""
tests/test_purge_keystroke_blobs.py — ADR-010 (T-74): stop persisting raw
keystroke arrays on ingest, and purge what's already at rest.

ADR-010 (docs/adr/ADR-010-keystroke-macro-only.md) retires per-key keystroke
capture. The raw ``keystrokes``/``pauses`` arrays inside a ``keystroke_data``
blob are the privacy-sensitive part (per-key timing); everything else in the
blob (``revisions``, ``deletionRate``, ``wordCount``, ``sessionDurationSec``,
``avgWpm``, etc.) is a macro/precomputed summary field and stays. This covers:

  1. ``POST /students/{id}/baseline`` no longer persists the raw arrays —
     ``original.routers.students_baseline._strip_raw_keystroke_arrays`` is
     applied before the sample is constructed. Other keys in the blob
     survive.
  2. ``scripts/purge_keystroke_blobs.py`` — dry-run (default) counts affected
     samples without writing; ``--apply`` rewrites them in place, stripping
     the same two keys, and persists via ``Repository.put()`` once per
     affected student.
  3. A sample with no raw arrays (already clean, or using the new
     ``composition_summary`` field instead) is correctly reported as
     needing no change, on both the dry-run and --apply paths.

All script testing here runs against ``store_reset``'s scratch SQLite file
(tests/conftest.py) — never the real ``profiles.db`` in this worktree.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import numpy as np
import pytest

from original.constants import FEATURE_DIM
from original.quantum.state import BaselineSample, StudentState

_ROOT = Path(__file__).resolve().parent.parent

_RAW_KEYSTROKE_BLOB = {
    "keystrokes": [{"key": "a", "elapsed": 100.0 * i} for i in range(20)],
    "pauses": [{"duration": 3000}],
    "revisions": [],
    "deletionRate": 0.02,
    "wordCount": 300,
    "sessionDurationSec": 1800,
    "avgWpm": 42.5,
}

_CLEAN_KEYSTROKE_BLOB = {
    "revisions": [],
    "deletionRate": 0.02,
    "wordCount": 300,
}

_COMPOSITION_SUMMARY = {
    "session_seconds": 1800,
    "word_count": 300,
    "paste_attempts": 0,
    "focus_losses": 1,
    "revision_count": 12,
    "started_at": "2026-09-20T14:00:00Z",
    "ended_at": "2026-09-20T14:30:00Z",
    "exam_config": {"block_copy": True, "min_words": 250, "duration_min": 30},
}


def _baseline_sample(**overrides) -> BaselineSample:
    kwargs = dict(
        text="x",
        vector=np.full(FEATURE_DIM, 0.5, dtype=np.float64),
        provenance="proctored",
        auth_weight=1.0,
    )
    kwargs.update(overrides)
    return BaselineSample(**kwargs)


def _load_purge_script():
    spec = importlib.util.spec_from_file_location(
        "purge_keystroke_blobs", _ROOT / "scripts" / "purge_keystroke_blobs.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ══════════════════════════════════════════════════════════════════════════════
# 1. _strip_raw_keystroke_arrays (original/routers/students_baseline.py)
# ══════════════════════════════════════════════════════════════════════════════


class TestStripRawKeystrokeArrays:
    def test_none_input_returns_none(self):
        from original.routers.students_baseline import _strip_raw_keystroke_arrays

        assert _strip_raw_keystroke_arrays(None) is None

    def test_strips_keystrokes_and_pauses_keeps_other_keys(self):
        from original.routers.students_baseline import _strip_raw_keystroke_arrays

        result = _strip_raw_keystroke_arrays(_RAW_KEYSTROKE_BLOB)
        assert "keystrokes" not in result
        assert "pauses" not in result
        assert result["deletionRate"] == 0.02
        assert result["wordCount"] == 300
        assert result["sessionDurationSec"] == 1800
        assert result["avgWpm"] == 42.5
        assert result["revisions"] == []

    def test_does_not_mutate_input(self):
        from original.routers.students_baseline import _strip_raw_keystroke_arrays

        original = dict(_RAW_KEYSTROKE_BLOB)
        _strip_raw_keystroke_arrays(_RAW_KEYSTROKE_BLOB)
        assert _RAW_KEYSTROKE_BLOB == original, "helper must not mutate its input"

    def test_already_clean_dict_is_returned_unchanged_in_content(self):
        from original.routers.students_baseline import _strip_raw_keystroke_arrays

        result = _strip_raw_keystroke_arrays(_CLEAN_KEYSTROKE_BLOB)
        assert result == _CLEAN_KEYSTROKE_BLOB

    def test_empty_dict_returns_empty_dict(self):
        from original.routers.students_baseline import _strip_raw_keystroke_arrays

        assert _strip_raw_keystroke_arrays({}) == {}


class TestScriptOwnStripHelperMirrorsRouterHelper:
    """scripts/purge_keystroke_blobs.py deliberately duplicates the stripping
    logic (see that module's docstring) rather than importing the router's
    helper. Exercise the script's own copy directly so both copies carry
    their own coverage of the None-input branch — main() itself never calls
    it with None (_needs_purge filters those out first), so this is the only
    path that reaches it."""

    def test_none_input_returns_none(self):
        mod = _load_purge_script()
        assert mod._strip_raw_keystroke_arrays(None) is None

    def test_strips_keystrokes_and_pauses_keeps_other_keys(self):
        mod = _load_purge_script()
        result = mod._strip_raw_keystroke_arrays(_RAW_KEYSTROKE_BLOB)
        assert "keystrokes" not in result
        assert "pauses" not in result
        assert result["deletionRate"] == 0.02


# ══════════════════════════════════════════════════════════════════════════════
# 1a. Ingestion endpoint applies the strip before persisting
# ══════════════════════════════════════════════════════════════════════════════


@pytest.fixture
def client(store_reset):
    from fastapi.testclient import TestClient

    import run

    return TestClient(run.load_legacy_demo_app())


class TestIngestEndpointStripsRawKeystrokeArrays:
    def test_proctored_baseline_strips_keystrokes_and_pauses_on_persist(self, client):
        from original import store

        sid = "demo:t74-purge-strip-regression"
        resp = client.post(
            f"/students/{sid}/baseline",
            json={
                "text": "This proctored sitting carries live Bbook keystroke telemetry "
                "that must never reach storage as raw per-key arrays. " * 3,
                "provenance": "proctored",
                "assignment": "midterm",
                "keystroke_data": _RAW_KEYSTROKE_BLOB,
            },
        )
        assert resp.status_code == 200, resp.text

        state = store.get(sid)
        assert state is not None and state.samples, "sample was not persisted"
        persisted = state.samples[-1].keystroke_data
        assert persisted is not None
        assert "keystrokes" not in persisted
        assert "pauses" not in persisted
        # Macro fields survive — only the raw per-key/per-pause arrays go.
        assert persisted["deletionRate"] == 0.02
        assert persisted["wordCount"] == 300
        assert persisted["sessionDurationSec"] == 1800
        assert persisted["avgWpm"] == 42.5

    def test_baseline_without_keystroke_data_stores_none(self, client):
        from original import store

        sid = "demo:t74-purge-strip-absent"
        resp = client.post(
            f"/students/{sid}/baseline",
            json={
                "text": "An uploaded paper with no live keystroke telemetry attached "
                "at all. " * 3,
                "provenance": "verified",
                "assignment": "essay1",
            },
        )
        assert resp.status_code == 200, resp.text

        state = store.get(sid)
        assert state is not None and state.samples
        assert state.samples[-1].keystroke_data is None


# ══════════════════════════════════════════════════════════════════════════════
# 2/3. scripts/purge_keystroke_blobs.py — dry-run vs --apply, over the
# Repository abstraction (backend-agnostic: SqliteRepository here via
# store_reset's scratch DB, never the real profiles.db).
# ══════════════════════════════════════════════════════════════════════════════


@pytest.fixture
def scratch_repo(store_reset):
    """A get_repository()-backed SqliteRepository isolated to a scratch DB.

    store_reset already points original.store's ORIGINAL_DB / _DB_PATH at a
    tmp_path file; get_repository() defaults to SqliteRepository (no
    REPO_BACKEND/REPO_SHADOW set in the test environment), which delegates to
    original.store — so this repo instance reads/writes the same scratch
    file store_reset isolated.
    """
    from original.repository import get_repository, reset_repository

    reset_repository()
    yield get_repository()
    reset_repository()


def _seed_state(repo, student_id: str, samples: list[BaselineSample]) -> None:
    state = StudentState(student_id=student_id, samples=[])
    for s in samples:
        state.add_sample(s)
    repo.put(state)


class TestPurgeScriptDryRunVsApply:
    def test_dry_run_default_reports_count_and_changes_nothing(self, scratch_repo, capsys):
        _seed_state(
            scratch_repo,
            "sem:purge-dry-run",
            [
                _baseline_sample(text="a", keystroke_data=_RAW_KEYSTROKE_BLOB),
                _baseline_sample(text="b", keystroke_data=_RAW_KEYSTROKE_BLOB),
            ],
        )

        mod = _load_purge_script()
        rc = mod.main([])  # no --apply => dry run
        assert rc == 0

        out = capsys.readouterr().out
        assert "DRY RUN" in out
        assert "2" in out  # 2 samples would be purged

        reloaded = scratch_repo.get("sem:purge-dry-run")
        assert reloaded.samples[0].keystroke_data == _RAW_KEYSTROKE_BLOB
        assert reloaded.samples[1].keystroke_data == _RAW_KEYSTROKE_BLOB
        assert "keystrokes" in reloaded.samples[0].keystroke_data
        assert "pauses" in reloaded.samples[0].keystroke_data

    def test_apply_rewrites_affected_samples_and_reports_count(self, scratch_repo, capsys):
        _seed_state(
            scratch_repo,
            "sem:purge-apply",
            [
                _baseline_sample(text="a", keystroke_data=_RAW_KEYSTROKE_BLOB),
                _baseline_sample(text="b", keystroke_data=_RAW_KEYSTROKE_BLOB),
            ],
        )

        mod = _load_purge_script()
        rc = mod.main(["--apply"])
        assert rc == 0

        out = capsys.readouterr().out
        assert "APPLY" in out
        assert "2" in out

        reloaded = scratch_repo.get("sem:purge-apply")
        for sample in reloaded.samples:
            assert sample.keystroke_data is not None
            assert "keystrokes" not in sample.keystroke_data
            assert "pauses" not in sample.keystroke_data
            # Macro fields survive the purge.
            assert sample.keystroke_data["deletionRate"] == 0.02
            assert sample.keystroke_data["wordCount"] == 300

    def test_apply_calls_put_once_per_affected_student_not_per_sample(
        self, scratch_repo, monkeypatch
    ):
        _seed_state(
            scratch_repo,
            "sem:purge-put-count",
            [
                _baseline_sample(text="a", keystroke_data=_RAW_KEYSTROKE_BLOB),
                _baseline_sample(text="b", keystroke_data=_RAW_KEYSTROKE_BLOB),
                _baseline_sample(text="c", keystroke_data=_RAW_KEYSTROKE_BLOB),
            ],
        )

        put_calls = []
        original_put = scratch_repo.put

        def _counting_put(state):
            put_calls.append(state.student_id)
            original_put(state)

        monkeypatch.setattr(scratch_repo, "put", _counting_put)

        mod = _load_purge_script()
        # Script calls get_repository() itself, so patch that to return our
        # instrumented instance.
        monkeypatch.setattr(mod, "get_repository", lambda: scratch_repo)
        rc = mod.main(["--apply"])
        assert rc == 0
        assert put_calls == [
            "sem:purge-put-count"
        ], "put() must be called exactly once per affected student, not once per sample"

    def test_covers_multiple_students_and_totals_across_them(self, scratch_repo, capsys):
        _seed_state(
            scratch_repo,
            "sem:purge-multi-a",
            [_baseline_sample(text="a", keystroke_data=_RAW_KEYSTROKE_BLOB)],
        )
        _seed_state(
            scratch_repo,
            "sem:purge-multi-b",
            [
                _baseline_sample(text="a", keystroke_data=_RAW_KEYSTROKE_BLOB),
                _baseline_sample(text="b", keystroke_data=_RAW_KEYSTROKE_BLOB),
            ],
        )

        mod = _load_purge_script()
        rc = mod.main(["--apply"])
        assert rc == 0

        out = capsys.readouterr().out
        assert "3" in out  # total samples across both students

        a = scratch_repo.get("sem:purge-multi-a")
        b = scratch_repo.get("sem:purge-multi-b")
        assert "keystrokes" not in a.samples[0].keystroke_data
        assert "keystrokes" not in b.samples[0].keystroke_data
        assert "keystrokes" not in b.samples[1].keystroke_data


# ══════════════════════════════════════════════════════════════════════════════
# 3. Already-clean samples (no raw arrays, or composition_summary instead)
# are reported as not needing changes and are left untouched.
# ══════════════════════════════════════════════════════════════════════════════


class TestPurgeScriptSkipsAlreadyCleanSamples:
    def test_clean_keystroke_data_is_not_counted_or_touched(self, scratch_repo, capsys):
        _seed_state(
            scratch_repo,
            "sem:purge-clean",
            [_baseline_sample(text="a", keystroke_data=_CLEAN_KEYSTROKE_BLOB)],
        )

        mod = _load_purge_script()
        rc = mod.main(["--apply"])
        assert rc == 0

        out = capsys.readouterr().out
        assert "0 sample" in out

        reloaded = scratch_repo.get("sem:purge-clean")
        assert reloaded.samples[0].keystroke_data == _CLEAN_KEYSTROKE_BLOB

    def test_composition_summary_only_sample_is_not_counted(self, scratch_repo, capsys):
        _seed_state(
            scratch_repo,
            "sem:purge-composition-only",
            [_baseline_sample(text="a", composition_summary=_COMPOSITION_SUMMARY)],
        )

        mod = _load_purge_script()
        rc = mod.main(["--apply"])
        assert rc == 0

        out = capsys.readouterr().out
        assert "0 sample" in out

        reloaded = scratch_repo.get("sem:purge-composition-only")
        assert reloaded.samples[0].keystroke_data is None
        assert reloaded.samples[0].composition_summary == _COMPOSITION_SUMMARY

    def test_no_keystroke_data_at_all_is_not_counted(self, scratch_repo, capsys):
        _seed_state(
            scratch_repo,
            "sem:purge-none",
            [_baseline_sample(text="a")],
        )

        mod = _load_purge_script()
        rc = mod.main(["--apply"])
        assert rc == 0

        out = capsys.readouterr().out
        assert "0 sample" in out

    def test_mixed_state_only_affected_samples_change(self, scratch_repo):
        _seed_state(
            scratch_repo,
            "sem:purge-mixed",
            [
                _baseline_sample(text="a", keystroke_data=_RAW_KEYSTROKE_BLOB),
                _baseline_sample(text="b", keystroke_data=_CLEAN_KEYSTROKE_BLOB),
                _baseline_sample(text="c"),
            ],
        )

        mod = _load_purge_script()
        rc = mod.main(["--apply"])
        assert rc == 0

        reloaded = scratch_repo.get("sem:purge-mixed")
        assert "keystrokes" not in reloaded.samples[0].keystroke_data
        assert reloaded.samples[1].keystroke_data == _CLEAN_KEYSTROKE_BLOB  # untouched
        assert reloaded.samples[2].keystroke_data is None


# ══════════════════════════════════════════════════════════════════════════════
# 4. The purge script never touches the real profiles.db — self-check that
# the fixture wiring actually isolates ORIGINAL_DB, as a guard against a
# future refactor accidentally dropping store_reset from a new test.
# ══════════════════════════════════════════════════════════════════════════════


class TestPurgeScriptDbIsolation:
    def test_scratch_repo_points_at_tmp_path_not_real_profiles_db(self, scratch_repo, tmp_path):
        from original import store

        assert str(tmp_path) in str(store._DB_PATH)
        assert store._DB_PATH.name != "profiles.db" or str(tmp_path) in str(store._DB_PATH)
        real_db = _ROOT / "profiles.db"
        assert store._DB_PATH != real_db
