"""
raid.py — RAID (Robust AI Detection) adapter.

RAID covers 8 domains × 11 generators × 4 decoding strategies. Each row
either has ``model = "human"`` (a reference text) or one of the LLM
generators. We re-shape this into the corpus + manifest Original wants:

  - **Author = domain**. All Wikipedia-domain human references become
    ``raid:wiki``; all news human references become ``raid:news``, etc.
    Yes — this is per-domain authorship, not per-individual; it tests
    whether Original can tell human-domain prose from LLM-domain prose
    even when the topic is the same. That is exactly what an academic
    integrity tool needs to do.

  - **First 3 human texts per domain → baseline** (``is_baseline=True``).

  - **Subsequent human texts → ``label=AUTHENTIC``**, scored.

  - **AI-generated rows → ``label=AI_GENERATED``**, scored, tagged
    with ``ai_provider`` derived from the ``model`` column.

The fetcher caches ``.benchmark_cache/raid/raid_sample.csv``. We read it
with the stdlib ``csv`` module — no pandas dependency.
"""

from __future__ import annotations

import csv
import io
from pathlib import Path
from typing import Dict, List, Optional

from validation.manifest_schema import AIProvider, AuthorshipLabel
from validation.wide._adapter import WideEntry, materialize


RAID_CACHE = Path(__file__).resolve().parent.parent.parent / ".benchmark_cache" / "raid" / "raid_sample.csv"


# RAID model strings → ai_provider buckets used by Original
_PROVIDER_MAP = {
    "human":          AIProvider.NONE,
    "chatgpt":        AIProvider.CHATGPT,
    "gpt2":           AIProvider.CHATGPT,
    "gpt3":           AIProvider.CHATGPT,
    "gpt4":           AIProvider.CHATGPT,
    "claude":         AIProvider.CLAUDE,
    "gemini":         AIProvider.GEMINI,
    "bard":           AIProvider.GEMINI,
}


def _bucket_provider(model: str) -> AIProvider:
    m = (model or "").lower()
    for key, prov in _PROVIDER_MAP.items():
        if key in m:
            return prov
    # Unknown / open-source generator — leave as NONE so the bias slicer
    # still groups it cleanly under ai_provider="none". The CorpusEntry
    # label = AI_GENERATED is what carries the meaning.
    return AIProvider.NONE


def build_corpus(
    *,
    corpus_dir: Path,
    manifest_path: Path,
    sample_size: int = 800,
    min_text_chars: int = 600,
    csv_path: Optional[Path] = None,
) -> dict:
    """
    Build a corpus + manifest from the cached RAID sample CSV.

    Args:
        sample_size: cap on total rows considered (split across human +
                     AI rows after the per-domain cap kicks in).
        min_text_chars: drop any text below this length.
        csv_path: override the default cache location.

    Returns the materialize() stats dict.
    """
    src = Path(csv_path) if csv_path else RAID_CACHE
    if not src.exists():
        raise FileNotFoundError(
            f"RAID sample not cached at {src}. Run: "
            f"python scripts/fetch_benchmark_data.py --raid"
        )

    # Track per-(domain, role) caps so we don't drown one domain in AI
    # rows or starve another of human rows.
    per_domain_human_cap = max(8, sample_size // 16)
    per_domain_ai_cap    = max(8, sample_size // 16)
    human_counts: Dict[str, int] = {}
    ai_counts: Dict[str, int] = {}

    entries: List[WideEntry] = []
    rows_read = 0
    with open(src, encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            if rows_read >= sample_size * 2:
                break
            rows_read += 1
            domain = (row.get("domain") or "unknown").lower().strip()
            model = (row.get("model") or "").lower().strip()
            text = (row.get("generation") or row.get("text") or "").strip()
            if len(text) < min_text_chars:
                continue

            is_human = (model == "human")
            if is_human:
                if human_counts.get(domain, 0) >= per_domain_human_cap:
                    continue
                human_counts[domain] = human_counts.get(domain, 0) + 1
                idx = human_counts[domain]
                entries.append(WideEntry(
                    author_id=f"raid:{domain}",
                    label=AuthorshipLabel.AUTHENTIC,
                    text=text,
                    prompt=row.get("title") or domain,
                    is_baseline=(idx <= 3),
                    ai_provider=AIProvider.NONE,
                    native_english=True,
                    source_id=row.get("id") or row.get("source_id") or "",
                ))
            else:
                if ai_counts.get(domain, 0) >= per_domain_ai_cap:
                    continue
                ai_counts[domain] = ai_counts.get(domain, 0) + 1
                entries.append(WideEntry(
                    author_id=f"raid:{domain}",
                    label=AuthorshipLabel.AI_GENERATED,
                    text=text,
                    prompt=row.get("title") or domain,
                    is_baseline=False,
                    ai_provider=_bucket_provider(model),
                    native_english=None,
                    source_id=row.get("id") or row.get("source_id") or "",
                    notes=f"model={model}, attack={row.get('attack')}",
                ))

    return materialize(
        entries,
        corpus_dir=corpus_dir,
        manifest_path=manifest_path,
        description="RAID sample — per-domain human-vs-LLM detection",
    )
