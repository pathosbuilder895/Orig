"""Propose a CANDIDATE flag threshold (and tier weights) from a study eval.

    python scripts/propose_thresholds.py --eval validation/study/out/study_eval.json
    python scripts/propose_thresholds.py --eval EVAL.json --cap 0.02 --out-dir DIR
    python scripts/propose_thresholds.py --eval EVAL.json --fresh-cohort-eval LOCK.json

Reads the JSON written by ``validation/study_eval.py`` and writes two files:

  candidate_operating_point.json       same schema as the committed
                                       validation/study/current_operating_point.json,
                                       kind "candidate", plus the evidence it
                                       was chosen on and the exact inputs gate
                                       G-S1 reads (``gate_inputs``)
  candidate_operating_point.diff.md    what changes against the current
                                       artifact, the trade-off, and the gate
                                       verdict the candidate would get

It NEVER writes the live artifact: an output path that resolves to the
current artifact, or lands under ``original/`` or ``demo/``, is refused, and
an existing candidate is only replaced with ``--force``. Adopting a candidate
is a separate, owner-approved change to Exam.jsx and the snapshot, after
gate G-S1 passes (NORTH_STAR rule 4).

Threshold rule. Flag when the consistency score is below the cut-off. Among
cut-offs whose false-flag rate on conclusive natural attempts is at most
``--cap`` (default 5%), take the one that catches the most shadow attempts;
among cut-offs that catch the same number, take the lowest, which leaves
the widest margin below every natural attempt. If no cut-off within the cap
catches anything, the candidate flags nothing (cut-off 0).

The in-sample numbers flatter the choice: it was made on those rows. So the
script repeats the whole selection leave-one-student-out (each student's
attempts are judged at a cut-off chosen without them), and that out-of-sample
count is what ``gate_inputs`` carries. With ``--fresh-cohort-eval`` the frozen
cut-off is instead applied to a second, untouched cohort, and that is the
evidence the gate reads. "Untouched" is checked: a fresh cohort that shares a
submission or a student (writer or claimed) with the training cohort is
refused, because re-exported training rows would pass by construction.

Weights. ``--weights unchanged`` (default) copies the current tier weights:
the study's scores were computed under them, so a threshold chosen on those
scores is only valid for them. ``--weights study`` derives advisory tier
factors from the eval's feature separation (shrunk toward 1 for a small
cohort, clipped to [0.5, 2.0], sum of squared weights over active features
preserved). Gate G-S1 never judges a weight change: the factors were fitted
on this cohort, so re-scoring it would be in-sample. A weight change needs a
FRESH cohort scored under the candidate weights and the score-changing-flag
process in validation/README.md.

Deterministic: no clock reads; the same eval JSON gives the same bytes.
"""

from __future__ import annotations

import argparse
import copy
import difflib
import hashlib
import json
import math
import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from validation.power import wilson_interval  # noqa: E402

CURRENT_ARTIFACT = _ROOT / "validation" / "study" / "current_operating_point.json"
DEFAULT_OUT_DIR = _ROOT / "validation" / "study" / "candidates"
CANDIDATE_NAME = "candidate_operating_point.json"
DIFF_NAME = "candidate_operating_point.diff.md"
PROTECTED_DIRS = ("original", "demo")
EVAL_SCHEMA = "study-eval-v1"
DEFAULT_CAP = 0.05
GRID = tuple(range(0, 102))
TRADE_OFF_CAPS = (0.0, 0.01, 0.02, 0.05, 0.10)
WEIGHT_SHRINK_K = 20  # factor shrinkage n/(n+K): at 20 students half the raw effect survives
WEIGHT_CLIP = (0.5, 2.0)
FDR_ALPHA = 0.10
COMPARED_FIELDS = (
    "score_field",
    "flag_rule",
    "inconclusive_rule",
    "action_thresholds",
    "tier_weights",
    "disabled_tiers",
)


class ProposalError(ValueError):
    pass


# ── selection ─────────────────────────────────────────────────────────────────


def _count_below(scores: list[float], t: float) -> int:
    return sum(1 for s in scores if s < t)


def false_flag_allowance(n_natural: int, cap: float) -> int:
    """How many natural attempts a cut-off may flag at this cap and n."""
    return math.floor(cap * n_natural + 1e-9)


def select_threshold(
    natural: list[float], shadow: list[float], cap: float, max_false_flags: int | None = None
) -> dict:
    """The cut-off rule in the module docstring, over whole-point cut-offs.
    The cap is applied as a count of allowed false flags: ``max_false_flags``
    when given (the leave-one-student-out folds pass the full cohort's
    allowance, so a fold with one natural attempt fewer is not held to a
    stricter rule than the candidate), else floor(cap * n)."""
    if not natural or not shadow:
        return {
            "threshold": 0,
            "false_flags": 0,
            "catches": 0,
            "n_natural": len(natural),
            "n_shadow": len(shadow),
            "note": "no conclusive attempts of one kind; flag nothing",
        }
    allowed = (
        false_flag_allowance(len(natural), cap) if max_false_flags is None else max_false_flags
    )
    best_t, best_c = 0, -1
    for t in GRID:
        ff = _count_below(natural, t)
        if ff > allowed:
            break  # the false-flag count only grows with t
        c = _count_below(shadow, t)
        if c > best_c:
            best_t, best_c = t, c
    out = {
        "threshold": best_t,
        "false_flags": _count_below(natural, best_t),
        "catches": best_c,
        "n_natural": len(natural),
        "n_shadow": len(shadow),
    }
    if best_c == 0:
        out["threshold"] = 0
        out["false_flags"] = 0
        out["note"] = "no cut-off within the cap catches any shadow attempt; flag nothing"
    return out


def _rate(k: int, n: int) -> dict:
    if n <= 0:
        return {"k": k, "n": n, "rate": None, "wilson95": None}
    lo, hi = wilson_interval(k, n)
    return {"k": k, "n": n, "rate": round(k / n, 4), "wilson95": [round(lo, 4), round(hi, 4)]}


def _split(rows: list[dict]) -> tuple[list[float], list[float]]:
    nat = [r["score"] for r in rows if r["conclusive"] and r["label"] == "natural"]
    sh = [r["score"] for r in rows if r["conclusive"] and r["label"] == "shadow"]
    return nat, sh


def _students_with(rows: list[dict], label: str | None = None) -> int:
    """Distinct claimed students with at least one conclusive attempt (of
    `label`, when given): the units the gate's intervals and floor count."""
    return len(
        {
            r["claimed_student_id"]
            for r in rows
            if r["conclusive"] and (label is None or r["label"] == label)
        }
    )


def leave_one_student_out(rows: list[dict], cap: float) -> dict:
    """Re-run the selection once per claimed student without that student's
    attempts, and judge their attempts at the cut-off chosen without them.
    Every fold may flag as many natural attempts as the full cohort may
    (floor(cap * n) over ALL conclusive natural attempts): applying the cap as
    a rate to a fold's smaller n would hold the folds to a stricter rule than
    the candidate and understate its false flags."""
    students = sorted({r["claimed_student_id"] for r in rows if r["conclusive"]})
    allowed = false_flag_allowance(len(_split(rows)[0]), cap)
    ff = n_nat = caught = n_sh = 0
    thresholds = []
    for s in students:
        train = [r for r in rows if r["claimed_student_id"] != s]
        test = [r for r in rows if r["claimed_student_id"] == s]
        t = select_threshold(*_split(train), cap, max_false_flags=allowed)["threshold"]
        thresholds.append(t)
        nat, sh = _split(test)
        ff += _count_below(nat, t)
        n_nat += len(nat)
        caught += _count_below(sh, t)
        n_sh += len(sh)
    ts = sorted(thresholds)
    return {
        "kind": "leave_one_student_out",
        "false_flag_allowance": allowed,
        "folds": len(students),
        "students": len(students),
        "natural_students": _students_with(rows, "natural"),
        "shadow_students": _students_with(rows, "shadow"),
        "false_flags": _rate(ff, n_nat),
        "catches": _rate(caught, n_sh),
        "fold_thresholds": (
            {"min": ts[0], "median": ts[len(ts) // 2], "max": ts[-1]} if ts else None
        ),
        "note": (
            "each student's attempts are judged at a cut-off chosen without them; shadow "
            "attempts that student WROTE against classmates stay in training"
        ),
    }


def fresh_cohort(fresh: dict, threshold: int) -> dict:
    nat, sh = _split(fresh["rows"])
    return {
        "kind": "fresh_cohort",
        "eval_input_sha256": fresh["input"]["sha256"],
        "students": _students_with(fresh["rows"]),
        "natural_students": _students_with(fresh["rows"], "natural"),
        "shadow_students": _students_with(fresh["rows"], "shadow"),
        "false_flags": _rate(_count_below(nat, threshold), len(nat)),
        "catches": _rate(_count_below(sh, threshold), len(sh)),
        "auc": fresh["auc"]["value"],
        "auc_ci95": fresh["auc"]["ci95"],
    }


# ── weights ───────────────────────────────────────────────────────────────────


def study_weights(current: dict, ev: dict) -> dict:
    """Advisory tier factors from the eval's feature separation. A tier's raw
    factor is 1 + (median separation of its features with BH q <= 0.10),
    shrunk toward 1 by n/(n+20) students and clipped to [0.5, 2.0]; then
    every active tier is rescaled so the sum of squared PER-FEATURE weights
    over active features is unchanged (a mean-1 normalisation inflates that
    sum and shifts every score; see the LENGTH_WEIGHT_SCHEDULE note in
    original/constants.py). Disabled tiers are left exactly as they are."""
    from original.constants import FEATURE_TIER

    disabled = set(current.get("disabled_tiers", []))
    weights = {int(k): float(v) for k, v in current["tier_weights"].items()}
    n_students = ev["counts"]["claimed_students"]
    shrink = n_students / (n_students + WEIGHT_SHRINK_K)
    per_tier: dict[int, list[float]] = {}
    for f in ev["feature_importance"].get("tested", []):
        if f["bh_q"] <= FDR_ALPHA:
            per_tier.setdefault(int(f["tier"]), []).append(float(f["separation"]))
    raw = {}
    for t in weights:
        seps = sorted(per_tier.get(t, []))
        med = seps[len(seps) // 2] if seps else 0.0
        factor = 1.0 + med * shrink
        raw[t] = min(WEIGHT_CLIP[1], max(WEIGHT_CLIP[0], factor)) if t not in disabled else 1.0
    counts: dict[int, int] = {}
    for tier in FEATURE_TIER.values():
        counts[int(tier)] = counts.get(int(tier), 0) + 1
    active = [t for t in weights if t not in disabled]
    before = sum(counts.get(t, 0) * weights[t] ** 2 for t in active)
    after = sum(counts.get(t, 0) * (weights[t] * raw[t]) ** 2 for t in active)
    alpha = math.sqrt(before / after) if after > 0 else 1.0
    new = {}
    for t in sorted(weights):
        new[str(t)] = weights[t] if t in disabled else round(weights[t] * raw[t] * alpha, 4)
    return {
        "tier_weights": new,
        "factors": {str(t): round(raw[t], 4) for t in sorted(raw)},
        "rescale": round(alpha, 6),
        "shrink": round(shrink, 4),
        "tiers_with_evidence": sorted(per_tier),
    }


# ── artifact + diff ───────────────────────────────────────────────────────────


def _sha256_json(obj: dict) -> str:
    return hashlib.sha256(json.dumps(obj, sort_keys=True).encode()).hexdigest()


def _check_disjoint(train: list[dict], fresh: list[dict]) -> None:
    """A fresh cohort shares no submission and no student with the cohort the
    cut-off was chosen on; otherwise it is the training data again."""
    shared_subs = {r["submission_id"] for r in train} & {r["submission_id"] for r in fresh}
    if shared_subs:
        raise ProposalError(f"the fresh cohort repeats {len(shared_subs)} training submission(s)")

    def people(rows):
        return {r["claimed_student_id"] for r in rows} | {r["writer_student_id"] for r in rows}

    shared_people = people(train) & people(fresh)
    if shared_people:
        raise ProposalError(
            f"the fresh cohort shares {len(shared_people)} student(s) with the training cohort; "
            "a fresh cohort must be different students"
        )


def propose(
    ev: dict,
    current: dict,
    *,
    cap: float = DEFAULT_CAP,
    weights: str = "unchanged",
    fresh: dict | None = None,
) -> dict:
    if ev.get("schema") != EVAL_SCHEMA:
        raise ProposalError(
            f"expected an eval report with schema {EVAL_SCHEMA!r}, got {ev.get('schema')!r}"
        )
    if not 0 <= cap < 1:
        raise ProposalError(f"cap must be in [0, 1), got {cap}")
    if weights not in ("unchanged", "study"):
        raise ProposalError(f"weights must be 'unchanged' or 'study', got {weights!r}")
    if current.get("kind") != "current":
        raise ProposalError(
            f"--current must be the committed snapshot (kind 'current'), got kind {current.get('kind')!r}"
        )
    if fresh is not None:
        if fresh.get("schema") != EVAL_SCHEMA:
            raise ProposalError("the fresh-cohort file is not a study eval report")
        if fresh["input"]["sha256"] == ev["input"]["sha256"]:
            raise ProposalError("the fresh cohort is the same CSV the threshold is chosen on")
        _check_disjoint(ev["rows"], fresh["rows"])

    rows = ev["rows"]
    nat, sh = _split(rows)
    chosen = select_threshold(nat, sh, cap)
    t = chosen["threshold"]
    t_now = current["flag_rule"]["flag_if_score_below"]

    trade = []
    for c in sorted(set(TRADE_OFF_CAPS) | {cap}):
        sel = select_threshold(nat, sh, c)
        trade.append(
            {
                "cap": c,
                "threshold": sel["threshold"],
                "false_flags": _rate(sel["false_flags"], len(nat)),
                "catches": _rate(sel["catches"], len(sh)),
            }
        )

    loso = leave_one_student_out(rows, cap)
    fresh_ev = fresh_cohort(fresh, t) if fresh is not None else None
    evidence = fresh_ev or loso

    cand = copy.deepcopy({k: current[k] for k in current if k in COMPARED_FIELDS})
    cand["flag_rule"]["flag_if_score_below"] = t
    cand["flag_rule"]["source"] = "CANDIDATE from scripts/propose_thresholds.py; not live"
    weight_block = {
        "mode": weights,
        "scores_valid_for_candidate": True,
        "note": "copied from the current artifact; the study's scores were computed under these",
    }
    if weights == "study":
        derived = study_weights(current, ev)
        cand["tier_weights"] = derived.pop("tier_weights")
        changed = cand["tier_weights"] != current["tier_weights"]
        weight_block = {
            "mode": "study",
            "scores_valid_for_candidate": not changed,
            **derived,
            "note": (
                "advisory: derived from about 20 students' feature separation. The threshold above "
                "was chosen on scores made under the CURRENT weights, and these factors were fitted "
                "on this cohort, so neither can be checked on it: a weight change needs a FRESH "
                "cohort scored under these weights, and G-S1 does not judge it"
            ),
        }

    in_sample = {
        "threshold": t,
        "false_flags": _rate(chosen["false_flags"], len(nat)),
        "catches": _rate(chosen["catches"], len(sh)),
    }
    current_in_sample = {
        "threshold": t_now,
        "false_flags": _rate(_count_below(nat, t_now), len(nat)),
        "catches": _rate(_count_below(sh, t_now), len(sh)),
    }
    if "note" in chosen:
        in_sample["note"] = chosen["note"]

    gate_inputs = {
        "oos_false_flags": evidence["false_flags"]["k"],
        "oos_natural": evidence["false_flags"]["n"],
        "oos_caught": evidence["catches"]["k"],
        "oos_shadow": evidence["catches"]["n"],
        "auc": (fresh_ev or {}).get("auc", ev["auc"]["value"]),
        "auc_ci95": (fresh_ev or {}).get("auc_ci95", ev["auc"]["ci95"]),
        "n_students": evidence["students"],
        "evidence": evidence["kind"],
        "weights_match_scores": weight_block["scores_valid_for_candidate"],
        "natural_students": evidence["natural_students"],
        "shadow_students": evidence["shadow_students"],
        "selection_cap": cap,
        "candidate_above_folds": bool(
            fresh_ev is None and loso["fold_thresholds"] and t > loso["fold_thresholds"]["max"]
        ),
    }

    candidate = {
        "schema": current.get("schema", "study-operating-point-v1"),
        "kind": "candidate",
        "description": (
            "CANDIDATE operating point proposed from a natural/shadow study. NOT LIVE: nothing reads "
            "this file except validation/calibration_gate.py gate G-S1. Adopting it is an "
            "owner-approved change to demo/bluebook/Exam.jsx and the current snapshot."
        ),
        **cand,
        "derived_from": {
            "proposal_script": "scripts/propose_thresholds.py",
            "eval_schema": ev["schema"],
            "eval_input_sha256": ev["input"]["sha256"],
            "eval_report_sha256": _sha256_json(ev),
            "current_artifact_sha256": _sha256_json(current),
            "settings": {"cap": cap, "weights": weights},
        },
        "selection": {
            "rule": (
                "flag when score < cut-off; most shadow catches with natural false flags <= cap; "
                "ties go to the lowest cut-off"
            ),
            "cap": cap,
            "in_sample": in_sample,
            "current_in_sample": current_in_sample,
            "trade_off": trade_off_text(in_sample, current_in_sample, cap),
            "trade_off_table": trade,
            "warning": "in-sample: chosen on these rows, so these numbers flatter the choice",
        },
        "out_of_sample": {"leave_one_student_out": loso, "fresh_cohort": fresh_ev},
        "separation": {"auc": ev["auc"]["value"], "auc_ci95": ev["auc"]["ci95"]},
        "weights": weight_block,
        "gate_inputs": gate_inputs,
    }
    candidate["gate_preview"] = _gate_preview(gate_inputs)
    return candidate


def _gate_preview(gate_inputs: dict) -> dict:
    from dataclasses import asdict

    from validation.calibration_gate import evaluate_g_s1_study_operating_point

    return asdict(evaluate_g_s1_study_operating_point(**gate_inputs))


def min_natural_to_demonstrate(cap: float) -> int:
    """Conclusive natural attempts needed before even zero false flags put
    the Wilson 95% upper bound at or below the cap."""
    if not 0 < cap < 1:
        raise ProposalError(f"cap must be in (0, 1) to be demonstrable, got {cap}")
    n = 1
    while wilson_interval(0, n)[1] > cap:
        n += 1
    return n


def _verdict_note(verdict: str, cap: float, evidence: str = "leave_one_student_out") -> str:
    if verdict == "fail":
        return (
            "A FAIL is a measurement and is never downgraded: out of sample, this candidate "
            "misses at least one pre-registered criterion (the legs above say which)."
        )
    if verdict == "uninformative":
        return (
            f"UNINFORMATIVE is the expected verdict for a study of about 20 students: showing a "
            f"false-flag rate at or below {cap:.0%} with 95% confidence needs conclusive natural "
            f"attempts from {min_natural_to_demonstrate(cap)} different students with none flagged. "
            "It is not a pass."
        )
    if evidence != "fresh_cohort":
        return (
            "PASS on leave-one-student-out evidence. That is not adoption evidence: only a "
            "fresh-cohort PASS is (docs/research/STUDY_PROTOCOL_2026-10.md section 7)."
        )
    return (
        "PASS on a fresh cohort. Adoption still needs the owner's approval, a shadow measurement on "
        "live submissions, and the change to demo/bluebook/Exam.jsx and the snapshot "
        "(docs/research/STUDY_PROTOCOL_2026-10.md section 7)."
    )


def _fold_text(ft: dict | None) -> str:
    if not ft:
        return "n/a"
    return f"{ft['min']}-{ft['max']}, median {ft['median']}"


def _pct(d: dict) -> str:
    return "n/a" if d["rate"] is None else f"{d['k']}/{d['n']} ({d['rate']:.1%})"


def trade_off_text(chosen: dict, now: dict, cap: float) -> str:
    t, t_now = chosen["threshold"], now["threshold"]
    head = (
        f"Holding false flags on natural writing to at most {cap:.0%} means flagging only scores "
        f"below {t}. On this cohort that flags {_pct(chosen['false_flags'])} of natural attempts and "
        f"catches {_pct(chosen['catches'])} of shadow attempts; the live rule (< {t_now}) flags "
        f"{_pct(now['false_flags'])} and catches {_pct(now['catches'])}."
    )
    d_ff = chosen["false_flags"]["k"] - now["false_flags"]["k"]
    d_c = chosen["catches"]["k"] - now["catches"]["k"]
    if t < t_now:
        tail = (
            f" The price of the cap is {-d_c} fewer shadow catches for {-d_ff} fewer false flags: "
            f"every shadow attempt scoring {t} or more passes unflagged."
        )
    elif t > t_now:
        tail = (
            f" This candidate is MORE aggressive than the live rule: {d_c} more shadow catches "
            f"for {d_ff} more false flags on honest writing. It stays within the cap on this "
            "cohort only; read the out-of-sample numbers before believing that."
        )
    else:
        tail = " The live rule already sits at this cut-off."
    return head + tail


def render_diff(current: dict, candidate: dict) -> str:
    sel = candidate["selection"]
    oos = candidate["out_of_sample"]
    gp = candidate["gate_preview"]
    lines = [
        "# Candidate operating point (NOT LIVE)",
        "",
        f"Proposed by `scripts/propose_thresholds.py` from eval input sha256 "
        f"`{candidate['derived_from']['eval_input_sha256'][:12]}`, cap {sel['cap']:.0%}, "
        f"weights `{candidate['weights']['mode']}`. Nothing reads this candidate except gate "
        "G-S1; adopting it is a separate, owner-approved change.",
        "",
        "## What changes",
        "",
        "| field | current | candidate |",
        "|---|---|---|",
    ]
    changed = 0
    for key in COMPARED_FIELDS:
        a, b = current.get(key), candidate.get(key)
        if key == "flag_rule":
            a = {k: v for k, v in a.items() if k != "source"}
            b = {k: v for k, v in b.items() if k != "source"}
        if a == b:
            continue
        if isinstance(a, dict) and isinstance(b, dict):
            for k in sorted(set(a) | set(b), key=str):
                if a.get(k) != b.get(k):
                    changed += 1
                    lines.append(f"| `{key}.{k}` | {a.get(k)} | {b.get(k)} |")
        else:
            changed += 1
            lines.append(f"| `{key}` | {a} | {b} |")
    if not changed:
        lines.append("| (none) | | |")
    lsto = oos["leave_one_student_out"]
    lines += [
        "",
        "## Trade-off",
        "",
        sel["trade_off"],
        "",
        "| cap | cut-off | false flags (natural) | caught (shadow) |",
        "|---:|---:|---|---|",
    ]
    for row in sel["trade_off_table"]:
        lines.append(
            f"| {row['cap']:.0%} | {row['threshold']} | {_pct(row['false_flags'])} | {_pct(row['catches'])} |"
        )
    lines += [
        "",
        "These are in-sample: the cut-off was chosen on the same rows.",
        "",
        "## Out of sample",
        "",
        f"Leave-one-student-out ({lsto['folds']} students with conclusive attempts, fold cut-offs "
        f"{_fold_text(lsto['fold_thresholds'])}): "
        f"false flags {_pct(lsto['false_flags'])}, caught {_pct(lsto['catches'])}.",
    ]
    if oos["fresh_cohort"]:
        fc = oos["fresh_cohort"]
        lines.append(
            f"Fresh cohort ({fc['students']} students, input `{fc['eval_input_sha256'][:12]}`): "
            f"false flags {_pct(fc['false_flags'])}, caught {_pct(fc['catches'])}, AUC {fc['auc']}."
        )
    lines += [
        "",
        f"## Gate G-S1 preview: **{gp['verdict'].upper()}**",
        "",
        f"{gp['criterion']}  ",
        f"{gp['current_value']}",
        "",
        _verdict_note(
            gp["verdict"], gp["detail"].get("cap", DEFAULT_CAP), gp["detail"].get("evidence", "")
        ),
        "",
        "## Weights",
        "",
        candidate["weights"]["note"][0].upper() + candidate["weights"]["note"][1:] + ".",
        "",
        "## Exact diff",
        "",
        "```diff",
    ]
    a = json.dumps({k: current.get(k) for k in COMPARED_FIELDS}, indent=2).splitlines()
    b = json.dumps({k: candidate.get(k) for k in COMPARED_FIELDS}, indent=2).splitlines()
    lines += list(
        difflib.unified_diff(a, b, "current_operating_point.json", CANDIDATE_NAME, lineterm="", n=2)
    ) or ["(no change)"]
    lines += ["```", ""]
    return "\n".join(lines)


# ── output guard + CLI ────────────────────────────────────────────────────────


def _same(a: Path, b: Path) -> bool:
    """Same file or directory on disk (inode, not spelling): catches a
    differently cased path on a case-insensitive filesystem and a hard link."""
    try:
        return a.exists() and b.exists() and os.path.samefile(a, b)
    except OSError:
        return False


def check_out_paths(paths: list[Path], current_path: Path, force: bool) -> None:
    live = [current_path, CURRENT_ARTIFACT]
    protected = [_ROOT / d for d in PROTECTED_DIRS]
    for p in paths:
        r = Path(os.path.abspath(p))
        if any(r.resolve() == x.resolve() or _same(r, x) for x in live):
            raise ProposalError(f"refusing to write {p}: that is the current (live) artifact")
        for d in protected:
            for anc in (r, *r.parents):
                if anc.resolve() == d.resolve() or _same(anc, d):
                    raise ProposalError(
                        f"refusing to write {p}: candidates never go under {d.name}/"
                    )
        if r.exists() and not force:
            raise ProposalError(f"{p} exists; pass --force to replace a previous candidate")


def _write_atomic(path: Path, text: str) -> None:
    """Write beside the target, then rename over it: a hard link to some other
    file at `path` is replaced, never written through."""
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text)
    os.replace(tmp, path)


def write_candidate(
    candidate: dict, diff_md: str, out_dir: Path, current_path: Path, force: bool = False
) -> tuple[Path, Path]:
    out_dir = Path(out_dir)
    cand_path, diff_path = out_dir / CANDIDATE_NAME, out_dir / DIFF_NAME
    check_out_paths([cand_path, diff_path], current_path, force)
    out_dir.mkdir(parents=True, exist_ok=True)
    _write_atomic(cand_path, json.dumps(candidate, indent=2) + "\n")
    _write_atomic(diff_path, diff_md)
    return cand_path, diff_path


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description="Propose a candidate flag threshold from a study eval.")
    p.add_argument("--eval", required=True, help="study_eval.json from validation/study_eval.py")
    p.add_argument(
        "--cap",
        type=float,
        default=DEFAULT_CAP,
        help="max false-flag rate on natural attempts (default 0.05)",
    )
    p.add_argument("--weights", choices=("unchanged", "study"), default="unchanged")
    p.add_argument(
        "--fresh-cohort-eval",
        default=None,
        help="study_eval.json of a second, untouched cohort to judge the frozen cut-off on",
    )
    p.add_argument(
        "--current", default=str(CURRENT_ARTIFACT), help="current artifact to diff against"
    )
    p.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    p.add_argument("--force", action="store_true", help="replace an existing candidate")
    args = p.parse_args(argv)
    try:
        ev = json.loads(Path(args.eval).read_text())
        current_path = Path(args.current)
        current = json.loads(current_path.read_text())
        fresh = (
            json.loads(Path(args.fresh_cohort_eval).read_text()) if args.fresh_cohort_eval else None
        )
        candidate = propose(ev, current, cap=args.cap, weights=args.weights, fresh=fresh)
        cand_path, diff_path = write_candidate(
            candidate, render_diff(current, candidate), Path(args.out_dir), current_path, args.force
        )
    except ProposalError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    sel = candidate["selection"]
    print(f"wrote {cand_path}")
    print(f"wrote {diff_path}")
    print(sel["trade_off"])
    print(
        f"gate G-S1 preview: {candidate['gate_preview']['verdict'].upper()} "
        f"({candidate['gate_preview']['current_value']})"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
