"""
scripts/pilot_preflight.py — pre-deployment checklist for a pilot launch.

Run this before pointing a seminary at the deployment. Every check prints a
[PASS]/[WARN]/[FAIL] row; the script exits 1 iff any check FAILs. WARNs are
judgment calls documented in docs/PILOT_RUNBOOK.md.

Checks:
  1. Environment — ORIGINAL_ENV, SECRET_KEY, GUARD_DESTRUCTIVE,
     MAINTENANCE_TOKEN, ALLOWED_ORIGINS (non-empty, no '*', https-only).
     These mirror the fail-fast semantics in original/api.py's lifespan.
  2. Database — path writable, WAL journal mode, expected tables present
     (connecting runs the same schema init the app would).
  3. AI-likelihood detector — artifact loads and passes its reference-vector
     check (the sklearn version-skew gate). FAIL if a detector flag is on
     and the load fails; WARN otherwise.
  4. Backup recency — newest profiles-*.db younger than --max-backup-age-hours
     (WARN-only: backups may live off-box).
  5. spaCy model — en_core_web_sm importable (the feature pipeline needs it).

Usage:
    .venv/bin/python scripts/pilot_preflight.py                  # --env pilot default
    .venv/bin/python scripts/pilot_preflight.py --env demo       # relaxed demo profile
    .venv/bin/python scripts/pilot_preflight.py --db /data/profiles.db \
        --backup-dir /data/backups
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path
from typing import List, Tuple

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT))

EXPECTED_TABLES = {
    "student_profiles", "fidelity_scores", "ai_likelihood_scores",
    "corrections", "submission_manifests", "audit_log",
    "tuned_thresholds_v2", "baseline_requests", "users", "tenants",
}

PASS, WARN, FAIL = "PASS", "WARN", "FAIL"


class Checklist:
    def __init__(self) -> None:
        self.rows: List[Tuple[str, str, str]] = []

    def add(self, status: str, name: str, detail: str = "") -> None:
        self.rows.append((status, name, detail))

    def render(self) -> int:
        width = max(len(name) for _, name, _ in self.rows) if self.rows else 0
        n_fail = n_warn = 0
        for status, name, detail in self.rows:
            if status == FAIL:
                n_fail += 1
            elif status == WARN:
                n_warn += 1
            print(f"[{status}] {name.ljust(width)}  {detail}")
        print()
        verdict = "NOT READY" if n_fail else ("READY (with warnings)" if n_warn else "READY")
        print(f"Preflight: {verdict} — "
              f"{len(self.rows)} checks, {n_fail} failed, {n_warn} warnings.")
        return 1 if n_fail else 0


def check_env(cl: Checklist, profile: str) -> None:
    hard = FAIL if profile == "pilot" else WARN

    env = os.environ.get("ORIGINAL_ENV", "")
    cl.add(PASS if env == profile else hard, "ORIGINAL_ENV",
           f"= {env!r} (expected {profile!r})")

    secret = os.environ.get("SECRET_KEY", "")
    if not secret:
        cl.add(hard, "SECRET_KEY", "not set — tokens reset on every restart")
    elif len(secret) < 32:
        cl.add(WARN, "SECRET_KEY", f"only {len(secret)} chars — prefer 64+ "
               "(python -c 'import secrets;print(secrets.token_urlsafe(64))')")
    else:
        cl.add(PASS, "SECRET_KEY", "set")

    guard = os.environ.get("GUARD_DESTRUCTIVE", "")
    cl.add(PASS if guard == "1" else hard, "GUARD_DESTRUCTIVE",
           f"= {guard!r} (destructive endpoints "
           f"{'guarded' if guard == '1' else 'OPEN'})")

    token = os.environ.get("MAINTENANCE_TOKEN", "")
    if guard == "1" and not token:
        cl.add(hard, "MAINTENANCE_TOKEN", "guard is on but no token set")
    else:
        cl.add(PASS, "MAINTENANCE_TOKEN", "set" if token else "n/a (guard off)")

    origins = os.environ.get("ALLOWED_ORIGINS", "")
    parsed = [o.strip() for o in origins.split(",") if o.strip()]
    if not parsed:
        cl.add(hard, "ALLOWED_ORIGINS", "not set — CORS falls back to defaults")
    elif "*" in parsed:
        cl.add(hard, "ALLOWED_ORIGINS", "contains '*' — never in pilot")
    elif any(not o.startswith("https://") for o in parsed):
        cl.add(WARN, "ALLOWED_ORIGINS", f"non-https origin present: {parsed}")
    else:
        cl.add(PASS, "ALLOWED_ORIGINS", ", ".join(parsed))


def check_db(cl: Checklist, db_arg: str) -> None:
    db_path = Path(db_arg or os.environ.get("ORIGINAL_DB", str(_ROOT / "profiles.db")))
    if db_path.name == ":memory:":
        cl.add(WARN, "database", "ORIGINAL_DB=:memory: — nothing persists")
        return
    parent = db_path.parent
    if not parent.exists() or not os.access(parent, os.W_OK):
        cl.add(FAIL, "database", f"parent dir not writable: {parent}")
        return

    os.environ["ORIGINAL_DB"] = str(db_path)
    try:
        import original.store as store
        store._DB_PATH = db_path
        with store._get_conn() as conn:   # runs schema init exactly as the app would
            mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
            tables = {r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        cl.add(PASS if mode.lower() == "wal" else FAIL, "db journal_mode", mode)
        missing = EXPECTED_TABLES - tables
        cl.add(PASS if not missing else FAIL, "db tables",
               "all present" if not missing else f"missing: {sorted(missing)}")
    except Exception as e:
        cl.add(FAIL, "database", f"{type(e).__name__}: {e}")


def check_detector(cl: Checklist, skip: bool) -> None:
    if skip:
        cl.add(WARN, "ai-likelihood detector", "skipped (--skip-detector)")
        return
    flag_on = (os.environ.get("AI_LIKELIHOOD_ENABLED") == "1"
               or os.environ.get("AI_LIKELIHOOD_SHADOW") == "1")
    try:
        from original.ai_likelihood import reset_for_tests, warm
        reset_for_tests()
        ok = warm()
    except Exception as e:
        ok = False
        cl.add(FAIL if flag_on else WARN, "ai-likelihood detector",
               f"import failed: {e}")
        return
    if ok:
        cl.add(PASS, "ai-likelihood detector",
               "artifact loads + reference-vector check passes")
    else:
        cl.add(FAIL if flag_on else WARN, "ai-likelihood detector",
               "artifact unavailable or failed validation"
               + (" — a detector flag is ON" if flag_on else
                  " (flags are off, so not blocking)"))


def check_backups(cl: Checklist, backup_dir: str, max_age_hours: float) -> None:
    bdir = Path(backup_dir)
    if not bdir.is_dir():
        cl.add(WARN, "backups", f"no backup dir at {bdir} — configure "
               "scripts/backup_db.sh in cron (see docs/PILOT_RUNBOOK.md)")
        return
    backups = sorted(bdir.glob("profiles-*.db"), key=lambda p: p.stat().st_mtime)
    if not backups:
        cl.add(WARN, "backups", f"{bdir} contains no profiles-*.db files")
        return
    age_h = (time.time() - backups[-1].stat().st_mtime) / 3600
    cl.add(PASS if age_h <= max_age_hours else WARN, "backups",
           f"newest is {age_h:.1f}h old ({backups[-1].name})")


def check_spacy(cl: Checklist) -> None:
    try:
        import spacy
        ok = spacy.util.is_package("en_core_web_sm")
    except Exception as e:
        cl.add(FAIL, "spacy en_core_web_sm", f"spacy import failed: {e}")
        return
    cl.add(PASS if ok else FAIL, "spacy en_core_web_sm",
           "installed" if ok else "missing — run: python -m spacy download en_core_web_sm")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--env", default="pilot", choices=["pilot", "demo"],
                    help="Expected ORIGINAL_ENV profile (pilot = env checks FAIL, "
                         "demo = they WARN).")
    ap.add_argument("--db", default="", help="Database path (default: $ORIGINAL_DB).")
    ap.add_argument("--backup-dir", default=str(_ROOT / "backups"))
    ap.add_argument("--max-backup-age-hours", type=float, default=26.0)
    ap.add_argument("--skip-detector", action="store_true")
    args = ap.parse_args(argv)

    cl = Checklist()
    check_env(cl, args.env)
    check_db(cl, args.db)
    check_detector(cl, args.skip_detector)
    check_backups(cl, args.backup_dir, args.max_backup_age_hours)
    check_spacy(cl)
    return cl.render()


if __name__ == "__main__":
    sys.exit(main())
