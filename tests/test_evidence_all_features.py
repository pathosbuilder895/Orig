"""Every measurement in the vector on the staff evidence pages (ADR-013).

What these pin:
* every code in ``ALL_FEATURE_CODES`` appears exactly once, in a documented,
  deterministic order (the engine's |difference| × group weight, ties in
  registry order);
* the 0–1 values are the engine's own (``extract_features``) and the
  past-paper average is ``StudentState.baseline_mean``'s recency weighting;
* every quote in the full list is a verbatim slice of its stored text;
* switched-off and placeholder measurements say so and never differ;
* the descriptions table covers the vector and uses none of the banned words.
"""

from __future__ import annotations

import html
import json
import re

import numpy as np
import pytest

from original import evidence as ev
from original.constants import (
    ALL_FEATURE_CODES,
    COMPARISON_CODES,
    DISABLED_FEATURE_GROUPS,
    FEATURE_DIM,
    FEATURE_TIER,
    MUSICAL_COMPARISON_CODES,
    TIER17_CODES,
    TIER18_CODES,
    TIER_WEIGHTS,
)
from original.evidence_features import feature_info
from original.features.baseline_scope import NOT_COMPUTED_FOR_BASELINES
from original.features.pipeline import _normalise, extract_features, extract_raw_features
from original.quantum.state import BaselineSample, StudentState
from tests.test_evidence import EDGE, PLAIN, _corpus_texts

BASELINES = [(f"past paper {i + 1}", t) for i, t in enumerate(PLAIN)]
BANNED = re.compile(r"(?-i:\bAI\b)|AI detection|cheat|authorship verification|plagiar|misconduct", re.I)


@pytest.fixture(scope="module")
def full_evidence():
    feats = [{"code": "comma_rate", "submission_value": 0.0, "baseline_value": 0.0, "delta": 0.0}]
    return ev.build_evidence(feats, EDGE, BASELINES, all_features=True)


def test_descriptions_cover_the_vector_exactly_and_honestly():
    info = feature_info()
    assert list(info) != [] and set(info) == set(ALL_FEATURE_CODES) and len(info) == FEATURE_DIM
    for code, meta in info.items():
        assert meta["description"] and not BANNED.search(meta["description"]), code
        assert meta["kind"] in {"measured", "off", "not_compared"}
    off = {c for c in ALL_FEATURE_CODES if info[c]["kind"] == "off"}
    expected_off = (set(TIER17_CODES) if "behavioral" in DISABLED_FEATURE_GROUPS else set()) | (
        set(TIER18_CODES) if "uniformity" in DISABLED_FEATURE_GROUPS else set()
    )
    assert off == expected_off
    not_compared = {c for c in ALL_FEATURE_CODES if info[c]["kind"] == "not_compared"}
    assert not_compared == set(MUSICAL_COMPARISON_CODES) | set(COMPARISON_CODES)
    assert not_compared == set(NOT_COMPUTED_FOR_BASELINES)
    for code in not_compared:
        # The #318 text said every paper gets 0.5; the scored paper does not.
        assert "every paper, past or new" not in info[code]["description"]
        assert "not for the past papers themselves" in info[code]["description"]
    assert ev.KIND_WORDS["not_compared"] == "not compared: past papers have no value for this"
    for word in [ev.WHOLE_TEXT_NOTE, ev.ALL_FEATURES_ORDERING, ev.AVERAGE_DIFFERS_NOTE, *ev.KIND_WORDS.values()]:
        assert not BANNED.search(word)


def test_raw_extraction_is_exactly_what_extract_features_normalises():
    for text in (EDGE, PLAIN[0]):
        raw = extract_raw_features(text)
        norm = extract_features(text)
        for code, value in norm.items():
            expected = _normalise(raw[code], code) if code in raw else 0.5
            assert value == expected, code


def test_every_feature_appears_exactly_once_in_a_documented_order(full_evidence):
    full = full_evidence["all_features"]
    assert full_evidence["feature_count"] == FEATURE_DIM == len(full)
    codes = [f["code"] for f in full]
    assert sorted(codes) == sorted(ALL_FEATURE_CODES) and len(set(codes)) == FEATURE_DIM
    assert [f["rank"] for f in full] == list(range(1, FEATURE_DIM + 1))
    keys = []
    n_compared = sum(f["kind"] != "not_compared" for f in full)
    # Not-compared measurements come last, in registry order, with no size.
    tail = full[n_compared:]
    assert [f["code"] for f in tail] == [c for c in ALL_FEATURE_CODES if c in NOT_COMPUTED_FOR_BASELINES]
    assert all(f["kind"] == "not_compared" and f["engine_scale"]["weighted_size"] is None for f in tail)
    for f in full[:n_compared]:
        eng = f["engine_scale"]
        size = abs(eng["this_paper"] - eng["past_papers_average"]) * TIER_WEIGHTS[FEATURE_TIER[f["code"]]]
        assert eng["weighted_size"] == pytest.approx(size, abs=2e-4)
        keys.append((-round(eng["weighted_size"], 4), ALL_FEATURE_CODES.index(f["code"])))
    # Sizes never increase down the list; equal sizes keep registry order.
    for (a_size, a_idx), (b_size, b_idx) in zip(keys, keys[1:], strict=False):
        assert a_size <= b_size + 2e-4
        if a_size == b_size and a_size == 0:
            assert a_idx < b_idx
    assert full_evidence["all_features_ordering"] == ev.ALL_FEATURES_ORDERING


def test_values_are_the_engines_and_the_average_is_recency_weighted(full_evidence):
    this = extract_features(EDGE)
    past = [extract_features(t) for _, t in BASELINES]
    state = StudentState(student_id="s")
    for t, vec in zip(PLAIN, past, strict=True):
        state.samples.append(
            BaselineSample(
                text=t,
                vector=np.array([vec[c] for c in ALL_FEATURE_CODES]),
                provenance="verified",
                auth_weight=1.0,
            )
        )
    mean = state.baseline_mean
    for f in full_evidence["all_features"]:
        d = ALL_FEATURE_CODES.index(f["code"])
        eng = f["engine_scale"]
        if f["kind"] == "not_compared":
            # Recomputed from the text, this paper only has the stand-in too:
            # nothing on either side is shown or compared.
            assert eng["this_paper"] is None and eng["past_papers_average"] is None
            assert [p["value"] for p in eng["past_papers"]] == [None] * len(past)
            assert eng["past_range"] is None and eng["outside_past_range"] is None
            continue
        assert eng["this_paper"] == round(this[f["code"]], 4)
        assert [p["value"] for p in eng["past_papers"]] == [round(v[f["code"]], 4) for v in past]
        assert eng["past_papers_average"] == pytest.approx(mean[d], abs=1e-4)
        lo, hi = min(v[f["code"]] for v in past), max(v[f["code"]] for v in past)
        assert eng["outside_past_range"] == (not lo - 1e-9 <= this[f["code"]] <= hi + 1e-9)
        if f["direction"] == "higher":
            assert eng["difference"] > 0
        elif f["direction"] == "lower":
            assert eng["difference"] < 0
    assert ev.recency_weighted_mean([]) == [0.5] * FEATURE_DIM


def test_kinds_notes_and_off_or_placeholder_measurements(full_evidence):
    by_code = {f["code"]: f for f in full_evidence["all_features"]}
    info = feature_info()
    for code, f in by_code.items():
        if info[code]["kind"] == "off":
            assert f["kind"] == "off" and f["engine_scale"]["difference"] == 0
            assert f["direction"] == "same" and "plain" not in f and f["locatable"] is False
        elif info[code]["kind"] == "not_compared":
            assert f["kind"] == "not_compared" and f["engine_scale"]["difference"] is None
            assert f["direction"] == "not_compared" and "plain" not in f and f["locatable"] is False
            assert f["note"] == "Not compared: past papers have no value for this."
            assert f["in_top_list"] is False
        elif code in ev.LOCATABLE:
            assert f["kind"] == "located" and f["locatable"] is True
            assert "examples" in f["this_paper"] and f["plain"]["unit"] == ev.LOCATABLE[code].unit
        else:
            assert f["kind"] == "whole_text" and f["note"] == ev.WHOLE_TEXT_NOTE
            assert ("plain" in f) == (info[code]["unit"] is not None)
            assert ("plain_note" in f) == (info[code]["unit"] is None)
    assert sum(f["kind"] == "located" for f in by_code.values()) == len(ev.LOCATABLE)
    assert by_code["comma_rate"]["in_top_list"] is True
    assert sum(f["in_top_list"] for f in by_code.values()) == 1


def test_every_quote_in_the_full_list_is_an_exact_slice(full_evidence):
    sources = {"this paper": EDGE, **dict(BASELINES)}
    n = 0
    for f in full_evidence["all_features"]:
        for side in ("this_paper", "past_papers"):
            for q in f.get(side, {}).get("examples", []) if f["kind"] == "located" else []:
                source = sources[q["paper"]]
                assert q["passage"] == source[q["passage_start"] : q["passage_end"]]
                assert q["match"] == source[q["match_start"] : q["match_end"]]
                n += 1
    assert n > 30


def test_deterministic_with_nothing_cached(full_evidence):
    feats = [{"code": "comma_rate", "submission_value": 0.0, "baseline_value": 0.0, "delta": 0.0}]
    ev._paper_values.cache_clear()
    ev.engine_view.cache_clear()
    again = ev.build_evidence(feats, EDGE, BASELINES, all_features=True)
    assert json.dumps(again, sort_keys=True) == json.dumps(full_evidence, sort_keys=True)
    assert ev.render_html("s", again, None) == ev.render_html("s", full_evidence, None)
    assert ev.render_markdown("s", again, None) == ev.render_markdown("s", full_evidence, None)


def test_markdown_and_html_list_each_measurement_once_with_a_contents(full_evidence):
    md = ev.render_markdown("sub-1", full_evidence, None)
    assert f"## All {FEATURE_DIM} measurements, largest difference first" in md
    assert md.index("## Biggest differences") < md.index("## All ") < md.index("## Every measurement")
    detail = md[md.index("## Every measurement in detail") :]
    for f in full_evidence["all_features"]:
        assert detail.count(f"`{f['code']}` · group") == 1
    assert detail.count(ev.WHOLE_TEXT_NOTE) == sum(
        f["kind"] == "whole_text" for f in full_evidence["all_features"]
    )
    assert "Every countable habit" not in md  # the full list replaces the old overview table
    html_out = ev.render_html("sub-1", full_evidence, None)
    assert html_out.count("<details id='f-") == FEATURE_DIM
    assert html_out.count("<li><a href='#f-") == FEATURE_DIM
    for f in full_evidence["all_features"]:
        assert html_out.count(f"id='f-{f['code']}'") == 1
        assert f"href='#f-{f['code']}'" in html_out
    assert "<nav><h2>Contents</h2>" in html_out and "id='top'" in html_out and "id='all'" in html_out
    assert not BANNED.search(re.sub(r"<[^>]+>", " ", html_out).replace(EDGE, ""))


def test_engine_vectors_pass_through_and_a_different_average_is_noted():
    sub = {c: 0.5 for c in ALL_FEATURE_CODES}
    sub["dash_rate"] = 0.9
    vectors = [[0.5] * FEATURE_DIM for _ in BASELINES]
    mean = [0.5] * FEATURE_DIM
    feats = [{"code": "dash_rate", "submission_value": 0.9, "baseline_value": 0.2, "delta": 0.7}]
    out = ev.build_evidence(
        feats,
        EDGE,
        BASELINES,
        all_features=True,
        submission_vector=sub,
        baseline_vectors=vectors,
        past_average=np.array(mean),
    )
    first = out["all_features"][0]
    assert first["code"] == "dash_rate" and first["engine_scale"]["difference"] == 0.4
    assert all(
        f["engine_scale"]["difference"] == (None if f["kind"] == "not_compared" else 0)
        for f in out["all_features"][1:]
    )
    # The engine's own value for a not-compared measurement is shown, nothing else.
    tail = [f for f in out["all_features"] if f["kind"] == "not_compared"]
    assert len(tail) == 7 and all(f["engine_scale"]["this_paper"] == 0.5 for f in tail)
    assert out["past_average_matches_top_list"] is False
    assert ev.AVERAGE_DIFFERS_NOTE in ev.render_markdown("s", out, None)
    assert html.escape(ev.AVERAGE_DIFFERS_NOTE) in ev.render_html("s", out, None)
    with pytest.raises(ValueError):
        ev.build_all_features(EDGE, BASELINES, baseline_vectors=vectors[:1])
    no_past = ev.build_all_features(EDGE, [])
    assert len(no_past) == FEATURE_DIM
    assert all(f["engine_scale"]["past_range"] is None for f in no_past)


def test_api_lists_every_feature_with_the_engines_numbers(live_client, store_reset, monkeypatch):
    monkeypatch.setenv("EVIDENCE_PASSAGES_ENABLED", "1")
    sid = "evidence_all_api"
    for text in _corpus_texts(3):
        r = live_client.post(f"/students/{sid}/baseline", json={"text": text, "provenance": "verified"})
        assert r.status_code == 200, r.text[:300]
    text = _corpus_texts(4)[3]
    body = live_client.post(f"/students/{sid}/score", json={"text": text, "submission_id": "a1"}).json()
    full = body["evidence"]["all_features"]
    assert sorted(f["code"] for f in full) == sorted(ALL_FEATURE_CODES)
    by_code = {f["code"]: f["engine_scale"] for f in full}
    top = {f["code"] for f in full if f["in_top_list"]}
    assert top == {f["code"] for f in body["interference"]["destructive_features"]}
    for f in body["interference"]["destructive_features"]:
        assert by_code[f["code"]]["this_paper"] == pytest.approx(f["submission_value"], abs=1e-4)
        assert by_code[f["code"]]["past_papers_average"] == pytest.approx(
            f["baseline_value"], abs=1e-4
        )
    assert body["evidence"]["past_average_matches_top_list"] is True


def test_a_code_outside_the_vector_keeps_an_empty_description():
    feats = [{"code": "not_a_feature", "submission_value": 0.6, "baseline_value": 0.4, "delta": 0.2}]
    out = ev.build_evidence(feats, EDGE, BASELINES[:1])
    assert out["features"][0]["description"] == ""
    assert "## 1. not_a_feature" in ev.render_markdown("s", out, None)
    assert "<p></p>" not in ev.render_html("s", out, None)
