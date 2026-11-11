"""Alpha-readiness gates: the 3-paper baseline minimum and non-expiring invites.

conftest sets MIN_BASELINE_SAMPLES=1 for legacy fixtures; every test here
removes it so the production default (3) is what is checked.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from original import invites as invites_mod
from original import mailer
from tests.test_bluebook_self_serve import PW, _add_students, _auth, _course, _signup, _token_of
from tests.test_scoring_router_branches import BLEND, LONG_TEXT, SUBMISSION_TEXT, _add_baseline, _score


@pytest.fixture
def production_minimum(monkeypatch):
    monkeypatch.delenv("MIN_BASELINE_SAMPLES", raising=False)


def _texts(n):
    return [f"Essay number {i}. " + LONG_TEXT for i in range(n)]


def test_default_minimum_is_three(production_minimum):
    from original.routers._shared import min_baseline_samples

    assert min_baseline_samples() == 3


@pytest.mark.parametrize("raw,expected", [("5", 5), ("0", 1), ("junk", 3), ("", 3)])
def test_minimum_env_override(monkeypatch, raw, expected):
    from original.routers._shared import min_baseline_samples

    monkeypatch.setenv("MIN_BASELINE_SAMPLES", raw)
    assert min_baseline_samples() == expected


def test_two_papers_is_insufficient_baseline_not_a_score(live_client, store_reset, production_minimum):
    sid = "gate-two"
    for t in _texts(2):
        assert _add_baseline(live_client, sid, text=t).status_code in (200, 201)
    r = _score(live_client, sid)
    assert r.status_code == 422, r.text
    detail = r.json()["detail"]
    assert detail["code"] == "insufficient_baseline"
    assert detail["required"] == 3 and detail["have"] == 2
    assert "deviation_score" not in r.text
    b = live_client.post(BLEND.format(sid=sid), json={"text": SUBMISSION_TEXT})
    assert b.status_code == 422 and b.json()["detail"]["code"] == "insufficient_baseline"


def test_three_papers_scores(live_client, store_reset, production_minimum):
    sid = "gate-three"
    for t in _texts(3):
        assert _add_baseline(live_client, sid, text=t).status_code in (200, 201)
    r = _score(live_client, sid)
    assert r.status_code == 200, r.text


def test_readiness_floor_follows_the_minimum(live_client, store_reset, production_minimum):
    sid = "gate-ready"
    for t in _texts(2):
        _add_baseline(live_client, sid, text=t)
    r = live_client.get(f"/students/{sid}/readiness").json()
    assert r["verdict"] == "insufficient"
    assert any("at least 3 approved baseline papers" in x for x in r["recommendations"])
    _add_baseline(live_client, sid, text="A third. " + LONG_TEXT)
    assert live_client.get(f"/students/{sid}/readiness").json()["verdict"] == "developing"


# ── invites ──────────────────────────────────────────────────────────────────


def test_invites_expire_in_14_days_by_default(monkeypatch):
    monkeypatch.delenv("INVITE_NO_EXPIRY", raising=False)
    assert not invites_mod.no_expiry()
    assert "expires in 14 days" in mailer._validity()


def test_no_expiry_invite_is_far_future_and_redeemable(live_client, store_reset, monkeypatch):
    monkeypatch.setenv("INVITE_NO_EXPIRY", "1")
    t = _signup(live_client)
    row = _add_students(live_client, t["token"], _course(live_client, t["token"]), "s@x.edu")[0]
    assert datetime.fromisoformat(row["invite_expires_at"]).year == 9999
    assert "stays valid until it is used or replaced" in mailer._validity()
    r = live_client.post("/auth/invite/redeem", json={"token": _token_of(row["invite_path"]), "password": PW})
    assert r.status_code == 200, r.text


def test_removing_a_student_revokes_their_unused_link(live_client, store_reset, monkeypatch):
    monkeypatch.setenv("INVITE_NO_EXPIRY", "1")
    t = _signup(live_client)
    course = _course(live_client, t["token"])
    row = _add_students(live_client, t["token"], course, "gone@x.edu")[0]
    r = live_client.delete(f"/bluebook/courses/{course}/students/{row['student_id']}", headers=_auth(t["token"]))
    assert r.status_code == 200, r.text
    redeem = live_client.post("/auth/invite/redeem", json={"token": _token_of(row["invite_path"]), "password": PW})
    assert redeem.status_code == 400


# ── batch scorer ─────────────────────────────────────────────────────────────


def test_batch_reports_insufficient_baseline_students_without_scoring(tmp_path):
    from scripts.alpha import batch_score_alpha as batch

    for student, n in (("thin", 2), ("full", 3)):
        base = tmp_path / "export" / student
        (base / "baseline").mkdir(parents=True)
        (base / "submission").mkdir()
        for i in range(n):
            (base / "baseline" / f"{i:02d}.txt").write_text("word " * 150)
        (base / "submission" / f"{student}-sub.txt").write_text("word " * 150)
    calls = []

    def scorer(repo, baseline_dir, submission_dir, student_id):
        calls.append(student_id)
        return {"submissions": [{"filename": f"{student_id}-sub.txt", "deviation_score": 0.2,
                                 "authorship_probability": 0.2, "recommended_action": "no_action"}]}, 0.0, ""

    _, rows, problems = batch.run_batch(tmp_path / "export", tmp_path / "out", tmp_path, None,
                                        no_rerun=True, throttle_seconds=0, scorer=scorer)
    assert calls == ["full"]
    thin = next(r for r in rows if r["student"] == "thin")
    assert thin["insufficient_baseline"] and thin.get("deviation") is None
    assert any("INSUFFICIENT BASELINE" in p for p in problems)
    report = (tmp_path / "out" / "report.md").read_text()
    assert "insufficient baseline (fewer than 3 papers, not scored): thin" in report
