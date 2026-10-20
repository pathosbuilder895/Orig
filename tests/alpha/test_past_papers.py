"""Students sharing their own past papers from the Collections account
(original/routers/past_papers.py): stored pending, never scored, only
teacher-approved papers enter the baseline and count toward the 3-paper gate,
tenant- and student-scoped, and the split tag reaches the alpha export."""

from __future__ import annotations

import csv
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest

from original import principal
from original.repository import get_repository, reset_repository
from scripts.alpha import batch_score_alpha as batch

from tests.alpha.test_alpha_ready_e2e import TOPICS, _paper

ROOT = Path(__file__).resolve().parents[2]
PASSWORD = "alpha-local-Passw0rd!"
# Anything that would tell a student how their writing reads.
FORBIDDEN = re.compile(
    r"score|deviation|divergence|drift|feature|voice|action|threshold|sample_count|authenticated|purity|kappa",
    re.I,
)


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


def _workspace(client, email, n_students=2):
    """A teacher with Original, one course, and n signed-in students."""
    inv = subprocess.run(
        [sys.executable, "scripts/invite_professor.py", email, "--name", "Teacher",
         "--with-original", "--no-expiry", "--base-url", "https://local.example.test"],
        cwd=ROOT, env={**os.environ, "INVITE_NO_EXPIRY": "1"}, text=True, capture_output=True, timeout=60,
    )
    assert inv.returncode == 0, inv.stderr
    link = re.search(r"https://local\.example\.test/bluebook/\?invite=\S+", inv.stdout).group(0)
    prof = _ok(client.post("/auth/invite/redeem", json={"token": _tok(link), "password": PASSWORD, "accept_terms": True}))
    T = _auth(prof["token"])
    course = _ok(client.post("/bluebook/courses", json={"name": "Alpha", "code": "A1"}, headers=T), 201)
    tag = email.split("@")[0].replace("+", "")
    roster = _ok(client.post(f"/bluebook/courses/{course['id']}/students", json={
        "students": [{"email": f"{tag}s{i}@example.test", "name": f"S{i}"} for i in range(n_students)],
        "send_email": False,
    }, headers=T))["students"]
    students = []
    for row in roster:
        s = _ok(client.post("/auth/invite/redeem", json={"token": _tok(row["invite_path"]), "password": PASSWORD}))
        students.append((row["student_id"], _auth(s["token"])))
    return T, students


def _share(client, headers, text=None, file=None, **data):
    files = {"file": file} if file else None
    form = dict(data)
    if text is not None:
        form["text"] = text
    return client.post("/bluebook/me/papers", data=form, files=files, headers=headers)


@pytest.mark.slow
def test_student_shares_pending_paper_with_no_score(live_client):
    T, [(sid, S), _] = _workspace(live_client, "t1@example.test")
    out = _ok(_share(live_client, S, file=("Essay on buses.txt", _paper(0, TOPICS[1]).encode(), "text/plain")), 201)
    assert out["message"] == "Received — your teacher will review it."
    assert [p["title"] for p in out["papers"]] == ["Essay on buses"]
    assert out["papers"][0]["status"] == "pending" and out["papers"][0]["is_section"] is False
    assert not FORBIDDEN.search(json.dumps(out)), out
    listed = _ok(live_client.get("/bluebook/me/papers", headers=S))
    assert listed["enabled"] is True and not FORBIDDEN.search(json.dumps(listed))
    # Pending: nothing reached the baseline, and nothing was scored.
    state = get_repository().get(sid)
    assert state is None or state.sample_count == 0
    # Teacher sees it with the student's name and the source tag.
    [row] = _ok(live_client.get("/bluebook/past-papers?status=pending", headers=T))["papers"]
    assert row["student"] == "S0" and row["baseline_source"] == "independent" and row["status"] == "pending"
    # A repeat of the same text is refused; a too-short paste too.
    assert _share(live_client, S, text=_paper(0, TOPICS[1])).status_code == 409
    assert _share(live_client, S, text="too short").status_code == 422
    # A file of an unsupported type is refused plainly.
    assert _share(live_client, S, file=("x.png", b"\x89PNG", "image/png")).status_code == 422
    # A section needs the longer paper's title.
    assert _share(live_client, S, text=_paper(0, TOPICS[2]), is_section="1").status_code == 422
    # Students cannot reach the teacher list or approval.
    assert live_client.get("/bluebook/past-papers", headers=S).status_code == 403
    assert live_client.post(f"/bluebook/past-papers/{row['paper_id']}/approve", headers=S).status_code == 403
    # Signed out: refused.
    assert live_client.post("/bluebook/me/papers", data={"text": _paper(0, TOPICS[3])}).status_code == 401


@pytest.mark.slow
def test_only_approved_papers_count_toward_gate(live_client):
    T, [(sid, S), _] = _workspace(live_client, "t2@example.test")
    for k in range(4):
        _ok(_share(live_client, S, text=_paper(0, TOPICS[k]), title=f"Paper {k}"), 201)
    papers = _ok(live_client.get("/bluebook/past-papers", headers=T))["papers"]
    by_title = {p["title"]: p["paper_id"] for p in papers}
    for k in range(2):
        out = _ok(live_client.post(f"/bluebook/past-papers/{by_title[f'Paper {k}']}/approve", headers=T))
        assert out["status"] == "approved"
    _ok(live_client.post(f"/bluebook/past-papers/{by_title['Paper 3']}/decline", headers=T))
    # Two approved, one pending, one declined: below the 3-paper gate.
    r = live_client.post(f"/students/{sid}/score", json={"text": _paper(0, "public parks")}, headers=T)
    assert r.status_code == 422 and r.json()["detail"]["have"] == 2, r.text
    out = _ok(live_client.post(f"/bluebook/past-papers/{by_title['Paper 2']}/approve", headers=T))
    assert out["status"] == "approved"
    r = live_client.post(f"/students/{sid}/score", json={"text": _paper(0, "public parks")}, headers=T)
    assert r.status_code == 200, r.text
    # Approved samples are self-uploads, never supervised.
    state = get_repository().get(sid)
    assert state.sample_count == 3
    assert {s.provenance for s in state.samples} == {"unverified"}
    # The student sees statuses only.
    mine = _ok(live_client.get("/bluebook/me/papers", headers=S))
    assert sorted(p["status"] for p in mine["papers"]) == ["approved", "approved", "approved", "declined"]
    assert not FORBIDDEN.search(json.dumps(mine))
    # Approving twice is a no-op; declining an approved paper or approving a
    # declined one is refused.
    assert _ok(live_client.post(f"/bluebook/past-papers/{by_title['Paper 0']}/approve", headers=T))["status"] == "approved"
    assert get_repository().get(sid).sample_count == 3
    assert live_client.post(f"/bluebook/past-papers/{by_title['Paper 0']}/decline", headers=T).status_code == 409
    assert live_client.post(f"/bluebook/past-papers/{by_title['Paper 3']}/approve", headers=T).status_code == 409


@pytest.mark.slow
def test_papers_are_scoped_to_student_and_workspace(live_client):
    T1, [(a, SA), (_b, SB)] = _workspace(live_client, "t3@example.test")
    T2, [(_c, SC), _] = _workspace(live_client, "t4@example.test")
    _ok(_share(live_client, SA, text=_paper(0, TOPICS[0]), title="A's paper"), 201)
    # Another student in the same course sees none of it.
    assert _ok(live_client.get("/bluebook/me/papers", headers=SB))["papers"] == []
    # A student_id in the form is ignored: the paper is always the caller's own.
    _ok(_share(live_client, SB, text=_paper(1, TOPICS[1]), title="B's paper", student_id=a), 201)
    a_titles = [p["title"] for p in _ok(live_client.get("/bluebook/me/papers", headers=SA))["papers"]]
    assert a_titles == ["A's paper"]
    # The other workspace's teacher neither lists nor touches them.
    assert _ok(live_client.get("/bluebook/past-papers", headers=T2))["papers"] == []
    pid = next(p["paper_id"] for p in _ok(live_client.get("/bluebook/past-papers", headers=T1))["papers"]
               if p["title"] == "A's paper")
    for verb in ("approve", "decline"):
        assert live_client.post(f"/bluebook/past-papers/{pid}/{verb}", headers=T2).status_code == 404
    assert live_client.get(f"/bluebook/past-papers/{pid}", headers=T2).status_code == 404
    assert _ok(live_client.get(f"/bluebook/past-papers/{pid}", headers=T1))["text"]
    assert _ok(live_client.get("/bluebook/me/papers", headers=SC))["papers"] == []


@pytest.mark.slow
def test_split_tag_reaches_export(live_client, tmp_path):
    T, [(sid, S), _] = _workspace(live_client, "t5@example.test")
    _ok(_share(live_client, S, text=_paper(0, TOPICS[0]), title="Whole"), 201)
    for k in (1, 2):
        _ok(_share(live_client, S, text=_paper(0, TOPICS[k]), title=f"Part {k}",
                   is_section="1", parent_title="My Long Thesis"), 201)
    rows = _ok(live_client.get("/bluebook/past-papers", headers=T))["papers"]
    assert {r["title"]: r["baseline_source"] for r in rows} == {
        "Whole": "independent", "Part 1": "split", "Part 2": "split"}
    for r in rows:
        _ok(live_client.post(f"/bluebook/past-papers/{r['paper_id']}/approve", headers=T))
    approved = _ok(live_client.get("/bluebook/past-papers", headers=T))["papers"]
    folder = sid.replace(":", "_")
    texts = {f"{i:02d}.txt": _ok(live_client.get(f"/students/{sid}/samples/{i}/text", headers=T))["text"]
             for i in range(3)}
    (tmp_path / folder / "baseline").mkdir(parents=True)
    for name, text in texts.items():
        (tmp_path / folder / "baseline" / name).write_text(text)
    path = batch.write_baseline_sources(tmp_path, {folder: texts}, approved)
    out = list(csv.DictReader(path.open()))
    assert sorted(r["baseline_source"] for r in out) == ["independent", "split", "split"]
    assert {r["parent_paper_id"] for r in out if r["baseline_source"] == "split"} == {f"{folder}:my long thesis"}
    mapping, present = batch.load_baseline_sources(tmp_path, {folder})
    assert present and sum(1 for v in mapping[folder].values() if v[0] == "split") == 2
    # Matched by text, which the export and the stored paper share.
    hashes = {r["text_sha256"] for r in approved}
    assert all(hashlib.sha256(t.encode()).hexdigest() in hashes for t in texts.values())
    # A hand-tagged baselines.csv already in the export is left alone.
    assert batch.write_baseline_sources(tmp_path, {folder: texts}, approved) is None
