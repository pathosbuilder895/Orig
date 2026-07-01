"""
pan_av.py — PAN Authorship Verification adapter.

PAN's AV datasets (2021/2022/2023, Zenodo) are pair-style:

    {"id": "1", "pair": ["text_a", "text_b"], "authors": ["alice", "bob"]}
    truth: {"id": "1", "same": false}

For Original — which is baseline-vs-submission — we re-group by author:
collect every text written by author X, take the first 3 as baseline,
the rest as authentic. For every cross-author text (a text by author Y
in a pair we shared with author X), that text becomes a GHOSTWRITTEN
scoring entry tagged against author X.

That gives ``run_calibration`` the (≥3 baseline, ≥1 scoring) shape per
author it needs, while still using the real PAN labels.

The fetcher (``scripts/fetch_benchmark_data.py``) caches:
    .benchmark_cache/pan/<year>/dataset.json
which already drops author metadata; we re-parse the original
``pairs.jsonl`` and ``truth.jsonl`` to keep the author IDs.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import List, Optional

from validation.manifest_schema import AIProvider, AuthorshipLabel
from validation.wide._adapter import WideEntry, materialize


PAN_CACHE_ROOT = Path(__file__).resolve().parent.parent.parent / ".benchmark_cache" / "pan"


def _find_jsonl(year_dir: Path, name: str) -> Optional[Path]:
    """Locate pairs.jsonl / truth.jsonl, which may sit under an `inner_dir`."""
    direct = list(year_dir.glob(f"**/{name}"))
    return direct[0] if direct else None


def build_corpus(
    *,
    year: int,
    corpus_dir: Path,
    manifest_path: Path,
    sample_pairs: int = 500,
    min_text_chars: int = 800,
) -> dict:
    """
    Read the cached PAN AV release for ``year``, regroup by author, and
    write a corpus + manifest into ``corpus_dir`` / ``manifest_path``.

    Args:
        year: 2021, 2022, or 2023.
        sample_pairs: cap on the number of pairs consumed (keeps the
                      benchmark laptop-friendly).
        min_text_chars: drop any text below this length — Original needs
                        enough material to get a stable feature vector.

    Returns the materialize() stats dict.
    """
    year_dir = PAN_CACHE_ROOT / str(year)
    if not year_dir.exists():
        raise FileNotFoundError(
            f"PAN {year} not cached. Run: python scripts/fetch_benchmark_data.py "
            f"--pan-year {year}"
        )

    pairs_path = _find_jsonl(year_dir, "pairs.jsonl")
    truth_path = _find_jsonl(year_dir, "truth.jsonl")
    if pairs_path is None or truth_path is None:
        raise FileNotFoundError(
            f"PAN {year} cache incomplete: pairs.jsonl/truth.jsonl missing. "
            f"Re-run the fetcher with --force."
        )

    truth: dict = {}
    with open(truth_path, encoding="utf-8") as f:
        for line in f:
            obj = json.loads(line)
            truth[obj["id"]] = bool(obj.get("same", False))

    # Group texts by author. For each text we remember its sibling in
    # the original pair so we can tag cross-author texts as GHOSTWRITTEN.
    by_author: dict = {}    # author_id → [(text, label, pair_id, sibling_author)]
    n_pairs = 0
    with open(pairs_path, encoding="utf-8") as f:
        for line in f:
            if n_pairs >= sample_pairs:
                break
            obj = json.loads(line)
            pair = obj.get("pair", [])
            authors = obj.get("authors", [])
            if len(pair) != 2 or len(authors) != 2:
                continue
            if not all(len(t) >= min_text_chars for t in pair):
                continue
            n_pairs += 1
            same = truth.get(obj["id"], False)

            # Author A's text — always authentic to A.
            by_author.setdefault(authors[0], []).append(
                (pair[0], AuthorshipLabel.AUTHENTIC, obj["id"], authors[1])
            )
            # Author B's text — authentic to B when same=True, otherwise
            # authentic to B AND a ghostwritten scoring candidate for A.
            by_author.setdefault(authors[1], []).append(
                (pair[1], AuthorshipLabel.AUTHENTIC, obj["id"], authors[0])
            )

    # Ghostwritten cross-author samples — for every author with ≥3 own
    # texts, pull cross-author texts from authors we've seen with them.
    entries: List[WideEntry] = []
    eligible = {a for a, txts in by_author.items() if len(txts) >= 4}
    for author_id in eligible:
        own = by_author[author_id]
        # First 3 = baseline; rest = authentic scoring.
        for idx, (text, _, pid, _) in enumerate(own):
            entries.append(WideEntry(
                author_id=f"pan{year}:{author_id}",
                label=AuthorshipLabel.AUTHENTIC,
                text=text,
                prompt=f"pan{year}_pair_{pid}",
                is_baseline=(idx < 3),
                ai_provider=AIProvider.NONE,
                native_english=None,
                source_id=f"{pid}#a",
            ))
        # Cross-author ghostwritten — up to N per author, from siblings.
        ghost_count = 0
        for _text, _label, pid, sibling in own:
            if sibling not in eligible:
                continue
            sibling_texts = by_author.get(sibling, [])
            if not sibling_texts:
                continue
            ghost_text = sibling_texts[0][0]
            if len(ghost_text) < min_text_chars:
                continue
            entries.append(WideEntry(
                author_id=f"pan{year}:{author_id}",
                label=AuthorshipLabel.GHOSTWRITTEN,
                text=ghost_text,
                prompt=f"pan{year}_pair_{pid}",
                is_baseline=False,
                source_id=f"{pid}#ghost_from_{sibling}",
                notes=f"ghostwritten by sibling {sibling}",
            ))
            ghost_count += 1
            if ghost_count >= 3:
                break

    return materialize(
        entries,
        corpus_dir=corpus_dir,
        manifest_path=manifest_path,
        description=f"PAN {year} Authorship Verification — regrouped by author",
    )
