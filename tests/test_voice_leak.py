"""
ADR-005 leak-test gate — the permanent guarantee that the student read-model
never carries surveillance internals on the wire.

Two layers of defence:
  1. Unit: drive original.voice projections with deliberately adversarial raw
     inputs (real feature codes, raw divergence scores, action enums, formation
     reasons) and assert NONE of them survive into the projected output.
  2. Integration: sign in as a student, hit /me/voice and /me/work, and assert
     the serialized payloads contain no forbidden token. Also proves the
     self-only authorization (a student cannot read a classmate via /students).
"""

import json

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
ALLOWED_VOICE_VIEW_KEYS = frozenset({
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
})

ALLOWED_SUBMIT_RESULT_KEYS = frozenset({
    "headline",
    "summary",
    "steady",
    "review_opportunity",
})

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
        {"submission_id": "s2", "created_at": "2025-11-14T00:00:00",
         "divergence_score": 0.61, "action": "schedule_conversation"},
        {"submission_id": "s1", "created_at": "2025-10-09T00:00:00",
         "divergence_score": 0.12, "action": "no_action"},
    ]
    corrections = [
        {"notes": "Your handling of apophatic language is genuinely your own now.",
         "reviewer": "Dr. Pemberton", "created_at": "2025-12-18T00:00:00",
         "original_divergence_score": 0.61, "original_action": "schedule_conversation"},
    ]
    pathway = {"current_step": 1, "total_steps": 3, "status": "open",
               "reason": "voice divergence", "submission_id": "s2"}

    view = voice_mod.project_voice_view(
        name="Thomas Merton", baseline_vector=baseline,
        sample_count=5, authenticated_count=2,
        manifests=manifests, corrections=corrections, pathway=pathway,
    )
    _assert_voice_view_clean(view)

    # The shape is still useful: 7 blended dimensions, an ascending arc, a note.
    assert len(view["fingerprint"]) == 7
    assert [p["fidelity"] for p in view["arc"]] == [88, 39]  # oldest→newest, resolved
    assert view["arc"][1]["attention"] is True               # the flagged piece
    assert view["voice_notes"][0]["reviewer"] == "Dr. Pemberton"
    assert view["review_opportunities"], "a flagged manifest should invite a conversation"
    assert view["formation"]["current_step"] == 1


def test_submission_result_redaction():
    # A raw-ish Layer-7 dict with an action enum + constructive feature codes.
    layer7 = {
        "recommendation": {"action": "monitor"},
        "authorship": {"deviation_score": 0.52},
        "interference": {"constructive_features": [
            {"code": "type_token_ratio", "name": "Type-token ratio"},
            {"code": "burstiness", "name": "Burstiness"},
        ]},
        "human_explanation": {"summary": "deviation score 0.52; anomalies detected"},
    }
    res = voice_mod.project_submission_result(layer7, "Thomas Merton")
    _assert_submit_result_clean(res)
    assert res["review_opportunity"] is True
    assert res["steady"], "constructive features should surface as steady dimensions"


# ── Integration: live endpoints over a signed-in student ─────────────────────

@pytest.fixture(scope="module")
def student_token():
    r = client.post("/student-auth/login", json={
        "email": "merton@gethsemani.edu", "institution": "Gethsemani Demo",
        "name": "Thomas Merton",
    })
    assert r.status_code == 200, r.text
    body = r.json()
    tok = body["token"]
    sid = body["student_id"]
    hdr = {"Authorization": f"Bearer {tok}"}
    # Seed two authenticated baselines so scoring is possible.
    for i in range(2):
        rr = client.post(f"/students/{sid}/baseline",
                         json={"text": LONG_TEXT, "assignment": f"a{i}", "provenance": "verified"},
                         headers=hdr)
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
    r = client.post("/me/work", headers={"Authorization": f"Bearer {tok}"},
                    json={"text": LONG_TEXT, "title": "Conscience & Formation"})
    assert r.status_code == 200, r.text
    _assert_submit_result_clean(r.json())


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
