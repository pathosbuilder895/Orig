"""Tenant-scoped collection of same-author LOO distances for pooling.

Tenant scoping mirrors null_pool.py: a reference distribution must never
mix tenants, and the scored student never contributes to the reference
they are measured against.
"""

from __future__ import annotations

import numpy as np

from ..principal import DEMO_TENANT, tenant_of


def collect_tenant_distances(states, tenant: str, exclude_sid: str) -> list[np.ndarray]:
    out: list[np.ndarray] = []
    for sid, state in states.items():
        if sid == exclude_sid:
            continue
        if (tenant_of(sid) or DEMO_TENANT) != tenant:
            continue
        try:
            d = np.asarray(state.loo_distances, dtype=float).ravel()
        except Exception:
            continue
        d = d[np.isfinite(d)]
        if d.size:
            out.append(d)
    return out
