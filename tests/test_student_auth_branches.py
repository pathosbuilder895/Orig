"""
tests/test_student_auth_branches.py — branch-coverage completion for
original/student_auth.py's three token verifiers.

verify_launch_token, verify_proctor_attestation, and verify_session all
share one shape: split on "." → constant-time HMAC signature check → JSON
decode (guarded by `except Exception`) → typed claim checks → expiry check.
Between them, three other test files already close most of that shape:

- tests/test_bluebook_branches.py exercises verify_launch_token's
  missing-token, expired, bad-signature, malformed(no-dot), and
  present-but-empty-sid arms at the HTTP layer
  (GET /bluebook/launch → bluebook_magic_launch).
- tests/test_student_auth.py exercises verify_session's tamper,
  bad-signature, garbage/empty/no-dot, expiry, and secret-rotation arms.
- tests/test_baseline_provenance_authz.py exercises
  verify_proctor_attestation's bad-signature and wrong-sid arms, plus the
  cross-token-type arms shared with verify_session (a proctor attestation
  fed to verify_session, and a session token fed to verify_proctor_attestation).

What's left after all of that (confirmed by a scoped coverage run —
`pytest tests/test_bluebook_branches.py tests/test_phone_park.py
tests/test_voice_leak.py tests/test_staff_auth.py $(grep -rl "student_auth"
tests/) --cov=original.student_auth --cov-branch --cov-report=term-missing`,
which reported `Missing 94-95, 97, 137, 143-144, 150, 195-196, 198` and
`missing_branches [[96, 97], [136, 137], [149, 150], [197, 198]]` via
`coverage json`):

- verify_session: the `except Exception` JSON-decode-failure arm (94-95)
  and the `not isinstance(body, dict) or "sid" not in body` True arm
  (96->97).
- verify_proctor_attestation: the `not token or "." not in token` True arm
  (136->137), the `except Exception` arm (143-144), and the expiry True
  arm (149->150).
- verify_launch_token: the `except Exception` arm (195-196) and the
  `not isinstance(body, dict) or body.get("typ") != "launch" or "sid" not
  in body` True arm (197->198).

Every token here is minted with the module's own helpers: the public
`mint_session`/`mint_proctor_attestation` for well-formed claim sets, and
the private `_b64`/`_sign` pair (the same primitives `mint_*` is built
from) for the malformed/off-shape bodies no public mint function can
produce. Both read SECRET_KEY through student_auth._secret() same as
production — nothing here hardcodes a secret or a signature.

These are security controls: every assertion below pins the DENY side
(None/False on bad input), matching how the module is actually relied on.
"""

from __future__ import annotations

import json
import time

from original import student_auth as sa

_SID = "sem:branchcheck"


def _sign_body(body: dict) -> str:
    """Mint a validly-signed token for an arbitrary claim body, bypassing
    the public mint_* helpers (which only ever produce well-formed claims)
    so the claim-check arms can be reached directly."""
    payload = sa._b64(json.dumps(body, separators=(",", ":")).encode())
    return f"{payload}.{sa._sign(payload)}"


def _sign_raw(raw: bytes) -> str:
    """Mint a validly-signed token whose payload bytes are not valid JSON
    at all, to reach the `except Exception` decode-failure arm."""
    payload = sa._b64(raw)
    return f"{payload}.{sa._sign(payload)}"


# ── verify_session: remaining arms ──────────────────────────────────────────


class TestVerifySessionRemainingArms:
    def test_malformed_json_payload_rejected(self):
        """student_auth.py:94-95 — a payload that carries a genuine
        signature but whose decoded bytes are not valid JSON must be
        caught by `except Exception` and rejected, not raise out of
        verify_session."""
        token = _sign_raw(b"{not json at all")
        assert sa.verify_session(token) is None

    def test_body_missing_sid_rejected(self):
        """student_auth.py:96-97 — a validly-signed, well-formed JSON
        object that never got a "sid" key must be rejected, not KeyError
        on the caller's body["sid"] access."""
        token = _sign_body({"name": "no sid here", "exp": time.time() + 3600})
        assert sa.verify_session(token) is None

    def test_body_not_a_dict_rejected(self):
        """Same arm (96-97), the other disjunct: JSON decodes cleanly but
        to a list, not an object."""
        token = _sign_raw(json.dumps(["not", "a", "dict"]).encode())
        assert sa.verify_session(token) is None


# ── verify_proctor_attestation: remaining arms ──────────────────────────────


class TestVerifyProctorAttestationRemainingArms:
    def test_empty_and_dotless_tokens_rejected(self):
        """student_auth.py:136-137 — a falsy token and a token with no "."
        both take the same short-circuit rejection before any decoding is
        attempted."""
        assert sa.verify_proctor_attestation("", _SID) is False
        assert sa.verify_proctor_attestation("no-dot-here", _SID) is False

    def test_malformed_json_payload_rejected(self):
        """student_auth.py:143-144 — the except Exception arm."""
        token = _sign_raw(b"{not json at all")
        assert sa.verify_proctor_attestation(token, _SID) is False

    def test_expired_attestation_rejected(self):
        """student_auth.py:149-150 — a validly-signed attestation correctly
        bound to this student, but whose exp has already passed."""
        token = sa.mint_proctor_attestation(_SID, "exam-1", ttl_seconds=-10)
        assert sa.verify_proctor_attestation(token, _SID) is False


# ── verify_launch_token: remaining arms ─────────────────────────────────────


class TestVerifyLaunchTokenRemainingArms:
    def test_malformed_json_payload_rejected(self):
        """student_auth.py:195-196 — the except Exception arm."""
        token = _sign_raw(b"{not json at all")
        assert sa.verify_launch_token(token) is None

    def test_body_not_a_dict_rejected(self):
        """student_auth.py:197-198, first disjunct: JSON decodes cleanly
        but to a list, not an object."""
        token = _sign_raw(json.dumps(["not", "a", "dict"]).encode())
        assert sa.verify_launch_token(token) is None

    def test_wrong_typ_rejected_via_session_token(self):
        """student_auth.py:197-198, second disjunct — token confusion: a
        plain login session token (no "typ" claim at all) must not be
        redeemable as a launch token."""
        token = sa.mint_session(_SID, "Some Student")
        assert sa.verify_launch_token(token) is None

    def test_wrong_typ_rejected_via_proctor_attestation(self):
        """Same disjunct, the other token type that must not cross over:
        a proctor attestation ("typ": "proctor") is not a launch token."""
        token = sa.mint_proctor_attestation(_SID, "exam-1")
        assert sa.verify_launch_token(token) is None

    def test_missing_sid_rejected(self):
        """student_auth.py:197-198, third disjunct — a correctly-typed
        body that never got a "sid" key at all. Distinct from
        tests/test_bluebook_branches.py::test_launch_missing_sid_400,
        where the "sid" key is present but its value is empty."""
        token = _sign_body(
            {
                "typ": "launch",
                "tid": "sem",
                "exam": "",
                "name": "",
                "exp": time.time() + 3600,
            }
        )
        assert sa.verify_launch_token(token) is None
