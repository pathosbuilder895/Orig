"""
_adapter.py — shared helpers for the wide-benchmark dataset adapters.

Every adapter (RAID, PAN AV, M4) ultimately has to produce two things on
disk that ``validation.calibration.run_calibration`` can consume:

  1. A directory of essay ``.txt`` files
  2. A ``manifest.json`` matching ``validation.manifest_schema.ValidationManifest``

The shape that ``run_calibration`` enforces (see ``CorpusEntry``):

- Each author needs ≥ 3 baseline samples (``is_baseline=True``)
- Each author should have ≥ 1 non-baseline sample to score
- ``label`` is one of AUTHENTIC / AI_GENERATED / GHOSTWRITTEN / MIXED /
  PARAPHRASED — we use AUTHENTIC + AI_GENERATED + GHOSTWRITTEN here
- ``word_count`` must be set (the bias slicer buckets on it)

This module exposes:

  * ``WideEntry``     — a tiny dataclass adapters fill in
  * ``materialize()`` — writes ``.txt`` files + ``manifest.json`` from a
                       list of ``WideEntry`` records

Everything else (HTTP, parsing, dataset-specific quirks) lives in the
per-dataset adapter modules.
"""

from __future__ import annotations

import datetime
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional

from validation.manifest_schema import (
    AIProvider,
    AuthorshipLabel,
    CorpusEntry,
    ValidationManifest,
)


# ── A dataset-agnostic entry the adapters fill in ────────────────────────────

@dataclass
class WideEntry:
    """One essay's worth of data, the shape the materialize() step wants."""

    author_id: str                  # canonical author identifier (e.g. "raid_wiki")
    label: AuthorshipLabel          # AUTHENTIC | AI_GENERATED | GHOSTWRITTEN | …
    text: str                       # the essay text itself
    prompt: str                     # short topic/prompt label
    is_baseline: bool = False
    ai_provider: AIProvider = AIProvider.NONE
    native_english: Optional[bool] = None
    theological_tradition: Optional[str] = None
    notes: str = ""
    source_id: str = ""             # original dataset row id (for traceability)


# ── Writing the corpus + manifest ────────────────────────────────────────────

_SAFE = re.compile(r"[^a-z0-9_\-]+")


def _slug(s: str) -> str:
    s = s.lower().strip().replace(" ", "_")
    return _SAFE.sub("", s)[:40] or "x"


def materialize(
    entries: List[WideEntry],
    corpus_dir: Path,
    manifest_path: Path,
    *,
    description: str,
    min_baseline_per_author: int = 3,
    min_scoring_per_author: int = 1,
    author_meta: Optional[Dict[str, dict]] = None,
) -> Dict[str, int]:
    """
    Write ``entries`` to ``corpus_dir`` as ``.txt`` files and emit a
    ``ValidationManifest`` to ``manifest_path``.

    Authors that don't meet the baseline/scoring minimums are dropped from
    the manifest (and a warning is printed). Returns a small stats dict
    so the caller can show "wrote N essays across M authors".

    The filenames are deterministic — ``{author_id}/{idx:04d}_{label}.txt``.
    Re-running materialize() on the same entries overwrites cleanly.
    """
    corpus_dir.mkdir(parents=True, exist_ok=True)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)

    # Group entries by author and split baseline vs scoring.
    by_author: Dict[str, List[WideEntry]] = {}
    for e in entries:
        by_author.setdefault(e.author_id, []).append(e)

    kept_authors: Dict[str, List[CorpusEntry]] = {}
    dropped: List[str] = []
    for author_id, items in by_author.items():
        baselines = [e for e in items if e.is_baseline]
        scoring = [e for e in items if not e.is_baseline]
        if len(baselines) < min_baseline_per_author or len(scoring) < min_scoring_per_author:
            dropped.append(
                f"{author_id} (baseline={len(baselines)}, scoring={len(scoring)})"
            )
            continue

        author_dir = corpus_dir / _slug(author_id)
        author_dir.mkdir(parents=True, exist_ok=True)

        corpus_entries: List[CorpusEntry] = []
        for idx, e in enumerate(items):
            fname = f"{_slug(author_id)}/{idx:04d}_{e.label.value}.txt"
            (corpus_dir / fname).write_text(e.text, encoding="utf-8")
            corpus_entries.append(CorpusEntry(
                filename=fname,
                author_id=author_id,
                label=e.label,
                prompt=e.prompt or "n/a",
                word_count=len(e.text.split()),
                is_baseline=e.is_baseline,
                ai_provider=e.ai_provider,
                theological_tradition=e.theological_tradition,
                native_english=e.native_english,
                notes=e.notes or e.source_id or None,
            ))
        kept_authors[author_id] = corpus_entries

    if dropped:
        print(f"  [adapter] dropped {len(dropped)} authors: {dropped[:5]}{'…' if len(dropped) > 5 else ''}")

    flat_entries = [c for lst in kept_authors.values() for c in lst]
    if not flat_entries:
        raise RuntimeError(
            f"No author met min_baseline={min_baseline_per_author} + "
            f"min_scoring={min_scoring_per_author}. Try a larger --sample."
        )

    manifest = ValidationManifest(
        version="1.0",
        created_at=datetime.datetime.utcnow().isoformat() + "Z",
        description=description,
        authors=author_meta or {a: {} for a in kept_authors},
        entries=flat_entries,
    )
    manifest_path.write_text(manifest.model_dump_json(indent=2))

    return {
        "authors_kept": len(kept_authors),
        "authors_dropped": len(dropped),
        "essays_written": len(flat_entries),
        "baseline_count": sum(1 for e in flat_entries if e.is_baseline),
        "scoring_count": sum(1 for e in flat_entries if not e.is_baseline),
    }


# ── Manifest lookup (for the bias slicer) ────────────────────────────────────

def manifest_lookup_for(manifest_path: Path) -> Dict[str, dict]:
    """
    Build the ``filename → {field: value, …}`` mapping that the bias
    slicer expects. Pulls ai_provider, native_english,
    theological_tradition off each entry.
    """
    data = json.loads(manifest_path.read_text())
    out: Dict[str, dict] = {}
    for e in data.get("entries", []):
        out[e["filename"]] = {
            "ai_provider": e.get("ai_provider"),
            "native_english": e.get("native_english"),
            "theological_tradition": e.get("theological_tradition"),
            "label": e.get("label"),
        }
    return out
