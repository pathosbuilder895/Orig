"""Located evidence passages and the preliminary score (ADR-013).

What these pin:
* every quote is a verbatim slice of the stored text at its recorded offsets;
* located places are exactly what the engine's own measurement counted;
* same input -> same evidence;
* both features are off by default and never reach a student session.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from original import evidence as ev
from original.constants import ALL_FEATURE_CODES, FEATURE_DIM
from original.evidence_features import feature_info
from original.features import preprocess as pp
from original.features.pipeline import extract_features
from original.features.tier1 import TextDoc

ROOT = Path(__file__).resolve().parents[1]
CORPUS = ROOT / "validation" / "public_authors" / "corpus"

EDGE = (
    "However, the market at night was loud; vendors shouted, and children ran between the stalls.  "
    "I think it's the best place in town -- perhaps the best in the state. Why do people go there?\n\n"
    "Because the food is cheap: noodles, dumplings (with chili oil), and \u201cfresh\u201d juice "
    "(Smith, 2020). Furthermore, the lights are beautiful \u2014 really.^3 Dr. Lee said \"yes\" once.\n"
    "    This indented line is a block quotation and is set aside by the engine before measuring.\n"
    "But the crowds can be overwhelming; therefore, I usually go early. It's clearly worth it, "
    "as Mill argues. And so it goes: the stalls were packed by the vendors who were tired.\n\n"
    "References\nSmith, J. (2020). Night markets. Press."
)
PLAIN = [
    "The town library is a quiet place. I go there every Saturday morning with my sister. We read for "
    "hours and then we walk home through the park; the librarians know us by name.",
    "My grandmother taught me to cook rice. She measured the water with her finger and never used a cup. "
    "The rice was always perfect, and the kitchen smelled of ginger and garlic.",
    "Last summer I worked at a hardware store. The work was hard but the owner was kind. I learned how "
    "to cut keys and mix paint for customers who came in every day: it was a good job.",
]
LONG_SENTENCE = ("But " + "the long road wound on past fields and farms and rivers, " * 20).strip() + " and ended here. Short one."
# A genuine long quotation (> 40 words) that preprocess sets aside.
LONG_QUOTE = '"' + "the words of another writer quoted at length here " * 12 + 'end."'
QUOTE_GAP = "He quoted it once. " + LONG_QUOTE + " Then he left."


def _corpus_texts(limit=6):
    files = sorted(CORPUS.glob("*/*part_01.txt"))[:limit]
    return [f.read_text(encoding="utf-8", errors="replace")[2000:9000] for f in files]


SHORT_LONG_QUOTE = ('She wrote "' + "extraordinarily " * 14 + 'extraordinarily" twice; it stayed. ' + PLAIN[0])

ALL_TEXTS = [EDGE, LONG_SENTENCE, QUOTE_GAP, SHORT_LONG_QUOTE, *PLAIN, *_corpus_texts()]


@pytest.mark.parametrize("index", range(len(ALL_TEXTS)))
def test_engine_view_rebuilds_the_engines_strings_exactly(index):
    text = ALL_TEXTS[index]
    view = ev.engine_view(text)
    assert view is not None
    assert view.prose.text == pp.preprocess(text)[0]
    assert view.clean.text == TextDoc(view.prose.text).clean
    for level in (view.prose, view.clean):
        assert len(level.origin) == len(level.text)
        real = [o for o in level.origin if o >= 0]
        assert real == sorted(real)
        # Every mapped non-space character is the same character in the stored text.
        for ch, o in zip(level.text, level.origin):
            if o >= 0 and not ch.isspace():
                assert text[o] == ch


@pytest.mark.parametrize("index", range(len(ALL_TEXTS)))
def test_every_locatable_habit_is_located_and_counts_match_the_engine(index):
    text = ALL_TEXTS[index]
    doc = TextDoc(pp.preprocess(text)[0])
    for code, spec in ev.LOCATABLE.items():
        reading = ev.read_paper(text, code)
        assert reading.places is not None, code
        assert reading.value == spec.value(doc)
        if spec.sentence_length is None:
            assert spec.formula(len(reading.places), doc) == pytest.approx(reading.value, abs=1e-12)
        for place in reading.places:
            assert 0 <= place.sentence_start <= place.start < place.end <= len(text)
            assert place.sentence_start < place.sentence_end <= len(text)


def test_locatable_codes_are_real_active_features_in_engine_order():
    from original.constants import ALL_FEATURE_CODES, DISABLED_FEATURE_GROUPS, FEATURE_TIER

    order = [c for c in ALL_FEATURE_CODES if c in ev.LOCATABLE]
    assert list(ev.LOCATABLE) == order
    assert all(FEATURE_TIER[c] in (1, 2, 3, 4, 6) for c in ev.LOCATABLE)
    assert DISABLED_FEATURE_GROUPS  # tiers 17/18 stay out of this list
    assert set(ev.LOCATABLE) <= set(extract_features(PLAIN[0]))


def _all_quotes(evidence):
    for feature in evidence["features"]:
        for side in ("this_paper", "past_papers"):
            for q in feature.get(side, {}).get("examples", []):
                yield q


def _feature(code, delta=0.3):
    return {"code": code, "submission_value": 0.7, "baseline_value": 0.4, "delta": delta}


def test_every_quote_is_a_verbatim_slice_at_its_offsets():
    baselines = [(f"past paper {i + 1}", t) for i, t in enumerate(PLAIN)]
    sources = {"this paper": EDGE, **dict(baselines)}
    feats = [_feature(c, 0.3 if i % 2 else -0.3) for i, c in enumerate(ev.LOCATABLE)]
    evidence = ev.build_evidence(feats, EDGE, baselines, top_n=len(feats))
    quotes = list(_all_quotes(evidence))
    assert len(quotes) > 30
    for q in quotes:
        source = sources[q["paper"]]
        assert q["passage"] == source[q["passage_start"]:q["passage_end"]]
        assert q["match"] == source[q["match_start"]:q["match_end"]]
        assert q["passage_start"] <= q["match_start"] <= q["match_end"] <= q["passage_end"]
        assert q["start"] <= q["match_start"] and q["match_end"] <= q["end"]
        assert len(q["passage"]) <= ev.MAX_QUOTE_CHARS + 40
    # Nothing the engine set aside is quoted as a counted place: the citation and back matter are gone.
    assert not any("Smith, 2020" in q["match"] or "Night markets" in q["match"] for q in quotes)


def test_long_sentences_are_clipped_to_a_verbatim_window():
    evidence = ev.build_evidence([_feature("sentence_initial_conjunction_rate"), _feature("mean_sentence_length")],
                                 LONG_SENTENCE, [("past paper 1", LONG_SENTENCE)])
    quotes = list(_all_quotes(evidence))
    assert any(q["clipped_end"] for q in quotes)
    for q in quotes:
        assert q["passage"] == LONG_SENTENCE[q["passage_start"]:q["passage_end"]]
        assert len(q["passage"]) <= ev.MAX_QUOTE_CHARS
        assert not q["passage"].endswith(" ")


def test_short_matches_inside_long_sentences_get_a_window_around_them():
    text = "First words here " + ", ".join(["one thing"] * 80) + "; then the end."
    evidence = ev.build_evidence([_feature("semicolon_colon_rate")], text, [("past paper 1", PLAIN[0])])
    (q,) = evidence["features"][0]["this_paper"]["examples"]
    assert q["match"] == ";" and q["clipped_start"] and not q["clipped_end"]
    assert q["passage"] == text[q["passage_start"]:q["passage_end"]]


def test_evidence_is_deterministic():
    baselines = [(f"past paper {i + 1}", t) for i, t in enumerate(PLAIN)]
    feats = [_feature("transition_density"), _feature("char_trigram_entropy"), _feature("comma_rate", -0.2)]
    first = json.dumps(ev.build_evidence(feats, EDGE, baselines), sort_keys=True)
    ev.engine_view.cache_clear()
    ev._kept_cached.cache_clear()
    second = json.dumps(ev.build_evidence(feats, EDGE, baselines), sort_keys=True)
    assert first == second
    assert ev.render_markdown("s", json.loads(first), None) == ev.render_markdown("s", json.loads(second), None)


def test_statistical_habits_are_numbers_only_and_labelled():
    evidence = ev.build_evidence([_feature("char_trigram_entropy"), _feature("perplexity_proxy")], EDGE,
                                 [("past paper 1", PLAIN[0])])
    for feature in evidence["features"]:
        assert feature["locatable"] is False
        assert feature["note"] == ev.NUMBERS_ONLY_NOTE
        assert "this_paper" not in feature and "past_papers" not in feature
        assert feature["engine_scale"] == {"this_paper": 0.7, "past_papers_average": 0.4,
                                           "note": "Original's 0 to 1 scale for this habit, as used in the score."}
    md = ev.render_markdown("s", evidence, None)
    assert ev.NUMBERS_ONLY_NOTE in md


def test_engine_order_is_kept_and_capped():
    feats = [_feature(c) for c in ("comma_rate", "char_trigram_entropy", "dash_rate", "hedging_density",
                                   "question_ratio", "quote_rate", "contraction_rate")]
    evidence = ev.build_evidence(feats, EDGE, [("past paper 1", PLAIN[0])])
    assert [f["code"] for f in evidence["features"]] == [f["code"] for f in feats[:5]]
    assert [f["rank"] for f in evidence["features"]] == [1, 2, 3, 4, 5]


def test_absent_habits_say_so():
    evidence = ev.build_evidence([_feature("contraction_rate"), _feature("question_ratio", -0.2)], PLAIN[0],
                                 [("past paper 1", PLAIN[1])])
    contraction, question = evidence["features"]
    assert contraction["this_paper"]["count"] == 0 and contraction["note"].startswith("No contraction")
    assert question["note"].startswith("No question")
    md = ev.render_markdown("s", evidence, None)
    assert "*(none in this paper)*" in md and "*(none in the past papers)*" in md
    one_sided = ev.build_evidence([_feature("contraction_rate")], EDGE, [("past paper 1", PLAIN[0])])
    assert one_sided["features"][0]["note"].startswith("No contraction (don't, it's, …) appears in the past papers")


def test_set_aside_text_is_reported_with_verbatim_previews():
    coverage = ev.measured_coverage(QUOTE_GAP)
    assert coverage["measured_words"] < coverage["stored_words"] / 4
    assert coverage["set_aside_count"] == 1
    (gap,) = coverage["set_aside"]
    assert gap["preview"] == QUOTE_GAP[gap["start"]:gap["preview_end"]]
    md = ev.render_markdown("s", ev.build_evidence([], QUOTE_GAP, [("past paper 1", PLAIN[0])]), None)
    assert "less than 80% of this paper's words were measured" in md
    assert "The score listed no habits" in md
    evidence = ev.build_evidence([_feature("sentence_initial_conjunction_rate")], LONG_SENTENCE + " " + QUOTE_GAP,
                                 [("past paper 1", PLAIN[0])])
    edge = ev.measured_coverage(EDGE)
    assert any("Night markets" in r["preview"] or "References" in r["preview"] for r in edge["set_aside"])
    assert evidence["measured"]["past_papers"][0]["paper"] == "past paper 1"


def test_sentences_that_run_across_set_aside_text_are_marked():
    text = "And she wrote " + LONG_QUOTE + " before she left the city. " + "This is my own sentence. " * 3
    evidence = ev.build_evidence([_feature("sentence_initial_conjunction_rate")], text, [("past paper 1", PLAIN[0])])
    quote = evidence["features"][0]["this_paper"]["examples"][0]
    assert quote["crosses_set_aside"] is True
    assert "runs across text it set aside" in ev.render_markdown("s", evidence, None)


def test_fail_closed_when_the_rebuild_or_count_disagrees(monkeypatch):
    real = pp.preprocess
    ev.engine_view.cache_clear()
    monkeypatch.setattr(pp, "preprocess", lambda text: (real(text)[0] + " extra", real(text)[1]))
    assert ev.engine_view(PLAIN[0]) is None
    reading = ev.read_paper(PLAIN[0], "comma_rate")
    assert reading.places is None
    coverage = ev.measured_coverage(PLAIN[0])
    assert coverage["set_aside"] is None
    feature = ev.build_evidence([_feature("comma_rate")], PLAIN[0], [("past paper 1", PLAIN[1])])["features"][0]
    assert feature["locatable"] is False and feature["note"] == ev.NOT_LOCATED_NOTE
    assert ev.NOT_LOCATED_NOTE in ev.render_markdown("s", {"features": [feature], "ordering": "o"}, None)
    monkeypatch.setattr(pp, "preprocess", real)
    ev.engine_view.cache_clear()
    ev._kept_cached.cache_clear()

    # A count that disagrees with the measurement also fails closed.
    spec = ev.LOCATABLE["comma_rate"]
    monkeypatch.setitem(ev.LOCATABLE, "comma_rate", ev.Locatable(
        spec.code, spec.what, spec.unit, lambda view: ("prose", [(0, 1)]), spec.formula, spec.value))
    assert ev.read_paper(PLAIN[0], "comma_rate").places is None
    monkeypatch.setitem(ev.LOCATABLE, "comma_rate", ev.Locatable(
        spec.code, spec.what, spec.unit, lambda view: ("prose", None), spec.formula, spec.value))
    assert ev.read_paper(PLAIN[0], "comma_rate").places is None
    monkeypatch.setattr(ev, "_sentence_spans", lambda view: None)
    assert ev.read_paper(PLAIN[0], "question_ratio").places is None
    assert ev.read_paper(PLAIN[0], "not_a_feature") is None


def test_case_folding_that_changes_length_fails_closed():
    text = "\u0130stanbul is large; however, it is also old. " * 3
    reading = ev.read_paper(text, "transition_density")
    assert reading.places is None
    assert ev.read_paper(text, "adversative_ratio").places is None
    assert ev.read_paper(text, "semicolon_colon_rate").places is not None


def test_preliminary_score_is_the_engines_numbers_with_its_label():
    p = ev.preliminary_score(0.6789, "schedule_conversation", inconclusive=False)
    assert p == {"label": "Preliminary · unvalidated · not a judgment", "score": 0.68,
                 "band": "schedule_conversation", "band_words": "Outside the usual range", "note": ev.PRELIMINARY_NOTE}
    for args in ((0.9, "escalate", True), (None, "monitor", False), (0.2, "error", False)):
        q = ev.preliminary_score(args[0], args[1], inconclusive=args[2])
        assert q["score"] is None and q["band_words"] == "Not enough writing on file to compare yet."
    banned = re.compile(r"\bAI\b|detect|cheat|authorship verification|accura|percent|%|authentic|misconduct",
                        re.IGNORECASE)
    for words in [ev.PRELIMINARY_LABEL, ev.PRELIMINARY_NOTE, *ev.BAND_WORDS.values(), ev.NUMBERS_ONLY_NOTE,
                  ev.NOT_LOCATED_NOTE]:
        assert not banned.search(words), words


def test_flags_default_off(monkeypatch):
    monkeypatch.delenv("EVIDENCE_PASSAGES_ENABLED", raising=False)
    monkeypatch.delenv("PRELIMINARY_SCORE_ENABLED", raising=False)
    assert ev.evidence_enabled() is False and ev.preliminary_enabled() is False
    monkeypatch.setenv("EVIDENCE_PASSAGES_ENABLED", "0")
    monkeypatch.setenv("PRELIMINARY_SCORE_ENABLED", "true")
    assert ev.evidence_enabled() is False and ev.preliminary_enabled() is False
    monkeypatch.setenv("EVIDENCE_PASSAGES_ENABLED", "1")
    monkeypatch.setenv("PRELIMINARY_SCORE_ENABLED", "1")
    assert ev.evidence_enabled() is True and ev.preliminary_enabled() is True


def test_html_report_has_two_columns_and_escapes_text():
    text = "Tom said <b>hi</b>; then left. It's late."
    evidence = ev.build_evidence([_feature("semicolon_colon_rate"), _feature("mean_sentence_length"),
                                  _feature("contraction_rate"), _feature("char_trigram_entropy")],
                                 text, [("past <1>", PLAIN[0])])
    html_out = ev.render_html("sub<1>", evidence, ev.preliminary_score(0.5, "monitor", inconclusive=False))
    assert "<h3>This paper</h3>" in html_out and "<h3>Past papers</h3>" in html_out
    assert "&lt;b&gt;hi&lt;/b&gt;<mark>;</mark>" in html_out
    assert "<b>hi</b>" not in html_out and "sub&lt;1&gt;" in html_out and "past &lt;1&gt;" in html_out
    assert "Preliminary · unvalidated · not a judgment" in html_out
    assert "None in the past papers." in html_out and ev.NUMBERS_ONLY_NOTE in html_out
    assert "words)</small>" in html_out
    whole = ev.render_html("s", ev.build_evidence([_feature("question_ratio")], "Why now? Fine.", [("p", "Who? Yes.")]), None)
    assert "<mark>" not in whole


def test_descriptions_come_from_the_suite_feature_data(monkeypatch):
    assert ev.describe("semicolon_colon_rate")[1].startswith("How often semicolons and colons appear")
    assert ev.describe("sentence_length_variance")[1] == "How much the writer's sentence lengths bounce around compared with staying even."
    ev._descriptions.cache_clear()
    monkeypatch.setattr(ev, "_FEATURE_DATA", Path("/nonexistent/feature-data.js"))
    assert ev.describe("comma_rate") == ("Comma Rate", "")
    ev._descriptions.cache_clear()


def test_staff_explainability_never_reaches_students_or_in_process_callers(monkeypatch):
    from original.routers import students_scoring as ss

    monkeypatch.setenv("EVIDENCE_PASSAGES_ENABLED", "1")
    monkeypatch.setenv("PRELIMINARY_SCORE_ENABLED", "1")
    feature = SimpleNamespace(code="comma_rate", name="Comma Rate", tier=4, contribution=0.0, direction="destructive",
                              baseline_value=0.2, submission_value=0.6, delta=0.4)
    result = SimpleNamespace(
        baseline_confidence=SimpleNamespace(authenticated_count=5, effective_sample_count=3.2),
        authorship=SimpleNamespace(deviation_score=0.66),
        recommendation=SimpleNamespace(action="schedule_conversation"),
        interference=SimpleNamespace(destructive_features=[feature]),
        feature_vector={code: 0.5 for code in ALL_FEATURE_CODES},
    )
    from original.quantum.scoring import FeatureContribution

    result.interference.destructive_features = [FeatureContribution(**vars(feature))]
    flat = [0.5] * FEATURE_DIM
    state = SimpleNamespace(samples=[SimpleNamespace(text=t, auth_weight=1.0, vector=flat) for t in PLAIN]
                            + [SimpleNamespace(text="ignored", auth_weight=0.0, vector=flat)],
                            baseline_mean=flat)

    def fresh():
        return SimpleNamespace(evidence=None, preliminary=None)

    student = SimpleNamespace(state=SimpleNamespace(principal=SimpleNamespace(role="student")))
    teacher = SimpleNamespace(state=SimpleNamespace(principal=SimpleNamespace(role="professor")))
    for request in (None, student):
        response = fresh()
        ss._attach_staff_explainability(response, request, EDGE, state, result)
        assert response.evidence is None and response.preliminary is None
    response = fresh()
    ss._attach_staff_explainability(response, teacher, EDGE, state, result)
    assert response.preliminary.score == 0.66 and response.preliminary.band_words == "Outside the usual range"
    assert [p["paper"] for p in response.evidence["measured"]["past_papers"]] == ["past paper 1", "past paper 2", "past paper 3"]
    assert response.evidence["features"][0]["this_paper"]["count"] == len(ev.read_paper(EDGE, "comma_rate").places) == 7
    # Where each past paper came from: only what the samples store.
    assert [p["paper"] for p in response.evidence["baseline_papers"]] == ["past paper 1", "past paper 2", "past paper 3"]
    assert response.evidence["baseline_papers"][0] == {
        "paper": "past paper 1", "assignment": None, "submitted_at": None, "provenance": None, "word_count": None}
    named = SimpleNamespace(samples=[SimpleNamespace(text=PLAIN[0], auth_weight=1.0, vector=flat, assignment="On Liberty",
                                                     submitted_at="2025-01-24", provenance="verified", word_count=40)],
                            baseline_mean=flat)
    response = fresh()
    ss._attach_staff_explainability(response, teacher, EDGE, named, result)
    assert response.evidence["baseline_papers"] == [{"paper": "past paper 1", "assignment": "On Liberty",
                                                     "submitted_at": "2025-01-24", "provenance": "verified", "word_count": 40}]
    # Every measurement, with the engine's own vectors passed through.
    assert len(response.evidence["all_features"]) == FEATURE_DIM
    # Comparison measurements are not compared (past papers have no value for
    # them): no difference at all rather than a difference against a stand-in.
    assert all(
        f["engine_scale"]["difference"] == 0
        if f["kind"] != "not_compared"
        else f["engine_scale"]["difference"] is None and f["engine_scale"]["this_paper"] == 0.5
        for f in response.evidence["all_features"]
    )
    # A contributing sample without stored text: the page cannot show it, so it
    # does not borrow the engine's mean either.
    gap = SimpleNamespace(samples=[*state.samples, SimpleNamespace(text="", auth_weight=1.0, vector=flat)],
                          baseline_mean=[0.9] * FEATURE_DIM)
    response = fresh()
    ss._attach_staff_explainability(response, teacher, EDGE, gap, result)
    compared = [f for f in response.evidence["all_features"] if f["kind"] != "not_compared"]
    assert compared[-1]["engine_scale"]["past_papers_average"] == 0.5
    assert response.evidence["all_features"][-1]["engine_scale"]["past_papers_average"] is None

    thin = SimpleNamespace(**{**vars(result), "baseline_confidence": SimpleNamespace(authenticated_count=3, effective_sample_count=3.0)})
    response = fresh()
    ss._attach_staff_explainability(response, teacher, EDGE, state, thin)
    assert response.preliminary.score is None

    monkeypatch.setattr("original.evidence.build_evidence", lambda *a, **k: 1 / 0)
    response = fresh()
    ss._attach_staff_explainability(response, teacher, EDGE, state, result)
    assert response.evidence is None and response.preliminary is not None

    monkeypatch.setenv("PRELIMINARY_SCORE_ENABLED", "0")
    monkeypatch.setattr("original.evidence.build_evidence", lambda *a, **k: {"features": []})
    response = fresh()
    ss._attach_staff_explainability(response, teacher, EDGE, state, result)
    assert response.evidence["features"] == [] and response.preliminary is None
    assert len(response.evidence["baseline_papers"]) == 3

    monkeypatch.setenv("EVIDENCE_PASSAGES_ENABLED", "0")
    response = fresh()
    ss._attach_staff_explainability(response, teacher, EDGE, state, result)
    assert response.evidence is None and response.preliminary is None


def _post_baselines(client, sid):
    for text in _corpus_texts(3):
        r = client.post(f"/students/{sid}/baseline", json={"text": text, "provenance": "verified"})
        assert r.status_code == 200, r.text[:300]


def test_score_api_is_unchanged_with_flags_off_and_adds_evidence_when_on(live_client, store_reset, monkeypatch):
    monkeypatch.delenv("EVIDENCE_PASSAGES_ENABLED", raising=False)
    monkeypatch.delenv("PRELIMINARY_SCORE_ENABLED", raising=False)
    sid = "evidence_api_alice"
    _post_baselines(live_client, sid)
    text = _corpus_texts(4)[3]
    off = live_client.post(f"/students/{sid}/score", json={"text": text, "submission_id": "e1"}).json()
    assert off["evidence"] is None and off["preliminary"] is None
    monkeypatch.setenv("EVIDENCE_PASSAGES_ENABLED", "1")
    monkeypatch.setenv("PRELIMINARY_SCORE_ENABLED", "1")
    on = live_client.post(f"/students/{sid}/score", json={"text": text, "submission_id": "e2"}).json()
    assert on["authorship"]["deviation_score"] == off["authorship"]["deviation_score"]
    assert on["recommendation"] == off["recommendation"]
    assert [f["code"] for f in on["evidence"]["features"]] == [
        f["code"] for f in off["interference"]["destructive_features"]]
    assert on["preliminary"]["label"] == ev.PRELIMINARY_LABEL
    assert on["preliminary"]["score"] is None  # three counted samples is below "ready"
    for q in _all_quotes(on["evidence"]):
        if q["paper"] == "this paper":
            assert q["passage"] == text[q["passage_start"]:q["passage_end"]]


def test_text_the_engine_splits_differently_fails_closed_for_sentence_habits():
    text = "The <DOT> marker is odd. Is it? Yes."
    assert ev._sentence_spans(ev.engine_view(text)) is None
    assert ev.read_paper(text, "question_ratio").places is None
    assert ev.read_paper(text, "mean_sentence_length").places is None


def test_overview_and_full_markdown_render():
    baselines = [(f"past paper {i + 1}", t) for i, t in enumerate(PLAIN)]
    overview = ev.countable_overview(EDGE, baselines)
    assert [row["code"] for row in overview] == list(ev.LOCATABLE)
    semicolons = next(row for row in overview if row["code"] == "semicolon_colon_rate")
    assert semicolons["outside_past_range"] is True
    assert ev.countable_overview(EDGE, [])[0]["past_range"] is None
    evidence = ev.build_evidence([_feature("typing_speed_cv"), _feature("sentence_length_variance")], EDGE, baselines)
    # Descriptions come from the code-checked table, also for switched-off groups.
    assert evidence["features"][0]["description"] == feature_info()["typing_speed_cv"]["description"]
    md = ev.render_markdown("sub-1", evidence, ev.preliminary_score(None, None, inconclusive=True), overview)
    assert "Every countable habit (fixed order, not a ranking; numbers only)" in md
    assert "**Preliminary · unvalidated · not a judgment**: – · Not enough writing on file to compare yet." in md
    assert "| This paper | Past papers |" in md
    html_out = ev.render_html("sub-1", {"features": evidence["features"]}, None)
    assert "Measured:" not in html_out


def test_sentence_spread_examples_do_not_repeat_a_sentence():
    places = ev.read_paper("Only one sentence here.", "sentence_length_variance").places
    assert len(ev._length_pick(places, "spread", "higher", 3)) == 1
    many = ev.read_paper(PLAIN[0], "sentence_length_variance").places
    assert len(ev._length_pick(many, "spread", "higher", 2)) == 2
    assert ev._length_pick(many, "mean", "lower", 1)[0].words == min(p.words for p in many)


def test_engine_view_mirrors_paragraph_style_indentation():
    text = "\tMy first paragraph, typed with a tab.\n\n\tMy second paragraph, also tabbed, goes on."
    view = ev.engine_view(text)
    assert view is not None and view.prose.text == pp.preprocess(text)[0]
