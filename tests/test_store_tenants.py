"""
tests/test_store_tenants.py — Unit tests for the SQL LIKE-escaping fix
(code-review finding #4).

``_escape_like`` is a SQLite-only implementation detail (a Postgres backend
uses jsonb operators / different escaping, per WS-6 P2) — it isn't part of
the ``Repository`` protocol, so it can't live in the backend-agnostic
contract suite. Everything that *is* expressible against the Repository
interface (tenant registry CRUD, tenant_stats scoping, delete_tenant_students)
moved to tests/test_repository_contract.py per WS-6 P1 deliverable #3.
"""

from __future__ import annotations

import original.store as store


class TestEscapeLike:
    def test_no_wildcards_unchanged(self):
        assert store._escape_like("seminary-dallas:") == "seminary-dallas:"

    def test_underscore_escaped(self):
        assert store._escape_like("sem_a:") == r"sem\_a:"

    def test_percent_escaped(self):
        assert store._escape_like("sem%a:") == r"sem\%a:"

    def test_backslash_escaped_first(self):
        # Backslash must be doubled before % / _ are escaped
        assert store._escape_like("a\\b") == "a\\\\b"

    def test_combined(self):
        assert store._escape_like("a_b%c") == r"a\_b\%c"
