"""AI-mirror study of rule D: pick 20 locked_test authors, write the prompt sheet.

Each target is one held-out paper (the same one the seed-7 trial would use as
its first new paper). An AI chat tool is asked to write a paper with that title
for that journal; later steps score the reply against the author's baseline.
Only published titles and journal names are used; no student writing is involved.

    python -m validation.scholarly.ai_mirror select
"""
from __future__ import annotations

import argparse
import dataclasses
import json
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from . import loader, policy
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


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="ai_mirror")
    ap.add_argument("step", choices=["select"])
    ap.parse_args(argv)
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
