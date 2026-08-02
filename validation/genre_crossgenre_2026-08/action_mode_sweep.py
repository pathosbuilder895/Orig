"""
Does llr_action_mode ("gate"/"trigger"/"blend") actually fix the genre-shift
false-positive problem found in sweep_harness.py, measured on real
recommended ACTIONS (not just the raw AUC numbers)?

Reuses the cached vectors.npy / vectors_meta.json from extract_vectors.py.
"""
import json
import sys
from collections import Counter
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent.parent
sys.path.insert(0, str(_ROOT))

import numpy as np

from original.quantum.state import StudentState, BaselineSample
from original.quantum.scoring import score, ScoringConfig
from original.quantum.null_pool import fit_impostor_gaussian
from original.constants import ALL_FEATURE_CODES

HERE = Path(__file__).parent
LEWIS_GENRES = ["narnia", "space_trilogy", "theology", "memoir", "essays", "satire"]
MODES = ["shadow", "gate", "trigger", "blend"]  # "shadow" == today's shipped behaviour
SEVERITY = {"no_action": 0, "monitor": 1, "schedule_conversation": 2, "escalate": 3}


def load():
    vectors = np.load(HERE / "vectors.npy")
    meta = json.loads((HERE / "vectors_meta.json").read_text())
    for m, v in zip(meta, vectors):
        m["vector"] = v
    return meta


def make_state(records, label):
    st = StudentState(student_id=label)
    for r in records:
        st.add_sample(BaselineSample(
            text="", vector=r["vector"], provenance="proctored", auth_weight=1.0,
            assignment=r["chunk_id"], genre=r["genre"],
        ))
    return st


def actions_for(state, records, mode, impostor_stats):
    config = ScoringConfig(null_model="impostor", llr_action_mode=mode)
    out = []
    for r in records:
        vec = r["vector"]
        fdict = {code: float(v) for code, v in zip(ALL_FEATURE_CODES, vec)}
        result = score(
            state, vec, fdict, submission_id=r["chunk_id"],
            n_tokens=r["word_count"], impostor_stats=impostor_stats,
            scoring_config=config,
        )
        out.append(result.recommendation.action)
    return out


def rate_at_or_above(actions, floor):
    return sum(1 for a in actions if SEVERITY[a] >= SEVERITY[floor]) / len(actions)


def main():
    records = load()
    lewis = [r for r in records if r["author"] == "lewis"]
    chesterton = [r for r in records if r["author"] == "chesterton"]

    by_work = {}
    for r in chesterton:
        by_work.setdefault(r["work"], []).append(r)
    calib, test_impostor = [], []
    for work, rs in by_work.items():
        for i, r in enumerate(rs):
            (calib if i % 2 == 0 else test_impostor).append(r)

    impostor_stats = fit_impostor_gaussian([r["vector"] for r in calib])

    print(f"Lewis chunks: {len(lewis)}  Chesterton test (impostor): {len(test_impostor)}\n")
    print(f"{'genre':15s} {'mode':10s} {'lewis: no_act/monitor/sched/escalate':40s} "
          f"{'lewis FP@sched+':>16s} {'lewis FP@escalate':>18s}   "
          f"{'chesterton: no_act/monitor/sched/escalate':42s} {'chest. TP@monitor+':>19s}")

    summary = {
        mode: {
            "lewis_fp_sched": [], "lewis_fp_escalate": [],
            "chesterton_tp_monitor": [], "chesterton_tp_sched": [], "chesterton_tp_escalate": [],
        }
        for mode in MODES
    }

    for genre in LEWIS_GENRES:
        held_out = [r for r in lewis if r["genre"] == genre]
        cross_baseline_records = [r for r in lewis if r["genre"] != genre]
        if not held_out or not cross_baseline_records:
            continue
        state_template = cross_baseline_records  # rebuilt fresh per mode call below

        for mode in MODES:
            lewis_state = make_state(state_template, f"lewis_cross_{genre}_{mode}")
            lewis_actions = actions_for(lewis_state, held_out, mode, impostor_stats)

            chesterton_state = make_state(state_template, f"lewis_cross_{genre}_{mode}_imp")
            chesterton_actions = actions_for(chesterton_state, test_impostor, mode, impostor_stats)

            lc = Counter(lewis_actions)
            cc = Counter(chesterton_actions)
            lewis_dist = "/".join(str(lc.get(a, 0)) for a in SEVERITY)
            chesterton_dist = "/".join(str(cc.get(a, 0)) for a in SEVERITY)

            fp_sched = rate_at_or_above(lewis_actions, "schedule_conversation")
            fp_escalate = rate_at_or_above(lewis_actions, "escalate")
            tp_monitor = rate_at_or_above(chesterton_actions, "monitor")
            tp_sched = rate_at_or_above(chesterton_actions, "schedule_conversation")
            tp_escalate = rate_at_or_above(chesterton_actions, "escalate")

            summary[mode]["lewis_fp_sched"].append(fp_sched)
            summary[mode]["lewis_fp_escalate"].append(fp_escalate)
            summary[mode]["chesterton_tp_monitor"].append(tp_monitor)
            summary[mode]["chesterton_tp_sched"].append(tp_sched)
            summary[mode]["chesterton_tp_escalate"].append(tp_escalate)

            print(f"{genre:15s} {mode:10s} {lewis_dist:40s} {fp_sched:16.3f} {fp_escalate:18.3f}   "
                  f"{chesterton_dist:42s} {tp_monitor:19.3f} {tp_sched:8.3f} {tp_escalate:10.3f}")

    print("\n=== Averaged across genre buckets (matched severity bars both sides) ===")
    print(f"{'mode':10s} {'lewis FP @sched+':>18s} {'@escalate':>11s}   "
          f"{'chesterton TP @monitor+':>25s} {'@sched+':>10s} {'@escalate':>11s}")
    for mode in MODES:
        s = summary[mode]
        print(f"{mode:10s} {np.mean(s['lewis_fp_sched']):18.3f} {np.mean(s['lewis_fp_escalate']):11.3f}   "
              f"{np.mean(s['chesterton_tp_monitor']):25.3f} {np.mean(s['chesterton_tp_sched']):10.3f} "
              f"{np.mean(s['chesterton_tp_escalate']):11.3f}")


if __name__ == "__main__":
    main()
