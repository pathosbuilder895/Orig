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
