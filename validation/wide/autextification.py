"""
autextification.py — AuTexTification (IberLEF 2023) adapter.

English subtask 1: human vs. machine-generated text detection across 3
domains (tweets, legal, wiki/how-to). Built specifically to run a real,
same-dataset head-to-head against the StyloAI paper
(https://arxiv.org/html/2405.10129v1), which reports 81% accuracy /
0.88 AUC on this exact corpus with a Random Forest classifier.

  - **Author = domain**. ``autext:tweets``, ``autext:legal``, ``autext:wiki``
    — same per-domain-authorship framing as the RAID adapter (raid.py):
    tests whether Original separates human-domain prose from LLM-domain
    prose even when the topic/register is held constant.

  - **First N human texts per domain → baseline** (``is_baseline=True``).

  - **Subsequent human texts → ``label=AUTHENTIC``**, scored.

  - **Generated rows → ``label=AI_GENERATED``**, scored. The ``model``
    column is an anonymised letter (A-F) per the IberLEF shared-task
    rules — not a named commercial provider — so ``ai_provider`` stays
    NONE and the letter is preserved in ``notes`` for traceability.

DELIBERATELY NOT length-filtered to "Original-friendly" texts: tweets
median ~100 chars, legal/wiki median ~440 chars — all well under
Original's ~500-word stability floor (see validation/stability/). This
is intentional. StyloAI's own reported numbers were computed on these
exact same short texts; filtering them out here would bias the
comparison in Original's favor. min_text_chars only drops truly empty
rows.

The fetcher caches ``.benchmark_cache/autextification/{train,test}.tsv``.
Rows arrive pre-shuffled (unlike RAID's domain-sorted train.csv) — no
extra shuffling needed.
"""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Dict, List, Optional

from validation.manifest_schema import AIProvider, AuthorshipLabel
from validation.wide._adapter import WideEntry, materialize


AUTEXT_DIR = Path(__file__).resolve().parent.parent.parent / ".benchmark_cache" / "autextification"


def build_corpus(
    *,
    corpus_dir: Path,
    manifest_path: Path,
    split: str = "train",
    sample_size: int = 1200,
    min_text_chars: int = 10,
    tsv_path: Optional[Path] = None,
) -> dict:
    """
    Build a corpus + manifest from the cached AuTexTification TSV.

    Args:
        split: "train" or "test" — which cached TSV to read.
        sample_size: cap on total rows considered (split across human +
                     generated rows after the per-domain cap kicks in).
        min_text_chars: drop any text below this length. Kept low (10)
                        deliberately — see module docstring.
        tsv_path: override the default cache location.

    Returns the materialize() stats dict.
    """
    src = Path(tsv_path) if tsv_path else (AUTEXT_DIR / f"{split}.tsv")
    if not src.exists():
        raise FileNotFoundError(
            f"AuTexTification {split}.tsv not cached at {src}. Run: "
            f"python scripts/fetch_benchmark_data.py --autextification"
        )

    per_domain_human_cap = max(8, sample_size // 8)   # 3 domains → generous per-domain budget
    per_domain_ai_cap    = max(8, sample_size // 8)
    human_counts: Dict[str, int] = {}
    ai_counts: Dict[str, int] = {}

    entries: List[WideEntry] = []
    rows_read = 0
    with open(src, encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f, delimiter="\t")
        for row in reader:
            if rows_read >= sample_size * 2:
                break
            rows_read += 1

            domain = (row.get("domain") or "unknown").lower().strip()
            model = (row.get("model") or "").strip()
            label = (row.get("label") or "").lower().strip()
            text = (row.get("text") or "").strip()
            if len(text) < min_text_chars:
                continue

            is_human = (label == "human")
            if is_human:
                if human_counts.get(domain, 0) >= per_domain_human_cap:
                    continue
                human_counts[domain] = human_counts.get(domain, 0) + 1
                idx = human_counts[domain]
                entries.append(WideEntry(
                    author_id=f"autext:{domain}",
                    label=AuthorshipLabel.AUTHENTIC,
                    text=text,
                    prompt=row.get("prompt") or domain,
                    is_baseline=(idx <= 3),
                    ai_provider=AIProvider.NONE,
                    native_english=True,
                    source_id=row.get("id") or "",
                ))
            else:
                if ai_counts.get(domain, 0) >= per_domain_ai_cap:
                    continue
                ai_counts[domain] = ai_counts.get(domain, 0) + 1
                entries.append(WideEntry(
                    author_id=f"autext:{domain}",
                    label=AuthorshipLabel.AI_GENERATED,
                    text=text,
                    prompt=row.get("prompt") or domain,
                    is_baseline=False,
                    ai_provider=AIProvider.NONE,   # anonymised model letter, not a named provider
                    native_english=None,
                    source_id=row.get("id") or "",
                    notes=f"model={model} (anonymised, IberLEF 2023 shared task)",
                ))

    return materialize(
        entries,
        corpus_dir=corpus_dir,
        manifest_path=manifest_path,
        description=f"AuTexTification {split} — per-domain human-vs-LLM detection "
                    f"(StyloAI comparison corpus)",
    )
