"""Before/after study for LENGTH_MATCHED_BASELINE on the committed corpus.

Question: when a new paper is much shorter than the student's past papers
and the past papers are re-measured in pieces of the new paper's length, are
honest writers flagged less often, and can other writers still be told apart?

    python -m validation.length_match.run --out validation/length_match/report.json

Every trial is scored three ways on identical inputs:

  off   today's behaviour: past papers measured whole.
  on    LENGTH_MATCHED_BASELINE=on, through score() itself.
  wide  the simpler alternative, study-only: past papers stay whole and every
        feature's spread is widened by sqrt(past length / new length), the
        factor pure sampling noise would call for. It corrects the spread
        and not the mean, so it shows how much of the gain needs the pieces.

Design, fixed before the first run
----------------------------------
* Same pseudo-students and the same split as validation/opportunity_mask/:
  the first 4 x B words of an author are 4 past papers of B words, the rest
  is cut into new papers of L words. No word is on both sides, and no random
  number decides a split.
* Engaged cells (B at least 2 x L): (1200, 300), (1200, 600), (600, 300).
  Reference cell (300, 300): nothing is long enough to cut, so "on" must
  equal "off" on every trial (asserted), and its rates are the yardstick for
  what a like-for-like comparison at 300 words looks like.
* Genuine and other-writer trials, and the decision bar (recommendation
  .action at schedule_conversation or escalate, ScoringConfig() defaults),
  are as in validation/opportunity_mask/.

Criteria, fixed before the first run (pooled over the three engaged cells)
--------------------------------------------------------------------------
  E   engagement  the reference was length-matched on at least 90% of
                  genuine trials, and there are at least 200 of them.
                  Otherwise the verdict is UNINFORMATIVE, never a pass.
  H   honest      the genuine flag rate under "on" is at least 10 points
                  below off, and the 95% interval of that difference,
                  resampled by claimed author, excludes zero.
  C1  separation  AUC under "on" is no more than 0.01 below off.
  C2  catch       "off" catches other writers at these lengths largely by
                  flagging nearly everyone, so the raw catch rates are not
                  comparable. Move off's bar until it flags honest papers at
                  the rate "on" does; "on" must catch no more than 5 points
                  fewer other writers than off does at that bar.

PASS needs E, H, C1 and C2. A pass licenses a shadow soak only. It is not
evidence about students: these are published authors and synthetic seminary
papers cut from continuous text (pieces of one work stand in for separate
papers), on one corpus with no held-out lock. "wide" is reported and decides
nothing.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import multiprocessing as mp
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np

_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_ROOT))

from original.constants import ACTION_THRESHOLDS  # noqa: E402
from original.features.pipeline import extract_features, feature_vector  # noqa: E402
from original.quantum.length_match import (  # noqa: E402
    build_length_matched_state,
    split_into_pieces,
)
from original.quantum.scoring import ScoringConfig  # noqa: E402
from original.quantum.scoring import score as quantum_score  # noqa: E402
from original.quantum.state import BaselineSample, StudentState  # noqa: E402
from validation.opportunity_mask.run import (  # noqa: E402
    AUTHORS,
    IMPOSTOR_PER_PAIR,
    N_BASELINE,
    _words,
    split_author,
)
from validation.short_regime.stats import auc  # noqa: E402

ENGAGED_CELLS = [(1200, 300), (1200, 600), (600, 300)]
REFERENCE_CELLS = [(300, 300)]
ARMS = ("off", "on", "wide")

MIN_ENGAGEMENT = 0.90
MIN_GENUINE = 200
MIN_FLAG_DROP = 0.10
MAX_AUC_DROP = 0.01
MAX_CATCH_DROP = 0.05

_CACHE: dict[str, tuple[np.ndarray, dict]] = {}


def _key(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _extract(text: str) -> tuple[str, np.ndarray, dict]:
    return _key(text), feature_vector(text), extract_features(text)


def _features(text: str) -> tuple[np.ndarray, dict]:
    k = _key(text)
    if k not in _CACHE:
        _, vec, fd = _extract(text)
        _CACHE[k] = (vec, fd)
    return _CACHE[k]


def _vectorise(text: str) -> np.ndarray:
    return _features(text)[0]


@dataclass
class _WideState(StudentState):
    """Study-only: whole past papers, spread widened for a shorter paper."""

    widen: float = 1.0

    @property
    def baseline_std(self) -> np.ndarray:
        return StudentState.baseline_std.fget(self) * self.widen


def _state(author: str, baseline: list[str], widen: float | None = None) -> StudentState:
    cls_kwargs = {"student_id": f"len:{author}"}
    state = StudentState(**cls_kwargs) if widen is None else _WideState(**cls_kwargs, widen=widen)
    for i, text in enumerate(baseline):
        state.add_sample(
            BaselineSample(
                text=text,
                vector=_vectorise(text),
                provenance="verified",
                auth_weight=1.0,
                assignment=f"a{i}",
            )
        )
    return state


def _score(state: StudentState, text: str, n_tokens: int, mode: str = "off", matched=None):
    vec, fd = _features(text)
    res = quantum_score(
        state=state,
        submission_vector=vec,
        feature_dict=fd,
        n_tokens=n_tokens,
        scoring_config=ScoringConfig(length_matched_baseline=mode),
        length_matched_state=matched,
    )
    # Flagged is read from deviation against the PRODUCT's cut points, so the
    # "on" arm keeps measuring the matched reference alone. Since 2026-11-19
    # the code reads "on" against LENGTH_MATCHED_ACTION_THRESHOLDS, so the
    # recommended action would mix the reference with the new cut points
    # (those are studied in validation/length_match_thresholds/). Under these
    # defaults the two agree for "off" and "wide".
    d = float(res.authorship.deviation_score)
    return d, d >= ACTION_THRESHOLDS["schedule_conversation"][0], res


def _material(corpus_dir: Path, base_len: int, probe_len: int) -> dict:
    out = {}
    for author in AUTHORS:
        words = _words(corpus_dir, author)
        if len(words) < N_BASELINE * base_len + IMPOSTOR_PER_PAIR * probe_len:
            continue
        out[author] = split_author(words, base_len, probe_len)
    return out


def _all_texts(material: dict, probe_len: int) -> list[str]:
    texts = []
    for baseline, probes in material.values():
        texts += baseline + probes
        for paper in baseline:
            pieces = split_into_pieces(paper, probe_len)
            if len(pieces) > 1:
                texts += pieces
    return texts


def warm_cache(texts: list[str], jobs: int) -> None:
    todo = list({_key(t): t for t in texts if _key(t) not in _CACHE}.values())
    if not todo:
        return
    if jobs <= 1:
        results = map(_extract, todo)
    else:
        with mp.get_context("spawn").Pool(jobs) as pool:
            results = pool.map(_extract, todo, chunksize=4)
    for k, vec, fd in results:
        _CACHE[k] = (vec, fd)


def run_cell(material: dict, base_len: int, probe_len: int, engaged: bool) -> list[dict]:
    rows = []
    for author, (baseline, probes) in material.items():
        state = _state(author, baseline)
        wide = _state(author, baseline, widen=math.sqrt(base_len / probe_len))
        matched = build_length_matched_state(state, probe_len, _vectorise)
        if (matched is not None) != engaged:
            raise AssertionError(f"{author} {base_len}/{probe_len}: engagement is not as designed")
        trials = [("genuine", author, j, t) for j, t in enumerate(probes)]
        for other, (_b, other_probes) in material.items():
            if other != author:
                trials += [
                    ("impostor", other, j, t)
                    for j, t in enumerate(other_probes[:IMPOSTOR_PER_PAIR])
                ]
        for kind, writer, _j, text in trials:
            off_d, off_f, _ = _score(state, text, probe_len)
            on_d, on_f, on_res = _score(state, text, probe_len, "on", matched)
            wide_d, wide_f, _ = _score(wide, text, probe_len)
            if not engaged and (on_d, on_f) != (off_d, off_f):
                raise AssertionError(f"{author}: nothing to cut, yet the score moved")
            rows.append(
                {
                    "kind": kind,
                    "claimed": author,
                    "writer": writer,
                    "cell": f"{base_len}/{probe_len}",
                    "applied": bool(on_res.length_match_applied),
                    "off": off_d,
                    "on": on_d,
                    "wide": wide_d,
                    "off_flag": off_f,
                    "on_flag": on_f,
                    "wide_flag": wide_f,
                }
            )
    return rows


def _split(rows: list[dict]) -> tuple[list[dict], list[dict]]:
    return [r for r in rows if r["kind"] == "genuine"], [r for r in rows if r["kind"] == "impostor"]


def _rate(rows: list[dict], key: str) -> float:
    return float(np.mean([r[key] for r in rows])) if rows else float("nan")


def _auc(rows: list[dict], key: str) -> float:
    gen, imp = _split(rows)
    if not gen or not imp:
        return float("nan")
    return auc(np.array([r[key] for r in gen]), np.array([r[key] for r in imp]))


def catch_at_matched_bar(rows: list[dict], arm: str, target_flag_rate: float) -> float:
    """Catch rate of ``arm`` when its bar is moved until it flags honest
    papers at ``target_flag_rate`` (ties resolved toward flagging fewer)."""
    gen, imp = _split(rows)
    scores = np.sort(np.array([r[arm] for r in gen]))[::-1]
    k = int(math.floor(target_flag_rate * len(scores)))
    bar = scores[k - 1] if k > 0 else float("inf")
    return float(np.mean([r[arm] >= bar for r in imp]))


def _by_author_ci(rows: list[dict], stat, n_boot: int = 1000, seed: int = 0) -> list[float]:
    """95% interval of ``stat(rows)``, resampling CLAIMED AUTHORS: trials
    against one student's past papers share that student's reference."""
    by_author: dict[str, list[dict]] = {}
    for r in rows:
        by_author.setdefault(r["claimed"], []).append(r)
    names = sorted(by_author)
    rng = np.random.default_rng(seed)
    vals = []
    for _ in range(n_boot):
        sample = [r for n in rng.choice(names, size=len(names)) for r in by_author[n]]
        v = stat(sample)
        if np.isfinite(v):
            vals.append(v)
    return [round(float(np.percentile(vals, 2.5)), 4), round(float(np.percentile(vals, 97.5)), 4)]


def _flag_drop(rows: list[dict]) -> float:
    gen, _ = _split(rows)
    return _rate(gen, "off_flag") - _rate(gen, "on_flag")


def summarise(rows: list[dict]) -> dict:
    gen, imp = _split(rows)
    out = {
        "n_genuine": len(gen),
        "n_impostor": len(imp),
        "n_claimed_authors": len({r["claimed"] for r in rows}),
        "genuine_engagement": round(_rate(gen, "applied"), 4),
    }
    for arm in ARMS:
        out[arm] = {
            "genuine_flag_rate": round(_rate(gen, f"{arm}_flag"), 4),
            "impostor_catch_rate": round(_rate(imp, f"{arm}_flag"), 4),
            "auc": round(_auc(rows, arm), 4),
            "mean_genuine_deviation": round(_rate(gen, arm), 4),
            "mean_impostor_deviation": round(_rate(imp, arm), 4),
        }
    on_rate = out["on"]["genuine_flag_rate"]
    out["off_catch_at_on_flag_rate"] = round(catch_at_matched_bar(rows, "off", on_rate), 4)
    out["wide_catch_at_on_flag_rate"] = round(catch_at_matched_bar(rows, "wide", on_rate), 4)
    # Added after the first run, so exploratory: it decides nothing. The
    # product's bar was set on whole-paper references; this reads each arm at
    # a few fixed honest flag rates instead, 0.13 being the (300, 300) cell's.
    out["exploratory_catch_at_flag_rate"] = {
        arm: {str(t): round(catch_at_matched_bar(rows, arm, t), 4) for t in (0.05, 0.10, 0.13)}
        for arm in ARMS
    }
    out["flag_drop"] = round(_flag_drop(rows), 4)
    out["flag_drop_ci95"] = _by_author_ci(rows, _flag_drop)
    out["delta_auc_ci95"] = _by_author_ci(rows, lambda s: _auc(s, "on") - _auc(s, "off"))
    return out


def verdict(summary: dict) -> dict:
    """Three-valued, like validation/calibration_gate.py: an unreachable
    criterion is uninformative, never a pass."""
    off, on = summary["off"], summary["on"]
    engaged = (
        summary["genuine_engagement"] >= MIN_ENGAGEMENT and summary["n_genuine"] >= MIN_GENUINE
    )
    honest = summary["flag_drop"] >= MIN_FLAG_DROP and summary["flag_drop_ci95"][0] > 0
    separation = off["auc"] - on["auc"] <= MAX_AUC_DROP
    catch = summary["off_catch_at_on_flag_rate"] - on["impostor_catch_rate"] <= MAX_CATCH_DROP
    if not engaged:
        result = "uninformative"
    elif honest and separation and catch:
        result = "pass"
    else:
        result = "fail"
    return {
        "verdict": result,
        "E_engagement": engaged,
        "H_honest": honest,
        "C1_separation": separation,
        "C2_catch": catch,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=None, help="write the JSON report here")
    ap.add_argument("--jobs", type=int, default=max(1, (mp.cpu_count() or 2) - 2))
    args = ap.parse_args(argv)
    corpus_dir = _ROOT / "validation" / "corpus"

    cells, pooled = [], []
    for base_len, probe_len in ENGAGED_CELLS + REFERENCE_CELLS:
        engaged = (base_len, probe_len) in ENGAGED_CELLS
        t0 = time.perf_counter()
        material = _material(corpus_dir, base_len, probe_len)
        warm_cache(_all_texts(material, probe_len), args.jobs)
        rows = run_cell(material, base_len, probe_len, engaged)
        s = summarise(rows)
        if engaged:
            pooled += rows
        cells.append(
            {"baseline_words": base_len, "probe_words": probe_len, "engaged": engaged, **s}
        )
        print(
            f"past {base_len:>4}w / new {probe_len:>4}w  "
            f"n={s['n_genuine']:>3}g/{s['n_impostor']:>4}i  "
            + "  ".join(
                f"{arm}: honest {s[arm]['genuine_flag_rate']:.1%} caught "
                f"{s[arm]['impostor_catch_rate']:.1%} AUC {s[arm]['auc']:.3f}"
                for arm in ARMS
            )
            + f"  [{time.perf_counter() - t0:.0f}s]",
            file=sys.stderr,
        )
    total = summarise(pooled)
    v = verdict(total)
    print(f"\npooled (engaged cells): {json.dumps(total, indent=1)}")
    print(f"VERDICT: {v['verdict'].upper()}  {v}")
    if args.out:
        report = {"cells": cells, "pooled": total, "verdict": v}
        Path(args.out).write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
