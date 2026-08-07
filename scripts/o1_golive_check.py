#!/usr/bin/env python3
"""
o1_golive_check.py — O1 deploy verification (pre-cutover).

Run this against the pilot service immediately after the blueprint deploy
lands, and again within 48h of any later deploy that precedes an exam. It is
read-only, unauthenticated, and exits non-zero on any failure.

This is the *pre*-cutover companion to ``scripts/pilot_smoke_test.py``. That
one asserts ``backend == "postgres"`` and so fails by design until the WS-6 P5
cutover (O4) has happened; this one asserts the O1 end state instead.

Checks (from the O1 line of the pilot launch master plan and
``docs/PROVISIONING_CHECKLIST.md`` §4):
  1. /health → 200, status "ok", environment "pilot", backend "sqlite".
  2. /health.commit matches --expect-commit, if given — proves the deploy is
     running the revision you think it is.
  3. /lti/jwks publishes exactly one key, with kid --expect-kid if given. The
     kid is sha256() of the PEM *text* (original/lti.py), so a mismatch here
     almost always means the LTI_PRIVATE_KEY paste picked up or lost a
     trailing newline rather than that the key itself is wrong.
  4. Anonymous lockdown: the six §4 spot-checks. If any of these is reachable,
     STOP — the deploy is not running this build.
  5. HSTS present, and CORS does not echo a hostile Origin.

Usage
-----
    python -m scripts.o1_golive_check \
        --base-url https://original-pilot.onrender.com \
        --expect-kid 7939c6c8a6f9a736 \
        [--expect-commit <sha>]
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request

# (path, expected_status) — docs/PROVISIONING_CHECKLIST.md §4
LOCKDOWN = [
    ("/students", 401),
    ("/students/sem:anything", 403),
    ("/admin/audit", 401),
    ("/tenants", 401),
    ("/seed.db", 404),
    ("/lab.html", 404),
]

HOSTILE_ORIGIN = "https://evil.example"


def _get(base_url, path, headers=None):
    """(status, body, headers). Never raises on an HTTP error status."""
    req = urllib.request.Request(base_url.rstrip("/") + path)
    for k, v in (headers or {}).items():
        req.add_header(k, v)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, resp.read().decode("utf-8", "replace"), dict(resp.headers)
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace"), dict(e.headers)
    except Exception as e:  # network/DNS/TLS
        return 0, f"{type(e).__name__}: {e}", {}


def run_checks(get, expect_kid=None, expect_commit=None):
    """Yield (name, ok, detail). ``get`` is (path, headers) -> (status, body, headers)."""
    status, body, _ = get("/health", None)
    try:
        health = json.loads(body)
    except Exception:
        health = {}
    yield (
        "health_reachable",
        status == 200 and health.get("status") == "ok",
        (f"status={status} health.status={health.get('status')!r}"),
    )
    yield (
        "environment_is_pilot",
        health.get("environment") == "pilot",
        (f"environment={health.get('environment')!r} (want 'pilot')"),
    )
    # Pre-cutover this must still be sqlite. If it says postgres, O4 already
    # ran and you should be using pilot_smoke_test.py instead.
    yield (
        "backend_is_sqlite",
        health.get("backend") == "sqlite",
        (f"backend={health.get('backend')!r} (want 'sqlite' pre-cutover)"),
    )
    if expect_commit:
        got = str(health.get("commit") or "")
        yield (
            "commit_matches",
            got.startswith(expect_commit[:7]),
            (f"commit={got!r} (want {expect_commit[:7]}...)"),
        )

    status, body, _ = get("/lti/jwks", None)
    try:
        keys = json.loads(body).get("keys", [])
    except Exception:
        keys = []
    yield "jwks_has_one_key", len(keys) == 1, f"{len(keys)} key(s) published"
    if expect_kid:
        got_kid = keys[0].get("kid") if keys else None
        yield (
            "jwks_kid_matches",
            got_kid == expect_kid,
            (
                f"kid={got_kid!r} (want {expect_kid!r}); a mismatch usually means the "
                "LTI_PRIVATE_KEY paste gained or lost a trailing newline"
            ),
        )

    for path, want in LOCKDOWN:
        status, _, _ = get(path, None)
        yield f"lockdown{path}", status == want, f"got {status}, want {want}"

    _, _, headers = get("/health", None)
    hsts = {k.lower(): v for k, v in headers.items()}.get("strict-transport-security")
    yield "hsts_present", bool(hsts), f"strict-transport-security={hsts!r}"

    _, _, headers = get("/health", {"Origin": HOSTILE_ORIGIN})
    acao = {k.lower(): v for k, v in headers.items()}.get("access-control-allow-origin")
    yield (
        "cors_rejects_hostile_origin",
        acao != HOSTILE_ORIGIN,
        (f"access-control-allow-origin={acao!r} for Origin: {HOSTILE_ORIGIN}"),
    )


def main(argv=None):
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--base-url", required=True, help="e.g. https://original-pilot.onrender.com")
    p.add_argument("--expect-kid", default=None, help="JWKS kid from the env sheet")
    p.add_argument("--expect-commit", default=None, help="deployed git sha (prefix ok)")
    args = p.parse_args(argv)

    def get(path, headers):
        return _get(args.base_url, path, headers)

    failed = 0
    for name, ok, detail in run_checks(get, args.expect_kid, args.expect_commit):
        print(f"[{'PASS' if ok else 'FAIL'}] {name}: {detail}")
        failed += not ok

    print()
    if failed:
        print(f"O1 go-live check: FAIL ({failed} failing)")
        print("Per docs/PROVISIONING_CHECKLIST.md: if a lockdown check is reachable, STOP —")
        print("the deploy is not running this build.")
        return 1
    print("O1 go-live check: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
