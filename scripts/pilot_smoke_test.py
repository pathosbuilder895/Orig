#!/usr/bin/env python3
"""
pilot_smoke_test.py — WS-6 P5 post-cutover smoke test.

Run this against the live pilot service **immediately after flipping
REPO_BACKEND=postgres and unfreezing** (the last step of the P5 cutover, before
telling professors the window is closed). It is read-only — it never writes —
and exits non-zero on any failure so it can gate the window.

Checks (see WS-6 P5 acceptance criteria):
  1. GET /health returns status "ok".
  2. /health.backend == "postgres" — the cutover env flip actually took. If it
     still says "sqlite" the flip didn't apply; roll back / investigate.
  3. student count is present and, if --expect-count is given, matches the
     pre-cutover count (the migration report's student_profiles row count) --
     the single strongest signal that the data came across.
  4. (optional, with --token + --student) a known student profile is served
     from Postgres with a 200 -- proves an authenticated read path end to end.

Usage
-----
    python -m scripts.pilot_smoke_test \
        --base-url https://original-pilot.onrender.com \
        --expect-count 128 \
        [--token <operator-bearer-token> --student "sem:alice"]

FERPA: with --token you are fetching a real student record; run from a trusted
machine over TLS, and don't log the response.
"""

from __future__ import annotations

import argparse
import json
import urllib.error
import urllib.request


def _http_get(base_url: str, path: str, token: str | None = None) -> tuple[int, object]:
    """(status_code, parsed_json_or_text). Never raises on an HTTP error
    status -- returns the code so the checks can report it cleanly."""
    req = urllib.request.Request(base_url.rstrip("/") + path, method="GET")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = resp.read().decode("utf-8")
            status = resp.status
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        status = e.code
    try:
        return status, json.loads(body)
    except json.JSONDecodeError:
        return status, body


def run_smoke(fetch, *, expect_count: int | None = None, student: str | None = None) -> dict:
    """Run the checks using ``fetch(path) -> (status, json)``. Returns a report
    dict with a top-level ``ok`` and a per-check list. Pure of I/O specifics so
    it's unit-testable against a TestClient as well as the real service."""
    checks: list[dict] = []

    def record(name, ok, detail):
        checks.append({"check": name, "ok": ok, "detail": detail})

    status, health = fetch("/health")
    health = health if isinstance(health, dict) else {}
    record(
        "health_reachable",
        status == 200 and health.get("status") == "ok",
        f"status={status} health.status={health.get('status')!r}",
    )
    record(
        "backend_is_postgres",
        health.get("backend") == "postgres",
        f"backend={health.get('backend')!r} (want 'postgres')",
    )

    count = health.get("students_in_store")
    if expect_count is None:
        record("student_count_present", isinstance(count, int), f"students_in_store={count!r}")
    else:
        record(
            "student_count_matches",
            count == expect_count,
            f"students_in_store={count!r} expected={expect_count}",
        )

    if student is not None:
        s_status, _ = fetch(f"/students/{student}")
        record("known_student_served", s_status == 200, f"GET /students/{student} -> {s_status}")

    return {"ok": all(c["ok"] for c in checks), "checks": checks}


def _render(report: dict) -> str:
    lines = []
    for c in report["checks"]:
        lines.append(f"[{'PASS' if c['ok'] else 'FAIL'}] {c['check']}: {c['detail']}")
    lines.append(f"\nsmoke test: {'PASS' if report['ok'] else 'FAIL'}")
    return "\n".join(lines)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="WS-6 P5 post-cutover smoke test (read-only).")
    parser.add_argument(
        "--base-url", required=True, help="e.g. https://original-pilot.onrender.com"
    )
    parser.add_argument("--expect-count", type=int, help="pre-cutover student_profiles row count")
    parser.add_argument("--token", help="operator bearer token for the known-student check")
    parser.add_argument("--student", help="a known scoped student id to spot-check (needs --token)")
    args = parser.parse_args(argv)

    def fetch(path):
        return _http_get(args.base_url, path, token=args.token)

    report = run_smoke(fetch, expect_count=args.expect_count, student=args.student)
    print(_render(report))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
