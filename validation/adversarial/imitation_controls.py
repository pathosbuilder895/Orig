"""
validation/adversarial/imitation_controls.py: report-only controls for the
two confounds a validation review found in gate G-A2 (2026-11-19).

G-A2 compared ~650-word AI imitations with the victim's genuine held-out
documents, which run 2,500 to 19,400 words; and for the six cross-work
victims every baseline and held-out document is one unbroken paragraph,
while the imitations have paragraphs. A short paper against long past
papers scores high whoever wrote it
(`docs/research/2026-11-14-length-matched-baseline.md`), and the paragraph
features differ outright, so G-A2's separation could come from length and
layout rather than from the imitation failing to read as its author.

Two controls, scored on the same live path, flags and baselines as G-A2:

  genuine_slice   the first W words of each genuine held-out document, W the
                  word count of that victim's imitation at that N, cut on the
                  original text so its own formatting is kept.
  imitation_flat  the imitation with its paragraph breaks replaced by spaces,
                  for victims whose baselines are all one paragraph each;
                  otherwise the imitation unchanged.

Printed and written: AUROC (with the gates' 95% lower bound) and the
`schedule_conversation`+ rate for imitation vs full-length genuine (G-A2's
own comparison), imitation vs genuine_slice (length matched) and
imitation_flat vs genuine_slice (length and layout matched). The imitation
and full-length genuine scores are read from the G-A2 report rather than
re-scored, so run this at the commit that report was scored at: imitations
left unflattened are re-scored as a check, must match the report bit for
bit (`reproduction_check`), and the run exits 1 when they do not.
Report-only: no gate reads it. Since 2026-11-20 G-A2 itself compares the
imitations with genuine_slice cells built by the harness
(`report.length_matched_slices`, the same cut at the same W), so this module
now serves as the layout control and the record of the 2026-11-19 numbers.

Layout turned out not to matter for the single-paragraph victims: their
`avg_paragraph_length` is the same in every baseline, so
`StudentState.active_feature_mask` drops it and the score never sees it.

    .venv/bin/python -m validation.adversarial.imitation_controls \\
        --report validation/adversarial/reports/2026-11-19_llm_attacks.json \\
        --out validation/adversarial/reports/2026-11-19_imitation_controls.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

_ACTIONS = ("no_action", "monitor", "schedule_conversation", "escalate")
_WORD_RE = re.compile(r"\S+")


def cut_words(text: str, n_words: int) -> str:
    """The first `n_words` whitespace-separated words of `text`, cut on the
    original string so its line breaks and spacing are kept."""
    end = 0
    for i, match in enumerate(_WORD_RE.finditer(text)):
        if i == n_words:
            break
        end = match.end()
    return text[:end]


def flatten(text: str) -> str:
    """One paragraph: every run of whitespace that contains a line break
    becomes a single space."""
    return re.sub(r"[ \t]*\n\s*", " ", text).strip()


def single_paragraph(texts: list[str]) -> bool:
    return all("\n" not in t.strip() for t in texts)


def rate_at_or_above(actions: list[str], floor: str) -> float | None:
    if not actions:
        return None
    bar = _ACTIONS.index(floor)
    return sum(_ACTIONS.index(a) >= bar for a in actions) / len(actions)


def _profile(victim_id: str, n: int):
    from validation.adversarial.profiles import build_victim_profiles
    from validation.adversarial.report import HARNESS_SEED

    for p in build_victim_profiles(n_baselines=n, seed=HARNESS_SEED):
        if p.victim_id == victim_id:
            return p
    raise LookupError(f"no victim profile {victim_id!r} at N={n}")


def build_cells(report_rows: list[dict]) -> list:
    """One genuine_slice cell and one imitation_flat cell per imitation row
    of the G-A2 report."""
    from validation.adversarial.generators import LLMImitation
    from validation.adversarial.profiles import VictimProfile
    from validation.adversarial.report import Cell

    cells = []
    for row in report_rows:
        if row["kind"] != "llm_imitation":
            continue
        vid, n = row["victim_id"], row["n"]
        texts = [t for e, t in LLMImitation(vid).load_entries() if e.get("n_baselines") == n]
        if len(texts) != 1:
            raise ValueError(f"expected one imitation for {vid} at N={n}, got {len(texts)}")
        profile = _profile(vid, n)
        width = len(texts[0].split())
        slices = [cut_words(h, width) for h in profile.genuine_holdout]
        flat = flatten(texts[0]) if single_paragraph(profile.baselines) else texts[0]
        for kind, docs in (("genuine_slice", slices), ("imitation_flat", [flat])):
            cells.append(
                Cell(
                    corpus="controls",
                    kind=kind,
                    n=n,
                    attack="none",
                    profile=VictimProfile(
                        victim_id=vid,
                        baselines=list(profile.baselines),
                        genuine_holdout=[],
                        impostor_docs=docs,
                    ),
                )
            )
    return cells


def _collect(rows: list[dict], kind: str, side: str, victims: set | None = None) -> dict:
    """{n: {"scores": [...], "actions": [...], "victims": set}} for one row
    kind, reading `<side>_scores` / `<side>_actions`."""
    out: dict[int, dict] = {}
    for r in rows:
        if r["kind"] != kind or (victims is not None and r["victim_id"] not in victims[r["n"]]):
            continue
        slot = out.setdefault(r["n"], {"scores": [], "actions": [], "victims": set()})
        slot["scores"] += r[f"{side}_scores"]
        slot["actions"] += r[f"{side}_actions"]
        slot["victims"].add(r["victim_id"])
    return out


def summarize(report_rows: list[dict], control_rows: list[dict]) -> dict:
    from validation.calibration_gate import _ga_auroc, _ga_auroc_lower

    imitation = _collect(report_rows, "llm_imitation", "impostor")
    victims = {n: slot["victims"] for n, slot in imitation.items()}
    full = _collect(report_rows, "clean", "holdout", victims)
    sliced = _collect(control_rows, "genuine_slice", "impostor")
    flat = _collect(control_rows, "imitation_flat", "impostor")

    def compare(attack: dict, genuine: dict) -> dict:
        auc = _ga_auroc(attack["scores"], genuine["scores"])
        lower = None
        if auc is not None:
            lower = _ga_auroc_lower(auc, len(attack["scores"]), len(genuine["scores"]))
        return {
            "auroc": auc,
            "auroc_lower_95": lower,
            "n_attack": len(attack["scores"]),
            "n_genuine": len(genuine["scores"]),
        }

    out = {}
    for n in sorted(imitation):
        out[f"N={n}"] = {
            "victims": sorted(victims[n]),
            "schedule_conversation_plus": {
                "imitation": rate_at_or_above(imitation[n]["actions"], "schedule_conversation"),
                "imitation_flat": rate_at_or_above(flat[n]["actions"], "schedule_conversation"),
                "genuine_full": rate_at_or_above(full[n]["actions"], "schedule_conversation"),
                "genuine_slice": rate_at_or_above(sliced[n]["actions"], "schedule_conversation"),
            },
            "imitation_vs_genuine_full": compare(imitation[n], full[n]),
            "imitation_vs_genuine_slice": compare(imitation[n], sliced[n]),
            "imitation_flat_vs_genuine_slice": compare(flat[n], sliced[n]),
        }
    return out


def reproduction_check(report_rows: list[dict], cells: list, control_rows: list[dict]) -> dict:
    """An imitation_flat cell whose imitation was NOT flattened (its victim's
    baselines are paragraphed, so the doc still has line breaks) re-scores
    exactly the document the G-A2 report scored, against the same
    baselines. Its score must match the report's bit for bit; a mismatch
    means the control ran under different scoring code or flags, and its
    comparison with the report's numbers does not hold."""
    reported = {
        (r["victim_id"], r["n"]): r["impostor_scores"]
        for r in report_rows
        if r["kind"] == "llm_imitation"
    }
    checked, mismatched = 0, []
    for cell, row in zip(cells, control_rows, strict=True):
        if cell.kind != "imitation_flat" or "\n" not in cell.profile.impostor_docs[0]:
            continue
        checked += 1
        key = (cell.profile.victim_id, cell.n)
        if row["impostor_scores"] != reported[key]:
            mismatched.append(f"{key[0]} N={key[1]}")
    return {"checked": checked, "mismatched": mismatched}


def _git_sha() -> str | None:
    import subprocess

    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, check=True
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    return out.stdout.strip() or None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--report", type=Path, required=True, help="the G-A2 harness report")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--workers", type=int, default=None)
    args = parser.parse_args(argv)

    import time

    from validation.adversarial.report import LIVE_SCORING_ENV, default_workers, run_cells

    report = json.loads(args.report.read_text())
    cells = build_cells(report["rows"])
    workers = args.workers or default_workers()
    started = time.monotonic()
    control_rows = run_cells(cells, path="api", workers=workers)
    meta = {
        "git_sha": _git_sha(),
        "live_scoring_env": dict(LIVE_SCORING_ENV),
        "workers": workers,
        "runtime_seconds": round(time.monotonic() - started, 1),
        "reproduces_report": reproduction_check(report["rows"], cells, control_rows),
    }
    summary = summarize(report["rows"], control_rows)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(
        json.dumps(
            {"report": str(args.report), "meta": meta, "summary": summary, "rows": control_rows},
            indent=1,
            sort_keys=True,
            default=str,
        )
        + "\n"
    )
    print(json.dumps({"meta": meta, "summary": summary}, indent=2, sort_keys=True))
    if meta["reproduces_report"]["mismatched"]:
        print(
            "error: unflattened imitations did not reproduce the report's scores "
            f"({meta['reproduces_report']['mismatched']}); run this at the report's commit",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    from validation.benchmark.reproducibility import lock_environment

    lock_environment()
    sys.exit(main())
