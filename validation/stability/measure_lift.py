"""
measure_lift.py — quantify the Phase 2 lift from LENGTH_ADAPTIVE_WEIGHTS.

Runs the public-author attribution test (Test 2) twice on the same
corpus:

  1. Flag OFF: ``LENGTH_ADAPTIVE_WEIGHTS=0`` (current production behaviour).
  2. Flag ON:  ``LENGTH_ADAPTIVE_WEIGHTS=1`` (Phase 2 length-adaptive scaling).

Held-out essays are truncated to ``--n-tokens`` words before scoring so
the comparison actually lives in the "short" bucket of
``LENGTH_WEIGHT_SCHEDULE``. At full length most chunks land in the
"long" bucket where the schedule is identity (no change by design).

The comparison reports per-essay rank-of-true-author for each
configuration plus aggregate top-1 accuracy. The baseline (current
production) is what we beat.

Reuses everything ``validation/public_authors/run.py`` already does
(TestClient, demo:pa_ student_id pattern, the same eligible-author
filter); only the scoring loop differs.
"""

from __future__ import annotations

# Lock env BEFORE any original.* import; we'll flip LENGTH_ADAPTIVE_WEIGHTS
# per-call further down.
from validation.benchmark.reproducibility import lock_environment  # noqa: E402
ENV_LOCK = lock_environment()

import argparse
import json
import os
import sys
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional


_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent.parent
sys.path.insert(0, str(_ROOT))

_MANIFEST = _ROOT / "validation" / "public_authors" / "manifest.json"
_CORPUS_DIR = _ROOT / "validation" / "public_authors" / "corpus"


def _truncate(text: str, n_words: int) -> str:
    words = text.split()
    return " ".join(words[:n_words])


def _set_flag(on: bool) -> None:
    os.environ["LENGTH_ADAPTIVE_WEIGHTS"] = "1" if on else "0"


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--n-tokens", type=int, default=500,
                   help="Truncate each held-out essay to this many words. "
                        "Default 500 (lands inside the 'short' bucket).")
    p.add_argument("--out", type=Path,
                   default=_HERE / "lift_2026-06-30.json",
                   help="Output JSON path for the per-essay comparison.")
    args = p.parse_args()

    import run as _run_module
    from fastapi.testclient import TestClient

    manifest = json.loads(_MANIFEST.read_text())
    by_author: Dict[str, dict] = defaultdict(lambda: {"baseline": [], "scored": []})
    for e in manifest["entries"]:
        key = "baseline" if e["is_baseline"] else "scored"
        by_author[e["author_id"]][key].append(e)

    eligible = [
        aid for aid, items in sorted(by_author.items())
        if len(items["baseline"]) >= 3 and items["scored"]
    ]
    print(f"eligible authors: {eligible}", file=sys.stderr)

    client = TestClient(_run_module.load_legacy_demo_app())

    # ── Build baselines once per author (flag-independent — baselines are
    #     not scored, only the held-out essays are). ──
    for aid in eligible:
        sid = f"demo:pa_{aid}"
        for entry in by_author[aid]["baseline"]:
            text = (_CORPUS_DIR / entry["filename"]).read_text(encoding="utf-8")
            r = client.post(f"/students/{sid}/baseline", json={
                "text": text,
                "provenance": "verified",
                "assignment": entry["prompt"],
                "submitted_at": "2026-01-01",
            })
            if r.status_code != 200:
                print(f"  ⚠ baseline {aid} {entry['filename']}: {r.status_code}",
                      file=sys.stderr)
        print(f"  baseline {aid}: {len(by_author[aid]['baseline'])} samples",
              file=sys.stderr)

    # ── Score each held-out essay TWICE: flag off, then flag on. ──
    rows: List[dict] = []
    for true_author in eligible:
        for entry in by_author[true_author]["scored"]:
            text = _truncate(
                (_CORPUS_DIR / entry["filename"]).read_text(encoding="utf-8"),
                args.n_tokens,
            )
            for mode in ("off", "on"):
                _set_flag(mode == "on")
                devs: Dict[str, float] = {}
                for candidate in eligible:
                    rr = client.post(f"/students/demo:pa_{candidate}/score", json={
                        "text": text, "assignment": entry["prompt"],
                        "submission_id": f"{entry['filename']}#{mode}",
                    })
                    devs[candidate] = float("nan") if rr.status_code != 200 \
                        else float(rr.json()["authorship"]["deviation_score"])

                ranked = sorted(devs.items(), key=lambda kv: kv[1])
                predicted = ranked[0][0]
                rank_of_true = next(
                    (i + 1 for i, (a, _) in enumerate(ranked) if a == true_author),
                    0,
                )
                rows.append({
                    "filename": entry["filename"],
                    "true_author": true_author,
                    "flag": mode,
                    "predicted": predicted,
                    "correct": predicted == true_author,
                    "rank_of_true": rank_of_true,
                    "deviations": {a: round(d, 4) for a, d in devs.items()},
                })

    # ── Aggregate. ──
    by_mode: Dict[str, list] = {"off": [], "on": []}
    for r in rows:
        by_mode[r["flag"]].append(r)

    def _top1(rs):
        return sum(1 for r in rs if r["correct"]) / max(1, len(rs))
    def _mean_rank(rs):
        return sum(r["rank_of_true"] for r in rs) / max(1, len(rs))

    summary = {
        "n_essays_per_mode": len(by_mode["off"]),
        "n_tokens_truncated_to": args.n_tokens,
        "off": {
            "top1": round(_top1(by_mode["off"]), 4),
            "mean_rank": round(_mean_rank(by_mode["off"]), 3),
        },
        "on": {
            "top1": round(_top1(by_mode["on"]), 4),
            "mean_rank": round(_mean_rank(by_mode["on"]), 3),
        },
    }
    summary["delta_top1"] = round(summary["on"]["top1"] - summary["off"]["top1"], 4)
    summary["delta_mean_rank"] = round(
        summary["on"]["mean_rank"] - summary["off"]["mean_rank"], 3
    )

    payload = {"summary": summary, "rows": rows, "eligible": eligible,
               "env": ENV_LOCK.__dict__}
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, indent=2))

    print()
    print(f"┌─────────────────────────────────────────────────────────────┐")
    print(f"│  n essays / mode: {summary['n_essays_per_mode']:<10}                              │")
    print(f"│  truncated to:    {args.n_tokens:<10} words                          │")
    print(f"│  flag OFF →  top1={summary['off']['top1']:.2%}   mean_rank={summary['off']['mean_rank']:.2f}     │")
    print(f"│  flag ON  →  top1={summary['on']['top1']:.2%}   mean_rank={summary['on']['mean_rank']:.2f}     │")
    print(f"│  Δ top1     :  {summary['delta_top1']:+.4f}                                │")
    print(f"│  Δ mean_rank:  {summary['delta_mean_rank']:+.3f}                                │")
    print(f"│  Report:    {args.out}")
    print(f"└─────────────────────────────────────────────────────────────┘")
    return 0


if __name__ == "__main__":
    sys.exit(main())
