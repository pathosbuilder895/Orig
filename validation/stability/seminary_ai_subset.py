"""
seminary_ai_subset.py — how well does Original catch AI-generated essays
in the seminary corpus, when scored against real author baselines?

The 20 ai_generated essays in validation/manifest.json are attributed
to a synthetic ``ai_author`` with ZERO baseline samples. That means
``run_calibration()`` skips them entirely (author-level filter needs
≥3 baselines), so the seminary corpus's headline AUC (0.7778) is
actually measured on the AUTHENTIC vs GHOSTWRITTEN majority alone.
The AI essays never contribute to the reported number.

This script scores the 20 AI essays against every REAL author baseline
via the in-memory FastAPI TestClient path, then reports the deviation
distribution and compares it to the authentic-vs-authentic distribution
from the same authors' baselines. The comparison answers a specific
question:

  "When ghostwritten-by-AI text is presented to Original as if it
   came from a real student, does Original correctly rate it as
   highly deviant?"

The right answer is HIGH deviation across the board — an AI essay
should look nothing like any real student's baseline.

  python -m validation.stability.seminary_ai_subset
"""

from __future__ import annotations

# Lock env BEFORE any original.* import; TestClient will pull it in.
from validation.benchmark.reproducibility import lock_environment  # noqa: E402
ENV_LOCK = lock_environment()

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, List

import numpy as np


_ROOT = Path(__file__).resolve().parent.parent.parent
_CORPUS = _ROOT / "validation" / "corpus"
_MANIFEST = _ROOT / "validation" / "manifest.json"


def _auc(y_true: np.ndarray, y_score: np.ndarray) -> float:
    """AUC via trapezoidal rule; same helper the bias slicer uses."""
    if y_true.size == 0 or y_score.size == 0:
        return 0.5
    order = np.argsort(-y_score, kind="mergesort")
    y_sorted = y_true[order]
    P = float(y_sorted.sum())
    N = float(y_sorted.size - P)
    if P == 0 or N == 0:
        return 0.5
    tps = np.cumsum(y_sorted)
    fps = np.cumsum(1 - y_sorted)
    tpr = np.concatenate([[0.0], tps / P])
    fpr = np.concatenate([[0.0], fps / N])
    return float(np.trapz(tpr, fpr))


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--out", type=Path,
                   default=_ROOT / "validation" / "stability" / "seminary_ai_subset_2026-07-01.json")
    p.add_argument("--max-real-authors", type=int, default=8,
                   help="Cap on real authors used as baseline targets (default 8).")
    args = p.parse_args()

    import run as _run_module
    from fastapi.testclient import TestClient

    manifest = json.loads(_MANIFEST.read_text())

    # Bucket entries by author + role.
    by_author = defaultdict(lambda: {"baseline": [], "scored_authentic": []})
    ai_essays: List[dict] = []
    for e in manifest["entries"]:
        if e["label"] == "ai_generated":
            ai_essays.append(e)
            continue
        if e.get("is_baseline"):
            by_author[e["author_id"]]["baseline"].append(e)
        elif e["label"] == "authentic":
            by_author[e["author_id"]]["scored_authentic"].append(e)

    # Pick the top-N real authors by baseline count.
    eligible = sorted(
        (a for a, items in by_author.items() if len(items["baseline"]) >= 3
         and items["scored_authentic"]),
        key=lambda a: -len(by_author[a]["baseline"]),
    )[:args.max_real_authors]
    if not eligible:
        print("[seminary-ai] no eligible real authors!", file=sys.stderr)
        return 1

    print(f"[seminary-ai] {len(ai_essays)} AI essays × {len(eligible)} real authors"
          f" = {len(ai_essays) * len(eligible)} AI scorings",
          file=sys.stderr)
    print(f"[seminary-ai] eligible: {eligible}", file=sys.stderr)

    client = TestClient(_run_module.load_legacy_demo_app())

    # ── 1. Build each real author's baseline. ──
    for aid in eligible:
        sid = f"demo:sem_{aid}"
        for entry in by_author[aid]["baseline"]:
            text = (_CORPUS / entry["filename"]).read_text(encoding="utf-8")
            r = client.post(f"/students/{sid}/baseline", json={
                "text": text,
                "provenance": "verified",
                "assignment": entry.get("prompt", "n/a"),
                "submitted_at": "2026-01-01",
            })
            if r.status_code != 200:
                print(f"  ⚠ baseline {aid} {entry['filename']}: "
                      f"{r.status_code} {r.text[:120]}", file=sys.stderr)
        print(f"  baseline built: {aid} ({len(by_author[aid]['baseline'])} samples)",
              file=sys.stderr)

    # ── 2. Score each authentic scoring essay against its OWN author.
    #      (Same-author baseline — should be LOW deviation.)
    print(f"[seminary-ai] scoring authentic essays against their own author…",
          file=sys.stderr)
    authentic_devs: List[float] = []
    for aid in eligible:
        for entry in by_author[aid]["scored_authentic"]:
            text = (_CORPUS / entry["filename"]).read_text(encoding="utf-8")
            rr = client.post(f"/students/demo:sem_{aid}/score", json={
                "text": text,
                "assignment": entry.get("prompt", "n/a"),
                "submission_id": f"authentic#{entry['filename']}",
            })
            if rr.status_code == 200:
                authentic_devs.append(float(rr.json()["authorship"]["deviation_score"]))
    print(f"  {len(authentic_devs)} authentic-vs-own scorings",
          file=sys.stderr)

    # ── 3. Score each AI essay against every real author.
    #      Take the MIN across authors as the best-case (attacker gets
    #      lucky). Take the MEAN as the average impersonation-anomaly.
    print(f"[seminary-ai] scoring AI essays against each real author…",
          file=sys.stderr)
    ai_min_devs: List[float] = []
    ai_mean_devs: List[float] = []
    ai_all_devs: List[float] = []
    for i, entry in enumerate(ai_essays):
        text = (_CORPUS / entry["filename"]).read_text(encoding="utf-8")
        devs_this_essay: List[float] = []
        for aid in eligible:
            rr = client.post(f"/students/demo:sem_{aid}/score", json={
                "text": text,
                "assignment": entry.get("prompt", "n/a"),
                "submission_id": f"ai_essay_{i}#{aid}",
            })
            if rr.status_code == 200:
                d = float(rr.json()["authorship"]["deviation_score"])
                devs_this_essay.append(d)
                ai_all_devs.append(d)
        if devs_this_essay:
            ai_min_devs.append(min(devs_this_essay))
            ai_mean_devs.append(sum(devs_this_essay) / len(devs_this_essay))

    # ── 4. Aggregate: AUC for "is this AUTHENTIC?" using
    #      y_true=1 for own-author authentic, 0 for AI-vs-any-author.
    ad = np.array(authentic_devs, dtype=np.float64)
    aid = np.array(ai_all_devs, dtype=np.float64)
    y_true = np.concatenate([np.ones(ad.size, dtype=np.int8),
                             np.zeros(aid.size, dtype=np.int8)])
    y_prob = 1.0 - np.concatenate([ad, aid])          # authorship_probability ≈ 1 − deviation
    auc = _auc(y_true, y_prob)

    def _pct(vs, q):
        return round(float(np.percentile(vs, q)), 4) if len(vs) else float("nan")

    summary = {
        "n_ai_essays": len(ai_essays),
        "n_real_authors": len(eligible),
        "eligible_real_authors": eligible,
        "n_authentic_scorings": len(authentic_devs),
        "n_ai_scorings": len(ai_all_devs),
        "authentic": {
            "mean": round(float(ad.mean()), 4) if ad.size else None,
            "std":  round(float(ad.std()), 4)  if ad.size else None,
            "p25":  _pct(ad, 25), "p50": _pct(ad, 50), "p75": _pct(ad, 75),
        },
        "ai_all": {
            "mean": round(float(aid.mean()), 4) if aid.size else None,
            "std":  round(float(aid.std()), 4)  if aid.size else None,
            "p25":  _pct(aid, 25), "p50": _pct(aid, 50), "p75": _pct(aid, 75),
        },
        "ai_min_per_essay": {
            "mean": round(float(np.mean(ai_min_devs)), 4) if ai_min_devs else None,
            "std":  round(float(np.std(ai_min_devs)), 4)  if ai_min_devs else None,
        },
        "ai_mean_per_essay": {
            "mean": round(float(np.mean(ai_mean_devs)), 4) if ai_mean_devs else None,
            "std":  round(float(np.std(ai_mean_devs)), 4)  if ai_mean_devs else None,
        },
        "auc_authentic_vs_ai": round(auc, 4),
        # How often does AI look MORE authentic than a real essay?
        "pct_ai_lower_dev_than_authentic_p50": round(
            float(np.mean(aid < np.median(ad))) if aid.size and ad.size else 0.0, 4,
        ),
        "env": ENV_LOCK.__dict__,
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(summary, indent=2))

    print()
    print(f"┌────────────────────────────────────────────────────────────────┐")
    print(f"│  seminary AI-detection: 20 AI essays × 8 real authors            │")
    print(f"│  authentic_vs_ai AUC:  {summary['auc_authentic_vs_ai']:.4f}                                  │")
    print(f"│  authentic mean_dev:    {summary['authentic']['mean']}                             │")
    print(f"│         AI mean_dev:    {summary['ai_all']['mean']}                             │")
    print(f"│  AI-min per essay:      {summary['ai_min_per_essay']['mean']} (best-case attacker score)  │")
    print(f"│  AI-mean per essay:     {summary['ai_mean_per_essay']['mean']} (average impersonation)   │")
    print(f"│  % AI scoring below median-authentic: {summary['pct_ai_lower_dev_than_authentic_p50']:.1%}       │")
    print(f"│  Report: {args.out}")
    print(f"└────────────────────────────────────────────────────────────────┘")
    return 0


if __name__ == "__main__":
    sys.exit(main())
