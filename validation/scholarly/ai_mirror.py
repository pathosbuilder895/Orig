"""AI-mirror study of rule D: pick 20 locked_test authors, write the prompt sheet.

Each target is one held-out paper (the same one the seed-7 trial would use as
its first new paper). An AI chat tool is asked to write a paper with that title
for that journal; later steps score the reply against the author's baseline.
Only published titles and journal names are used; no student writing is involved.

    python -m validation.scholarly.ai_mirror select
    python -m validation.scholarly.ai_mirror intake --author A... --model "..." --date YYYY-MM-DD --route app
"""
from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import re
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


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="ai_mirror")
    sub = ap.add_subparsers(dest="step", required=True)
    sub.add_parser("select")
    cp = sub.add_parser("check-env")
    cp.add_argument("--n-boot", type=int, default=10)
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
