"""Rule D: report-only, testing-phase consistency observation (RULE_D_OBSERVATION).

``on`` is the default while testing (2026-11, owner decision); ``RULE_D_OBSERVATION=off``
turns it off. ``off``: nothing is computed, stored or attached. ``shadow``: computed and stored,
one aggregate INFO log line per scoring call, nothing attached to the response. ``on``:
also attached to the scoring response for staff only (never to students, never on
``/me/work``). In every mode rule D never changes ``deviation_score`` or the recommended
action. See docs/research/2026-11-12-scholarly-rule-d-locked-test-results.md.
"""

from __future__ import annotations

import os

MODES = ("off", "shadow", "on")


def mode() -> str:
    """Read RULE_D_OBSERVATION; unset means ``on``. Anything set but unrecognised (an empty
    string, ``1``, a typo) is ``off``: a value someone typed must never be read as on."""
    raw = os.environ.get("RULE_D_OBSERVATION", "on").strip().lower()
    # "1" is deliberately NOT an alias for on: a typed value is read only by its name.
    return raw if raw in MODES else "off"
