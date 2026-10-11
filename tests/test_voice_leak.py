"""
ADR-005 leak-test gate — the permanent guarantee that the student read-model
never carries surveillance internals on the wire.

Three layers of defence:
  1. Unit: drive original.voice projections with deliberately adversarial raw
     inputs (real feature codes, raw divergence scores, action enums, formation
     reasons) and assert NONE of them survive into the projected output.
  2. Integration: sign in as a student, hit /me/voice and /me/work, and assert
     the serialized payloads contain no forbidden token. Also proves the
     self-only authorization (a student cannot read a classmate via /students).
  3. Static HTML: scan demo/student.html itself for surveillance words in
     user-visible text nodes (not CSS class names, not JS variable names),
     so the first-paint render before any data fetch is also clean.
"""

import ast
import json
import pathlib
import re
import uuid

import pytest
from fastapi.testclient import TestClient

import run
from original import voice as voice_mod
from original import principal as pr
from original.constants import ALL_FEATURE_CODES

app = run.load_legacy_demo_app()
client = TestClient(app)

LONG_TEXT = (
    "Grace and peace are the twin notes that open nearly every Pauline letter, "
    "and their repetition is not accidental but theological. The writer returns "
    "again and again to the same vocabulary, the same cadence, the same habit of "
    "qualifying a bold claim with a gentle clause. Across a semester these habits "
    "compound into a recognizable voice, and it is that voice, not any single "
    "sentence, that the system learns to know and to defend with care and patience. "
    "The argument unfolds in stages, each one resting on the last, until the "
    "conclusion arrives less as a surprise than as something already half-known."
)

# ── Positive contract: the keys VoiceView and VoiceSubmitResult are allowed
# to expose. Anything NOT in these sets is a leak by construction.
#
# This is a stronger guarantee than the old substring scan because it can't
# false-negative (a new forbidden field can't slip in unnamed) and can't
# false-positive (instructor prose containing the word "manifest" no longer
# breaks CI).
#
# When project_voice_view or project_submission_result legitimately grows a
# new top-level key, add it here in the same commit. That's the design — the
# allow-list IS the contract.
ALLOWED_VOICE_VIEW_KEYS = frozenset(
    {
        "name",
        "headline",
        "subhead",
        "fingerprint",
        "fingerprint.name",
        "fingerprint.value",
        "arc",
        "arc.period",
        "arc.fidelity",
        "arc.attention",
        "voice_notes",
        "voice_notes.note",
        "voice_notes.reviewer",
        "voice_notes.date",
        "review_opportunities",
        "review_opportunities.invitation_prose",
        "review_opportunities.locator",
        "milestones",
        "milestones.label",
        "milestones.state",
        "milestones.blurb",
        "formation",
        "formation.active",
        "formation.status",
        "formation.current_step",
        "formation.total_steps",
        "formation.step_label",
        "formation.supportive_copy",
    }
)

ALLOWED_SUBMIT_RESULT_KEYS = frozenset(
    {
        "headline",
        "summary",
        "steady",
        "review_opportunity",
    }
)

# The substring scan is RETAINED as a secondary defence — it catches values
# (not just keys) that look like surveillance internals. Tightly scoped so
# legitimate prose can use the natural English words (e.g. "manifest itself").
# Each entry is matched against the VALUE strings only, not key names.
FORBIDDEN_VALUE_FRAGMENTS = [
    "divergence_score",
    "deviation_score",
    "baseline_vector",
    "feature_vector",
    "no_action",
    "schedule_conversation",
    "human_explanation",
    "auth_weight",
]


def _walk_keys(blob, prefix: str = ""):
    """Yield every dotted key path that appears in a nested dict/list blob."""
    if isinstance(blob, dict):
        for k, v in blob.items():
            yield f"{prefix}.{k}" if prefix else k
            yield from _walk_keys(v, k)
    elif isinstance(blob, list):
        for item in blob:
            yield from _walk_keys(item, prefix)


def _walk_values(blob):
    """Yield every string value (recursively) in a nested dict/list blob."""
    if isinstance(blob, dict):
        for v in blob.values():
            yield from _walk_values(v)
    elif isinstance(blob, list):
        for item in blob:
            yield from _walk_values(item)
    elif isinstance(blob, str):
        yield blob


def _assert_keys_in(blob, allowed: frozenset, label: str) -> None:
    """The primary contract — every key in `blob` must be in the allow-list."""
    for path in _walk_keys(blob):
        assert path in allowed, (
            f"{label}: unexpected key {path!r} (not in the allow-list — "
            f"either redact it, or add it to ALLOWED_*_KEYS in the same commit)"
        )


def _assert_values_clean(blob) -> None:
    """Belt-and-suspenders — value strings can't contain surveillance fragments."""
    for value in _walk_values(blob):
        v = value.lower()
        for bad in FORBIDDEN_VALUE_FRAGMENTS:
            assert bad not in v, f"forbidden fragment {bad!r} found in value {value!r}"
        for code in ALL_FEATURE_CODES:
            assert code not in v, f"feature code {code!r} leaked into value {value!r}"


def _assert_voice_view_clean(blob) -> None:
    _assert_keys_in(blob, ALLOWED_VOICE_VIEW_KEYS, "VoiceView")
    _assert_values_clean(blob)


def _assert_submit_result_clean(blob) -> None:
    _assert_keys_in(blob, ALLOWED_SUBMIT_RESULT_KEYS, "VoiceSubmitResult")
    _assert_values_clean(blob)


# Back-compat alias for any external callers that imported the old name.
_assert_clean = _assert_voice_view_clean


# ── Unit: projection redacts adversarial raw inputs ──────────────────────────


def test_projection_drops_feature_codes_and_scores():
    # A baseline vector keyed by the REAL feature codes, with raw scores.
    baseline = {code: 0.6 for code in ALL_FEATURE_CODES}
    manifests = [
        {
            "submission_id": "s2",
            "created_at": "2025-11-14T00:00:00",
            "divergence_score": 0.61,
            "action": "schedule_conversation",
        },
        {
            "submission_id": "s1",
            "created_at": "2025-10-09T00:00:00",
            "divergence_score": 0.12,
            "action": "no_action",
        },
    ]
    corrections = [
        {
            "notes": "Your handling of apophatic language is genuinely your own now.",
            "reviewer": "Dr. Pemberton",
            "created_at": "2025-12-18T00:00:00",
            "original_divergence_score": 0.61,
            "original_action": "schedule_conversation",
        },
    ]
    pathway = {
        "current_step": 1,
        "total_steps": 3,
        "status": "open",
        "reason": "voice divergence",
        "submission_id": "s2",
    }

    view = voice_mod.project_voice_view(
        name="Thomas Merton",
        baseline_vector=baseline,
        sample_count=5,
        approved_count=2,
        manifests=manifests,
        corrections=corrections,
        pathway=pathway,
    )
    _assert_voice_view_clean(view)

    # The shape is still useful: 7 blended dimensions, an ascending arc, a note.
    assert len(view["fingerprint"]) == 7
    assert [p["fidelity"] for p in view["arc"]] == [88, 39]  # oldest→newest, resolved
    assert view["arc"][1]["attention"] is True  # the flagged piece
    assert view["voice_notes"][0]["reviewer"] == "Dr. Pemberton"
    assert view["review_opportunities"], "a flagged manifest should invite a conversation"
    assert view["formation"]["current_step"] == 1


def test_submission_result_redaction():
    # A raw-ish Layer-7 dict with an action enum + constructive feature codes.
    layer7 = {
        "recommendation": {"action": "monitor"},
        "authorship": {"deviation_score": 0.52},
        "interference": {
            "constructive_features": [
                {"code": "type_token_ratio", "name": "Type-token ratio"},
                {"code": "burstiness", "name": "Burstiness"},
            ]
        },
        "human_explanation": {"summary": "deviation score 0.52; anomalies detected"},
    }
    res = voice_mod.project_submission_result(layer7, "Thomas Merton")
    _assert_submit_result_clean(res)
    assert res["review_opportunity"] is True
    assert res["steady"], "constructive features should surface as steady dimensions"


# ── Unit: remaining branch arms in the pure projection helpers ───────────────
# (p3-task-4 support-module branch-coverage sweep — not new leak-contract
# assertions, just table-driven coverage of arms the redaction tests above
# don't happen to exercise.)


def test_clamp01_clamps_both_directions():
    assert voice_mod._clamp01(-0.5) == 0.0
    assert voice_mod._clamp01(1.5) == 1.0
    assert voice_mod._clamp01(0.5) == 0.5


def test_short_period_handles_falsy_input():
    assert voice_mod._short_period(None) == ""
    assert voice_mod._short_period("") == ""
    assert voice_mod._short_period("2025-10-09T00:00:00") == "2025-10-09"


def test_project_voice_notes_skips_blank_note():
    corrections = [
        {"notes": "   ", "reviewer": "Dr. X", "created_at": "2025-10-09T00:00:00"},
        {"notes": "Good work.", "reviewer": "Dr. Y", "created_at": "2025-10-10T00:00:00"},
    ]
    notes = voice_mod.project_voice_notes(corrections)
    assert len(notes) == 1
    assert notes[0]["note"] == "Good work."


def test_project_review_opportunities_skips_no_action_then_returns():
    manifests = [
        {"action": "no_action", "created_at": "2025-10-09T00:00:00"},
        {"action": "monitor", "created_at": "2025-10-10T00:00:00"},
    ]
    opp = voice_mod.project_review_opportunities(manifests)
    assert len(opp) == 1
    assert opp[0]["locator"] == "2025-10-10"


def test_project_headline_growth_bands():
    # grew_by >= 8 -> "strengthened" band
    arc_up = [{"fidelity": 40}, {"fidelity": 50}]
    head = voice_mod.project_headline("Dana", arc_up)
    assert "strengthened" in head["headline"]
    assert "up 10 since" in head["subhead"]

    # -8 < grew_by < 8 -> the "settling" else band, and grew_by > 0 still
    # appends the "up N" clause.
    arc_settle = [{"fidelity": 50}, {"fidelity": 53}]
    head2 = voice_mod.project_headline("Dana", arc_settle)
    assert "settling" in head2["headline"]
    assert "up 3 since" in head2["subhead"]


def test_project_headline_addresses_a_named_student_and_not_a_nameless_one():
    assert voice_mod.project_headline("Dana Whitfield", [])["headline"] == (
        "Dana, your voice is finding its shape."
    )
    # No name on file: never "Your, your voice".
    for blank in ("", "   ", None):
        head = voice_mod.project_headline(blank, [])
        assert head["headline"] == "Your voice is finding its shape."
    assert voice_mod.project_headline("", [{"fidelity": 40}, {"fidelity": 50}])["headline"] == (
        "Your voice strengthened across this term."
    )
    # With nothing drawn yet, the subhead says where a profile comes from.
    assert "teacher approves" in voice_mod.project_headline("Dana", [])["subhead"]


def test_project_submission_result_handles_missing_recommendation_and_interference():
    # No "recommendation"/"interference" keys at all: the internal `_get`
    # helper must resolve `obj=None` for those lookups rather than raising.
    layer7 = {"authorship": {"deviation_score": 0.1}}
    res = voice_mod.project_submission_result(layer7, "Dana")
    assert res["headline"] == "This reads like you."
    assert res["steady"] == []


def test_project_submission_result_escalate_uses_the_else_branch():
    layer7 = {
        "recommendation": {"action": "escalate"},
        "authorship": {"deviation_score": 0.9},
        "interference": {"constructive_features": []},
    }
    res = voice_mod.project_submission_result(layer7, "Dana")
    assert res["headline"] == "Some passages here read differently from your voice."
    assert res["review_opportunity"] is True


def test_project_submission_result_stops_after_three_steady_dimensions():
    # 4 distinct-dimension constructive features: steady_dims must cap at 3
    # and `break`, never reaching the 4th (Register) dimension.
    constructive = [
        {"code": "mean_sentence_length"},  # Cadence
        {"code": "type_token_ratio"},  # Diction
        {"code": "punctuation_diversity"},  # Texture
        {"code": "theological_register_score"},  # Register — must not be reached
    ]
    layer7 = {
        "recommendation": {"action": "monitor"},
        "interference": {"constructive_features": constructive},
    }
    res = voice_mod.project_submission_result(layer7, "Dana")
    assert len(res["steady"]) == 3
    assert not any("register" in s.lower() for s in res["steady"])


# ── Integration: live endpoints over a signed-in student ─────────────────────


@pytest.fixture(scope="module")
def student_token():
    r = client.post(
        "/student-auth/login",
        json={
            "email": "merton@gethsemani.edu",
            "institution": "Gethsemani Demo",
            "name": "Thomas Merton",
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    tok = body["token"]
    sid = body["student_id"]
    hdr = {"Authorization": f"Bearer {tok}"}
    # Seed two authenticated baselines so scoring is possible.
    for i in range(2):
        rr = client.post(
            f"/students/{sid}/baseline",
            json={"text": LONG_TEXT, "assignment": f"a{i}", "provenance": "verified"},
            headers=hdr,
        )
        assert rr.status_code == 200, rr.text
    return tok, sid


def test_me_voice_requires_auth():
    assert client.get("/me/voice").status_code == 401


def test_me_voice_is_clean(student_token):
    tok, _sid = student_token
    r = client.get("/me/voice", headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 200, r.text
    _assert_voice_view_clean(r.json())
    assert len(r.json()["fingerprint"]) == 7


def test_me_work_is_clean(student_token):
    tok, _sid = student_token
    r = client.post(
        "/me/work",
        headers={"Authorization": f"Bearer {tok}"},
        json={"text": LONG_TEXT, "title": "Conscience & Formation"},
    )
    assert r.status_code == 200, r.text
    _assert_submit_result_clean(r.json())


def test_me_work_leaves_the_students_sample_count_unchanged(student_token):
    """/me/work compares only: the piece never joins the baseline (NORTH_STAR
    rule 8, only teacher-approved writing becomes baseline)."""
    tok, sid = student_token
    hdr = {"Authorization": f"Bearer {tok}"}
    before = client.get(f"/students/{sid}", headers=hdr).json()

    for _ in range(2):
        r = client.post(
            "/me/work",
            headers=hdr,
            json={"text": LONG_TEXT, "title": "A piece to compare"},
        )
        assert r.status_code == 200, r.text
        _assert_submit_result_clean(r.json())

    after = client.get(f"/students/{sid}", headers=hdr).json()
    # (The student may already hold more than the fixture's two samples when
    # another module shares the store; what matters is that nothing was added.)
    assert before["sample_count"] >= 2
    assert after["sample_count"] == before["sample_count"]
    assert after["authenticated_count"] == before["authenticated_count"]
    assert len(after["samples"]) == len(before["samples"])


def test_student_cannot_read_a_classmate(student_token):
    """Self-only authz: a student token cannot read another student's record."""
    tok, sid = student_token
    # Same tenant, different student id.
    tenant = sid.split(":", 1)[0]
    other = f"{tenant}:someone-else"
    r = client.get(f"/students/{other}", headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 403, r.text


def test_student_cannot_probe_other_tenant_existence(student_token):
    """A student token must not be able to enumerate students in OTHER tenants.

    If the authz check is "is this my student id?", a request for any
    nonexistent id under a foreign tenant must STILL return 403, not 404 —
    otherwise the response code differentiates "tenant exists but you can't
    see it" from "tenant doesn't exist", which is itself an information leak.
    """
    tok, _sid = student_token
    foreign_tenant_id = "some-other-school:any-student-id"
    r = client.get(
        f"/students/{foreign_tenant_id}",
        headers={"Authorization": f"Bearer {tok}"},
    )
    assert r.status_code == 403, (
        f"expected 403 to keep cross-tenant existence unleakable; "
        f"got {r.status_code} (body: {r.text!r})"
    )


def test_student_can_still_read_self(student_token):
    """The self-only rule must not break a student reading their own record."""
    tok, sid = student_token
    r = client.get(f"/students/{sid}", headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 200, r.text


# ── Voice Affirmed: a piece a teacher approved is on file ────────────────────
# A student's own upload counts toward the baseline (authenticated_count, at half
# weight) but a student cannot approve their own writing, so it does not affirm a
# voice. Only the trusted provenances do: a supervised sitting (proctored), a
# teacher-verified paper (verified) or a course-site import (canvas).


def _milestone_states(sample_count, approved_count, pathway=None):
    view = voice_mod.project_voice_view(
        name="Dana",
        baseline_vector={},
        sample_count=sample_count,
        approved_count=approved_count,
        manifests=[],
        corrections=[],
        pathway=pathway,
    )
    return {m["label"]: m["state"] for m in view["milestones"]}


def test_voice_affirmed_follows_an_approved_piece_and_never_a_finished_pathway():
    done = {"current_step": 3, "total_steps": 3, "status": "completed"}
    upcoming = {"Voice Sampled": "upcoming", "Voice Established": "upcoming", "Voice Affirmed": "upcoming"}
    assert _milestone_states(0, 0) == upcoming
    # A completed pathway used to affirm a voice with nothing on file.
    assert _milestone_states(0, 0, done) == upcoming
    # One approved piece: sampled and affirmed, not yet established.
    assert _milestone_states(1, 1) == {
        "Voice Sampled": "reached",
        "Voice Established": "upcoming",
        "Voice Affirmed": "reached",
    }
    assert _milestone_states(3, 3) == {
        "Voice Sampled": "reached",
        "Voice Established": "reached",
        "Voice Affirmed": "reached",
    }
    # Writing a student uploaded themselves is on file but not approved: it can
    # sample and establish a voice, never affirm it.
    assert _milestone_states(1, 0) == {
        "Voice Sampled": "reached",
        "Voice Established": "upcoming",
        "Voice Affirmed": "upcoming",
    }
    assert _milestone_states(4, 0)["Voice Established"] == "reached"
    assert _milestone_states(4, 0)["Voice Affirmed"] == "upcoming"
    # One approved piece among the student's own uploads is enough.
    assert _milestone_states(4, 1)["Voice Affirmed"] == "reached"


def test_voice_affirmed_blurb_says_a_teacher_approved_the_piece_and_claims_nothing_more():
    blurbs = {m["label"]: m["blurb"] for m in voice_mod.project_milestones(1, 1)}
    assert blurbs["Voice Affirmed"] == "A piece your teacher approved is on file."
    said = blurbs["Voice Affirmed"].lower()
    for claim in ("genuine", "verified", "authentic", "reference writing"):
        assert claim not in said, claim


def test_me_route_counts_approved_pieces_from_the_trusted_provenances_it_imports():
    # One definition of "trusted": the router imports it, so a provenance added to
    # the set later is approved here too, and a copy cannot drift.
    from original.routers import _shared, me

    assert me._TRUSTED_PROVENANCE is _shared._TRUSTED_PROVENANCE
    assert _shared._TRUSTED_PROVENANCE == {"proctored", "verified", "canvas"}


def _affirmed_state(token):
    r = client.get("/me/voice", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200, r.text
    return {m["label"]: m["state"] for m in r.json()["milestones"]}


@pytest.fixture
def fresh_student():
    """A student who has signed in and written nothing yet (a new one every test)."""
    r = client.post(
        "/student-auth/login",
        json={
            "email": f"dana-{uuid.uuid4().hex[:10]}@gethsemani.edu",
            "institution": "Gethsemani Demo",
            "name": "Dana Test",
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    return body["token"], body["student_id"]


def test_me_voice_does_not_affirm_a_voice_from_the_students_own_upload(fresh_student):
    """The reachable state: a student POSTs their own piece (asking for 'verified',
    which the server downgrades to 'unverified'). It counts toward the baseline, and
    Voice Affirmed stays upcoming."""
    tok, sid = fresh_student
    hdr = {"Authorization": f"Bearer {tok}"}
    r = client.post(
        f"/students/{sid}/baseline",
        json={"text": LONG_TEXT, "assignment": "my own upload", "provenance": "verified"},
        headers=hdr,
    )
    assert r.status_code == 200, r.text
    assert r.json()["provenance"] == "unverified"
    record = client.get(f"/students/{sid}", headers=hdr).json()
    assert record["authenticated_count"] == 1  # it counts toward the baseline...
    assert [s["provenance"] for s in record["samples"]] == ["unverified"]
    states = _affirmed_state(tok)
    assert states["Voice Sampled"] == "reached"
    assert states["Voice Affirmed"] == "upcoming"  # ...and does not affirm the voice


@pytest.mark.parametrize("provenance", ["proctored", "verified", "canvas"])
def test_me_voice_affirms_a_voice_once_a_teacher_approved_piece_is_on_file(fresh_student, provenance):
    tok, sid = fresh_student
    hdr = {"Authorization": f"Bearer {tok}"}
    client.post(
        f"/students/{sid}/baseline",
        json={"text": LONG_TEXT, "assignment": "my own upload", "provenance": "unverified"},
        headers=hdr,
    )
    assert _affirmed_state(tok)["Voice Affirmed"] == "upcoming"
    # The demo's anonymous principal stands in for the teacher or the supervised
    # sitting: off a real deploy it keeps the provenance it asks for.
    r = client.post(
        f"/students/{sid}/baseline",
        json={"text": LONG_TEXT + " It ends here.", "assignment": "approved", "provenance": provenance},
    )
    assert r.status_code == 200, r.text
    assert r.json()["provenance"] == provenance
    assert _affirmed_state(tok)["Voice Affirmed"] == "reached"


# ── Student-facing copy never says "formation" ───────────────────────────────
# Owner decision 2026-10-09: the student pages do not use "formation" wording
# (the pathway is still a feature; the word is not copy). Two nets, so neither a
# new branch nor a new string slips past: every string literal in the two
# modules that is not a docstring, and every string value the projections
# actually return, across every state they can be in.

STUDENT_COPY_MODULES = ("voice.py", "routers/me.py")
# Not copy: the VoiceView key name (the API contract) and route paths.
NOT_COPY = {"formation"}


def _copy_literals(path: pathlib.Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            body = node.body
            if body and isinstance(body[0], ast.Expr) and isinstance(
                getattr(body[0], "value", None), ast.Constant
            ):
                docstrings.add(id(body[0].value))
    return [
        n.value
        for n in ast.walk(tree)
        if isinstance(n, ast.Constant)
        and isinstance(n.value, str)
        and id(n) not in docstrings
        and n.value not in NOT_COPY
        and not n.value.startswith("/")
    ]


@pytest.mark.parametrize("module", STUDENT_COPY_MODULES)
def test_no_string_literal_in_the_student_modules_says_formation(module):
    path = REPO_ROOT_FOR_COPY / "original" / module
    found = [t for t in _copy_literals(path) if "formation" in t.lower()]
    assert not found, f"original/{module} has student-facing copy with 'formation': {found}"
    # Nor with "tutor" (the student's word is "teacher") or an em dash.
    dashes = chr(0x2014) + chr(0x2015)
    found = [t for t in _copy_literals(path) if "tutor" in t.lower() or any(d in t for d in dashes)]
    assert not found, f"original/{module} has student-facing copy with 'tutor' or an em dash: {found}"


REPO_ROOT_FOR_COPY = pathlib.Path(__file__).resolve().parent.parent


def test_no_returned_string_says_formation_in_any_state():
    # Every pathway state, every score action, with and without a baseline.
    pathways = [
        None,
        {"current_step": 0, "total_steps": 3, "status": "open"},
        {"current_step": 1, "total_steps": 3, "status": "open"},
        {"current_step": 2, "total_steps": 3, "status": "open"},
        {"current_step": 3, "total_steps": 3, "status": "completed"},
    ]
    views = []
    for pathway in pathways:
        for samples, auth in ((0, 0), (1, 0), (3, 0), (3, 1)):
            for manifests in ([], [{"created_at": "2026-01-01T00:00:00", "action": "monitor",
                                    "divergence_score": 0.4}]):
                views.append(
                    voice_mod.project_voice_view(
                        name="Dana Whitfield",
                        baseline_vector={code: 0.5 for code in ALL_FEATURE_CODES},
                        sample_count=samples,
                        approved_count=auth,
                        manifests=manifests,
                        corrections=[],
                        pathway=pathway,
                    )
                )
    results = [voice_mod.project_no_baseline_result()]
    for action in ("no_action", "monitor", "schedule_conversation", "escalate"):
        layer7 = {
            "recommendation": {"action": action},
            "interference": {"constructive_features": [{"code": "burstiness"}]},
        }
        results.append(voice_mod.project_submission_result(layer7, "Dana"))

    # Growth in the Arc changes the subhead; a note with no reviewer gets the default.
    for first, last in ((40, 60), (60, 40), (50, 51)):
        manifests = [
            {"created_at": "2026-02-01T00:00:00", "action": "no_action", "divergence_score": 1 - last / 100},
            {"created_at": "2026-01-01T00:00:00", "action": "no_action", "divergence_score": 1 - first / 100},
        ]
        views.append(
            voice_mod.project_voice_view(
                name="Dana",
                baseline_vector={},
                sample_count=3,
                approved_count=3,
                manifests=manifests,
                corrections=[{"notes": "Well argued.", "created_at": "2026-02-02T00:00:00"}],
                pathway=None,
            )
        )
    assert views[-1]["voice_notes"][0]["reviewer"] == "Your teacher"

    dashes = chr(0x2014) + chr(0x2015)
    for blob in views + results:
        for value in _walk_values(blob):
            assert "formation" not in value.lower(), f"'formation' in returned copy: {value!r}"
            assert "tutor" not in value.lower(), f"'tutor' in returned copy: {value!r}"
            assert not any(d in value for d in dashes), f"an em dash in returned copy: {value!r}"


def test_no_baseline_result_is_honest_and_says_nothing_was_added():
    res = voice_mod.project_no_baseline_result()
    _assert_submit_result_clean(res)
    assert res["headline"] == "Nothing to compare this with yet."
    assert "no approved writing" in res["summary"]
    # A piece compared in My Work is never stored, so no teacher can add it; the
    # sentence says what does join a profile instead.
    assert (
        "Not added to your writing profile. Only writing your teacher approves, such as "
        "sealed Bluebook work, joins your writing profile."
    ) in res["summary"]
    assert "may choose" not in res["summary"]
    assert res["steady"] == [] and res["review_opportunity"] is False


def test_compared_results_never_claim_the_piece_was_kept():
    for action in ("no_action", "monitor", "schedule_conversation", "escalate"):
        res = voice_mod.project_submission_result({"recommendation": {"action": action}}, "Dana")
        said = (res["headline"] + " " + res["summary"]).lower()
        for claim in ("saved", "body of work", "record", "added"):
            assert claim not in said, (action, claim)


# ── Static-HTML: the first-paint render must not flash surveillance jargon ───
#
# The integration tests above prove the JSON payloads are clean. But the
# student.html template renders a fallback before the JS fetches /me/voice
# — for ~50-200ms the user sees the static copy. ADR-005's promise has to
# hold during that flash too. This test parses the user-visible text nodes
# out of demo/student.html and asserts none of the forbidden words appear.

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent

# Words that may not appear in user-visible STUDENT-facing text. Each of
# these would betray the surveillance framing ADR-005 promised to redact.
# The list is deliberately narrow: substrings shared with legitimate prose
# (e.g. "manifest" in "manifested") are NOT included — only the unambiguous
# surveillance-only terms.
STUDENT_FORBIDDEN_STATIC = [
    "divergence",
    "deviation",
    "catastrophic",
    "interference",
    # action enum names (formal config, not formation register)
    "no_action",
    "schedule_conversation",
    "escalate ",  # trailing space so "escalating" doesn't trip
]


def _user_visible_text(html: str) -> str:
    """Strip <style>, <script>, comments — keep only text between tags."""
    html = re.sub(r"<style[\s\S]*?</style>", "", html, flags=re.IGNORECASE)
    html = re.sub(r"<script[\s\S]*?</script>", "", html, flags=re.IGNORECASE)
    html = re.sub(r"<!--[\s\S]*?-->", "", html)
    # Pull strings between tags only — element bodies, not attribute values.
    return " ".join(m for m in re.findall(r">([^<]+)<", html) if m.strip())


def test_student_html_static_first_paint_is_clean():
    """ADR-005 holds during the static-render flash before JS replaces copy."""
    html = (REPO_ROOT / "demo" / "student.html").read_text()
    visible = _user_visible_text(html).lower()
    for bad in STUDENT_FORBIDDEN_STATIC:
        assert bad not in visible, (
            f"surveillance word {bad!r} appears in user-visible text on "
            f"demo/student.html. Replace with the formation-register equivalent "
            f"(see original/voice.py for the canonical word choices)."
        )
