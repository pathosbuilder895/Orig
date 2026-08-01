import numpy as np

from original.quantum.pooled_source import collect_tenant_distances


class _FakeState:
    def __init__(self, distances):
        self._d = np.asarray(distances, dtype=float)

    @property
    def loo_distances(self):
        return self._d


def test_scopes_to_tenant_and_excludes_self():
    states = {
        "demo:alice": _FakeState([1.0, 1.1]),
        "demo:bob": _FakeState([0.9, 1.2]),
        "other:carol": _FakeState([5.0, 5.1]),
    }
    out = collect_tenant_distances(states, tenant="demo", exclude_sid="demo:alice")
    assert len(out) == 1
    assert np.allclose(out[0], [0.9, 1.2])


def test_flat_ids_belong_to_the_demo_sandbox():
    """Legacy un-namespaced ids are the demo sandbox, matching
    principal.py's tenant_of() convention."""
    states = {"legacy": _FakeState([1.0, 1.1]), "demo:bob": _FakeState([0.9])}
    out = collect_tenant_distances(states, tenant="demo", exclude_sid="demo:bob")
    assert len(out) == 1
    assert np.allclose(out[0], [1.0, 1.1])


def test_skips_states_without_usable_distances():
    states = {
        "demo:alice": _FakeState([]),
        "demo:bob": _FakeState([0.9, 1.2]),
        "demo:carol": _FakeState([np.nan]),
    }
    out = collect_tenant_distances(states, tenant="demo", exclude_sid="demo:zed")
    assert len(out) == 1
