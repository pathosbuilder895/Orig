"""A paper's parts are not measured as its prose (ADR-015, MATTER_SPLITTER_ENABLED).

The 2026-11-18 document-parts experiment (ADR-015 and its script are on PR #326,
validation/diagnostics/document_parts_2026-11-18/) found that
a bibliography under a heading the old rule missed ("Works Cited:", "## References")
raised an honest paper's reading by about 0.10, and that a cover letter changed
which habits a teacher is shown. This pins the fix for
the bibliography at the level that decides it: with the splitter on, adding a
heading block or a list of sources under any of its headings to a real paper
leaves every measured feature exactly as it was for the paper alone.

Cover letters and notes without years are not detected (rules for them kept
setting student writing aside), so they are not in PARTS: they are still
measured as prose until a teacher can mark a part herself.

The parts are the experiment's own fixed texts. The papers are the first 9,000
characters of a public-domain work in validation/public_authors/corpus/ (one
author here to keep CI fast; the full experiment, nine authors through the
live routes, is rerun by hand from PR #326's script).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from original.constants import ALL_FEATURE_CODES
from original.features.pipeline import feature_vector

CORPUS = Path(__file__).resolve().parents[1] / "validation" / "public_authors" / "corpus"

TITLE = """Jordan Reyes
Professor Hartley
PHIL 210: Moral and Political Philosophy
14 March 2026

"""

ENTRIES_MLA = """
Arendt, Hannah. The Human Condition. 2nd ed., U of Chicago P, 1998.
Berlin, Isaiah. Four Essays on Liberty. Oxford UP, 1969.
Gray, John. Mill on Liberty: A Defence. 2nd ed., Routledge, 1996.
Rawls, John. A Theory of Justice. Harvard UP, 1971.
Riley, Jonathan. Mill's On Liberty. Routledge, 1998.
Ten, C. L. Mill on Liberty. Clarendon Press, 1980.
"""

ENTRIES_APA = """
Berlin, I. (1969). Two concepts of liberty. In Four essays on liberty (pp. 118-172). Oxford UP.
Gray, J. (1996). Mill on liberty: A defence (2nd ed.). Routledge.
Rawls, J. (1971). A theory of justice. Harvard University Press.
Riley, J. (1998). Mill's On liberty. Routledge.
Ten, C. L. (1980). Mill on liberty. Clarendon Press.
"""

PARTS = {
    "heading block": lambda t: TITLE + t,
    "Works Cited": lambda t: t + "\n\nWorks Cited\n" + ENTRIES_MLA,
    "Works Cited:": lambda t: t + "\n\nWorks Cited:\n" + ENTRIES_MLA,
    "## References": lambda t: t + "\n\n## References\n" + ENTRIES_APA,
    "7. References": lambda t: t + "\n\n7. References\n" + ENTRIES_APA,
    "**Works Cited**": lambda t: t + "\n\n**Works Cited**\n" + ENTRIES_MLA,
    "heading block and a list": lambda t: TITLE + t + "\n\nWorks Cited:\n" + ENTRIES_MLA,
}


def _paper(author: str) -> str:
    first = sorted(CORPUS.glob(f"{author}/*part_0*.txt"))[0]
    return first.read_text(encoding="utf-8")[:9000]


@pytest.fixture(scope="module", params=["mill"])
def paper(request):
    mp = pytest.MonkeyPatch()
    mp.setenv("MATTER_SPLITTER_ENABLED", "1")
    text = _paper(request.param)
    plain = np.asarray(feature_vector(text))
    yield text, plain
    mp.undo()


@pytest.mark.parametrize("part", sorted(PARTS))
def test_adding_a_part_changes_no_measurement(paper, part, monkeypatch):
    monkeypatch.setenv("MATTER_SPLITTER_ENABLED", "1")
    text, plain = paper
    with_part = np.asarray(feature_vector(PARTS[part](text)))
    moved = [
        (ALL_FEATURE_CODES[i], float(plain[i]), float(with_part[i]))
        for i in np.flatnonzero(np.abs(with_part - plain) > 0)
    ]
    assert moved == [], f"{part}: these measurements moved: {moved[:5]}"


def test_with_the_splitter_off_the_unmatched_heading_still_moves_them(monkeypatch):
    """The witness: without the splitter the old rule measures a list of
    sources under "Works Cited:" as prose, which is the fault being fixed."""
    monkeypatch.delenv("MATTER_SPLITTER_ENABLED", raising=False)
    text = _paper("mill")
    plain = np.asarray(feature_vector(text))
    with_list = np.asarray(feature_vector(PARTS["Works Cited:"](text)))
    assert np.abs(with_list - plain).max() > 0.05
