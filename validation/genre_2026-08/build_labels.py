"""
Build the hand-labelled genre corpus from the committed sources.

Run:
    .venv/bin/python validation/genre_2026-08/build_labels.py

Every label below is a HAND decision, recorded here as an explicit
group -> (label, justification) mapping rather than inferred at runtime, so
each one can be checked against the codebook by a reader who does not trust
the labeller. The codebook is committed before this file and its sha256 is
pinned into the output; if the definitions change, the labels must be
re-examined rather than silently inheriting a new meaning.

See validation/genre_2026-08/CODEBOOK.md for the class definitions, for why
`sermon` and Plato are excluded, and for why documents that fit no class are
omitted rather than forced.
"""

from __future__ import annotations

import hashlib
import json
import sys
from collections import defaultdict
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent.parent
sys.path.insert(0, str(_ROOT))

CODEBOOK = _HERE / "CODEBOOK.md"
OUT = _HERE / "labels.json"

# Documents shorter than this are dropped: the signals the classifier reads
# are per-sentence and per-word rates, which are noise on a fragment.
MIN_WORDS = 250

# Per-class cap. Burke alone has 173 files and would otherwise carry
# scholarly_essay outright; the cap is applied per class and filled evenly
# across that class's authors, so a prolific author cannot dominate.
#
# 40 rather than 60: at 60 the available scholarly_essay documents filled the
# cap while creative_fiction could supply only 12, putting one class at 60 of
# 118 — over half the corpus on its own, which
# tests/validation/test_genre_labels.py rejects. The binding constraint is the
# smallest class, and no cap can fix that; the cap only stops the largest from
# swamping it further.
PER_CLASS_CAP = 40

# ── The hand labels ───────────────────────────────────────────────────────────
#
# (glob, author, label, justification-against-the-codebook)
GROUPS: list[tuple[str, str, str, str]] = [
    # academic_exegesis — written to be graded, expository, source-organised.
    ("validation/corpus/seminary_01_*.txt", "seminary_01", "academic_exegesis",
     "seminary coursework: analyses a doctrine for an assessor, expository structure"),
    ("validation/corpus/seminary_02_*.txt", "seminary_02", "academic_exegesis",
     "seminary coursework: analyses a doctrine for an assessor, expository structure"),
    ("validation/corpus/seminary_03_*.txt", "seminary_03", "academic_exegesis",
     "seminary coursework: analyses a doctrine for an assessor, expository structure"),
    ("validation/corpus/seminary_04_*.txt", "seminary_04", "academic_exegesis",
     "seminary coursework: analyses a doctrine for an assessor, expository structure"),
    ("validation/corpus/seminary_05_*.txt", "seminary_05", "academic_exegesis",
     "seminary coursework: analyses a doctrine for an assessor, expository structure"),

    # scholarly_essay — sustained argument to an educated public.
    ("validation/corpus/burke_*.txt", "burke", "scholarly_essay",
     "political pamphlet: argues a thesis about institutions to a general reader"),
    ("validation/corpus/paine_*.txt", "paine", "scholarly_essay",
     "political pamphlet: argues a thesis about institutions to a general reader"),
    ("validation/corpus/fed_hamilton_*.txt", "hamilton", "scholarly_essay",
     "Federalist papers: argumentative essays advocating ratification"),
    ("validation/corpus/fed_madison_*.txt", "madison", "scholarly_essay",
     "Federalist papers: argumentative essays advocating ratification"),
    ("validation/corpus/fed_jay_*.txt", "jay", "scholarly_essay",
     "Federalist papers: argumentative essays advocating ratification"),
    ("validation/public_authors/corpus/mill/on_liberty_*.txt", "mill", "scholarly_essay",
     "On Liberty: chain-of-argument prose about a public question"),
    ("validation/public_authors/corpus/newman/the_idea_of_a_university_*.txt", "newman",
     "scholarly_essay", "lectures arguing a thesis about education, not homiletic"),
    ("validation/public_authors/corpus/james/the_varieties_*.txt", "james", "scholarly_essay",
     "Gifford lectures: argues a thesis about religious experience to a public"),
    ("validation/public_authors/corpus/chesterton/orthodoxy_*.txt", "chesterton",
     "scholarly_essay", "Orthodoxy: argumentative apologetic addressed to a general reader"),

    # personal_essay — the writer is the subject.
    ("validation/public_authors/corpus/thoreau/*.txt", "thoreau", "personal_essay",
     "first-person reflection organised by experience, not by argument"),
    # CORRECTED 2026-08-08, post-hoc — see LABEL_CORRECTIONS below.
    ("validation/public_authors/corpus/emerson/*.txt", "emerson", "scholarly_essay",
     "Self-Reliance / Compensation / History argue about the world in the first "
     "person; the codebook's deciding test sends argument-about-the-world to "
     "scholarly_essay regardless of pronoun"),
    ("validation/public_authors/corpus/douglass/my_bondage_*.txt", "douglass", "personal_essay",
     "autobiography: narrative asserted as true of the writer"),
    ("validation/public_authors/corpus/augustine/confessions_*.txt", "augustine",
     "personal_essay", "Confessions: first-person account of the writer's own life"),

    # creative_fiction — invented narrative, scene and character dialogue.
    ("validation/public_authors/cross_work_corpus/dickens/*.txt", "dickens", "creative_fiction",
     "novels: invented persons and events, advanced by scene and dialogue"),
    ("validation/public_authors/cross_work_corpus/christie/*.txt", "christie",
     "creative_fiction", "novels: invented persons and events, advanced by scene and dialogue"),
]

# Post-hoc label corrections, recorded rather than quietly applied.
#
# Honesty requires flagging the timing: this correction was made AFTER the
# first model was evaluated, which is exactly the ordering the codebook-first
# discipline exists to prevent. Three things bound the damage, and a reader
# should weigh them rather than take the correction on trust:
#
#   1. It is justified by the codebook INDEPENDENTLY of the outcome. The
#      deciding test between personal_essay and scholarly_essay is "argument
#      about the world -> scholarly; account of a life -> personal". Emerson's
#      Self-Reliance, Compensation and History argue about the world. The
#      original label was wrong when it was written, not merely inconvenient.
#   2. Emerson is a DERIVATION author. The hold-out (seminary_05, dickens,
#      thoreau, mill, newman, paine) is untouched, so the evaluation set
#      remains independent of this change.
#   3. Thoreau carries the SAME ambiguity — Civil Disobedience argues about
#      the world while Walden recounts a life — and was deliberately NOT
#      relabelled, because he is in the hold-out. Correcting test labels after
#      seeing test results is not a correction, it is fitting.
LABEL_CORRECTIONS = [
    {
        "author": "emerson",
        "from": "personal_essay",
        "to": "scholarly_essay",
        "date": "2026-08-08",
        "post_hoc": True,
        "split": "derivation",
        "reason": (
            "Contradicted the codebook's own deciding test. Confirmed by the "
            "signal profile: Emerson's abstract-noun ratio (0.0296) sits with "
            "Chesterton's scholarly essays (0.0320), not with the "
            "autobiographers Augustine (0.0177) and Douglass (0.0222)."
        ),
    },
]

# Authors held out, chosen per class by sorted name so the split is
# reproducible and was not picked to flatter a result. One third of each
# class's authors, at least one.
HOLDOUT_FRACTION = 3


def _word_count(path: Path) -> int:
    return len(path.read_text(errors="ignore").split())


def build() -> dict:
    by_class: dict[str, list[dict]] = defaultdict(list)
    for pattern, author, label, justification in GROUPS:
        for path in sorted(_ROOT.glob(pattern)):
            if path.name.startswith("_"):  # _full_work_cache.txt and friends
                continue
            if _word_count(path) < MIN_WORDS:
                continue
            by_class[label].append(
                {
                    "path": str(path.relative_to(_ROOT)),
                    "author": author,
                    "label": label,
                    "justification": justification,
                }
            )

    entries: list[dict] = []
    for label, rows in sorted(by_class.items()):
        # Fill the cap evenly across authors: round-robin over each author's
        # own sorted document list, so a prolific author contributes more only
        # once every other author is exhausted.
        per_author: dict[str, list[dict]] = defaultdict(list)
        for row in rows:
            per_author[row["author"]].append(row)
        authors = sorted(per_author)
        kept: list[dict] = []
        index = 0
        while len(kept) < PER_CLASS_CAP:
            added = False
            for author in authors:
                if index < len(per_author[author]) and len(kept) < PER_CLASS_CAP:
                    kept.append(per_author[author][index])
                    added = True
            if not added:
                break
            index += 1

        n_holdout = max(1, len(authors) // HOLDOUT_FRACTION)
        holdout_authors = set(authors[-n_holdout:])
        for row in kept:
            row["split"] = "holdout" if row["author"] in holdout_authors else "derivation"
        entries.extend(kept)

    return {
        "version": 1,
        "codebook_sha256": hashlib.sha256(CODEBOOK.read_bytes()).hexdigest(),
        "classes": sorted(by_class),
        "min_words": MIN_WORDS,
        "per_class_cap": PER_CLASS_CAP,
        "label_corrections": LABEL_CORRECTIONS,
        "entries": sorted(entries, key=lambda e: e["path"]),
    }


def main() -> None:
    payload = build()
    OUT.write_text(json.dumps(payload, indent=1) + "\n")

    from collections import Counter

    per_class = Counter(e["label"] for e in payload["entries"])
    per_split = Counter(e["split"] for e in payload["entries"])
    print(f"wrote {OUT.relative_to(_ROOT)}: {len(payload['entries'])} entries")
    print(f"classes: {dict(per_class)}")
    print(f"splits:  {dict(per_split)}")
    for label in sorted(per_class):
        rows = [e for e in payload["entries"] if e["label"] == label]
        d = sorted({e["author"] for e in rows if e["split"] == "derivation"})
        h = sorted({e["author"] for e in rows if e["split"] == "holdout"})
        print(f"  {label:20s} derivation={d} holdout={h}")


if __name__ == "__main__":
    main()
