"""The splitter's rules version on stored splitter measurements
(``features/matter.py`` ``RULES_VERSION``; ``original/measurement.py``).

A splitter measurement (``extra_vectors["matter"]``,
``extra_vectors["fs2+matter"]`` and a teacher's ``choice_vectors``) is
stored with the rules version it was made under. One made under other rules
is served exactly as if it were missing, and the backfill measures it again.
One stored before stamps existed counts as version 1 (the version in force
when stamps were added), so the deploy that adds stamps changes nothing; the
backfill stamps it without measuring it again. The default "v1" measurement
never reads any of this, so with the switches off nothing changes at all.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pytest

from original import measurement as m
from original import store
from original.constants import FEATURE_DIM
from original.features import feature_flags as ff
from original.features import matter
from original.features import part_overrides as po
from original.quantum.state import BaselineSample, StudentState

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "paper_matter"
MLA = (FIXTURES / "mla_docx.txt").read_text(encoding="utf-8")
FIRST = MLA.index("Wendell Berry writes")
SECOND = MLA.index("Critics have often")
PAST = [(FIXTURES / f"{n}.txt").read_text(encoding="utf-8") for n in ("mla_docx", "apa")]


def _bf():
    spec = importlib.util.spec_from_file_location(
        "backfill_measurements_rv", ROOT / "scripts" / "backfill_measurements.py"
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["backfill_measurements_rv"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    for name in (
        "FEATURE_SET",
        "MATTER_SPLITTER_ENABLED",
        "PAPER_PROFILE_ENABLED",
        "UPLOAD_ALSO_MEASURE",
    ):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def bump(monkeypatch):
    """A later rules change: RULES_VERSION goes to 2."""
    monkeypatch.setattr(matter, "RULES_VERSION", 2)


def _vec(x: float) -> np.ndarray:
    return np.full(FEATURE_DIM, x)


def _sample(text="paper", extra=None, rules=None, choice=None, choice_vectors=None):
    return BaselineSample(
        text=text,
        vector=_vec(0.5),
        provenance="verified",
        auth_weight=1.0,
        extra_vectors=extra,
        extra_vector_rules=rules,
        part_overrides=po.to_stored(choice, text, choice_vectors),
    )


def _cut_first() -> po.PartOverride:
    return po.validate(MLA, [[FIRST, SECOND]], None)


# ── the rule ─────────────────────────────────────────────────────────────────


def test_unstamped_is_version_one_and_a_bump_makes_it_stale(monkeypatch):
    assert matter.RULES_VERSION == matter.UNSTAMPED_RULES_VERSION == 1
    assert matter.rules_current(None) and matter.rules_current(1)
    assert not matter.rules_current(2)  # a newer stamp (rolled-back deploy) is not ours
    monkeypatch.setattr(matter, "RULES_VERSION", 2)
    assert not matter.rules_current(None) and not matter.rules_current(1)
    assert matter.rules_current(2)


def test_an_unstamped_entry_is_served_as_today():
    """The deploy that adds stamps changes nothing for entries stored before."""
    paper = _sample(extra={"matter": _vec(0.1), "fs2+matter": _vec(0.2)})
    assert np.array_equal(m.vector_for(paper, "matter"), _vec(0.1))
    assert np.array_equal(m.vector_for(paper, "fs2+matter"), _vec(0.2))


def test_a_stale_entry_is_served_exactly_as_a_missing_one(bump, monkeypatch):
    monkeypatch.setenv("MATTER_SPLITTER_ENABLED", "1")
    stale = _sample(extra={"matter": _vec(0.1), "fs2": _vec(0.3)}, rules={"matter": 1})
    fresh = _sample(extra={"matter": _vec(0.2)}, rules={"matter": 2})
    unstamped = _sample(extra={"matter": _vec(0.4)})
    assert m.vector_for(stale, "matter") is None and m.vector_for(unstamped, "matter") is None
    assert np.array_equal(m.vector_for(fresh, "matter"), _vec(0.2))
    assert np.array_equal(m.vector_for(stale, "fs2"), _vec(0.3))  # not the splitter
    plan = m.plan_for(StudentState("t:a", samples=[stale, fresh]))
    missing = m.plan_for(StudentState("t:a", samples=[_sample(), fresh]))
    assert plan.used == "v1" == missing.used and plan.stamp() == missing.stamp()
    assert m.states_measured_as([StudentState("t:a", samples=[stale])], "matter") == []


def test_rules_stamps_cover_only_splitter_measurements():
    assert m.rules_stamps(None) is None and m.rules_stamps({"fs2": _vec(0.1)}) is None
    assert m.rules_stamps({"fs2": _vec(0), "matter": _vec(0), "fs2+matter": _vec(0)}) == {
        "matter": 1,
        "fs2+matter": 1,
    }


# ── storage ──────────────────────────────────────────────────────────────────


def test_stamps_round_trip_and_absent_stamps_store_as_before():
    from original.postgres_repository import PostgresRepository

    plain = StudentState("t:a", samples=[_sample(extra={"matter": _vec(0.1)})])
    assert "extra_vector_rules" not in json.loads(store._serialize(plain))["samples"][0]
    assert "extra_vector_rules" not in PostgresRepository._state_to_doc(plain)["samples"][0]
    assert store._deserialize(store._serialize(plain)).samples[0].extra_vector_rules is None

    stamped = StudentState(
        "t:a", samples=[_sample(extra={"matter": _vec(0.1)}, rules={"matter": 3})]
    )
    for back in (
        store._deserialize(store._serialize(stamped)),
        PostgresRepository._doc_to_state(PostgresRepository._state_to_doc(stamped)),
    ):
        assert back.samples[0].extra_vector_rules == {"matter": 3}


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("bogus", None), ({"matter": "1", "fs2+matter": True}, None), ({"matter": 2}, {"matter": 2})],
)
def test_malformed_stamps_read_as_unstamped(raw, expected):
    doc = json.loads(
        store._serialize(StudentState("t:a", samples=[_sample(extra={"matter": _vec(0.1)})]))
    )
    doc["samples"][0]["extra_vector_rules"] = raw
    assert store._deserialize(json.dumps(doc)).samples[0].extra_vector_rules == expected


# ── written with every splitter measurement ──────────────────────────────────


def test_an_upload_stamps_its_splitter_measurement(live_client, store_reset, monkeypatch):
    for also, rules in (("matter", {"matter": 1}), ("fs2", None)):
        monkeypatch.setenv("UPLOAD_ALSO_MEASURE", also)
        sid = f"demo:stamp_{also}"
        r = live_client.post(
            f"/students/{sid}/baseline",
            json={"text": PAST[0], "provenance": "verified", "assignment": "p0"},
        )
        assert r.status_code == 200, r.text[:300]
        sample = store.get(sid).samples[0]
        assert set(sample.extra_vectors) == {also} and sample.extra_vector_rules == rules
    monkeypatch.delenv("UPLOAD_ALSO_MEASURE")
    sid = "demo:stamp_none"
    live_client.post(
        f"/students/{sid}/baseline",
        json={"text": PAST[0], "provenance": "verified", "assignment": "p0"},
    )
    assert store.get(sid).samples[0].extra_vector_rules is None


def test_choice_vectors_are_stamped():
    doc = po.to_stored(_cut_first(), MLA, {"matter": _vec(0.7)})
    assert doc["choice_rules"] == {"matter": 1}
    assert "choice_rules" not in po.to_stored(_cut_first(), MLA)
    more = po.with_choice_vectors(doc, {"fs2+matter": _vec(0.8)})
    assert more["choice_rules"] == {"fs2+matter": 1, "matter": 1}
    assert po.with_choice_rules({"choice_rules": {"fs2+matter": 4}}, "matter")["choice_rules"] == {
        "fs2+matter": 4,
        "matter": 1,
    }


def test_a_stale_choice_vector_falls_back_to_the_rules_own(monkeypatch):
    monkeypatch.setenv("MATTER_SPLITTER_ENABLED", "1")
    monkeypatch.setenv("PAPER_PROFILE_ENABLED", "1")
    paper = _sample(
        MLA, extra={"matter": _vec(0.25)}, choice=_cut_first(), choice_vectors={"matter": _vec(0.7)}
    )
    assert np.allclose(m.vector_for(paper, "matter"), 0.7)
    # Rules re-measured under v2, the choice's measurement still v1: the
    # choice's is not served, the rules' own (current) one is.
    monkeypatch.setattr(matter, "RULES_VERSION", 2)
    paper.extra_vector_rules = {"matter": 2}
    assert po.choice_vector(paper, "matter") is None
    assert np.allclose(m.vector_for(paper, "matter"), 0.25)
    # An unstamped choice measurement (stored before stamps) is v1 too.
    del paper.part_overrides["choice_rules"]
    assert po.choice_vector(paper, "matter") is None


def test_a_put_counts_a_stale_paper_as_not_measured(live_client, store_reset, monkeypatch):
    """The PUT never creates a splitter measurement; a stale one is missing,
    so the choice is kept unmeasured, as for a paper never measured."""
    monkeypatch.setenv("MATTER_SPLITTER_ENABLED", "1")
    monkeypatch.setenv("PAPER_PROFILE_ENABLED", "1")
    sid = "parts_school_stale"
    store.put(
        StudentState(
            sid, samples=[_sample(MLA, extra={"matter": _vec(0.5)}), _sample("Another paper.")]
        )
    )
    url = f"/students/{sid}/samples/0/parts"
    monkeypatch.setattr(matter, "RULES_VERSION", 2)
    put = live_client.put(url, json={"exclude_ranges": [[FIRST, SECOND]]})
    assert put.status_code == 200, put.text[:300]
    assert put.json()["paper_measured"] is False
    assert "choice_vectors" not in store.get(sid).samples[0].part_overrides
    monkeypatch.setattr(matter, "RULES_VERSION", 1)
    put = live_client.put(url, json={"exclude_ranges": [[FIRST, SECOND]]})
    assert put.json()["paper_measured"] is True
    stored = store.get(sid).samples[0].part_overrides
    assert set(stored["choice_vectors"]) == {"matter"} and stored["choice_rules"] == {"matter": 1}


# ── the backfill ─────────────────────────────────────────────────────────────


class Extract:
    def __init__(self, value=0.25):
        self.calls: list[str] = []
        self.value = value

    def __call__(self, text):
        self.calls.append(ff.current_measurement())
        return _vec(0.75 if po.for_text(text) is not None else self.value)


def test_the_backfill_stamps_unstamped_entries_without_measuring(store_reset):
    from original.repository import get_repository, reset_repository

    reset_repository()
    repo = get_repository()
    repo.put(StudentState("t:a", samples=[_sample(extra={"matter": _vec(0.1)}), _sample("two")]))
    bf, ex = _bf(), Extract()
    dry = bf.backfill(repo, "matter", apply=False, extract=ex)
    assert (dry.already, dry.to_stamp, dry.to_measure, dry.stale) == (1, 1, 1, 0)
    assert "would stamp with splitter rules v1 (no new measurement): 1" in "\n".join(dry.lines())
    report = bf.backfill(repo, "matter", apply=True, extract=ex)
    assert ex.calls == ["matter"] and (report.stamped, report.measured) == (1, 1)
    a, b = repo.get("t:a").samples
    assert np.array_equal(a.extra_vectors["matter"], _vec(0.1))  # not measured again
    assert a.extra_vector_rules == b.extra_vector_rules == {"matter": 1}
    assert all(np.array_equal(s.vector, _vec(0.5)) for s in (a, b))
    ex.calls.clear()
    again = bf.backfill(repo, "matter", apply=True, extract=ex)
    assert ex.calls == [] and (again.stamped, again.written_students) == (0, 0)
    fs2 = bf.backfill(repo, "fs2", apply=True, extract=ex)  # not the splitter: never stamped
    assert fs2.stamped == 0 and repo.get("t:a").samples[0].extra_vector_rules == {"matter": 1}
    reset_repository()


def test_after_a_bump_the_backfill_refills_stale_entries(store_reset, monkeypatch):
    from original.repository import get_repository, reset_repository

    reset_repository()
    repo = get_repository()
    repo.put(
        StudentState(
            "t:a",
            samples=[
                _sample(extra={"fs2+matter": _vec(0.1)}, rules={"fs2+matter": 1}),
                _sample("two", extra={"fs2+matter": _vec(0.2)}),  # unstamped
            ],
        )
    )
    monkeypatch.setattr(matter, "RULES_VERSION", 2)
    monkeypatch.setenv("FEATURE_SET", "2")
    monkeypatch.setenv("MATTER_SPLITTER_ENABLED", "1")
    assert m.plan_for(repo.get("t:a")).used == "v1"  # stale: fall back
    bf, ex = _bf(), Extract(0.9)
    report = bf.backfill(repo, "fs2+matter", apply=True, extract=ex)
    assert (report.stale, report.measured, report.stamped) == (2, 2, 0)
    assert "made under older splitter rules (measured again): 2" in "\n".join(report.lines())
    samples = repo.get("t:a").samples
    assert all(np.allclose(s.extra_vectors["fs2+matter"], 0.9) for s in samples)
    assert all(s.extra_vector_rules == {"fs2+matter": 2} for s in samples)
    assert m.plan_for(repo.get("t:a")).used == "fs2+matter"
    reset_repository()


def test_the_backfill_refills_or_stamps_a_choice_measurement(store_reset, monkeypatch):
    from original.repository import get_repository, reset_repository

    reset_repository()
    repo = get_repository()
    paper = _sample(
        MLA, extra={"matter": _vec(0.25)}, choice=_cut_first(), choice_vectors={"matter": _vec(0.7)}
    )
    del paper.part_overrides["choice_rules"]  # stored before stamps existed
    repo.put(StudentState("t:a", samples=[paper]))
    bf, ex = _bf(), Extract()
    report = bf.backfill(repo, "matter", apply=True, extract=ex)
    assert ex.calls == [] and report.stamped == 1
    stored = repo.get("t:a").samples[0]
    assert stored.part_overrides["choice_rules"] == {"matter": 1}
    assert stored.extra_vector_rules == {"matter": 1}
    assert np.allclose(po.choice_vector(stored, "matter"), 0.7)

    monkeypatch.setattr(matter, "RULES_VERSION", 2)
    report = bf.backfill(repo, "matter", apply=True, extract=ex)
    assert ex.calls == ["matter", "matter"] and report.measured == 1
    stored = repo.get("t:a").samples[0]
    assert stored.part_overrides["choice_rules"] == {"matter": 2}
    assert stored.extra_vector_rules == {"matter": 2}
    assert np.allclose(po.choice_vector(stored, "matter"), 0.75)
    reset_repository()


def test_a_stamp_is_never_written_over_a_measurement_changed_meanwhile(store_reset):
    from original.repository import get_repository, reset_repository

    reset_repository()
    repo = get_repository()
    paper = _sample(
        MLA, extra={"matter": _vec(0.25)}, choice=_cut_first(), choice_vectors={"matter": _vec(0.7)}
    )
    del paper.part_overrides["choice_rules"]
    repo.put(StudentState("t:a", samples=[paper, _sample("two", extra={"matter": _vec(0.1)})]))
    bf = _bf()
    real_get = repo.get
    calls = {"n": 0}

    def get(sid):  # the second read (before writing) sees another writer's changes
        calls["n"] += 1
        state = real_get(sid)
        if calls["n"] == 2:
            state.samples[0].part_overrides = {**state.samples[0].part_overrides, "x": 1}
            state.samples[1].extra_vectors = {"matter": _vec(0.3)}
        return state

    repo.get = get
    report = bf.backfill(repo, "matter", apply=True, extract=Extract())
    assert report.changed == ["t:a#0", "t:a#1"] and report.stamped == 1
    repo.get = real_get
    first, second = repo.get("t:a").samples
    assert first.extra_vector_rules == {"matter": 1}  # its vector was as read
    assert "choice_rules" not in first.part_overrides  # its choice was not
    assert second.extra_vector_rules is None and np.allclose(second.extra_vectors["matter"], 0.3)
    reset_repository()


# ── switches off: nothing moves ──────────────────────────────────────────────


def test_switches_off_scores_are_identical_whatever_the_stamps(
    live_client, store_reset, monkeypatch
):
    """Stored v1 vectors are what every flags-off score reads: a student whose
    splitter measurements are stale scores byte-identically to one whose are
    current, and to one with none at all."""
    monkeypatch.setenv("UPLOAD_ALSO_MEASURE", "matter")
    for sid in ("demo:rv_a", "demo:rv_b"):
        for i, text in enumerate([*PAST, PAST[0] + "\n\nA closing sentence."]):
            r = live_client.post(
                f"/students/{sid}/baseline",
                json={"text": text, "provenance": "verified", "assignment": f"p{i}"},
            )
            assert r.status_code == 200, r.text[:300]
    monkeypatch.delenv("UPLOAD_ALSO_MEASURE")
    state = store.get("demo:rv_b")
    for s in state.samples:  # b's look like they were made under other rules
        s.extra_vector_rules = {"matter": 7}
    store.put(state)
    new = (FIXTURES / "mla_variants.txt").read_text(encoding="utf-8")

    def score(sid):
        body = live_client.post(
            f"/students/{sid}/score", json={"text": new, "submission_id": "same"}
        ).json()
        for key in ("student_id", "submission_id", "timestamp", "scored_at"):
            body.pop(key, None)
        return json.dumps(body, sort_keys=True).replace(sid, "S")

    assert score("demo:rv_a") == score("demo:rv_b")
    assert all(
        np.array_equal(a.vector, b.vector)
        for a, b in zip(store.get("demo:rv_a").samples, store.get("demo:rv_b").samples, strict=True)
    )
