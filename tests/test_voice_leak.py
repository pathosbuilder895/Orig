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

# Tokens that must NEVER appear in any student-facing payload. Feature codes are
# checked separately (the full ALL_FEATURE_CODES list).
FORBIDDEN_SUBSTRINGS = [
    "divergence",
    "deviation",
    "purity",
    "baseline_vector",
    "feature_vector",
    "sample_count",
    "authenticated_count",
    "trajectory",
    "quantum",
    "anomal",          # "anomaly" / "anomalous"
    "no_action",
    "schedule_conversation",
    "escalate",
    "manifest",
    "human_explanation",
]


def _assert_clean(blob) -> None:
    """Assert a JSON-serializable blob carries no forbidden token or feature code."""
    text = json.dumps(blob).lower()
    for bad in FORBIDDEN_SUBSTRINGS:
        assert bad not in text, f"forbidden token {bad!r} leaked into student payload"
    for code in ALL_FEATURE_CODES:
        assert code not in text, f"feature code {code!r} leaked into student payload"


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
    _assert_clean(view)

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
    _assert_clean(res)
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
    _assert_clean(r.json())
    assert len(r.json()["fingerprint"]) == 7


def test_me_work_is_clean(student_token):
    tok, _sid = student_token
    r = client.post("/me/work", headers={"Authorization": f"Bearer {tok}"},
                    json={"text": LONG_TEXT, "title": "Conscience & Formation"})
    assert r.status_code == 200, r.text
    _assert_clean(r.json())


def test_student_cannot_read_a_classmate(student_token):
    """Self-only authz: a student token cannot read another student's record."""
    tok, sid = student_token
    # Same tenant, different student id.
    tenant = sid.split(":", 1)[0]
    other = f"{tenant}:someone-else"
    r = client.get(f"/students/{other}", headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 403, r.text


def test_student_can_still_read_self(student_token):
    """The self-only rule must not break a student reading their own record."""
    tok, sid = student_token
    r = client.get(f"/students/{sid}", headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 200, r.text
