"""
student_auth.py — lightweight, stateless student authentication.

Two responsibilities:

1. **Identity derivation.** A student's id is derived deterministically from
   (institution, email): ``{tenant_slug}:{sha256(email)[:16]}``. This is
   FERPA-friendly (the email never appears in the id or in URLs — only an
   opaque hash), institution-scoped (two schools can both have
   jane@example.com without collision), and consistent with the multi-tenant
   ``{tenant_id}:{local_id}`` convention used for tenant scoping. The same
   formula is shared with the Bbook identity bridge.

2. **Sessions.** A signed, stateless session token: ``<payload>.<hmac>``,
   where payload is base64url(JSON{sid, name, exp}) and the signature is
   HMAC-SHA256 over the payload keyed by SECRET_KEY. No session table — the
   token verifies itself. Tamper or expiry → rejected. Sessions minted from
   an account login also carry ``acct``, which lets the principal resolver
   revoke them once the account is erased (see ``mint_session``).

This is the demo/pilot path. The v1 Postgres path uses full JWT (see
original/api/v1/auth.py); both can derive the same student id, so a student
provisioned in either system resolves identically.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import time

_DEFAULT_TTL = 7 * 24 * 3600  # one week


def _secret() -> bytes:
    # Falls back to a fixed dev secret so the demo works without SECRET_KEY,
    # but the startup check warns when SECRET_KEY is unset (see api.py).
    return (os.environ.get("SECRET_KEY") or "demo-insecure-student-secret").encode()


def slugify(text: str) -> str:
    """Turn an institution name into a stable tenant slug."""
    s = (text or "").strip().lower()
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return s or "default"


def derive_student_id(institution: str, email: str) -> str:
    """
    Deterministic, institution-scoped, FERPA-friendly student id.

    Returns ``{tenant_slug}:{16-hex}`` — the prefix ties the student to a
    tenant (so list_ids_for_tenant / tenant_stats see them) and the hash
    hides the email.
    """
    tenant = slugify(institution)
    digest = hashlib.sha256(f"{tenant}:{(email or '').strip().lower()}".encode()).hexdigest()[:16]
    return f"{tenant}:{digest}"


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def _sign(payload: str) -> str:
    return _b64(hmac.new(_secret(), payload.encode(), hashlib.sha256).digest())


def mint_session(
    student_id: str, name: str = "", ttl_seconds: int = _DEFAULT_TTL, account: bool = False
) -> str:
    """Mint a signed session token for a student.

    ``account`` marks a session minted from a password login or invite
    redemption, i.e. one backed by a ``users`` row. Such a session is
    revocable: ``principal.resolve_principal`` rejects it once that row is
    gone (erasure). Launch-link, LTI, and demo sessions have no account row
    by design, carry no claim, and are byte-identical to before."""
    body = {"sid": student_id, "name": name, "exp": int(time.time()) + ttl_seconds}
    if account:
        body["acct"] = 1
    payload = _b64(json.dumps(body, separators=(",", ":")).encode())
    return f"{payload}.{_sign(payload)}"


def verify_session(token: str) -> dict | None:
    """
    Return the session body {sid, name, exp} if the token is valid and
    unexpired, else None. Constant-time signature comparison.
    """
    if not token or "." not in token:
        return None
    payload, sig = token.split(".", 1)
    if not hmac.compare_digest(sig, _sign(payload)):
        return None
    try:
        body = json.loads(_unb64(payload))
    except Exception:
        return None
    if not isinstance(body, dict) or "sid" not in body:
        return None
    # A proctor attestation is signed with the same secret but is NOT a login
    # session — reject it here so it can only unlock a proctored baseline write,
    # never authenticate a request.
    if body.get("typ"):
        return None
    if float(body.get("exp", 0)) < time.time():
        return None
    return body


# ── Phone parking, tied to the student's account (2026-10) ────────────────────
# Two narrow, signed grants. Neither is a login session (``verify_session``
# rejects anything with a ``typ``), and each names exactly one student and one
# collection, so a code scanned from one student's screen can only ever park a
# phone for that student on that collection.
#
#   scan  — shown as a QR code on the student's own briefing. Short-lived: a
#           photo of someone else's screen is useless a few minutes later.
#   beat  — handed to the phone once it has scanned, kept only in that page's
#           memory, and good for one sitting's worth of "the page is open".

PHONE_SCAN_TTL = 10 * 60
PHONE_BEAT_TTL = 6 * 3600


def _mint_typed(typ: str, student_id: str, exam: str, ttl_seconds: int) -> str:
    body = {"typ": typ, "sid": student_id, "exam": exam, "exp": int(time.time()) + ttl_seconds}
    payload = _b64(json.dumps(body, separators=(",", ":")).encode())
    return f"{payload}.{_sign(payload)}"


def _verify_typed(token: str, typ: str) -> dict | None:
    if not token or not isinstance(token, str) or "." not in token:
        return None
    payload, sig = token.split(".", 1)
    if not hmac.compare_digest(sig, _sign(payload)):
        return None
    try:
        body = json.loads(_unb64(payload))
    except Exception:
        return None
    if not isinstance(body, dict) or body.get("typ") != typ:
        return None
    if not body.get("sid") or not body.get("exam"):
        return None
    if float(body.get("exp", 0)) < time.time():
        return None
    return body


_URL_SAFE = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789_-")


def _compact(value: str) -> str:
    """A token field as itself when it is URL-safe, else ``~`` + base64."""
    if value and all(c in _URL_SAFE for c in value):
        return value
    return "~" + _b64(value.encode())


def _uncompact(value: str) -> str | None:
    if value.startswith("~"):
        try:
            return _unb64(value[1:]).decode()
        except Exception:
            return None
    return value


def _scan_sig(payload: str) -> str:
    # Domain-separated from every other grant, and cut to 128 bits so the QR
    # code stays small enough to scan easily from a laptop screen.
    raw = hmac.new(_secret(), ("phonescan|" + payload).encode(), hashlib.sha256).digest()
    return _b64(raw[:16])


def mint_phone_scan_token(student_id: str, exam: str, ttl_seconds: int = PHONE_SCAN_TTL) -> str:
    """A compact signed code ``<student>.<exam>.<expiry>.<sig>`` for a QR code.

    The student's workspace prefix (``tenant:``) is left out: it is always the
    collection's own workspace (the only caller checks that), and the scan
    route puts it back from the collection. Short codes scan far more easily.
    """
    tenant, sep, local = student_id.partition(":")
    who = (
        local
        if sep and local and all(c in _URL_SAFE for c in local)
        else "~" + _b64(student_id.encode())
    )
    exp = int(time.time()) + ttl_seconds
    exp36 = ("-" if exp < 0 else "") + _base36(abs(exp))
    payload = f"{who}.{_compact(exam)}.{exp36}"
    return f"{payload}.{_scan_sig(payload)}"


def _base36(n: int) -> str:
    digits = "0123456789abcdefghijklmnopqrstuvwxyz"
    out = ""
    while True:
        n, r = divmod(n, 36)
        out = digits[r] + out
        if not n:
            return out


def verify_phone_scan_token(token: str) -> dict | None:
    """``{student, student_is_full, exam, exp}`` for a valid, unexpired scan
    code, else None. ``student_is_full`` is False when the workspace prefix
    was left out and must be taken from the collection."""
    if not token or not isinstance(token, str) or token.count(".") != 3:
        return None
    who, exam_c, exp36, sig = token.split(".")
    if not hmac.compare_digest(sig, _scan_sig(f"{who}.{exam_c}.{exp36}")):
        return None
    try:
        exp = -int(exp36[1:], 36) if exp36.startswith("-") else int(exp36, 36)
    except ValueError:
        return None
    if exp < time.time():
        return None
    exam = _uncompact(exam_c)
    full = who.startswith("~")
    student = _uncompact(who) if full else who
    if not exam or not student:
        return None
    return {"student": student, "student_is_full": full, "exam": exam, "exp": exp}


def mint_phone_beat_token(student_id: str, exam: str, ttl_seconds: int = PHONE_BEAT_TTL) -> str:
    return _mint_typed("phonebeat", student_id, exam, ttl_seconds)


def verify_phone_beat_token(token: str) -> dict | None:
    return _verify_typed(token, "phonebeat")


# ── Proctor attestation ───────────────────────────────────────────────────────
# A short-lived, signed grant that a *proctored* baseline write for a specific
# student is authorized. Minted server-side at exam launch (see lti.py) and
# presented by the exam client on POST /students/{id}/baseline. Because a bare
# student session token cannot forge it, a student cannot self-author
# high-trust (proctored/verified/canvas) samples into their own profile.

_PROCTOR_TTL = 6 * 3600  # one exam-day window


def mint_proctor_attestation(
    student_id: str, exam: str = "", ttl_seconds: int = _PROCTOR_TTL
) -> str:
    """Mint a signed proctor attestation authorizing one student's proctored
    baseline writes for a bounded window (issued at exam launch)."""
    body = {
        "typ": "proctor",
        "sid": student_id,
        "exam": exam,
        "exp": int(time.time()) + ttl_seconds,
    }
    payload = _b64(json.dumps(body, separators=(",", ":")).encode())
    return f"{payload}.{_sign(payload)}"


def verify_proctor_attestation(token: str, student_id: str, exam: str | None = None) -> bool:
    """True iff ``token`` is a valid, unexpired proctor attestation issued for
    exactly ``student_id``. Constant-time signature comparison.

    ``exam`` is optional and checked only when given: a caller with an exam
    id to check the token against (a future cross-exam-confusion guard, not
    yet wired to any call site — see ADR discussion at T-69) gets that extra
    check; the existing student+expiry-only call site
    (``routers/_shared.py:_authorize_provenance``) omits it and is
    unaffected, since ``exam=None`` skips the comparison entirely.
    """
    if not token or "." not in token:
        return False
    payload, sig = token.split(".", 1)
    if not hmac.compare_digest(sig, _sign(payload)):
        return False
    try:
        body = json.loads(_unb64(payload))
    except Exception:
        return False
    if not isinstance(body, dict) or body.get("typ") != "proctor":
        return False
    if body.get("sid") != student_id:
        return False
    if exam is not None and body.get("exam") != exam:
        return False
    if float(body.get("exp", 0)) < time.time():
        return False
    return True


def attestation_jti(token: str) -> str:
    """Stable identity for a proctor attestation, for single-use tracking
    (T-69). The signature already binds the payload to ``SECRET_KEY``, so
    hashing just the payload half (not re-deriving or storing the signature)
    is enough: a caller must already hold a validly-signed token to have a
    jti worth consuming, and the raw bearer token itself never touches the
    single-use ledger."""
    payload = token.split(".", 1)[0] if "." in token else token
    return hashlib.sha256(payload.encode()).hexdigest()


def attestation_exam(token: str) -> str:
    """The ``exam`` claim embedded in a proctor attestation, best-effort
    ("" if the token can't be parsed). Recorded on the single-use
    consumption ledger for audit/future cross-checking — this reads the
    claim, it does not verify it against anything by itself."""
    if not token or "." not in token:
        return ""
    try:
        body = json.loads(_unb64(token.split(".", 1)[0]))
    except Exception:
        return ""
    return body.get("exam", "") if isinstance(body, dict) else ""


# ── Magic-link launch token ───────────────────────────────────────────────────
# A signed, self-contained launch credential the offline roster_links.py builds
# (one per student) for the no-Canvas fallback. Redeemed by GET /bluebook/launch,
# which trades it for a short session + a proctor attestation. Because it is
# signed, a student cannot forge a launch for an arbitrary id; because the real
# session/attestation are minted only at redemption, no long-lived bearer token
# is ever placed in the distributed URL.

_LAUNCH_TTL = 14 * 24 * 3600  # links are distributed, then used over the next days


def mint_launch_token(
    student_id: str,
    tenant: str,
    exam: str = "",
    name: str = "",
    ttl_seconds: int = _LAUNCH_TTL,
    exam_id: str = "",
) -> str:
    """Mint a signed Bluebook magic-link launch token binding a student.

    ``exam`` is the display title; ``exam_id`` (optional) names the stored
    exam so the SPA loads its real prompt and timing. Omitted, the claim is
    absent and the token is byte-identical to one minted before it existed."""
    body = {
        "typ": "launch",
        "sid": student_id,
        "tid": tenant,
        "exam": exam,
        "name": name,
        "exp": int(time.time()) + ttl_seconds,
    }
    if exam_id:
        body["eid"] = exam_id
    payload = _b64(json.dumps(body, separators=(",", ":")).encode())
    return f"{payload}.{_sign(payload)}"


def verify_launch_token(token: str) -> dict | None:
    """Return the launch body ``{sid, tid, exam, name, exp}`` if valid and
    unexpired, else None. Constant-time signature comparison."""
    if not token or "." not in token:
        return None
    payload, sig = token.split(".", 1)
    if not hmac.compare_digest(sig, _sign(payload)):
        return None
    try:
        body = json.loads(_unb64(payload))
    except Exception:
        return None
    if not isinstance(body, dict) or body.get("typ") != "launch" or "sid" not in body:
        return None
    if float(body.get("exp", 0)) < time.time():
        return None
    return body
