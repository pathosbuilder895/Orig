from __future__ import annotations

import csv
import json
import math
import os
import re
import socket
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient

from original import principal
from original.repository import get_repository, reset_repository
from scripts.alpha import batch_score_alpha as batch
from scripts.alpha.delete_alpha_tenant import ALPHA_TENANT_NAME, delete_tenant

ROOT = Path(__file__).resolve().parents[2]
PASSWORD = "alpha-local-Passw0rd!"


@pytest.fixture(autouse=True)
def alpha_temp_database(store_reset):
    reset_repository()
    principal.invalidate_tenant_cache()
    yield
    reset_repository()
    principal.invalidate_tenant_cache()


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _invite_token(path: str) -> str:
    return parse_qs(urlparse(path).query)["invite"][0]


def _text(seed: str) -> str:
    return " ".join(f"{seed} detail number {index} follows a careful observation in the city." for index in range(18))


def _assert_ok(response, expected=200):
    assert response.status_code == expected, response.text[:1000]
    return response.json() if "json" in response.headers.get("content-type", "") else response.text


def test_alpha_script_clis_have_help():
    for relative in (
        "scripts/alpha/batch_score_alpha.py",
        "scripts/alpha/delete_alpha_tenant.py",
        "scripts/alpha/verify_join_flow_local.py",
    ):
        result = subprocess.run([sys.executable, str(ROOT / relative), "--help"],
                                cwd=ROOT, text=True, capture_output=True, timeout=30)
        assert result.returncode == 0, result.stderr
        assert "usage:" in result.stdout.lower()


def test_local_join_verifier_cli_runs_against_a_temporary_database(live_app):
    """Exercise the join helper as a real CLI against a localhost test server."""
    from fastapi.staticfiles import StaticFiles

    # `run.py` adds the same static mount after the API routers; the test app
    # fixture intentionally contains only the API routes.
    # live_app is session-scoped, so remove the mount afterwards or later
    # route-inspection tests see a Mount without `.methods`.
    routes_before = list(live_app.router.routes)
    live_app.mount("/", StaticFiles(directory=str(ROOT / "demo"), html=True), name="alpha_frontend")
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(128)
    port = listener.getsockname()[1]
    base_url = f"http://127.0.0.1:{port}"
    import uvicorn

    server = uvicorn.Server(uvicorn.Config(live_app, log_level="critical", access_log=False))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 10
        while not server.started and thread.is_alive() and time.monotonic() < deadline:
            time.sleep(.05)
        assert server.started, "local test server did not start"
        invitation = subprocess.run(
            [sys.executable, "scripts/invite_professor.py", "local+join@example.test",
             "--name", "Local Join", "--with-original", "--base-url", base_url],
            cwd=ROOT, env=os.environ.copy(), text=True, capture_output=True, timeout=60,
        )
        assert invitation.returncode == 0, invitation.stderr
        link = re.search(rf"{re.escape(base_url)}/bluebook/\?invite=[^\s]+", invitation.stdout)
        assert link, invitation.stdout
        verified = subprocess.run(
            [sys.executable, "scripts/alpha/verify_join_flow_local.py",
             link.group(0).replace(base_url, ""), "--base-url", base_url],
            cwd=ROOT, env=os.environ.copy(), text=True, capture_output=True, timeout=90,
        )
        assert verified.returncode == 0, verified.stdout + verified.stderr
        assert "PASS local join flow completed" in verified.stdout
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        listener.close()
        live_app.router.routes[:] = routes_before


def test_label_csv_validation_and_threshold_sweep_are_deterministic(tmp_path):
    export_dir = tmp_path / "export"
    student_dir = export_dir / "alpha_student"
    (student_dir / "baseline").mkdir(parents=True)
    (student_dir / "submission").mkdir()
    for i in range(3):
        (student_dir / "baseline" / f"{i}.txt").write_text(_text(f"baseline{i}"))
    (student_dir / "submission" / "natural.txt").write_text(_text("natural"))
    (student_dir / "submission" / "other.txt").write_text(_text("other"))
    labels_path = tmp_path / "labels.csv"
    with labels_path.open("w", newline="") as file:
        writer = csv.writer(file)
        writer.writerow(["submission_id", "label", "author_true", "writer_true"])
        writer.writerow(["natural", "natural", "self", "self"])
        writer.writerow(["other", "shadow", "partner", "other-writer"])

    assert batch.validate_labels(labels_path, {"natural", "other"}) == {
        "natural": {"label": "natural", "author_true": "self", "writer_true": "self", "shadow": "false",
                    "shadow_kind": "", "imitated_student_id": "", "prompt_id": "",
                    "paired_submission_id": "", "shadow_source_paper_id": "", "generator_tool": ""},
        "other": {"label": "shadow", "author_true": "partner", "writer_true": "other-writer", "shadow": "true",
                  "shadow_kind": "", "imitated_student_id": "", "prompt_id": "",
                  "paired_submission_id": "", "shadow_source_paper_id": "", "generator_tool": ""},
    }
    # Legacy header + legacy not_own label still normalise to the canonical schema.
    labels_path.write_text("submission_id,label,true_author\nnatural,natural,self\nother,not_own,partner\n")
    legacy = batch.validate_labels(labels_path, {"natural", "other"})
    assert legacy["other"]["label"] == "shadow" and legacy["other"]["author_true"] == "partner"
    with pytest.raises(ValueError, match="unknown submission ids"):
        batch.validate_labels(labels_path, {"natural"})
    labels_path.write_text("submission_id,label\nother,maybe\n")
    with pytest.raises(ValueError, match="header must be exactly"):
        batch.validate_labels(labels_path, {"other"})
    labels_path.write_text("submission_id,label,author_true,writer_true\nnatural,natural,self,self\nother,shadow,partner,other-writer\n")

    # Canonical v2: shadow metadata lives outside the scored text and is validated.
    v2 = tmp_path / "labels_v2.csv"
    v2.write_text(
        "submission_id,label,author_true,writer_true,shadow_kind,imitated_student_id,prompt_id,paired_submission_id,shadow_source_paper_id,generator_tool\n"
        "natural,natural,self,self,,,,,,\n"
        "other,shadow,partner,writer-7,ai_staff,partner,prompt-a,natural,sample-1,staff-tool-x\n")
    parsed = batch.validate_labels(v2, {"natural", "other"})
    assert parsed["other"]["shadow"] == "true" and parsed["other"]["generator_tool"] == "staff-tool-x"
    assert parsed["other"]["paired_submission_id"] == "natural"
    v2.write_text(v2.read_text().replace("writer-7", "partner"))
    with pytest.raises(ValueError, match="must not be the imitated student"):
        batch.validate_labels(v2, {"natural", "other"})

    calls = []
    def deterministic_score(repo, baseline_dir, submission_dir, student_id):
        calls.append(student_id)
        return ({"submissions": [
            {"filename": "natural.txt", "deviation_score": .2, "authorship_probability": .2,
             "recommended_action": "no_action", "scoring_time_ms": 4},
            {"filename": "other.txt", "deviation_score": .85, "authorship_probability": .85,
             "recommended_action": "escalate", "scoring_time_ms": 5},
        ]}, .01, "")

    code, rows, problems = batch.run_batch(export_dir, tmp_path / "out", ROOT, labels_path,
                                           no_rerun=False, throttle_seconds=0, scorer=deterministic_score)
    assert code == 0 and not problems
    assert len(calls) == 2  # all-data plus the determinism rerun; n=3 needs no first-three comparison
    assert all(row["deterministic"] is True for row in rows)
    assert all(math.isfinite(row["deviation"]) for row in rows)
    report = (tmp_path / "out/report.md").read_text().lower()
    assert "deviation threshold sweep" in report
    assert sum(line.startswith("| 0.") for line in report.splitlines()) == 19
    assert "nan" not in report


def _write_baselines(student_dir, count=3):
    (student_dir / "baseline").mkdir(parents=True, exist_ok=True)
    (student_dir / "submission").mkdir(exist_ok=True)
    for i in range(count):
        (student_dir / "baseline" / f"{i:02d}.txt").write_text(_text(f"baseline{i}"))


def test_split_baseline_tagging_and_report_breakout(tmp_path):
    export_dir = tmp_path / "export"
    ind = export_dir / "stud_ind"; spl = export_dir / "stud_split"
    _write_baselines(ind); _write_baselines(spl)
    (ind / "submission" / "ind_natural.txt").write_text(_text("ind natural"))
    (spl / "submission" / "split_natural.txt").write_text(_text("split natural"))
    (export_dir / "baselines.csv").write_text(
        "student,baseline_file,baseline_source,parent_paper_id\n"
        + "".join(f"stud_ind,{i:02d}.txt,independent,\n" for i in range(3))
        + "".join(f"stud_split,{i:02d}.txt,split,long-paper-1\n" for i in range(3)))
    labels_path = tmp_path / "labels.csv"
    labels_path.write_text("submission_id,label,author_true,writer_true\n"
                           "ind_natural,natural,stud_ind,stud_ind\n"
                           "split_natural,natural,stud_split,stud_split\n")

    def fake_score(repo, baseline_dir, submission_dir, student_id):
        flagged = "split" in student_id
        return ({"submissions": [
            {"filename": path.name, "deviation_score": .9 if flagged else .2,
             "authorship_probability": .5,
             "recommended_action": "escalate" if flagged else "no_action",
             "scoring_time_ms": 1} for path in sorted(Path(submission_dir).glob("*.txt"))]}, .01, "")

    code, rows, problems = batch.run_batch(export_dir, tmp_path / "out", ROOT, labels_path,
                                           no_rerun=True, throttle_seconds=0, scorer=fake_score)
    assert not problems
    by_id = {row["submission_id"]: row for row in rows}
    # Gate counts papers (3 each), but split-derived count is reported separately.
    assert by_id["ind_natural"]["baseline_source"] == "independent"
    assert by_id["ind_natural"]["n_split_baselines"] == 0
    assert by_id["split_natural"]["baseline_source"] == "split"
    assert by_id["split_natural"]["n_split_baselines"] == 3
    assert by_id["split_natural"]["baseline_parent_ids"] == "long-paper-1"
    report = (tmp_path / "out/report.md").read_text()
    assert "Baseline-source breakout" in report and "never pooled silently" in report
    assert "| independent | 1 | 1 | 0/1 (0%) |" in report
    assert "| split | 1 | 1 | 1/1 (100%) |" in report
    csv_text = (tmp_path / "out/per_submission.csv").read_text()
    assert "baseline_source" in csv_text and "n_split_baselines" in csv_text


def test_ai_own_is_validated_and_can_still_be_reported_separately(tmp_path):
    export_dir = tmp_path / "export"
    stud = export_dir / "stud_c"
    _write_baselines(stud)
    for name in ("c_natural", "c_partner", "c_own"):
        (stud / "submission" / f"{name}.txt").write_text(_text(name))
    header = ("submission_id,label,author_true,writer_true,shadow_kind,imitated_student_id,prompt_id,"
              "paired_submission_id,shadow_source_paper_id,generator_tool\n")
    labels_path = tmp_path / "labels.csv"
    good = (header + "c_natural,natural,stud_c,stud_c,,,,,,\n"
            "c_partner,shadow,stud_c,writer-9,human_partner,stud_c,prompt-a,c_natural,sample-1,\n"
            "c_own,shadow,stud_c,stud_c,ai_own,stud_c,prompt-a,c_natural,,tester-tool-y\n")
    labels_path.write_text(good)
    ids = {"c_natural", "c_partner", "c_own"}
    parsed = batch.validate_labels(labels_path, ids)
    assert parsed["c_own"]["shadow_kind"] == "ai_own" and parsed["c_own"]["shadow"] == "true"
    # ai_own requires generator_tool and must imitate the tester's own writing.
    labels_path.write_text(good.replace("tester-tool-y", ""))
    with pytest.raises(ValueError, match="ai_own shadow needs generator_tool"):
        batch.validate_labels(labels_path, ids)
    labels_path.write_text(good.replace("ai_own,stud_c,", "ai_own,someone-else,"))
    with pytest.raises(ValueError, match="imitated_student_id must equal author_true"):
        batch.validate_labels(labels_path, ids)
    # Other kinds still reject writer_true == author_true.
    labels_path.write_text(good.replace("writer-9", "stud_c"))
    with pytest.raises(ValueError, match="must not be the imitated student"):
        batch.validate_labels(labels_path, ids)
    labels_path.write_text(good)

    def fake_score(repo, baseline_dir, submission_dir, student_id):
        return ({"submissions": [
            {"filename": path.name, "deviation_score": .9 if "own" in path.name else .2,
             "authorship_probability": .5,
             "recommended_action": "escalate" if "own" in path.name else "no_action",
             "scoring_time_ms": 1} for path in sorted(Path(submission_dir).glob("*.txt"))]}, .01, "")

    # Default: every shadow kind, ai_own included, counts in the headline.
    code, rows, problems = batch.run_batch(export_dir, tmp_path / "out", ROOT, labels_path,
                                           no_rerun=True, throttle_seconds=0, scorer=fake_score)
    assert not problems
    report = (tmp_path / "out/report.md").read_text()
    assert "Caught shadow work (all kinds): 1/2 (50%)" in report
    assert "| ai_own | AI imitation of own writing | 1 | 1/1 (100%) |" in report
    assert "| human_partner | human shadow | 1 | 0/1 (0%) |" in report
    # Opting out keeps the old separate reporting: ai_own is not pooled in.
    kinds = batch.parse_shadow_kinds("human_partner,ai_staff,injected_other,public_domain")
    code, rows, problems = batch.run_batch(export_dir, tmp_path / "out2", ROOT, labels_path,
                                           no_rerun=True, throttle_seconds=0, scorer=fake_score,
                                           primary_kinds=kinds)
    assert not problems
    report = (tmp_path / "out2/report.md").read_text()
    assert "Caught shadow work (ai_staff, human_partner, injected_other, public_domain): 0/1 (0%)" in report
    assert "not pooled above: ai_own" in report
    assert "| ai_own | AI imitation of own writing (separate) | 1 | 1/1 (100%) |" in report
    assert "- Human shadows: 0/1 (0%)" in report
    assert "- AI imitation of own writing (ai_own, separate; not in the criteria): 1/1 (100%)" in report
    assert all(row["not_own_total"] == 1 for row in batch.threshold_sweep(rows, kinds))


def test_simplified_alpha_ai_own_is_the_headline_shadow(tmp_path):
    """Simplified alpha (2026-10-25): "Your own piece" (natural) + "AI imitation"
    (ai_own). With no other shadow kind, the headline catch rate, the gate, the
    sweep and the breakout must all count the AI imitation."""
    export_dir = tmp_path / "export"
    stud = export_dir / "EXAMPLE-stu-A"
    _write_baselines(stud)
    (stud / "submission" / "EXAMPLE-DELETE-sub001.txt").write_text(_text("own piece"))
    (stud / "submission" / "EXAMPLE-DELETE-sub002.txt").write_text(_text("ai imitation"))
    labels_path = tmp_path / "answer_key.csv"
    labels_path.write_text(
        "submission_id,label,author_true,writer_true,shadow_kind,imitated_student_id,prompt_id,"
        "paired_submission_id,shadow_source_paper_id,generator_tool\n"
        "EXAMPLE-DELETE-sub001,natural,EXAMPLE-stu-A,EXAMPLE-stu-A,,,own-piece,,,\n"
        "EXAMPLE-DELETE-sub002,shadow,EXAMPLE-stu-A,EXAMPLE-stu-A,ai_own,EXAMPLE-stu-A,own-piece,"
        "EXAMPLE-DELETE-sub001,EXAMPLE-DELETE-sub001,EXAMPLE-ToolName\n")
    seen_dirs = []

    def fake_score(repo, baseline_dir, submission_dir, student_id):
        seen_dirs.append((Path(baseline_dir), Path(submission_dir)))
        return ({"submissions": [
            {"filename": path.name, "deviation_score": .8 if path.stem.endswith("2") else .2,
             "authorship_probability": .5,
             "recommended_action": "escalate" if path.stem.endswith("2") else "no_action",
             "scoring_time_ms": 1} for path in sorted(Path(submission_dir).glob("*.txt"))]}, .01, "")

    code, rows, problems = batch.run_batch(export_dir, tmp_path / "out", ROOT, labels_path,
                                           no_rerun=True, throttle_seconds=0, scorer=fake_score,
                                           evidence=False)
    assert not problems
    report = (tmp_path / "out/report.md").read_text()
    assert "Caught shadow work (all kinds): 1/1 (100%)" in report
    assert "False flags on natural work: 0/1 (0%)" in report
    assert "**PASS** on point estimates." in report and code == 0
    sweep = batch.threshold_sweep(rows)
    assert sweep and all(row["not_own_total"] == 1 and row["natural_total"] == 1 for row in sweep)
    assert "| 0.50 | 1/1 (100%) | 0/1 (0%) |" in report
    assert "| independent | 1 | 1 | 0/1 (0%) | 1 | 1/1 (100%) |" in report
    # Labels stay out of the scored text: the scorer saw only the export's own files.
    for baseline_dir, submission_dir in seen_dirs:
        assert submission_dir == stud / "submission"
        for path in list(baseline_dir.glob("*")) + list(submission_dir.glob("*")):
            text = path.read_text()
            assert "ai_own" not in text and "EXAMPLE-ToolName" not in text
    # The CLI flag rejects unknown kinds.
    with pytest.raises(ValueError, match="unknown: bogus"):
        batch.parse_shadow_kinds("ai_own,bogus")
    assert batch.parse_shadow_kinds("all") == batch.DEFAULT_PRIMARY_SHADOW_KINDS




def test_baselines_csv_rejects_split_without_parent_and_unknown_files(tmp_path):
    export_dir = tmp_path / "export"
    student_dir = export_dir / "stud_a"
    _write_baselines(student_dir)
    (student_dir / "submission" / "paper.txt").write_text(_text("paper"))
    bad = export_dir / "baselines.csv"
    bad.write_text("student,baseline_file,baseline_source,parent_paper_id\nstud_a,00.txt,split,\n")
    with pytest.raises(ValueError, match="parent_paper_id"):
        batch.load_baseline_sources(export_dir, {"stud_a"})
    bad.write_text("student,baseline_file,baseline_source,parent_paper_id\nstud_a,99.txt,independent,\n")
    with pytest.raises(ValueError, match="no such baseline file"):
        batch.load_baseline_sources(export_dir, {"stud_a"})
    assert batch.load_baseline_sources(tmp_path / "empty", {"stud_a"}) == ({}, False)


def test_batch_scoring_rejects_non_finite_scores_and_never_writes_nan(tmp_path):
    export_dir = tmp_path / "export"
    student_dir = export_dir / "alpha_one"
    (student_dir / "baseline").mkdir(parents=True)
    (student_dir / "submission").mkdir()
    for index in range(3):
        (student_dir / "baseline" / f"{index}.txt").write_text(_text(str(index)))
    (student_dir / "submission" / "paper.txt").write_text(_text("paper"))
    def bad_score(*_args):
        return ({"submissions": [{"filename": "paper.txt", "deviation_score": float("nan"),
                                   "authorship_probability": .5, "recommended_action": "no_action"}]}, .01, "")
    code, rows, problems = batch.run_batch(export_dir, tmp_path / "out", ROOT, None,
                                           no_rerun=True, throttle_seconds=0, scorer=bad_score)
    assert code == 2
    assert any("non-finite" in problem for problem in problems)
    assert (tmp_path / "out/report.md").exists()
    assert "nan" not in (tmp_path / "out/report.md").read_text().lower()
    assert "nan" not in (tmp_path / "out/per_submission.csv").read_text().lower()


def test_delete_is_dry_run_by_default_and_scoped_to_named_alpha_tenant():
    repo = get_repository()
    repo.put_tenant("alpha-one", ALPHA_TENANT_NAME, environment="production", meta={})
    repo.set_tenant_products("alpha-one", ["bluebook", "original"])
    repo.put_tenant("other-one", "Another workspace", environment="production", meta={})
    repo.set_tenant_products("other-one", ["bluebook"])
    repo.put_bluebook_course({"id": "course-alpha", "tenant_id": "alpha-one", "name": "Alpha", "code": "A"})
    repo.put_bluebook_course({"id": "course-other", "tenant_id": "other-one", "name": "Other", "code": "O"})

    assert delete_tenant(repo, "alpha-one", execute=False, confirm_name="") == 0
    assert repo.get_bluebook_course("course-alpha") is not None
    assert delete_tenant(repo, "alpha-one", execute=True, confirm_name="wrong") == 4
    assert repo.get_bluebook_course("course-alpha") is not None
    assert delete_tenant(repo, "alpha-one", execute=True, confirm_name=ALPHA_TENANT_NAME) == 0
    assert repo.get_bluebook_course("course-alpha") is None
    assert repo.get_bluebook_course("course-other") is not None
    assert delete_tenant(repo, "other-one", execute=True, confirm_name="Another workspace") == 3
    assert repo.get_bluebook_course("course-other") is not None


def test_student_token_cannot_call_scoring_when_exam_consistency_is_off(live_client):
    repo = get_repository()
    tenant_id, student_id = "alpha-score-guard", "alpha-score-guard:student"
    repo.put_tenant(tenant_id, "Alpha score guard", environment="production", meta={})
    repo.set_tenant_products(tenant_id, ["bluebook", "original"])
    repo.put_bluebook_exam({
        "id": "alpha-consistency-off", "tenant_id": tenant_id, "course_id": None,
        "title": "Consistency off", "duration": 25, "conditions": {"aiDetect": False},
        "status": "ACTIVE", "questions": ["Write."],
    })
    token = principal.mint_principal_token(student_id, "student", tenant_id)
    headers = _auth(token)
    score = live_client.post(f"/students/{student_id}/score", json={"text": _text("private writing")}, headers=headers)
    blend = live_client.post(f"/students/{student_id}/score/blend", json={"text": _text("private writing")}, headers=headers)
    assert score.status_code == blend.status_code == 403
    assert "unavailable" in score.json()["detail"].lower()


def test_local_runbook_rehearsal_twenty_concurrent_students_full_delete(live_app, live_client, tmp_path, monkeypatch):
    """Run the local alpha path end to end against this test's throwaway SQLite DB."""
    db_path = Path(os.environ["ORIGINAL_DB"])
    monkeypatch.setenv("REPO_BACKEND", "sqlite")
    monkeypatch.delenv("REPO_SHADOW", raising=False)
    monkeypatch.setenv("ORIGINAL_ENV", "demo")
    invitation = subprocess.run(
        [sys.executable, "scripts/invite_professor.py", "andrew+alpha@example.test",
         "--name", "Andrew (Alpha test)", "--with-original", "--base-url", "https://local.example.test"],
        cwd=ROOT, env=os.environ.copy(), text=True, capture_output=True, timeout=60,
    )
    assert invitation.returncode == 0, invitation.stderr
    assert "Products: bluebook, original" in invitation.stdout
    invite_link = re.search(r"https://local\.example\.test/bluebook/\?invite=[^\s]+", invitation.stdout).group(0)
    professor = _assert_ok(live_client.post("/auth/invite/redeem", json={
        "token": _invite_token(invite_link), "password": PASSWORD, "accept_terms": True,
    }))
    tenant_id, teacher_token = professor["tenant_id"], professor["token"]
    assert get_repository().get_tenant(tenant_id)["products"] == ["bluebook", "original"]

    course = _assert_ok(live_client.post("/bluebook/courses", json={"name": "Alpha test", "code": "ALPHA1"},
                                         headers=_auth(teacher_token)), 201)
    exam_headers = {"blockCopy": True, "blockAI": True, "blockWeb": False, "aiDetect": False, "spellChk": True}
    exams = []
    for name in ("Practice prompt 1", "Practice prompt 2 (other-style)"):
        exam = _assert_ok(live_client.post("/bluebook/exams", json={
            "title": name, "status": "ACTIVE", "duration": 25,
            "questions": ["Describe a city that exists only at night."],
            "conditions": exam_headers, "course_id": course["id"],
        }, headers=_auth(teacher_token)), 201)
        assert exam["duration"] == 25 and exam["conditions"]["blockCopy"] is True
        assert exam["conditions"]["aiDetect"] is False
        exams.append(exam)

    roster = _assert_ok(live_client.post(f"/bluebook/courses/{course['id']}/students", json={
        "students": [{"email": f"alpha{i:02d}@example.test", "name": f"Volunteer {i:02d}"} for i in range(1, 21)],
        "send_email": False,
    }, headers=_auth(teacher_token))) ["students"]
    assert len(roster) == 20 and all(row["invite_path"] and not row["emailed"] for row in roster)

    students = []
    for row in roster:
        redeemed = _assert_ok(live_client.post("/auth/invite/redeem", json={
            "token": _invite_token(row["invite_path"]), "password": PASSWORD,
        }))
        assert redeemed["student_id"] == row["student_id"]
        students.append({"id": row["student_id"], "token": redeemed["token"], "email": row["email"]})
        for index in range(3):
            baseline = _assert_ok(live_client.post(f"/students/{row['student_id']}/baseline", json={
                "text": _text(f"volunteer{row['student_id'][-2:]} baseline{index}"),
                "provenance": "verified", "assignment": f"prior {index + 1}",
            }, headers=_auth(teacher_token)))
            assert baseline["authenticated_count"] >= index + 1

    # Start each sitting before sealing; only 20 students, not two sessions per student, race.
    for student in students:
        for exam in exams:
            _assert_ok(live_client.post(f"/bluebook/me/exams/{exam['id']}/start", headers=_auth(student["token"])))

    def seal(student, exam, label):
        with TestClient(live_app) as client:
            response = client.post("/bluebook/submissions", json={
                "exam_id": exam["id"], "student_id": student["id"], "word_count": 110,
                "text": _text(f"{label} paper from {student['id'][-2:]}"),
            }, headers=_auth(student["token"]))
        return student, exam, response

    pending = []
    with ThreadPoolExecutor(max_workers=20) as pool:
        for student in students:
            pending.append(pool.submit(seal, student, exams[0], "natural"))
            pending.append(pool.submit(seal, student, exams[1], "partner"))
        submissions = [future.result(timeout=90) for future in as_completed(pending)]
    submitted_ids = {}
    for student, exam, response in submissions:
        assert response.status_code == 201, response.text[:1000]
        payload = response.json()
        submitted_ids.setdefault(student["id"], {})[exam["id"]] = payload["id"]

    # A student's own endpoints omit all score fields, and the direct score and blend APIs
    # are denied because both exams explicitly disable writing consistency.
    forbidden = {"ai_score", "stylometric", "score", "deviation_score", "authorship_probability", "recommended_action"}
    for student in students:
        headers = _auth(student["token"])
        listing = _assert_ok(live_client.get("/bluebook/me/submissions", headers=headers))["submissions"]
        assert len(listing) == 2
        assert not any(forbidden.intersection(row) for row in listing)
        for submission_id in submitted_ids[student["id"]].values():
            detail = _assert_ok(live_client.get(f"/bluebook/me/submissions/{submission_id}", headers=headers))
            assert not forbidden.intersection(detail)
        denied = live_client.post(f"/students/{student['id']}/score", json={"text": _text("student direct score")}, headers=headers)
        assert denied.status_code == 403
        denied_blend = live_client.post(f"/students/{student['id']}/score/blend", json={"text": _text("student direct score")}, headers=headers)
        assert denied_blend.status_code == 403

    export_root = tmp_path / "export"
    label_file = tmp_path / "labels.csv"
    label_rows = []
    for index, exam in enumerate(exams):
        exported = live_client.get(f"/bluebook/exams/{exam['id']}/export", headers=_auth(teacher_token))
        assert exported.status_code == 200
        parsed = list(csv.DictReader(exported.text.splitlines()))
        assert len(parsed) == 20
        for row in parsed:
            student_dir = export_root / row["student_id"].replace(":", "_")
            (student_dir / "baseline").mkdir(parents=True, exist_ok=True)
            (student_dir / "submission").mkdir(exist_ok=True)
            (student_dir / "submission" / f"{row['submission_id']}.txt").write_text(row["text"], encoding="utf-8")
            label_rows.append((row["submission_id"], "natural" if index == 0 else "not_own", row["student_id"]))
    # The rehearsal export uses the official sample-text endpoint to populate each baseline.
    roster_now = _assert_ok(live_client.get("/students", headers=_auth(teacher_token)))
    for student_row in roster_now["roster"]:
        student_dir = export_root / student_row["id"].replace(":", "_")
        for index in range(3):
            sample = _assert_ok(live_client.get(f"/students/{student_row['id']}/samples/{index}/text", headers=_auth(teacher_token)))
            (student_dir / "baseline" / f"{index:02d}.txt").write_text(sample["text"], encoding="utf-8")
    with label_file.open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        writer.writerow(["submission_id", "label", "true_author"])
        writer.writerows(label_rows)

    scoring = subprocess.run([
        sys.executable, "scripts/alpha/batch_score_alpha.py", "--from-dir", str(export_root),
        "--labels", str(label_file), "--out", str(tmp_path / "scores"), "--repo", str(ROOT), "--throttle-seconds", "0",
    ], cwd=ROOT, text=True, capture_output=True, timeout=600)
    assert scoring.returncode in {0, 1}, scoring.stderr + scoring.stdout[-2000:]
    assert (tmp_path / "scores/report.md").exists() and (tmp_path / "scores/per_submission.csv").exists()
    report = (tmp_path / "scores/report.md").read_text(encoding="utf-8")
    assert "Deviation threshold sweep" in report and "submissions: 40" in report
    assert "nan" not in report.lower()

    deleted = subprocess.run([
        sys.executable, "scripts/alpha/delete_alpha_tenant.py", tenant_id,
        "--execute", "--confirm-name", ALPHA_TENANT_NAME,
    ], cwd=ROOT, env=os.environ.copy(), text=True, capture_output=True, timeout=120)
    assert deleted.returncode == 0, deleted.stderr + deleted.stdout
    repo = get_repository()
    assert repo.list_ids_for_tenant(tenant_id) == []
    assert repo.list_bluebook_courses(tenant_id) == []
    assert repo.list_bluebook_exams(tenant_id) == []


def _real_ish_text(seed: str) -> str:
    return (f"The {seed} market was loud at night; vendors shouted, and children ran between the stalls. "
            "However, I usually went early because it's quieter then. Why did people stay so late? "
            "Perhaps the food was the reason: noodles, dumplings and fresh juice. ") * 6


def test_batch_writes_staff_evidence_and_preliminary_columns_without_labels(tmp_path):
    export_dir = tmp_path / "export"
    stud = export_dir / "stud_ev"
    _write_baselines(stud)
    (stud / "submission" / "ev_natural.txt").write_text(_real_ish_text("night"))
    (stud / "submission" / "ev_other.txt").write_text(_real_ish_text("harbour"))
    thin = export_dir / "stud_thin"
    _write_baselines(thin, count=2)
    (thin / "submission" / "thin_paper.txt").write_text(_text("thin"))
    labels_path = tmp_path / "labels.csv"
    labels_path.write_text("submission_id,label,author_true,writer_true\n"
                           "ev_natural,natural,stud_ev,stud_ev\n"
                           "ev_other,shadow,stud_ev,SECRET-WRITER-LABEL\n"
                           "thin_paper,natural,stud_thin,stud_thin\n")
    destructive = [
        {"code": "semicolon_colon_rate", "name": "Semicolon+Colon Rate", "tier": 4, "contribution": 0.0,
         "direction": "destructive", "baseline_value": 0.0, "submission_value": 0.4, "delta": 0.4},
        {"code": "char_trigram_entropy", "name": "Char Trigram Entropy", "tier": 4, "contribution": 0.0,
         "direction": "destructive", "baseline_value": 0.5, "submission_value": 0.7, "delta": 0.2},
    ]

    def fake_score(repo, baseline_dir, submission_dir, student_id):
        return ({"submissions": [
            {"filename": path.name, "deviation_score": .66 if "other" in path.name else .2,
             "authorship_probability": .5,
             "recommended_action": "schedule_conversation" if "other" in path.name else "no_action",
             "scoring_time_ms": 1, "destructive_features": destructive}
            for path in sorted(Path(submission_dir).glob("*.txt"))]}, .01, "")

    out = tmp_path / "out"
    code, rows, problems = batch.run_batch(export_dir, out, ROOT, labels_path,
                                           no_rerun=True, throttle_seconds=0, scorer=fake_score)
    by_id = {row["submission_id"]: row for row in rows}
    assert by_id["ev_other"]["preliminary_score"] == 0.66
    assert by_id["ev_other"]["preliminary_band"] == "Outside the usual range"
    assert by_id["ev_natural"]["preliminary_band"] == "Within the writer's usual range"
    assert by_id["thin_paper"]["preliminary_score"] is None
    assert by_id["thin_paper"]["preliminary_band"] == "Not enough writing on file to compare yet."
    assert "evidence_file" not in by_id["thin_paper"]
    # Calibration semantics unchanged: the strict flag still comes from the action alone.
    assert by_id["ev_other"]["strict_flag"] is True and by_id["ev_natural"]["strict_flag"] is False
    for sid in ("ev_natural", "ev_other"):
        assert by_id[sid]["evidence_file"] == f"evidence/{sid}.md"
        for ext in ("md", "html", "json"):
            body = (out / "evidence" / f"{sid}.{ext}").read_text(encoding="utf-8")
            # Answer-key values never reach an evidence file.
            assert "SECRET-WRITER-LABEL" not in body and "shadow" not in body.lower()
        payload = json.loads((out / "evidence" / f"{sid}.json").read_text(encoding="utf-8"))
        assert payload["staff_only"] is True
        semicolons = payload["evidence"]["features"][0]
        assert semicolons["locatable"] is True and semicolons["this_paper"]["count"] == 12  # six ";" and six ":"
        text = (stud / "submission" / f"{sid}.txt").read_text()
        for q in semicolons["this_paper"]["examples"]:
            assert q["match"] in (";", ":") and q["match"] == text[q["match_start"]:q["match_end"]]
            assert q["passage"] == text[q["passage_start"]:q["passage_end"]]
        assert payload["evidence"]["features"][1]["locatable"] is False
    report = (out / "report.md").read_text()
    assert "Staff evidence and preliminary scores (never shown to students)" in report
    assert "Evidence passages: 2 file(s)" in report
    assert "preliminary_band" in (out / "per_submission.csv").read_text()

    # Determinism: a second run writes byte-identical evidence.
    first = (out / "evidence" / "ev_other.json").read_bytes()
    batch.run_batch(export_dir, tmp_path / "out2", ROOT, labels_path, no_rerun=True, throttle_seconds=0,
                    scorer=fake_score)
    assert (tmp_path / "out2" / "evidence" / "ev_other.json").read_bytes() == first

    # --no-evidence keeps the preliminary column and writes no evidence files.
    code, rows, _ = batch.run_batch(export_dir, tmp_path / "out3", ROOT, labels_path, no_rerun=True,
                                    throttle_seconds=0, scorer=fake_score, evidence=False)
    assert not (tmp_path / "out3" / "evidence").exists()
    assert all("evidence_file" not in row for row in rows)


def test_batch_evidence_failure_is_a_problem_not_a_crash(tmp_path, monkeypatch):
    export_dir = tmp_path / "export"
    stud = export_dir / "stud_err"
    _write_baselines(stud)
    (stud / "submission" / "paper.txt").write_text(_text("paper"))
    monkeypatch.setattr(batch, "write_evidence", lambda *a, **k: 1 / 0)

    def fake_score(*_args):
        return ({"submissions": [{"filename": "paper.txt", "deviation_score": .3, "authorship_probability": .5,
                                  "recommended_action": "no_action", "scoring_time_ms": 1}]}, .01, "")
    code, rows, problems = batch.run_batch(export_dir, tmp_path / "out", ROOT, None, no_rerun=True,
                                           throttle_seconds=0, scorer=fake_score)
    assert code == 0
    assert problems == ["stud_err/paper: evidence file not written (ZeroDivisionError)"]
    assert rows[0]["preliminary_score"] == 0.3
