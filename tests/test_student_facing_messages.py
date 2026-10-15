"""Server messages a student can see are plain, calm and kind.

A launch link is opened by a browser, so its errors used to land on the
student's screen as raw JSON ({"detail": ...}). They now come back as a short
page when the browser asks for HTML, and stay JSON for API callers. The
launch page itself never names Original (a Collections-only workspace never
shows Original's name), and the maintenance message is a sentence a person
can act on.
"""

from __future__ import annotations

from original import student_auth

_TENANT = "bbmsg"
_BROWSER = {"Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8"}


def test_an_unusable_launch_link_gives_a_browser_a_page_not_json(live_client, store_reset):
    r = live_client.get("/bluebook/launch", params={"t": "not-a-token"}, headers=_BROWSER)
    assert r.status_code == 400
    assert r.headers["content-type"].startswith("text/html")
    assert "This exam link has expired or is not valid." in r.text
    assert "Please ask your teacher for a new one." in r.text
    assert '"detail"' not in r.text


def test_an_unusable_launch_link_stays_json_for_an_api_caller(live_client, store_reset):
    r = live_client.get("/bluebook/launch", params={"t": "not-a-token"})
    assert r.status_code == 400
    assert r.json()["detail"] == "This exam link has expired or is not valid. Please ask your teacher for a new one."


def test_a_launch_link_without_a_student_is_explained_plainly(live_client, store_reset):
    token = student_auth.mint_launch_token("", _TENANT, exam="exam-1", name="")
    r = live_client.get("/bluebook/launch", params={"t": token}, headers=_BROWSER)
    assert r.status_code == 400
    assert "This exam link is incomplete." in r.text
    assert "student binding" not in r.text


def test_the_launch_page_does_not_name_original(live_client, store_reset):
    token = student_auth.mint_launch_token(f"{_TENANT}:s1", _TENANT, exam="", name="")
    r = live_client.get("/bluebook/launch", params={"t": token}, headers=_BROWSER)
    assert r.status_code == 200
    assert "<title>Collections</title>" in r.text
    assert "Opening your exam" in r.text
    assert "Original" not in r.text.split("<script>")[0]


def test_the_maintenance_message_is_one_a_person_can_act_on(live_client, store_reset, monkeypatch):
    monkeypatch.setenv("MAINTENANCE_MODE", "1")
    r = live_client.post("/auth/login", json={"email": "a@b.test", "password": "whatever-123"})
    assert r.status_code == 503
    detail = r.json()["detail"]
    assert detail.startswith("Maintenance in progress.")
    assert "Please try again in a few minutes." in detail
    assert "frozen" not in detail and "migration" not in detail
    assert chr(0x2014) not in detail


def test_a_reading_that_differs_does_not_push_the_student_back_to_their_baseline():
    """NORTH_STAR rule 5: no result should push a student to imitate a
    baseline. My work (demo/original/my-work.html) shows this summary; it used
    to call the piece "worth revisiting" and offer a pathway that page does
    not have."""
    from original import voice as voice_mod

    layer7 = {
        "baseline_confidence": {"authenticated_count": 5, "effective_sample_count": 3.0},
        "recommendation": {"action": "escalate"},
        "authorship": {"deviation_score": 0.9},
        "interference": {"constructive_features": []},
    }
    summary = voice_mod.project_submission_result(layer7, "Dana")["summary"]
    for word in ("revisit", "pathway", "diverge", "verdict"):
        assert word not in summary.lower(), word
    assert "not a judgement about you" in summary
