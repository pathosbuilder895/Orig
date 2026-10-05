"""No keystroke-derived data enters the classroom release (text + coarse session only)."""

from __future__ import annotations

from original import constants
from original.schemas import AddSampleRequest, ScoreSubmissionRequest
from original.schemas import TestScoreRequest as _ScoreRequest  # not a pytest class

KEYS = {"keystrokes": [1, 2], "pauses": [3], "deletionRate": 0.2, "avgWpm": 41}
SUMMARY = {"session_seconds": 600, "paste_attempts": 0, "focus_losses": 1, "revision_count": 37}


def test_keystroke_data_is_discarded_while_behavioral_features_are_disabled():
    assert "behavioral" in constants.DISABLED_FEATURE_GROUPS
    for model in (
        AddSampleRequest(text="t", keystroke_data=KEYS, composition_summary=SUMMARY),
        ScoreSubmissionRequest(text="t", keystroke_data=KEYS, composition_summary=SUMMARY),
    ):
        assert model.keystroke_data is None
        assert "revision_count" not in model.composition_summary
        assert model.composition_summary["session_seconds"] == 600
    assert _ScoreRequest(text="t", keystroke_data=KEYS).keystroke_data is None


def test_keystroke_data_passes_when_behavioral_features_are_enabled(monkeypatch):
    monkeypatch.setattr(
        constants, "DISABLED_FEATURE_GROUPS", constants.DISABLED_FEATURE_GROUPS - {"behavioral"}
    )
    model = AddSampleRequest(text="t", keystroke_data=KEYS, composition_summary=SUMMARY)
    assert model.keystroke_data == KEYS
    assert model.composition_summary["revision_count"] == 37


def test_baseline_route_persists_no_keystroke_data(live_client, store_reset):
    from original.repository import get_repository

    text = " ".join(["Augustine writes of memory and the restless heart."] * 30)
    r = live_client.post(
        "/students/demo:ks-student/baseline",
        json={"text": text, "keystroke_data": KEYS, "composition_summary": SUMMARY},
    )
    assert r.status_code == 200, r.text
    sample = get_repository().get("demo:ks-student").samples[-1]
    assert sample.keystroke_data is None
    assert "revision_count" not in (sample.composition_summary or {})
    assert sample.composition_summary["session_seconds"] == 600


PASTE_KEYS = {
    "keystrokes": [{"key": "a", "elapsed": 100.0 * i} for i in range(20)],
    "pauses": [{"duration": 3000}],
    "revisions": [{"type": "paste"}, {"type": "paste"}],
    "deletionRate": 0.2,
    "avgWpm": 41,
    "wordCount": 120,
}

BASELINES = [
    "Augustine begins with praise, not argument. He asks how a creature can call on a God it "
    "does not yet know, and he lets the question hang for a while. The restless heart is his "
    "answer, though he never quite says so plainly. I think he wants the reader to feel the "
    "delay. Memory comes later, in the tenth book, where he wanders its halls like a man "
    "looking for a coin he dropped in the dark.",
    "The pear tree story bothers me more each time I read it. Nobody was hungry. The pears "
    "were not even good. Augustine says he loved the theft itself, and the company of the "
    "boys who did it with him. That last part matters, I think, because he admits he would "
    "not have done it alone. Sin here is social before it is anything else, and that is a "
    "strange thing for a bishop to confess.",
    "Monica keeps appearing at the edges of the story. She weeps, she prays, she follows him "
    "across the sea to Milan. When she dies at Ostia he holds back his tears and then cannot. "
    "The scene is short. It is also the most human moment in the whole book, and I suspect "
    "he knew that when he wrote it, because he stops arguing for a page and simply remembers "
    "her.",
]

SUBMISSION = (
    "Ambrose reads silently, and Augustine is astonished. Why? Because in his world reading "
    "meant speaking the words aloud, even alone, even at night. He watches the bishop's eyes "
    "move across the page while his voice stays still, and he does not dare interrupt. I find "
    "this small detail more revealing than the long debates about Manichees. It tells us what "
    "kind of attention Augustine admired. Quiet. Patient. Turned inward, the way his own "
    "memory would later be turned inward in the tenth book."
)


def test_keystroke_data_cannot_move_a_score_under_the_context_manifest(
    live_client, store_reset, monkeypatch
):
    """With the context manifest on (demo deploys, and always in the admin
    playground), ``resolve_composition_mode`` used to read paste events out of
    ``keystroke_data``, mark the submission ``tool_cleaned`` and attenuate
    Tiers 11 and 14. Discarded at the boundary, it can no longer move a score."""
    monkeypatch.setenv("CONTEXT_MANIFEST_ENABLED", "1")
    monkeypatch.setenv("ADAPTIVE_WEIGHTS_ENABLED", "1")
    sid = "demo:ks-manifest-student"
    for text in BASELINES:
        r = live_client.post(f"/students/{sid}/baseline", json={"text": text})
        assert r.status_code == 200, r.text

    plain = live_client.post(f"/students/{sid}/score", json={"text": SUBMISSION})
    keyed = live_client.post(
        f"/students/{sid}/score", json={"text": SUBMISSION, "keystroke_data": PASTE_KEYS}
    )
    assert plain.status_code == 200, plain.text
    assert keyed.status_code == 200, keyed.text
    plain, keyed = plain.json(), keyed.json()

    # The text alone does not read as tool-cleaned, so paste events would have flipped it.
    assert plain["context_manifest"]["composition_mode"]["mode"] != "tool_cleaned"
    assert (
        keyed["context_manifest"]["composition_mode"]
        == plain["context_manifest"]["composition_mode"]
    )
    assert keyed["authorship"]["deviation_score"] == plain["authorship"]["deviation_score"]
    assert keyed["recommendation"]["action"] == plain["recommendation"]["action"]
