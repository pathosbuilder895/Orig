"""
tests/test_student_auth.py — student identity derivation + stateless sessions.

Covers: deterministic, institution-scoped, FERPA-friendly id derivation;
signed-session mint/verify; tamper and expiry rejection; slugify.
"""

from __future__ import annotations

import time

from original import student_auth as sa


# ── slugify ───────────────────────────────────────────────────────────────────

class TestSlugify:
    def test_basic(self):
        assert sa.slugify("Wycliffe College") == "wycliffe-college"

    def test_punctuation_collapsed(self):
        assert sa.slugify("St. Mary's  Seminary!") == "st-mary-s-seminary"

    def test_empty_defaults(self):
        assert sa.slugify("") == "default"
        assert sa.slugify("   ") == "default"


# ── derive_student_id ─────────────────────────────────────────────────────────

class TestDeriveStudentId:
    def test_format_is_tenant_prefixed(self):
        sid = sa.derive_student_id("Wycliffe College", "andrew@wycliffe.edu")
        assert sid.startswith("wycliffe-college:")
        # 16 hex chars after the prefix
        assert len(sid.split(":", 1)[1]) == 16

    def test_deterministic_and_case_insensitive(self):
        a = sa.derive_student_id("Wycliffe College", "andrew@wycliffe.edu")
        b = sa.derive_student_id("Wycliffe College", "  Andrew@Wycliffe.EDU ")
        assert a == b

    def test_institution_scoped(self):
        a = sa.derive_student_id("Wycliffe College", "jane@example.com")
        b = sa.derive_student_id("Other Seminary",  "jane@example.com")
        assert a != b

    def test_email_not_present_in_id(self):
        sid = sa.derive_student_id("Wycliffe College", "andrew@wycliffe.edu")
        assert "andrew" not in sid and "wycliffe.edu" not in sid

    def test_prefix_matches_slugify(self):
        sid = sa.derive_student_id("St. Mary's Seminary", "x@y.edu")
        assert sid.split(":", 1)[0] == sa.slugify("St. Mary's Seminary")


# ── sessions ──────────────────────────────────────────────────────────────────

class TestSessions:
    def test_mint_verify_roundtrip(self):
        tok = sa.mint_session("sem:alice", "Alice")
        body = sa.verify_session(tok)
        assert body["sid"] == "sem:alice"
        assert body["name"] == "Alice"
        assert body["exp"] > time.time()

    def test_tamper_rejected(self):
        tok = sa.mint_session("sem:alice", "Alice")
        # Flip the payload (everything before the dot)
        payload, sig = tok.split(".", 1)
        forged = payload[:-2] + ("AA" if not payload.endswith("AA") else "BB") + "." + sig
        assert sa.verify_session(forged) is None

    def test_bad_signature_rejected(self):
        tok = sa.mint_session("sem:alice", "Alice")
        assert sa.verify_session(tok[:-3] + "zzz") is None

    def test_garbage_rejected(self):
        assert sa.verify_session("garbage") is None
        assert sa.verify_session("") is None
        assert sa.verify_session("no-dot-here") is None

    def test_expiry_rejected(self):
        tok = sa.mint_session("sem:alice", "Alice", ttl_seconds=-5)
        assert sa.verify_session(tok) is None

    def test_secret_change_invalidates(self, monkeypatch):
        tok = sa.mint_session("sem:alice", "Alice")
        assert sa.verify_session(tok) is not None
        monkeypatch.setenv("SECRET_KEY", "a-different-secret-entirely")
        # Signed under the old secret → rejected under the new one
        assert sa.verify_session(tok) is None
