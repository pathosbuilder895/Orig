"""Bluebook's "worth a look" mark is an Original result, so it carries the testing label.

NORTH_STAR rule 10: wherever a teacher sees an Original result, the screen says
plainly that Original is in its testing phase. In Bluebook that result is the
"worth a look" mark (a sealed exam compared with the writing in the student's
baseline). The sentence is the one the Original suite shows (``NOTICE`` in
``demo/original/live.js``); Bluebook is a separate bundle, so it keeps its own
copy, and these tests keep the two the same and keep every screen that shows the
mark rendering the shared note. (The behaviour itself is asserted in the
professor-journey e2e.)
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BLUEBOOK = ROOT / "demo" / "bluebook"
LIVE_JS = ROOT / "demo" / "original" / "live.js"

NOTICE = (
    "Testing phase: Original is not yet validated on real student writing. "
    "Treat any result as a reason for a conversation, never as evidence."
)
SOURCE_LINE = "Worth a look: marked by Original's comparison with the writing in each student's baseline."


def _jsx() -> dict[str, str]:
    return {p.name: p.read_text(encoding="utf-8") for p in sorted(BLUEBOOK.glob("*.jsx"))}


def test_bluebook_label_is_the_sentence_the_original_suite_shows():
    live = LIVE_JS.read_text(encoding="utf-8")
    suite = re.search(r"var NOTICE = '([^']+)';", live)
    assert suite and suite.group(1) == NOTICE
    assert f"export const ORIGINAL_TESTING_NOTICE = '{NOTICE}';" in _jsx()["components.jsx"]


def test_the_label_is_written_once_in_bluebook_source():
    written = {name: text.count(NOTICE) for name, text in _jsx().items() if NOTICE in text}
    assert written == {"components.jsx": 1}


def test_every_screen_that_shows_the_mark_renders_the_shared_note():
    shown = []
    for name, text in _jsx().items():
        if name == "components.jsx":
            continue
        if re.search(r"worth a look", text, re.IGNORECASE):
            shown.append(name)
            assert "<WorthALookNote" in text, f"{name} shows the mark without the testing label"
    # The screens that show the mark today; a new one must be added here on purpose.
    assert shown == ["Results.jsx", "Students.jsx"]


def test_the_results_row_line_carries_the_label_too():
    results = _jsx()["Results.jsx"]
    assert "Marked by Original's comparison with the writing in this student's baseline. {ORIGINAL_TESTING_NOTICE}" in results
    assert SOURCE_LINE in _jsx()["components.jsx"]


def test_the_shared_badge_names_the_label_in_its_tooltip_but_does_not_rely_on_it():
    components = _jsx()["components.jsx"]
    assert "title={flagged ? `${WORTH_A_LOOK_SOURCE} ${ORIGINAL_TESTING_NOTICE}` : undefined}" in components
    # A tooltip is not enough: the screens render the note (previous test).


def test_the_committed_bundle_carries_the_label():
    bundle = (BLUEBOOK / "bluebook.bundle.js").read_text(encoding="utf-8")
    assert NOTICE in bundle, "rebuild: cd demo/bluebook && npm run build"
    assert SOURCE_LINE in bundle
