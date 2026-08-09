"""
tests/validation/test_genre_labels.py — integrity of the hand-labelled genre
corpus.

Task 8 of docs/superpowers/plans/2026-08-08-genre-resolution-v2.md.

These are the structural guarantees standing in for an independent labeller.
The labeller and the implementer are the same agent, so the labels are only
as trustworthy as the constraints that can be checked mechanically.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path

import pytest

_LABELS = Path("validation/genre_2026-08/labels.json")
_CODEBOOK = Path("validation/genre_2026-08/CODEBOOK.md")
_CLASSES = {"academic_exegesis", "scholarly_essay", "personal_essay", "creative_fiction"}


@pytest.fixture(scope="module")
def labels():
    return json.loads(_LABELS.read_text())


class TestLabelCorrections:
    def test_post_hoc_corrections_are_recorded_not_silent(self, labels):
        """A label changed after seeing a model's results must be visible in
        the artifact, with its justification and its split, so a reader can
        weigh it rather than take it on trust."""
        for correction in labels.get("label_corrections", []):
            assert correction["reason"]
            assert correction["date"]
            assert "post_hoc" in correction

    def test_no_correction_touches_a_holdout_author(self, labels):
        """Correcting a test label after seeing test results is not a
        correction, it is fitting. Thoreau carries the same ambiguity as
        Emerson and was deliberately left alone."""
        holdout_authors = {e["author"] for e in labels["entries"] if e["split"] == "holdout"}
        for correction in labels.get("label_corrections", []):
            assert correction["author"] not in holdout_authors


class TestLabelIntegrity:
    def test_every_label_is_in_the_class_set(self, labels):
        assert {e["label"] for e in labels["entries"]} <= _CLASSES

    def test_sermon_is_not_labelled(self, labels):
        """Only one sermon author exists in the corpus (Edwards), so the
        class would be an author detector. See the codebook."""
        assert "sermon" not in {e["label"] for e in labels["entries"]}

    def test_plato_is_not_labelled(self, labels):
        """263 documents resting on a contestable call, in two translations
        so the 'author' is a translator. See the codebook."""
        assert not any("plato" in e["path"].lower() for e in labels["entries"])

    def test_every_referenced_file_exists(self, labels):
        missing = [e["path"] for e in labels["entries"] if not Path(e["path"]).exists()]
        assert missing == []

    def test_every_entry_carries_a_justification(self, labels):
        assert all(e.get("justification") for e in labels["entries"])

    def test_labels_pin_the_codebook_they_were_written_against(self, labels):
        """If the definitions change, the labels must be re-examined rather
        than silently inheriting a new meaning."""
        assert labels["codebook_sha256"] == hashlib.sha256(_CODEBOOK.read_bytes()).hexdigest()


class TestSplitDiscipline:
    def test_the_split_is_author_disjoint(self, labels):
        """A document-level split would let the model score well by
        recognising an author rather than a genre."""
        by_split: dict[str, set[str]] = {}
        for entry in labels["entries"]:
            by_split.setdefault(entry["split"], set()).add(entry["author"])
        assert by_split["derivation"].isdisjoint(by_split["holdout"])

    def test_both_splits_are_non_empty(self, labels):
        counts = Counter(e["split"] for e in labels["entries"])
        assert counts["derivation"] > 0 and counts["holdout"] > 0

    def test_every_class_appears_in_both_splits(self, labels):
        """A class absent from the hold-out cannot be evaluated at all."""
        for split in ("derivation", "holdout"):
            present = {e["label"] for e in labels["entries"] if e["split"] == split}
            assert present == _CLASSES, f"{split} is missing {_CLASSES - present}"

    def test_no_class_is_carried_by_a_single_author(self, labels):
        """A class evidenced by one author is an author detector. This is the
        rule that removed `sermon` from the class set."""
        authors_per_class: dict[str, set[str]] = {}
        for entry in labels["entries"]:
            authors_per_class.setdefault(entry["label"], set()).add(entry["author"])
        thin = {k: sorted(v) for k, v in authors_per_class.items() if len(v) < 2}
        assert thin == {}, f"single-author classes: {thin}"

    def test_no_class_exceeds_half_the_corpus(self, labels):
        """Burke alone has 173 files and would otherwise carry
        scholarly_essay outright."""
        counts = Counter(e["label"] for e in labels["entries"])
        total = sum(counts.values())
        over = {k: v for k, v in counts.items() if v > total / 2}
        assert over == {}, f"class dominates the corpus: {over} of {total}"

    def test_no_author_dominates_its_own_class(self, labels):
        """The per-class cap is filled round-robin across authors so a
        prolific author contributes more only once the others run out."""
        by_class: dict[str, Counter] = {}
        for entry in labels["entries"]:
            by_class.setdefault(entry["label"], Counter())[entry["author"]] += 1
        for label, counts in by_class.items():
            if len(counts) < 3:
                continue  # a 2-author class cannot avoid 50% each
            total = sum(counts.values())
            worst = max(counts.values())
            assert worst <= total * 0.6, f"{label}: one author holds {worst}/{total}"
