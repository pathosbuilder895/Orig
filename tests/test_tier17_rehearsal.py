"""
tests/test_tier17_rehearsal.py — the Tier 17 enablement rehearsal.

"behavioral" stays in DISABLED_FEATURE_GROUPS in production until the
readiness gate (scripts/tier17_report.py) says READY on real pilot data
AND a human approves the flip (docs/TIER17_ENABLEMENT_RUNBOOK.md). These
tests make that eventual flip a rehearsed act instead of a first
performance: the group is enabled ONLY inside a restore-guaranteed
fixture, and the full pipeline (extract_features → StudentState →
active_feature_mask → score) is proven to behave with the six behavioral
dimensions live.

Nothing here changes the production default; the default-off test doubles
as a tripwire that the default is still off.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from original.constants import (
    ALL_FEATURE_CODES,
    DISABLED_FEATURE_GROUPS,
    TIER17_CODES,
)
from original.features.pipeline import extract_features
from original.quantum.scoring import score
from original.quantum.state import BaselineSample, StudentState

_TIER17_IDX = [ALL_FEATURE_CODES.index(c) for c in TIER17_CODES]

_VALID_ACTIONS = {"no_action", "monitor", "schedule_conversation", "escalate"}

# Four baseline sittings plus one submission, same authorial voice, distinct
# wording — long enough for the prose pipeline to extract real features.
_BASELINE_TEXTS = [
    (
        "The doctrine of creation has never been, for the church, a bare claim "
        "about temporal origins. It is a confession about dependence: that the "
        "world receives its being from beyond itself, moment by moment. When "
        "the psalmist says the heavens declare the glory of God, the point is "
        "not astronomy but doxology. Creation speaks because it is spoken. To "
        "read Genesis well, then, is to ask not merely what happened but who "
        "is addressed, and what obedience the address requires of us now. The "
        "early commentators understood this instinctively, which is why their "
        "readings feel so strange to modern eyes trained on mechanism alone."
    ),
    (
        "Augustine's account of memory in the tenth book of the Confessions "
        "remains startling. He describes vast halls and treasuries, images "
        "stored and summoned, and yet insists that memory is where he meets "
        "God. This is not nostalgia dressed up as theology. It is a claim "
        "that interiority itself is a created space, that the self is deeper "
        "than the self can see, and that the search for God is therefore also "
        "a search through one's own strange depths. Few modern accounts of "
        "consciousness are as honest about how little of ourselves we hold "
        "in view at any moment, or about how much arrives unbidden."
    ),
    (
        "A sermon is not an essay read aloud. The essay persuades by "
        "accumulation; the sermon persuades by address. When the preacher "
        "says you, the congregation is not overhearing an argument but "
        "receiving a summons. This is why sermon manuscripts so often "
        "disappoint on the page: the living second person has drained out "
        "of them, leaving only assertions. The old homiletic manuals knew "
        "this and trained preachers in delivery as a theological "
        "discipline, not a rhetorical ornament. Recovering that instinct "
        "would change more pulpits than any new method could."
    ),
    (
        "Exegesis begins in patience. The text is older than the reader, "
        "stranger than the reader assumes, and indifferent to the reader's "
        "deadlines. Before a single claim is ventured, the grammar must be "
        "traced, the context weighed, the term followed through its other "
        "occurrences. Students resist this slowness at first, suspecting it "
        "of pedantry. But the slowness is the method: what the text yields "
        "to patience it withholds from haste. Every shortcut taken in the "
        "reading reappears later as a weakness in the argument, usually at "
        "the exact point where precision mattered most."
    ),
]

_SUBMISSION_TEXT = (
    "The parables resist summary because they are not illustrations of "
    "ideas but instruments of encounter. A man finds a treasure in a field; "
    "a woman sweeps her house for a coin; a father runs down the road. Each "
    "story ends before its meaning does, and the remainder is assigned to "
    "the hearer. To ask what the parable teaches is already to stand at the "
    "wrong angle to it. The better question is what the parable does, and "
    "to whom, and whether we are willing to be the ones addressed. That "
    "willingness, more than any interpretive technique, is what the form "
    "demands and what it rewards."
)


def _keystroke_blob(seed: int) -> dict:
    """A varied, realistic composition-shaped blob. Seeds produce distinct
    rhythm/revision/pause profiles so the six features carry real variance
    across a baseline (degenerate distributions would be masked back out)."""
    rng = np.random.default_rng(20260813 + seed)
    keystrokes = []
    elapsed = 0.0
    for i in range(200):
        # Bursts (fast keys) alternating with hesitation, scaled per seed.
        if i % (4 + seed % 3) == 0:
            gap = float(rng.uniform(250, 600 + 80 * seed))
        else:
            gap = float(rng.uniform(60, 140 + 10 * seed))
        elapsed += gap
        key = "Backspace" if i % (12 + 2 * seed) == 0 else "a"
        keystrokes.append({"key": key, "elapsed": elapsed})
    n_pauses = 2 + seed % 4
    revisions = [{"type": "delete", "charsAffected": 2 + seed % 5} for _ in range(1 + seed % 3)]
    if seed % 3 == 0:
        revisions.append({"type": "paste", "charsAffected": 40})
    return {
        "keystrokes": keystrokes,
        "pauses": [{"duration": 3200 + 400 * k} for k in range(n_pauses)],
        "revisions": revisions,
        "wordCount": 110 + 5 * seed,
        "sessionDurationSec": elapsed / 1000.0,
    }


def _vector(feature_dict: dict[str, float]) -> np.ndarray:
    return np.array([feature_dict[c] for c in ALL_FEATURE_CODES], dtype=np.float64)


def _build_state(enabled_texts_blobs: list[tuple[str, dict]]) -> StudentState:
    samples = []
    for text, blob in enabled_texts_blobs:
        feats = extract_features(text, keystroke_data=blob)
        samples.append(
            BaselineSample(
                text=text, vector=_vector(feats), provenance="proctored", auth_weight=1.0
            )
        )
    return StudentState(student_id="tier17-rehearsal", samples=samples)


@pytest.fixture()
def behavioral_enabled():
    """Enable the behavioral group for one test, restore-guaranteed."""
    assert "behavioral" in DISABLED_FEATURE_GROUPS, (
        "precondition failed: 'behavioral' is no longer disabled by default — "
        "if the flip has been made deliberately, retire this rehearsal file "
        "per docs/TIER17_ENABLEMENT_RUNBOOK.md; otherwise this is a regression"
    )
    DISABLED_FEATURE_GROUPS.discard("behavioral")
    try:
        yield
    finally:
        DISABLED_FEATURE_GROUPS.add("behavioral")


def test_default_off_keeps_tier17_neutral_even_with_keystroke_data():
    """Production default: keystroke data present, features still 0.5/inactive."""
    assert "behavioral" in DISABLED_FEATURE_GROUPS
    feats = extract_features(_BASELINE_TEXTS[0], keystroke_data=_keystroke_blob(0))
    for code in TIER17_CODES:
        assert feats[code] == 0.5


def test_enabled_tier17_features_leave_neutral_and_stay_bounded(behavioral_enabled):
    feats = extract_features(_BASELINE_TEXTS[0], keystroke_data=_keystroke_blob(0))
    vals = [feats[c] for c in TIER17_CODES]
    assert any(abs(v - 0.5) > 0.002 for v in vals)
    assert all(0.0 <= v <= 1.0 for v in vals)


def test_enabled_without_keystroke_data_still_neutral(behavioral_enabled):
    """The flag alone must not invent behavioral signal for pasted-in text."""
    feats = extract_features(_BASELINE_TEXTS[0], keystroke_data=None)
    for code in TIER17_CODES:
        assert feats[code] == 0.5


def test_active_mask_flips_for_tier17_when_enabled(behavioral_enabled):
    state = _build_state(
        [(t, _keystroke_blob(i)) for i, t in enumerate(_BASELINE_TEXTS)]
    )
    mask = state.active_feature_mask
    flipped = [ALL_FEATURE_CODES[i] for i in _TIER17_IDX if mask[i]]
    # The rehearsal corpus is built to vary every behavioral dimension, but the
    # gate we rehearse for production requires only >= 4 of 6 non-degenerate —
    # hold the rehearsal to the same bar.
    assert len(flipped) >= 4, f"only {flipped} became active"


def test_active_mask_stays_off_at_default():
    state = _build_state(
        [(t, _keystroke_blob(i)) for i, t in enumerate(_BASELINE_TEXTS)]
    )
    mask = state.active_feature_mask
    assert not any(mask[i] for i in _TIER17_IDX)


def test_score_end_to_end_with_behavioral_dimensions_live(behavioral_enabled):
    """The rehearsal's core: the full scoring path with 103-dim-capable
    profiles neither crashes nor degenerates."""
    state = _build_state(
        [(t, _keystroke_blob(i)) for i, t in enumerate(_BASELINE_TEXTS)]
    )
    feats = extract_features(_SUBMISSION_TEXT, keystroke_data=_keystroke_blob(7))
    out = score(
        state,
        _vector(feats),
        feats,
        submission_id="tier17-rehearsal-sub",
        n_tokens=len(_SUBMISSION_TEXT.split()),
    )
    assert math.isfinite(out.authorship.deviation_score)
    assert out.authorship.deviation_score >= 0.0
    assert 0.0 <= out.authorship.authorship_probability <= 1.0
    assert out.recommendation.action in _VALID_ACTIONS


def test_fixture_restores_the_production_default(behavioral_enabled):
    """Inside the fixture the group is live; the finally-block guarantees the
    default returns. Paired with test_default_off_* running in any order,
    this proves rehearsals cannot leak the flag into other tests."""
    assert "behavioral" not in DISABLED_FEATURE_GROUPS
