"""Tests for validation/adversarial/imitation_controls.py, the report-only
length and layout controls for gate G-A2. They pin the two transforms the
controls rest on and that the summary compares the right populations."""

from __future__ import annotations

from validation.adversarial import imitation_controls as ic


def test_cut_words_keeps_the_original_formatting():
    text = "One  two\nthree\n\nfour five six"
    assert ic.cut_words(text, 3) == "One  two\nthree"
    assert ic.cut_words(text, 99) == text
    assert ic.cut_words(text, 0) == ""


def test_flatten_joins_paragraphs_with_single_spaces():
    assert ic.flatten("First.\n\nSecond line\nwraps.\n  \n\tThird.") == (
        "First. Second line wraps. Third."
    )
    assert ic.flatten("No breaks here.") == "No breaks here."


def test_single_paragraph():
    assert ic.single_paragraph(["one long line", "another one\n"])
    assert not ic.single_paragraph(["one", "two\n\nparagraphs"])


def _row(kind, vid, n, scores, actions, side):
    return {
        "kind": kind,
        "victim_id": vid,
        "n": n,
        f"{side}_scores": scores,
        f"{side}_actions": actions,
    }


def test_summary_restricts_the_full_genuine_comparator_to_the_imitated_victims():
    report = [
        _row("llm_imitation", "a", 5, [0.9], ["escalate"], "impostor"),
        _row("clean", "a", 5, [0.1, 0.2], ["no_action", "monitor"], "holdout"),
        # victim b has a clean cell but no imitation at N=5: excluded
        _row("clean", "b", 5, [0.95, 0.96], ["escalate", "escalate"], "holdout"),
    ]
    controls = [
        _row("genuine_slice", "a", 5, [0.3, 0.95], ["monitor", "escalate"], "impostor"),
        _row("imitation_flat", "a", 5, [0.5], ["schedule_conversation"], "impostor"),
    ]
    out = ic.summarize(report, controls)["N=5"]
    assert out["victims"] == ["a"]
    assert out["imitation_vs_genuine_full"]["auroc"] == 1.0
    assert out["imitation_vs_genuine_full"]["n_genuine"] == 2
    assert out["imitation_vs_genuine_slice"]["auroc"] == 0.5
    assert out["imitation_flat_vs_genuine_slice"]["auroc"] == 0.5
    rates = out["schedule_conversation_plus"]
    assert rates == {
        "imitation": 1.0,
        "imitation_flat": 1.0,
        "genuine_full": 0.0,
        "genuine_slice": 0.5,
    }


def test_build_cells_slices_held_out_documents_and_flattens_only_single_paragraph_victims():
    """Against the committed corpus: mill's baselines are one paragraph each,
    douglass's are not. Every slice is a prefix of a genuine held-out
    document with the imitation's word count, nothing scored is one of the
    baselines, and only mill's imitation is flattened."""
    from validation.adversarial.generators import LLMImitation

    rows = [
        {"kind": "llm_imitation", "victim_id": "mill", "n": 3},
        {"kind": "llm_imitation", "victim_id": "douglass", "n": 3},
    ]
    cells = ic.build_cells(rows)
    assert [(c.kind, c.profile.victim_id) for c in cells] == [
        ("genuine_slice", "mill"),
        ("imitation_flat", "mill"),
        ("genuine_slice", "douglass"),
        ("imitation_flat", "douglass"),
    ]
    for vid in ("mill", "douglass"):
        profile = ic._profile(vid, 3)
        (imitation,) = (t for e, t in LLMImitation(vid).load_entries() if e["n_baselines"] == 3)
        sliced, flat = (c for c in cells if c.profile.victim_id == vid)
        assert len(sliced.profile.impostor_docs) == len(profile.genuine_holdout)
        for doc, source in zip(sliced.profile.impostor_docs, profile.genuine_holdout, strict=True):
            assert source.startswith(doc)
            assert len(doc.split()) == len(imitation.split())
        for cell in (sliced, flat):
            assert cell.profile.baselines == profile.baselines
            assert not set(cell.profile.impostor_docs) & set(profile.baselines)
        if vid == "mill":
            assert ic.single_paragraph(profile.baselines)
            assert flat.profile.impostor_docs == [ic.flatten(imitation)]
            assert "\n" not in flat.profile.impostor_docs[0]
        else:
            assert not ic.single_paragraph(profile.baselines)
            assert flat.profile.impostor_docs == [imitation]


def test_reproduction_check_flags_a_changed_score():
    class _Cell:
        def __init__(self, kind, vid, n, doc):
            self.kind, self.n = kind, n
            self.profile = type("P", (), {"victim_id": vid, "impostor_docs": [doc]})()

    report = [{"kind": "llm_imitation", "victim_id": "a", "n": 3, "impostor_scores": [0.5]}]
    cells = [
        _Cell("imitation_flat", "a", 3, "para one\n\npara two"),
        _Cell("imitation_flat", "b", 3, "flattened, not checked"),
    ]
    same = [{"impostor_scores": [0.5]}, {"impostor_scores": [0.9]}]
    moved = [{"impostor_scores": [0.51]}, {"impostor_scores": [0.9]}]
    assert ic.reproduction_check(report, cells, same) == {"checked": 1, "mismatched": []}
    assert ic.reproduction_check(report, cells, moved) == {"checked": 1, "mismatched": ["a N=3"]}
