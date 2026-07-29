"""Score operating-point trials under a lever combo.

Honest score  = trial's own honest chunk vs its own state.
Impostor score = another trial's honest chunk vs this state (all cross pairs).
Attack score  = ai/ghost chunk vs each seminary state (labeled separately).
"""
from __future__ import annotations

import argparse
import hashlib
import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np

_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_ROOT))

from original.features.pipeline import extract_features, feature_vector  # noqa: E402
from original.quantum.scoring import ScoringConfig  # noqa: E402
from original.quantum.scoring import score as quantum_score  # noqa: E402
from original.quantum.state import BaselineSample, StudentState  # noqa: E402

from .corpus import Trial, attack_probes, build_pools, build_trials  # noqa: E402
from .stats import auc, bootstrap_ci, catch_at_budget  # noqa: E402

N_TOKENS = 500
_VEC_CACHE: dict[str, tuple[np.ndarray, dict]] = {}


@dataclass(frozen=True)
class LeverCombo:
    length_adaptive: bool
    rank_shrinkage: bool
    cohort_prior: bool
    decision_stat: str  # "deviation" | "llr"

    @property
    def name(self) -> str:
        parts = [
            "LAW" if self.length_adaptive else "",
            "SHRINK" if self.rank_shrinkage else "",
            "PRIOR" if self.cohort_prior else "",
            "LLR" if self.decision_stat == "llr" else "",
        ]
        return "+".join(p for p in parts if p) or "OFF"


def _features(text: str) -> tuple[np.ndarray, dict]:
    key = hashlib.sha256(text.encode()).hexdigest()
    if key not in _VEC_CACHE:
        _VEC_CACHE[key] = (feature_vector(text), extract_features(text))
    return _VEC_CACHE[key]


def build_state(trial: Trial, combo: LeverCombo) -> StudentState:
    # RANK_REMEDIATION is read from os.environ inside _build_density_matrix —
    # set it BEFORE the first density_matrix access, fresh state per combo.
    if combo.rank_shrinkage:
        os.environ["RANK_REMEDIATION"] = "shrinkage"
    else:
        os.environ.pop("RANK_REMEDIATION", None)
    state = StudentState(student_id=trial.student_id)
    for t in trial.baseline:
        vec, _ = _features(t)
        state.add_sample(
            BaselineSample(
                text=t, vector=vec, provenance="verified",
                auth_weight=1.0, genre="essay",
            )
        )
    return state


def cohort_stats(trials: list[Trial], exclude: str) -> dict:
    vecs = [
        _features(t)[0]
        for tr in trials if tr.student_id != exclude
        for t in tr.baseline
    ]
    V = np.stack(vecs)
    return {
        "mean": V.mean(axis=0),
        "std": np.maximum(V.std(axis=0), 0.005),
        "n_samples": len(vecs),
    }


def _score(state, text, sid, combo, cstats) -> tuple[float, bool]:
    vec, fd = _features(text)
    cfg = ScoringConfig(
        bayesian_prior_enabled=combo.cohort_prior,
        prior_weight=3.0,
        length_adaptive_weights=combo.length_adaptive,
        null_model="impostor" if combo.decision_stat == "llr" else "none",
        genre_stats=cstats if combo.cohort_prior else None,
    )
    imp = (cstats["mean"], cstats["std"]) if combo.decision_stat == "llr" else None
    res = quantum_score(
        state=state, submission_vector=vec, feature_dict=fd,
        submission_id=sid, n_tokens=N_TOKENS,
        impostor_stats=imp, scoring_config=cfg,
    )
    a = res.authorship
    if combo.decision_stat == "llr" and a.llr_deviation_score is not None:
        return float(a.llr_deviation_score), False
    return float(a.deviation_score), combo.decision_stat == "llr"


def run_combo(trials, attacks, combo: LeverCombo, budget: float = 0.05) -> dict:
    honest, impostor, attack_rows, llr_fallbacks = [], [], [], 0
    for tr in trials:
        state = build_state(tr, combo)
        cstats = cohort_stats(trials, exclude=tr.student_id)
        for j, h in enumerate(tr.honest):
            d, fb = _score(state, h, f"h:{tr.student_id}:{j}", combo, cstats)
            honest.append(d)
            llr_fallbacks += fb
        for other in trials:
            if other.student_id == tr.student_id:
                continue
            for j, h in enumerate(other.honest[:5]):  # cap: 5 impostor probes/pair
                sid = f"i:{other.student_id}->{tr.student_id}:{j}"
                d, fb = _score(state, h, sid, combo, cstats)
                impostor.append(d)
                llr_fallbacks += fb
        if tr.student_id.startswith("seminary"):
            for kind, chunks in attacks.items():
                for j, c in enumerate(chunks[:5]):
                    d, fb = _score(state, c, f"{kind}:{tr.student_id}:{j}", combo, cstats)
                    attack_rows.append({"kind": kind, "target": tr.student_id, "score": d})
                    llr_fallbacks += fb
    h, i = np.array(honest), np.array(impostor)
    cr = catch_at_budget(h, i, budget)
    return {
        "combo": combo.name,
        "n_honest": len(honest), "n_impostor": len(impostor),
        "auc": round(auc(h, i), 4),
        "auc_ci": [round(x, 4) for x in bootstrap_ci(h, i, "auc", seed=42)],
        "threshold": round(cr.threshold, 4),
        "catch_rate": round(cr.catch_rate, 4),
        "catch_ci": [round(x, 4) for x in bootstrap_ci(h, i, "catch", seed=42)],
        "false_flag_rate": round(cr.false_flag_rate, 4),
        "honest_scores": [round(x, 4) for x in honest],
        "impostor_scores": [round(x, 4) for x in impostor],
        "attacks": attack_rows,
        "llr_fallbacks": llr_fallbacks,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--combo", default="off", help="'off' or 'grid' (Task 4)")
    ap.add_argument("--report-dir", default=None)
    args = ap.parse_args(argv)
    os.environ["CONTEXT_MANIFEST_ENABLED"] = "0"
    os.environ["ADAPTIVE_WEIGHTS_ENABLED"] = "0"

    corpus_dir = _ROOT / "validation" / "corpus"
    pools = build_pools(corpus_dir)
    trials = build_trials(pools)
    attacks = attack_probes(corpus_dir)
    print(f"{len(trials)} pseudo-students; honest probes: "
          f"{sum(len(t.honest) for t in trials)}", file=sys.stderr)

    combos = [LeverCombo(False, False, False, "deviation")]
    if args.combo == "grid":
        combos = [
            LeverCombo(law, shr, pri, ds)
            for law in (False, True) for shr in (False, True)
            for pri in (False, True) for ds in ("deviation", "llr")
        ]
    results = []
    for c in combos:
        t0 = time.perf_counter()
        r = run_combo(trials, attacks, c)
        r["elapsed_s"] = round(time.perf_counter() - t0, 1)
        print(f"  {r['combo']:22s} AUC={r['auc']:.3f} "
              f"catch@5%={r['catch_rate']:.3f}", file=sys.stderr)
        results.append(r)

    from .report import write_report
    out = Path(args.report_dir) if args.report_dir else (
        _ROOT / "validation" / "benchmarks" / time.strftime("%Y-%m-%d") / "short_regime"
    )
    write_report(out, results)
    print(f"reports -> {out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
