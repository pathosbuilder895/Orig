"""The evidence path never runs the full feature extraction again (ADR-013).

On 2026-11-17 analysing a paper for a pilot student whose past papers ran to
6,400 and 9,700 words took the pilot down: every scoring request re-ran the
whole extraction on the submission and on every past paper for the
side-by-side page, and its whole-paper spaCy parses took a warm process from
about 325 MB to over 500 MB, past the 512 MB instance. Render answered 502
until the process restarted.

What these pin:
* with the engine's own vectors (the API) building the evidence calls no
  spaCy pipeline, no sentence embedding and no tension arc, even on a paper
  long enough to pass the tension arc's word guard;
* the raw values it does compute are the extractor's own, and they cover
  every habit the pages show in plain units except Tier 5's seven;
* Tier 5's plain values, read back from a vector, are the extractor's own
  wherever the 0–1 value is inside the scale, and a value at an end of the
  scale shows that measurement on the 0 to 1 scale only, never a guess.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from original import evidence as ev
from original.constants import ALL_FEATURE_CODES, FEATURE_TIER, NORM_BOUNDS
from original.evidence_features import feature_info
from original.features.pipeline import extract_features, extract_raw_features
from tests.test_evidence import EDGE, PLAIN

BASELINES = [(f"past paper {i + 1}", t) for i, t in enumerate(PLAIN)]
TIER5 = [c for c in ALL_FEATURE_CODES if FEATURE_TIER[c] == 5]
# Long enough (and in paragraphs) that the tension arc would parse it.
LONG = "\n\n".join([EDGE, *PLAIN] * 4)


def _vector(text: str) -> list[float]:
    feats = extract_features(text)
    return [feats[c] for c in ALL_FEATURE_CODES]


def _plain_whole_text_codes() -> set[str]:
    info = feature_info()
    return {
        c
        for c in ALL_FEATURE_CODES
        if info[c]["kind"] == "measured" and c not in ev.LOCATABLE and info[c]["unit"] is not None
    }


@pytest.mark.parametrize("text", [EDGE, LONG, *PLAIN])
def test_light_values_are_the_extractors_own(text):
    full = extract_raw_features(text)
    light = ev._light_raw.__wrapped__(text)
    assert light and set(light) <= set(full)
    for code, value in light.items():
        assert value == full[code], code
    # Every habit shown in plain units is computed here, or is Tier 5's.
    assert _plain_whole_text_codes() - set(light) == set(TIER5)


def test_evidence_with_engine_vectors_runs_no_full_extraction(monkeypatch):
    assert len(LONG.split()) > 200
    sub_vec = _vector(LONG)
    past = [("past paper 1", LONG), *BASELINES]
    past_vecs = [_vector(t) for _, t in past]
    ev._light_raw.cache_clear()
    ev._paper_values.cache_clear()
    ev.engine_view.cache_clear()

    def boom(*_a, **_k):
        raise AssertionError("full extraction or a spaCy parse on the evidence path")

    import original.features.pipeline as pipeline
    import original.features.prosodic as prosodic
    import original.features.tier5 as tier5
    import original.features.tier11 as tier11
    import original.tension_arc as tension_arc
    from original.features import tier1

    monkeypatch.setattr(pipeline, "extract_raw_features", boom)
    monkeypatch.setattr(tension_arc, "analyze_tension_arc", boom)
    for mod in (tier5, tier11, prosodic):
        monkeypatch.setattr(mod, "_get_nlp", boom)
    monkeypatch.setattr(tier1.TextDoc, "spacy_doc", property(boom))
    feats = [{"code": "comma_rate", "submission_value": 0.0, "baseline_value": 0.0, "delta": 0.0}]
    out = ev.build_evidence(
        feats, LONG, past, all_features=True, submission_vector=sub_vec, baseline_vectors=past_vecs
    )
    assert len(out["all_features"]) == len(ALL_FEATURE_CODES)


def test_read_back_matches_the_full_extraction_inside_the_scale():
    texts = [EDGE] + [t for _, t in BASELINES]
    vectors = [_vector(t) for t in texts]
    ev._light_raw.cache_clear()
    full = {f["code"]: f for f in ev.build_all_features(EDGE, BASELINES)}
    fast = {
        f["code"]: f
        for f in ev.build_all_features(
            EDGE, BASELINES, submission_vector=vectors[0], baseline_vectors=vectors[1:]
        )
    }
    compared = 0
    for code in TIER5:
        d = ALL_FEATURE_CODES.index(code)
        if not all(0.0 < v[d] < 1.0 for v in vectors):
            assert "plain" not in fast[code]
            assert fast[code]["plain_note"] == ev.PLAIN_UNREADABLE_NOTE
            continue
        a, b = full[code]["plain"], fast[code]["plain"]
        assert a["unit"] == b["unit"]
        assert b["this_paper"] == pytest.approx(a["this_paper"], abs=1e-3)
        for x, y in zip(a["past_papers"], b["past_papers"], strict=True):
            assert y["value"] == pytest.approx(x["value"], abs=1e-3)
        compared += 1
    assert compared >= 3
    # Every other measurement reads the same either way.
    for code in ALL_FEATURE_CODES:
        if code not in TIER5:
            assert fast[code].get("plain") == full[code].get("plain"), code


def test_a_value_at_an_end_of_the_scale_is_never_read_back():
    code = TIER5[0]
    lo, hi = NORM_BOUNDS[code]
    assert ev._unnormalise(0.25, code) == pytest.approx(lo + 0.25 * (hi - lo))
    for edge in (0.0, 1.0, -0.1, 1.5, float("nan")):
        assert math.isnan(ev._unnormalise(edge, code))
    assert math.isnan(ev._unnormalise(0.5, "not_a_feature"))
    vectors = [_vector(t) for _, t in BASELINES]
    sub = _vector(EDGE)
    sub[ALL_FEATURE_CODES.index(code)] = 1.0
    out = {
        f["code"]: f
        for f in ev.build_all_features(
            EDGE, BASELINES, submission_vector=np.array(sub), baseline_vectors=vectors
        )
    }
    assert "plain" not in out[code] and out[code]["plain_note"] == ev.PLAIN_UNREADABLE_NOTE
    assert out[code]["kind"] == "whole_text" and out[code]["engine_scale"]["this_paper"] == 1.0


def test_a_short_vector_list_is_still_refused():
    with pytest.raises(ValueError):
        ev.build_all_features(EDGE, BASELINES, baseline_vectors=[_vector(PLAIN[0])])


# ── A side that never uses a habit the other side uses (2026-11-17) ──────────

NO_COMMAS = (
    "The lighthouse stands at the end of the point. It is white. The paint is old now. "
    "My uncle kept the light for nine years and he never missed a single night of it. "
    "He climbed the stairs at dusk and lit the lamp and checked the lens for dust. "
    "Then he sat by the window and watched the sea until the morning came back."
)
COMMAS = (
    "My grandmother, who kept a garden, taught me patience. I learned, slowly, to wait. "
    "Seeds, frost and slugs do not care about plans, and rain can undo a month of work."
)


def test_a_side_without_the_habit_shows_its_longest_sentences_verbatim():
    feat = {"code": "comma_rate", "submission_value": 0.0, "baseline_value": 0.5, "delta": -0.5}
    out = ev.build_feature_evidence(feat, NO_COMMAS, [("past paper 1", COMMAS)], rank=1)
    this = out["this_paper"]
    assert this["count"] == 0 and this["examples"] == []
    assert out["note"] == "No comma appears in this paper."
    um = this["unmarked"]
    assert len(um) == 3
    assert [q["words"] for q in um] == sorted((q["words"] for q in um), reverse=True)
    for q in um:
        assert q["paper"] == "this paper" and "," not in q["passage"]
        assert q["passage"] == NO_COMMAS[q["passage_start"] : q["passage_end"]]
        assert "match" not in q
    assert um[0]["passage"].startswith("My uncle kept the light")
    assert "unmarked" not in out["past_papers"]

    # And the other way round: the past papers never use it, this paper does.
    back = ev.build_feature_evidence(
        {**feat, "delta": 0.5},
        COMMAS,
        [("past paper 1", NO_COMMAS), ("past paper 2", NO_COMMAS)],
        rank=1,
    )
    pu = back["past_papers"]["unmarked"]
    assert back["note"] == "No comma appears in the past papers."
    assert [q["paper"] for q in pu] == ["past paper 1", "past paper 2", "past paper 1"]
    assert all(q["passage"] == NO_COMMAS[q["passage_start"] : q["passage_end"]] for q in pu)
    assert "unmarked" not in back["this_paper"]


def test_unmarked_fails_closed_and_is_never_added_when_both_sides_lack_the_habit(monkeypatch):
    feat = {"code": "dash_rate", "submission_value": 0.0, "baseline_value": 0.0, "delta": 0.0}
    out = ev.build_feature_evidence(feat, NO_COMMAS, [("past paper 1", NO_COMMAS)], rank=1)
    assert "unmarked" not in out["this_paper"] and "unmarked" not in out["past_papers"]
    monkeypatch.setattr(ev, "engine_view", lambda text: None)
    assert ev._unmarked(NO_COMMAS, "this paper", 3) == []
