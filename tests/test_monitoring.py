"""Tests for original/monitoring.py — Sentry is optional, opt-in, and must
never carry a student's writing off the server."""

from __future__ import annotations

import sys
import types

import pytest

from original import monitoring


@pytest.fixture
def fake_sentry(monkeypatch):
    calls = []
    mod = types.ModuleType("sentry_sdk")
    mod.init = lambda **kw: calls.append(kw)
    monkeypatch.setitem(sys.modules, "sentry_sdk", mod)
    return calls


def test_off_without_a_dsn(fake_sentry):
    assert monitoring.init_sentry({}) is False
    assert monitoring.init_sentry({"SENTRY_DSN": "   "}) is False
    assert fake_sentry == []


def test_on_with_a_dsn_and_never_sends_bodies_pii_or_locals(fake_sentry):
    env = {
        "SENTRY_DSN": "https://key@o0.ingest.example/1",
        "ORIGINAL_ENV": "pilot",
        "RENDER_GIT_COMMIT": "abc123",
    }
    assert monitoring.init_sentry(env) is True
    (kw,) = fake_sentry
    assert kw["dsn"] == env["SENTRY_DSN"]
    assert kw["environment"] == "pilot"
    assert kw["release"] == "abc123"
    assert kw["send_default_pii"] is False
    assert kw["max_request_body_size"] == "never"
    assert kw["include_local_variables"] is False
    assert kw["traces_sample_rate"] == 0.0
    assert kw["before_send"] is monitoring.scrub_event


def test_defaults_environment_and_release(fake_sentry):
    assert monitoring.init_sentry({"SENTRY_DSN": "https://k@x/1"}) is True
    assert fake_sentry[0]["environment"] == "demo"
    assert fake_sentry[0]["release"] is None


@pytest.mark.parametrize(
    ("raw", "rate"), [("0.25", 0.25), ("5", 1.0), ("-1", 0.0), ("nope", 0.0), ("", 0.0)]
)
def test_trace_rate_cannot_enable_classroom_tracing(fake_sentry, raw, rate):
    monitoring.init_sentry({"SENTRY_DSN": "https://k@x/1", "SENTRY_TRACES_SAMPLE_RATE": raw})
    assert fake_sentry[0]["traces_sample_rate"] == 0.0
    assert fake_sentry[0]["before_send_transaction"]({"text": "student prose"}) is None


def test_missing_package_is_a_warning_not_a_crash(monkeypatch):
    monkeypatch.setitem(sys.modules, "sentry_sdk", None)  # import raises ImportError
    assert monitoring.init_sentry({"SENTRY_DSN": "https://k@x/1"}) is False


def test_a_failing_init_is_a_warning_not_a_crash(monkeypatch):
    mod = types.ModuleType("sentry_sdk")

    def boom(**kw):
        raise ValueError("bad dsn")

    mod.init = boom
    monkeypatch.setitem(sys.modules, "sentry_sdk", mod)
    assert monitoring.init_sentry({"SENTRY_DSN": "not a dsn"}) is False


def test_scrub_event_keeps_only_method_and_path():
    event = {
        "request": {
            "method": "POST",
            "url": "https://bluebook.example/bluebook/submissions?token=secret#frag",
            "data": {"text": "a student's whole answer"},
            "headers": {"Authorization": "Bearer t"},
            "cookies": {"s": "1"},
            "query_string": "token=secret",
        },
        "user": {"id": "student-1", "ip_address": "10.0.0.1"},
        "breadcrumbs": {"values": [{"message": "http", "data": {"body": "answer"}}, "odd"]},
    }
    out = monitoring.scrub_event(event)
    assert out["request"] == {"method": "POST"}
    assert "user" not in out
    assert "breadcrumbs" not in out


def test_scrub_event_tolerates_missing_parts():
    assert monitoring.scrub_event({}) == {}
    assert monitoring.scrub_event({"request": {"method": "GET"}}) == {"request": {"method": "GET"}}
    assert monitoring.scrub_event({"request": "odd", "breadcrumbs": []}) == {}


def test_writing_in_exception_logs_context_and_urls_never_leaves():
    import json

    prose = "PRIVATE STUDENT ANSWER"
    event = {
        "event_id": "abc",
        "level": "error",
        "message": prose,
        "logentry": {"formatted": prose},
        "extra": {"answer": prose},
        "contexts": {"validation": prose},
        "tags": {"text": prose},
        "request": {"method": "POST", "url": "https://example/" + prose},
        "breadcrumbs": {"values": [{"message": prose}]},
        "exception": {
            "values": [
                {
                    "type": "ValueError",
                    "value": prose,
                    "stacktrace": {
                        "frames": [
                            {
                                "filename": "original/api.py",
                                "function": "submit",
                                "lineno": 10,
                                "vars": {"text": prose},
                                "context_line": prose,
                                "pre_context": [prose],
                            }
                        ]
                    },
                }
            ]
        },
    }
    safe = monitoring.scrub_event(event)
    assert prose not in json.dumps(safe)
    assert safe["exception"]["values"][0]["stacktrace"]["frames"] == [
        {"filename": "original/api.py", "function": "submit", "lineno": 10}
    ]
    assert safe["event_id"] == "abc"
