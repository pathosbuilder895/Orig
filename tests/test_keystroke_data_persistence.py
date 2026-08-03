"""
tests/test_keystroke_data_persistence.py — persisting the Tier 17 keystroke blob.

Before this change, ``POST /students/{id}/baseline`` received ``keystroke_data``
on the request, used it TRANSIENTLY to extract the (disabled) Tier 17 features
into the feature vector, and then discarded it — the raw blob never reached
``BaselineSample`` or either storage backend. That left
``scripts/tier17_report.py`` structurally pinned at 0 samples forever (see its
module docstring), even against a production database full of proctored Bbook
sittings.

This is metadata storage, not a scoring change: the six Tier 17 features stay
in ``DISABLED_FEATURE_GROUPS`` regardless of whether this blob is persisted.
These tests cover:

  1. ``BaselineSample.keystroke_data`` defaults to None (additive field).
  2. SQLite round-trip (``store._serialize`` / ``_deserialize``).
  3. SQLite backward compatibility: a sample dict serialized before this
     field existed still deserializes, with ``keystroke_data=None``.
  4. Postgres round-trip (``PostgresRepository._state_to_doc`` / ``_doc_to_state``
     — pure functions, no live database required).
  5. Postgres backward compatibility, mirroring (3).
  6. The ingestion endpoint threads ``req.keystroke_data`` onto the persisted
     sample.
  7. ``scripts/tier17_report.py`` counts real samples persisted through
     ``original.store`` end-to-end (not just the synthetic raw-SQL fixtures
     in tests/test_tier17_report.py).
"""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import numpy as np
import pytest

from original.constants import FEATURE_DIM
from original.quantum.state import BaselineSample, StudentState

_ROOT = Path(__file__).resolve().parent.parent
_KEYSTROKE_BLOB = {
    "keystrokes": [{"key": "a", "elapsed": 100.0 * i} for i in range(20)],
    "pauses": [{"duration": 3000}],
    "revisions": [],
    "deletionRate": 0.02,
    "wordCount": 300,
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


# ══════════════════════════════════════════════════════════════════════════════
# 1. BaselineSample default
# ══════════════════════════════════════════════════════════════════════════════


class TestBaselineSampleDefault:
    def test_keystroke_data_defaults_to_none(self):
        s = _baseline_sample()
        assert s.keystroke_data is None

    def test_keystroke_data_can_be_set(self):
        s = _baseline_sample(keystroke_data=_KEYSTROKE_BLOB)
        assert s.keystroke_data == _KEYSTROKE_BLOB


# ══════════════════════════════════════════════════════════════════════════════
# 2/3. SQLite: store._serialize / _deserialize
# ══════════════════════════════════════════════════════════════════════════════


class TestSqliteSerialization:
    def test_round_trip_carries_keystroke_data(self):
        from original.store import _deserialize, _serialize

        state = StudentState(student_id="s", samples=[])
        state.add_sample(_baseline_sample(text="a", keystroke_data=_KEYSTROKE_BLOB))
        state.add_sample(_baseline_sample(text="b"))  # no keystroke data — stays None

        revived = _deserialize(_serialize(state))
        assert revived.samples[0].keystroke_data == _KEYSTROKE_BLOB
        assert revived.samples[1].keystroke_data is None

    def test_legacy_row_without_keystroke_data_key_defaults_to_none(self):
        """A sample dict serialized before this field existed has no
        "keystroke_data" key at all — not even null, since the key wasn't in
        the dict comprehension yet. Simulate that exact pre-migration shape
        by stripping the key after serializing with the *current* _serialize
        (which does emit it, null or not) and confirm _deserialize still
        loads the row, defaulting the field to None. This is the exact shape
        every pre-existing production row has today."""
        from original.store import _deserialize, _serialize

        state = StudentState(student_id="legacy", samples=[])
        state.add_sample(_baseline_sample(text="a"))

        legacy_payload = json.loads(_serialize(state))
        # Current _serialize always emits the key (null when unset, like
        # `genre`/`context_manifest`) — strip it to reproduce the shape a
        # pre-this-change row actually has, where the key is absent entirely.
        del legacy_payload["samples"][0]["keystroke_data"]
        legacy_str = json.dumps(legacy_payload)

        revived = _deserialize(legacy_str)
        assert revived.samples[0].keystroke_data is None


# ══════════════════════════════════════════════════════════════════════════════
# 4/5. Postgres: PostgresRepository._state_to_doc / _doc_to_state
#
# Both are @staticmethod and operate purely on in-memory objects/dicts — no
# live Postgres connection required, so these run unconditionally (not gated
# behind DATABASE_URL / @pytest.mark.postgres like the actual-database
# contract tests in test_repository_contract.py).
# ══════════════════════════════════════════════════════════════════════════════


class TestPostgresSerialization:
    def test_round_trip_carries_keystroke_data(self):
        from original.repository import PostgresRepository

        state = StudentState(student_id="s", samples=[])
        state.add_sample(_baseline_sample(text="a", keystroke_data=_KEYSTROKE_BLOB))
        state.add_sample(_baseline_sample(text="b"))

        doc = PostgresRepository._state_to_doc(state)
        revived = PostgresRepository._doc_to_state(doc)
        assert revived.samples[0].keystroke_data == _KEYSTROKE_BLOB
        assert revived.samples[1].keystroke_data is None

    def test_legacy_doc_without_keystroke_data_key_defaults_to_none(self):
        """Mirrors the SQLite legacy test above: strip the key entirely to
        reproduce a doc written before this field existed."""
        from original.repository import PostgresRepository

        state = StudentState(student_id="legacy", samples=[])
        state.add_sample(_baseline_sample(text="a"))

        legacy_doc = PostgresRepository._state_to_doc(state)
        del legacy_doc["samples"][0]["keystroke_data"]

        revived = PostgresRepository._doc_to_state(legacy_doc)
        assert revived.samples[0].keystroke_data is None


# ══════════════════════════════════════════════════════════════════════════════
# 6. Ingestion endpoint threads keystroke_data onto the persisted sample
# ══════════════════════════════════════════════════════════════════════════════


@pytest.fixture
def client(store_reset):
    from fastapi.testclient import TestClient

    import run

    return TestClient(run.load_legacy_demo_app())


class TestIngestEndpointPersistsKeystrokeData:
    def test_proctored_baseline_with_keystroke_data_is_persisted(self, client):
        from original import store

        sid = "demo:t17-keystroke-regression"
        resp = client.post(
            f"/students/{sid}/baseline",
            json={
                "text": "This proctored sitting carries live Bbook keystroke telemetry "
                "so the Tier 17 readiness gate can eventually measure it. " * 3,
                "provenance": "proctored",
                "assignment": "midterm",
                "keystroke_data": _KEYSTROKE_BLOB,
            },
        )
        assert resp.status_code == 200, resp.text

        state = store.get(sid)
        assert state is not None and state.samples, "sample was not persisted"
        assert state.samples[-1].keystroke_data == _KEYSTROKE_BLOB
        assert state.samples[-1].provenance == "proctored"

    def test_baseline_without_keystroke_data_stores_none(self, client):
        """A normal (non-Bbook) upload must not synthesize a blob."""
        from original import store

        sid = "demo:t17-keystroke-absent"
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
# 7. scripts/tier17_report.py counts real samples persisted through the
#    normal store.put() path (not just the synthetic raw-SQL rows in
#    tests/test_tier17_report.py, which intentionally bypass original.store).
# ══════════════════════════════════════════════════════════════════════════════


def _load_tier17_report():
    spec = importlib.util.spec_from_file_location(
        "tier17_report_e2e", _ROOT / "scripts" / "tier17_report.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestTier17ReportSeesStorePersistedData:
    def test_store_persisted_keystroke_data_is_counted(self, tmp_path, monkeypatch):
        """Seed a real SQLite DB via original.store.put() (the same code path
        the API uses), then point tier17_report at that file directly. Before
        this change this always reported 0, since store._serialize() dropped
        the blob; now it must see every proctored sample that carries one.

        Reimports original.store against a scratch ORIGINAL_DB so this test
        never touches the real store module's cached _DB_PATH (or any real
        profiles.db). Uses ``import original.store as X`` — NOT
        ``from original import store as X`` — for the reimport: the `from`
        form resolves via getattr() on the already-imported `original`
        package and silently returns the STALE cached module even after
        `del sys.modules["original.store"]`, so it never sees the new
        ORIGINAL_DB.

        ``import a.b`` has its own hazard on the way back out: as a side
        effect it sets the ``b`` attribute on the already-imported ``a``
        package object to point at the fresh module. Restoring
        ``sys.modules`` alone leaves that attribute pointing at the (now
        torn-down) fresh module — every later ``from original import store``
        elsewhere in the suite (e.g. tests/conftest.py's ``store_reset``
        fixture, used by dozens of other tests) would silently resolve to
        it instead of the real module, while code that already bound
        ``original.store`` before this test ran (api.py, routers/_shared.py)
        keeps the real one — the exact silent-divergence hazard
        tests/context/test_drift.py's persistence test docstring warns
        about. Restore the package attribute explicitly, not just
        sys.modules, so nothing leaks past this test."""
        import sys

        monkeypatch.setenv("ORIGINAL_DB", str(tmp_path / "seeded_profiles.db"))
        db_path = tmp_path / "seeded_profiles.db"

        original_pkg = sys.modules["original"]
        _saved_modules = {
            mod: sys.modules[mod] for mod in list(sys.modules) if mod.startswith("original.store")
        }
        _saved_attr = original_pkg.__dict__.get("store")
        try:
            for mod in _saved_modules:
                del sys.modules[mod]
            import original.store as fresh_store

            assert fresh_store._DB_PATH == db_path, (
                "reimport did not pick up the scratch ORIGINAL_DB — would "
                "silently write into the real store module's database"
            )

            for i in range(5):
                state = StudentState(student_id=f"stud_{i}", samples=[])
                for j in range(4):
                    state.add_sample(
                        _baseline_sample(
                            text=f"sample {i}-{j}",
                            keystroke_data=_KEYSTROKE_BLOB,
                        )
                    )
                # One non-proctored, one keystroke-less sample per student —
                # must NOT be counted by the report.
                state.add_sample(_baseline_sample(text="unverified", provenance="unverified"))
                state.add_sample(_baseline_sample(text="no telemetry", keystroke_data=None))
                fresh_store.put(state)
        finally:
            sys.modules.update(_saved_modules)
            if _saved_attr is not None:
                original_pkg.store = _saved_attr

        assert db_path.exists(), "store.put() did not write the scratch DB file"

        tier17_report = _load_tier17_report()
        conn = tier17_report._connect_readonly(db_path)
        try:
            samples = tier17_report._fetch_keystroke_samples(conn)
        finally:
            conn.close()

        assert (
            len(samples) == 20
        ), f"expected 5 students x 4 proctored+keystroke samples = 20, got {len(samples)}"
        report = tier17_report.build_report(samples)
        assert report["totals"]["proctored_samples_with_keystroke_data"] == 20
        assert report["totals"]["distinct_students"] == 5
