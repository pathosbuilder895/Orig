"""
tests/security/conftest.py — provisioning fixtures for the abuse-case suite.

Keep this file small: one fixture (``two_tenants``) that stands up two real
(pilot-environment) tenants with staff headers and one baselined student
apiece. Tasks 4, 5 and 9 reuse it — do not grow it into a general-purpose
helper module; per-attack-goal setup belongs in the test file that needs it.
"""

from __future__ import annotations

import pytest

# ~140 words — comfortably above the baseline word-count floor. Copied
# verbatim from tests/test_pilot_lockdown.py / tests/test_tenant_isolation.py
# so baseline ingestion succeeds the same way it does there.
LONG_TEXT = (
    "The doctrine of justification by faith stands at the center of the gospel. "
    "When Paul writes to the Romans, he labors to show that righteousness comes "
    "not by works of the law but through faith in Christ alone. This conviction "
    "shaped the Reformation and continues to shape pastoral practice today. "
    "A careful reader notices how the argument unfolds in stages, each building "
    "on the last, until the conclusion becomes unavoidable. The voice here is "
    "deliberate and measured, favoring long subordinate clauses and a vocabulary "
    "drawn from systematic theology. Such patterns, repeated across many essays, "
    "form a fingerprint as distinctive as handwriting. The seminary student who "
    "writes this way in September will, absent intervention, write this way in "
    "May, and that continuity is precisely what we set out to measure and to "
    "protect with patience and with care."
)

TENANT_A = "sectesta"
TENANT_B = "sectestb"


@pytest.fixture
def two_tenants(pilot_env, store_reset, live_client, principal_headers):
    """Provision two pilot tenants (A, B) under real-deploy mode.

    Returns a dict with each tenant's id, staff (professor) auth headers, and
    one baselined student id. Tenant creation itself needs an operator
    principal: on a real deploy ``POST /tenants`` is a staff-only path (the
    tenant-isolation middleware 401s anonymous/demo/student callers), and
    operator is a SUPER_ROLES role so it isn't scoped to either tenant.
    """
    op_headers = principal_headers("op_sectest", "operator", TENANT_A)
    for tenant_id in (TENANT_A, TENANT_B):
        r = live_client.post(
            "/tenants",
            json={
                "tenant_id": tenant_id,
                "name": f"Security Test Tenant {tenant_id}",
                "environment": "pilot",
            },
            headers=op_headers,
        )
        assert r.status_code == 201, r.text

    headers_a = principal_headers(f"prof_{TENANT_A}", "professor", TENANT_A)
    headers_b = principal_headers(f"prof_{TENANT_B}", "professor", TENANT_B)

    student_a = f"{TENANT_A}:alice"
    student_b = f"{TENANT_B}:bob"
    for student_id, headers in ((student_a, headers_a), (student_b, headers_b)):
        r = live_client.post(
            f"/students/{student_id}/baseline",
            json={"text": LONG_TEXT, "assignment": "intro-essay"},
            headers=headers,
        )
        assert r.status_code == 200, r.text

    return {
        "tenant_a": TENANT_A,
        "tenant_b": TENANT_B,
        "headers_a": headers_a,
        "headers_b": headers_b,
        "student_a": student_a,
        "student_b": student_b,
    }
