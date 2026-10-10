"""Credentials carried in a URL's query string must not reach the access log.

Four GET links carry one: the signed launch link (``/bluebook/launch?t=``),
the one-time set-password invite (``/bluebook/?invite=``), the password reset
(``?reset=``) and the phone-park page (``parked.html?t=``). Uvicorn's access
log prints every request line with its query string, so each link landed in
the pilot's stdout logs, where anyone who can read the logs could redeem a
pending invite. ``RequestLoggingMiddleware`` already logs every request by
path alone, so ``run.py`` turns uvicorn's duplicate access log off.
"""

from __future__ import annotations

import logging
import os
import sys

import pytest

import run

SECRET = "SENTINEL-TOKEN-0f3a"


@pytest.fixture
def unmounted_after(live_app):
    """run.main() mounts demo/ onto the shared app in place. Restore the route
    table and flag afterwards, as tests/security/test_static_tree.py's
    ``mounted_app`` does, so later route-inventory tests are unaffected."""
    saved_routes = list(live_app.router.routes)
    had_flag = getattr(live_app.state, "_original_demo_frontend_mounted", False)
    yield
    live_app.router.routes[:] = saved_routes
    if not had_flag and hasattr(live_app.state, "_original_demo_frontend_mounted"):
        delattr(live_app.state, "_original_demo_frontend_mounted")


def test_pilot_start_command_turns_off_the_uvicorn_access_log(monkeypatch, unmounted_after):
    calls = []
    monkeypatch.setattr(run.uvicorn, "run", lambda app, **kwargs: calls.append(kwargs))
    # main() setdefaults demo-mode flags into the environment; keep them here.
    monkeypatch.setattr(os, "environ", dict(os.environ))
    # The pilot's startCommand: python run.py --demo --port $PORT --skip-seed
    monkeypatch.setattr(sys, "argv", ["run.py", "--demo", "--port", "8123", "--skip-seed"])
    run.main()
    assert len(calls) == 1
    assert calls[0]["access_log"] is False


def test_request_log_records_token_links_without_the_token(live_client, caplog):
    caplog.set_level(logging.INFO, logger="original.http")
    links = [
        ("/bluebook/launch", f"t={SECRET}"),
        ("/bluebook/", f"invite={SECRET}"),
        ("/bluebook/", f"reset={SECRET}"),
        ("/bluebook/parked.html", f"t={SECRET}"),
    ]
    for path, query in links:
        live_client.get(f"{path}?{query}")
    logged = [r.path for r in caplog.records if r.name == "original.http"]
    assert logged == [path for path, _ in links]
    # Every field of every server-side record, extras included (caplog.text
    # has only the message). The test client logs each URL it requests under
    # "httpx" or, on newer installs, "httpx2"; that is the client, not us.
    server = [r for r in caplog.records if not r.name.startswith("httpx")]
    assert not [r for r in server if SECRET in str(vars(r))]
