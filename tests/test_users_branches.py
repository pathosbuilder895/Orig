"""
tests/test_users_branches.py — original/users.py, staff email+password auth.

No dedicated unit-test file existed for this module — it's exercised via the
`/auth/*` endpoints in tests/test_staff_auth.py, which covers the "wrong
password" mismatch arm of `verify_password` (a real hash, a wrong password,
`hmac.compare_digest` returns False) but not its other two branches: a
recognisably-formed-but-wrong-algorithm stored hash, and a malformed stored
hash that makes the `stored.split("$")` unpacking itself raise.
"""

from __future__ import annotations

from original import users


def test_verify_password_wrong_algorithm_prefix_returns_false():
    """A well-formed 4-part hash whose algo tag isn't ours must fail the
    `algo != _ALGO` check directly — no crypto is even attempted."""
    stored = f"bcrypt${users._ITERATIONS}${'00' * 16}${'00' * 32}"
    assert users.verify_password("whatever", stored) is False


def test_verify_password_malformed_stored_hash_returns_false():
    """A stored value that doesn't even have the expected 4 `$`-separated
    parts must be caught by the outer except, not raise ValueError."""
    assert users.verify_password("whatever", "not-a-valid-hash-at-all") is False


def test_verify_password_correct_password_round_trips():
    stored = users.hash_password("correct horse battery staple")
    assert users.verify_password("correct horse battery staple", stored) is True


def test_verify_password_mismatch_returns_false():
    stored = users.hash_password("correct horse battery staple")
    assert users.verify_password("wrong password", stored) is False
