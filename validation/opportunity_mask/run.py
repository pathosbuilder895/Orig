"""Before/after study for OPPORTUNITY_MASK on the committed corpus.

Question: when the new paper gave a share-type measurement no chance to occur
and the scorer stops comparing its placeholder, are honest writers flagged
less often, and are other writers still caught?

    python -m validation.opportunity_mask.run

Every trial is scored three ways on identical inputs:

  off      today's behaviour.
  on       unmeasured features leave the comparison (min_count = 1).
  control  the same NUMBER of features leaves the comparison, chosen at
           random from the measured ones. If "on" only helps as much as the
           control does, the gain is from dropping features, not from
           dropping the right ones.

Design, fixed before the first run
----------------------------------
* One author = one pseudo-student. The first 4 x B words of an author's text
  are 4 past papers of B words; the rest is cut into new papers of L words.
  No word is on both sides. No random number decides a split.
* Cells: B = 1200 with L in {300, 600, 1200} (a short new paper against
  longer past papers, the case the fault bites hardest), and B = L for 300
  and 600 as well: five cells.
* Genuine trial: an author's new paper against their own past papers (at
  most 10 per author per cell). Other-writer trial: the first 3 new papers
  of every other author against those same past papers.
* Decision bar: the product's own, recommendation.action at
  schedule_conversation or escalate, under ScoringConfig() defaults.

Criteria, fixed before the first run (pooled over all five cells)
----------------------------------------------------------------
  E  engagement   at least 10% of genuine trials have one or more
                  unmeasured features, and at least 200 genuine trials.
                  Otherwise the verdict is UNINFORMATIVE, never a pass.
  H  honest       genuine flag rate under "on" is not higher than under off.
  C  catch        other-writer catch rate under "on" drops by at most 2
                  points, and AUC drops by at most 0.005.

PASS needs E, H and C. A pass licenses a shadow soak only. It is not evidence
about students: these are published authors and synthetic seminary papers,
and the comparison is paired on one corpus with no held-out lock. The
min_count sweep at the end is exploratory and must not be used to pick a
threshold (that would turn this corpus into a tuning set).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

import numpy as np

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT))

from original.constants import FEATURE_DIM  # noqa: E402
from original.features.opportunity import (  # noqa: E402
    OPPORTUNITY_FEATURES,
    mask_from_counts,
    opportunity_counts,
)
from original.features.pipeline import extract_features, feature_vector  # noqa: E402
from original.quantum.scoring import ScoringConfig  # noqa: E402
from original.quantum.scoring import score as quantum_score  # noqa: E402
from original.quantum.state import BaselineSample, StudentState  # noqa: E402
from validation.short_regime.stats import auc  # noqa: E402

AUTHORS = [
    "burke",
    "douglass",
    "lincoln",
    "paine",
    "fed_hamilton",
    "fed_madison",
    "fed_jay",
    *[f"seminary_{i:02d}" for i in range(6, 12)],
]
CELLS = [(1200, 300), (1200, 600), (1200, 1200), (300, 300), (600, 600)]
N_BASELINE = 4
MAX_GENUINE = 10
IMPOSTOR_PER_PAIR = 3
FLAGGED = {"schedule_conversation", "escalate"}
SWEEP = (1, 2, 3, 5, 10)

MIN_ENGAGEMENT = 0.10
MIN_GENUINE = 200
MAX_CATCH_DROP = 0.02
MAX_AUC_DROP = 0.005

_CACHE: dict[str, tuple[np.ndarray, dict, dict]] = {}


def _features(text: str) -> tuple[np.ndarray, dict, dict]:
    key = hashlib.sha256(text.encode()).hexdigest()
    if key not in _CACHE:
        _CACHE[key] = (feature_vector(text), extract_features(text), opportunity_counts(text))
    return _CACHE[key]


def _words(corpus_dir: Path, author: str) -> list[str]:
    files = sorted(corpus_dir.glob(f"{author}_*.txt"))
    return "\n".join(f.read_text(encoding="utf-8") for f in files).split()


def split_author(words: list[str], base_len: int, probe_len: int) -> tuple[list[str], list[str]]:
    """(past papers, new papers): disjoint, in reading order, no randomness."""
    cut = N_BASELINE * base_len
    baseline = [" ".join(words[i : i + base_len]) for i in range(0, cut, base_len)]
    rest = words[cut:]
    probes = [
        " ".join(rest[i : i + probe_len]) for i in range(0, len(rest) - probe_len + 1, probe_len)
    ]
    if len(probes) > MAX_GENUINE:  # spread evenly through the remaining text
        step = len(probes) / MAX_GENUINE
        probes = [probes[int(k * step)] for k in range(MAX_GENUINE)]
    return baseline, probes


def _state(author: str, baseline: list[str]) -> StudentState:
    state = StudentState(student_id=f"opp:{author}")
    for i, text in enumerate(baseline):
        state.add_sample(
            BaselineSample(
                text=text,
                vector=_features(text)[0],
                provenance="verified",
                auth_weight=1.0,
                assignment=f"a{i}",
            )
        )
    return state


def _control_mask(state: StudentState, real_mask: np.ndarray, seed: str) -> np.ndarray:
    """As many features as "on" drops, drawn from the ones that were measured."""
    active = state.active_feature_mask
    k = int((real_mask & active).sum())
    pool = np.flatnonzero(active & ~real_mask)
    mask = np.zeros(FEATURE_DIM, dtype=bool)
    if k and len(pool) >= k:
        rng = np.random.default_rng(int(hashlib.sha256(seed.encode()).hexdigest()[:8], 16))
        mask[rng.choice(pool, size=k, replace=False)] = True
    return mask


def _one(state: StudentState, text: str, mode: str, mask: np.ndarray | None, n_tokens: int):
    vec, fd, _ = _features(text)
    res = quantum_score(
        state=state,
        submission_vector=vec,
        feature_dict=fd,
        n_tokens=n_tokens,
        scoring_config=ScoringConfig(opportunity_mask=mode),
        unmeasured_mask=mask,
    )
    return float(res.authorship.deviation_score), res.recommendation.action in FLAGGED, res


def score_trial(state: StudentState, text: str, tag: str, n_tokens: int) -> dict:
    counts = _features(text)[2]
    mask = mask_from_counts(counts)
    off_d, off_f, _ = _one(state, text, "off", None, n_tokens)
    on_d, on_f, on_res = _one(state, text, "on", mask, n_tokens)
    ctl_d, ctl_f, _ = _one(state, text, "on", _control_mask(state, mask, tag), n_tokens)
    unmeasured = on_res.unmeasured_features or []
    if not unmeasured and (on_d, on_f) != (off_d, off_f):
        raise AssertionError(f"{tag}: nothing unmeasured, yet the score moved")
    sweep = {
        m: _one(state, text, "on", mask_from_counts(counts, m), n_tokens)[:2] for m in SWEEP[1:]
    }
    return {
        "off": off_d,
        "on": on_d,
        "control": ctl_d,
        "off_flag": off_f,
        "on_flag": on_f,
        "control_flag": ctl_f,
        "unmeasured": unmeasured,
        "sweep": {str(m): [d, f] for m, (d, f) in sweep.items()},
    }


def run_cell(corpus_dir: Path, base_len: int, probe_len: int) -> dict:
    material = {}
    for author in AUTHORS:
        words = _words(corpus_dir, author)
        if len(words) < N_BASELINE * base_len + IMPOSTOR_PER_PAIR * probe_len:
            continue
        material[author] = split_author(words, base_len, probe_len)
    rows = []
    for author, (baseline, probes) in material.items():
        state = _state(author, baseline)
        for j, text in enumerate(probes):
            row = score_trial(state, text, f"g:{author}:{j}", probe_len)
            rows.append({"kind": "genuine", "claimed": author, "writer": author, **row})
        for other, (_b, other_probes) in material.items():
            if other == author:
                continue
            for j, text in enumerate(other_probes[:IMPOSTOR_PER_PAIR]):
                row = score_trial(state, text, f"i:{other}->{author}:{j}", probe_len)
                rows.append({"kind": "impostor", "claimed": author, "writer": other, **row})
    return {"baseline_words": base_len, "probe_words": probe_len, "rows": rows}


def _rate(rows: list[dict], key: str) -> float:
    return float(np.mean([r[key] for r in rows])) if rows else float("nan")


def _auc(rows: list[dict], key: str) -> float:
    g = np.array([r[key] for r in rows if r["kind"] == "genuine"])
    i = np.array([r[key] for r in rows if r["kind"] == "impostor"])
    return auc(g, i) if g.size and i.size else float("nan")


def _mcnemar(rows: list[dict], a: str, b: str) -> dict:
    """Discordant decisions between two arms on the same trials."""
    return {
        "flag_removed": int(sum(r[a] and not r[b] for r in rows)),
        "flag_added": int(sum(r[b] and not r[a] for r in rows)),
    }


def _delta_auc_ci(rows: list[dict], n_boot: int = 500, seed: int = 0) -> list[float]:
    """Paired bootstrap of AUC(on) - AUC(off), resampling CLAIMED AUTHORS.

    Trials against one student's past papers share that student's baseline,
    so they are not independent; resampling single trials would understate
    the interval.
    """
    by_author: dict[str, list[dict]] = {}
    for r in rows:
        by_author.setdefault(r["claimed"], []).append(r)
    names = sorted(by_author)
    rng = np.random.default_rng(seed)
    deltas = []
    for _ in range(n_boot):
        sample = [r for n in rng.choice(names, size=len(names)) for r in by_author[n]]
        d = _auc(sample, "on") - _auc(sample, "off")
        if np.isfinite(d):
            deltas.append(d)
    return [float(np.percentile(deltas, 2.5)), float(np.percentile(deltas, 97.5))]


def summarise(rows: list[dict]) -> dict:
    gen = [r for r in rows if r["kind"] == "genuine"]
    imp = [r for r in rows if r["kind"] == "impostor"]
    per_feature = {
        code: round(float(np.mean([code in r["unmeasured"] for r in gen])), 4)
        for code in OPPORTUNITY_FEATURES
    }
    out = {
        "n_genuine": len(gen),
        "n_impostor": len(imp),
        "n_claimed_authors": len({r["claimed"] for r in rows}),
        "genuine_engagement": round(float(np.mean([bool(r["unmeasured"]) for r in gen])), 4),
        "mean_unmeasured_genuine": round(float(np.mean([len(r["unmeasured"]) for r in gen])), 3),
        "unmeasured_rate_by_feature": per_feature,
        "delta_auc_ci95": [round(x, 4) for x in _delta_auc_ci(rows)],
        "genuine_discordant": _mcnemar(gen, "off_flag", "on_flag"),
        "impostor_discordant": _mcnemar(imp, "off_flag", "on_flag"),
    }
    for arm in ("off", "on", "control"):
        out[arm] = {
            "genuine_flag_rate": round(_rate(gen, f"{arm}_flag"), 4),
            "impostor_catch_rate": round(_rate(imp, f"{arm}_flag"), 4),
            "auc": round(_auc(rows, arm), 4),
            "mean_genuine_deviation": round(_rate(gen, arm), 4),
            "mean_impostor_deviation": round(_rate(imp, arm), 4),
        }
    out["exploratory_min_count_sweep"] = {
        str(m): {
            "genuine_flag_rate": round(float(np.mean([r["sweep"][str(m)][1] for r in gen])), 4),
            "impostor_catch_rate": round(float(np.mean([r["sweep"][str(m)][1] for r in imp])), 4),
        }
        for m in SWEEP[1:]
    }
    return out


def verdict(summary: dict) -> dict:
    """Three-valued, like validation/calibration_gate.py: an unreachable
    criterion is uninformative, never a pass."""
    off, on = summary["off"], summary["on"]
    engaged = (
        summary["genuine_engagement"] >= MIN_ENGAGEMENT and summary["n_genuine"] >= MIN_GENUINE
    )
    honest = on["genuine_flag_rate"] <= off["genuine_flag_rate"]
    catch = (
        off["impostor_catch_rate"] - on["impostor_catch_rate"] <= MAX_CATCH_DROP
        and off["auc"] - on["auc"] <= MAX_AUC_DROP
    )
    if not engaged:
        result = "uninformative"
    elif honest and catch:
        result = "pass"
    else:
        result = "fail"
    return {"verdict": result, "E_engagement": engaged, "H_honest": honest, "C_catch": catch}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=None, help="write the JSON report here")
    args = ap.parse_args(argv)
    corpus_dir = _ROOT / "validation" / "corpus"

    cells, pooled = [], []
    for base_len, probe_len in CELLS:
        t0 = time.perf_counter()
        cell = run_cell(corpus_dir, base_len, probe_len)
        s = summarise(cell["rows"])
        pooled += cell["rows"]
        cells.append({"baseline_words": base_len, "probe_words": probe_len, **s})
        off, on, ctl = s["off"], s["on"], s["control"]
        print(
            f"past {base_len:>4}w / new {probe_len:>4}w  "
            f"n={s['n_genuine']:>3}g/{s['n_impostor']:>4}i  "
            f"engaged={s['genuine_engagement']:.0%}  "
            f"honest flagged {off['genuine_flag_rate']:.1%} -> {on['genuine_flag_rate']:.1%} "
            f"(control {ctl['genuine_flag_rate']:.1%})  "
            f"caught {off['impostor_catch_rate']:.1%} -> {on['impostor_catch_rate']:.1%}  "
            f"AUC {off['auc']:.3f} -> {on['auc']:.3f}  "
            f"[{time.perf_counter() - t0:.0f}s]",
            file=sys.stderr,
        )
    total = summarise(pooled)
    v = verdict(total)
    print(f"\npooled: {json.dumps({k: total[k] for k in ('off', 'on', 'control')}, indent=1)}")
    print(f"delta AUC 95% CI (by author): {total['delta_auc_ci95']}")
    print(f"honest discordant: {total['genuine_discordant']}")
    print(f"VERDICT: {v['verdict'].upper()}  {v}")

    report = {"cells": cells, "pooled": total, "verdict": v}
    if args.out:
        Path(args.out).write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
