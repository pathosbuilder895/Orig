"""AI-mirror study of rule D: pick 20 locked_test authors, write the prompt sheet.

Each target is one held-out paper (the same one the seed-7 trial would use as
its first new paper). An AI chat tool is asked to write a paper with that title
for that journal; later steps score the reply against the author's baseline.
Only published titles and journal names are used; no student writing is involved.

    python -m validation.scholarly.ai_mirror select
    python -m validation.scholarly.ai_mirror intake --author A... --model "..." --date YYYY-MM-DD --route app
    python -m validation.scholarly.ai_mirror check-env
    python -m validation.scholarly.ai_mirror locked --study scholarly-ai-mirror-2026-11-16   (once)
"""
from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import math
import random
import re
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from . import clean, fetch, loader, policy, rule_d
from .schema import ScholarlyManifest, ScholarlyPaper

HERE = Path(__file__).resolve().parent
STUDY_ID = "scholarly-ai-mirror-2026-11-16"
COLLECTION = "humanities"
SEED = 7
N_TARGETS = 20
TOOLS = ("claude", "chatgpt", "gemini")
PROMPT = (
    'Write an original scholarly journal article of about 1,600 words titled "{title}", '
    "suitable for publication in {venue}. Write continuous academic prose in paragraphs. Do "
    "not use headings, bullet points, numbered lists, tables, footnotes or a reference list."
)
CONTINUE_PROMPT = (
    "Please continue the article from where it stopped, in the same style, for about 600 "
    "more words."
)
CONTINUE_BELOW = 1300
MIN_PARA_WORDS = 12
ROUTES = ("app", "subagent")
AI_DIR = HERE / "ai_mirror"
RESULTS_DIR = HERE
PUBLISHED_LOCKED = "rule_d_humanities_locked_test_2026-11-12.json"
REPRODUCED_KEYS = ("honest_flag_rate", "catch_rate", "auc", "n_authors", "n_honest", "n_probe")
_REPO = HERE.parent.parent


@dataclass(frozen=True)
class Target:
    rank: int
    author_id: str
    paper_id: str
    title: str
    venue: str
    tool: str


def new_paper_for(papers: List[ScholarlyPaper], seed: int, n_past: int = 4,
                  past_words: int = 1200, new_words: int = 1200) -> str:
    """The id ``loader.load_trials`` would put first in ``honest_ids``, from metadata only."""
    order = sorted(papers, key=lambda p: loader._rank(seed, p.source_paper_id))
    past = [p for p in order if p.word_count >= past_words][:n_past]
    rest = [p for p in order if p not in past and p.word_count >= new_words]
    if not rest:
        raise ValueError("author has no new paper of the required length")
    return rest[0].source_paper_id


def select_targets(manifest: ScholarlyManifest, candidates: dict) -> List[Target]:
    by_author = manifest.authors()
    ids = sorted(manifest.authors_in("locked_test"),
                 key=lambda a: loader._rank(SEED, "ai-mirror:" + a))[:N_TARGETS]
    works = {w["work_id"]: w for a in candidates["authors"] for w in a["papers"]}
    out: List[Target] = []
    for rank, aid in enumerate(ids):
        pid = new_paper_for(by_author[aid], SEED)
        if pid not in works:
            raise KeyError(f"paper {pid} (author {aid}) is not in the candidate list")
        w = works[pid]
        out.append(Target(rank=rank, author_id=aid, paper_id=pid, title=w["title"],
                          venue=w["host"], tool=TOOLS[rank % len(TOOLS)]))
    return out


def render_sheet(targets: List[Target]) -> str:
    lines = [
        f"# Prompt sheet: {STUDY_ID}", "",
        "Paste each prompt into a fresh chat in the named tool, exactly as written.",
        f"Save the complete reply as plain text to the path shown under it. If the reply is "
        f"under {CONTINUE_BELOW:,} words, send this follow-up once, in the same chat, and save "
        "both replies together in order:", "",
        "```", CONTINUE_PROMPT, "```", "",
    ]
    for t in targets:
        lines += [
            f"## {t.rank + 1}. {t.tool}", "",
            "```", PROMPT.format(title=t.title, venue=t.venue), "```", "",
            f"Save to: `validation/scholarly/ai_mirror/raw/{t.author_id}.txt`", "",
        ]
    return "\n".join(lines)


def load_targets(path: Optional[Path] = None) -> List[Target]:
    path = path or AI_DIR / "targets_humanities.json"
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return [Target(**t) for t in data["targets"]]


_REF_HEADS = frozenset({
    "references", "reference list", "bibliography", "select bibliography", "works cited",
    "literature cited", "sources", "notes", "endnotes", "further reading"})
_SECTION_PREFIX = re.compile(r"^(?:\d+|[ivxlc]+)[.)]\s+", re.I)
_BULLET = re.compile(r"^\s*(?:[-*+\u2022]|\d+[.)])\s+")
_REF_YEAR = re.compile(r"\((?:1[5-9]|20)\d\d[a-z]?\)|\b(?:1[5-9]|20)\d\d\.")
_REF_MARKERS = ("pp.", "Press", "Journal", "doi", "Vol.", "ed.", "eds.", "University", "Review")


def _is_ref_heading(line: str) -> bool:
    s = line.strip().lstrip("#").strip(" *_")
    s = _SECTION_PREFIX.sub("", s)
    return s.rstrip(":").strip(" *_").lower() in _REF_HEADS


def _alnum(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def _unemphasise(line: str) -> str:
    line = line.replace("**", "").replace("__", "").replace("*", "")
    return re.sub(r"(?<!\w)_|_(?!\w)", "", line)


def _reference_like(para: str) -> bool:
    return bool(_REF_YEAR.search(para)) and any(m in para for m in _REF_MARKERS)


def _cut_trailing_references(paras: List[str]) -> tuple:
    """Drop the trailing run of reference-like paragraphs; return (kept, number dropped)."""
    i = len(paras)
    while i > 0 and _reference_like(paras[i - 1]):
        i -= 1
    return paras[:i], len(paras) - i


def _normalise(raw: str, title: str) -> tuple:
    lines = raw.replace("\r\n", "\n").split("\n")
    for i, ln in enumerate(lines):
        if _is_ref_heading(ln):
            lines = lines[:i]
            break
    want = _alnum(title)
    kept: List[str] = []
    for ln in lines:
        if ln.lstrip().startswith("#"):
            continue
        ln = _unemphasise(_BULLET.sub("", ln))
        if ln.strip() and _alnum(ln) == want:
            continue
        kept.append(ln)
    raws = re.split(r"\n\s*\n", "\n".join(kept))
    pairs = [(r, clean.strip_inline(r)) for r in raws]
    pairs = [(r, c) for r, c in pairs if len(c.split()) >= MIN_PARA_WORDS]
    _, cut = _cut_trailing_references([r for r, _ in pairs])
    if cut:
        pairs = pairs[:len(pairs) - cut]
    return "\n\n".join(c for _, c in pairs), cut


def normalise_ai_text(raw: str, title: str) -> str:
    """Make an AI reply look like a cleaned corpus paper: plain prose paragraphs only."""
    return _normalise(raw, title)[0]


def load_ai_manifest(path: Optional[Path] = None) -> dict:
    path = Path(path) if path else AI_DIR / f"manifest_{COLLECTION}.json"
    if not path.exists():
        return {"study_id": STUDY_ID, "collection": COLLECTION, "papers": {}}
    return json.loads(path.read_text(encoding="utf-8"))


def intake(author_id: str, model: str, date: str, route: str, continued: bool) -> dict:
    """Clean ``raw/<author>.txt`` into ``texts/<author>.txt`` and upsert its manifest entry."""
    if route not in ROUTES:
        raise ValueError(f"route must be one of {ROUTES}, got {route!r}")
    target = next((t for t in load_targets() if t.author_id == author_id), None)
    if target is None:
        raise ValueError(f"author {author_id!r} is not in the targets file")
    raw_path = AI_DIR / "raw" / f"{author_id}.txt"
    if not raw_path.exists():
        raise ValueError(f"missing raw reply: {raw_path}")
    raw_bytes = raw_path.read_bytes()
    text, cut = _normalise(raw_bytes.decode("utf-8"), target.title)
    if not text.strip():
        raise ValueError(f"cleaned text for {author_id!r} is empty")
    out = AI_DIR / "texts" / f"{author_id}.txt"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    entry = {
        "author_id": author_id, "paper_id": target.paper_id, "tool": target.tool,
        "model": model, "date": date, "route": route, "continued": bool(continued),
        "words": len(text.split()), "cut_reference_paragraphs": cut,
        "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "raw_sha256": hashlib.sha256(raw_bytes).hexdigest(),
    }
    manifest = load_ai_manifest()
    manifest["papers"][author_id] = entry
    manifest["papers"] = dict(sorted(manifest["papers"].items()))
    (AI_DIR / f"manifest_{COLLECTION}.json").write_text(
        json.dumps(manifest, indent=1) + "\n", encoding="utf-8")
    if entry["words"] < CONTINUE_BELOW and not continued:
        print(f"{author_id}: only {entry['words']} words; send the continue prompt once "
              f"in the same chat, save both replies, and re-run with --continued:\n  {CONTINUE_PROMPT}")
    return entry


def thresholds_match(recomputed: dict, committed: dict) -> List[str]:
    """Config names whose threshold differs at 6 decimals or is missing from ``recomputed``."""
    bad = []
    for name, want in committed.items():
        got = recomputed.get(name)
        if got is None or round(float(got), 6) != round(float(want), 6):
            bad.append(name)
    return sorted(bad)


def check_environment(n_boot: int = 10) -> dict:
    """Prove the rebuilt corpus and vectorizers reproduce the committed thresholds."""
    verify = fetch.verify(COLLECTION, fetch.DEFAULT_CACHE)
    _vecs, sha = rule_d.fit_or_load_vectorizers(COLLECTION)
    recomputed = rule_d.calibrate(COLLECTION, n_boot)["thresholds"]
    committed_doc = json.loads((rule_d.HERE / f"rule_d_thresholds_{COLLECTION}.json")
                               .read_text(encoding="utf-8"))
    committed = committed_doc["thresholds"]
    mismatches = thresholds_match(recomputed, committed)
    result = {
        "date": time.strftime("%Y-%m-%d"),
        "verify": verify,
        "vectorizers_sha256": sha,
        "sha_matches_committed": sha == committed_doc.get("vectorizers_sha256"),
        "recomputed": recomputed,
        "committed": committed,
        "mismatches": mismatches,
        "passed": mismatches == [],
    }
    AI_DIR.mkdir(parents=True, exist_ok=True)
    (AI_DIR / f"environment_{COLLECTION}.json").write_text(
        json.dumps(result, indent=1) + "\n", encoding="utf-8")
    return result


# ------------------------------------------------------------ scoring summary --
def wilson(k: int, n: int, z: float = 1.96) -> tuple:
    """Wilson score interval for k successes out of n; (0.0, 1.0) when n is 0."""
    if n == 0:
        return (0.0, 1.0)
    p = k / n
    den = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / den
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return (max(0.0, centre - half), min(1.0, centre + half))


def decide(k: int, n: int) -> str:
    """The pre-registered outcome: is a 95% catch rate ruled out by the Wilson upper end?"""
    if n == 0:
        return "no_papers"
    return "below_95" if wilson(k, n)[1] < 0.95 else "95_not_ruled_out"


def ai_cut(text: str, words: int, author_id: str) -> str:
    """The AI paper cut to ``words`` at a paragraph start seeded by the author id."""
    return loader.cut_words(text, words, random.Random(loader._rank(SEED, "ai:" + author_id)))


def ai_extra_docs(texts: dict) -> tuple:
    """``extra_docs`` for the seed-7 trial of every config, and per config the authors whose
    AI text is shorter than that config's new-paper length (left out, never padded)."""
    extra, left_out = {}, {}
    for name, _past_w, new_w in rule_d.CONFIGS:
        per_author, short = {}, []
        for aid, text in texts.items():
            if len(text.split()) < new_w:
                short.append(aid)
                continue
            per_author[aid] = [(ai_cut(text, new_w, aid), 1, None, "ai")]
        extra[(name, SEED)] = per_author
        left_out[name] = short
    return extra, left_out


def summarise_ai(rows: List[dict], thresholds: dict, targets: List[Target], left_out: dict) -> dict:
    """Caught (D strictly above the committed threshold) out of n per config, seed 7 only,
    with the same authors' own new papers flagged in the same trials beside it."""
    targets = sorted(targets, key=lambda t: t.rank)
    ids = {t.author_id for t in targets}
    out, honest = {}, {}
    for name, _, _ in rule_d.CONFIGS:
        thr = thresholds[name]
        mine = [r for r in rows if r["config"] == name and r["seed"] == SEED]
        papers, missing = [], []
        per_tool = {tool: [0, 0] for tool in TOOLS}
        for t in targets:
            ai_rows = [r for r in mine if r["author"] == t.author_id and r["kind"] == "ai"]
            if not ai_rows:
                missing.append(t.author_id)
            for r in ai_rows:
                caught = float(r["D"]) > thr
                papers.append({"author": t.author_id, "tool": t.tool, "D": float(r["D"]), "caught": caught})
                tally = per_tool.setdefault(t.tool, [0, 0])
                tally[0] += int(caught)
                tally[1] += 1
        k, n = sum(p["caught"] for p in papers), len(papers)
        out[name] = {"caught": k, "n": n, "rate": (k / n) if n else None,
                     "wilson95": list(wilson(k, n)), "outcome": decide(k, n), "per_tool": per_tool,
                     "missing_authors": missing, "left_out_short": list(left_out.get(name, [])),
                     "papers": papers}
        h = [r for r in mine if not r["label"] and r["author"] in ids]
        honest[name] = {"flagged": sum(float(r["D"]) > thr for r in h), "n": len(h)}
    out["honest_same_authors"] = honest
    return out


def reproduction_diff(cells: dict, published: dict) -> List[str]:
    """``config/kind/key`` for every reproduced figure that differs from the published cell."""
    diffs = []
    for name in dict.fromkeys(list(published) + list(cells)):
        pub_c, new_c = published.get(name, {}), cells.get(name, {})
        for kind in dict.fromkeys(list(pub_c) + list(new_c)):
            pub_k, new_k = pub_c.get(kind, {}), new_c.get(kind, {})
            for key in REPRODUCED_KEYS:
                if (key in pub_k or key in new_k) and pub_k.get(key) != new_k.get(key):
                    diffs.append(f"{name}/{kind}/{key}")
    return diffs


# --------------------------------------------------------------- the opening --
def _uncommitted(path: Path) -> bool:
    """True when ``git status`` shows any change, tracked or untracked, under ``path``."""
    proc = subprocess.run(["git", "status", "--porcelain", "--", str(path)], cwd=_REPO,
                          capture_output=True, text=True)
    if proc.returncode != 0:
        raise SystemExit(f"git status failed for {path}: {proc.stderr.strip()}")
    return bool(proc.stdout.strip())


def _opened_before() -> bool:
    """True when the opening log (``loader.LOCKED_LOG``, read now) already has a line for this
    study and collection, even if no result file was written (a crash after the opening)."""
    log = Path(loader.LOCKED_LOG)
    if not log.exists():
        return False
    for line in log.read_text(encoding="utf-8").splitlines():
        parts = line.split("\t")
        if not line.startswith("#") and len(parts) >= 3 \
                and parts[1].strip() == COLLECTION and parts[2].strip() == STUDY_ID:
            return True
    return False


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _check_before_opening(study: str) -> tuple:
    """Every guard of the opening. Raises SystemExit naming what failed; touches nothing locked."""
    if study != STUDY_ID:
        raise SystemExit(f"locked_test may only be opened here for the pre-registered study {STUDY_ID!r}, "
                         f"not {study!r}")
    existing = sorted(RESULTS_DIR.glob(f"ai_mirror_{COLLECTION}_locked_test_*.json"))
    if existing:
        raise SystemExit(f"{existing[0].name} exists: locked_test has already been opened for this study")
    if _opened_before():
        raise SystemExit(f"{Path(loader.LOCKED_LOG).name} already records an opening of {COLLECTION} "
                         f"locked_test for study {STUDY_ID!r}; a re-run (for example after a crash) "
                         "needs the owner's approval and must not be done from here")
    env_path = AI_DIR / f"environment_{COLLECTION}.json"
    if not env_path.exists():
        raise SystemExit(f"{env_path.name} is missing: run check-env and pass the environment gate first")
    env = json.loads(env_path.read_text(encoding="utf-8"))
    if env.get("passed") is not True:
        raise SystemExit(f"{env_path.name} does not record passed: true; the environment gate failed, "
                         "so locked_test stays closed")
    vecs, vec_sha = rule_d.fit_or_load_vectorizers(COLLECTION)
    if vec_sha != env.get("vectorizers_sha256"):
        raise SystemExit(f"vectorizers sha256 {vec_sha} differs from the one that passed the gate in "
                         f"{env_path.name} ({env.get('vectorizers_sha256')}); refusing to open")
    targets = load_targets()
    papers = load_ai_manifest()["papers"]
    texts = {}
    for t in sorted(targets, key=lambda t: t.rank):
        path = AI_DIR / "texts" / f"{t.author_id}.txt"
        if t.author_id not in papers:
            raise SystemExit(f"target {t.author_id} has no entry in the AI manifest")
        if not path.exists():
            raise SystemExit(f"AI text file {path.name} for target {t.author_id} is missing")
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != papers[t.author_id]["sha256"]:
            raise SystemExit(f"AI text for {t.author_id} does not match the sha256 in its manifest entry")
        texts[t.author_id] = data.decode("utf-8")
    if _uncommitted(AI_DIR):
        raise SystemExit(f"uncommitted changes under {AI_DIR}: commit the AI papers, manifest and "
                         "environment file before opening (git status -- that directory)")
    return targets, texts, vecs, vec_sha


def open_locked(study: str, n_boot: int = 1000) -> dict:
    """The single opening of locked_test for this study. Every guard runs, and every input is
    read, before ``loader.load_trial_grid`` (which logs the opening) is called."""
    targets, texts, vecs, vec_sha = _check_before_opening(study)
    targets_sha = _sha256_file(AI_DIR / f"targets_{COLLECTION}.json")
    manifest_sha = _sha256_file(AI_DIR / f"manifest_{COLLECTION}.json")
    thresholds = json.loads((rule_d.HERE / f"rule_d_thresholds_{COLLECTION}.json")
                            .read_text(encoding="utf-8"))["thresholds"]
    published = json.loads((rule_d.HERE / PUBLISHED_LOCKED).read_text(encoding="utf-8"))["cells"]
    extra, left_out = ai_extra_docs(texts)
    grid = [(n, pw, nw, s) for n, pw, nw in rule_d.CONFIGS for s in rule_d.SEEDS]
    sets = loader.load_trial_grid(COLLECTION, "locked_test", grid, allow_locked_for=study,
                                  n_past=4, n_new=2, n_probes=5)
    rows = rule_d.build_scores(COLLECTION, sets, vecs, extra_docs=extra)
    cells = {}
    for name, _, _ in rule_d.CONFIGS:
        R = [r for r in rows if r["config"] == name and r["kind"] != "ai"]
        cells[name] = {kind: rule_d.cell_report(R, thresholds[name], kind, n_boot) for kind in rule_d.KINDS}
    diffs = reproduction_diff(cells, published)
    date = time.strftime("%Y-%m-%d")
    out = {"study_id": study, "collection": COLLECTION, "partition": "locked_test", "date": date,
           "vectorizers_sha256": vec_sha, "thresholds": thresholds, "n_boot": n_boot,
           "targets_sha256": targets_sha, "ai_manifest_sha256": manifest_sha,
           "reproduction": {"equal": diffs == [], "diffs": diffs, "published": PUBLISHED_LOCKED,
                            "cells": cells},
           "ai": summarise_ai(rows, thresholds, targets, left_out),
           "skipped": {f"{n}/seed{s}/{a}": why for (n, s), ts in sets.items() for a, why in ts.skipped.items()}}
    path = RESULTS_DIR / f"ai_mirror_{COLLECTION}_locked_test_{date}.json"
    path.write_text(json.dumps(out, indent=1) + "\n", encoding="utf-8")
    for name, _, _ in rule_d.CONFIGS:
        c, h = out["ai"][name], out["ai"]["honest_same_authors"][name]
        print(f"{name}: AI caught {c['caught']}/{c['n']} ({c['outcome']}); "
              f"same authors' own papers flagged {h['flagged']}/{h['n']}", flush=True)
    print("reproduction equal:", out["reproduction"]["equal"], "| wrote", path)
    return out


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="ai_mirror")
    sub = ap.add_subparsers(dest="step", required=True)
    sub.add_parser("select")
    cp = sub.add_parser("check-env")
    cp.add_argument("--n-boot", type=int, default=10)
    lp = sub.add_parser("locked")
    lp.add_argument("--study", required=True)
    lp.add_argument("--n-boot", type=int, default=1000)
    ip = sub.add_parser("intake")
    ip.add_argument("--author", required=True)
    ip.add_argument("--model", required=True)
    ip.add_argument("--date", required=True)
    ip.add_argument("--route", required=True, choices=list(ROUTES))
    ip.add_argument("--continued", action="store_true")
    args = ap.parse_args(argv)
    if args.step == "check-env":
        result = check_environment(args.n_boot)
        print(json.dumps(result, indent=1))
        return 0 if result["passed"] else 1
    if args.step == "intake":
        intake(args.author, args.model, args.date, args.route, args.continued)
        return 0
    if args.step == "locked":
        open_locked(args.study, args.n_boot)
        return 0
    manifest = loader.load_manifest(COLLECTION)
    candidates = json.loads((loader.HERE / "candidates" / f"{COLLECTION}.json")
                            .read_text(encoding="utf-8"))
    targets = select_targets(manifest, candidates)
    AI_DIR.mkdir(parents=True, exist_ok=True)
    (AI_DIR / f"targets_{COLLECTION}.json").write_text(json.dumps(
        {"study_id": STUDY_ID, "collection": COLLECTION, "seed": SEED,
         "targets": [dataclasses.asdict(t) for t in targets]}, indent=2) + "\n", encoding="utf-8")
    (AI_DIR / f"prompts_{COLLECTION}.md").write_text(render_sheet(targets), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
