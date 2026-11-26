"""Paste format: does the ``para`` measurement (``PARAGRAPH_BREAKS_ENABLED``,
``original/features/paragraphs.py``) make a single-newline paste read like the
same paper pasted with blank lines, and leave every other input unchanged?
Diagnostic only, dev split only; nothing in ``original/`` and no flag default
changes.

Every dev record of ``cases_after.jsonl.xz`` is scored through the live
``/students/{id}/score`` route with ``run.py``'s pilot-like flags, four ways:
``v1`` and ``matter`` (as ``run.py --after`` scores them) and ``para`` and
``matter+para``. Past papers are added with ``UPLOAD_ALSO_MEASURE`` set to the
measurement scored, so each score compares like with like (ADR-014); every
row checks the response's ``measurement.used``.

    .venv/bin/python -I validation/diagnostics/document_parts_v2/run_paragraphs.py

Writes ``rows_dev_paragraphs.json``, ``summary_dev_paragraphs.json`` and
``tables_dev_paragraphs.md``, and the tables into README.md between the
``tables:dev_paragraphs`` markers. There is no hold-out mode.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import importlib.util
import json
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


def _run_module():
    """run.py, loaded by path (its name would shadow the repository's run.py)."""
    key = "_document_parts_v2_run"
    if key not in sys.modules:
        spec = importlib.util.spec_from_file_location(key, HERE / "run.py")
        mod = importlib.util.module_from_spec(spec)
        sys.modules[key] = mod
        spec.loader.exec_module(mod)
    return sys.modules[key]


R = _run_module()

#: measurement -> (MATTER_SPLITTER_ENABLED, PARAGRAPH_BREAKS_ENABLED)
MEASUREMENTS = {
    "v1": ("0", "0"),
    "matter": ("1", "0"),
    "para": ("0", "1"),
    "matter+para": ("1", "1"),
}
#: Each new measurement against the one it adds to.
PAIRS = (("para", "v1"), ("matter+para", "matter"))
ENV = {**R.PILOT_ENV, "PARAGRAPH_BREAKS_ENABLED": "0"}
CACHE = HERE / "build" / "score_cache_paragraphs"

_W: dict = {}


def _init() -> None:
    sys.modules["sentence_transformers"] = None  # the pilot lockfile has none
    os.environ.update(ENV)
    R.logging_quiet()
    from fastapi.testclient import TestClient

    from original import api

    _W["client"] = TestClient(api.app)
    _W["bases"] = {}
    _W["n"] = 0


def _set(matter: str, para: str) -> None:
    os.environ["MATTER_SPLITTER_ENABLED"] = matter
    os.environ["PARAGRAPH_BREAKS_ENABLED"] = para


def _base(author: str, measurement: str, baselines: list[str]) -> str:
    key = (author, measurement)
    if key in _W["bases"]:
        return _W["bases"][key]
    c = _W["client"]
    sid = f"demo:v2para_{author}_{measurement.replace('+', '_')}_{os.getpid()}"
    os.environ["UPLOAD_ALSO_MEASURE"] = "matter" if measurement == "v1" else measurement
    _set("0", "0")
    for i, t in enumerate(baselines):
        r = c.post(
            f"/students/{sid}/baseline",
            json={"text": t, "provenance": "verified", "submitted_at": f"2026-01-{i + 1:02d}"},
        )
        assert r.status_code == 200, (r.status_code, r.text[:300])
    os.environ["UPLOAD_ALSO_MEASURE"] = ENV["UPLOAD_ALSO_MEASURE"]
    _W["bases"][key] = sid
    return sid


def _clone(base_sid: str) -> str:
    from original.routers._shared import _repo

    _W["n"] += 1
    sid = f"{base_sid}_c{_W['n']}"
    state = copy.deepcopy(_repo().get(base_sid))
    state.student_id = sid
    _repo().put(state)
    return sid


def _score_task(task: tuple[str, str, list[str], list[dict]]) -> list[dict]:
    from original.routers._shared import _repo

    author, measurement, baselines, recs = task
    base = _base(author, measurement, baselines)
    c = _W["client"]
    rows = []
    for rec in recs:
        _set(*MEASUREMENTS[measurement])
        sid = _clone(base)
        text = rec["text"]
        r = c.post(f"/students/{sid}/score", json={"text": text, "submission_id": f"{sid}_s"})
        assert r.status_code == 200, (rec["case_id"], r.status_code, r.text[:300])
        d = r.json()
        _repo().delete_student(sid)
        used = (d.get("measurement") or {}).get("used", "v1")
        assert used == measurement, (rec["case_id"], measurement, d.get("measurement"))
        rows.append(
            {
                "case_id": rec["case_id"],
                "author": author,
                "variant": rec["variant"],
                "input": rec["input"],
                "measurement": measurement,
                "deviation": d["authorship"]["deviation_score"],
                "action": d["recommendation"]["action"],
            }
        )
    _set("0", "0")
    return rows


def _key(task) -> str:
    author, measurement, baselines, recs = task
    shas = [r["sha256"] for r in recs]
    h = hashlib.sha256(json.dumps([R.code_hash(), ENV, measurement, baselines, shas]).encode())
    return f"{author}_{measurement.replace('+', '_')}_{recs[0]['input']}_{h.hexdigest()[:16]}"


def _cached(task) -> list[dict]:
    path = CACHE / f"{_key(task)}.json"
    if path.exists():
        return json.loads(path.read_text())
    if "client" not in _W:
        _init()
    rows = _score_task(task)
    CACHE.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(rows))
    return rows


# ── Summaries ────────────────────────────────────────────────────────────────


def _stats(changes: dict[str, float], bands: dict[str, int]) -> dict:
    ch = list(changes.values())
    return {
        "n": len(ch),
        "changes": changes,
        "band": bands,
        "mean": round(statistics.mean(ch), 4),
        "min": round(min(ch), 4),
        "max": round(max(ch), 4),
        "band_up": sum(b > 0 for b in bands.values()),
        "band_down": sum(b < 0 for b in bands.values()),
    }


def summarise(rows: list[dict]) -> dict:
    by = {(r["author"], r["variant"], r["input"], r["measurement"]): r for r in rows}
    authors = sorted({r["author"] for r in rows})
    variants = sorted({r["variant"] for r in rows})
    # 1. Single-newline paste minus blank-line paste, same paper, per measurement.
    word_vs_blank: dict = {}
    for m in MEASUREMENTS:
        for v in variants:
            ch, bd = {}, {}
            for a in authors:
                w, b = by[(a, v, "paste_word", m)], by[(a, v, "paste", m)]
                ch[a] = round(w["deviation"] - b["deviation"], 4)
                bd[a] = R.BAND[w["action"]] - R.BAND[b["action"]]
            word_vs_blank.setdefault(m, {})[v] = _stats(ch, bd)
    # 2. The new measurement against the one it adds to, per input type.
    unchanged: dict = {}
    for new, old in PAIRS:
        for inp in R.INPUTS:
            same = moved = 0
            ch, bd = {}, {}
            for a in authors:
                for v in variants:
                    x, y = by[(a, v, inp, new)], by[(a, v, inp, old)]
                    if x["deviation"] == y["deviation"] and x["action"] == y["action"]:
                        same += 1
                    else:
                        moved += 1
                    if v == "prose":
                        ch[a] = round(x["deviation"] - y["deviation"], 4)
                        bd[a] = R.BAND[x["action"]] - R.BAND[y["action"]]
            unchanged.setdefault(f"{new} vs {old}", {})[inp] = {
                "papers": same + moved,
                "identical": same,
                "moved": moved,
                "prose": _stats(ch, bd),
            }
    return {"word_vs_blank": word_vs_blank, "new_vs_old": unchanged}


def byte_identity_vs_after(rows: list[dict]) -> dict:
    """Do this run's ``v1`` and ``matter`` rows equal ``rows_dev_after.json``
    (``run.py --after``, flag off / on), deviation to the last bit and action?"""
    path = HERE / "rows_dev_after.json"
    if not path.exists():
        return {"compared": 0, "note": "rows_dev_after.json not found"}
    old = {
        (r["case_id"], {"off": "v1", "on": "matter"}[r["flag"]]): r
        for r in json.loads(path.read_text())["scores"]
    }
    same = differ = 0
    examples = []
    for r in rows:
        o = old.get((r["case_id"], r["measurement"]))
        if o is None:
            continue
        if o["deviation"] == r["deviation"] and o["action"] == r["action"]:
            same += 1
        else:
            differ += 1
            if len(examples) < 5:
                examples.append([r["case_id"], r["measurement"], o["deviation"], r["deviation"]])
    return {"compared": same + differ, "identical": same, "differ": differ, "examples": examples}


def _f(x: float) -> str:
    return f"{x:+.3f}"


def render(summary: dict) -> str:
    wvb = summary["word_vs_blank"]
    authors = summary["authors"]
    out = [
        "Published prose, not student writing; diagnostic; dev split only; n = 6 papers "
        "per row, so band counts show direction, not rates (**uninformative** as "
        "proportions).",
        "",
        "#### Single-newline paste minus blank-line paste (same paper), per author",
        "",
        "| Variant | Measurement | " + " | ".join(authors) + " | mean | band up / down |",
        "|---|---|" + "---|" * len(authors) + "---|---|",
    ]
    for v in ("prose", "prose_short"):
        for m in MEASUREMENTS:
            s = wvb[m][v]
            cells = [
                _f(s["changes"][a]) + (f" ({s['band'][a]:+d} band)" if s["band"][a] else "")
                for a in authors
            ]
            out.append(
                f"| {v} | {m} | "
                + " | ".join(cells)
                + f" | {_f(s['mean'])} | {s['band_up']} / {s['band_down']} |"
            )
    out += [
        "",
        "#### Single-newline minus blank-line paste, every variant (mean; range; band up / down)",
        "",
        "| Variant | " + " | ".join(MEASUREMENTS) + " |",
        "|---|" + "---|" * len(MEASUREMENTS),
    ]
    for v in sorted(wvb["v1"]):
        cells = []
        for m in MEASUREMENTS:
            s = wvb[m][v]
            cells.append(
                f"{_f(s['mean'])}; {_f(s['min'])} to {_f(s['max'])}; "
                f"{s['band_up']} / {s['band_down']}"
            )
        out.append(f"| {v} | " + " | ".join(cells) + " |")
    out += [
        "",
        "#### The new measurement against the one it adds to, per input type",
        "",
        "Papers: every dev variant x author (21 x 6). Identical: same deviation to the last "
        "bit and same action.",
        "",
        "| Comparison | Input | papers | identical | moved | prose: mean change | prose: band "
        "up / down |",
        "|---|---|---|---|---|---|---|",
    ]
    for comp, per in summary["new_vs_old"].items():
        for inp, g in per.items():
            p = g["prose"]
            out.append(
                f"| {comp} | {inp} | {g['papers']} | {g['identical']} | {g['moved']} | "
                f"{_f(p['mean'])} | {p['band_up']} / {p['band_down']} |"
            )
    b = summary["byte_identity_vs_after"]
    out += [
        "",
        f"`v1` and `matter` rows against `rows_dev_after.json` (`run.py --after`): "
        f"{b.get('identical', 0)} of {b['compared']} identical.",
    ]
    return "\n".join(out)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--workers", type=int, default=min(4, os.cpu_count() or 1))
    args = ap.parse_args()
    t0 = time.time()
    meta, recs = R.load("dev", "cases_after.jsonl.xz")  # dev only, never the hold-out
    assert {r["split"] for r in recs} == {"dev"}
    tasks = []
    for a in sorted({r["author"] for r in recs}):
        for m in MEASUREMENTS:
            for pair in (("paste", "paste_word"), ("docx", "pdf")):
                tasks.append(
                    (
                        a,
                        m,
                        meta["baselines"][a],
                        [r for r in recs if r["author"] == a and r["input"] in pair],
                    )
                )
    rows: list[dict] = []
    ctx = mp.get_context("spawn")
    with ctx.Pool(args.workers) as pool:
        for k, got in enumerate(pool.imap_unordered(_cached, tasks), 1):
            rows += got
            print(f"scored {k}/{len(tasks)} tasks ({time.time() - t0:.0f}s)", flush=True)
    rows.sort(key=lambda r: (r["case_id"], r["measurement"]))
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True
    ).stdout.strip()
    summary = {
        "split": "dev",
        "label": "Published prose, not student writing. Diagnostic, not validation; n = 6.",
        "authors": sorted({r["author"] for r in recs}),
        "commit": commit,
        "code_hash": R.code_hash(),
        "flags": {k: v for k, v in ENV.items() if k != "ORIGINAL_DB"},
        "n_rows": len(rows),
        **summarise(rows),
        "byte_identity_vs_after": byte_identity_vs_after(rows),
        "runtime_seconds": round(time.time() - t0),
    }
    (HERE / "rows_dev_paragraphs.json").write_text(json.dumps({"scores": rows}, indent=0) + "\n")
    (HERE / "summary_dev_paragraphs.json").write_text(
        json.dumps(summary, indent=1, sort_keys=True) + "\n"
    )
    tables = render(summary)
    (HERE / "tables_dev_paragraphs.md").write_text(tables + "\n")
    readme = HERE / "README.md"
    txt = readme.read_text()
    readme.write_text(
        re.sub(
            r"(<!-- tables:dev_paragraphs -->\n).*?(<!-- /tables:dev_paragraphs -->)",
            lambda mt: mt.group(1) + tables + "\n" + mt.group(2),
            txt,
            flags=re.S,
        )
    )
    print(f"done in {time.time() - t0:.0f}s: summary_dev_paragraphs.json", flush=True)


if __name__ == "__main__":
    main()
