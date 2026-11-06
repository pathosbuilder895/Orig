"""Text font and size (2026-11): each signed-in account keeps its own
display choice on the server, readable only by its owner, limited to known
values, and deleted with the student's data. Display only."""

from __future__ import annotations

import pytest

from original.repository import get_repository
from tests.alpha.test_past_papers import _fresh, _ok, _workspace  # noqa: F401  (autouse fixture)

URL = "/bluebook/me/display"


@pytest.mark.slow
def test_display_prefs_round_trip_owner_only(live_client):
    T, [(sid, S), _] = _workspace(live_client, "disp1@example.test")
    assert _ok(live_client.get(URL, headers=T))["display"] is None
    _ok(live_client.put(URL, json={"font": "readable", "size": "xlarge"}, headers=T))
    assert _ok(live_client.get(URL, headers=T))["display"] == {"font": "readable", "size": "xlarge"}
    _ok(live_client.put(URL, json={"font": "sans", "size": "large"}, headers=T))
    assert _ok(live_client.get(URL, headers=T))["display"] == {"font": "sans", "size": "large"}
    # The student has their own, separate setting.
    assert _ok(live_client.get(URL, headers=S))["display"] is None
    _ok(live_client.put(URL, json={"font": "classic", "size": "small"}, headers=S))
    assert _ok(live_client.get(URL, headers=S))["display"]["font"] == "classic"
    assert _ok(live_client.get(URL, headers=T))["display"]["font"] == "sans"
    # Not signed in: refused.
    assert live_client.get(URL).status_code in (401, 403)
    assert live_client.put(URL, json={"font": "sans", "size": "large"}).status_code in (401, 403)


@pytest.mark.slow
def test_unknown_values_refused(live_client):
    T, _ = _workspace(live_client, "disp2@example.test", n_students=1)
    for body in (
        {},
        {"font": "comic", "size": "large"},
        {"font": "sans", "size": "huge"},
        {"font": "sans"},
        {"size": "large"},
        {"font": 1, "size": "large"},
    ):
        assert live_client.put(URL, json=body, headers=T).status_code == 422, body


@pytest.mark.slow
def test_withdrawal_deletes_display_prefs(live_client):
    T, [(sid, S), _] = _workspace(live_client, "disp3@example.test")
    _ok(live_client.put(URL, json={"font": "readable", "size": "large"}, headers=S))
    assert get_repository().get_display_prefs(sid)
    get_repository().delete_student(sid)
    assert get_repository().get_display_prefs(sid) is None
