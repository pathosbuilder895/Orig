"""Harness: how well Original sets the parts of a paper aside, and how much the
parts it misses move a reading. Diagnostic only; nothing in ``original/`` and
no flag default changes.

For every record in ``cases.jsonl.xz`` (``make_cases.py``), with
``MATTER_SPLITTER_ENABLED`` off and on:

* segmentation: which characters ``features.preprocess.body_segments`` leaves
  out of the measured body, compared with the true labels: per part kind,
  the share of its characters set aside (recall), and the share of the true
  prose set aside (false set-aside). Non-whitespace characters only.
* reading: the paper scored through the live ``/students/{id}/score`` route
  (in-process ``TestClient``, the 2026-11-18 harness's pilot-like flags)
  against the author's four genuine past papers, minus the score of the same
  prose alone in the same input type; and whether the action band moved.

Past papers are added with ``UPLOAD_ALSO_MEASURE=matter`` so that with the
splitter on the score really compares like with like (ADR-014); every
flag-on row checks the response's ``measurement.used`` is ``matter``.

    .venv/bin/python validation/diagnostics/document_parts_v2/run.py            # dev split
    .venv/bin/python validation/diagnostics/document_parts_v2/run.py --split holdout   # once
    .venv/bin/python validation/diagnostics/document_parts_v2/run.py --after   # today's extractor

``--after`` reads ``cases_after.jsonl.xz`` (``make_cases.py --reextract``):
the "on" rows of a PDF use its switch-on extraction (``text_on``), and the
segmentation rows also count each part's characters listed as ``possible``
by ``matter.find_parts`` and the page breaks in the text. Output goes to
``*_after`` files, so the "before" results stay as they were.

The hold-out run refuses to run again once ``summary_holdout.json`` exists.
"""

from __future__ import annotations

import argparse
import copy
import datetime
import hashlib
import importlib.util
import json
import lzma
import multiprocessing as mp
import os
import re
import statistics
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def _make_cases():
    """make_cases.py, loaded by path (it loads content.py and labels.py the
    same way), so this folder never goes on sys.path: this file's name would
    shadow the repository's own ``run.py``."""
    key = "_document_parts_v2_make_cases"
    if key not in sys.modules:
        spec = importlib.util.spec_from_file_location(key, HERE / "make_cases.py")
        mod = importlib.util.module_from_spec(spec)
        sys.modules[key] = mod
        spec.loader.exec_module(mod)
    return sys.modules[key]


MC = _make_cases()
L = MC.L

FLAGS = ("off", "on")
MEASUREMENT = {"off": "v1", "on": "matter"}
BAND = {"no_action": 0, "monitor": 1, "schedule_conversation": 2, "escalate": 3}
INPUTS = ("paste", "paste_word", "docx", "pdf")
PART_KINDS = [
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
]
PILOT_ENV = {
    "ORIGINAL_DB": ":memory:",
    "CONTEXT_MANIFEST_ENABLED": "0",
    "ADAPTIVE_WEIGHTS_ENABLED": "0",
    "NULL_MODEL": "none",
    "DRIFT_GATE": "advisory",
    "FEATURE_SET": "1",
    "UPLOAD_ALSO_MEASURE": "matter",
    "MATTER_SPLITTER_ENABLED": "0",
    # Report-only extras that cannot change the score or the action; off so a
    # run takes minutes, not hours (Rule D scans every student per request).
    "EVIDENCE_PASSAGES_ENABLED": "0",
    "RULE_D_OBSERVATION": "off",
    # Four workers on four cores: one BLAS thread each.
    "OMP_NUM_THREADS": "1",
    "OPENBLAS_NUM_THREADS": "1",
    "MKL_NUM_THREADS": "1",
}
CACHE = HERE / "build" / "score_cache"


def load(split: str, cases: str = "cases.jsonl.xz") -> tuple[dict, list[dict]]:
    with lzma.open(HERE / cases, "rt", encoding="utf-8") as fh:
        lines = [json.loads(line) for line in fh]
    meta = lines[0]["_meta"]
    return meta, [r for r in lines[1:] if r["split"] == split]


# ── Segmentation ─────────────────────────────────────────────────────────────


def _runs(text: str, mask: list[bool], labels: list[str], want) -> list[str]:
    """Up to three snippets (first 90 characters) of runs where ``want``."""
    out, i = [], 0
    while i < len(text) and len(out) < 3:
        if want(i):
            j = i
            while j < len(text) and (want(j) or text[j].isspace()):
                j += 1
            snip = " ".join(text[i:j].split())
            if len(snip) > 2:
                out.append(snip[:90])
            i = j
        else:
            i += 1
    return out


def text_for(rec: dict, flag: str) -> tuple[str, list[list]]:
    """The text Original stores for this record with the switch ``flag``: a
    PDF extracted with the switch on is restructured (``cases_after``)."""
    if flag == "on" and "text_on" in rec:
        return rec["text_on"], rec["labels_on"]
    return rec["text"], rec["labels"]


def segment(rec: dict, flag: str) -> dict:
    from original.features import feature_flags as ff
    from original.features import matter
    from original.features.preprocess import body_segments

    text, runs = text_for(rec, flag)
    labels = L.unrle(runs)
    with ff.measuring(MEASUREMENT[flag]):
        kept = body_segments(text)
    aside = [True] * len(text)
    for a, b in kept:
        aside[a:b] = [False] * (b - a)
    product = ["kept" if not x else "cut_to_end" for x in aside]
    maybe = [False] * len(text)
    if flag == "on":
        parts = (
            matter.find_parts(text)
            if hasattr(matter, "find_parts")
            else matter.Parts(matter.find_matter(text), [])  # before step 3
        )
        for r in parts.set_aside:
            for i in range(r.start, min(r.end, len(text))):
                product[i] = r.kind
        for r in parts.possible:
            maybe[r.start : r.end] = [True] * (min(r.end, len(text)) - r.start)
    total: dict[str, int] = {}
    out: dict[str, int] = {}
    possible: dict[str, int] = {}
    confusion: dict[str, dict[str, int]] = {}
    for ch, k, x, pk, mb in zip(text, labels, aside, product, maybe, strict=True):
        if ch.isspace():
            continue
        total[k] = total.get(k, 0) + 1
        if x:
            out[k] = out.get(k, 0) + 1
        elif mb:
            possible[k] = possible.get(k, 0) + 1
        confusion.setdefault(k, {})
        confusion[k][pk] = confusion[k].get(pk, 0) + 1
    return {
        "case_id": rec["case_id"],
        "author": rec["author"],
        "variant": rec["variant"],
        "format": rec["format"],
        "input": rec["input"],
        "flag": flag,
        "chars": total,
        "set_aside": out,
        "possible": possible,
        "page_breaks": text.count("\f"),
        "product_kind": confusion,
        "prose_set_aside_examples": _runs(
            text, aside, labels, lambda i: aside[i] and labels[i] == "prose"
        ),
        "part_kept_examples": _runs(
            text, aside, labels, lambda i: not aside[i] and labels[i] in PART_KINDS
        ),
    }


# ── Scoring (worker processes) ───────────────────────────────────────────────

_W: dict = {}


def _worker_init() -> None:
    sys.modules["sentence_transformers"] = None  # the pilot lockfile has none
    os.environ.update(PILOT_ENV)
    logging_quiet()
    from fastapi.testclient import TestClient

    from original import api

    _W["client"] = TestClient(api.app)
    _W["bases"] = {}
    _W["n"] = 0


def logging_quiet() -> None:
    import logging

    logging.disable(logging.WARNING)


def _base(author: str, baselines: list[str]) -> str:
    if author in _W["bases"]:
        return _W["bases"][author]
    c = _W["client"]
    sid = f"demo:v2base_{author}_{os.getpid()}"
    for i, t in enumerate(baselines):
        r = c.post(
            f"/students/{sid}/baseline",
            json={"text": t, "provenance": "verified", "submitted_at": f"2026-01-{i + 1:02d}"},
        )
        assert r.status_code == 200, (r.status_code, r.text[:300])
    _W["bases"][author] = sid
    return sid


def _clone(base_sid: str) -> str:
    """A fresh student holding the same past papers, so no score ever sees
    another score's history."""
    from original.routers._shared import _repo

    _W["n"] += 1
    sid = f"{base_sid}_c{_W['n']}"
    state = copy.deepcopy(_repo().get(base_sid))
    state.student_id = sid
    _repo().put(state)
    return sid


def _repo_delete(sid: str) -> None:
    from original.routers._shared import _repo

    _repo().delete_student(sid)


_CODE_HASH: list[str] = []


def code_hash() -> str:
    """A hash of every file under ``original/`` (path and bytes), so a cached
    score is never served after the engine or the splitter's rules changed."""
    if not _CODE_HASH:
        h = hashlib.sha256()
        src = ROOT / "original"
        for path in sorted(src.rglob("*")):
            if not path.is_file() or "__pycache__" in path.parts or path.suffix == ".pyc":
                continue
            h.update(str(path.relative_to(src)).encode())
            h.update(b"\x00")
            h.update(path.read_bytes())
            h.update(b"\x00")
        _CODE_HASH.append(h.hexdigest())
    return _CODE_HASH[0]


def _task_key(task: tuple[str, list[str], list[dict]]) -> str:
    author, baselines, recs = task
    shas = [[r["sha256"], r.get("sha256_on")] for r in recs]
    h = hashlib.sha256(json.dumps([code_hash(), PILOT_ENV, baselines, shas]).encode())
    return f"{author}_{recs[0]['input']}_{h.hexdigest()[:16]}"


def _cached_task(task: tuple[str, list[str], list[dict]]) -> list[dict]:
    """One task's rows, from build/score_cache when the same texts and flags
    were scored before (so a stopped run resumes where it stopped)."""
    path = CACHE / f"{_task_key(task)}.json"
    if path.exists():
        return json.loads(path.read_text())
    if "client" not in _W:
        _worker_init()
    rows = _score_task(task)
    CACHE.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rows))
    return rows


def _score_task(task: tuple[str, list[str], list[dict]]) -> list[dict]:
    author, baselines, recs = task
    base = _base(author, baselines)
    c = _W["client"]
    rows = []
    for rec in recs:
        for flag in FLAGS:
            os.environ["MATTER_SPLITTER_ENABLED"] = "1" if flag == "on" else "0"
            sid = _clone(base)
            text = text_for(rec, flag)[0]
            r = c.post(f"/students/{sid}/score", json={"text": text, "submission_id": f"{sid}_s"})
            assert r.status_code == 200, (rec["case_id"], r.status_code, r.text[:300])
            d = r.json()
            _repo_delete(sid)
            used = (d.get("measurement") or {}).get("used", "v1")
            assert used == MEASUREMENT[flag], (rec["case_id"], flag, d.get("measurement"))
            rows.append(
                {
                    "case_id": rec["case_id"],
                    "author": author,
                    "variant": rec["variant"],
                    "format": rec["format"],
                    "input": rec["input"],
                    "flag": flag,
                    "control": rec["control"],
                    "is_control": rec["is_control"],
                    "deviation": d["authorship"]["deviation_score"],
                    "action": d["recommendation"]["action"],
                    "measurement": used,
                    "words": len(text.split()),
                }
            )
    os.environ["MATTER_SPLITTER_ENABLED"] = "0"
    return rows


def _determinism_check(baselines: dict, recs: list[dict]) -> dict:
    """The same text on two fresh clones must score identically."""
    _worker_init()
    rec = next(r for r in recs if r["variant"] == "prose" and r["input"] == "paste")
    a = _score_task((rec["author"], baselines[rec["author"]], [rec]))
    b = _score_task((rec["author"], baselines[rec["author"]], [rec]))
    same = [x["deviation"] for x in a] == [y["deviation"] for y in b]
    return {
        "case_id": rec["case_id"],
        "identical": same,
        "deviations": [x["deviation"] for x in a + b],
    }


# ── Summaries ────────────────────────────────────────────────────────────────


def _ratio(a: int, b: int) -> float | None:
    return round(a / b, 4) if b else None


def seg_summary(seg_rows: list[dict], key) -> dict:
    out: dict = {}
    for r in seg_rows:
        g = (
            out.setdefault(r["flag"], {})
            .setdefault(r["input"], {})
            .setdefault(
                key(r),
                {
                    "n_cases": 0,
                    "parts": {},
                    "prose": {
                        "chars": 0,
                        "set_aside": 0,
                        "possible": 0,
                        "cases_any": 0,
                        "per_case": [],
                    },
                },
            )
        )
        g["n_cases"] += 1
        pc = r["chars"].get("prose", 0)
        pa = r["set_aside"].get("prose", 0)
        g["prose"]["chars"] += pc
        g["prose"]["set_aside"] += pa
        g["prose"]["possible"] += r.get("possible", {}).get("prose", 0)
        g["prose"]["cases_any"] += int(pa > 0)
        g["prose"]["per_case"].append(_ratio(pa, pc))
        for k in PART_KINDS:
            n = r["chars"].get(k, 0)
            if not n:
                continue
            p = g["parts"].setdefault(
                k, {"n_cases": 0, "chars": 0, "set_aside": 0, "possible": 0, "per_case": []}
            )
            p["n_cases"] += 1
            p["possible"] += r.get("possible", {}).get(k, 0)
            p["chars"] += n
            p["set_aside"] += r["set_aside"].get(k, 0)
            p["per_case"].append(_ratio(r["set_aside"].get(k, 0), n))
    for flag in out.values():
        for inp in flag.values():
            for g in inp.values():
                pr = g["prose"]
                pr["pooled"] = _ratio(pr["set_aside"], pr["chars"])
                pr["max_case"] = max((x for x in pr.pop("per_case") if x is not None), default=None)
                for p in g["parts"].values():
                    pcs = [x for x in p.pop("per_case") if x is not None]
                    p["pooled"] = _ratio(p["set_aside"], p["chars"])
                    p["min_case"], p["max_case"] = min(pcs), max(pcs)
    return out


def reading_summary(score_rows: list[dict]) -> dict:
    by = {(r["author"], r["variant"], r["input"], r["flag"]): r for r in score_rows}
    out: dict = {}
    for r in score_rows:
        if r["is_control"]:
            continue
        ctl = by[(r["author"], r["control"], r["input"], r["flag"])]
        g = (
            out.setdefault(r["flag"], {})
            .setdefault(r["input"], {})
            .setdefault(r["variant"], {"compared_with": r["control"], "changes": {}, "band": {}})
        )
        g["changes"][r["author"]] = round(r["deviation"] - ctl["deviation"], 4)
        g["band"][r["author"]] = BAND[r["action"]] - BAND[ctl["action"]]
    for flag in out.values():
        for inp in flag.values():
            for g in inp.values():
                ch = list(g["changes"].values())
                g.update(
                    n=len(ch),
                    mean=round(statistics.mean(ch), 4),
                    min=min(ch),
                    max=max(ch),
                    within_001=sum(abs(x) <= 0.01 for x in ch),
                    band_up=sum(b > 0 for b in g["band"].values()),
                    band_down=sum(b < 0 for b in g["band"].values()),
                )
    return out


def extraction_summary(recs: list[dict], score_rows: list[dict]) -> dict:
    out: dict = {}
    on: dict = {}
    for r in recs:
        if "lost_on" in r:
            g = on.setdefault(r["input"], {"records": 0, "source": {}, "lost": {}})
            g["records"] += 1
            for k, n in r["source"].items():
                g["source"][k] = g["source"].get(k, 0) + n
            for k, n in r["lost_on"].items():
                g["lost"][k] = g["lost"].get(k, 0) + n
    for g in on.values():
        g["lost_share"] = {k: _ratio(g["lost"].get(k, 0), n) for k, n in g["source"].items()}
    for r in recs:
        g = out.setdefault(r["input"], {"records": 0, "source": {}, "lost": {}, "unattributed": 0})
        g["records"] += 1
        g["unattributed"] += r["unattributed"]
        for k, n in r["source"].items():
            g["source"][k] = g["source"].get(k, 0) + n
        for k, n in r["lost"].items():
            g["lost"][k] = g["lost"].get(k, 0) + n
    for g in out.values():
        g["lost_share"] = {k: _ratio(g["lost"].get(k, 0), n) for k, n in g["source"].items()}
    # What the input type alone does to a reading: prose only, vs pasted prose.
    by = {(r["author"], r["variant"], r["input"], r["flag"]): r for r in score_rows}
    effect: dict = {}
    for (a, v, inp, flag), r in by.items():
        if v != "prose" or inp == "paste":
            continue
        d = r["deviation"] - by[(a, v, "paste", flag)]["deviation"]
        effect.setdefault(flag, {}).setdefault(inp, {})[a] = round(d, 4)
    breaks = {}
    for r in recs:
        if "page_breaks" in r:
            b = breaks.setdefault(r["input"], {"records": 0, "with_breaks": 0, "breaks": 0})
            b["records"] += 1
            b["with_breaks"] += int(r["page_breaks"] > 0)
            b["breaks"] += r["page_breaks"]
    return {
        "per_input": out,
        "per_input_switch_on": on,
        "page_breaks": breaks,
        "prose_only_vs_paste": effect,
    }


# ── Report tables ────────────────────────────────────────────────────────────

COLS = [
    ("title page", ["title_page"]),
    ("heading block", ["heading_block"]),
    ("title", ["title"]),
    ("abstract", ["abstract"]),
    ("section headings", ["section_heading"]),
    ("references", ["references"]),
    ("notes", ["notes", "footnote"]),
    ("appendix", ["appendix"]),
    ("running head", ["page_header"]),
]


def _pct(x: float | None) -> str:
    return "" if x is None else f"{100 * x:.0f}%"


def _pooled(g: dict, kinds: list[str]) -> float | None:
    chars = sum(g["parts"].get(k, {}).get("chars", 0) for k in kinds)
    aside = sum(g["parts"].get(k, {}).get("set_aside", 0) for k in kinds)
    return _ratio(aside, chars)


def seg_table(seg: dict, keys: list[str], label: str) -> str:
    head = f"| {label} | Input | n | " + " | ".join(c for c, _ in COLS) + " | **prose set aside** |"
    lines = [head, "|" + "---|" * (len(COLS) + 4)]
    for key in keys:
        for inp in INPUTS:
            off, on = seg["off"][inp].get(key), seg["on"][inp].get(key)
            if not off:
                continue
            cells = []
            for _, kinds in COLS:
                a, b = _pooled(off, kinds), _pooled(on, kinds)
                cells.append("" if a is None else f"{_pct(a)} / {_pct(b)}")
            fa, fb = off["prose"]["pooled"], on["prose"]["pooled"]
            cells.append(f"**{_pct(fa)} / {_pct(fb)}**")
            lines.append(f"| {key} | {inp} | {off['n_cases']} | " + " | ".join(cells) + " |")
    return "\n".join(lines)


def reading_table(rd: dict, variants: list[str]) -> str:
    lines = [
        "| Variant | Input | n | mean change off / on | range on | within 0.01 on "
        "| band up off / on |",
        "|---|---|---|---|---|---|---|",
    ]
    for v in variants:
        for inp in INPUTS:
            off, on = rd["off"].get(inp, {}).get(v), rd["on"].get(inp, {}).get(v)
            if not off:
                continue
            lines.append(
                f"| {v} | {inp} | {on['n']} | {off['mean']:+.3f} / {on['mean']:+.3f} | "
                f"{on['min']:+.3f} to {on['max']:+.3f} | {on['within_001']} | "
                f"{off['band_up']} / {on['band_up']} |"
            )
    return "\n".join(lines)


def extraction_table(ex: dict) -> str:
    kinds = sorted({k for g in ex["per_input"].values() for k in g["source"]})
    lines = [
        "| Input | " + " | ".join(kinds) + " | unattributed chars |",
        "|" + "---|" * (len(kinds) + 2),
    ]
    for inp in INPUTS:
        g = ex["per_input"].get(inp)
        if not g:
            continue
        cells = [_pct(g["lost_share"].get(k)) if k in g["source"] else "" for k in kinds]
        lines.append(f"| {inp} | " + " | ".join(cells) + f" | {g['unattributed']} |")
    return "\n".join(lines)


def possible_table(seg: dict, keys: list[str]) -> str:
    lines = [
        "| Format | Input | n | " + " | ".join(c for c, _ in COLS) + " | prose |",
        "|" + "---|" * (len(COLS) + 4),
    ]
    for key in keys:
        for inp in INPUTS:
            g = seg["on"][inp].get(key)
            if not g:
                continue
            cells = []
            for _, kinds in COLS:
                chars = sum(g["parts"].get(k, {}).get("chars", 0) for k in kinds)
                maybe = sum(g["parts"].get(k, {}).get("possible", 0) for k in kinds)
                cells.append(_pct(_ratio(maybe, chars)))
            cells.append(_pct(_ratio(g["prose"]["possible"], g["prose"]["chars"])))
            lines.append(f"| {key} | {inp} | {g['n_cases']} | " + " | ".join(cells) + " |")
    return "\n".join(lines)


def render_tables(summary: dict, variants: list[str]) -> str:
    seg_v, seg_f = summary["segmentation_by_variant"], summary["segmentation_by_format"]
    parts = [
        "Each cell: share of that part's characters set aside, splitter **off / on**; "
        "last column: share of the true prose set aside (false set-aside), off / on. "
        "Non-whitespace characters, pooled over the n papers in the row.",
        "",
        "#### By format",
        "",
        seg_table(seg_f, ["MLA", "APA", "Turabian", "prose only"], "Format"),
        "",
        "#### By variant",
        "",
        seg_table(seg_v, variants, "Variant"),
        "",
        "#### Reading change (deviation with the parts minus the same prose alone, "
        "same input type)",
        "",
        reading_table(summary["reading"], [v for v in variants if not v.startswith("prose")]),
        "",
        "#### Lost in extraction (share of each part's source characters not found "
        "in the extracted text)",
        "",
        extraction_table(summary["extraction"]),
    ]
    if any(
        p.get("possible") for inp in seg_f["on"].values() for g in inp.values()
        for p in [*g["parts"].values(), g["prose"]]
    ):
        parts += [
            "",
            "#### Listed as possible, splitter on (measured as prose, shown to the teacher)",
            "",
            "Share of each part's characters, and of the true prose, inside a `possible` "
            "range and not set aside.",
            "",
            possible_table(seg_f, ["MLA", "APA", "Turabian", "prose only"]),
        ]
    return "\n".join(parts)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--split", choices=("dev", "holdout"), default="dev")
    ap.add_argument("--workers", type=int, default=min(4, os.cpu_count() or 1))
    ap.add_argument(
        "--segment-only", action="store_true", help="skip scoring (seconds, not minutes)"
    )
    ap.add_argument(
        "--after",
        action="store_true",
        help="read cases_after.jsonl.xz (today's extractor) and write *_after files",
    )
    args = ap.parse_args()
    held = HERE / f"summary_holdout{'_after' if args.after else ''}.json"
    if args.split == "holdout" and held.exists():
        sys.exit(
            f"{held.name} exists: the hold-out has been looked at once already. "
            "Do not re-run it to tune against it; see README."
        )

    t0 = time.time()
    meta, recs = load(args.split, "cases_after.jsonl.xz" if args.after else "cases.jsonl.xz")
    CONTROLS, VARIANTS = MC.CONTROLS, MC.VARIANTS

    seg_rows = [segment(r, f) for r in recs for f in FLAGS]
    print(f"segmentation: {len(seg_rows)} rows in {time.time() - t0:.0f}s", flush=True)

    score_rows: list[dict] = []
    determinism = None
    if not args.segment_only:
        tasks = []
        for a in sorted({r["author"] for r in recs}):
            for pair in (("paste", "paste_word"), ("docx", "pdf")):
                tasks.append(
                    (
                        a,
                        meta["baselines"][a],
                        [r for r in recs if r["author"] == a and r["input"] in pair],
                    )
                )
        ctx = mp.get_context("spawn")
        with ctx.Pool(args.workers) as pool:
            for k, rows in enumerate(pool.imap_unordered(_cached_task, tasks), 1):
                score_rows += rows
                print(f"scored {k}/{len(tasks)} tasks ({time.time() - t0:.0f}s)", flush=True)
        with ctx.Pool(1) as pool:
            determinism = pool.apply(_determinism_check, (meta["baselines"], recs))
        score_rows.sort(key=lambda r: (r["case_id"], r["flag"]))
        # The main run's rows may come from build/score_cache; the check above
        # always scores fresh, so the two must agree (stale cache guard).
        main_run = [r["deviation"] for r in score_rows if r["case_id"] == determinism["case_id"]]
        determinism["main_run_deviations"] = main_run
        determinism["main_run_matches_fresh"] = main_run == determinism["deviations"][:2]
        assert determinism["main_run_matches_fresh"], determinism

    variants = [v for v in VARIANTS if any(r["variant"] == v for r in recs)]
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True
    ).stdout.strip()
    summary = {
        "split": args.split,
        "authors": sorted({r["author"] for r in recs}),
        "commit": commit,
        "code_hash": code_hash(),
        "flags": {k: v for k, v in PILOT_ENV.items() if k != "ORIGINAL_DB"},
        "libreoffice": meta["libreoffice"],
        "n_records": len(recs),
        "segmentation_by_variant": seg_summary(seg_rows, lambda r: r["variant"]),
        "segmentation_by_format": seg_summary(
            seg_rows, lambda r: "prose only" if r["variant"] in CONTROLS else r["format"]
        ),
        "determinism": determinism,
        "runtime_seconds": round(time.time() - t0),
    }
    if score_rows:
        summary["reading"] = reading_summary(score_rows)
        summary["extraction"] = extraction_summary(recs, score_rows)
    if args.split == "holdout":
        summary["HOLDOUT_LOOKED_AT"] = {
            "at": datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds"),
            "note": "Computed once and not reported. Any rule tuned after this date has "
            "seen these numbers only if someone opened this file; say so if you did.",
        }
    # A segmentation-only run has no reading or extraction sections, so it
    # never overwrites a full run's files.
    stem = args.split + ("_after" if args.after else "")
    stem += "_segment_only" if args.segment_only else ""
    (HERE / f"rows_{stem}.json").write_text(
        json.dumps({"segmentation": seg_rows, "scores": score_rows}, indent=0) + "\n"
    )
    (HERE / f"summary_{stem}.json").write_text(
        json.dumps(summary, indent=1, sort_keys=True) + "\n"
    )
    if args.split == "dev" and score_rows:
        tables = render_tables(summary, variants)
        tag = "dev_after" if args.after else "dev"
        (HERE / f"tables_{tag}.md").write_text(tables + "\n")
        readme = HERE / "README.md"
        if readme.exists():
            txt = readme.read_text()
            new = re.sub(
                rf"(<!-- tables:{tag} -->\n).*?(<!-- /tables:{tag} -->)",
                lambda m: m.group(1) + tables + "\n" + m.group(2),
                txt,
                flags=re.S,
            )
            readme.write_text(new)
    print(f"done in {time.time() - t0:.0f}s: summary_{stem}.json", flush=True)


if __name__ == "__main__":
    main()
