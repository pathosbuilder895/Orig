"""Versioned measurements (ADR-014; original/measurement.py).

Mixed-version fallback, the version stamp on score responses and evidence,
storage of the extra measurement (SQLite and the Postgres document shape), and
that with every switch off nothing changes.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest

from original import measurement as m
from original import store
from original.constants import FEATURE_DIM
from original.features import feature_flags as ff
from original.quantum.state import BaselineSample, StudentState

FIXTURES = Path(__file__).parent / "fixtures" / "paper_matter"
PAST = [
    (FIXTURES / f"{n}.txt").read_text(encoding="utf-8") for n in ("mla_docx", "apa", "chicago_pdf")
]
NEW = (FIXTURES / "mla_variants.txt").read_text(encoding="utf-8")


def _sample(seed: int, extra: dict | None = None) -> BaselineSample:
    v = np.random.RandomState(seed).uniform(0, 1, FEATURE_DIM)
    return BaselineSample(
        text=f"paper {seed}", vector=v, provenance="verified", auth_weight=1.0, extra_vectors=extra
    )


def _vec(x: float) -> np.ndarray:
    return np.full(FEATURE_DIM, x)


@pytest.fixture
def clean_flags(monkeypatch):
    for name in ("FEATURE_SET", "MATTER_SPLITTER_ENABLED", "UPLOAD_ALSO_MEASURE"):
        monkeypatch.delenv(name, raising=False)
    return monkeypatch


# ── flags ────────────────────────────────────────────────────────────────────


def test_measurement_ids_follow_the_switches(clean_flags):
    assert ff.requested_measurement() == "v1" == ff.current_measurement()
    clean_flags.setenv("FEATURE_SET", "2")
    assert ff.requested_measurement() == "fs2"
    clean_flags.setenv("MATTER_SPLITTER_ENABLED", "1")
    assert ff.requested_measurement() == "fs2+matter"
    with ff.measuring("v1"):
        assert ff.cache_key() == (1, False) and ff.current_measurement() == "v1"
        assert ff.requested_measurement() == "fs2+matter"  # the environment's ask
    assert ff.current_measurement() == "fs2+matter"
    clean_flags.setenv("FEATURE_SET", "1")
    assert ff.requested_measurement() == "matter"


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, None),
        ("", None),
        ("v1", None),
        ("nonsense", None),
        ("fs2", "fs2"),
        (" fs2+matter ", "fs2+matter"),
    ],
)
def test_upload_also_measure_parsing(clean_flags, value, expected):
    if value is not None:
        clean_flags.setenv("UPLOAD_ALSO_MEASURE", value)
    assert ff.upload_also_measure() == expected


def test_measuring_does_not_leak_into_another_context():
    import contextvars

    def inner():
        ff.set_measurement("fs2+matter")
        return ff.cache_key()

    assert contextvars.copy_context().run(inner) == (2, True)
    assert ff._OVERRIDE.get() is None


# ── plan: like with like ─────────────────────────────────────────────────────


def test_default_plan_is_a_no_op(clean_flags):
    state = StudentState("t:a", samples=[_sample(1), _sample(2)])
    plan = m.plan_for(state)
    assert plan.state is state and plan.used == "v1" and plan.stamp() is None


def test_every_paper_measured_uses_the_new_measurement(clean_flags):
    clean_flags.setenv("FEATURE_SET", "2")
    state = StudentState(
        "t:a", samples=[_sample(1, {"fs2": _vec(0.1)}), _sample(2, {"fs2": _vec(0.2)})]
    )
    plan = m.plan_for(state)
    assert plan.used == "fs2" and plan.state is not state
    assert [s.vector[0] for s in plan.state.samples] == [0.1, 0.2]
    assert state.samples[0].vector[0] != 0.1  # the stored state is untouched
    assert plan.stamp() == {
        "requested": "fs2",
        "used": "fs2",
        "past_papers": 2,
        "past_papers_measured": 2,
    }
    with pytest.raises(ValueError, match="refusing to store"):
        store._serialize(plan.state)


def test_mixed_versions_fall_back_to_the_default_for_both_sides(clean_flags):
    clean_flags.setenv("FEATURE_SET", "2")
    clean_flags.setenv("MATTER_SPLITTER_ENABLED", "1")
    state = StudentState(
        "t:a",
        samples=[_sample(1, {"fs2+matter": _vec(0.1)}), _sample(2), _sample(3, {"fs2": _vec(0.3)})],
    )
    plan = m.plan_for(state)
    assert plan.used == "v1" and plan.state is state
    stamp = plan.stamp()
    assert stamp["requested"] == "fs2+matter" and stamp["past_papers_measured"] == 1
    assert stamp["fallback"].startswith("2 of 3 past papers are not yet measured as fs2+matter")


def test_no_papers_falls_back(clean_flags):
    clean_flags.setenv("FEATURE_SET", "2")
    assert m.plan_for(StudentState("t:a")).used == "v1"


def test_peer_states_are_measured_alike():
    full = StudentState("t:b", samples=[_sample(1, {"fs2": _vec(0.4)})])
    part = StudentState("t:c", samples=[_sample(2, {"fs2": _vec(0.5)}), _sample(3)])
    empty = StudentState("t:d")
    assert m.states_measured_as([full, part, empty], "v1") == [full, part, empty]
    (only,) = m.states_measured_as([full, part, empty], "fs2")
    assert only.student_id == "t:b" and only.samples[0].vector[0] == 0.4


def test_measurement_of_reads_the_stamp():
    from original.schemas import MeasurementOut

    assert m.measurement_of({}) == "v1"
    assert m.measurement_of({"measurement": {"used": "fs2"}}) == "fs2"
    assert m.measurement_of({"measurement": {"used": "bogus"}}) == "v1"
    obj = type(
        "R",
        (),
        {
            "measurement": MeasurementOut(
                requested="fs2", used="fs2", past_papers=1, past_papers_measured=1
            )
        },
    )()
    assert m.measurement_of(obj) == "fs2"
    assert m.vector_for(_sample(1), "fs2") is None
    assert m.vector_for(_sample(1), "v1") is not None


# ── storage ──────────────────────────────────────────────────────────────────


def test_document_without_extra_measurements_is_unchanged():
    doc = json.loads(store._serialize(StudentState("t:a", samples=[_sample(1)])))
    assert "extra_vectors" not in doc["samples"][0]
    from original.postgres_repository import PostgresRepository

    pg = PostgresRepository._state_to_doc(StudentState("t:a", samples=[_sample(1)]))
    assert "extra_vectors" not in pg["samples"][0]


def test_extra_measurements_round_trip_on_both_backends(caplog):
    from original.postgres_repository import PostgresRepository

    state = StudentState("t:a", samples=[_sample(1, {"fs2": _vec(0.25)})])
    back = store._deserialize(store._serialize(state))
    assert np.array_equal(back.samples[0].extra_vectors["fs2"], _vec(0.25))
    pg_back = PostgresRepository._doc_to_state(PostgresRepository._state_to_doc(state))
    assert np.array_equal(pg_back.samples[0].extra_vectors["fs2"], _vec(0.25))
    doc = json.loads(store._serialize(state))
    doc["samples"][0]["extra_vectors"]["matter"] = [0.5, 0.5]
    with caplog.at_level("WARNING"):
        again = store._deserialize(json.dumps(doc))
    assert set(again.samples[0].extra_vectors) == {"fs2"}
    doc["samples"][0]["extra_vectors"] = {"matter": [0.5]}
    assert store._deserialize(json.dumps(doc)).samples[0].extra_vectors is None


def test_extra_vectors_at_upload(clean_flags):
    calls = []

    def extract(text, keystroke_data=None):
        calls.append((ff.current_measurement(), keystroke_data))
        return _vec(0.7)

    assert m.extra_vectors_at_upload("x", extract=extract) is None and calls == []
    clean_flags.setenv("UPLOAD_ALSO_MEASURE", "fs2+matter")
    extra = m.extra_vectors_at_upload("x", {"k": 1}, extract=extract)
    assert set(extra) == {"fs2+matter"} and calls == [("fs2+matter", {"k": 1})]
    assert m.extra_vectors_at_upload("x", extract=lambda t: 1 / 0) is None
    real = m.extra_vectors_at_upload(PAST[0])
    assert real["fs2+matter"].shape == (FEATURE_DIM,)


# ── through the API ──────────────────────────────────────────────────────────


def _score(client, sid, sub):
    r = client.post(f"/students/{sid}/score", json={"text": NEW, "submission_id": sub})
    assert r.status_code == 200, r.text[:300]
    return r.json()


def _add(client, sid, text, name):
    r = client.post(
        f"/students/{sid}/baseline",
        json={"text": text, "provenance": "verified", "assignment": name},
    )
    assert r.status_code == 200, r.text[:300]


def test_api_versioned_scoring(live_client, store_reset, clean_flags):
    clean_flags.setenv("EVIDENCE_PASSAGES_ENABLED", "1")
    clean_flags.setenv("PRELIMINARY_SCORE_ENABLED", "0")
    sid = "demo:versioned"
    # Past papers added with the switches ON: the stored vector must still be v1.
    clean_flags.setenv("FEATURE_SET", "2")
    clean_flags.setenv("MATTER_SPLITTER_ENABLED", "1")
    clean_flags.setenv("UPLOAD_ALSO_MEASURE", "fs2+matter")
    for i, text in enumerate(PAST):
        _add(live_client, sid, text, f"p{i}")
    clean_flags.delenv("FEATURE_SET")
    clean_flags.delenv("MATTER_SPLITTER_ENABLED")
    clean_flags.delenv("UPLOAD_ALSO_MEASURE")

    stored = store.get(sid)
    from original.features.pipeline import feature_vector

    for s, text in zip(stored.samples, PAST, strict=True):
        assert np.array_equal(s.vector, feature_vector(text))  # v1, untouched by the env
        assert set(s.extra_vectors) == {"fs2+matter"}

    default = _score(live_client, sid, "s1")
    assert "measurement" not in default and "measurement" not in default["evidence"]

    clean_flags.setenv("FEATURE_SET", "2")
    clean_flags.setenv("MATTER_SPLITTER_ENABLED", "1")
    new = _score(live_client, sid, "s2")
    assert new["measurement"] == {
        "requested": "fs2+matter",
        "used": "fs2+matter",
        "past_papers": 3,
        "past_papers_measured": 3,
    }
    assert new["evidence"]["measurement"] == new["measurement"]
    assert new["authorship"]["deviation_score"] != default["authorship"]["deviation_score"]

    # A fourth past paper added the default way: mixed, so back to v1 on both sides.
    clean_flags.delenv("FEATURE_SET")
    clean_flags.delenv("MATTER_SPLITTER_ENABLED")
    _add(live_client, sid, PAST[0] + "\n\nOne more closing sentence for a different paper.", "p3")
    default4 = _score(live_client, sid, "s3")
    clean_flags.setenv("FEATURE_SET", "2")
    clean_flags.setenv("MATTER_SPLITTER_ENABLED", "1")
    mixed = _score(live_client, sid, "s4")
    assert (
        mixed["measurement"]["used"] == "v1" and mixed["measurement"]["past_papers_measured"] == 3
    )
    assert "fallback" in mixed["measurement"]
    assert mixed["authorship"] == default4["authorship"]
    blend = live_client.post(f"/students/{sid}/score/blend", json={"text": NEW * 3}).json()
    assert blend["measurement"]["used"] == "v1"
    clean_flags.delenv("FEATURE_SET")
    clean_flags.delenv("MATTER_SPLITTER_ENABLED")
    assert (
        "measurement"
        not in live_client.post(f"/students/{sid}/score/blend", json={"text": NEW * 3}).json()
    )


def test_evidence_page_states_the_measurement():
    page = (Path(__file__).parents[1] / "demo" / "original" / "evidence.html").read_text(
        encoding="utf-8"
    )
    assert "renderMeasurement(ev.measurement)" in page and 'id="measured-as"' in page
