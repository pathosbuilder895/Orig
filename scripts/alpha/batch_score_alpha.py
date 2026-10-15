#!/usr/bin/env python3
"""Post-session batch scoring for the alpha (DRAFT).

1. EXPORT (read-only, staff token, against the alpha workspace only):
   GET /bluebook/exams/{exam}/export        -> sealed texts (CSV); --exam may repeat
   GET /students                            -> roster + sample counts (tenant-scoped)
   GET /students/{sid}/samples/{i}/text     -> each baseline sample
2. SCORE OFFLINE on this machine with scripts/score_documents.py (same
   /students/{id}/score code path, in-process demo app, throwaway SQLite;
   never the pilot DB). Pilot DB env vars are stripped from the child.
3. CHECKS: score ranges [0,1], NaN/inf, determinism (2 runs), timing,
   baseline-size effect (first 3 samples vs all), baseline minimums (>=3, >=300 words).
4. ACCURACY vs a staff-only label CSV (--labels): submission_id,label,true_author
   label = natural | not_own. Outputs false-flag rate (natural), catch rate
   (not_own), confusion matrix at the strict threshold (action in
   schedule_conversation/escalate), a lenient one (+monitor), a deviation
   threshold sweep, INCONCLUSIVE rate (baseline < 3 samples or < 300 words,
   the app's own "not enough reference" rule), bootstrap 95% CIs, and a
   pre-registered PASS/FAIL (default: <=1 false flag per 20 natural AND
   catch >= 75%, i.e. >=15/20).
   Injected known-other-author texts: drop them in
   export/<student>/submission/<any-id>.txt and add a label row.
5. REPORT: out/report.md + out/per_submission.csv keyed by opaque ids
   (no names/emails). For Andrew only; never shown to students.

Usage:
  ALPHA_TOKEN=<teacher bearer> python batch_score_alpha.py \
      --base-url https://original-pilot.onrender.com --exam <natural_exam> --exam <second_exam> \
      --labels labels.csv \
      --repo /path/to/Orig --out alpha_scores/
  --from-dir alpha_scores/export   re-score an existing export without network.
"""
from __future__ import annotations
import argparse, csv, io, json, math, os, statistics, subprocess, sys, tempfile, time
from pathlib import Path

DROP_ENV = ("DATABASE_URL", "REPO_BACKEND", "ORIGINAL_DB", "SHADOW_DATABASE_URL")


def export(base, token, exams, dest: Path):
    import requests
    h = {"Authorization": f"Bearer {token}"}
    rows = []
    for exam in exams:
        r = requests.get(f"{base}/bluebook/exams/{exam}/export", headers=h, timeout=60); r.raise_for_status()
        rows += list(csv.DictReader(io.StringIO(r.text)))
    roster = requests.get(f"{base}/students", headers=h, timeout=60); roster.raise_for_status()
    counts = {s["id"]: s.get("sample_count", 0) for s in roster.json().get("roster", [])}
    for row in rows:
        sid = row["student_id"]; d = dest / sid.replace(":", "_")
        (d / "baseline").mkdir(parents=True, exist_ok=True); (d / "submission").mkdir(exist_ok=True)
        (d / "submission" / f"{row['submission_id']}.txt").write_text(row["text"] or "")
        for i in range(int(counts.get(sid, 0))):
            s = requests.get(f"{base}/students/{sid}/samples/{i}/text", headers=h, timeout=60)
            if s.ok:
                (d / "baseline" / f"{i:02d}.txt").write_text(s.json().get("text", ""))
    (dest / "manifest.json").write_text(json.dumps({"exams": exams, "submissions": len(rows)}, indent=2))
    return dest


def score(repo: Path, bdir: Path, sdir: Path, sid: str):
    env = {k: v for k, v in os.environ.items() if k not in DROP_ENV}
    tmp = Path(tempfile.mkdtemp(prefix="alpha_score_"))
    env.update(ORIGINAL_DB=str(tmp / "p.db"), ORIGINAL_ENV="demo", PYTHONPATH=str(repo))
    out = tmp / "r.json"; t0 = time.time()
    p = subprocess.run([sys.executable, str(repo / "scripts/score_documents.py"), "--baseline-dir", str(bdir),
                        "--score-dir", str(sdir), "--student-id", "alpha_" + sid[-12:], "--out", str(out)],
                       cwd=repo, env=env, capture_output=True, text=True)
    if p.returncode or not out.exists():
        return None, time.time() - t0, p.stderr[-400:]
    return json.loads(out.read_text()), time.time() - t0, ""


STRICT = {"schedule_conversation", "escalate"}
LENIENT = STRICT | {"monitor"}


def bad(x):
    return x is None or (isinstance(x, float) and (math.isnan(x) or math.isinf(x)))


def rate(k, n):
    return f"{k}/{n} ({100*k/n:.0f}%)" if n else "0/0"


def wilson(k, n, z=1.96):
    if not n:
        return (float("nan"), float("nan"))
    p = k / n; d = 1 + z*z/n; c = p + z*z/(2*n); h = z*math.sqrt(p*(1-p)/n + z*z/(4*n*n))
    return (max(0.0, (c-h)/d), min(1.0, (c+h)/d))


def boot_ci(items, stat, n=2000, seed=0):
    """Percentile bootstrap over students (cluster resample) -> (lo, hi)."""
    import random
    rng = random.Random(seed); keys = sorted(items); vals = []
    for _ in range(n):
        smp = [x for _ in keys for x in items[rng.choice(keys)]]
        v = stat(smp)
        if v is not None:
            vals.append(v)
    if not vals:
        return (float("nan"), float("nan"))
    vals.sort(); return vals[int(.025*len(vals))], vals[int(.975*len(vals)) - 1]


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url"); ap.add_argument("--exam", action="append", default=[])
    ap.add_argument("--from-dir", type=Path); ap.add_argument("--labels", type=Path)
    ap.add_argument("--repo", type=Path, default=Path(__file__).resolve().parents[1])
    ap.add_argument("--out", type=Path, default=Path("alpha_scores"))
    ap.add_argument("--max-false-flag-rate", type=float, default=1/20)
    ap.add_argument("--min-catch-rate", type=float, default=0.75)
    ap.add_argument("--no-rerun", action="store_true", help="skip the determinism rerun")
    a = ap.parse_args(argv); a.out = a.out.resolve(); a.out.mkdir(parents=True, exist_ok=True)
    if a.from_dir:
        exp = a.from_dir.resolve()
    else:
        tok = os.environ.get("ALPHA_TOKEN") or sys.exit("set ALPHA_TOKEN")
        exp = export(a.base_url.rstrip("/"), tok, a.exam, a.out / "export")
    labels = {}
    if a.labels:
        for r in csv.DictReader(open(a.labels)):
            lab = r["label"].strip().lower()
            if lab not in ("natural", "not_own"):
                sys.exit(f"bad label {lab!r} for {r['submission_id']}")
            labels[r["submission_id"].strip()] = (lab, r.get("true_author", "").strip())
    rows, problems, timing = [], [], []
    for d in sorted(p for p in exp.iterdir() if p.is_dir()):
        sid = d.name; bl = sorted((d / "baseline").glob("*.txt")); sub = d / "submission"
        subs = sorted(sub.glob("*.txt")) if sub.is_dir() else []
        words = [len(f.read_text().split()) for f in bl]
        enough = len(bl) >= 3 and sum(words) >= 300
        base = {"student": sid, "n_baselines": len(bl), "baseline_words": sum(words)}
        if not bl or not subs:
            for f in subs or [None]:
                rows.append({**base, "submission_id": f.stem if f else "", "error": "no baselines or no paper"})
            continue
        r1, t1, e1 = score(a.repo, d / "baseline", sub, sid); timing.append(t1)
        r2 = None if a.no_rerun else score(a.repo, d / "baseline", sub, sid)[0]
        r3 = None
        if len(bl) > 3:  # baseline-size effect: first 3 samples only
            t3 = Path(tempfile.mkdtemp(prefix="alpha_b3_"))
            for f in bl[:3]:
                (t3 / f.name).write_text(f.read_text())
            r3 = score(a.repo, t3, sub, sid)[0]
        if not r1:
            for f in subs:
                rows.append({**base, "submission_id": f.stem, "error": e1})
            continue
        by = lambda r: {Path(x["filename"]).stem: x for x in (r or {}).get("submissions", [])}
        s1, s2, s3 = by(r1), by(r2), by(r3)
        for f in subs:
            x = s1.get(f.stem, {}); lab, author = labels.get(f.stem, ("", ""))
            row = {**base, "submission_id": f.stem, "label": lab, "true_author": author,
                   "deviation": x.get("deviation_score"), "authorship_probability": x.get("authorship_probability"),
                   "action": x.get("recommended_action"), "score_ms": x.get("scoring_time_ms"),
                   "inconclusive": not enough, "error": x.get("error")}
            row["strict_flag"] = (row["action"] in STRICT) and enough
            row["lenient_flag"] = (row["action"] in LENIENT) and enough
            if f.stem in s2:
                row["deterministic"] = (s2[f.stem]["deviation_score"] == row["deviation"]
                                        and s2[f.stem]["authorship_probability"] == row["authorship_probability"])
                if not row["deterministic"]:
                    problems.append(f"{sid}/{f.stem}: rerun differs")
            if f.stem in s3:
                row["deviation_first3"] = s3[f.stem]["deviation_score"]
            for k in ("deviation", "authorship_probability"):
                v = row[k]
                if bad(v) or not (0 <= v <= 1):
                    problems.append(f"{sid}/{f.stem}: {k}={v} out of range/NaN")
            if a.labels and not lab:
                problems.append(f"{sid}/{f.stem}: no label row")
            rows.append(row)
        if not enough:
            problems.append(f"{sid}: baseline below minimum ({len(bl)} samples, {sum(words)} words) -> INCONCLUSIVE")

    keys = sorted({k for r in rows for k in r})
    with open(a.out / "per_submission.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=keys); w.writeheader(); w.writerows(rows)

    scored = [r for r in rows if not bad(r.get("deviation"))]
    devs = [r["deviation"] for r in scored]
    eff = [abs(r["deviation"] - r["deviation_first3"]) for r in scored if "deviation_first3" in r]
    md = ["# Alpha batch scoring report (internal, never shown to students)", "",
          f"- submissions: {len(rows)}; scored: {len(scored)}; errors: {sum(1 for r in rows if r.get('error'))}",
          f"- INCONCLUSIVE (baseline below minimum): {rate(sum(1 for r in rows if r.get('inconclusive')), len(rows))}",
          (f"- deviation min/median/max: {min(devs):.3f} / {statistics.median(devs):.3f} / {max(devs):.3f}" if devs else "- no scores"),
          f"- deterministic on rerun: {sum(1 for r in scored if r.get('deterministic'))}/{len(scored)}" + (" (rerun skipped)" if a.no_rerun else ""),
          f"- scoring time: per paper max {max((r['score_ms'] or 0 for r in scored), default=0):.0f} ms; per student run (incl. app start) max {max(timing, default=0):.1f} s",
          (f"- baseline-size effect |dev(all) - dev(first 3)|: mean {statistics.mean(eff):.3f}, max {max(eff):.3f} (n={len(eff)})" if eff else "- baseline-size effect: n/a (nobody has >3 samples)")]
    passed = None
    if a.labels:
        lab = [r for r in scored if r.get("label") and not r.get("inconclusive")]
        nat = [r for r in lab if r["label"] == "natural"]; own = [r for r in lab if r["label"] == "not_own"]
        ff = sum(r["strict_flag"] for r in nat); ct = sum(r["strict_flag"] for r in own)
        per = {}
        for r in lab:
            per.setdefault(r["student"], []).append(r)
        ffr = lambda smp: (lambda n: sum(r["strict_flag"] for r in n) / len(n) if n else None)([r for r in smp if r["label"] == "natural"])
        cr = lambda smp: (lambda n: sum(r["strict_flag"] for r in n) / len(n) if n else None)([r for r in smp if r["label"] == "not_own"])
        flo, fhi = boot_ci(per, ffr); clo, chi = boot_ci(per, cr)
        lff = sum(r["lenient_flag"] for r in nat); lct = sum(r["lenient_flag"] for r in own)
        passed = bool(nat and own and ff / len(nat) <= a.max_false_flag_rate and ct / len(own) >= a.min_catch_rate)
        md += ["", "## Accuracy against labels (strict = schedule_conversation/escalate; INCONCLUSIVE excluded)",
               f"- **False flags on own work:** {rate(ff, len(nat))}, 95% Wilson {wilson(ff,len(nat))[0]:.0%}–{wilson(ff,len(nat))[1]:.0%}; student-bootstrap {flo:.0%}–{fhi:.0%}",
               f"- **Caught not-own work:** {rate(ct, len(own))}, 95% Wilson {wilson(ct,len(own))[0]:.0%}–{wilson(ct,len(own))[1]:.0%}; student-bootstrap {clo:.0%}–{chi:.0%}",
               "  (bootstrap collapses to a point when every paper agrees; read the Wilson interval)",
               f"- lenient (+monitor): false flags {rate(lff, len(nat))}, caught {rate(lct, len(own))}",
               "", "| strict | flagged | not flagged |", "|---|---|---|",
               f"| not_own | {ct} (TP) | {len(own)-ct} (FN) |", f"| natural | {ff} (FP) | {len(nat)-ff} (TN) |",
               "", "### Deviation threshold sweep (flag if deviation >= t)", "| t | caught | false flags |", "|---|---|---|"]
        for t in [i / 20 for i in range(1, 20)]:
            md.append(f"| {t:.2f} | {rate(sum(r['deviation'] >= t for r in own), len(own))} | {rate(sum(r['deviation'] >= t for r in nat), len(nat))} |")
        md += ["", f"### Pre-registered criteria: false-flag rate <= {a.max_false_flag_rate:.0%} AND catch rate >= {a.min_catch_rate:.0%}",
               f"**{'PASS' if passed else 'FAIL'}** on the point estimates.",
               "", "> Small-sample caveat: with ~20 natural and ~20 not-own papers, each paper is 5 points of rate and the "
               "95% intervals above are wide (0/20 false flags is still compatible with ~15%). Treat a PASS as "
               "\"no red flags in the math on real writing\", not as validated accuracy. Fix the criteria before "
               "the session and do not tune thresholds on this same data and then re-score it."]
    md += ["", "## Problems", *(f"- {p}" for p in problems or ["none"]), "",
           "| student | submission | label | baselines | words | deviation | dev(first3) | action | strict flag | det |",
           "|---|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        dv = r.get("deviation"); d3 = r.get("deviation_first3")
        md.append(f"| {r['student'][-8:]} | {r['submission_id'][:10]} | {r.get('label','')} | {r['n_baselines']} | {r['baseline_words']} | "
                  f"{'-' if dv is None else f'{dv:.3f}'} | {'-' if d3 is None else f'{d3:.3f}'} | "
                  f"{'INCONCLUSIVE' if r.get('inconclusive') else r.get('action', r.get('error','-'))} | {r.get('strict_flag','-')} | {r.get('deterministic','-')} |")
    (a.out / "report.md").write_text("\n".join(md) + "\n")
    print("\n".join(md[:40])); print(f"\nWrote {a.out/'report.md'} and per_submission.csv")
    hard = any("NaN" in p or "rerun" in p for p in problems)
    return 2 if hard else (0 if passed in (None, True) else 1)


if __name__ == "__main__":
    sys.exit(main())
