"""original/paper_profile.py: the teacher-only paper profile.

Descriptive facts about a paper's heading block, section headings, citations,
quotations and list of sources. It is checked here to (1) read realistic MLA,
APA and Chicago papers correctly, (2) report less, never more, when unsure,
(3) change nothing the engine measures, and (4) reach staff only.
"""

from __future__ import annotations

import ast
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from original import paper_profile as pp
from original import voice
from original.constants import ALL_FEATURE_CODES, FEATURE_DIM

FIXTURES = Path(__file__).parent / "fixtures" / "paper_matter"


def _paper(name: str) -> str:
    return (FIXTURES / f"{name}.txt").read_text(encoding="utf-8")


# ── Reading realistic papers ─────────────────────────────────────────────────

EXPECTED = {
    # name: (sources, list heading, earliest, latest, style guess, headings,
    #        front-matter words, in-text citations, footnote markers)
    "mla_docx": (3, "Works Cited", 2000, 2008, "MLA", 0, 18, 2, 0),
    "mla_variants": (2, "Works Cited", 1865, 2002, "MLA", 0, 12, 1, 0),
    "apa": (3, "References", 2010, 2017, "APA", 5, 26, 2, 0),
    "chicago_pdf": (2, "Bibliography", 1984, 1991, "Chicago notes", 0, 10, 0, 3),
    "pdf_wrap_trap": (0, None, None, None, None, 0, 12, 0, 0),
    "poem_quote": (0, None, None, None, None, 1, 2, 0, 0),
    "tricky_prose": (0, None, None, None, None, 1, 5, 0, 0),
}


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_sample_papers_are_read_as_a_teacher_would(name):
    sources, heading, earliest, latest, style, headings, front, cites, notes = EXPECTED[name]
    p = pp.paper_profile(_paper(name))
    assert p["sources"]["count"] == sources
    assert p["sources"]["list_heading"] == heading
    assert (p["sources"]["earliest_year"], p["sources"]["latest_year"]) == (earliest, latest)
    assert p["citation_style"]["guess"] == style
    assert p["headings"] == headings
    assert p["front_matter_words"] == front
    assert p["in_text_citations"]["count"] == cites
    assert p["footnote_markers"] == notes
    assert sum(p["sources"]["kinds"].values()) == sources


def test_mla_heading_with_colon_and_centring_is_still_the_list_of_sources():
    p = pp.paper_profile(_paper("mla_variants"))
    assert p["sources"]["kinds"] == {"book": 1, "web page": 1}


def test_a_heading_word_inside_the_prose_is_not_a_list_of_sources():
    # "Notes", "References to ...", "Appendix A of my life", "Bibliography is ..."
    # are the writer's own prose: no list, no style, nothing cut.
    p = pp.paper_profile(_paper("tricky_prose"))
    assert p["sources"]["count"] == 0 and p["citation_style"]["guess"] is None
    assert p["words"] == len(_paper("tricky_prose").split())


def test_a_wrapped_first_line_of_prose_is_not_counted_as_the_heading_block():
    text = _paper("pdf_wrap_trap")
    p = pp.paper_profile(text)
    # Ana Ruiz / Professor Cole / ENGL 220 / 12 October 2026 / Reading Late James
    assert p["front_matter_words"] == 2 + 2 + 2 + 3 + 3


def test_footnote_markers_skip_decimals_and_page_headers():
    text = "Results were weak, r = .31, p = .04, overall.\n\nSmith 2\n\nHe said so.1 Then she agreed.2\n"
    assert pp.paper_profile(text)["footnote_markers"] == 2


def test_one_pair_of_brackets_is_one_in_text_citation():
    text = "Sleep matters (Walker, 2017; Stickgold & Walker, 2013). It helps (Diekelmann & Born, 2010, p. 115)."
    p = pp.paper_profile(text)
    assert p["in_text_citations"]["count"] == 2
    assert p["in_text_citations"]["per_100_words"] == round(2 / len(text.split()) * 100, 2)


def test_style_is_unclear_when_the_signs_disagree_and_none_without_citations():
    mixed = "One view (Smith 45) and another (Jones, 2019) and (Lee, 2020) and (Ray 12)."
    assert pp.paper_profile(mixed)["citation_style"]["guess"] == "unclear"
    plain = pp.paper_profile("I walked home. It rained all day, and I stayed in.")
    assert plain["citation_style"] == {
        "guess": None,
        "words": "No citations found to guess a style from.",
        "signs": [],
        "caveat": pp.STYLE_CAVEAT,
    }


def test_empty_and_odd_inputs_never_raise():
    for text in ("", "\n\n\n", "Works Cited", "References\n\nSmith, J. (2020). A.", None):
        p = pp.paper_profile(text)
        assert p["words"] >= 0 and isinstance(p["citation_style"]["words"], str)


def test_deterministic_and_json_safe():
    text = _paper("apa")
    assert pp.paper_profile(text) == pp.paper_profile(text)
    json.dumps(pp.build_paper_profiles(text, [("past paper 1", _paper("mla_docx"))]))


# ── Plain, honest wording ────────────────────────────────────────────────────

BANNED = ("ai detection", "cheat", "authorship verification", "fingerprint", "detect", "proof")


def _strings(blob):
    if isinstance(blob, dict):
        for k, v in blob.items():
            yield k
            yield from _strings(v)
    elif isinstance(blob, list):
        for v in blob:
            yield from _strings(v)
    elif isinstance(blob, str):
        yield blob


def test_wording_is_plain_and_the_style_is_always_a_best_guess():
    for name in EXPECTED:
        p = pp.build_paper_profiles(_paper(name), [])
        for s in _strings(p):
            assert not any(b in s.lower() for b in BANNED), s
        style = p["this_paper"]["citation_style"]
        if style["guess"] is not None:
            assert style["words"].startswith("Best guess:")
        assert style["caveat"] == "A best guess from the formatting, not a check of the citations."
    source = Path(pp.__file__).read_text(encoding="utf-8").lower()
    for b in ("ai detection", "cheating", "authorship verification"):
        assert b not in source


# ── Changes nothing the engine measures ──────────────────────────────────────


def test_nothing_in_the_scoring_path_imports_the_profile():
    root = Path(pp.__file__).parent
    for rel in ("features/pipeline.py", "features/preprocess.py", "quantum/scoring.py", "evidence.py"):
        tree = ast.parse((root / rel).read_text(encoding="utf-8"))
        names = {
            (n.module or "") + "." + a.name
            for n in ast.walk(tree)
            if isinstance(n, ast.ImportFrom)
            for a in n.names
        } | {a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
        assert not any("paper_profile" in name for name in names), rel


def test_the_profile_leaves_preprocess_output_unchanged():
    from original.features.preprocess import preprocess

    for name in EXPECTED:
        text = _paper(name)
        before = preprocess(text)
        pp.paper_profile(text)
        assert preprocess(text)[0] == before[0]


def test_flag_is_off_unless_switched_on(monkeypatch):
    monkeypatch.delenv("PAPER_PROFILE_ENABLED", raising=False)
    assert pp.paper_profile_enabled() is False
    for off in ("0", "off", "false", "", "no", "maybe"):
        monkeypatch.setenv("PAPER_PROFILE_ENABLED", off)
        assert pp.paper_profile_enabled() is False
    for on in ("1", "on", "TRUE", " yes "):
        monkeypatch.setenv("PAPER_PROFILE_ENABLED", on)
        assert pp.paper_profile_enabled() is True


# ── Staff only ───────────────────────────────────────────────────────────────


def _engine_result():
    from original.quantum.scoring import FeatureContribution

    feature = FeatureContribution(code="comma_rate", name="Comma Rate", tier=4, contribution=0.0,
                                  direction="destructive", baseline_value=0.2, submission_value=0.6, delta=0.4)
    return SimpleNamespace(
        baseline_confidence=SimpleNamespace(authenticated_count=3, effective_sample_count=3.0),
        authorship=SimpleNamespace(deviation_score=0.5),
        recommendation=SimpleNamespace(action="monitor"),
        interference=SimpleNamespace(destructive_features=[feature]),
        feature_vector={code: 0.5 for code in ALL_FEATURE_CODES},
    )


def test_profile_attaches_for_staff_only_and_only_when_switched_on(monkeypatch):
    from original.routers import students_scoring as ss

    flat = [0.5] * FEATURE_DIM
    pasts = [_paper("mla_docx"), _paper("chicago_pdf"), _paper("tricky_prose")]
    state = SimpleNamespace(samples=[SimpleNamespace(text=t, auth_weight=1.0, vector=flat) for t in pasts],
                            baseline_mean=flat)
    student = SimpleNamespace(state=SimpleNamespace(principal=SimpleNamespace(role="student")))
    teacher = SimpleNamespace(state=SimpleNamespace(principal=SimpleNamespace(role="professor")))

    def run(request):
        response = SimpleNamespace(evidence=None, preliminary=None)
        ss._attach_staff_explainability(response, request, _paper("apa"), state, _engine_result())
        return response

    monkeypatch.setenv("EVIDENCE_PASSAGES_ENABLED", "1")
    monkeypatch.setenv("PRELIMINARY_SCORE_ENABLED", "0")
    monkeypatch.delenv("PAPER_PROFILE_ENABLED", raising=False)
    assert "paper_profile" not in run(teacher).evidence

    monkeypatch.setenv("PAPER_PROFILE_ENABLED", "1")
    profile = run(teacher).evidence["paper_profile"]
    assert profile["note"] == pp.PROFILE_NOTE
    assert profile["this_paper"]["citation_style"]["guess"] == "APA"
    assert [p["paper"] for p in profile["past_papers"]] == ["past paper 1", "past paper 2", "past paper 3"]
    assert [p["citation_style"]["guess"] for p in profile["past_papers"]] == ["MLA", "Chicago notes", None]
    for request in (None, student):
        assert run(request).evidence is None

    # A failure in the profile leaves the rest of the evidence in place.
    monkeypatch.setattr("original.paper_profile.build_paper_profiles", lambda *a, **k: 1 / 0)
    evidence = run(teacher).evidence
    assert evidence is not None and "paper_profile" not in evidence and evidence["features"]


def test_voice_drops_staff_only_keys_at_any_depth():
    assert "paper_profile" in voice.STAFF_ONLY_KEYS
    blob = {"headline": "h", "paper_profile": {"x": 1},
            "arc": [{"period": "p", "paper_profile": 2}], "deep": {"a": {"paper_profile": 3, "b": 4}}}
    original = json.loads(json.dumps(blob))
    assert voice.drop_staff_only(blob) == {"headline": "h", "arc": [{"period": "p"}], "deep": {"a": {"b": 4}}}
    assert blob == original  # the input is not changed
    assert voice.drop_staff_only("text") == "text" and voice.drop_staff_only([1, {"k": 2}]) == [1, {"k": 2}]


# ── Parts of the paper (features.matter.find_parts) ──────────────────────────

SAMPLES = Path(__file__).parents[1] / "validation" / "diagnostics" / "document_parts_v2" / "samples"


def _docx(name: str) -> str:
    from original.upload_utils import extract_text_from_bytes

    return extract_text_from_bytes((SAMPLES / f"{name}.docx").read_bytes(), f"{name}.docx")


def test_parts_are_listed_only_with_the_splitter_on(monkeypatch):
    text = _docx("apa_student")
    monkeypatch.delenv("MATTER_SPLITTER_ENABLED", raising=False)
    assert "parts" not in pp.paper_profile(text)
    monkeypatch.setenv("MATTER_SPLITTER_ENABLED", "1")
    assert pp.paper_profile(text)["parts"] == pp.paper_parts(text)


def test_an_apa_paper_lists_its_title_page_abstract_and_references():
    text = _docx("apa_student")
    parts = pp.paper_parts(text)
    by_kind = {p["kind"]: p for p in parts}
    for kind, label in (("title_page", "Title page"), ("abstract", "Abstract"), ("back_matter", "References")):
        part = by_kind[kind]
        assert (part["label"], part["status"], part["by"], part["possible"]) == (label, "set_aside", "rules", False)
        assert part["rules_status"] == "set_aside"
        a, b = part["ranges"][0]
        assert 0 <= a < b <= len(text) and (part["start"], part["end"]) == (a, part["ranges"][-1][1])
        assert part["words"] == sum(len(text[x:y].split()) for x, y in part["ranges"]) > 0
        assert part["first_line"] and len(part["first_line"]) <= pp.FIRST_LINE_CHARS
        assert "\x1f" not in part["first_line"]  # a page marker is never shown
    assert by_kind["abstract"]["first_line"] == "Abstract"
    assert by_kind["back_matter"]["first_line"] == "References"
    # Section headings are one part, all their lines together.
    headings = by_kind["heading"]
    assert headings["label"] == "Section headings" and len(headings["ranges"]) == headings["lines"] == 3
    assert [p["start"] for p in parts] == sorted(p["start"] for p in parts)
    json.dumps(parts)


def test_a_part_the_rules_were_unsure_of_is_measured_and_marked_possible():
    text = _paper("apa")  # an "Abstract" heading with no clear end
    possible = [p for p in pp.paper_parts(text) if p["possible"]]
    assert [p["kind"] for p in possible] == ["abstract"]
    assert possible[0]["status"] == possible[0]["rules_status"] == "measured"


def test_an_appendix_after_the_list_of_sources_is_listed_as_measured():
    parts = pp.paper_parts(_docx("turabian_appendix"))
    appendix = [p for p in parts if p["kind"] == "appendix"]
    assert len(appendix) == 1 and appendix[0]["status"] == "measured" and appendix[0]["first_line"] == "Appendix A"
    assert any(p["label"] == "Bibliography" and p["status"] == "set_aside" for p in parts)


@pytest.fixture
def switches(monkeypatch):
    monkeypatch.setenv("MATTER_SPLITTER_ENABLED", "1")
    monkeypatch.setenv("PAPER_PROFILE_ENABLED", "1")


def test_a_teachers_choice_is_shown_on_the_parts_it_touches(switches):
    from original.features import part_overrides as po

    text = _docx("apa_student")
    parts = {p["kind"]: p for p in pp.paper_parts(text)}
    title, abstract = parts["title_page"]["ranges"][0], parts["abstract"]["ranges"][0]
    body = parts["back_matter"]["ranges"][0][0] - 300  # inside the body, in none of the parts
    choice = po.validate(text, [[body, body + 100]], [abstract])
    snapped = [list(r) for r in choice.exclude]
    shown = {p["kind"]: p for p in pp.paper_parts(po.chosen(text, choice))}
    assert (shown["abstract"]["status"], shown["abstract"]["by"]) == ("measured", "teacher")
    assert shown["abstract"]["rules_status"] == "set_aside"
    assert (shown["title_page"]["status"], shown["title_page"]["by"]) == ("set_aside", "rules")
    assert shown["chosen"]["ranges"] == snapped and shown["chosen"]["by"] == "teacher"
    assert shown["chosen"]["status"] == "set_aside" and shown["chosen"]["label"] == "A part you chose"
    assert title == shown["title_page"]["ranges"][0]
    assert {p["kind"] for p in pp.paper_parts(text)} == set(parts)  # the plain text: the rules


def test_a_choice_marks_only_the_parts_it_changed(switches):
    """Setting an appendix aside covers the "Appendix A" heading too, which the
    rules set aside already: the headings stay the rules' doing. Measuring the
    headings afterwards cuts that line out of the appendix's range, and the
    appendix is still mostly set aside."""
    from original.features import part_overrides as po

    text = _docx("turabian_appendix")
    parts = {p["kind"]: p for p in pp.paper_parts(text)}
    appendix = parts["appendix"]["ranges"][0]
    shown = {p["kind"]: p for p in pp.paper_parts(po.chosen(text, po.validate(text, [appendix], None)))}
    assert (shown["appendix"]["status"], shown["appendix"]["by"]) == ("set_aside", "teacher")
    assert (shown["heading"]["status"], shown["heading"]["by"]) == ("set_aside", "rules")
    heading = parts["heading"]["ranges"][0]
    rest = po.minus_ranges([tuple(appendix)], [tuple(heading)])
    choice = po.validate(text, rest, [heading])
    shown = {p["kind"]: p for p in pp.paper_parts(po.chosen(text, choice))}
    assert (shown["heading"]["status"], shown["heading"]["by"]) == ("measured", "teacher")
    assert (shown["appendix"]["status"], shown["appendix"]["by"]) == ("set_aside", "teacher")


def test_the_profile_carries_the_choice_only_with_both_switches(monkeypatch):
    from original.features import part_overrides as po

    text = _docx("apa_student")
    title = next(p for p in pp.paper_parts(text) if p["kind"] == "title_page")["ranges"]
    carried = po.chosen(text, po.validate(text, None, title))
    monkeypatch.setenv("MATTER_SPLITTER_ENABLED", "1")
    monkeypatch.setenv("PAPER_PROFILE_ENABLED", "0")
    assert pp.paper_profile(carried)["choice"] == {"exclude_ranges": [], "include_ranges": []}
    monkeypatch.setenv("PAPER_PROFILE_ENABLED", "1")
    assert pp.paper_profile(text)["choice"] == {"exclude_ranges": [], "include_ranges": []}
    assert pp.paper_profile(carried)["choice"] == {"exclude_ranges": [], "include_ranges": title}
    monkeypatch.setenv("MATTER_SPLITTER_ENABLED", "0")
    assert "choice" not in pp.paper_profile(carried)


def test_a_long_first_line_is_cut_short():
    line = "A Very Long Title " * 10
    assert pp._first_line(line + "\n\nBody.", 0, len(line)).endswith("…")
    assert len(pp._first_line(line, 0, len(line))) == pp.FIRST_LINE_CHARS
    assert pp._first_line("\n\x1f\n  Short  line \n", 0, 20) == "Short line"


def test_parts_reach_staff_only(monkeypatch):
    monkeypatch.setenv("MATTER_SPLITTER_ENABLED", "1")
    profile = pp.build_paper_profiles(_docx("apa_student"), [])
    assert profile["this_paper"]["parts"]
    student_view = voice.drop_staff_only({"evidence": {"paper_profile": profile}, "headline": "h"})
    assert student_view == {"evidence": {}, "headline": "h"}
