"""Tests for scripts/o1_golive_check.py — the O1 (pre-cutover) deploy check.

The script's run_checks() takes a ``get`` callable so it can be driven without
a network, mirroring how tests/test_cutover.py drives pilot_smoke_test.
"""

import json

from scripts.o1_golive_check import HOSTILE_ORIGIN, LOCKDOWN, run_checks

GOOD_HEALTH = {
    "status": "ok",
    "environment": "pilot",
    "backend": "sqlite",
    "commit": "c2ba17676f344b629e5b00d6fe891c67e11d97ae",
    "feature_dim": 109,
}
KID = "7939c6c8a6f9a736"


def make_get(health=None, kid=KID, key_count=1, lockdown=None, hsts=True, echo_origin=False):
    """Build a ``get`` that serves a configurable fake deployment."""
    health = GOOD_HEALTH if health is None else health
    codes = dict(LOCKDOWN) if lockdown is None else lockdown

    def get(path, headers=None):
        if path == "/health":
            h = {}
            if hsts:
                h["strict-transport-security"] = "max-age=31536000; includeSubDomains"
            if echo_origin and headers and headers.get("Origin"):
                h["access-control-allow-origin"] = headers["Origin"]
            return 200, json.dumps(health), h
        if path == "/lti/jwks":
            keys = [{"kid": kid, "kty": "RSA"} for _ in range(key_count)]
            return 200, json.dumps({"keys": keys}), {}
        return codes.get(path, 200), "", {}

    return get


def results(get, **kw):
    return {name: ok for name, ok, _ in run_checks(get, **kw)}


class TestO1GoLiveCheck:
    def test_passes_on_a_correct_pre_cutover_deploy(self):
        r = results(make_get(), expect_kid=KID, expect_commit=GOOD_HEALTH["commit"])
        assert all(r.values()), [k for k, v in r.items() if not v]

    def test_fails_when_backend_is_already_postgres(self):
        # Post-cutover deployments must use pilot_smoke_test.py instead.
        get = make_get({**GOOD_HEALTH, "backend": "postgres"})
        assert results(get)["backend_is_sqlite"] is False

    def test_fails_when_environment_is_not_pilot(self):
        get = make_get({**GOOD_HEALTH, "environment": "demo"})
        assert results(get)["environment_is_pilot"] is False

    def test_fails_on_kid_mismatch(self):
        # The realistic failure: a trailing newline rode along with the paste.
        r = results(make_get(kid="ebe8fab89c991e38"), expect_kid=KID)
        assert r["jwks_kid_matches"] is False

    def test_kid_not_checked_when_not_supplied(self):
        assert "jwks_kid_matches" not in results(make_get(kid="anything"))

    def test_fails_when_jwks_is_empty(self):
        # An unset LTI_PRIVATE_KEY publishes {"keys": []}.
        assert results(make_get(key_count=0))["jwks_has_one_key"] is False

    def test_fails_on_commit_mismatch(self):
        r = results(make_get(), expect_commit="deadbee")
        assert r["commit_matches"] is False

    def test_commit_matches_on_short_sha_prefix(self):
        r = results(make_get(), expect_commit="c2ba1767")
        assert r["commit_matches"] is True

    def test_each_lockdown_endpoint_is_checked_and_can_fail(self):
        for path, _ in LOCKDOWN:
            # 200 means the endpoint is anonymously reachable — the STOP signal.
            get = make_get(lockdown={**dict(LOCKDOWN), path: 200})
            r = results(get)
            assert r[f"lockdown{path}"] is False, path
            others = [
                v for k, v in r.items() if k.startswith("lockdown") and k != f"lockdown{path}"
            ]
            assert all(others), f"{path} leaked into other lockdown checks"

    def test_fails_when_hsts_absent(self):
        assert results(make_get(hsts=False))["hsts_present"] is False

    def test_fails_when_cors_echoes_hostile_origin(self):
        get = make_get(echo_origin=True)
        assert results(get)["cors_rejects_hostile_origin"] is False

    def test_unreachable_host_fails_rather_than_raising(self):
        def get(path, headers=None):
            return 0, "URLError: connection refused", {}

        r = results(get, expect_kid=KID)
        assert r["health_reachable"] is False
        assert r["jwks_has_one_key"] is False

    def test_hostile_origin_constant_is_not_a_real_domain_we_trust(self):
        assert HOSTILE_ORIGIN not in ("https://original-pilot.onrender.com",)
