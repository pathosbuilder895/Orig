"""mailer.py — account email (invites and password resets) via SendGrid.

Scope is deliberately narrow. This module sends exactly two kinds of message:
an invitation to set a Bluebook password, and a password-reset link. Both
carry a one-time link and nothing about a student's work or any score.
Scoring notifications remain a documented no-op
(``routers/_shared.py:_send_notification_email``) — that is a policy decision
for institutions and this module does not touch it.

**No-op without config**, like every other integration here: unless
``SENDGRID_API_KEY`` and ``MAIL_FROM`` are both set, ``send()`` returns False
without opening a socket, and callers fall back to showing the link to the
teacher. A delivery failure is logged and also returns False; it never raises
into a request handler.

Uses SendGrid's v3 HTTP API over ``urllib`` — no SDK dependency — so the
pilot's slim requirements are unchanged.

Env:
    SENDGRID_API_KEY  API key with Mail Send permission.
    MAIL_FROM         Verified sender, e.g. "Bluebook <no-reply@example.edu>".
    PUBLIC_BASE_URL   Absolute site origin for links, e.g. "https://bluebook.example.com".
                      Falls back to the request's own origin when unset.
"""

from __future__ import annotations

import json
import logging
import os
import re
import urllib.error
import urllib.request

log = logging.getLogger(__name__)

SENDGRID_URL = "https://api.sendgrid.com/v3/mail/send"
_TIMEOUT_SECONDS = 10


def configured() -> bool:
    return bool(os.environ.get("SENDGRID_API_KEY", "").strip()) and bool(
        os.environ.get("MAIL_FROM", "").strip()
    )


def _parse_from(value: str) -> dict:
    """'Name <addr@x>' or 'addr@x' -> SendGrid's {email, name?}."""
    m = re.match(r"^\s*(.*?)\s*<\s*([^>]+?)\s*>\s*$", value)
    if m:
        out = {"email": m.group(2)}
        if m.group(1):
            out["name"] = m.group(1).strip('"')
        return out
    return {"email": value.strip()}


def absolute_url(path: str, request_base: str = "") -> str:
    """An absolute link for an email. PUBLIC_BASE_URL wins; otherwise the
    origin the request arrived on."""
    base = (os.environ.get("PUBLIC_BASE_URL", "").strip() or request_base or "").rstrip("/")
    return f"{base}{path}" if base else path


def send(to: str, subject: str, text: str) -> bool:
    """Send one plain-text email. True only when SendGrid accepted it."""
    if not configured() or not to:
        return False
    body = {
        "personalizations": [{"to": [{"email": to}]}],
        "from": _parse_from(os.environ["MAIL_FROM"]),
        "subject": subject,
        "content": [{"type": "text/plain", "value": text}],
        # Invite and reset links are one-time credentials: never rewrite them
        # through a click-tracking redirect.
        "tracking_settings": {"click_tracking": {"enable": False, "enable_text": False}},
    }
    req = urllib.request.Request(
        SENDGRID_URL,
        data=json.dumps(body).encode(),
        headers={
            "Authorization": f"Bearer {os.environ['SENDGRID_API_KEY'].strip()}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT_SECONDS) as resp:  # noqa: S310
            ok = 200 <= resp.status < 300
    except urllib.error.HTTPError as e:
        log.warning("account email not sent: SendGrid returned %s", e.code)
        return False
    except Exception as e:  # network, DNS, timeout
        log.warning("account email not sent: %s", type(e).__name__)
        return False
    if not ok:
        log.warning("account email not sent: unexpected SendGrid status")
    return ok


def send_invite(to: str, link: str, course: str = "", teacher: str = "") -> bool:
    who = teacher or "Your teacher"
    where = f" for {course}" if course else ""
    text = (
        f"{who} has added you to Bluebook{where}.\n\n"
        f"Set your password here (this link works once and expires in 14 days):\n{link}\n\n"
        "Then sign in with this email address to see your examinations.\n\n"
        "If you were not expecting this, you can ignore this email."
    )
    return send(to, f"You've been added to Bluebook{where}", text)


def send_reset(to: str, link: str) -> bool:
    text = (
        "Someone asked to reset the password for this Bluebook account.\n\n"
        f"Choose a new password here (this link works once and expires in 14 days):\n{link}\n\n"
        "If you did not ask for this, you can ignore this email; your password is unchanged."
    )
    return send(to, "Reset your Bluebook password", text)
