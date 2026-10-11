"""T-19: a per-caller scoring budget on real deploys.

POST /students/{id}/score and POST /me/work run the heaviest work in the app
(feature extraction, spaCy). On a real deploy each signed-in caller gets
SCORE_RATE_LIMIT_PER_MINUTE of them per rolling minute, shared between the two
routes; off real deploys (the test suite, the zero-login demo) there is no
limit, because every request there runs as the one demo principal.
"""

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from original import student_auth
from original.routers import students_scoring as ss

TEXT = "A short paragraph of writing to compare with the writing on file."


@pytest.fixture
def budget(monkeypatch):
    """Set the per-minute budget and whether the app counts as a real deploy,
    for the throttle only (the rest of the request path stays in demo mode)."""
    monkeypatch.setattr(ss, "_score_calls", {})

    def set_budget(per_minute, real=True):
        monkeypatch.setattr(ss, "_SCORE_LIMIT_PER_MINUTE", per_minute)
        monkeypatch.setattr(ss, "_api", lambda: SimpleNamespace(_IS_REAL_DEPLOY=real))

    return set_budget


def _request(user="u1", tenant="t1"):
    principal = SimpleNamespace(user_id=user, tenant_id=tenant)
    return SimpleNamespace(state=SimpleNamespace(principal=principal), headers={}, client=None)


def test_the_call_after_the_budget_is_refused_with_429(budget):
    budget(3)
    for _ in range(3):
        ss._throttle_score(_request())
    with pytest.raises(HTTPException) as exc:
        ss._throttle_score(_request())
    assert exc.value.status_code == 429
    assert "Too many scoring requests" in exc.value.detail


def test_each_caller_has_its_own_budget(budget):
    budget(1)
    ss._throttle_score(_request("u1", "t1"))
    with pytest.raises(HTTPException):
        ss._throttle_score(_request("u1", "t1"))
    ss._throttle_score(_request("u2", "t1"))  # another user, same workspace
    ss._throttle_score(_request("u1", "t2"))  # same id, another workspace


def test_the_budget_refills_after_a_minute(budget, monkeypatch):
    budget(1)
    clock = [1000.0]
    monkeypatch.setattr(ss.time, "monotonic", lambda: clock[0])
    ss._throttle_score(_request())
    with pytest.raises(HTTPException):
        ss._throttle_score(_request())
    clock[0] += 61
    ss._throttle_score(_request())


@pytest.mark.parametrize(
    "per_minute, real, request_",
    [
        (1, False, _request()),  # off a real deploy
        (0, True, _request()),  # SCORE_RATE_LIMIT_PER_MINUTE=0 turns it off
        (1, True, None),  # in-process callers pass no request
    ],
)
def test_no_limit_applies(budget, per_minute, real, request_):
    budget(per_minute, real=real)
    for _ in range(5):
        ss._throttle_score(request_)


def test_an_anonymous_caller_is_bucketed_by_ip(budget):
    budget(1)
    anon = SimpleNamespace(state=SimpleNamespace(principal=None), headers={}, client=None)
    ss._throttle_score(anon)
    with pytest.raises(HTTPException):
        ss._throttle_score(anon)


def test_score_route_returns_429_once_the_budget_is_spent(budget, live_client, store_reset):
    budget(1)
    body = {"text": TEXT, "assignment": "Rate limit"}
    first = live_client.post("/students/nobody/score", json=body)
    assert first.status_code == 404  # past the throttle, then no such student
    second = live_client.post("/students/nobody/score", json=body)
    assert second.status_code == 429


def test_me_work_returns_429_not_no_writing_on_file(budget, live_client, store_reset):
    # /me/work reports any HTTPException from scoring as "no writing on file";
    # the throttle runs before that, so a spent budget reads as 429.
    budget(1)
    token = student_auth.mint_session("ghost-tenant:rate-limited", "Ghost Student")
    headers = {"Authorization": f"Bearer {token}"}
    body = {"text": TEXT, "title": "Rate limit"}
    assert live_client.post("/me/work", json=body, headers=headers).status_code == 200
    assert live_client.post("/me/work", json=body, headers=headers).status_code == 429


def test_the_table_is_bounded_under_caller_churn(budget, monkeypatch):
    budget(5)
    monkeypatch.setattr(ss, "_score_calls", {f"t:u{i}": [0.0] for i in range(10_000)})
    ss._throttle_score(_request("new", "t"))
    assert ss._score_calls == {}
