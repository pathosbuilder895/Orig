"""
consumed_attestations.py — single-use enforcement for proctor attestations.

A proctor attestation (``student_auth.mint_proctor_attestation``) is a
bearer credential valid for the whole ``_PROCTOR_TTL`` window (6h) and,
before T-69, redeemable any number of times within that window for any
text: a captured token let an attacker inject repeated trusted-weight
baseline samples. This module makes redemption single-use — the first
successful proctored write consumes the attestation's jti; a second write
presenting the same token is refused trust (downgraded to ``unverified``,
never rejected outright, per ``_authorize_provenance``'s
downgrade-never-reject policy) rather than admitted at full weight again.

Consumption is keyed by jti (``student_auth.attestation_jti``), not by the
raw token, so the ledger never stores a bearer credential at rest.
"""

from __future__ import annotations

from .repository import get_repository


def mark_used(jti: str, tenant_id: str | None, exam: str, student_id: str) -> bool:
    """Atomically consume a proctor attestation. Returns True the first
    time a given jti is marked used, False on every subsequent call
    (replay). The underlying storage-layer uniqueness constraint on jti
    makes this race-safe under concurrent requests, not just sequential
    ones — see ``store.consume_proctor_attestation`` /
    ``PostgresRepository.consume_proctor_attestation``.
    """
    return get_repository().consume_proctor_attestation(jti, tenant_id, exam, student_id)
