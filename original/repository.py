"""
repository.py — the persistence seam (ADR-002).

A single interface that every new feature routes through, so the demo
(SQLite) and v1 (Postgres) backends stop being parallel universes. The API
layer depends on ``Repository``, never on ``original.store`` directly.

Today only ``SqliteRepository`` exists (delegating to ``original.store``).
A ``PostgresRepository`` plugs in at ``get_repository()`` for the pilot /
production environments once the v1 SQLAlchemy models are extended to cover
these features. The ``environment`` argument is where that choice is made.

This first slice covers the Formation pathway (the convergence demonstrator).
Additional methods (tenants, audit, student state) move behind this interface
incrementally — see ADR-002 action items.
"""

from __future__ import annotations

from typing import Dict, Optional, Protocol, runtime_checkable

from . import store


@runtime_checkable
class Repository(Protocol):
    """Storage operations the API depends on. Backend-agnostic."""

    # ── Formation pathways ────────────────────────────────────────────────
    def get_formation_pathway(self, student_id: str) -> Optional[Dict]: ...
    def open_formation_pathway(
        self, student_id: str, submission_id: Optional[str] = None,
        reason: Optional[str] = None,
    ) -> Optional[Dict]: ...
    def advance_formation_pathway(self, student_id: str) -> Optional[Dict]: ...


class SqliteRepository:
    """Repository backed by the demo SQLite store (``original.store``)."""

    # ── Formation pathways ────────────────────────────────────────────────
    def get_formation_pathway(self, student_id: str) -> Optional[Dict]:
        return store.get_formation_pathway(student_id)

    def open_formation_pathway(
        self, student_id: str, submission_id: Optional[str] = None,
        reason: Optional[str] = None,
    ) -> Optional[Dict]:
        return store.open_formation_pathway(student_id, submission_id, reason)

    def advance_formation_pathway(self, student_id: str) -> Optional[Dict]:
        return store.advance_formation_pathway(student_id)


# ── Factory ───────────────────────────────────────────────────────────────────

_REPO: Optional[Repository] = None


def get_repository(environment: str = "demo") -> Repository:
    """
    Return the repository for the given environment.

    Today every environment resolves to ``SqliteRepository``. When the
    Postgres implementation lands, this factory selects it for
    ``environment in {"pilot", "production"}`` — the single place the
    demo/v1 split is decided. Cached as a module singleton.
    """
    global _REPO
    if _REPO is None:
        _REPO = SqliteRepository()
    return _REPO


def reset_repository() -> None:
    """Test hook — drop the cached singleton so a fresh one is built."""
    global _REPO
    _REPO = None
