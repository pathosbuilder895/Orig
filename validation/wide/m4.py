"""
m4.py — M4 (Multi-domain, Multi-generator, Multilingual, Multi-source) adapter.

M4 ships per-(source, generator) JSONL files. Each line is shaped like:

    {"text": "...", "label": 0, "source": "arxiv", "model": "chatGPT"}
    (label: 0 = human, 1 = machine — the spec varies a bit across files)

We re-shape into the same per-domain authorship corpus RAID uses:

  - **Author = source domain** (``m4:arxiv``, ``m4:peerread``, etc.)
  - First 3 human texts per domain → baseline
  - Remaining human → AUTHENTIC (scored)
  - Machine-generated → AI_GENERATED (scored), tagged with ai_provider
    derived from the file name (the generator is encoded in the filename
    even when it's missing from the JSON payload).

English-only first pass — the file list in
``scripts/fetch_benchmark_data.py:M4_FILES`` only includes the English
generators.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Dict, List, Optional

from validation.manifest_schema import AIProvider, AuthorshipLabel
from validation.wide._adapter import WideEntry, materialize


M4_CACHE_ROOT = Path(__file__).resolve().parent.parent.parent / ".benchmark_cache" / "m4"


_PROVIDER_BY_FILENAME = [
    ("chatgpt",   AIProvider.CHATGPT),
    ("davinci",   AIProvider.CHATGPT),
    ("gpt",       AIProvider.CHATGPT),
    ("claude",    AIProvider.CLAUDE),
    ("cohere",    AIProvider.NONE),    # cohere not in our enum; bucket "none"
    ("dolly",     AIProvider.NONE),
    ("bloomz",    AIProvider.NONE),
    ("flan-t5",   AIProvider.NONE),
    ("gemini",    AIProvider.GEMINI),
    ("bard",      AIProvider.GEMINI),
]


def _provider_from_filename(name: str) -> AIProvider:
    n = name.lower()
    for key, prov in _PROVIDER_BY_FILENAME:
        if key in n:
            return prov
    return AIProvider.NONE


_SOURCE_FROM_FILENAME = re.compile(r"^([a-z]+)[_\.]")


def _source_from_filename(name: str) -> str:
    m = _SOURCE_FROM_FILENAME.match(name.lower())
    return m.group(1) if m else "unknown"


def build_corpus(
    *,
    corpus_dir: Path,
    manifest_path: Path,
    sample_size: int = 800,
    min_text_chars: int = 600,
    cache_root: Optional[Path] = None,
) -> dict:
    """
    Build a corpus + manifest from cached M4 JSONL files.

    Returns the materialize() stats dict.
    """
    root = Path(cache_root) if cache_root else M4_CACHE_ROOT
    if not root.exists():
        raise FileNotFoundError(
            f"M4 not cached at {root}. Run: python scripts/fetch_benchmark_data.py --m4"
        )

    files = sorted(root.glob("*.jsonl"))
    if not files:
        raise FileNotFoundError(
            f"No JSONL files in {root}. Re-run the fetcher with --m4 (or copy "
            f"files in manually — see scripts/fetch_benchmark_data.py)."
        )

    per_domain_human_cap = max(8, sample_size // 16)
    per_domain_ai_cap    = max(8, sample_size // 16)
    human_counts: Dict[str, int] = {}
    ai_counts: Dict[str, int] = {}

    entries: List[WideEntry] = []
    rows_read = 0

    for path in files:
        if rows_read >= sample_size * 4:
            break
        provider = _provider_from_filename(path.name)
        source = _source_from_filename(path.name)
        with open(path, encoding="utf-8") as f:
            for line in f:
                if rows_read >= sample_size * 4:
                    break
                rows_read += 1
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue

                # Some M4 files give "human_text"/"machine_text" pairs per row;
                # others give a single "text" + "label". Cover both.
                pairs: List[tuple] = []
                if "human_text" in row and "machine_text" in row:
                    pairs.append(("human", str(row["human_text"])))
                    pairs.append(("machine", str(row["machine_text"])))
                elif "text" in row:
                    label_val = row.get("label")
                    role = "human" if label_val in (0, "human") else "machine"
                    pairs.append((role, str(row["text"])))
                else:
                    continue

                for role, text in pairs:
                    text = text.strip()
                    if len(text) < min_text_chars:
                        continue
                    author_id = f"m4:{source}"
                    if role == "human":
                        if human_counts.get(source, 0) >= per_domain_human_cap:
                            continue
                        human_counts[source] = human_counts.get(source, 0) + 1
                        idx = human_counts[source]
                        entries.append(WideEntry(
                            author_id=author_id,
                            label=AuthorshipLabel.AUTHENTIC,
                            text=text,
                            prompt=source,
                            is_baseline=(idx <= 3),
                            ai_provider=AIProvider.NONE,
                            native_english=True,
                            source_id=str(row.get("id") or ""),
                        ))
                    else:
                        if ai_counts.get(source, 0) >= per_domain_ai_cap:
                            continue
                        ai_counts[source] = ai_counts.get(source, 0) + 1
                        entries.append(WideEntry(
                            author_id=author_id,
                            label=AuthorshipLabel.AI_GENERATED,
                            text=text,
                            prompt=source,
                            is_baseline=False,
                            ai_provider=provider,
                            native_english=None,
                            source_id=str(row.get("id") or ""),
                            notes=f"file={path.name}",
                        ))

    return materialize(
        entries,
        corpus_dir=corpus_dir,
        manifest_path=manifest_path,
        description="M4 sample — per-domain human-vs-LLM detection (English)",
    )
