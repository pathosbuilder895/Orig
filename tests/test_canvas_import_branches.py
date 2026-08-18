"""
Branch tests for original/routers/imports.py's Canvas baseline-import surface
(import_canvas_baseline, fetch_canvas_submission_text) — part 2 task 6.

No real network: original.canvas.live_import.make_client /
fetch_submissions / get_submission_text are monkeypatched (the module's own
documented seams — see live_import.make_client's docstring: "Single seam for
tests to monkeypatch"). canvas_url/access_token are always supplied in the
request body so these tests don't depend on CANVAS_BASE_URL/CANVAS_API_TOKEN
being unset in the ambient environment (that config-absent 400 path is
already covered by tests/test_imports_api_coverage.py::
test_canvas_baseline_routes_require_configuration).

Turnitin CSV import (a separate handler in the same file) already has full
branch coverage via tests/test_imports_api_coverage.py — not touched here.
"""

from __future__ import annotations

import original.canvas.live_import as canvas_live

BASELINE = "/students/{sid}/baseline"
IMPORT = "/canvas/baseline/{sid}/import-baseline"
LIST = "/canvas/baseline/{sid}/list-canvas-submissions"
FETCH_TEXT = "/canvas/baseline/{sid}/fetch-submission-text"

CONFIG = {"canvas_url": "https://fake.instructure.com", "access_token": "fake-token"}

# Reused from tests/test_students_baseline_batch.py's drift-gate fixture
# texts (same U1/U2/U3 + OUTLIER_TEXT pattern, verified empirically there to
# trip StudentState.check_drift's 0.30 magnitude threshold on tiers 4/6).
U1 = (
    "The doctrine of vocation situates daily labor within a larger account of providence. "
    "Faithful work in an ordinary calling honors the same God who ordained the extraordinary. "
    "Scripture repeatedly affirms that diligence in one's station is itself a form of worship. "
) * 15
U2 = (
    "Systematic theology proceeds by careful attention to the whole counsel of Scripture. "
    "Each doctrine must be weighed against the entire canon rather than isolated proof texts. "
    "The task requires patience, humility, and a willingness to be corrected by the text. "
) * 15
U3 = (
    "Pastoral ministry demands both doctrinal precision and genuine compassion for the flock. "
    "A shepherd who neglects sound teaching fails his people as surely as one lacking mercy. "
    "The two callings, teaching and caring, are never rightly separated in faithful practice. "
) * 15
OUTLIER_TEXT = (
    "OMG!!! ur baseline thing is SOOO weird lol -- like, \"whatever\" (i guess); "
    "idk, u know?? c'mon -- don't u think so; totally, right?! "
    "e.g. this ain't gonna work; i.e. it's kinda broken -- (maybe) \"who knows\"; "
) * 15

# >= canvas_live.MIN_WORDS (50) so it's never skipped as "too short" on its own.
GOOD_SUBMISSION_TEXT = "A perfectly ordinary Canvas submission with enough words. " * 12


class _FakeAsyncClient:
    """Stands in for the httpx.AsyncClient `async with ... as client:` block.
    Never used for a real request — fetch_submissions/get_submission_text are
    monkeypatched below to not touch it."""

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        return False


def _stub_canvas(monkeypatch, submissions, texts):
    """submissions: list of Canvas submission dicts (must include 'id').
    texts: dict {submission_id: text_or_None} returned by get_submission_text."""
    monkeypatch.setattr(canvas_live, "make_client", lambda: _FakeAsyncClient())

    async def _fetch_submissions(
        client, canvas_url, access_token, course_id, user_id, submission_ids=None
    ):
        if submission_ids:
            wanted = set(submission_ids)
            return [s for s in submissions if str(s.get("id", "")) in wanted]
        return list(submissions)

    async def _get_submission_text(sub, access_token, client):
        return texts.get(str(sub.get("id", "")))

    monkeypatch.setattr(canvas_live, "fetch_submissions", _fetch_submissions)
    monkeypatch.setattr(canvas_live, "get_submission_text", _get_submission_text)


def _add_baseline(client, sid, text, provenance="verified"):
    return client.post(
        BASELINE.format(sid=sid),
        json={"text": text, "provenance": provenance, "assignment": ""},
    )


# ── import_canvas_baseline ───────────────────────────────────────────────────


def test_import_rejects_empty_submission_ids(live_client, store_reset, monkeypatch):
    _stub_canvas(monkeypatch, submissions=[], texts={})
    r = live_client.post(
        IMPORT.format(sid="canvas-empty-ids"),
        json={**CONFIG, "canvas_course_id": "c1", "canvas_user_id": "u1"},
    )
    assert r.status_code == 422, r.text
    assert "submission_ids" in r.json()["detail"]


def test_import_skips_submission_under_min_words(live_client, store_reset, monkeypatch):
    """A fetched submission whose text is too short (or None) is counted as
    skipped, not imported and not an error."""
    _stub_canvas(
        monkeypatch,
        submissions=[{"id": "101", "submission_type": "online_text_entry"}],
        texts={"101": "too short"},  # well under MIN_WORDS (50)
    )
    r = live_client.post(
        IMPORT.format(sid="canvas-short"),
        json={
            **CONFIG,
            "canvas_course_id": "c1",
            "canvas_user_id": "u1",
            "submission_ids": ["101"],
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["imported"] == 0
    assert body["skipped"] == 1
    assert body["drift_holds"] == []


def test_import_holds_a_drifted_submission_instead_of_importing(
    live_client, store_reset, monkeypatch
):
    """Three stylistically-uniform authenticated baselines establish a
    baseline_mean; a wildly different Canvas submission trips check_drift
    (magnitude > 0.30) and is recorded in drift_holds instead of being
    imported — the False-arm complement of AUTH_WEIGHTS[provenance] > 0
    (canvas's weight is 0.8, so the drift check always runs for this
    provenance; see the docstring note below on the True/False split)."""
    sid = "canvas-drift"
    for text in (U1, U2, U3):
        assert _add_baseline(live_client, sid, text).status_code == 200

    _stub_canvas(
        monkeypatch,
        submissions=[{"id": "202", "submission_type": "online_text_entry"}],
        texts={"202": OUTLIER_TEXT},
    )
    r = live_client.post(
        IMPORT.format(sid=sid),
        json={
            **CONFIG,
            "canvas_course_id": "c1",
            "canvas_user_id": "u1",
            "submission_ids": ["202"],
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["imported"] == 0
    assert len(body["drift_holds"]) == 1
    assert body["drift_holds"][0]["canvas_submission_id"] == "202"
    assert body["drift_holds"][0]["drift"]["recommendation"] in ("flag_for_review", "rebaseline")


def test_import_happy_path_stores_the_sample(live_client, store_reset, monkeypatch):
    """Sanity check the success arm too, so the three failure/edge arms above
    aren't the only thing exercising this handler."""
    sid = "canvas-happy"
    _stub_canvas(
        monkeypatch,
        submissions=[{"id": "303", "submission_type": "online_text_entry"}],
        texts={"303": GOOD_SUBMISSION_TEXT},
    )
    r = live_client.post(
        IMPORT.format(sid=sid),
        json={
            **CONFIG,
            "canvas_course_id": "c1",
            "canvas_user_id": "u1",
            "submission_ids": ["303"],
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["imported"] == 1
    assert body["provenance"] == "canvas"


# ── fetch_canvas_submission_text ─────────────────────────────────────────────


def test_fetch_text_rejects_missing_submission_id(live_client, store_reset, monkeypatch):
    _stub_canvas(monkeypatch, submissions=[], texts={})
    r = live_client.post(
        FETCH_TEXT.format(sid="canvas-fetch-missing-id"),
        json={**CONFIG, "canvas_course_id": "c1", "canvas_user_id": "u1"},
    )
    assert r.status_code == 422, r.text
    assert "canvas_submission_id" in r.json()["detail"]


def test_fetch_text_404s_when_submission_not_in_canvas_response(
    live_client, store_reset, monkeypatch
):
    _stub_canvas(monkeypatch, submissions=[], texts={})  # fetch_submissions returns []
    r = live_client.post(
        FETCH_TEXT.format(sid="canvas-fetch-404"),
        json={
            **CONFIG,
            "canvas_course_id": "c1",
            "canvas_user_id": "u1",
            "canvas_submission_id": "does-not-exist",
        },
    )
    assert r.status_code == 404, r.text
    assert "does-not-exist" in r.json()["detail"]


def test_fetch_text_happy_path(live_client, store_reset, monkeypatch):
    _stub_canvas(
        monkeypatch,
        submissions=[{"id": "404", "submission_type": "online_text_entry"}],
        texts={"404": GOOD_SUBMISSION_TEXT},
    )
    r = live_client.post(
        FETCH_TEXT.format(sid="canvas-fetch-ok"),
        json={
            **CONFIG,
            "canvas_course_id": "c1",
            "canvas_user_id": "u1",
            "canvas_submission_id": "404",
        },
    )
    assert r.status_code == 200, r.text
    assert r.json()["text"] == GOOD_SUBMISSION_TEXT


# ── students_baseline._existing_text_hashes' missing-student arm ────────────
# Deferred from an earlier task: only reachable via imports.py, since
# import_canvas_baseline always get_or_create()s the student BEFORE calling
# _existing_text_hashes (so `state is None` can never be true from that call
# site), but list_canvas_submissions calls it directly on a student_id it has
# never created.


def test_list_canvas_submissions_for_a_never_seen_student(live_client, store_reset, monkeypatch):
    _stub_canvas(
        monkeypatch,
        submissions=[{"id": "505", "submission_type": "online_text_entry"}],
        texts={"505": GOOD_SUBMISSION_TEXT},
    )
    r = live_client.post(
        LIST.format(sid="canvas-never-seen-student"),
        json={**CONFIG, "canvas_course_id": "c1", "canvas_user_id": "u1"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total"] == 1
    # No prior baseline for this student → nothing can be "already_imported".
    assert body["submissions"][0]["already_imported"] is False
