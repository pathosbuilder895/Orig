"""The document-parts v2 test set labels every character exactly once.

``validation/diagnostics/document_parts_v2/`` is a diagnostic (not a gate):
real paper parts around genuine public-domain prose, with the true part of
every character. These checks keep its labels honest: the generator labels
each pasted character once, the extracted-text aligner recovers known labels
and reports what extraction dropped instead of guessing, and every committed
record's labels still line up with its text.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import lzma
import sys
from pathlib import Path

FOLDER = Path(__file__).resolve().parents[1] / "validation" / "diagnostics" / "document_parts_v2"


def _load(name: str):
    key = f"_document_parts_v2_{name}"
    if key not in sys.modules:
        spec = importlib.util.spec_from_file_location(key, FOLDER / f"{name}.py")
        mod = importlib.util.module_from_spec(spec)
        sys.modules[key] = mod
        spec.loader.exec_module(mod)
    return sys.modules[key]


MC = _load("make_cases")
L = MC.L
KINDS = {
    "prose",
    "title_page",
    "heading_block",
    "title",
    "abstract",
    "section_heading",
    "references",
    "notes",
    "footnote",
    "appendix",
    "page_header",
    "note_marker",
    L.SEP,
}


def test_pasted_cases_label_every_character_once():
    for variant in MC.VARIANTS:
        doc = MC.build("augustine", variant, "paste")
        for sep in ("\n\n", "\n"):
            text, kinds = MC.render_paste(doc, sep)
            assert len(kinds) == len(text), variant
            assert set(kinds) <= KINDS, variant
            # each paragraph sits where its labels say, in order
            pos = 0
            for p in doc.paras:
                if p.style == "blank" or not p.text:
                    continue
                at = text.index(p.text, pos)
                assert [kinds[at + i] for i in range(len(p.text))] == [
                    k for t, k in p.segs for _ in t
                ], variant
                pos = at + len(p.text)


def test_negative_controls_are_all_prose_apart_from_their_wrapper():
    for variant in (
        "neg_abstract_word",
        "neg_references_sentence",
        "neg_sermon_prayer",
        "neg_letter",
    ):
        text, kinds = MC.render_paste(MC.build("newman", variant, "paste"), "\n\n")
        trick = {
            "neg_abstract_word": "Abstract as this",
            "neg_references_sentence": "References to Newman",
            "neg_sermon_prayer": "Let us pray.",
            "neg_letter": "Dear Thomas,",
        }[variant]
        assert kinds[text.index(trick)] == "prose"


def test_aligner_recovers_a_docx_style_extraction_and_reports_what_it_dropped():
    doc = MC.build("augustine", "turabian", "docx")
    flow = MC.flow_units(doc)
    # python-docx: body paragraphs joined by a blank line, the footnote
    # reference numbers, the footer and the footnotes themselves gone.
    paras, want = [], []
    for text, kinds in flow:
        kept = [(c, k) for c, k in zip(text, kinds, strict=True) if k != "note_marker"]
        paras.append("".join(c for c, _ in kept))
        want.append([k for _, k in kept])
    ext = "\n\n".join(paras)
    res = L.align(ext, flow, MC.floating_units(doc, pages=7))
    expected = [k for n, ks in enumerate(want) for k in ([L.SEP] * 2 if n else []) + ks]
    got = res["labels"]
    assert len(got) == len(ext)
    assert all(g == e for c, g, e in zip(ext, got, expected, strict=True) if not c.isspace())
    assert res["unattributed"] == 0
    assert res["lost"]["note_marker"] == res["source"]["note_marker"] == MC.N_NOTES
    assert res["lost"]["footnote"] == res["source"]["footnote"]
    assert res["lost"]["page_header"] == res["source"]["page_header"]
    assert "prose" not in res["lost"]


def test_aligner_finds_a_running_head_and_footnote_printed_mid_paragraph():
    para = "Alpha beta gamma delta epsilon zeta eta theta iota kappa."
    flow = [(para, ["prose"] * len(para))]
    floating = [
        ("Reyes 2", "page_header"),
        ("1 Augustine, Confessions (Oxford: OUP, 1991), 3.", "footnote"),
    ]
    ext = (
        "Alpha beta gamma \n1 Augustine, Confessions (Oxford: OUP, \n1991), 3.\nReyes 2\n"
        "delta epsilon zeta eta theta iota \nkappa."
    )
    res = L.align(ext, flow, floating)
    got = {
        k: "".join(c for c, g in zip(ext, res["labels"], strict=True) if g == k and not c.isspace())
        for k in ("prose", "footnote", "page_header")
    }
    assert got["prose"] == "".join(para.split())
    assert got["page_header"] == "Reyes2"
    assert got["footnote"].startswith("1Augustine") and got["footnote"].endswith("3.")
    assert res["unattributed"] == 0 and res["lost"] == {}


def test_committed_records_still_line_up_with_their_text():
    with lzma.open(FOLDER / "cases.jsonl.xz", "rt", encoding="utf-8") as fh:
        lines = [json.loads(line) for line in fh]
    meta, records = lines[0]["_meta"], lines[1:]
    assert set(meta["split"]["dev"]).isdisjoint(meta["split"]["holdout"])
    assert len(records) == len(MC.C.AUTHORS) * len(MC.VARIANTS) * len(MC.INPUTS)
    for r in records:
        labels = L.unrle(r["labels"])
        assert len(labels) == len(r["text"]), r["case_id"]
        assert set(labels) <= KINDS | {L.UNATTRIBUTED}, r["case_id"]
        assert hashlib.sha256(r["text"].encode("utf-8")).hexdigest() == r["sha256"]
        if r["input"].startswith("paste"):
            assert r["lost"] == {} and r["unattributed"] == 0
