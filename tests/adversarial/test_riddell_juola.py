"""
tests/adversarial/test_riddell_juola.py — loader tests for the committed
Riddell-Juola adversarial-stylometry corpus (Task 16).

These tests exercise `load_riddell_juola_split` against the corpus text
already extracted and committed at
validation/adversarial/corpus/riddell_juola/{control,obfuscation,imitation}/
by validation/adversarial/fetch_riddell_juola.py — they do not re-download
or re-extract anything, and require no network access.
"""

from __future__ import annotations

import pytest

from validation.adversarial.fetch_riddell_juola import (
    CORPUS_DIR,
    load_riddell_juola_split,
)

# Counts verified against the live Zenodo bundle (record 18729526,
# rr_bundle.zip, MD5 3b4dbe6edde117d80a0f5e764f594d53) at retrieval time —
# see PROVENANCE.md.
EXPECTED_COUNTS = {
    "control": 21,
    "obfuscation": 27,
    "imitation": 18,
}

MIN_WORDS = 30


@pytest.mark.parametrize("split_name", sorted(EXPECTED_COUNTS))
def test_split_loads_expected_file_count(split_name):
    texts = load_riddell_juola_split(split_name)
    assert len(texts) == EXPECTED_COUNTS[split_name]


@pytest.mark.parametrize("split_name", sorted(EXPECTED_COUNTS))
def test_split_texts_are_real_prose(split_name):
    texts = load_riddell_juola_split(split_name)
    assert texts, f"no texts loaded for split {split_name!r}"
    for text in texts:
        assert isinstance(text, str)
        stripped = text.strip()
        assert stripped, "essay text is empty"
        word_count = len(stripped.split())
        assert word_count >= MIN_WORDS, (
            f"essay in split {split_name!r} has only {word_count} words, "
            f"below the {MIN_WORDS}-word plausible-prose floor"
        )
        # Plausible first-person prose: mostly ASCII letters/punctuation/
        # whitespace, not binary/corrupted content.
        printable_ratio = sum(c.isprintable() or c.isspace() for c in stripped) / len(stripped)
        assert printable_ratio > 0.99


def test_all_three_splits_are_disjoint_by_filename():
    control_dir = CORPUS_DIR / "control"
    obfuscation_dir = CORPUS_DIR / "obfuscation"
    imitation_dir = CORPUS_DIR / "imitation"
    control_ids = {p.name for p in control_dir.glob("*.txt")}
    obfuscation_ids = {p.name for p in obfuscation_dir.glob("*.txt")}
    imitation_ids = {p.name for p in imitation_dir.glob("*.txt")}
    assert control_ids & obfuscation_ids == set()
    assert control_ids & imitation_ids == set()
    assert obfuscation_ids & imitation_ids == set()


def test_unknown_split_name_raises_value_error():
    with pytest.raises(ValueError):
        load_riddell_juola_split("not_a_real_split")


def test_provenance_file_exists_and_documents_key_facts():
    provenance = CORPUS_DIR / "PROVENANCE.md"
    assert provenance.is_file(), f"missing {provenance}"
    text = provenance.read_text(encoding="utf-8")
    assert "10.5281/zenodo.18729526" in text
    assert "CC0" in text
    assert "3b4dbe6edde117d80a0f5e764f594d53" in text
