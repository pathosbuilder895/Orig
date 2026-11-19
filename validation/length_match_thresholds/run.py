"""Action cut points for LENGTH_MATCHED_BASELINE=on, set on one partition and
tested once on another.

PR #334's study (validation/length_match/) found that ``on`` stops flagging
honest short papers (49.7% to 3.5%) and separates writers slightly better, but
at the product's fixed cut points (0.40 / 0.60 / 0.75, set for narrow
whole-paper references) it also stops catching other writers (81.5% to 16.4%).
It said the cut points must be set for the matched reference, on a corpus
other than validation/corpus/, and tested on real separate papers per author.
This script does that.

    python -m validation.length_match_thresholds.run derive
    python -m validation.length_match_thresholds.run holdout   # once

Corpus: validation/scholarly/, ``humanities`` collection (single-author
journal articles, mostly theology and religion, at least 6 separate papers
per author; texts restored into the git-ignored cache with
``python -m validation.scholarly.fetch --collection humanities --restore``).
Author-disjoint partitions are fixed by a hash of the author id:

  derive   ``calibration`` partition. Cut points are chosen here.
  holdout  ``locked_test`` partition, opened once under STUDY_ID through
           validation/scholarly/loader.py, which appends the opening to
           LOCKED_OPENINGS.tsv. This script refuses to open it again.

Design, fixed before the first run
----------------------------------
* Trials come from ``loader.load_trials``: per author 4 past papers and 2 new
  papers, each a different article, cut to a fixed length; other-writer
  probes are 5 other authors' new papers. Cells (past words, new words):
  (1200, 300), (1500, 450), (1200, 600). Every cell has past papers at least
  twice the new paper, so the matched reference can engage.
* Every trial is scored ``off`` and ``on`` through quantum.scoring.score()
  with ScoringConfig() defaults otherwise (NULL_MODEL none, typicality off:
  the pilot's deviation-only action path), on identical inputs.
* The action is read from deviation_score against a set of cut points, as
  the pilot's deviation-only branch does (``lo <= d < hi``). A trial is
  flagged at "worth a conversation" or higher. The share of trials whose
  ``recommendation.action`` disagrees with the product cut points' band is
  reported; above 1% the run is uninformative (the band is then not what the
  product shows).
* sentence-transformers is blocked, as in the pilot's lockfile, so Tier 10 and
  the tension arc use the fallbacks the pilot runs.

Cut points, chosen on ``calibration`` (rules fixed before the first run)
-----------------------------------------------------------------------
Over the pooled honest trials where the match engaged, each cut point is the
smallest value t on a 0.001 grid whose honest share at or above t has a 95%
Wilson upper bound at most:

  monitor                0.20
  schedule_conversation  0.05
  escalate               0.02

They must come out strictly increasing; otherwise the derivation FAILS and
nothing is tested.

Hold-out criteria (``locked_test``, fixed before the first run)
--------------------------------------------------------------
  E   engagement  at least 30 authors and 200 honest trials, the match engaged
                  on at least 90% of honest trials, and action agreement
                  above 99%. Otherwise UNINFORMATIVE, never a pass.
  H1  honest      honest trials flagged at "worth a conversation" or higher
                  under ``on`` with the new cut points: the 95% interval,
                  resampled by author, has its upper end at most 0.10.
  H2  escalate    the same for "very differently": upper end at most 0.05.
  C1  separation  AUC under ``on`` is no more than 0.01 below ``off``.
  C2  catch       move ``off``'s bar until it flags honest papers at the rate
                  ``on`` does with the new cut points; ``on`` must catch at
                  least as many other writers as ``off`` does at that bar,
                  minus 2 points.

PASS needs E, H1, H2, C1 and C2. A pass supports wiring the cut points behind
the existing flag and a shadow soak; it is not evidence about students. These
are published scholars' journal articles, not student papers.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import multiprocessing as mp
import sys
import time
from pathlib import Path

# The pilot's lockfile leaves sentence-transformers out; scoring must use the
# same fallbacks. Set before anything imports the feature pipeline, and in
# every spawned worker (they import this module).
sys.modules.setdefault("sentence_transformers", None)

import numpy as np  # noqa: E402

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
from validation.length_match.run import _by_author_ci, catch_at_matched_bar  # noqa: E402
from validation.power import wilson_interval  # noqa: E402
from validation.scholarly import loader  # noqa: E402
from validation.short_regime.stats import auc  # noqa: E402

HERE = Path(__file__).resolve().parent
DERIVED = HERE / "derived_cut_points.json"
STUDY_ID = "length-match-thresholds-2026-11-19"
COLLECTION = "humanities"
CELLS = [(1200, 300), (1500, 450), (1200, 600)]
N_PAST, N_NEW, N_PROBES = 4, 2, 5
SEED = 7

TARGETS = {"monitor": 0.20, "schedule_conversation": 0.05, "escalate": 0.02}
FLAG_ACTIONS = ("schedule_conversation", "escalate")

MIN_AUTHORS = 30
MIN_HONEST = 200
MIN_ENGAGEMENT = 0.90
MIN_AGREEMENT = 0.99
MAX_FLAG_UPPER = 0.10
MAX_ESCALATE_UPPER = 0.05
MAX_AUC_DROP = 0.01
MAX_CATCH_DROP = 0.02

_CACHE: dict[str, tuple[np.ndarray, dict]] = {}


# ── features ────────────────────────────────────────────────────────────────


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


# ── bands ───────────────────────────────────────────────────────────────────


def product_cut_points() -> dict[str, float]:
    return {a: ACTION_THRESHOLDS[a][0] for a in TARGETS}


def band(d: float, cuts: dict[str, float]) -> str:
    """Deviation-only action, ``lo <= d < hi`` as in scoring._recommend."""
    if d >= cuts["escalate"]:
        return "escalate"
    if d >= cuts["schedule_conversation"]:
        return "schedule_conversation"
    if d >= cuts["monitor"]:
        return "monitor"
    return "no_action"


# ── trials ──────────────────────────────────────────────────────────────────


def _state(author: str, baseline: list[str]) -> StudentState:
    state = StudentState(student_id=f"lmt:{author}")
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


def _score(state, text: str, n_words: int, mode: str, matched=None):
    vec, fd = _features(text)
    res = quantum_score(
        state=state,
        submission_vector=vec,
        feature_dict=fd,
        n_tokens=n_words,
        scoring_config=ScoringConfig(length_matched_baseline=mode),
        length_matched_state=matched,
    )
    return float(res.authorship.deviation_score), res


def load_cell(partition: str, past_words: int, new_words: int, study: str | None):
    return loader.load_trials(
        COLLECTION,
        partition,
        n_past=N_PAST,
        n_new=N_NEW,
        past_words=past_words,
        new_words=new_words,
        n_probes=N_PROBES,
        seed=SEED,
        allow_locked_for=study,
    )


def cell_texts(trials, new_words: int) -> list[str]:
    texts = []
    for t in trials:
        texts += t.baseline + t.honest + t.probes
        for paper in t.baseline:
            pieces = split_into_pieces(paper, new_words)
            if len(pieces) > 1:
                texts += pieces
    return texts


def run_cell(trials, past_words: int, new_words: int) -> list[dict]:
    rows = []
    product = product_cut_points()
    for t in trials:
        state = _state(t.student_id, t.baseline)
        matched = build_length_matched_state(state, new_words, _vectorise)
        cases = [("genuine", t.student_id, x) for x in t.honest]
        cases += [("impostor", w, x) for w, x in zip(t.probe_sources, t.probes, strict=True)]
        for kind, writer, text in cases:
            off_d, off_res = _score(state, text, new_words, "off")
            on_d, on_res = _score(state, text, new_words, "on", matched)
            rows.append(
                {
                    "kind": kind,
                    "claimed": t.student_id,
                    "writer": writer,
                    "cell": f"{past_words}/{new_words}",
                    "applied": bool(on_res.length_match_applied),
                    "off": off_d,
                    "on": on_d,
                    "off_action": off_res.recommendation.action,
                    "on_action": on_res.recommendation.action,
                    "agree": band(off_d, product) == off_res.recommendation.action
                    and band(on_d, product) == on_res.recommendation.action,
                }
            )
    return rows


def collect(partition: str, jobs: int, study: str | None = None) -> tuple[list[dict], dict]:
    rows, skipped = [], {}
    for past_words, new_words in CELLS:
        t0 = time.perf_counter()
        ts = load_cell(partition, past_words, new_words, study)
        # The loader asks for the study id on EVERY load of locked_test and
        # logs each one, so one hold-out run writes one line per cell.
        skipped[f"{past_words}/{new_words}"] = ts.skipped
        warm_cache(cell_texts(ts.trials, new_words), jobs)
        cell_rows = run_cell(ts.trials, past_words, new_words)
        rows += cell_rows
        print(
            f"{partition} past {past_words}w / new {new_words}w: {len(ts.trials)} authors, "
            f"{len(cell_rows)} trials, {len(ts.skipped)} skipped "
            f"[{time.perf_counter() - t0:.0f}s]",
            file=sys.stderr,
        )
    return rows, skipped


# ── statistics ──────────────────────────────────────────────────────────────


def _split(rows):
    return [r for r in rows if r["kind"] == "genuine"], [r for r in rows if r["kind"] == "impostor"]


def derive_cut_points(rows: list[dict]) -> dict[str, float | None]:
    honest = np.array([r["on"] for r in _split(rows)[0] if r["applied"]])
    n = len(honest)
    out: dict[str, float | None] = {}
    for action, target in TARGETS.items():
        chosen = None
        for t in np.round(np.arange(0.0, 1.0005, 0.001), 3):
            if wilson_interval(int((honest >= t).sum()), n)[1] <= target:
                chosen = float(t)
                break
        out[action] = chosen
    return out


def _flag_rate(rows, arm: str, cuts, actions=FLAG_ACTIONS) -> float:
    return float(np.mean([band(r[arm], cuts) in actions for r in rows])) if rows else float("nan")


def _auc(gen, imp, arm: str) -> float:
    return round(auc(np.array([r[arm] for r in gen]), np.array([r[arm] for r in imp])), 4)


def summarise(rows: list[dict], cuts: dict[str, float]) -> dict:
    gen, imp = _split(rows)
    product = product_cut_points()

    def arm(name, c):
        return {
            "honest_flagged": round(_flag_rate(gen, name, c), 4),
            "honest_escalate": round(_flag_rate(gen, name, c, ("escalate",)), 4),
            "honest_monitor_or_higher": round(
                _flag_rate(gen, name, c, ("monitor",) + FLAG_ACTIONS), 4
            ),
            "other_writers_caught": round(_flag_rate(imp, name, c), 4),
        }

    on_rate = _flag_rate(gen, "on", cuts)
    return {
        "n_honest": len(gen),
        "n_other_writer": len(imp),
        "n_authors": len({r["claimed"] for r in rows}),
        "engagement": round(float(np.mean([r["applied"] for r in gen])), 4) if gen else 0.0,
        "action_agreement": round(float(np.mean([r["agree"] for r in rows])), 4) if rows else 0.0,
        "auc_off": round(
            auc(np.array([r["off"] for r in gen]), np.array([r["off"] for r in imp])), 4
        ),
        "auc_on": round(auc(np.array([r["on"] for r in gen]), np.array([r["on"] for r in imp])), 4),
        "off_product_cut_points": arm("off", product),
        "on_product_cut_points": arm("on", product),
        "on_new_cut_points": arm("on", cuts),
        "off_catch_at_on_new_flag_rate": round(catch_at_matched_bar(rows, "off", on_rate), 4),
        "honest_flagged_ci95_by_author": _by_author_ci(
            rows, lambda s: _flag_rate(_split(s)[0], "on", cuts)
        ),
        "honest_escalate_ci95_by_author": _by_author_ci(
            rows, lambda s: _flag_rate(_split(s)[0], "on", cuts, ("escalate",))
        ),
        "by_cell": {
            c: {
                "honest_flagged_off_product": round(
                    _flag_rate(_split([r for r in rows if r["cell"] == c])[0], "off", product), 4
                ),
                "honest_flagged_on_new": round(
                    _flag_rate(_split([r for r in rows if r["cell"] == c])[0], "on", cuts), 4
                ),
                "caught_off_product": round(
                    _flag_rate(_split([r for r in rows if r["cell"] == c])[1], "off", product), 4
                ),
                "caught_on_new": round(
                    _flag_rate(_split([r for r in rows if r["cell"] == c])[1], "on", cuts), 4
                ),
            }
            for c in sorted({r["cell"] for r in rows})
        },
    }


def verdict(s: dict) -> dict:
    engaged = (
        s["n_authors"] >= MIN_AUTHORS
        and s["n_honest"] >= MIN_HONEST
        and s["engagement"] >= MIN_ENGAGEMENT
        and s["action_agreement"] > MIN_AGREEMENT
    )
    h1 = s["honest_flagged_ci95_by_author"][1] <= MAX_FLAG_UPPER
    h2 = s["honest_escalate_ci95_by_author"][1] <= MAX_ESCALATE_UPPER
    c1 = s["auc_off"] - s["auc_on"] <= MAX_AUC_DROP
    c2 = (
        s["on_new_cut_points"]["other_writers_caught"]
        >= s["off_catch_at_on_new_flag_rate"] - MAX_CATCH_DROP
    )
    result = "uninformative" if not engaged else ("pass" if h1 and h2 and c1 and c2 else "fail")
    return {"verdict": result, "E": engaged, "H1": h1, "H2": h2, "C1": c1, "C2": c2}


def _criteria_hash() -> str:
    """Fingerprint of everything the hold-out is judged by, so a derived file
    made under different rules cannot be carried into the hold-out."""
    spec = [
        CELLS,
        N_PAST,
        N_NEW,
        N_PROBES,
        SEED,
        TARGETS,
        MIN_AUTHORS,
        MIN_HONEST,
        MIN_ENGAGEMENT,
        MIN_AGREEMENT,
        MAX_FLAG_UPPER,
        MAX_ESCALATE_UPPER,
        MAX_AUC_DROP,
        MAX_CATCH_DROP,
        COLLECTION,
        STUDY_ID,
    ]
    return hashlib.sha256(json.dumps(spec, sort_keys=True, default=str).encode()).hexdigest()[:16]


# ── phases ──────────────────────────────────────────────────────────────────


def derive(jobs: int) -> int:
    rows, skipped = collect("calibration", jobs)
    cuts = derive_cut_points(rows)
    ordered = all(v is not None for v in cuts.values()) and (
        cuts["monitor"] < cuts["schedule_conversation"] < cuts["escalate"]
    )
    out = {
        "study_id": STUDY_ID,
        "criteria_hash": _criteria_hash(),
        "partition": "calibration",
        "cut_points": cuts,
        "derivation": "pass" if ordered else "fail",
        "summary": summarise(rows, cuts) if ordered else None,
        "skipped": {c: len(v) for c, v in skipped.items()},
    }
    DERIVED.write_text(json.dumps(out, indent=2, sort_keys=True) + "\n")
    print(json.dumps({k: out[k] for k in ("cut_points", "derivation")}, indent=1))
    return 0 if ordered else 1


def _already_reported(out: Path) -> bool:
    """The hold-out is spent once its results exist. A run that stopped
    before writing a report produced no result anyone saw (2026-11-19: the
    first attempt crashed after loading one cell, because this script
    dropped the study id the loader needs on every load), so the same
    pre-registered test may finish; a second look at a finished one may not."""
    return out.exists() and json.loads(out.read_text()).get("study_id") == STUDY_ID


def holdout(jobs: int, out: Path) -> int:
    if not DERIVED.exists():
        raise SystemExit("run `derive` first: no derived_cut_points.json")
    derived = json.loads(DERIVED.read_text())
    if derived.get("criteria_hash") != _criteria_hash():
        raise SystemExit("derived_cut_points.json was made under different criteria")
    if derived.get("derivation") != "pass":
        raise SystemExit("the derivation failed; nothing to test")
    if _already_reported(out):
        raise SystemExit(f"the hold-out for {STUDY_ID} has a report already; it is run once")
    cuts = derived["cut_points"]
    rows, skipped = collect("locked_test", jobs, study=STUDY_ID)
    s = summarise(rows, cuts)
    v = verdict(s)
    report = {
        "study_id": STUDY_ID,
        "criteria_hash": _criteria_hash(),
        "writing": "published scholars' single-author journal articles (OpenAlex humanities, "
        "mostly theology and religion); not student writing",
        "cut_points": cuts,
        "product_cut_points": product_cut_points(),
        "derivation_summary": derived["summary"],
        "holdout": s,
        "skipped": {c: len(x) for c, x in skipped.items()},
        "verdict": v,
    }
    out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(s, indent=1))
    print(f"VERDICT: {v['verdict'].upper()}  {v}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("phase", choices=("derive", "holdout"))
    ap.add_argument("--jobs", type=int, default=max(1, (mp.cpu_count() or 2) - 2))
    ap.add_argument("--out", type=Path, default=HERE / "report_2026-11-19.json")
    args = ap.parse_args(argv)
    if args.phase == "derive":
        return derive(args.jobs)
    return holdout(args.jobs, args.out)


if __name__ == "__main__":
    raise SystemExit(main())
