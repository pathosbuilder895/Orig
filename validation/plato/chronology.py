"""
validation/plato/chronology.py — scholarly ground truth for the Plato study.

Pure data, no I/O. Encodes the standard early/middle/late grouping of the
Platonic dialogues as ordinal ranks, together with a per-dialogue
``high_confidence`` flag.

Ground truth source
-------------------
The grouping follows the mainstream consensus represented in John M. Cooper's
introduction to *Plato: Complete Works* (Hackett, 1997), which in turn rests on
the stylometric tradition running Campbell (1867) → Lutosławski (1897) →
Ritter → Brandwood (*The Chronology of Plato's Dialogues*, CUP 1990).

``high_confidence`` is True only where the group assignment is effectively
unanimous across that tradition AND is not subject to a well-known dissent.
Everything else is included in the corpus but flagged, and the primary metric
is reported on the high-confidence subset alone.

⚠ Circularity disclosure — this MUST appear in any writeup.
The scholarly chronology was itself partly *derived* from stylometry: Campbell
worked from Greek vocabulary, Lutosławski from Greek particles, Ritter and
Brandwood from Greek clausulae and phrase rhythm. None of those markers
survive translation into Jowett's English, so a correlation found here is not
straightforwardly circular — the features are measuring different things than
the features that produced the ground truth. But the ground truth is not
*independent* of the method in the way a documented publication date would be,
and no claim made from this corpus may pretend otherwise.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

# Ordinal ranks. Deliberately ordinal, not years: the absolute dates are
# guesswork, but the group ORDER is the part scholarship actually supports.
EARLY = 1
MIDDLE = 2
LATE = 3

GROUP_NAMES: Dict[int, str] = {EARLY: "early", MIDDLE: "middle", LATE: "late"}


@dataclass(frozen=True)
class Dialogue:
    """One work in the corpus.

    Attributes:
        slug: stable local identifier; used in filenames and the manifest.
        title: display title.
        pg_id: Project Gutenberg ebook id for the Jowett translation.
        group: EARLY / MIDDLE / LATE, or None for works excluded from the
            chronology analysis (i.e. the spurious control).
        high_confidence: include in the primary metric.
        note: why a work is flagged, when it is.
        spurious: not by Plato — used as a negative control, never ranked.
    """

    slug: str
    title: str
    pg_id: int
    group: Optional[int]
    high_confidence: bool = False
    note: str = ""
    spurious: bool = False


DIALOGUES: List[Dialogue] = [
    # ── Early: the Socratic / aporetic group ────────────────────────────────
    Dialogue("apology", "Apology", 1656, EARLY, True),
    Dialogue("crito", "Crito", 1657, EARLY, True),
    Dialogue("charmides", "Charmides", 1580, EARLY, True),
    Dialogue("laches", "Laches", 1584, EARLY, True),
    Dialogue("lysis", "Lysis", 1579, EARLY, True),
    Dialogue("euthyphro", "Euthyphro", 1642, EARLY, True),
    Dialogue("ion", "Ion", 1635, EARLY, True),
    Dialogue("hippias_minor", "Lesser Hippias", 1673, EARLY, True),
    Dialogue("protagoras", "Protagoras", 1591, EARLY, True),
    Dialogue(
        "gorgias",
        "Gorgias",
        1672,
        EARLY,
        False,
        "Transitional; some place it at the early/middle boundary.",
    ),
    Dialogue(
        "euthydemus",
        "Euthydemus",
        1598,
        EARLY,
        False,
        "Transitional; placement within the early group is unsettled.",
    ),
    Dialogue(
        "menexenus",
        "Menexenus",
        1682,
        EARLY,
        False,
        "Both date and authenticity have been questioned.",
    ),
    # ── Middle ──────────────────────────────────────────────────────────────
    Dialogue("phaedo", "Phaedo", 1658, MIDDLE, True),
    Dialogue("symposium", "Symposium", 1600, MIDDLE, True),
    Dialogue("republic", "The Republic", 1497, MIDDLE, True),
    Dialogue(
        "meno",
        "Meno",
        1643,
        MIDDLE,
        False,
        "Early/middle transitional; frequently grouped with the early works.",
    ),
    Dialogue(
        "cratylus",
        "Cratylus",
        1616,
        MIDDLE,
        False,
        "Placement contested across the middle group.",
    ),
    Dialogue(
        "phaedrus",
        "Phaedrus",
        1636,
        MIDDLE,
        False,
        "Often placed late-middle, adjacent to the late group.",
    ),
    Dialogue(
        "parmenides",
        "Parmenides",
        1687,
        MIDDLE,
        False,
        "Late-middle transitional; stylistically close to the late group.",
    ),
    Dialogue(
        "theaetetus",
        "Theaetetus",
        1726,
        MIDDLE,
        False,
        "Transitional to the late group; Jowett himself notes the ambiguity.",
    ),
    # ── Late ────────────────────────────────────────────────────────────────
    Dialogue("sophist", "Sophist", 1735, LATE, True),
    Dialogue("statesman", "Statesman", 1738, LATE, True),
    Dialogue("philebus", "Philebus", 1744, LATE, True),
    Dialogue("laws", "Laws", 1750, LATE, True, "Universally agreed to be the last work."),
    Dialogue(
        "timaeus",
        "Timaeus",
        1572,
        LATE,
        False,
        "G.E.L. Owen argued for a middle-period date; stylometry favours late.",
    ),
    Dialogue(
        "critias",
        "Critias",
        1571,
        LATE,
        False,
        "Companion to the Timaeus and inherits the same dispute.",
    ),
    # ── Negative control: spurious ──────────────────────────────────────────
    # Gutenberg's own title page for pg1681 reads "By a Platonic Imitator".
    # Never ranked; used only to test whether the feature space places it
    # outside the genuine corpus.
    Dialogue(
        "eryxias",
        "Eryxias",
        1681,
        None,
        False,
        "Near-universally judged spurious. Negative control only.",
        spurious=True,
    ),
]


# ── Second-translator control ───────────────────────────────────────────────
#
# Henry Cary's translation (PG 13726, Bohn's Classical Library) covers three
# dialogues that Jowett also translated. Holding the source text constant and
# varying the translator is what lets us measure how much of the feature-space
# variance the translator owns versus the source author.
#
# Deliberately conservative: Apology, Crito and Phaedo sit close together in
# the chronology, so if source-text signal beats translator signal HERE, it
# will do so across the full 40-year span.

CARY_PG_ID = 13726
CARY_DIALOGUES: List[str] = ["apology", "crito", "phaedo"]


# ── Lookups ─────────────────────────────────────────────────────────────────


def by_slug(slug: str) -> Dialogue:
    for d in DIALOGUES:
        if d.slug == slug:
            return d
    raise KeyError(f"unknown dialogue slug: {slug!r}")


def ranked() -> List[Dialogue]:
    """Every dialogue carrying a chronological rank (excludes the spurious control)."""
    return [d for d in DIALOGUES if d.group is not None and not d.spurious]


def high_confidence() -> List[Dialogue]:
    """The subset the primary metric is computed on."""
    return [d for d in ranked() if d.high_confidence]


def summary() -> str:
    lines = ["Plato corpus ground truth", ""]
    for g in (EARLY, MIDDLE, LATE):
        members = [d for d in ranked() if d.group == g]
        hc = sum(1 for d in members if d.high_confidence)
        lines.append(f"  {GROUP_NAMES[g]:<7} {len(members):>2} dialogues ({hc} high-confidence)")
    spurious = [d for d in DIALOGUES if d.spurious]
    lines.append(f"  control {len(spurious):>2} spurious ({', '.join(d.title for d in spurious)})")
    return "\n".join(lines)


if __name__ == "__main__":
    print(summary())
