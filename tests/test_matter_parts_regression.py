"""A paper's parts are not measured as its prose (ADR-015, MATTER_SPLITTER_ENABLED).

The 2026-11-18 document-parts experiment (ADR-015's evidence) found that
a bibliography under a heading the old rule missed ("Works Cited:", "## References")
raised an honest paper's reading by about 0.10, and that a cover letter changed
which habits a teacher is shown. This pins the fix at the level that decides
both: with the splitter on, adding any of those parts to a real paper leaves
every measured feature exactly as it was for the paper alone.

The parts are the experiment's own fixed texts. The papers are the first 9,000
characters of a public-domain work in validation/public_authors/corpus/ (one
author here to keep CI fast; the experiment rerun covers all nine).
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from original.constants import ALL_FEATURE_CODES
from original.features.pipeline import feature_vector

CORPUS = Path(__file__).resolve().parents[1] / "validation" / "public_authors" / "corpus"

COVER = """Dear Professor Hartley,

Please find attached my paper for the third assignment of the semester. I chose this
topic because it connects with what we discussed in seminar two weeks ago, and I hope
the argument is clearer than in my last draft. I would be grateful for any comments you
have on the second section in particular, which I found difficult to organise.

Thank you for your patience with the late submission; I was unwell for most of last week.

Sincerely,
Jordan Reyes
"""

TITLE = """Jordan Reyes
Professor Hartley
PHIL 210: Moral and Political Philosophy
14 March 2026

"""

NOTES = """

Notes

1. See Berlin 131 for the distinction between negative and positive liberty.
2. Gray argues the opposite reading; compare Riley 44-47.
3. Rawls, Theory of Justice, sec. 32.
4. All quotations from On Liberty follow the Hackett edition.
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
    "cover letter first": lambda t: COVER + "\n\n" + t,
    "cover letter last": lambda t: t + "\n\n" + COVER,
    "heading block": lambda t: TITLE + t,
    "Works Cited": lambda t: t + "\n\nWorks Cited\n" + ENTRIES_MLA,
    "Works Cited:": lambda t: t + "\n\nWorks Cited:\n" + ENTRIES_MLA,
    "## References": lambda t: t + "\n\n## References\n" + ENTRIES_APA,
    "7. References": lambda t: t + "\n\n7. References\n" + ENTRIES_APA,
    "notes then Works Cited": lambda t: t + NOTES + "\n\nWorks Cited\n" + ENTRIES_MLA,
    "all of them": lambda t: (
        COVER + "\n\n" + TITLE + t + NOTES + "\n\nWorks Cited:\n" + ENTRIES_MLA
    ),
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
