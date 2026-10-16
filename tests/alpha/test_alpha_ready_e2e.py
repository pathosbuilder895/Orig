"""End-to-end alpha rehearsal on a temporary database, covering the pieces the
older rehearsal does not: non-expiring invites, the /original/baseline.html
import route (POST /students/{id}/baseline/upload-batch, multipart), the
3-paper minimum, and real batch scoring (no stub scorer)."""

from __future__ import annotations

import csv
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

from original import principal
from original.repository import reset_repository
from scripts.alpha import batch_score_alpha as batch

ROOT = Path(__file__).resolve().parents[2]
PASSWORD = "alpha-local-Passw0rd!"

TOPICS = [
    "public libraries", "city buses", "school gardens", "night shifts", "local elections",
    "river cleanups", "farmers markets", "used bookshops",
]


def _paper(voice: int, topic: str, words: int = 360) -> str:
    """Deterministic, voice-consistent prose so a real scorer has something to read."""
    openers = [
        ["I think", "Honestly,", "To be fair,", "In my experience,"],
        ["It is evident that", "Consequently,", "Moreover,", "It follows that"],
    ][voice % 2]
    out, i = [], 0
    while len(" ".join(out).split()) < words:
        o = openers[i % len(openers)]
        out.append(
            f"{o} {topic} matter because people rely on them every day, and when "
            f"they work well nobody notices, but when they fail the whole street feels it. "
            f"Point {i} is that small budgets and patient staff do more than grand plans."
        )
        i += 1
    return " ".join(out)


@pytest.fixture(autouse=True)
def _fresh(store_reset, monkeypatch):
    monkeypatch.setenv("INVITE_NO_EXPIRY", "1")
    monkeypatch.delenv("MIN_BASELINE_SAMPLES", raising=False)
    reset_repository()
    principal.invalidate_tenant_cache()
    yield
    reset_repository()
    principal.invalidate_tenant_cache()


def _auth(t):
    return {"Authorization": f"Bearer {t}"}


def _tok(path):
    return parse_qs(urlparse(path).query)["invite"][0]


def _ok(r, code=200):
    assert r.status_code == code, r.text[:800]
    return r.json()


@pytest.mark.slow
def test_alpha_ready_flow_with_import_and_real_scoring(live_client, tmp_path):
    env = {**os.environ, "INVITE_NO_EXPIRY": "1"}
    inv = subprocess.run(
        [sys.executable, "scripts/invite_professor.py", "andrew+alpha@example.test", "--name", "Andrew",
         "--with-original", "--no-expiry", "--base-url", "https://local.example.test"],
        cwd=ROOT, env=env, text=True, capture_output=True, timeout=60,
    )
    assert inv.returncode == 0, inv.stderr
    assert "no expiry; reissue to revoke" in inv.stdout
    link = re.search(r"https://local\.example\.test/bluebook/\?invite=\S+", inv.stdout).group(0)
    prof = _ok(live_client.post("/auth/invite/redeem", json={"token": _tok(link), "password": PASSWORD, "accept_terms": True}))
    T = _auth(prof["token"])

    course = _ok(live_client.post("/bluebook/courses", json={"name": "Alpha", "code": "A1"}, headers=T), 201)
    cond = {"blockCopy": True, "blockAI": True, "blockWeb": False, "aiDetect": False, "spellChk": True}
    exams = [
        _ok(live_client.post("/bluebook/exams", json={"title": t, "status": "ACTIVE", "duration": 25,
            "questions": ["Argue for or against a public service you use."], "conditions": cond,
            "course_id": course["id"]}, headers=T), 201)
        for t in ("Exam A (own voice)", "Exam B (partner's style)")
    ]
    roster = _ok(live_client.post(f"/bluebook/courses/{course['id']}/students", json={
        "students": [{"email": f"v{i}@example.test", "name": f"V{i}"} for i in range(3)], "send_email": False,
    }, headers=T))["students"]
    assert all(datetime.fromisoformat(r["invite_expires_at"]).year == 9999 for r in roster)

    students = []
    for i, row in enumerate(roster):
        s = _ok(live_client.post("/auth/invite/redeem", json={"token": _tok(row["invite_path"]), "password": PASSWORD}))
        n_papers = 2 if i == 2 else 4  # V2 is the thin-baseline volunteer
        files = [("files", (f"paper{k}.txt", _paper(i, TOPICS[k]).encode(), "text/plain")) for k in range(n_papers)]
        up = _ok(live_client.post(f"/students/{row['student_id']}/baseline/upload-batch", files=files,
                                  data={"provenance": "verified"}, headers=T))
        assert up["imported"] == n_papers, up
        students.append((row["student_id"], s["token"], n_papers))

    for i, (sid, tok, _) in enumerate(students):
        for k, exam in enumerate(exams):
            voice = i if k == 0 else i + 1  # Exam B imitates the partner's voice
            _ok(live_client.post(f"/bluebook/me/exams/{exam['id']}/start", headers=_auth(tok)))
            _ok(live_client.post("/bluebook/submissions", json={
                "exam_id": exam["id"], "student_id": sid, "word_count": 360,
                "text": _paper(voice, "public parks"),
            }, headers=_auth(tok)), 201)
        assert live_client.post(f"/students/{sid}/score", json={"text": _paper(0, "x")}, headers=_auth(tok)).status_code == 403

    # Teacher-side scoring of the thin student is refused with a clear state.
    thin = students[2][0]
    r = live_client.post(f"/students/{thin}/score", json={"text": _paper(2, "public parks")}, headers=T)
    assert r.status_code == 422 and r.json()["detail"]["code"] == "insufficient_baseline"

    export = tmp_path / "export"
    labels = [("submission_id", "label", "true_author")]
    for k, exam in enumerate(exams):
        text = live_client.get(f"/bluebook/exams/{exam['id']}/export", headers=T).text
        for row in csv.DictReader(text.splitlines()):
            d = export / row["student_id"].replace(":", "_")
            (d / "submission").mkdir(parents=True, exist_ok=True)
            (d / "baseline").mkdir(exist_ok=True)
            (d / "submission" / f"{row['submission_id']}.txt").write_text(row["text"])
            labels.append((row["submission_id"], "natural" if k == 0 else "not_own", row["student_id"]))
    for sid, _, n in students:
        d = export / sid.replace(":", "_")
        for idx in range(n):
            sample = _ok(live_client.get(f"/students/{sid}/samples/{idx}/text", headers=T))
            (d / "baseline" / f"{idx:02d}.txt").write_text(sample["text"])
    lab = tmp_path / "labels.csv"
    with lab.open("w", newline="") as f:
        csv.writer(f).writerows(labels)

    _, rows, problems = batch.run_batch(export, tmp_path / "out", ROOT, lab, no_rerun=True, throttle_seconds=0)
    by_student = {}
    for row in rows:
        by_student.setdefault(row["student"], []).append(row)
    thin_rows = by_student[thin.replace(":", "_")]
    assert all(r["insufficient_baseline"] and r.get("deviation") is None for r in thin_rows)
    scored = [r for s, rs in by_student.items() if s != thin.replace(":", "_") for r in rs]
    assert len(scored) == 4 and all(r.get("deviation") is not None and not r.get("error") for r in scored), scored
    report = (tmp_path / "out" / "report.md").read_text()
    assert "INSUFFICIENT BASELINE" in report
