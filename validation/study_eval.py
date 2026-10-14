"""
validation/study_eval.py: analysis of the natural/shadow study.

Input is a CSV that meets ``validation/study_contract.py`` (one row per sealed
study submission). Output is a Markdown report, a JSON report and PNG charts:

  - separation: ROC curve and AUC (natural vs shadow) on ``deviation_score``,
    with a 95% interval from a bootstrap that resamples STUDENTS, not rows;
  - the confusion matrix at the exported verdict (the live Collections rule,
    scored against the claimed student's baseline), checked against that
    rule when the CSV carries ``authorship_probability``;
  - a threshold sweep on ``deviation_score``: false-flag rate on natural
    attempts against catch rate on shadow attempts, at every 0.01 cut-off,
    with Original's action bands (validation/study/current_operating_point.json)
    marked;
  - the INCONCLUSIVE rate, overall and per label;
  - the same numbers broken down by baseline count and by word count;
  - each student's own natural-versus-shadow gap;
  - which ``f_`` feature columns separate natural from shadow (exploratory);
  - a small-sample caveat computed from the data, at the top of the report.

The report describes ONE cohort. With about 20 students the intervals are
wide, and nothing here is an accuracy figure for Original (NORTH_STAR rule 2).
It deliberately issues no gate verdict: a verdict computed on the same rows a
threshold was chosen from passes by construction. The out-of-sample check is
``scripts/propose_thresholds.py``'s leave-one-student-out run, read by
``validation/calibration_gate.py`` gate G-S1.

Nothing here scores text or imports the feature pipeline; it reads numbers.
``validation/calibration.py`` is not imported for that reason (its module
import loads the spaCy pipeline); its false-flag/catch vocabulary is kept.

Usage:
    python -m validation.study_eval --csv study.csv --out-dir validation/study/out/run1

Outputs are deterministic for a given CSV, seed and checkout: no clock reads,
fixed-seed resampling, rows sorted by submission id.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import math
import os
import sys
from pathlib import Path

import numpy as np

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from validation.power import bar_decidable, rule_of_three_upper, wilson_interval  # noqa: E402
from validation.study_contract import (  # noqa: E402
    CONTRACT_VERSION,
    LABEL_NATURAL,
    LABEL_SHADOW,
    SCORE_COLUMN,
    SCORE_DIRECTION,
    SCORE_MAX,
    SCORE_MIN,
    StudyData,
    StudyRow,
    load_study_csv,
)

SCHEMA = "study-eval-v2"
DEFAULT_SEED = 20261013
DEFAULT_BOOTSTRAP = 2000
DEFAULT_PERMUTATIONS = 1000
DEFAULT_CAP = 0.05
CURRENT_OPERATING_POINT = _ROOT / "validation" / "study" / "current_operating_point.json"

# Flag rule everywhere in this module, from the contract's SCORE_DIRECTION
# (higher deviation_score = less consistent): an attempt is flagged when its
# deviation_score is AT OR ABOVE the cut-off t, the [lower, upper) convention
# of ACTION_THRESHOLDS. t = 0 flags every score; FLAG_NOTHING (above the score
# range) flags none. The grid steps by 0.01, the precision the action bands
# are written in.
FLAG_NOTHING = round(SCORE_MAX + 0.01, 2)
THRESHOLD_GRID: tuple[float, ...] = tuple(
    round(SCORE_MIN + i / 100, 2) for i in range(0, round((FLAG_NOTHING - SCORE_MIN) * 100) + 1)
)
FLAG_RULE_TEXT = f"flagged when {SCORE_COLUMN} >= cut-off"

# Baseline bins follow MODEL_CARD's minimum-baseline table (<3 insufficient,
# 3-4 reduced confidence, >=5 full range); word bins put the 300-word
# practical-reliability floor on a boundary.
BASELINE_BINS = (("0-2", 0, 2), ("3-4", 3, 4), ("5-9", 5, 9), ("10+", 10, None))
WORD_BINS = (("<150", 0, 149), ("150-299", 150, 299), ("300-499", 300, 499), ("500+", 500, None))

MIN_PER_CLASS_FOR_AUC = 3
FEATURE_TOP_N = 15
FDR_ALPHA = 0.10

# Chart palette (dataviz reference instance, light mode).
_SURFACE = "#fcfcfb"
_TEXT = "#0b0b0b"
_TEXT_2 = "#52514e"
_GRID = "#e4e3df"
_NEUTRAL = "#8a8984"
_NATURAL = "#2a78d6"
_SHADOW = "#eb6834"


# ── small numeric helpers ─────────────────────────────────────────────────────


def _r(x: float | None, nd: int = 4) -> float | None:
    if x is None:
        return None
    x = float(x)
    if not math.isfinite(x):
        return None
    return round(x, nd)


def _rate(k: int, n: int) -> dict:
    """A rate with its Wilson 95% interval (rows treated as independent,
    which the clustering of attempts within students makes optimistic)."""
    if n <= 0:
        return {"k": k, "n": n, "rate": None, "wilson95": None}
    lo, hi = wilson_interval(k, n)
    return {"k": k, "n": n, "rate": _r(k / n), "wilson95": [_r(lo), _r(hi)]}


def auc_shadow_less_consistent(natural: np.ndarray, shadow: np.ndarray) -> float | None:
    """P(a shadow attempt reads LESS consistent, i.e. has a higher
    deviation_score, than a natural one), ties counted half. 1.0 = perfect
    separation, 0.5 = chance."""
    n_n, n_s = len(natural), len(shadow)
    if n_n == 0 or n_s == 0:
        return None
    from scipy.stats import rankdata

    ranks = rankdata(np.concatenate([natural, shadow]))
    r_sh = float(ranks[n_n:].sum())
    return (r_sh - n_s * (n_s + 1) / 2.0) / (n_n * n_s)


def _flag_counts(scores: np.ndarray, t: float) -> int:
    return int(np.count_nonzero(scores >= t))


def collections_score(authorship_probability: float) -> int:
    """The live Collections score: Math.round(prob * 100) clamped to 0-100
    (demo/bluebook/Exam.jsx bbScoreWithOriginal). JavaScript rounds halves up;
    Python's round() would not."""
    return max(0, min(100, math.floor(authorship_probability * 100 + 0.5)))


# ── the evaluation ────────────────────────────────────────────────────────────


@dataclasses.dataclass(frozen=True)
class EvalSettings:
    # The live Collections cut-off (score below it is FLAGGED), used only to
    # check the exported verdict when authorship_probability is present.
    live_flag_if_score_below: float
    # Original's action bands as deviation_score cut-offs, marked on the
    # sweep: {action: lower bound}, from the current operating point.
    reference_cutoffs: dict[str, float] = dataclasses.field(default_factory=dict)
    cap: float = DEFAULT_CAP
    n_bootstrap: int = DEFAULT_BOOTSTRAP
    n_permutations: int = DEFAULT_PERMUTATIONS
    seed: int = DEFAULT_SEED
    fictional: bool = False


def looks_fictional(data: StudyData) -> bool:
    """Synthetic fixtures name every writer synth-NN. A report built from
    them must say it is fictional (NORTH_STAR rule 2)."""
    return all(r.student_id.startswith("synth-") for r in data.rows)


def load_current_operating_point(path: Path = CURRENT_OPERATING_POINT) -> dict:
    return json.loads(Path(path).read_text())


def reference_cutoffs(current: dict) -> dict[str, float]:
    """Each action band above no_action, as the deviation_score at which it
    starts (ACTION_THRESHOLDS are [lower, upper) on deviation_score)."""
    bands = current.get("action_thresholds", {})
    return {name: float(lo) for name, (lo, _hi) in bands.items() if lo > SCORE_MIN}


def _conclusive(rows, label, value=lambda r: r.deviation_score):
    return np.array([value(r) for r in rows if r.label == label and r.conclusive], dtype=float)


def _verdict_flag(r: StudyRow) -> float:
    return 1.0 if r.verdict_flagged else 0.0


def _clusters(
    rows: tuple[StudyRow, ...], value=lambda r: r.deviation_score
) -> list[tuple[np.ndarray, np.ndarray]]:
    """Per claimed student (the baseline both kinds of row are scored
    against): (natural values, shadow values), conclusive rows only."""
    by: dict[str, list[StudyRow]] = {}
    for r in rows:
        by.setdefault(r.claimed_student_id, []).append(r)
    return [
        (_conclusive(by[k], LABEL_NATURAL, value), _conclusive(by[k], LABEL_SHADOW, value))
        for k in sorted(by)
    ]


def _cluster_bootstrap(clusters, stat, n_boot: int, rng) -> dict:
    """Percentile 95% interval for stat(natural, shadow), resampling whole
    students with replacement. Resamples where stat is undefined (no row of
    one kind) are skipped and counted."""
    k = len(clusters)
    if k == 0 or n_boot <= 0:
        return {"ci95": None, "n_boot": 0, "n_skipped": 0}
    vals = []
    skipped = 0
    for _ in range(n_boot):
        idx = rng.integers(0, k, size=k)
        nat = np.concatenate([clusters[i][0] for i in idx])
        sh = np.concatenate([clusters[i][1] for i in idx])
        v = stat(nat, sh)
        if v is None:
            skipped += 1
            continue
        vals.append(v)
    if not vals:
        return {"ci95": None, "n_boot": 0, "n_skipped": skipped}
    lo, hi = np.percentile(np.array(vals), [2.5, 97.5])
    return {"ci95": [_r(lo), _r(hi)], "n_boot": len(vals), "n_skipped": skipped}


def _roc(natural: np.ndarray, shadow: np.ndarray) -> list[dict]:
    """From flag-nothing to flag-everything: the cut-off starts above every
    score and steps down through each observed score."""
    if len(natural) == 0 or len(shadow) == 0:
        return []
    cuts = [FLAG_NOTHING] + sorted(set(np.concatenate([natural, shadow]).tolist()), reverse=True)
    pts = []
    for t in cuts:
        pts.append(
            {
                "threshold": _r(t),
                "false_flag_rate": _r(_flag_counts(natural, t) / len(natural)),
                "catch_rate": _r(_flag_counts(shadow, t) / len(shadow)),
            }
        )
    return pts


def _sweep(natural: np.ndarray, shadow: np.ndarray) -> list[dict]:
    out = []
    for t in THRESHOLD_GRID:
        out.append(
            {
                "threshold": t,
                "false_flags": _rate(_flag_counts(natural, t), len(natural)),
                "catches": _rate(_flag_counts(shadow, t), len(shadow)),
            }
        )
    return out


def _verdict_check(rows, live_cutoff: float) -> dict:
    """The exported verdict against the live Collections rule (FLAGGED when
    round(100 x authorship_probability) < cut-off), on the conclusive rows
    that carry authorship_probability. A disagreement means the export
    derived its verdict some other way, or from another baseline."""
    checked = [r for r in rows if r.conclusive and r.authorship_probability is not None]
    disagree = [
        r.submission_id
        for r in checked
        if r.verdict_flagged != (collections_score(r.authorship_probability) < live_cutoff)
    ]
    return {
        "live_rule": f"FLAGGED when round(100 x authorship_probability) < {live_cutoff:g}",
        "rows_checked": len(checked),
        "disagreements": len(disagree),
        "disagreeing_submissions": disagree[:20],
    }


def _confusion(rows, live_cutoff: float) -> dict:
    """The matrix the exported verdict gives: what the live Collections rule
    did on these attempts, scored against the claimed student's baseline."""
    out = {}
    for label in (LABEL_NATURAL, LABEL_SHADOW):
        rs = [r for r in rows if r.label == label]
        flagged = sum(1 for r in rs if r.conclusive and r.verdict_flagged)
        not_flagged = sum(1 for r in rs if r.conclusive and not r.verdict_flagged)
        out[label] = {
            "total": len(rs),
            "flagged": flagged,
            "not_flagged": not_flagged,
            "inconclusive": sum(1 for r in rs if r.inconclusive),
            "unscored": sum(1 for r in rs if r.unscored),
        }
    nat, sh = out[LABEL_NATURAL], out[LABEL_SHADOW]
    return {
        "rule": "flagged when the exported verdict is FLAGGED (the live Collections rule)",
        "matrix": out,
        "false_flag_rate_conclusive": _rate(nat["flagged"], nat["flagged"] + nat["not_flagged"]),
        "catch_rate_conclusive": _rate(sh["flagged"], sh["flagged"] + sh["not_flagged"]),
        # "All attempts" still leaves unscored rows out (contract): an
        # inconclusive attempt counts, as never flagged.
        "false_flag_rate_all_attempts": _rate(nat["flagged"], nat["total"] - nat["unscored"]),
        "catch_rate_all_attempts": _rate(sh["flagged"], sh["total"] - sh["unscored"]),
        "verdict_check": _verdict_check(rows, live_cutoff),
    }


def _inconclusive(rows) -> dict:
    out = {}
    for label in (LABEL_NATURAL, LABEL_SHADOW, "all"):
        rs = [r for r in rows if label == "all" or r.label == label]
        out[label] = {
            "inconclusive": _rate(
                sum(1 for r in rs if r.inconclusive), sum(1 for r in rs if not r.unscored)
            ),
            "unscored": sum(1 for r in rs if r.unscored),
        }
    return out


def _bin_of(value: int, bins) -> str:
    for name, lo, hi in bins:
        if value >= lo and (hi is None or value <= hi):
            return name
    return bins[-1][0]


def _breakdown(rows, key, bins) -> list[dict]:
    out = []
    for name, lo, hi in bins:
        rs = [r for r in rows if _bin_of(key(r), bins) == name]
        nat = _conclusive(rs, LABEL_NATURAL)
        sh = _conclusive(rs, LABEL_SHADOW)
        nat_flag = _conclusive(rs, LABEL_NATURAL, _verdict_flag)
        sh_flag = _conclusive(rs, LABEL_SHADOW, _verdict_flag)
        auc = None
        auc_note = None
        if len(nat) >= MIN_PER_CLASS_FOR_AUC and len(sh) >= MIN_PER_CLASS_FOR_AUC:
            auc = _r(auc_shadow_less_consistent(nat, sh))
        else:
            auc_note = f"needs >= {MIN_PER_CLASS_FOR_AUC} conclusive attempts of each kind"
        n_nat_all = sum(1 for r in rs if r.label == LABEL_NATURAL)
        n_sh_all = sum(1 for r in rs if r.label == LABEL_SHADOW)
        out.append(
            {
                "bin": name,
                "range": [lo, hi],
                "natural_attempts": n_nat_all,
                "shadow_attempts": n_sh_all,
                "inconclusive": _rate(
                    sum(1 for r in rs if r.inconclusive), sum(1 for r in rs if not r.unscored)
                ),
                "false_flags_at_verdict": _rate(int(nat_flag.sum()), len(nat_flag)),
                "catches_at_verdict": _rate(int(sh_flag.sum()), len(sh_flag)),
                "auc": auc,
                "auc_note": auc_note,
            }
        )
    return out


def _sign_test_p(pos: int, neg: int) -> float | None:
    n = pos + neg
    if n == 0:
        return None
    from scipy.stats import binomtest

    return float(binomtest(pos, n, 0.5).pvalue)


def _per_student(rows, rng, n_boot: int) -> dict:
    by: dict[str, list[StudyRow]] = {}
    for r in rows:
        by.setdefault(r.claimed_student_id, []).append(r)
    students = []
    gaps = []
    for sid in sorted(by):
        rs = by[sid]
        nat = _conclusive(rs, LABEL_NATURAL)
        sh = _conclusive(rs, LABEL_SHADOW)
        both = len(nat) > 0 and len(sh) > 0
        gap = float(sh.mean() - nat.mean()) if both else None
        if gap is not None:
            gaps.append(gap)
        students.append(
            {
                "claimed_student_id": sid,
                "natural_n": int(len(nat)),
                "shadow_n": int(len(sh)),
                "inconclusive_n": sum(1 for r in rs if r.inconclusive),
                "natural_mean": _r(nat.mean()) if len(nat) else None,
                "shadow_mean": _r(sh.mean()) if len(sh) else None,
                "gap": _r(gap),
                "separable": bool(both and sh.min() > nat.max()),
                "natural_flagged_at_verdict": int(
                    _conclusive(rs, LABEL_NATURAL, _verdict_flag).sum()
                ),
                "shadow_caught_at_verdict": int(_conclusive(rs, LABEL_SHADOW, _verdict_flag).sum()),
                "baseline_count": max(r.baseline_count for r in rs),
            }
        )
    pos = sum(1 for g in gaps if g > 0)
    neg = sum(1 for g in gaps if g < 0)
    median_ci = None
    if gaps and n_boot > 0:
        arr = np.array(gaps)
        meds = [
            float(np.median(arr[rng.integers(0, len(arr), size=len(arr))])) for _ in range(n_boot)
        ]
        lo, hi = np.percentile(np.array(meds), [2.5, 97.5])
        median_ci = [_r(lo), _r(hi)]
    return {
        "students": students,
        "summary": {
            "students_with_both_kinds": len(gaps),
            "positive_gap": pos,
            "negative_gap": neg,
            "zero_gap": len(gaps) - pos - neg,
            "separable": sum(1 for s in students if s["separable"]),
            "median_gap": _r(float(np.median(gaps))) if gaps else None,
            "median_gap_ci95": median_ci,
            "sign_test_p": _r(_sign_test_p(pos, neg), 6),
            "note": (
                f"gap = mean shadow {SCORE_COLUMN} minus mean natural {SCORE_COLUMN} against "
                "the same baseline; positive means the imitation read as less consistent"
            ),
        },
    }


def _benjamini_hochberg(pvals: list[float]) -> list[float]:
    m = len(pvals)
    if m == 0:
        return []
    order = sorted(range(m), key=lambda i: pvals[i])
    q = [0.0] * m
    running = 1.0
    for rank in range(m, 0, -1):
        i = order[rank - 1]
        running = min(running, pvals[i] * m / rank)
        q[i] = running
    return q


def _feature_importance(data: StudyData, n_perm: int, seed: int) -> dict:
    """Which f_ columns separate natural from shadow. Exploratory: per-feature
    AUC, standardised mean difference, and a permutation p-value that
    shuffles labels WITHIN each claimed student (so a student whose writing
    simply differs from everyone else's cannot pass for a separating feature),
    with Benjamini-Hochberg q-values across the features tested."""
    from scipy.stats import rankdata

    from original.constants import ALL_FEATURE_CODES, FEATURE_TIER
    from validation.measurability import MeasurabilityStatus, assert_aggregatable, status

    if not data.feature_codes:
        return {"tested": [], "excluded": {}, "by_tier": [], "note": "the CSV has no f_ columns"}

    excluded: dict[str, str] = {}
    candidates = []
    for code in data.feature_codes:
        st = status(code)
        if st is not MeasurabilityStatus.MEASURABLE:
            excluded[code] = f"not measurable ({st.value})"
        else:
            candidates.append(code)

    rows = data.rows
    tested = []
    for code in candidates:
        keep = [r for r in rows if r.features.get(code) is not None]
        v = np.array([r.features[code] for r in keep], dtype=float)
        y = np.array([1 if r.label == LABEL_SHADOW else 0 for r in keep])
        n_s, n_n = int(y.sum()), int(len(y) - y.sum())
        if n_s < 2 or n_n < 2:
            excluded[code] = "fewer than 2 values of each kind"
            continue
        if float(np.ptp(v)) == 0.0:
            excluded[code] = "constant in this data"
            continue
        tested.append((code, keep, v, y, n_s, n_n))

    assert_aggregatable([t[0] for t in tested])

    results = []
    for code, keep, v, y, n_s, n_n in tested:
        ranks = rankdata(v)
        auc = (float(ranks[y == 1].sum()) - n_s * (n_s + 1) / 2.0) / (n_s * n_n)
        nat, sh = v[y == 0], v[y == 1]
        pooled = math.sqrt(
            ((n_n - 1) * nat.var(ddof=1) + (n_s - 1) * sh.var(ddof=1)) / max(1, n_n + n_s - 2)
        )
        smd = (sh.mean() - nat.mean()) / pooled if pooled > 0 else None

        rng = np.random.default_rng([seed, ALL_FEATURE_CODES.index(code)])
        groups: dict[str, list[int]] = {}
        for i, r in enumerate(keep):
            groups.setdefault(r.claimed_student_id, []).append(i)
        perm = np.tile(y, (n_perm, 1))
        for g in sorted(groups):
            idx = np.array(groups[g])
            if len(idx) > 1:
                perm[:, idx] = rng.permuted(perm[:, idx], axis=1)
        auc_perm = (perm @ ranks - n_s * (n_s + 1) / 2.0) / (n_s * n_n)
        obs = abs(auc - 0.5)
        p = (1 + int(np.count_nonzero(np.abs(auc_perm - 0.5) >= obs - 1e-12))) / (n_perm + 1)
        results.append(
            {
                "feature": code,
                "tier": int(FEATURE_TIER.get(code, 0)),
                "n": int(len(v)),
                "auc_shadow_higher": _r(auc),
                "separation": _r(abs(auc - 0.5) * 2.0),
                "direction": "higher in shadow"
                if auc > 0.5
                else ("lower in shadow" if auc < 0.5 else "none"),
                "smd": _r(smd),
                "perm_p": _r(p),
            }
        )

    qs = _benjamini_hochberg([res["perm_p"] for res in results])
    for res, q in zip(results, qs, strict=False):
        res["bh_q"] = _r(q)
    results.sort(key=lambda d: (-d["separation"], d["feature"]))

    tiers: dict[int, list[dict]] = {}
    for res in results:
        tiers.setdefault(res["tier"], []).append(res)
    by_tier = [
        {
            "tier": t,
            "features_tested": len(rs),
            "max_separation": max(x["separation"] for x in rs),
            "median_separation": _r(float(np.median([x["separation"] for x in rs]))),
            "features_q_le_alpha": sum(1 for x in rs if x["bh_q"] <= FDR_ALPHA),
        }
        for t, rs in sorted(tiers.items())
    ]
    return {
        "tested": results,
        "excluded": dict(sorted(excluded.items())),
        "by_tier": by_tier,
        "permutations": n_perm,
        "fdr_alpha": FDR_ALPHA,
        "note": (
            "exploratory: dozens of features on about 20 students; a feature "
            "near the top here is a lead for the next study, not a finding"
        ),
    }


def _min_n_demonstrable(cap: float) -> int:
    """Smallest number of natural attempts at which even ZERO false flags
    would put the Wilson 95% upper bound at or below the cap."""
    n = 1
    while wilson_interval(0, n)[1] > cap:
        n += 1
    return n


def _small_sample(data: StudyData, confusion: dict, cap: float) -> dict:
    rows = data.rows
    claimed = {r.claimed_student_id for r in rows}
    writers = {r.student_id for r in rows}
    nat = confusion["matrix"][LABEL_NATURAL]
    n_nat = nat["flagged"] + nat["not_flagged"]
    ff = nat["flagged"]
    decid = bar_decidable(ff, n_nat, cap) if n_nat else "undecided"
    min_n = _min_n_demonstrable(cap)
    lines = [
        f"This study has {len(claimed)} students ({len(rows)} attempts, "
        f"{n_nat} conclusive natural). It describes this cohort, on these prompts, "
        "on this day. It is not an accuracy figure for Original and must not be quoted "
        "as one (NORTH_STAR rule 2).",
        "Attempts against the same baseline are not independent, so the AUC and headline "
        "intervals resample claimed students (baselines). A writer's own natural and shadow "
        "attempts land in different clusters, so dependence through the writer is not "
        "captured and these intervals may still be too narrow; the sweep's Wilson "
        "intervals treat attempts as independent and are narrower still. With about 20 "
        "students every interval is wide: read the intervals, not the point estimates.",
        f"To show a false-flag rate at or below {cap:.0%} with 95% confidence needs at "
        f"least {min_n} conclusive natural attempts, from as many different students, with "
        f"none flagged (gate G-S1 counts a student's repeat attempts once). This study has "
        f"{n_nat}; against the {cap:.0%} bar the live verdict's observed false-flag count "
        f"is '{decid}' (validation.power.bar_decidable).",
        "Every threshold read off this report was chosen on these same rows, so it "
        "flatters itself. scripts/propose_thresholds.py re-checks its choice "
        "leave-one-student-out; a fresh cohort is still needed before anything is "
        "enabled.",
        "Shadow attempts are students imitating classmates on request. They are not "
        "evidence about ghostwriting, AI use, or misconduct.",
    ]
    out = {
        "students": len(claimed),
        "writers": len(writers),
        "attempts": len(rows),
        "conclusive_natural": n_nat,
        "natural_false_flags_at_verdict": ff,
        "min_natural_attempts_to_demonstrate_cap": min_n,
        "false_flag_bar_decidable": decid,
        "lines": lines,
    }
    if n_nat:
        out["rule_of_three_upper_if_zero"] = _r(rule_of_three_upper(n_nat))
    return out


def _rate_of_flags(nat, sh, label):
    v = nat if label == LABEL_NATURAL else sh
    return float(v.mean()) if len(v) else None


def evaluate(data: StudyData, settings: EvalSettings) -> dict:
    rows = data.rows
    natural = _conclusive(rows, LABEL_NATURAL)
    shadow = _conclusive(rows, LABEL_SHADOW)
    clusters = _clusters(rows)
    flag_clusters = _clusters(rows, _verdict_flag)
    rng = np.random.default_rng(settings.seed)

    auc = auc_shadow_less_consistent(natural, shadow)
    auc_boot = _cluster_bootstrap(clusters, auc_shadow_less_consistent, settings.n_bootstrap, rng)

    confusion = _confusion(rows, settings.live_flag_if_score_below)
    confusion["false_flag_rate_conclusive"]["student_bootstrap95"] = _cluster_bootstrap(
        flag_clusters,
        lambda nat, sh: _rate_of_flags(nat, sh, LABEL_NATURAL),
        settings.n_bootstrap,
        rng,
    )["ci95"]
    confusion["catch_rate_conclusive"]["student_bootstrap95"] = _cluster_bootstrap(
        flag_clusters,
        lambda nat, sh: _rate_of_flags(nat, sh, LABEL_SHADOW),
        settings.n_bootstrap,
        rng,
    )["ci95"]

    per_student = _per_student(rows, rng, settings.n_bootstrap)

    return {
        "schema": SCHEMA,
        "contract": {
            "version": CONTRACT_VERSION,
            "aliases_applied": data.aliases_applied,
            "warnings": list(data.warnings),
            "feature_columns": len(data.feature_codes),
            "unlabelled_rows_left_out": data.unlabelled,
        },
        "score": {
            "column": SCORE_COLUMN,
            "direction": SCORE_DIRECTION,
            "range": [SCORE_MIN, SCORE_MAX],
            "flag_rule": FLAG_RULE_TEXT,
        },
        "input": {"name": data.source_name, "sha256": data.sha256},
        "settings": dataclasses.asdict(settings),
        "small_sample": _small_sample(data, confusion, settings.cap),
        "counts": {
            "attempts": len(rows),
            "natural": sum(1 for r in rows if r.label == LABEL_NATURAL),
            "shadow": sum(1 for r in rows if r.label == LABEL_SHADOW),
            "conclusive_natural": int(len(natural)),
            "conclusive_shadow": int(len(shadow)),
            "claimed_students": len({r.claimed_student_id for r in rows}),
            "writers": len({r.student_id for r in rows}),
        },
        "auc": {
            "value": _r(auc),
            "meaning": (
                f"probability a shadow attempt has a higher {SCORE_COLUMN} (reads less "
                "consistent with the claimed student) than a natural one"
            ),
            **auc_boot,
            "method": "percentile bootstrap resampling claimed students with replacement",
        },
        "roc": _roc(natural, shadow),
        "confusion_at_verdict": confusion,
        "inconclusive": _inconclusive(rows),
        "sweep": _sweep(natural, shadow),
        "by_baseline_count": _breakdown(rows, lambda r: r.baseline_count, BASELINE_BINS),
        "by_word_count": _breakdown(rows, lambda r: r.word_count, WORD_BINS),
        "per_student": per_student,
        "feature_importance": _feature_importance(data, settings.n_permutations, settings.seed),
        "rows": [
            {
                "submission_id": r.submission_id,
                "claimed_student_id": r.claimed_student_id,
                "student_id": r.student_id,
                "label": r.label,
                "verdict": r.verdict,
                SCORE_COLUMN: r.deviation_score,
                "conclusive": r.conclusive,
                "inconclusive": r.inconclusive,
                "baseline_count": r.baseline_count,
                "word_count": r.word_count,
            }
            for r in rows
        ],
    }


def _experiment(report: dict, created_at: str) -> dict:
    from validation.experiment import build_spec, spec_to_dict

    per: dict[str, int] = {}
    for r in report["rows"]:
        per[r["claimed_student_id"]] = per.get(r["claimed_student_id"], 0) + 1
    spec = build_spec(
        task="verification",
        corpora={
            "study": {
                "n_authors": report["counts"]["claimed_students"],
                "n_documents": report["counts"]["attempts"],
                "total_words": sum(r["word_count"] for r in report["rows"]),
                "docs_per_author": dict(sorted(per.items())),
                "provenance": "student_pilot",
                "input_sha256": report["input"]["sha256"],
            }
        },
        windowing={"source": "sealed submissions as-is"},
        aggregation={
            "unit": "claimed student (bootstrap and permutation clusters)",
            "flag_rule": FLAG_RULE_TEXT,
            "live_rule": "exported verdict",
        },
        thresholds={
            "reference_cutoffs": report["settings"]["reference_cutoffs"],
            "false_flag_cap": report["settings"]["cap"],
        },
    )
    return spec_to_dict(dataclasses.replace(spec, created_at=created_at))


# ── Markdown ──────────────────────────────────────────────────────────────────


def _pct(x: float | None) -> str:
    return "n/a" if x is None else f"{x * 100:.1f}%"


def _rate_text(d: dict) -> str:
    if d["rate"] is None:
        return f"{d['k']}/{d['n']} (n/a)"
    lo, hi = d["wilson95"]
    return f"{d['k']}/{d['n']} = {_pct(d['rate'])} [{_pct(lo)}, {_pct(hi)}]"


def _ci_text(ci) -> str:
    return "n/a" if not ci else f"[{ci[0]:.3f}, {ci[1]:.3f}]"


def _p_text(p: float | None) -> str:
    if p is None:
        return "n/a"
    return "< 0.001" if p < 0.001 else f"{p:.3f}"


def _na(x) -> str:
    return "n/a" if x is None else str(x)


def _cut(t: float) -> str:
    return f"{t:.2f}"


def render_markdown(report: dict, chart_files: dict[str, str]) -> str:
    s = report["settings"]
    c = report["confusion_at_verdict"]
    m = c["matrix"]
    out = [
        "# Natural/shadow study: evaluation",
        "",
    ]
    if s.get("fictional"):
        out += [
            "> **FICTIONAL DATA.** This report was built from invented rows (a test fixture). "
            "No number in it says anything about Original or about students.",
            "",
        ]
    out += [
        f"Input `{report['input']['name']}` (sha256 `{report['input']['sha256'][:12]}`), "
        f"contract `{report['contract']['version']}`, schema `{report['schema']}`. "
        f"Seed {s['seed']}, {s['n_bootstrap']} bootstrap resamples, "
        f"{s['n_permutations']} permutations.",
        "",
        f"Score: `{report['score']['column']}`, {report['score']['range'][0]:g}-"
        f"{report['score']['range'][1]:g}; higher means LESS consistent with the claimed "
        f"student's baseline. Every cut-off below is {report['score']['flag_rule']}.",
        "",
        "## Read this first: small sample",
        "",
    ]
    out += [f"- {line}" for line in report["small_sample"]["lines"]]
    if report["contract"]["warnings"]:
        out += ["", "Contract warnings:"]
        out += [f"- {w}" for w in report["contract"]["warnings"]]
    if report["contract"].get("unlabelled_rows_left_out"):
        out += [
            "",
            f"{report['contract']['unlabelled_rows_left_out']} exported row(s) had no study label "
            "and are in no number below.",
        ]
    cn = report["counts"]
    out += [
        "",
        "## Data",
        "",
        "| | natural | shadow |",
        "|---|---:|---:|",
        f"| attempts | {cn['natural']} | {cn['shadow']} |",
        f"| conclusive (scored on a ready baseline) | {cn['conclusive_natural']} | {cn['conclusive_shadow']} |",
        "",
        f"{cn['claimed_students']} claimed students (baselines scored against), {cn['writers']} writers.",
        "",
        "## Separation (ROC / AUC)",
        "",
    ]
    a = report["auc"]
    if a["value"] is None:
        out.append("AUC cannot be computed: there are no conclusive attempts of one kind.")
    else:
        out.append(
            f"AUC **{a['value']:.3f}**, student-bootstrap 95% interval {_ci_text(a['ci95'])} "
            f"({a['n_boot']} resamples used, {a['n_skipped']} skipped). AUC is the "
            f"{a['meaning']}; 0.5 is chance."
        )
    if "roc" in chart_files:
        out += ["", f"![ROC curve]({chart_files['roc']})"]
    out += [
        "",
        "## Confusion matrix at the live rule (the exported verdict)",
        "",
        f"Read from the `verdict` column: {c['rule']}, scored against the claimed student's "
        "baseline. It is not a cut-off on the score above.",
        "",
        "| | flagged | not flagged | inconclusive | unscored |",
        "|---|---:|---:|---:|---:|",
    ]
    for label in (LABEL_NATURAL, LABEL_SHADOW):
        x = m[label]
        out.append(
            f"| {label} | {x['flagged']} | {x['not_flagged']} | {x['inconclusive']} | {x['unscored']} |"
        )
    out += [
        "",
        f"- False flags on natural writing (conclusive): {_rate_text(c['false_flag_rate_conclusive'])}; "
        f"student bootstrap {_ci_text(c['false_flag_rate_conclusive'].get('student_bootstrap95'))}.",
        f"- Shadow attempts caught (conclusive): {_rate_text(c['catch_rate_conclusive'])}; "
        f"student bootstrap {_ci_text(c['catch_rate_conclusive'].get('student_bootstrap95'))}.",
        f"- Over all scored attempts (an inconclusive attempt counts as not flagged; unscored "
        f"attempts are left out): false flags "
        f"{_rate_text(c['false_flag_rate_all_attempts'])}, catches {_rate_text(c['catch_rate_all_attempts'])}.",
    ]
    vc = c["verdict_check"]
    if vc["rows_checked"]:
        out.append(
            f"- Verdict checked against the live rule ({vc['live_rule']}) on {vc['rows_checked']} "
            f"row(s) carrying `authorship_probability`: {vc['disagreements']} disagree"
            + (
                "; the export did not derive its verdict the way Collections does, so this matrix "
                "is not the live rule's."
                if vc["disagreements"]
                else "."
            )
        )
    else:
        out.append(
            "- The CSV carries no `authorship_probability`, so the verdict could not be checked "
            "against the live rule; this matrix is the export's verdict as given."
        )
    inc = report["inconclusive"]
    out += [
        "",
        "## INCONCLUSIVE rate",
        "",
        "| | inconclusive | unscored |",
        "|---|---|---:|",
    ]
    for label in (LABEL_NATURAL, LABEL_SHADOW, "all"):
        out.append(
            f"| {label} | {_rate_text(inc[label]['inconclusive'])} | {inc[label]['unscored']} |"
        )
    out += [
        "",
        "INCONCLUSIVE is a valid answer (NORTH_STAR rule 3): it is reported, never folded into "
        "either side. Unscored rows (no score and not inconclusive) are left out of every rate.",
        "",
        "## Threshold sweep",
        "",
        f"Flag when `{SCORE_COLUMN}` is at or above the cut-off. Rates are over conclusive "
        "attempts. Rows marked with an action are where Original's action bands start "
        "(`ACTION_THRESHOLDS`); every 0.01 step is in the JSON.",
        "",
        "| cut-off | false flags (natural) | caught (shadow) |",
        "|---:|---|---|",
    ]
    refs = {round(v, 2): k for k, v in s["reference_cutoffs"].items()}
    for row in report["sweep"]:
        t = row["threshold"]
        if round(t * 100) % 10 == 0 or t in refs:
            mark = f" ({refs[t]})" if t in refs else ""
            out.append(
                f"| {_cut(t)}{mark} | {_rate_text(row['false_flags'])} | "
                f"{_rate_text(row['catches'])} |"
            )
    if "sweep" in chart_files:
        out += ["", f"![Threshold sweep]({chart_files['sweep']})"]
    if "distributions" in chart_files:
        out += ["", f"![Score distributions]({chart_files['distributions']})"]

    def _bd(title, rows):
        lines = [
            "",
            f"## By {title}",
            "",
            "| bin | natural | shadow | inconclusive | false flags (verdict) | caught (verdict) | AUC |",
            "|---|---:|---:|---|---|---|---|",
        ]
        for b in rows:
            auc = f"{b['auc']:.3f}" if b["auc"] is not None else f"n/a ({b['auc_note']})"
            lines.append(
                f"| {b['bin']} | {b['natural_attempts']} | {b['shadow_attempts']} | "
                f"{_rate_text(b['inconclusive'])} | {_rate_text(b['false_flags_at_verdict'])} | "
                f"{_rate_text(b['catches_at_verdict'])} | {auc} |"
            )
        return lines

    out += _bd("baseline count (approved reference samples)", report["by_baseline_count"])
    out += _bd("word count", report["by_word_count"])

    ps = report["per_student"]
    sm = ps["summary"]
    out += [
        "",
        "## Each student's own gap",
        "",
        f"{sm['note']}. Students with both kinds: {sm['students_with_both_kinds']}; positive gap "
        f"{sm['positive_gap']}, negative {sm['negative_gap']}, zero {sm['zero_gap']}; fully "
        f"separable {sm['separable']}. Median gap {sm['median_gap']}, bootstrap 95% "
        f"{_ci_text(sm['median_gap_ci95'])}; sign test p {_p_text(sm['sign_test_p'])}.",
        "",
        "| student | natural n | shadow n | natural mean | shadow mean | gap | separable | baseline |",
        "|---|---:|---:|---:|---:|---:|---|---:|",
    ]
    for st in ps["students"]:
        out.append(
            f"| {st['claimed_student_id']} | {st['natural_n']} | {st['shadow_n']} | "
            f"{_na(st['natural_mean'])} | {_na(st['shadow_mean'])} | {_na(st['gap'])} | "
            f"{'yes' if st['separable'] else 'no'} | {st['baseline_count']} |"
        )
    if "gaps" in chart_files:
        out += ["", f"![Per-student gap]({chart_files['gaps']})"]

    fi = report["feature_importance"]
    out += ["", "## Which features separate natural from shadow (exploratory)", ""]
    if not fi["tested"]:
        out.append(f"No feature was tested: {fi.get('note', '')}.")
    else:
        out += [
            f"{fi['note']}. Separation = |AUC - 0.5| x 2. p from {fi['permutations']} "
            "within-student label permutations; q = Benjamini-Hochberg across the "
            f"{len(fi['tested'])} features tested.",
            "",
            "| feature | tier | separation | direction | AUC | SMD | p | q |",
            "|---|---:|---:|---|---:|---:|---:|---:|",
        ]
        for f in fi["tested"][:FEATURE_TOP_N]:
            out.append(
                f"| `{f['feature']}` | {f['tier']} | {f['separation']:.3f} | {f['direction']} | "
                f"{f['auc_shadow_higher']:.3f} | {f['smd'] if f['smd'] is not None else 'n/a'} | "
                f"{_p_text(f['perm_p'])} | {f['bh_q']:.3f} |"
            )
        if "features" in chart_files:
            out += ["", f"![Feature separation]({chart_files['features']})"]
    if fi["excluded"]:
        reasons: dict[str, int] = {}
        for why in fi["excluded"].values():
            reasons[why] = reasons.get(why, 0) + 1
        out += [
            "",
            "Excluded columns: "
            + "; ".join(f"{n} {why}" for why, n in sorted(reasons.items()))
            + ".",
        ]
    out += [
        "",
        "## What this report does not show",
        "",
        "- Whether Original detects ghostwriting, AI use or misconduct. Shadow attempts are "
        "on-request imitations by classmates.",
        "- How the numbers would move on another cohort, prompt or genre.",
        "- An out-of-sample check of any threshold: see `scripts/propose_thresholds.py`.",
        "",
    ]
    return "\n".join(out)


# ── charts ────────────────────────────────────────────────────────────────────


def _style(ax, title: str, xlabel: str, ylabel: str) -> None:
    ax.set_facecolor(_SURFACE)
    ax.set_title(title, loc="left", fontsize=11, color=_TEXT, pad=10)
    ax.set_xlabel(xlabel, fontsize=9, color=_TEXT_2)
    ax.set_ylabel(ylabel, fontsize=9, color=_TEXT_2)
    ax.tick_params(colors=_TEXT_2, labelsize=8, length=0)
    ax.grid(True, color=_GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(_GRID)


def render_charts(report: dict, chart_dir: Path) -> dict[str, str]:
    """PNG charts. Returns {key: path relative to the report directory}.
    Returns {} (and the report says so) when matplotlib is not installed."""
    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError:
        return {}

    chart_dir.mkdir(parents=True, exist_ok=True)
    plt.rcParams.update({"font.family": "DejaVu Sans", "figure.facecolor": _SURFACE})
    files: dict[str, str] = {}
    refs = report["settings"]["reference_cutoffs"]
    cap = report["settings"]["cap"]

    def _ref_lines(ax, y_text: float) -> None:
        for name, v in sorted(refs.items(), key=lambda kv: kv[1]):
            ax.axvline(v, color=_NEUTRAL, linewidth=1, linestyle=":")
            ax.text(
                v + 0.006,
                y_text,
                name.replace("_", " "),
                color=_TEXT_2,
                fontsize=7,
                rotation=90,
                va="top",
            )

    def _save(fig, key, name):
        fig.tight_layout()
        fig.savefig(chart_dir / name, dpi=150, facecolor=_SURFACE, metadata={"Software": None})
        plt.close(fig)
        files[key] = f"{chart_dir.name}/{name}"

    # ROC
    if report["roc"]:
        fig, ax = plt.subplots(figsize=(5.6, 5.0))
        xs = [p["false_flag_rate"] for p in report["roc"]]
        ys = [p["catch_rate"] for p in report["roc"]]
        ax.plot([0, 1], [0, 1], color=_NEUTRAL, linewidth=1, linestyle="--")
        ax.text(0.62, 0.55, "chance", color=_TEXT_2, fontsize=8, rotation=38)
        # Straight segments, not a staircase: tied scores move both rates at
        # once, and the area under these segments is the reported AUC.
        ax.plot(xs, ys, color=_NATURAL, linewidth=2)
        cm = report["confusion_at_verdict"]
        fx, fy = cm["false_flag_rate_conclusive"]["rate"], cm["catch_rate_conclusive"]["rate"]
        if fx is not None and fy is not None:
            # The live verdict is a point, not on the curve: it reads another
            # score (the Collections score), so it can sit off the curve.
            ax.scatter([fx], [fy], s=64, color=_SHADOW, edgecolor=_SURFACE, linewidth=2, zorder=3)
            ax.annotate(
                "live verdict",
                (fx, fy),
                xytext=(8, -14),
                textcoords="offset points",
                fontsize=8,
                color=_TEXT,
            )
        a = report["auc"]
        sub = (
            f"AUC {a['value']:.2f}, 95% {_ci_text(a['ci95'])}"
            if a["value"] is not None
            else "AUC n/a"
        )
        _style(
            ax,
            f"Natural vs shadow ROC on {SCORE_COLUMN}  ({sub})",
            "False-flag rate on natural attempts",
            "Catch rate on shadow attempts",
        )
        ax.set_xlim(-0.02, 1.02)
        ax.set_ylim(-0.02, 1.02)
        _save(fig, "roc", "roc.png")

    # Threshold sweep
    fig, ax = plt.subplots(figsize=(7.2, 4.2))
    ts = [r["threshold"] for r in report["sweep"]]
    ff = [r["false_flags"]["rate"] for r in report["sweep"]]
    ca = [r["catches"]["rate"] for r in report["sweep"]]
    if any(v is not None for v in ff):
        ax.plot(
            ts,
            [v if v is not None else np.nan for v in ff],
            color=_NATURAL,
            linewidth=2,
            drawstyle="steps-post",
            label="False flags (natural)",
        )
    if any(v is not None for v in ca):
        ax.plot(
            ts,
            [v if v is not None else np.nan for v in ca],
            color=_SHADOW,
            linewidth=2,
            drawstyle="steps-post",
            label="Caught (shadow)",
        )
    ax.axhline(cap, color=_NEUTRAL, linewidth=1, linestyle="--")
    ax.text(0.01, cap + 0.015, f"{cap:.0%} false-flag cap", color=_TEXT_2, fontsize=8)
    _ref_lines(ax, 0.98)
    _style(
        ax,
        f"Threshold sweep: flag when {SCORE_COLUMN} is at or above the cut-off",
        f"Cut-off ({SCORE_COLUMN})",
        "Share of conclusive attempts flagged",
    )
    ax.set_ylim(-0.02, 1.02)
    ax.set_xlim(SCORE_MIN, FLAG_NOTHING)
    ax.legend(loc="center right", frameon=False, fontsize=8, labelcolor=_TEXT)
    _save(fig, "sweep", "threshold_sweep.png")

    # Score distributions (strip plot, deterministic jitter)
    nat = [
        r[SCORE_COLUMN] for r in report["rows"] if r["conclusive"] and r["label"] == LABEL_NATURAL
    ]
    sh = [r[SCORE_COLUMN] for r in report["rows"] if r["conclusive"] and r["label"] == LABEL_SHADOW]
    if nat or sh:
        fig, ax = plt.subplots(figsize=(7.2, 3.2))
        jit = np.random.default_rng(report["settings"]["seed"])
        for y, vals, color, name in ((1, nat, _NATURAL, "Natural"), (0, sh, _SHADOW, "Shadow")):
            if vals:
                ax.scatter(
                    vals,
                    y + jit.uniform(-0.18, 0.18, size=len(vals)),
                    s=36,
                    color=color,
                    edgecolor=_SURFACE,
                    linewidth=1,
                    label=name,
                    zorder=3,
                )
        _ref_lines(ax, 1.55)
        ax.set_yticks([0, 1])
        ax.set_yticklabels(["Shadow", "Natural"])
        _style(
            ax,
            f"{SCORE_COLUMN} by attempt kind (conclusive attempts; higher = less consistent)",
            SCORE_COLUMN,
            "",
        )
        ax.set_xlim(SCORE_MIN - 0.02, SCORE_MAX + 0.02)
        ax.set_ylim(-0.6, 1.6)
        ax.legend(loc="lower left", frameon=False, fontsize=8, labelcolor=_TEXT, ncol=2)
        _save(fig, "distributions", "score_distributions.png")

    # Per-student gap (dumbbell)
    studs = [s for s in report["per_student"]["students"] if s["gap"] is not None]
    if studs:
        studs.sort(key=lambda s: (s["gap"], s["claimed_student_id"]))
        fig, ax = plt.subplots(figsize=(7.2, max(2.8, 0.28 * len(studs) + 1.2)))
        ys = np.arange(len(studs))
        for y, s in zip(ys, studs, strict=False):
            ax.plot(
                [s["shadow_mean"], s["natural_mean"]], [y, y], color=_GRID, linewidth=2, zorder=1
            )
        ax.scatter(
            [s["natural_mean"] for s in studs],
            ys,
            s=40,
            color=_NATURAL,
            edgecolor=_SURFACE,
            linewidth=1,
            label="Natural mean",
            zorder=3,
        )
        ax.scatter(
            [s["shadow_mean"] for s in studs],
            ys,
            s=40,
            color=_SHADOW,
            edgecolor=_SURFACE,
            linewidth=1,
            label="Shadow mean",
            zorder=3,
        )
        ax.set_yticks(ys)
        ax.set_yticklabels([s["claimed_student_id"] for s in studs], fontsize=7)
        _style(ax, "Each student's natural vs shadow mean (same baseline)", SCORE_COLUMN, "")
        ax.set_xlim(SCORE_MIN - 0.02, SCORE_MAX + 0.02)
        ax.legend(
            loc="upper center",
            bbox_to_anchor=(0.5, -0.1),
            frameon=False,
            fontsize=8,
            labelcolor=_TEXT,
            ncol=2,
        )
        _save(fig, "gaps", "per_student_gap.png")

    # Feature separation (single series, no legend)
    top = report["feature_importance"]["tested"][:FEATURE_TOP_N]
    if top:
        top = list(reversed(top))
        fig, ax = plt.subplots(figsize=(7.2, max(2.8, 0.3 * len(top) + 1.2)))
        ys = np.arange(len(top))
        ax.barh(ys, [f["separation"] for f in top], color=_NATURAL, height=0.6)
        for y, f in zip(ys, top, strict=False):
            q_label = "q<0.01" if f["bh_q"] < 0.005 else f"q={f['bh_q']:.2f}"
            ax.text(f["separation"] + 0.01, y, q_label, va="center", fontsize=7, color=_TEXT_2)
        ax.set_yticks(ys)
        ax.set_yticklabels([f["feature"] for f in top], fontsize=7)
        _style(ax, "Feature separation, natural vs shadow (exploratory)", "|AUC - 0.5| x 2", "")
        ax.set_xlim(0, 1.1)
        _save(fig, "features", "feature_separation.png")

    return files


# ── CLI ───────────────────────────────────────────────────────────────────────


def run(
    csv_path: str | Path,
    out_dir: str | Path,
    *,
    cap: float = DEFAULT_CAP,
    n_bootstrap: int = DEFAULT_BOOTSTRAP,
    n_permutations: int = DEFAULT_PERMUTATIONS,
    seed: int = DEFAULT_SEED,
    charts: bool = True,
    created_at: str | None = None,
    fictional: bool | None = None,
) -> dict:
    if not 0 < cap < 1:
        raise ValueError(f"cap must be in (0, 1), got {cap}")
    data = load_study_csv(csv_path)
    if fictional is None:
        fictional = looks_fictional(data)
    current = load_current_operating_point()
    settings = EvalSettings(
        live_flag_if_score_below=float(current["flag_rule"]["flag_if_score_below"]),
        reference_cutoffs=reference_cutoffs(current),
        cap=float(cap),
        n_bootstrap=int(n_bootstrap),
        n_permutations=int(n_permutations),
        seed=int(seed),
        fictional=bool(fictional),
    )
    report = evaluate(data, settings)
    if created_at is None:
        created_at = os.environ.get("SOURCE_DATE_EPOCH") or "unrecorded (deterministic output)"
    report["experiment"] = _experiment(report, created_at)

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    chart_files = render_charts(report, out / "charts") if charts else {}
    report["charts"] = chart_files or None
    (out / "study_eval.json").write_text(json.dumps(report, indent=2) + "\n")
    md = render_markdown(report, chart_files)
    if charts and not chart_files:
        md += "\nCharts were skipped: matplotlib is not installed (requirements-dev.txt).\n"
    (out / "study_eval.md").write_text(md)
    return report


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Evaluate a natural/shadow study CSV.")
    p.add_argument(
        "--csv", required=True, help=f"study CSV ({CONTRACT_VERSION}, validation/study_contract.py)"
    )
    p.add_argument(
        "--out-dir", default="validation/study/out", help="report directory (git-ignored)"
    )
    p.add_argument(
        "--cap",
        type=float,
        default=DEFAULT_CAP,
        help="false-flag cap drawn on charts (default 0.05)",
    )
    p.add_argument("--bootstrap", type=int, default=DEFAULT_BOOTSTRAP)
    p.add_argument("--permutations", type=int, default=DEFAULT_PERMUTATIONS)
    p.add_argument("--seed", type=int, default=DEFAULT_SEED)
    p.add_argument("--no-charts", action="store_true")
    p.add_argument("--created-at", default=None, help="timestamp recorded in the experiment spec")
    p.add_argument(
        "--fictional",
        action="store_true",
        default=None,
        help="label the report FICTIONAL DATA (automatic when every writer id is synth-NN)",
    )
    args = p.parse_args(argv)
    if not 0 < args.cap < 1:
        p.error(f"--cap must be in (0, 1), got {args.cap}")
    from validation.study_contract import StudyContractError

    try:
        report = run(
            args.csv,
            args.out_dir,
            cap=args.cap,
            n_bootstrap=args.bootstrap,
            n_permutations=args.permutations,
            seed=args.seed,
            charts=not args.no_charts,
            created_at=args.created_at,
            fictional=args.fictional,
        )
    except StudyContractError as e:
        print(str(e), file=sys.stderr)
        return 2
    a = report["auc"]
    ff = report["confusion_at_verdict"]["false_flag_rate_conclusive"]
    ca = report["confusion_at_verdict"]["catch_rate_conclusive"]
    print(f"wrote {Path(args.out_dir) / 'study_eval.md'}")
    print(
        f"AUC on {SCORE_COLUMN} {a['value']} (student bootstrap 95% {a['ci95']}); live verdict: "
        f"false flags {ff['k']}/{ff['n']}, caught {ca['k']}/{ca['n']}"
    )
    print(
        "Small sample: read the intervals, not the point estimates (see the report's first section)."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
