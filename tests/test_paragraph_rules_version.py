"""The paragraph rule's version on stored measurements with the paragraph bit
(``features/paragraphs.py`` ``RULES_VERSION``; ``features/rules_stamp.py``).

A measurement id with the paragraph bit ("para", "fs2+para") is stamped with
the paragraph version; one with the splitter bit too ("matter+para",
"fs2+matter+para") with both, so a bump of either makes it stale. Stamps
stored before the paragraph rule was versioned (an int on a splitter id) and
unstamped entries are still served as current. The default "v1" measurement
never reads any of this.
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
from original.features import matter, paragraphs
from original.features import part_overrides as po
from original.features import rules_stamp as rs
from original.quantum.state import BaselineSample, StudentState

ROOT = Path(__file__).resolve().parents[1]
MLA = (ROOT / "tests" / "fixtures" / "paper_matter" / "mla_docx.txt").read_text(encoding="utf-8")


def _bf():
    spec = importlib.util.spec_from_file_location(
        "backfill_measurements_prv", ROOT / "scripts" / "backfill_measurements.py"
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["backfill_measurements_prv"] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    for name in (
        "FEATURE_SET",
        "MATTER_SPLITTER_ENABLED",
        "PARAGRAPH_BREAKS_ENABLED",
        "PAPER_PROFILE_ENABLED",
        "UPLOAD_ALSO_MEASURE",
    ):
        monkeypatch.delenv(name, raising=False)


def _vec(x: float) -> np.ndarray:
    return np.full(FEATURE_DIM, x)


def _sample(text="paper", extra=None, rules=None):
    return BaselineSample(
        text=text,
        vector=_vec(0.5),
        provenance="verified",
        auth_weight=1.0,
        extra_vectors=extra,
        extra_vector_rules=rules,
    )


# ── the stamp ────────────────────────────────────────────────────────────────


def test_stamp_format_per_measurement_id():
    assert paragraphs.RULES_VERSION == paragraphs.UNSTAMPED_RULES_VERSION == 1
    assert rs.stamp("v1") is None and rs.stamp("fs2") is None
    assert rs.stamp("matter") == rs.stamp("fs2+matter") == 1  # as stored before
    assert rs.stamp("para") == rs.stamp("fs2+para") == "p1"
    assert rs.stamp("matter+para") == rs.stamp("fs2+matter+para") == "m1.p1"
    assert m.rules_stamps({k: _vec(0) for k in ff.MEASUREMENTS if k != "v1"}) == {
        "matter": 1,
        "fs2+matter": 1,
        "para": "p1",
        "fs2+para": "p1",
        "matter+para": "m1.p1",
        "fs2+matter+para": "m1.p1",
    }


@pytest.mark.parametrize("raw", ["1", "p0", "m1", "m1.p", "p1.m1", "x", 1.0, True, [1]])
def test_what_is_not_a_stamp(raw):
    assert rs.parse(raw) is None
    assert not rs.current("para", raw) and not rs.current("matter+para", raw)


def test_a_para_entry_goes_stale_on_a_paragraph_bump(monkeypatch):
    monkeypatch.setenv("PARAGRAPH_BREAKS_ENABLED", "1")
    stamped = _sample(
        extra={"para": _vec(0.1), "fs2+para": _vec(0.2)},
        rules=m.rules_stamps({"para": 0, "fs2+para": 0}),
    )
    unstamped = _sample(extra={"para": _vec(0.3)})
    assert np.allclose(m.vector_for(stamped, "para"), 0.1)
    assert np.allclose(m.vector_for(stamped, "fs2+para"), 0.2)
    assert np.allclose(m.vector_for(unstamped, "para"), 0.3)  # unstamped: current
    monkeypatch.setattr(matter, "RULES_VERSION", 2)  # the splitter is not used
    assert np.allclose(m.vector_for(stamped, "para"), 0.1)
    monkeypatch.setattr(matter, "RULES_VERSION", 1)
    monkeypatch.setattr(paragraphs, "RULES_VERSION", 2)
    assert m.vector_for(stamped, "para") is None and m.vector_for(stamped, "fs2+para") is None
    assert m.vector_for(unstamped, "para") is None
    assert m.plan_for(StudentState("t:a", samples=[stamped])).used == "v1"
    fresh = _sample(extra={"para": _vec(0.4)}, rules={"para": "p2"})
    assert np.allclose(m.vector_for(fresh, "para"), 0.4)


@pytest.mark.parametrize("bumped", [matter, paragraphs])
def test_a_matter_para_entry_goes_stale_on_either_bump(monkeypatch, bumped):
    for rules in ({"matter+para": "m1.p1"}, {"matter+para": 1}, None):
        paper = _sample(extra={"matter+para": _vec(0.1)}, rules=rules)
        assert np.allclose(m.vector_for(paper, "matter+para"), 0.1)
        monkeypatch.setattr(bumped, "RULES_VERSION", 2)
        assert m.vector_for(paper, "matter+para") is None, rules
        monkeypatch.setattr(bumped, "RULES_VERSION", 1)
    both = _sample(extra={"matter+para": _vec(0.2)}, rules={"matter+para": "m2.p1"})
    assert m.vector_for(both, "matter+para") is None
    monkeypatch.setattr(matter, "RULES_VERSION", 2)
    assert np.allclose(m.vector_for(both, "matter+para"), 0.2)


def test_existing_matter_stamps_and_unstamped_entries_are_current():
    paper = _sample(
        extra={"matter": _vec(0.1), "fs2+matter": _vec(0.2), "matter+para": _vec(0.3)},
        rules={"matter": 1, "fs2+matter": 1},
    )
    assert np.allclose(m.vector_for(paper, "matter"), 0.1)
    assert np.allclose(m.vector_for(paper, "fs2+matter"), 0.2)
    assert np.allclose(m.vector_for(paper, "matter+para"), 0.3)


def test_choice_vectors_with_the_paragraph_bit_are_stamped_and_checked(monkeypatch):
    choice = po.validate(
        MLA, [[MLA.index("Wendell Berry writes"), MLA.index("Critics have")]], None
    )
    doc = po.to_stored(choice, MLA, {"matter+para": _vec(0.7), "matter": _vec(0.6)})
    assert doc["choice_rules"] == {"matter": 1, "matter+para": "m1.p1"}
    assert po.with_choice_rules({}, "fs2+matter+para")["choice_rules"] == {
        "fs2+matter+para": "m1.p1"
    }
    paper = BaselineSample(
        text=MLA, vector=_vec(0.5), provenance="verified", auth_weight=1.0, part_overrides=doc
    )
    assert np.allclose(po.choice_vector(paper, "matter+para"), 0.7)
    monkeypatch.setattr(paragraphs, "RULES_VERSION", 2)
    assert po.choice_vector(paper, "matter+para") is None
    assert np.allclose(po.choice_vector(paper, "matter"), 0.6)  # no paragraph bit


def test_string_stamps_round_trip_and_bad_ones_are_dropped():
    from original.postgres_repository import PostgresRepository

    rules = {"matter": 1, "para": "p1", "matter+para": "m1.p1"}
    state = StudentState(
        "t:a", samples=[_sample(extra=dict.fromkeys(rules, _vec(0.1)), rules=rules)]
    )
    for back in (
        store._deserialize(store._serialize(state)),
        PostgresRepository._doc_to_state(PostgresRepository._state_to_doc(state)),
    ):
        assert back.samples[0].extra_vector_rules == rules
    doc = json.loads(store._serialize(state))
    doc["samples"][0]["extra_vector_rules"] = {"para": "p1", "matter+para": "1"}
    assert store._deserialize(json.dumps(doc)).samples[0].extra_vector_rules == {"para": "p1"}


# ── the backfill ─────────────────────────────────────────────────────────────


class Extract:
    def __init__(self, value):
        self.calls: list[str] = []
        self.value = value

    def __call__(self, text):
        self.calls.append(ff.current_measurement())
        return _vec(self.value)


def test_the_backfill_refills_a_stale_para_entry(store_reset, monkeypatch):
    from original.repository import get_repository, reset_repository

    reset_repository()
    repo = get_repository()
    repo.put(
        StudentState(
            "t:a",
            samples=[
                _sample(extra={"para": _vec(0.1)}),  # unstamped
                _sample("two", extra={"para": _vec(0.2)}, rules={"para": "p1"}),
            ],
        )
    )
    bf = _bf()
    first = bf.backfill(repo, "para", apply=True, extract=Extract(0.3))
    assert (first.measured, first.stamped, first.stale) == (0, 1, 0)
    assert "stamped with paragraph rules v1" in "\n".join(first.lines())
    assert [s.extra_vector_rules for s in repo.get("t:a").samples] == [{"para": "p1"}] * 2

    monkeypatch.setattr(paragraphs, "RULES_VERSION", 2)
    monkeypatch.setenv("PARAGRAPH_BREAKS_ENABLED", "1")
    assert m.plan_for(repo.get("t:a")).used == "v1"
    ex = Extract(0.9)
    report = bf.backfill(repo, "para", apply=True, extract=ex)
    assert ex.calls == ["para", "para"] and (report.stale, report.measured) == (2, 2)
    assert "made under older paragraph rules (measured again): 2" in "\n".join(report.lines())
    samples = repo.get("t:a").samples
    assert all(np.allclose(s.extra_vectors["para"], 0.9) for s in samples)
    assert all(s.extra_vector_rules == {"para": "p2"} for s in samples)
    assert m.plan_for(repo.get("t:a")).used == "para"
    reset_repository()


def test_the_backfill_refills_matter_para_after_either_bump(store_reset, monkeypatch):
    from original.repository import get_repository, reset_repository

    reset_repository()
    repo = get_repository()
    repo.put(
        StudentState(
            "t:a", samples=[_sample(extra={"matter+para": _vec(0.1)}, rules={"matter+para": 1})]
        )
    )
    bf = _bf()
    for bumped, stamp in ((paragraphs, "m1.p2"), (matter, "m2.p2")):
        monkeypatch.setattr(bumped, "RULES_VERSION", 2)
        report = bf.backfill(repo, "matter+para", apply=True, extract=Extract(0.8))
        assert (report.stale, report.measured) == (1, 1)
        assert repo.get("t:a").samples[0].extra_vector_rules == {"matter+para": stamp}
    reset_repository()


# ── switches off: nothing moves ──────────────────────────────────────────────


def test_switches_off_nothing_reads_the_paragraph_stamp(monkeypatch):
    paper = _sample(extra={"para": _vec(0.1)}, rules={"para": "p9"})
    plain = _sample()
    assert m.plan_for(StudentState("t:a", samples=[paper])).stamp() is None
    assert np.array_equal(m.vector_for(paper, "v1"), m.vector_for(plain, "v1"))
    assert m.rules_stamps({"fs2": _vec(0)}) is None and m.rules_stamps(None) is None
    no_rules = StudentState("t:a", samples=[_sample(extra={"fs2": _vec(0.1)})])
    assert "extra_vector_rules" not in json.loads(store._serialize(no_rules))["samples"][0]
