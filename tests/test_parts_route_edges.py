"""The past-paper parts routes (``original/routers/students_parts.py``) at
their edges: an unknown student, going back to the rules with the switches
off when there was no choice, a paper uploaded with keystroke data, an audit
log that fails, and a choice the checks refuse. The main behaviour is in
tests/test_part_overrides.py."""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from original import store
from original.constants import AUTH_WEIGHTS, FEATURE_DIM
from original.quantum.state import BaselineSample, StudentState
from original.routers import students_parts

ROOT = Path(__file__).resolve().parents[1]
MLA = (ROOT / "tests" / "fixtures" / "paper_matter" / "mla_docx.txt").read_text(encoding="utf-8")
FIRST = MLA.index("Wendell Berry writes")
SECOND = MLA.index("Critics have often")


@pytest.fixture(autouse=True)
def _quiet(monkeypatch):
    from original.features import tier10

    monkeypatch.setattr(tier10, "_st_model", None)
    monkeypatch.setattr(tier10, "_st_failed", True)
    monkeypatch.setenv("RULE_D_OBSERVATION", "off")
    for name in ("MATTER_SPLITTER_ENABLED", "PAPER_PROFILE_ENABLED", "UPLOAD_ALSO_MEASURE"):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def switches(monkeypatch):
    monkeypatch.setenv("MATTER_SPLITTER_ENABLED", "1")
    monkeypatch.setenv("PAPER_PROFILE_ENABLED", "1")


def _seed(sid: str, keystroke_data: dict | None = None) -> None:
    flat = np.full(FEATURE_DIM, 0.5)
    store.put(
        StudentState(
            sid,
            samples=[
                BaselineSample(
                    text=MLA,
                    vector=flat.copy(),
                    provenance="proctored",
                    auth_weight=AUTH_WEIGHTS["proctored"],
                    assignment="Paper 1",
                    keystroke_data=keystroke_data,
                    extra_vectors={"matter": flat.copy()},
                )
            ],
        )
    )


def test_an_unknown_student_is_404(live_client, store_reset, switches):
    for method in ("get", "delete"):
        r = getattr(live_client, method)("/students/parts_nobody/samples/0/parts")
        assert r.status_code == 404 and "not found" in r.json()["detail"]


def test_back_to_the_rules_with_no_choice_and_a_switch_off_writes_nothing(
    live_client, store_reset, monkeypatch
):
    sid = "parts_edge_a"
    _seed(sid)
    writes = []
    monkeypatch.setattr(students_parts, "_persist_or_503", writes.append)
    r = live_client.delete(f"/students/{sid}/samples/0/parts")
    assert r.status_code == 200 and r.json() == {"enabled": False, "index": 0, "parts": []}
    assert writes == [] and store.get(sid).samples[0].part_overrides is None


def test_a_choice_is_measured_with_the_papers_own_keystroke_data(
    live_client, store_reset, switches, monkeypatch
):
    """A paper uploaded with keystroke data is measured with it again, as at
    upload, so the choice's measurement differs from the rules' only by the
    parts chosen."""
    sid = "parts_edge_b"
    keys = {"keystrokes": 10, "wordCount": 400}
    _seed(sid, keystroke_data=keys)
    seen = []
    real = students_parts.feature_vector

    def recording(text, **kw):
        seen.append(kw)
        return real(text, **kw)

    monkeypatch.setattr(students_parts, "feature_vector", recording)
    r = live_client.put(
        f"/students/{sid}/samples/0/parts", json={"exclude_ranges": [[FIRST, SECOND]]}
    )
    assert r.status_code == 200, r.text[:300]
    assert seen == [{"keystroke_data": keys}]
    assert set(store.get(sid).samples[0].part_overrides["choice_vectors"]) == {"matter"}


def test_a_failed_audit_log_does_not_lose_the_choice(
    live_client, store_reset, switches, monkeypatch
):
    sid = "parts_edge_c"
    _seed(sid)
    repo = students_parts._repo()

    class FailingAudit:
        def __getattr__(self, name):
            return getattr(repo, name)

        def log_audit(self, **_):
            raise RuntimeError("audit store down")

    monkeypatch.setattr(students_parts, "_repo", FailingAudit)
    r = live_client.put(
        f"/students/{sid}/samples/0/parts", json={"exclude_ranges": [[FIRST, SECOND]]}
    )
    assert r.status_code == 200, r.text[:300]
    assert store.get(sid).samples[0].part_overrides["exclude_ranges"]


def test_a_choice_the_checks_refuse_is_422_and_stores_nothing(live_client, store_reset, switches):
    sid = "parts_edge_d"
    _seed(sid)
    url = f"/students/{sid}/samples/0/parts"
    for body, words in (
        ({"exclude_ranges": [[0, len(MLA)]]}, "more than 60%"),
        ({"include_ranges": [[FIRST, SECOND]]}, "not a part"),
        ({"exclude_ranges": [[SECOND, FIRST]]}, "not within the text"),
    ):
        r = live_client.put(url, json=body)
        assert r.status_code == 422 and words in r.json()["detail"], r.text[:300]
    assert store.get(sid).samples[0].part_overrides is None
