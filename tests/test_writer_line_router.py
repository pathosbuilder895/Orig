"""Router-level INFO log line for WRITER_LINE: no student ids, one line per call."""

from __future__ import annotations

import logging
import uuid

import pytest
from fastapi.testclient import TestClient

import run

app = run.load_legacy_demo_app()
client = TestClient(app)

_BASELINES = [
    "The doctrine of justification has been central to Reformation theology since Luther.",
    "Calvin developed a covenantal framework that split forensic from transformative grace.",
    "Modern Pauline scholarship has revisited the theological vocabulary of the apostle.",
    "Theological method requires careful attention to both biblical text and historical context.",
]
_SUBMISSION = (
    "Coffee shops with reliable wifi multiply across suburban strip malls near the highway. "
    "Baristas pull delicate flat whites while soft jazz plays overhead every single afternoon."
)
_LOGGER = "original.routers.students_scoring"


def _run(monkeypatch, caplog, mode, n_baselines):
    if mode is None:
        monkeypatch.delenv("WRITER_LINE", raising=False)
    else:
        monkeypatch.setenv("WRITER_LINE", mode)
    sid = f"wl_log_{uuid.uuid4().hex[:8]}"
    for text in _BASELINES[:n_baselines]:
        r = client.post(f"/students/{sid}/baseline", json={"text": text, "provenance": "proctored"})
        assert r.status_code == 200, r.text
    caplog.clear()
    with caplog.at_level(logging.INFO, logger=_LOGGER):
        r = client.post(
            f"/students/{sid}/score", json={"text": _SUBMISSION, "submission_id": f"{sid}_s"}
        )
    assert r.status_code == 200, r.text
    lines = [m for m in caplog.messages if m.startswith("writer_line ")]
    for line in lines:
        assert sid not in line
    return lines


@pytest.mark.parametrize("mode", [None, "off"])
def test_off_logs_nothing(monkeypatch, caplog, mode):
    assert _run(monkeypatch, caplog, mode, 4) == []


def test_abstain_below_min_papers(monkeypatch, caplog):
    lines = _run(monkeypatch, caplog, "on", 2)
    assert len(lines) == 1
    assert "mode=on outcome=abstain would=None z=None" in lines[0]


@pytest.mark.parametrize(("mode", "outcome"), [("on", "applied"), ("shadow", "shadow")])
def test_applied_and_shadow(monkeypatch, caplog, mode, outcome):
    lines = _run(monkeypatch, caplog, mode, 4)
    assert len(lines) == 1
    assert f"mode={mode} outcome={outcome} would=" in lines[0]
    assert "would=None" not in lines[0]
