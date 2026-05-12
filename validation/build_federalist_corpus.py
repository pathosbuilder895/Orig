"""
validation/build_federalist_corpus.py — Build Federalist Papers validation corpus.

Downloads the Federalist Papers (Project Gutenberg #18), parses all 85 papers
into individual text files, writes a manifest.json, and then runs the calibration
study to produce a JSON report.

Usage:
    python -m validation.build_federalist_corpus

Output:
    validation/corpus/fed_*.txt          — individual papers
    validation/manifest.json             — corpus manifest
    validation/calibration_report.json   — calibration results
"""

from __future__ import annotations

import json
import os
import re
import sys
import urllib.request
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# ── Roman numeral converter ───────────────────────────────────────────────────

ROMAN = {
    'M': 1000, 'CM': 900, 'D': 500, 'CD': 400, 'C': 100, 'XC': 90,
    'L': 50,  'XL': 40,  'X': 10,  'IX': 9,   'V': 5,   'IV': 4,  'I': 1,
}

def roman_to_int(s: str) -> int:
    result, prev = 0, 0
    for ch in reversed(s.upper()):
        val = ROMAN.get(ch, 0)
        result += val if val >= prev else -val
        prev = val
    return result


# ── Authorship ground truth ───────────────────────────────────────────────────
# Source: Mosteller & Wallace (1964) + modern consensus
# H = Hamilton, M = Madison, J = Jay, HM = joint Hamilton+Madison
# D = Disputed (modern consensus: Madison)

AUTHORSHIP: Dict[int, str] = {
    1:  'H',
    2:  'J', 3: 'J', 4: 'J', 5: 'J',
    6:  'H', 7: 'H', 8: 'H', 9: 'H',
    10: 'M',
    11: 'H', 12: 'H', 13: 'H',
    14: 'M',
    15: 'H', 16: 'H', 17: 'H',
    18: 'HM', 19: 'HM', 20: 'HM',
    21: 'H', 22: 'H', 23: 'H', 24: 'H', 25: 'H',
    26: 'H', 27: 'H', 28: 'H', 29: 'H', 30: 'H',
    31: 'H', 32: 'H', 33: 'H', 34: 'H', 35: 'H', 36: 'H',
    37: 'M', 38: 'M', 39: 'M', 40: 'M', 41: 'M', 42: 'M', 43: 'M', 44: 'M',
    45: 'M', 46: 'M', 47: 'M', 48: 'M',
    49: 'D', 50: 'D', 51: 'D', 52: 'D', 53: 'D', 54: 'D', 55: 'D',
    56: 'D', 57: 'D', 58: 'D',
    59: 'H', 60: 'H', 61: 'H',
    62: 'D', 63: 'D',
    64: 'J',
    65: 'H', 66: 'H', 67: 'H', 68: 'H', 69: 'H', 70: 'H',
    71: 'H', 72: 'H', 73: 'H', 74: 'H', 75: 'H', 76: 'H', 77: 'H',
    78: 'H', 79: 'H', 80: 'H', 81: 'H', 82: 'H', 83: 'H', 84: 'H', 85: 'H',
}

AUTHOR_NAMES = {'H': 'Hamilton', 'M': 'Madison', 'J': 'Jay', 'HM': 'Hamilton & Madison', 'D': 'Disputed'}

# Papers used as baselines per author (undisputed, well-distributed)
# Need ≥ 3 per author for calibration; we use 6 to give a solid baseline
BASELINE_PAPERS: Dict[str, List[int]] = {
    'hamilton': [6, 7, 8, 9, 11, 12, 15, 16, 21, 22],   # 10 baselines
    'madison':  [10, 14, 37, 38, 39, 40, 41, 42],          # 8 baselines
    'jay':      [2, 3, 4],                                  # 3 baselines (Jay only wrote 5)
}


# ── Parsing ───────────────────────────────────────────────────────────────────

def fetch_text(url: str) -> str:
    print(f"Fetching {url} …")
    with urllib.request.urlopen(url, timeout=30) as r:
        return r.read().decode('utf-8-sig')


def parse_papers(raw: str) -> Dict[int, str]:
    """
    Split the Project Gutenberg text into individual paper bodies.
    Returns {paper_number: body_text}.
    """
    # Find the main content (after ToC)
    start = raw.find('THE FEDERALIST.\nNo. I.')
    if start == -1:
        # Try alternative
        start = raw.find('THE FEDERALIST.\r\nNo. I.')
    if start == -1:
        raise ValueError("Could not find start of papers")

    content = raw[start:]

    # Split on paper headers: "THE FEDERALIST.\nNo. {ROMAN}."
    # The header may or may not have "THE FEDERALIST." prefix after the first
    header_re = re.compile(
        r'THE FEDERALIST\.\s*\n+No\.\s+([IVXLCDM]+)\.',
        re.MULTILINE,
    )

    splits = list(header_re.finditer(content))
    if len(splits) < 80:
        # Try without "THE FEDERALIST." prefix (some editions drop it mid-text)
        header_re2 = re.compile(r'\nNo\.\s+([IVXLCDM]+)\.\s*\n', re.MULTILINE)
        splits = list(header_re2.finditer(content))

    papers: Dict[int, str] = {}
    for i, m in enumerate(splits):
        num = roman_to_int(m.group(1))
        if num < 1 or num > 85:
            continue
        body_start = m.end()
        body_end   = splits[i + 1].start() if i + 1 < len(splits) else len(content)
        body = content[body_start:body_end].strip()
        # Remove the byline header lines (title, publication, author name line)
        # Keep everything from "To the People of the State of New York:" onward
        # or if that's not present, strip first 6 lines
        to_people = body.find('To the People of the State of New York:')
        if to_people != -1:
            body = body[to_people:]
        else:
            # Strip first few header lines
            lines = body.split('\n')
            body = '\n'.join(lines[5:]).strip()
        papers[num] = body

    return papers


def save_corpus(papers: Dict[int, str], corpus_dir: Path) -> Dict[int, str]:
    """Save individual paper files and return {num: filename}."""
    corpus_dir.mkdir(parents=True, exist_ok=True)
    filenames: Dict[int, str] = {}
    for num, text in papers.items():
        auth_code = AUTHORSHIP.get(num, '?')
        tag = {'H': 'hamilton', 'M': 'madison', 'J': 'jay',
               'HM': 'joint', 'D': 'disputed'}.get(auth_code, 'unknown')
        fname = f"fed_{tag}_{num:02d}.txt"
        (corpus_dir / fname).write_text(text, encoding='utf-8')
        filenames[num] = fname
    print(f"Saved {len(filenames)} papers to {corpus_dir}/")
    return filenames


# ── Manifest builder ──────────────────────────────────────────────────────────

def build_manifest(
    papers: Dict[int, str],
    filenames: Dict[int, str],
) -> dict:
    """
    Build the validation manifest.

    Strategy:
      - author_hamilton: baseline = BASELINE_PAPERS['hamilton']
          authentic = remaining undisputed Hamilton papers
          ghostwritten (cross-author) = all undisputed Madison papers (not baseline)
      - author_madison: baseline = BASELINE_PAPERS['madison']
          authentic = remaining undisputed Madison papers
          ghostwritten = sample of undisputed Hamilton papers (not baseline)
      - author_jay: baseline = BASELINE_PAPERS['jay']
          authentic = remaining Jay papers
          ghostwritten = 3 undisputed Hamilton papers
      Disputed papers are included as a SEPARATE scoring run (label=authentic
      under author_disputed_as_madison to test the modern consensus).
    """
    from datetime import datetime, timezone

    entries = []

    # ── Hamilton ──────────────────────────────────────────────────────────────
    hamilton_baseline = set(BASELINE_PAPERS['hamilton'])
    hamilton_undisputed = [n for n, a in AUTHORSHIP.items() if a == 'H']
    madison_undisputed  = [n for n, a in AUTHORSHIP.items() if a == 'M']
    jay_undisputed      = [n for n, a in AUTHORSHIP.items() if a == 'J']

    for num in hamilton_undisputed:
        if num not in filenames:
            continue
        is_base = num in hamilton_baseline
        entries.append({
            "filename":    filenames[num],
            "author_id":   "hamilton",
            "label":       "authentic",
            "prompt":      f"Federalist No. {num} — constitutional argument",
            "word_count":  len(papers[num].split()),
            "is_baseline": is_base,
            "notes":       f"HAMILTON undisputed{'  [BASELINE]' if is_base else ''}",
        })

    # Cross-author ghostwritten: score Madison papers against Hamilton baseline
    # Use Madison papers NOT in Madison's own baseline (so they're fresh data)
    madison_scoring = [n for n in madison_undisputed
                       if n not in BASELINE_PAPERS['madison'] and n in filenames][:6]
    for num in madison_scoring:
        entries.append({
            "filename":    filenames[num],
            "author_id":   "hamilton",
            "label":       "ghostwritten",
            "prompt":      f"Federalist No. {num} — constitutional argument",
            "word_count":  len(papers[num].split()),
            "is_baseline": False,
            "notes":       "MADISON paper scored against Hamilton baseline (cross-author test)",
        })

    # ── Madison ───────────────────────────────────────────────────────────────
    madison_baseline = set(BASELINE_PAPERS['madison'])
    for num in madison_undisputed:
        if num not in filenames:
            continue
        is_base = num in madison_baseline
        entries.append({
            "filename":    filenames[num],
            "author_id":   "madison",
            "label":       "authentic",
            "prompt":      f"Federalist No. {num} — constitutional argument",
            "word_count":  len(papers[num].split()),
            "is_baseline": is_base,
            "notes":       f"MADISON undisputed{'  [BASELINE]' if is_base else ''}",
        })

    # Cross-author: Hamilton papers scored against Madison baseline
    hamilton_scoring_cross = [n for n in hamilton_undisputed
                               if n not in hamilton_baseline and n in filenames][2:8]
    for num in hamilton_scoring_cross:
        entries.append({
            "filename":    filenames[num],
            "author_id":   "madison",
            "label":       "ghostwritten",
            "prompt":      f"Federalist No. {num} — constitutional argument",
            "word_count":  len(papers[num].split()),
            "is_baseline": False,
            "notes":       "HAMILTON paper scored against Madison baseline (cross-author test)",
        })

    # ── Jay ───────────────────────────────────────────────────────────────────
    jay_baseline = set(BASELINE_PAPERS['jay'])
    for num in jay_undisputed:
        if num not in filenames:
            continue
        is_base = num in jay_baseline
        entries.append({
            "filename":    filenames[num],
            "author_id":   "jay",
            "label":       "authentic",
            "prompt":      f"Federalist No. {num} — constitutional argument",
            "word_count":  len(papers[num].split()),
            "is_baseline": is_base,
            "notes":       f"JAY undisputed{'  [BASELINE]' if is_base else ''}",
        })

    # Cross-author: Hamilton papers scored against Jay baseline
    for num in [23, 24, 25]:
        if num not in filenames:
            continue
        entries.append({
            "filename":    filenames[num],
            "author_id":   "jay",
            "label":       "ghostwritten",
            "prompt":      f"Federalist No. {num} — constitutional argument",
            "word_count":  len(papers[num].split()),
            "is_baseline": False,
            "notes":       "HAMILTON paper scored against Jay baseline (cross-author test)",
        })

    # ── Disputed papers → separate author_id so they don't taint the main AUC ─
    # We build a combined Madison baseline (all 8 Madison baseline papers)
    # and score the disputed papers against it.
    # Modern consensus says all disputed papers are Madison's.
    for num in [n for n, a in AUTHORSHIP.items() if a == 'D']:
        if num not in filenames:
            continue
        entries.append({
            "filename":    filenames[num],
            "author_id":   "disputed_vs_madison",
            "label":       "authentic",   # hypothesis: they ARE Madison
            "prompt":      f"Federalist No. {num} — constitutional argument (DISPUTED)",
            "word_count":  len(papers[num].split()),
            "is_baseline": False,
            "notes":       "DISPUTED paper — modern consensus: Madison",
        })

    # Add Madison baselines for the disputed author_id too
    for num in BASELINE_PAPERS['madison']:
        if num not in filenames:
            continue
        entries.append({
            "filename":    filenames[num],
            "author_id":   "disputed_vs_madison",
            "label":       "authentic",
            "prompt":      f"Federalist No. {num} — constitutional argument",
            "word_count":  len(papers[num].split()),
            "is_baseline": True,
            "notes":       "MADISON baseline for disputed-paper test",
        })

    manifest = {
        "version": "1.0",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "description": (
            "Federalist Papers authorship validation corpus. "
            "Ground truth per Mosteller & Wallace (1964) and modern consensus. "
            "Disputed papers (49-58, 62-63) attributed to Madison by consensus."
        ),
        "authors": {
            "hamilton": {"name": "Alexander Hamilton", "papers": "undisputed"},
            "madison":  {"name": "James Madison",      "papers": "undisputed"},
            "jay":      {"name": "John Jay",            "papers": "undisputed"},
            "disputed_vs_madison": {
                "name": "Disputed papers vs. Madison baseline",
                "papers": "Nos. 49-58, 62-63",
            },
        },
        "entries": entries,
    }
    return manifest


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    root = Path(__file__).resolve().parent.parent
    corpus_dir   = root / "validation" / "corpus"
    manifest_path = root / "validation" / "manifest.json"
    report_path   = root / "validation" / "calibration_report.json"

    # 1. Fetch
    url = "https://www.gutenberg.org/cache/epub/18/pg18.txt"
    raw = fetch_text(url)

    # 2. Parse
    papers = parse_papers(raw)
    print(f"Parsed {len(papers)} papers")

    # Verify we got a reasonable count
    missing = [n for n in range(1, 86) if n not in papers]
    if missing:
        print(f"  WARNING: missing papers: {missing}")

    # 3. Save corpus
    filenames = save_corpus(papers, corpus_dir)

    # 4. Build manifest
    manifest = build_manifest(papers, filenames)
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding='utf-8')
    print(f"Manifest written: {manifest_path} ({len(manifest['entries'])} entries)")

    # 5. Run calibration
    print("\nRunning calibration study …")
    sys.path.insert(0, str(root))
    from validation.calibration import run_calibration, save_report
    report = run_calibration(str(corpus_dir), str(manifest_path))
    save_report(report, str(report_path))

    # 6. Print summary
    print(f"\n{'='*60}")
    print(f"FEDERALIST PAPERS CALIBRATION")
    print(f"{'='*60}")
    print(f"Authors:          {report.total_authors}")
    print(f"Essays scored:    {report.total_essays_scored}")
    print(f"Baseline samples: {report.total_baseline_samples}")
    print(f"AUC:              {report.auc:.4f}")
    print(f"Avg score time:   {report.avg_scoring_time_ms:.1f} ms")
    print()
    for name, m in report.threshold_metrics.items():
        print(f"Threshold '{name}' ({m.threshold}):")
        print(f"  Accuracy={m.accuracy:.1%}  TPR={m.tpr:.1%}  FPR={m.fpr:.1%}")
    print()
    print("Per-label deviation (lower = more author-like):")
    for label, stats in sorted(report.per_label_stats.items()):
        print(f"  {label:14s}  mean={stats['mean_deviation']:.3f}  "
              f"std={stats['std_deviation']:.3f}  n={stats['count']}")
    print()

    # Show what the system says about the disputed papers
    disputed_results = [r for r in report.results if r.author_id == "disputed_vs_madison"]
    if disputed_results:
        print("Disputed papers vs. Madison baseline:")
        for r in sorted(disputed_results, key=lambda x: x.filename):
            num_match = re.search(r'(\d+)', r.filename)
            num = num_match.group(1) if num_match else '?'
            verdict = "✓ MADISON" if r.authorship_probability >= 0.5 else "✗ NOT MADISON"
            print(f"  No. {num:>2s}  prob={r.authorship_probability:.3f}  "
                  f"dev={r.deviation_score:.3f}  {verdict}")

    print(f"\nReport: {report_path}")


if __name__ == "__main__":
    main()
