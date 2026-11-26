"""The audit log names who acted, never the network address they acted from.

The privacy policy (demo/legal/privacy.html) says no IP address is stored in
the database. `audit_log` has no IP column, but DELETE /students/{id} used to
write `request.client.host` into its `actor` field. It now records the staff
account that made the request (or "demo" for the anonymous demo sandbox).
"""

from __future__ import annotations

import ipaddress

from original import store

LONG_TEXT = " ".join(["Augustine writes of memory and the restless heart."] * 30)


def _actors(student_id: str) -> list[str]:
    with store._get_conn() as conn:
        rows = conn.execute(
            "SELECT actor FROM audit_log WHERE student_id = ? AND action = 'student_delete'",
            (student_id,),
        ).fetchall()
    return [r[0] for r in rows]


def _is_ip(value: str) -> bool:
    try:
        ipaddress.ip_address(value)
        return True
    except ValueError:
        return value in {"testclient", "unknown"}  # the test client's stand-in host


def test_a_deletion_receipt_names_an_actor_not_an_address(live_client, store_reset):
    sid = "auditip_del"
    r = live_client.post(f"/students/{sid}/baseline", json={"text": LONG_TEXT, "assignment": "a1"})
    assert r.status_code == 200, r.text
    assert live_client.delete(f"/students/{sid}").status_code == 200
    actors = _actors(sid)
    assert actors and not any(_is_ip(a) for a in actors), actors


def test_a_refused_deletion_names_an_actor_not_an_address(live_client, store_reset):
    sid = "auditip_missing"
    assert live_client.delete(f"/students/{sid}").status_code == 404
    actors = _actors(sid)
    assert actors and not any(_is_ip(a) for a in actors), actors
