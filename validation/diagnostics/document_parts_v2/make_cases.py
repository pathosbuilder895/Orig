"""Build the labelled document-parts test set (deterministic).

Every case is one author's genuine prose wrapped in the parts of a real
student paper (MLA, APA 7 student and professional, Turabian/Chicago, edge
variants and negative controls), produced four ways:

``paste``       pasted text, a blank line between paragraphs (a Google Docs
                style paste)
``paste_word``  pasted text, one newline between paragraphs (a Word style
                paste)
``docx``        a real .docx (Title and Heading 1 styles, page breaks, a
                running head or page number in the header or footer, real
                footnotes for Turabian), read with
                ``original.upload_utils.extract_text_from_bytes``
``pdf``         that .docx printed to PDF by LibreOffice
                (``soffice --headless --convert-to pdf``), read the same way

Each record carries the text as Original would see it and the true part of
every character (``labels.py`` explains how extracted text is labelled).
Output:

``cases.jsonl.xz``  every record (text, labels, what extraction lost)
``samples/``        the .txt/.docx/.pdf files for one dev author, to open
``build/``          every .docx/.pdf (not committed; regenerated here)

Run from the repository root (needs LibreOffice for the PDFs):

    .venv/bin/python validation/diagnostics/document_parts_v2/make_cases.py
"""

from __future__ import annotations

import glob
import hashlib
import importlib.util
import io
import json
import lzma
import random
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def load_sibling(name: str):
    """A module from this folder, loaded by path under a private name, so the
    folder never goes on sys.path (its ``run.py`` would shadow the
    repository's own ``run.py``)."""
    key = f"_document_parts_v2_{name}"
    if key not in sys.modules:
        spec = importlib.util.spec_from_file_location(key, HERE / f"{name}.py")
        mod = importlib.util.module_from_spec(spec)
        sys.modules[key] = mod
        spec.loader.exec_module(mod)
    return sys.modules[key]


C = load_sibling("content")
L = load_sibling("labels")

SEED = 20261120
CORPUS = ROOT / "validation" / "public_authors" / "corpus"
TARGET_WORDS = 1450  # about the 9,000 characters the 2026-11-18 run used
SHORT_WORDS = 450
N_NOTES = 6
SAMPLE_AUTHOR = "edwards"  # a dev author whose prose has no long dashes
INPUTS = ("paste", "paste_word", "docx", "pdf")

MAIN = ["mla", "apa_student", "apa_professional", "turabian", "turabian_appendix"]
EDGE = [
    "apa_reference_list",
    "apa_literature_cited",
    "mla_unheaded_refs",
    "mla_short_long_refs",
    "apa_bold_abstract",
    "markdown_apa",
]
NEGATIVE = ["neg_abstract_word", "neg_references_sentence", "neg_sermon_prayer", "neg_letter"]
CONTROLS = [
    "prose",
    "prose_short",
    "prose_abstract_word",
    "prose_references_sentence",
    "prose_sermon_prayer",
    "prose_letter",
]
CONTROL_OF = {v: "prose" for v in MAIN + EDGE}
CONTROL_OF.update(
    mla_short_long_refs="prose_short",
    neg_abstract_word="prose_abstract_word",
    neg_references_sentence="prose_references_sentence",
    neg_sermon_prayer="prose_sermon_prayer",
    neg_letter="prose_letter",
)
FORMAT_OF = {
    "mla": "MLA",
    "apa_student": "APA",
    "apa_professional": "APA",
    "turabian": "Turabian",
    "turabian_appendix": "Turabian",
    "apa_reference_list": "APA",
    "apa_literature_cited": "APA",
    "mla_unheaded_refs": "MLA",
    "mla_short_long_refs": "MLA",
    "apa_bold_abstract": "APA",
    "markdown_apa": "APA",
    "neg_abstract_word": "MLA",
    "neg_references_sentence": "MLA",
    "neg_sermon_prayer": "MLA",
    "neg_letter": "MLA",
}
VARIANTS = MAIN + EDGE + NEGATIVE + CONTROLS
SAMPLE_VARIANTS = [*MAIN, "markdown_apa"]


# ── Prose ────────────────────────────────────────────────────────────────────


def clean_paragraphs(raw: str) -> list[str]:
    """Paragraphs of running prose from a Gutenberg-style file: wrapped lines
    joined, and chapter headings, all-caps summaries, chapter abstracts
    ("CH. I.") and lists of notes ("(1) Psalm ...") dropped, so the prose
    reads like a paper's body."""
    out = []
    for blk in re.split(r"\n\s*\n", raw):
        p = re.sub(r"\s+", " ", " ".join(ln.strip() for ln in blk.splitlines() if ln.strip()))
        if len(p.split()) < 25 or re.match(r"^(?:CH\.|CHAPTER\b|\(\d+\))", p):
            continue
        letters = [c for c in p if c.isalpha()]
        if letters and sum(c.isupper() for c in letters) / len(letters) > 0.5:
            continue
        out.append(p)
    return out


def take_words(paras: list[str], target: int) -> tuple[list[str], list[str]]:
    sel, n = [], 0
    for k, p in enumerate(paras):
        sel.append(p)
        n += len(p.split())
        if n >= target:
            return sel, paras[k + 1 :]
    return sel, []


def author_files(author: str) -> list[str]:
    return sorted(glob.glob(str(CORPUS / author / "*part_0*.txt")))


def read(path: str) -> str:
    return open(path, encoding="utf-8", errors="replace").read()


def baseline_texts(author: str) -> list[str]:
    """The four past papers: parts 1 to 4, cleaned the same way as the probe."""
    return [
        "\n\n".join(take_words(clean_paragraphs(read(f)), TARGET_WORDS)[0])
        for f in author_files(author)[:4]
    ]


_SENT_END = re.compile(r"[.!?][\"”’')\]]*(?=\s|$)")


def sentences(p: str) -> list[str]:
    """Sentences of a paragraph; a fragment under four words ("4.", a
    paragraph number) stays with the sentence after it."""
    out, pos, carry = [], 0, ""
    for m in _SENT_END.finditer(p):
        s = (carry + " " + p[pos : m.end()].strip()).strip()
        pos = m.end()
        if len(s.split()) < 4:
            carry = s
            continue
        out.append(s)
        carry = ""
    tail = (carry + " " + p[pos:].strip()).strip()
    if tail:
        out.append(tail)
    return out


def short_paragraphs(paras: list[str]) -> list[str]:
    """About SHORT_WORDS words from the start of the prose, in four paragraphs
    split at sentence ends (each boundary at the sentence end nearest a
    quarter of the words)."""
    sents: list[str] = []
    n = 0
    for s in (s for p in paras for s in sentences(p)):
        if n >= SHORT_WORDS and len(sents) >= 4:
            break
        sents.append(s)
        n += len(s.split())
    cum = [0]
    for s in sents:
        cum.append(cum[-1] + len(s.split()))
    bounds = [0]
    for k in (1, 2, 3):
        lo, hi = bounds[-1] + 1, len(sents) - (4 - k)
        bounds.append(min(range(lo, hi + 1), key=lambda i: abs(cum[i] - cum[-1] * k / 4)))
    bounds.append(len(sents))
    return [" ".join(sents[bounds[k] : bounds[k + 1]]) for k in range(4)]


def probe(author: str) -> dict:
    files = author_files(author)
    paras, rest = take_words(clean_paragraphs(read(files[4])), TARGET_WORDS)
    if not rest and len(files) > 5:
        rest = clean_paragraphs(read(files[5]))
    appendix, n = [], 0
    for p in rest:
        appendix.append(p)
        n += len(p.split())
        if n >= 150:
            break
    return {"paras": paras, "short": short_paragraphs(paras), "appendix": appendix}


# ── Citations ────────────────────────────────────────────────────────────────


def _full(a: tuple[str, str]) -> str:
    last, first = a
    return f"{first} {last}".strip()


def _dot(names: str) -> str:
    return names if names.endswith(".") else names + "."


def _initials(first: str) -> str:
    return " ".join(t[0] + "." for t in first.split())


def _apa_name(a: tuple[str, str]) -> str:
    last, first = a
    return f"{last}, {_initials(first)}" if first else last


def mla(r: dict) -> str:
    au = r.get("authors", [])
    if not au:
        names = ""
    elif len(au) == 1:
        names = f"{au[0][0]}, {au[0][1]}" if au[0][1] else au[0][0]
    elif len(au) == 2:
        names = f"{au[0][0]}, {au[0][1]}, and {_full(au[1])}"
    else:
        names = f"{au[0][0]}, {au[0][1]}, et al"
    pub = r.get("publisher", "").replace("University Press", "UP")
    if r["type"] == "book":
        extra = []
        if r.get("translator"):
            extra.append(f"Translated by {r['translator']}")
        if r.get("editor"):
            extra.append(f"Edited by {r['editor']}")
        if r.get("edition"):
            extra.append(r["edition"] if not extra else r["edition"].lower())
        tail = (", ".join(extra) + ", ") if extra else ""
        return f"{_dot(names)} {r['title']}. {tail}{pub}, {r['year']}."
    if r["type"] == "chapter":
        return (
            f'{_dot(names)} "{r["title"]}." {r["book"]}, edited by {r["editor"]}, {pub}, '
            f"{r['year']}, pp. {r['pages']}."
        )
    if r["type"] == "article":
        return (
            f'{_dot(names)} "{r["title"]}." {r["journal"]}, vol. {r["volume"]}, no. {r["issue"]}, '
            f"{r['year']}, pp. {r['pages']}, https://doi.org/{r['doi']}."
        )
    return f'"{r["title"]}." {r["site"]}, {r["url"]}. Accessed 2 Mar. 2026.'


def apa(r: dict) -> str:
    au = r.get("authors", [])
    names = [_apa_name(a) for a in au]
    if not names:
        nm = ""
    elif len(names) == 1:
        nm = names[0]
    elif len(names) == 2:
        nm = f"{names[0]}, & {names[1]}"
    else:
        nm = ", ".join(names[:-1]) + f", & {names[-1]}"
    if nm and not nm.endswith("."):
        nm += "."
    if r["type"] == "book":
        extra = ""
        if r.get("edition"):
            extra += f" ({r['edition']})"
        if r.get("translator"):
            tl, tf = r["translator"].rsplit(" ", 1)[1], r["translator"].rsplit(" ", 1)[0]
            extra += f" ({_initials(tf)} {tl}, Trans.)"
        if r.get("editor"):
            el, ef = r["editor"].rsplit(" ", 1)[1], r["editor"].rsplit(" ", 1)[0]
            extra += f" ({_initials(ef)} {el}, Ed.)"
        return f"{nm} ({r['year']}). {r['title']}{extra}. {r['publisher']}."
    if r["type"] == "chapter":
        el, ef = r["editor"].rsplit(" ", 1)[1], r["editor"].rsplit(" ", 1)[0]
        return (
            f"{nm} ({r['year']}). {r['title']}. In {_initials(ef)} {el} (Ed.), {r['book']} "
            f"(pp. {r['pages']}). {r['publisher']}."
        )
    if r["type"] == "article":
        return (
            f"{nm} ({r['year']}). {r['title']}. {r['journal']}, {r['volume']}({r['issue']}), "
            f"{r['pages']}. https://doi.org/{r['doi']}"
        )
    return f"{r['title']}. (n.d.). {r['site']}. {r['url']}"


def chicago_bib(r: dict) -> str:
    au = r.get("authors", [])
    names = ""
    if au:
        names = f"{au[0][0]}, {au[0][1]}" if au[0][1] else au[0][0]
        if len(au) == 2:
            names += f", and {_full(au[1])}"
        elif len(au) > 2:
            names += ", " + ", ".join(_full(a) for a in au[1:-1]) + f", and {_full(au[-1])}"
    if r["type"] == "book":
        extra = ""
        if r.get("translator"):
            extra += f" Translated by {r['translator']}."
        if r.get("editor"):
            extra += f" Edited by {r['editor']}."
        if r.get("edition"):
            extra += f" {r['edition']}"
        return f"{_dot(names)} {r['title']}.{extra} {r['city']}: {r['publisher']}, {r['year']}."
    if r["type"] == "chapter":
        return (
            f'{_dot(names)} "{r["title"]}." In {r["book"]}, edited by {r["editor"]}, {r["pages"]}. '
            f"{r['city']}: {r['publisher']}, {r['year']}."
        )
    if r["type"] == "article":
        return (
            f'{_dot(names)} "{r["title"]}." {r["journal"]} {r["volume"]}, no. {r["issue"]} '
            f"({r['year']}): {r['pages']}. https://doi.org/{r['doi']}."
        )
    return f'{r["site"]}. "{r["title"]}." Accessed March 2, 2026. {r["url"]}.'


def chicago_note(r: dict, page: int) -> str:
    who = _full(r["authors"][0]) if r.get("authors") else ""
    if r["type"] == "book":
        extra = (f", trans. {r['translator']}" if r.get("translator") else "") + (
            f", ed. {r['editor']}" if r.get("editor") else ""
        )
        return f"{who}, {r['title']}{extra} ({r['city']}: {r['publisher']}, {r['year']}), {page}."
    if r["type"] == "chapter":
        return (
            f'{who}, "{r["title"]}," in {r["book"]}, ed. {r["editor"]} ({r["city"]}: '
            f"{r['publisher']}, {r['year']}), {page}."
        )
    if r["type"] == "article":
        where = f"{r['journal']} {r['volume']}, no. {r['issue']} ({r['year']})"
        return f'{who}, "{r["title"]}," {where}: {page}.'
    return f'{r["site"]}, "{r["title"]}," accessed March 2, 2026, {r["url"]}.'


def short_note(r: dict, page: int) -> str:
    who = r["authors"][0][0] if r.get("authors") else r["site"]
    return f"{who}, {r['short']}, {page}."


def sort_key(r: dict) -> str:
    return (r["authors"][0][0] if r.get("authors") else r["title"]).lower()


def sources_for(author: str, rng: random.Random, long: bool = False) -> list[dict]:
    own = C.META[author]["sources"]
    if long:
        return sorted(own + C.POOL, key=sort_key)
    webs = [r for r in C.POOL if r["type"] == "web"]
    arts = [r for r in C.POOL if r["type"] == "article"]
    books = [r for r in C.POOL if r["type"] == "book"]
    picked = rng.sample(webs, 1) + rng.sample(arts, 2) + rng.sample(books, 2)
    return sorted(own + picked, key=sort_key)


def notes_for(author: str, rng: random.Random) -> list[str]:
    own = C.META[author]["sources"]
    art = rng.choice([r for r in C.POOL if r["type"] == "article"])
    pages = [rng.randint(12, 240) for _ in range(N_NOTES)]
    return [
        chicago_note(own[0], pages[0]),
        f"Ibid., {pages[1]}.",
        chicago_note(own[1], pages[2]),
        short_note(own[0], pages[3]),
        chicago_note(art, rng.randint(*map(int, art["pages"].split("-")))),
        short_note(own[1], pages[5]),
    ]


# ── Documents ────────────────────────────────────────────────────────────────


@dataclass
class Para:
    segs: list[tuple[str, str]]  # (text, true kind)
    style: str = "body"  # body|left|center|title|heading|hanging|blank|right
    page_break: bool = False

    @property
    def text(self) -> str:
        return "".join(t for t, _ in self.segs)


@dataclass
class Doc:
    paras: list[Para] = field(default_factory=list)
    header: str | None = None  # "{n}" stands for the page number
    header_align: str = "right"
    footer: str | None = None
    footnotes: list[str] = field(default_factory=list)  # real footnotes (docx only)

    def add(self, text: str, kind: str, style: str = "body", page_break: bool = False) -> None:
        self.paras.append(Para([(text, kind)], style, page_break))


def _student(m: dict) -> str:
    return f"{m['student'][0]} {m['student'][1]}"


def _teacher(m: dict) -> str:
    return " ".join(m["teacher"])


def _teacher_mla(m: dict) -> str:
    return f"{m['teacher'][0]} {m['teacher'][2]}"


def mla_head(d: Doc, m: dict, with_title: bool = True) -> None:
    for line in (_student(m), _teacher_mla(m), m["course"], "14 March 2026"):
        d.add(line, "heading_block", "left")
    if with_title:
        d.add(m["title"], "title", "center")


def prose_paras(
    d: Doc,
    paras: list[str],
    headings: list[str] | None = None,
    md: bool = False,
    markers: dict[int, list[int]] | None = None,
    first_break: bool = False,
) -> None:
    """Body paragraphs; section headings before evenly spaced paragraphs;
    note markers (paragraph -> character offsets) as kind note_marker."""
    at: dict[int, str] = {}
    if headings:
        h = min(len(headings), len(paras) - 1)
        for k in range(1, h + 1):
            at.setdefault(int(len(paras) * k / (h + 1) + 0.5), headings[k - 1])
    num = 0
    for i, p in enumerate(paras):
        if i in at:
            d.add(("## " if md else "") + at[i], "section_heading", "heading")
        segs, pos = [], 0
        for off in (markers or {}).get(i, []):
            num += 1
            segs += [(p[pos:off], "prose"), (str(num), "note_marker")]
            pos = off
        segs.append((p[pos:], "prose"))
        d.paras.append(Para([s for s in segs if s[0]], "body", first_break and i == 0))


def references(d: Doc, recs: list[dict], fmt, heading: str | None, style: str = "center") -> None:
    first = True
    if heading is not None:
        d.add(heading, "references", style, page_break=True)
        first = False
    for r in recs:
        d.add(fmt(r), "references", "hanging", page_break=first)
        first = False


def note_markers(paras: list[str]) -> dict[int, list[int]]:
    ends = [(i, m.end()) for i, p in enumerate(paras) for m in _SENT_END.finditer(p)]
    picks = sorted({ends[int((k + 0.5) * len(ends) / N_NOTES)] for k in range(N_NOTES)})
    out: dict[int, list[int]] = {}
    for i, off in picks:
        out.setdefault(i, []).append(off)
    return out


def apa_title_page(d: Doc, m: dict, professional: bool, md: bool = False) -> None:
    if professional:
        d.add(f"Running head: {m['short']}", "title_page", "left")
    for _ in range(3):
        d.add("", "title_page", "blank")
    d.add(("# " if md else "") + m["title"], "title_page", "title")
    d.add(_student(m), "title_page", "center")
    d.add(f"{m['department']}, {C.INSTITUTION}", "title_page", "center")
    if professional:
        d.add("Author Note", "title_page", "heading")
        first, last = m["student"]
        d.add(
            f"{first} {last} is an undergraduate student in the {m['department']}, "
            f"{C.INSTITUTION}. "
            f"This paper was prepared for {m['course']}, taught by {_teacher(m)}. Correspondence "
            f"concerning this paper should be addressed to {first} {last}, {m['department']}, "
            f"{C.INSTITUTION}. Email: {first[0].lower()}{last.lower()}@westfield.example.edu",
            "title_page",
        )
    else:
        d.add(m["course"], "title_page", "center")
        d.add(_teacher(m), "title_page", "center")
        d.add("March 14, 2026", "title_page", "center")


def apa_abstract(d: Doc, m: dict, label: str = "Abstract", md: bool = False) -> None:
    d.add(label, "abstract", "heading", page_break=True)
    d.add(m["abstract"], "abstract", "left")
    kw = ", ".join(m["keywords"])
    d.add(("**Keywords:** " if md else "Keywords: ") + kw, "abstract", "body")


def build(author: str, variant: str, mode: str) -> Doc:
    """The document for one case. ``mode`` is "paste" (what a teacher would
    paste: no header, notes as endnotes) or "docx" (header/footer, real
    footnotes)."""
    m = C.META[author]
    pr = probe(author)
    rng = random.Random(f"{SEED}:{author}:{variant}")
    d = Doc()
    surname = m["student"][1]
    docx = mode == "docx"

    if variant.startswith("prose"):
        paras = pr["short"] if variant == "prose_short" else list(pr["paras"])
        if variant == "prose_abstract_word":
            paras.insert(len(paras) // 2, C.ABSTRACT_PROSE)
        if variant == "prose_references_sentence":
            paras.insert(len(paras) // 2, C.REFERENCES_PROSE.format(name=m["name"]))
        if variant == "prose_letter":
            d.add(C.LETTER_OPEN, "prose", "left")
        prose_paras(d, paras)
        if variant == "prose_sermon_prayer":
            for line in C.PRAYER_LINES:
                d.add(line, "prose", "left")
        if variant == "prose_letter":
            for line in C.LETTER_CLOSE:
                d.add(line.format(first=m["student"][0]), "prose", "left")
        return d

    if variant in ("mla", "mla_unheaded_refs", "mla_short_long_refs") or variant.startswith("neg_"):
        d.header = f"{surname} {{n}}"
        mla_head(d, m, with_title=variant != "neg_letter")
        paras = pr["short"] if variant == "mla_short_long_refs" else list(pr["paras"])
        if variant == "neg_abstract_word":
            paras.insert(len(paras) // 2, C.ABSTRACT_PROSE)
        if variant == "neg_references_sentence":
            paras.insert(len(paras) // 2, C.REFERENCES_PROSE.format(name=m["name"]))
        if variant == "neg_letter":
            d.add(C.LETTER_OPEN, "prose", "left")
        prose_paras(d, paras)
        if variant == "neg_sermon_prayer":
            for line in C.PRAYER_LINES:
                d.add(line, "prose", "left")
            return d
        if variant == "neg_letter":
            for line in C.LETTER_CLOSE:
                d.add(line.format(first=m["student"][0]), "prose", "left")
            return d
        recs = sources_for(author, rng, long=variant == "mla_short_long_refs")
        heading = None if variant == "mla_unheaded_refs" else "Works Cited"
        references(d, recs, mla, heading)
        return d

    if variant.startswith("apa") or variant == "markdown_apa":
        md = variant == "markdown_apa"
        pro = variant == "apa_professional"
        d.header = f"{m['short']}\t{{n}}" if pro else "{n}"
        apa_title_page(d, m, pro, md)
        label = {"apa_bold_abstract": "**Abstract**", "markdown_apa": "## Abstract"}.get(
            variant, "Abstract"
        )
        apa_abstract(d, m, label, md)
        d.add(
            ("# " if md else "") + m["title"],
            "title",
            "heading" if not md else "left",
            page_break=True,
        )
        prose_paras(d, pr["paras"], m["headings"], md=md)
        heading = {
            "apa_reference_list": "Reference List",
            "apa_literature_cited": "Literature Cited",
            "markdown_apa": "## References",
        }.get(variant, "References")
        references(d, sources_for(author, rng), apa, heading, "heading")
        return d

    # Turabian / Chicago notes-bibliography.
    d.footer = "{n}"
    d.add(C.SEMINARY.upper(), "title_page", "center")
    for _ in range(4):
        d.add("", "title_page", "blank")
    d.add(m["title"].upper(), "title_page", "title")
    for _ in range(4):
        d.add("", "title_page", "blank")
    for line in (
        f"A Paper Submitted to {_teacher(m)}",
        "In Partial Fulfillment of the Requirements for the Course",
        m["course"],
        "",
        "by",
        _student(m),
        "",
        C.CITY,
        "March 2026",
    ):
        d.add(line, "title_page", "center" if line else "blank")
    notes = notes_for(author, rng)
    prose_paras(d, pr["paras"], markers=note_markers(pr["paras"]), first_break=True)
    if docx:
        d.footnotes = notes
    else:
        d.add("Notes", "notes", "center", page_break=True)
        for k, n in enumerate(notes, 1):
            d.add(f"{k}. {n}", "notes", "body")
    references(d, sources_for(author, rng), chicago_bib, "Bibliography")
    if variant == "turabian_appendix":
        d.add("Appendix A", "appendix", "center", page_break=True)
        for p in pr["appendix"]:
            d.add(p, "appendix", "body")
    return d


# ── Rendering ────────────────────────────────────────────────────────────────


def render_paste(d: Doc, sep: str) -> tuple[str, list[str]]:
    text, kinds = [], []
    for p in d.paras:
        if p.style == "blank" or not p.text:
            continue
        if text:
            text.append(sep)
            kinds.extend([L.SEP] * len(sep))
        for t, k in p.segs:
            text.append(t)
            kinds.extend([k] * len(t))
    return "".join(text), kinds


_W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'


def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def render_docx(d: Doc) -> bytes:
    import datetime

    from docx import Document
    from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_TAB_ALIGNMENT
    from docx.opc.constants import RELATIONSHIP_TYPE as RT
    from docx.opc.packuri import PackURI
    from docx.opc.part import Part
    from docx.oxml import parse_xml
    from docx.shared import Inches, Pt, RGBColor

    doc = Document()
    cp = doc.core_properties
    cp.author = cp.last_modified_by = "student"
    cp.created = cp.modified = datetime.datetime(2026, 3, 14, 9, 0, 0)
    cp.revision = 1
    normal = doc.styles["Normal"]
    normal.font.name, normal.font.size = "Times New Roman", Pt(12)
    normal.paragraph_format.line_spacing = 2.0
    normal.paragraph_format.space_after = Pt(0)
    for name, size in (("Title", 14), ("Heading 1", 12)):
        st = doc.styles[name]
        st.font.name, st.font.size, st.font.bold = "Times New Roman", Pt(size), True
        st.font.color.rgb = RGBColor(0, 0, 0)
        st.paragraph_format.space_before = st.paragraph_format.space_after = Pt(0)
        st.paragraph_format.line_spacing = 2.0
    sec = doc.sections[0]
    sec.top_margin = sec.bottom_margin = sec.left_margin = sec.right_margin = Inches(1)

    def page_field(par, template: str) -> None:
        before, _, after = template.partition("{n}")
        if "\t" in before:
            par.paragraph_format.tab_stops.add_tab_stop(Inches(6.5), WD_TAB_ALIGNMENT.RIGHT)
        if before:
            par.add_run(before)
        par._p.append(
            parse_xml(f'<w:fldSimple {_W} w:instr="PAGE"><w:r><w:t>1</w:t></w:r></w:fldSimple>')
        )
        if after:
            par.add_run(after)

    if d.header:
        hp = sec.header.paragraphs[0]
        hp.alignment = WD_ALIGN_PARAGRAPH.LEFT if "\t" in d.header else WD_ALIGN_PARAGRAPH.RIGHT
        page_field(hp, d.header)
    if d.footer:
        fp = sec.footer.paragraphs[0]
        fp.alignment = WD_ALIGN_PARAGRAPH.CENTER
        page_field(fp, d.footer)

    align = {
        "center": WD_ALIGN_PARAGRAPH.CENTER,
        "title": WD_ALIGN_PARAGRAPH.CENTER,
        "heading": WD_ALIGN_PARAGRAPH.CENTER,
        "right": WD_ALIGN_PARAGRAPH.RIGHT,
    }
    first_para = True
    for p in d.paras:
        style = {"title": "Title", "heading": "Heading 1"}.get(p.style)
        if first_para:
            par = doc.paragraphs[0] if doc.paragraphs else doc.add_paragraph()
            if style:
                par.style = doc.styles[style]
            first_para = False
        else:
            par = doc.add_paragraph(style=style)
        if p.style in align:
            par.alignment = align[p.style]
        pf = par.paragraph_format
        if p.style == "body":
            pf.first_line_indent = Inches(0.5)
        elif p.style == "hanging":
            pf.left_indent, pf.first_line_indent = Inches(0.5), Inches(-0.5)
        if p.page_break:
            pf.page_break_before = True
        for t, k in p.segs:
            if k == "note_marker":
                r = par.add_run()
                if d.footnotes:
                    r._r.append(
                        parse_xml(f'<w:rPr {_W}><w:vertAlign w:val="superscript"/></w:rPr>')
                    )
                    r._r.append(parse_xml(f'<w:footnoteReference {_W} w:id="{t}"/>'))
                else:
                    r.text = t
                    r.font.superscript = True
            else:
                par.add_run(t)

    if d.footnotes:
        body = "".join(
            f'<w:footnote w:id="{i}"><w:p><w:r><w:rPr><w:vertAlign w:val="superscript"/></w:rPr>'
            f'<w:footnoteRef/></w:r><w:r><w:t xml:space="preserve"> {_esc(n)}</w:t></w:r></w:p>'
            "</w:footnote>"
            for i, n in enumerate(d.footnotes, 1)
        )
        xml = (
            f'<w:footnotes {_W}><w:footnote w:type="separator" w:id="-1"><w:p><w:r><w:separator/>'
            f'</w:r></w:p></w:footnote><w:footnote w:type="continuationSeparator" w:id="0"><w:p>'
            f"<w:r><w:continuationSeparator/></w:r></w:p></w:footnote>{body}</w:footnotes>"
        )
        part = Part(
            PackURI("/word/footnotes.xml"),
            "application/vnd.openxmlformats-officedocument.wordprocessingml.footnotes+xml",
            xml.encode("utf-8"),
            doc.part.package,
        )
        doc.part.relate_to(part, RT.FOOTNOTES)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def flow_units(d: Doc) -> list[tuple[str, list[str]]]:
    """Body paragraphs as the PDF would print them (note numbers included)."""
    out = []
    for p in d.paras:
        if p.style == "blank" or not p.text.strip():
            continue
        kinds: list[str] = []
        for t, k in p.segs:
            kinds.extend([k] * len(t))
        out.append((p.text, kinds))
    return out


def floating_units(d: Doc, pages: int) -> list[tuple[str, str]]:
    out = []
    for tpl in (d.header, d.footer):
        if tpl:
            out += [(tpl.replace("{n}", str(n)), "page_header") for n in range(1, pages + 1)]
    out += [(f"{i} {n}", "footnote") for i, n in enumerate(d.footnotes, 1)]
    return out


def soffice_pdfs(docx_paths: list[Path], outdir: Path) -> None:
    profile = (HERE / "build" / "lo_profile").resolve()
    for i in range(0, len(docx_paths), 40):
        batch = [str(p) for p in docx_paths[i : i + 40]]
        subprocess.run(
            [
                "soffice",
                f"-env:UserInstallation=file://{profile}",
                "--headless",
                "--convert-to",
                "pdf",
                "--outdir",
                str(outdir),
                *batch,
            ],
            check=True,
            capture_output=True,
            timeout=900,
        )


def main() -> None:
    from pypdf import PdfReader

    from original.upload_utils import extract_text_from_bytes

    split_of = {a: s for s, names in C.SPLIT.items() for a in names}
    build_dir = HERE / "build"
    if build_dir.exists():
        shutil.rmtree(build_dir)
    (build_dir / "files").mkdir(parents=True)
    samples = HERE / "samples"
    if samples.exists():
        shutil.rmtree(samples)
    samples.mkdir()

    docs: dict[tuple[str, str], tuple[Doc, Doc]] = {}
    docx_paths = []
    for a in C.AUTHORS:
        for v in VARIANTS:
            paste_doc, docx_doc = build(a, v, "paste"), build(a, v, "docx")
            docs[(a, v)] = (paste_doc, docx_doc)
            path = build_dir / "files" / f"{a}__{v}.docx"
            path.write_bytes(render_docx(docx_doc))
            docx_paths.append(path)
    print(f"wrote {len(docx_paths)} .docx; converting to PDF", flush=True)
    soffice_pdfs(docx_paths, build_dir / "files")

    records = []
    for (a, v), (paste_doc, docx_doc) in docs.items():
        base = {
            "author": a,
            "split": split_of[a],
            "variant": v,
            "format": FORMAT_OF.get(v, "prose only"),
            "is_control": v in CONTROLS,
            "control": CONTROL_OF.get(v),
        }
        for inp, sep in (("paste", "\n\n"), ("paste_word", "\n")):
            text, kinds = render_paste(paste_doc, sep)
            records.append(
                {
                    **base,
                    "input": inp,
                    "text": text,
                    "labels": L.rle(kinds),
                    "source": L.nonws_counts(text, kinds),
                    "lost": {},
                    "unattributed": 0,
                }
            )
        pdf_path = build_dir / "files" / f"{a}__{v}.pdf"
        pages = len(PdfReader(str(pdf_path)).pages)
        for inp, path in (("docx", build_dir / "files" / f"{a}__{v}.docx"), ("pdf", pdf_path)):
            text = extract_text_from_bytes(path.read_bytes(), path.name)
            res = L.align(text, flow_units(docx_doc), floating_units(docx_doc, pages))
            records.append(
                {
                    **base,
                    "input": inp,
                    "text": text,
                    "labels": L.rle(res["labels"]),
                    "source": res["source"],
                    "lost": res["lost"],
                    "unattributed": res["unattributed"],
                    "pages": pages,
                }
            )
        if a == SAMPLE_AUTHOR and v in SAMPLE_VARIANTS:
            for ext in ("docx", "pdf"):
                shutil.copy(build_dir / "files" / f"{a}__{v}.{ext}", samples / f"{v}.{ext}")
            (samples / f"{v}.txt").write_text(render_paste(paste_doc, "\n\n")[0], encoding="utf-8")
    for r in records:
        r["case_id"] = f"{r['author']}/{r['variant']}/{r['input']}"
        r["sha256"] = hashlib.sha256(r["text"].encode("utf-8")).hexdigest()
    baselines = {a: baseline_texts(a) for a in C.AUTHORS}
    lo = subprocess.run(["soffice", "--version"], capture_output=True, text=True).stdout.strip()
    with lzma.open(HERE / "cases.jsonl.xz", "wt", encoding="utf-8", preset=9) as fh:
        fh.write(
            json.dumps(
                {
                    "_meta": {
                        "seed": SEED,
                        "libreoffice": lo,
                        "split": C.SPLIT,
                        "baselines": baselines,
                    }
                }
            )
            + "\n"
        )
        for r in records:
            fh.write(json.dumps(r) + "\n")
    print(
        f"{len(records)} records ({len(docs)} documents x {len(INPUTS)} inputs); "
        f"unattributed chars total {sum(r['unattributed'] for r in records)}"
    )


if __name__ == "__main__":
    main()
