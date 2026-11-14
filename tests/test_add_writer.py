"""POST /students: a teacher adds a writer by name.

An alpha writer emails papers: no course, email, invite or account. The
route mints an id in the caller's own tenant the way every other student id
is formed (``"{tenant}:{16 hex}"``, ``student_auth.derive_student_id``),
creates the empty profile and stores the name, so the writer is a roster
student like any other to every Original page.
"""

from __future__ import annotations

import re

import pytest

from original.repository import get_repository, reset_repository

TEXT = (
    "The doctrine of vocation, as articulated in the letters, situates daily labor "
    "within a larger account of providence. " * 30
)


@pytest.fixture(autouse=True)
def _fresh(store_reset):
    reset_repository()
    yield
    reset_repository()


@pytest.fixture
def staff(principal_headers):
    return principal_headers("prof-1", "professor", "acme")


def _create(client, headers, name="Ada Lovelace"):
    return client.post("/students", json={"name": name}, headers=headers)


def test_staff_adds_a_writer_in_their_own_tenant(live_client, staff):
    r = _create(live_client, staff, "  Ada Lovelace  ")
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["name"] == "Ada Lovelace"
    sid = body["student_id"]
    assert re.fullmatch(r"acme:[0-9a-f]{16}", sid)
    repo = get_repository()
    assert repo.get(sid) is not None
    assert repo.get(sid).sample_count == 0
    assert repo.get_display_name(sid) == "Ada Lovelace"


def test_the_audit_row_names_the_student_id_not_the_name(live_client, staff):
    sid = _create(live_client, staff).json()["student_id"]
    rows = get_repository().list_audit_actions_for_student(sid, ["writer_create"])
    assert len(rows) == 1
    assert rows[0]["result"] == "ok"
    assert "Ada" not in repr(rows[0])


def test_the_writer_is_on_the_roster_with_its_name_and_needs_more(live_client, staff):
    sid = _create(live_client, staff).json()["student_id"]
    r = live_client.get("/students", headers=staff)
    assert r.status_code == 200
    assert sid in r.json()["students"]
    row = next(x for x in r.json()["roster"] if x["id"] == sid)
    assert row["name"] == "Ada Lovelace"
    assert row["has_name"] is True
    assert row["sample_count"] == 0
    ready = live_client.get(f"/students/{sid}/readiness", headers=staff)
    assert ready.status_code == 200
    assert ready.json()["verdict"] == "insufficient"
    state = live_client.get(f"/students/{sid}", headers=staff)
    assert state.status_code == 200


def test_the_writer_takes_baseline_writing_like_any_student(live_client, staff):
    sid = _create(live_client, staff).json()["student_id"]
    r = live_client.post(
        f"/students/{sid}/baseline",
        json={"text": TEXT, "provenance": "verified"},
        headers=staff,
    )
    assert r.status_code == 200, r.text
    assert get_repository().get(sid).sample_count == 1


def test_two_writers_with_one_name_are_two_writers(live_client, staff):
    a = _create(live_client, staff).json()["student_id"]
    b = _create(live_client, staff).json()["student_id"]
    assert a != b


@pytest.mark.parametrize("name", ["", "   ", "x" * 121])
def test_an_empty_or_too_long_name_is_422(live_client, staff, name):
    r = _create(live_client, staff, name)
    assert r.status_code == 422
    assert get_repository().list_ids_for_tenant("acme") == []


def test_a_name_of_120_characters_is_kept(live_client, staff):
    r = _create(live_client, staff, "y" * 120)
    assert r.status_code == 201
    assert r.json()["name"] == "y" * 120


def test_a_missing_name_is_422(live_client, staff):
    r = live_client.post("/students", json={}, headers=staff)
    assert r.status_code == 422


def test_a_student_is_refused(live_client):
    login = live_client.post(
        "/student-auth/login",
        json={"email": "stu@acme.edu", "institution": "acme", "name": "Stu"},
    )
    assert login.status_code == 200, login.text
    h = {"Authorization": f"Bearer {login.json()['token']}"}
    r = _create(live_client, h)
    assert r.status_code == 403
    assert get_repository().get_display_name(login.json()["student_id"]) != "Ada Lovelace"


def test_a_student_principal_token_is_refused(live_client, principal_headers):
    r = _create(live_client, principal_headers("s1", "student", "acme"))
    assert r.status_code == 403
    assert get_repository().list_ids_for_tenant("acme") == []


def test_the_demo_student_role_is_refused(live_client):
    r = _create(live_client, {"x-demo-role": "student"})
    assert r.status_code == 403


def test_anonymous_on_a_real_deploy_is_refused(live_client, pilot_env):
    r = _create(live_client, {})
    assert r.status_code == 401
    assert get_repository().list_ids() == []


def test_staff_on_a_real_deploy_adds_a_writer(live_client, pilot_env, staff):
    r = _create(live_client, staff)
    assert r.status_code == 201, r.text
    assert r.json()["student_id"].startswith("acme:")


def test_the_open_demo_adds_a_writer_to_the_demo_tenant(live_client):
    r = _create(live_client, {})
    assert r.status_code == 201, r.text
    assert re.fullmatch(r"demo:[0-9a-f]{16}", r.json()["student_id"])


def test_another_tenant_cannot_see_or_read_the_writer(live_client, staff, principal_headers):
    sid = _create(live_client, staff).json()["student_id"]
    other = principal_headers("prof-2", "professor", "beta")
    listed = live_client.get("/students", headers=other).json()
    assert sid not in listed["students"]
    assert sid not in {r["id"] for r in listed["roster"]}
    assert live_client.get(f"/students/{sid}", headers=other).status_code == 403
    mine = _create(live_client, other, "Other Writer").json()["student_id"]
    assert mine.startswith("beta:")


def test_a_body_tenant_field_cannot_move_the_writer(live_client, staff):
    r = live_client.post("/students", json={"name": "Ada", "tenant_id": "beta"}, headers=staff)
    assert r.status_code == 201
    assert r.json()["student_id"].startswith("acme:")
    assert get_repository().list_ids_for_tenant("beta") == []


def test_delete_removes_the_writer_and_its_name(live_client, staff):
    sid = _create(live_client, staff).json()["student_id"]
    r = live_client.delete(f"/students/{sid}", headers=staff)
    assert r.status_code == 200, r.text
    repo = get_repository()
    assert repo.get(sid) is None
    assert repo.get_display_name(sid) == ""
    roster = live_client.get("/students", headers=staff).json()["roster"]
    assert sid not in {x["id"] for x in roster}


def test_a_minted_id_already_taken_is_never_reused(live_client, staff, monkeypatch):
    from original.routers import students as students_router

    first = _create(live_client, staff, "First").json()["student_id"]
    draws = iter(["same", "same", "fresh"])
    monkeypatch.setattr(students_router.secrets, "token_hex", lambda n: next(draws))
    monkeypatch.setattr(
        students_router.student_auth,
        "derive_student_id",
        lambda tenant, key: first if key == "same" else f"{tenant}:{'f' * 16}",
    )
    r = _create(live_client, staff, "Second")
    assert r.status_code == 201
    assert r.json()["student_id"] == "acme:" + "f" * 16
    assert get_repository().get_display_name(first) == "First"


@pytest.mark.parametrize(
    "name", ["\x00", "\n", "Ada\x00Lovelace", "Ada\nLovelace", "Ada\tL", "Ada\x7f"]
)
def test_a_name_with_control_characters_is_422_and_creates_nothing(live_client, staff, name):
    r = _create(live_client, staff, name)
    assert r.status_code == 422
    assert get_repository().list_ids_for_tenant("acme") == []


def test_a_name_that_did_not_save_erases_the_writer_and_is_503(live_client, staff, monkeypatch):
    # PostgresRepository.set_display_name logs and swallows a write failure.
    repo = get_repository()
    monkeypatch.setattr(type(repo), "set_display_name", lambda self, sid, name: None)
    r = _create(live_client, staff)
    assert r.status_code == 503
    assert "Nothing was added" in r.json()["detail"]
    assert repo.list_ids_for_tenant("acme") == []
    assert live_client.get("/students", headers=staff).json()["roster"] == []


@pytest.mark.parametrize("tenant", ["", "Not A Slug"])
def test_a_principal_without_a_usable_tenant_is_400(live_client, principal_headers, tenant):
    r = _create(live_client, principal_headers("prof-x", "professor", tenant))
    assert r.status_code == 400
    assert r.json()["detail"] == "Your account has no workspace to add a writer to."
    assert get_repository().list_ids() == []
