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

from typing import Dict, List, Optional, Protocol, runtime_checkable

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

    # ── Tenants ───────────────────────────────────────────────────────────
    def get_tenant(self, tenant_id: str) -> Optional[Dict]: ...
    def list_tenants(self, environment: Optional[str] = None) -> List[Dict]: ...
    def put_tenant(
        self, tenant_id: str, name: str, environment: str = "demo",
        meta: Optional[Dict] = None,
    ) -> None: ...
    def tenant_stats(self, tenant_id: str) -> Dict: ...

    # ── Audit log ─────────────────────────────────────────────────────────
    def list_audit(
        self, student_id: Optional[str] = None, action: Optional[str] = None,
        limit: int = 100, offset: int = 0,
    ) -> Dict: ...
    def log_audit(self, action: str, **kwargs) -> None: ...


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

    # ── Tenants ───────────────────────────────────────────────────────────
    def get_tenant(self, tenant_id: str) -> Optional[Dict]:
        return store.get_tenant(tenant_id)

    def list_tenants(self, environment: Optional[str] = None) -> List[Dict]:
        return store.list_tenants(environment=environment)

    def put_tenant(
        self, tenant_id: str, name: str, environment: str = "demo",
        meta: Optional[Dict] = None,
    ) -> None:
        store.put_tenant(tenant_id, name, environment=environment, meta=meta)

    def tenant_stats(self, tenant_id: str) -> Dict:
        return store.tenant_stats(tenant_id)

    # ── Audit log ─────────────────────────────────────────────────────────
    def list_audit(
        self, student_id: Optional[str] = None, action: Optional[str] = None,
        limit: int = 100, offset: int = 0,
    ) -> Dict:
        return store.list_audit(student_id=student_id, action=action,
                                limit=limit, offset=offset)

    def log_audit(self, action: str, **kwargs) -> None:
        store.log_audit(action, **kwargs)


class PostgresRepository:
    """
    Repository backed by the v1 Postgres/SQLAlchemy models — the pilot /
    production implementation (ADR-002 action item 4).

    Skeleton: the v1 models (Institution, Student, Submission, Baseline) do
    not yet cover formation pathways, the tenant-environment registry, or the
    unified audit log. Each method raises until its model + query land, so the
    convergence work is explicit and discoverable rather than silently absent.

    When implemented, ``get_repository()`` selects this for
    ``environment in {"pilot", "production"}`` — the single switch point.
    """

    _NOT_READY = (
        "PostgresRepository.{op} is not implemented yet. Extend the v1 "
        "SQLAlchemy models to cover this, then wire it here (see ADR-002)."
    )

    def _todo(self, op: str):
        raise NotImplementedError(self._NOT_READY.format(op=op))

    # Formation
    def get_formation_pathway(self, student_id):                 self._todo("get_formation_pathway")
    def open_formation_pathway(self, student_id, submission_id=None, reason=None): self._todo("open_formation_pathway")
    def advance_formation_pathway(self, student_id):             self._todo("advance_formation_pathway")
    # Tenants
    def get_tenant(self, tenant_id):                             self._todo("get_tenant")
    def list_tenants(self, environment=None):                    self._todo("list_tenants")
    def put_tenant(self, tenant_id, name, environment="demo", meta=None): self._todo("put_tenant")
    def tenant_stats(self, tenant_id):                           self._todo("tenant_stats")
    # Audit
    def list_audit(self, student_id=None, action=None, limit=100, offset=0): self._todo("list_audit")
    def log_audit(self, action, **kwargs):                       self._todo("log_audit")


# ── Factory ───────────────────────────────────────────────────────────────────

_REPO: Optional[Repository] = None


def get_repository(environment: str = "demo") -> Repository:
    """
    Return the repository for the given environment — the single switch point
    for the demo/v1 split (ADR-002).

    - demo                 → SqliteRepository (local, zero-dependency)
    - pilot | production   → PostgresRepository once its models land; until
                             then it also resolves to SQLite so nothing breaks,
                             and the NotImplementedError surfaces only when an
                             unported operation is actually called.

    Cached as a module singleton.
    """
    global _REPO
    if _REPO is None:
        # Postgres impl is a skeleton today; keep SQLite as the working default
        # for every environment. Flip this to PostgresRepository() per
        # environment as the v1 models are extended.
        _REPO = SqliteRepository()
    return _REPO


def reset_repository() -> None:
    """Test hook — drop the cached singleton so a fresh one is built."""
    global _REPO
    _REPO = None
