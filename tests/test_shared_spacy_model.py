"""The shared spaCy pipeline must measure exactly what the four separate loads did.

Before ``original/features/spacy_model.py`` each spaCy user loaded its own
``en_core_web_sm``: Tier 5 and Tier 11 without ``ner``/``lemmatizer``, the
prosodic tier without ``ner``, and the tension arc with everything. Now one
pipeline is shared and components are switched off per call. These tests run
the old separate loads and the shared one side by side on several texts and
require identical token annotations, an identical full feature vector (raw
and normalised) and an identical tension arc.
"""

from __future__ import annotations

import dataclasses
import math
from pathlib import Path

import numpy as np
import pytest

spacy = pytest.importorskip("spacy")

from original import tension_arc  # noqa: E402
from original.features import prosodic, spacy_model, tier5, tier11  # noqa: E402
from original.features.pipeline import extract_features, extract_raw_features  # noqa: E402

try:
    spacy.load("en_core_web_sm")
except OSError:  # pragma: no cover - CI downloads the model
    pytest.skip("en_core_web_sm not installed", allow_module_level=True)

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "demo" / "bluebook" / "e2e" / "fixtures" / "evidence"
CORPUS = ROOT / "validation" / "public_authors" / "corpus"


def _texts() -> list[str]:
    texts = [p.read_text(encoding="utf-8") for p in sorted(FIXTURES.glob("*.txt"))]
    for path in sorted(CORPUS.glob("*/*part_01.txt"))[:3]:
        texts.append(path.read_text(encoding="utf-8", errors="replace")[2000:9000])
    texts.append(
        "Short one. The committee, which met twice, couldn't agree; nobody was surprised!\n\n"
        "\u201cWell,\u201d she said \u2014 and then, quite suddenly, she left the room."
    )
    return texts


TEXTS = _texts()


def _install(mods: dict[str, object], monkeypatch) -> None:
    monkeypatch.setattr(tier5, "_nlp", mods["tier5"])
    monkeypatch.setattr(tier11, "_nlp", mods["tier11"])
    monkeypatch.setattr(prosodic, "_nlp", mods["prosodic"])
    monkeypatch.setattr(prosodic, "_spacy_ok", True)
    monkeypatch.setattr(tension_arc, "_nlp", mods["tension_arc"])
    monkeypatch.setattr(tension_arc, "_spacy_available", True)


@pytest.fixture(scope="module")
def separate():
    """The four pipelines exactly as the modules used to load them."""
    return {
        "tier5": spacy.load("en_core_web_sm", disable=["ner", "lemmatizer"]),
        "tier11": spacy.load("en_core_web_sm", disable=["ner", "lemmatizer"]),
        "prosodic": spacy.load("en_core_web_sm", disable=["ner"]),
        "tension_arc": spacy.load("en_core_web_sm"),
    }


@pytest.fixture
def shared(monkeypatch):
    """The modules' own loaders, starting from nothing cached."""
    monkeypatch.setattr(tier5, "_nlp", None)
    monkeypatch.setattr(tier11, "_nlp", None)
    monkeypatch.setattr(prosodic, "_nlp", None)
    monkeypatch.setattr(prosodic, "_spacy_ok", None)
    monkeypatch.setattr(tension_arc, "_nlp", None)
    monkeypatch.setattr(tension_arc, "_spacy_available", None)
    # Keep load_models() to spaCy: no sentence-transformers download here.
    monkeypatch.setattr(tension_arc, "_embedder", object())
    nlp_arc = tension_arc._get_nlp()
    monkeypatch.setattr(tension_arc, "_embedder", None)
    monkeypatch.setattr(tension_arc, "_embedder_available", False)
    return {
        "tier5": tier5._get_nlp(),
        "tier11": tier11._get_nlp(),
        "prosodic": prosodic._get_nlp(),
        "tension_arc": nlp_arc,
    }


def _annotations(doc) -> list[tuple]:
    rows = [
        (t.text, t.idx, t.tag_, t.pos_, t.dep_, t.head.i, t.lemma_, t.ent_type_, t.is_sent_start)
        for t in doc
    ]
    return rows + [("ents", tuple((e.start, e.end, e.label_) for e in doc.ents))]


def _same(a, b) -> bool:
    if isinstance(a, float) and isinstance(b, float) and math.isnan(a) and math.isnan(b):
        return True
    return a == b


def test_one_model_is_loaded_and_shared(shared):
    base = shared["tension_arc"]
    assert shared["tier5"]._nlp is base
    assert shared["tier11"]._nlp is base
    assert shared["prosodic"]._nlp is base
    assert shared["tier5"].disabled == ("ner", "lemmatizer")
    assert shared["tier11"].disabled == ("ner", "lemmatizer")
    assert shared["prosodic"].disabled == ("ner",)
    assert spacy_model.shared_nlp() is base
    assert shared["prosodic"].vocab is base.vocab


@pytest.mark.parametrize("name", ["tier5", "tier11", "prosodic", "tension_arc"])
def test_every_view_annotates_exactly_like_its_old_load(name, separate, shared):
    for text in TEXTS:
        assert _annotations(shared[name](text)) == _annotations(separate[name](text)), name


def test_full_feature_vector_is_identical(separate, shared, monkeypatch):
    shared_mods = dict(shared)
    new_raw = [extract_raw_features(t) for t in TEXTS]
    new_norm = [extract_features(t) for t in TEXTS]
    _install(separate, monkeypatch)
    old_raw = [extract_raw_features(t) for t in TEXTS]
    old_norm = [extract_features(t) for t in TEXTS]
    _install(shared_mods, monkeypatch)  # leave the shared views in place
    for old, new in zip(old_raw + old_norm, new_raw + new_norm, strict=True):
        assert old.keys() == new.keys()
        diff = [k for k in old if not _same(old[k], new[k])]
        assert diff == [], diff
    # Sanity: the spaCy-backed features really ran (not the fallbacks).
    assert any(v for v in new_raw[0].values())


def test_tension_arc_is_identical(separate, shared, monkeypatch):
    shared_mods = dict(shared)
    new = [dataclasses.asdict(tension_arc.analyze_tension_arc(t)) for t in TEXTS]
    _install(separate, monkeypatch)
    old = [dataclasses.asdict(tension_arc.analyze_tension_arc(t)) for t in TEXTS]
    _install(shared_mods, monkeypatch)
    assert repr(old) == repr(new)


def test_missing_model_still_raises_to_the_caller(monkeypatch):
    import sys
    import types

    def _raise_load(name, disable=None):
        raise OSError("model 'en_core_web_sm' not found")

    fake = types.ModuleType("spacy")
    fake.load = _raise_load
    monkeypatch.setitem(sys.modules, "spacy", fake)
    with pytest.raises(OSError):
        spacy_model.load_view(disable=("ner",))


def test_view_passes_pipe_and_attributes_through(shared):
    view = shared["tier5"]
    docs = list(view.pipe(TEXTS[:2]))
    assert [_annotations(d) for d in docs] == [_annotations(view(t)) for t in TEXTS[:2]]
    assert view.pipe_names == view._nlp.pipe_names
    np.testing.assert_equal(view.meta["name"], "core_web_sm")
