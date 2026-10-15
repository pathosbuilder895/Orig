#!/usr/bin/env python3
"""Exercise the local professor-invite and student-join flow against localhost only."""
from __future__ import annotations

import argparse
import sys
from urllib.parse import parse_qs, urlparse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def invite_token(invite_path: str) -> str:
    values = parse_qs(urlparse(invite_path).query).get("invite", [])
    if len(values) != 1:
        raise ValueError("invite path must contain exactly one ?invite= token")
    return values[0]


def ensure_local_base(base_url: str) -> str:
    parsed = urlparse(base_url)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("this verifier only permits http://localhost, 127.0.0.1, or [::1]")
    return base_url.rstrip("/")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("invite_path", help="local professor invite URL path containing ?invite=...")
    parser.add_argument("--base-url", default="http://127.0.0.1:8001", help="local API URL (localhost only)")
    parser.add_argument("--password", default="alpha-local-Passw0rd!", help="temporary password for this local rehearsal")
    args = parser.parse_args(argv)
    try:
        base = ensure_local_base(args.base_url)
        token = invite_token(args.invite_path)
    except ValueError as exc:
        parser.error(str(exc))

    import requests

    def check(label, response, expected=200):
        if response.status_code != expected:
            print(f"FAIL {label}: expected {expected}, got {response.status_code}: {response.text[:300]}")
            raise RuntimeError(label)
        print(f"PASS {label}: {response.status_code}")
        if "json" in response.headers.get("content-type", ""):
            return response.json()
        return None

    headers = lambda bearer: {"Authorization": f"Bearer {bearer}"}
    try:
        check("invite page", requests.get(base + args.invite_path, timeout=10))
        check("terms required", requests.post(base + "/auth/invite/redeem", json={"token": token, "password": args.password}, timeout=10), 422)
        teacher = check("teacher invite redemption", requests.post(base + "/auth/invite/redeem", json={"token": token, "password": args.password, "accept_terms": True}, timeout=10))
        if "bluebook" not in teacher.get("products", []):
            raise RuntimeError("teacher invite did not create a Collections workspace")
        print("PASS Collections workspace present")
        teacher_token = teacher["token"]
        course = check("course creation", requests.post(base + "/bluebook/courses", json={"name": "Alpha test", "code": "ALPHA1"}, headers=headers(teacher_token), timeout=10), 201)
        conditions = {"blockCopy": True, "blockAI": True, "blockWeb": False, "aiDetect": False, "spellChk": True}
        exam = check("25-minute exam creation", requests.post(base + "/bluebook/exams", json={"title": "Practice prompt", "status": "ACTIVE", "duration": 25, "questions": ["Describe a city that exists only at night."], "conditions": conditions, "course_id": course["id"]}, headers=headers(teacher_token), timeout=10), 201)
        students = check("student roster creation", requests.post(base + f"/bluebook/courses/{course['id']}/students", json={"students": [{"email": "local-volunteer@example.test", "name": "Local Volunteer"}], "send_email": False}, headers=headers(teacher_token), timeout=10))["students"]
        invite = students[0]["invite_path"]
        check("student invite redemption", requests.post(base + "/auth/invite/redeem", json={"token": invite_token(invite), "password": args.password}, timeout=10))
        student = check("student login", requests.post(base + "/auth/login", json={"email": students[0]["email"], "password": args.password}, timeout=10))
        student_headers = headers(student["token"])
        check("student exam visibility", requests.get(base + "/bluebook/me/exams", headers=student_headers, timeout=10))
        check("student starts exam", requests.post(base + f"/bluebook/me/exams/{exam['id']}/start", headers=student_headers, timeout=10))
        sealed = check("student seals exam", requests.post(base + "/bluebook/submissions", json={"exam_id": exam["id"], "student_id": student.get("user_id") or student.get("student_id"), "word_count": 30, "text": "night city " * 15}, headers=student_headers, timeout=10), 201)
        print(f"PASS local join flow completed; sealed submission {sealed.get('id')}")
        return 0
    except (requests.RequestException, RuntimeError, KeyError, IndexError) as exc:
        if not isinstance(exc, RuntimeError):
            print(f"FAIL local join flow: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
