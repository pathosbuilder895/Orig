"""The notification sender is a no-op, and says so when a key is set.

``_send_notification_email`` has never sent an email. That is deliberate (see
its docstring: recipient policy and FERPA wording are a pilot-institution
decision, not an SDK call), but "deliberate" only holds if two things stay
true, and neither was covered before this file:

  1. It really does no I/O — a stub that quietly grew a network call would
     start emailing students' scores from the scoring hot path.
  2. An operator who exports ``SENDGRID_API_KEY`` is told it is ignored,
     rather than left to assume delivery is on.

The network assertion here is deliberately blunt: every socket-creation entry
point is monkeypatched to raise, so *any* attempt to reach the wire fails the
test loudly rather than depending on which HTTP client a future edit reaches
for.
"""

from __future__ import annotations

import logging
import socket

import pytest

from original.routers._shared import _send_notification_email, log_email_sender_status


@pytest.fixture
def no_network(monkeypatch):
    """Make any outbound connection attempt an immediate, obvious failure."""
    calls: list[str] = []

    def _boom(name):
        def _raise(*args, **kwargs):
            calls.append(name)
            raise AssertionError(f"network attempted via {name}({args!r})")

        return _raise

    monkeypatch.setattr(socket.socket, "connect", _boom("socket.connect"))
    monkeypatch.setattr(socket.socket, "connect_ex", _boom("socket.connect_ex"))
    monkeypatch.setattr(socket, "create_connection", _boom("socket.create_connection"))
    return calls


def test_send_notification_email_is_silent_no_op_with_key_set(monkeypatch, caplog, no_network):
    """Key set, sender stubbed: returns cleanly, touches no socket."""
    monkeypatch.setenv("SENDGRID_API_KEY", "SG.not-a-real-key.definitely-not-used")

    with caplog.at_level(logging.INFO, logger="original.routers._shared"):
        result = _send_notification_email(student_name="stu-1", action="monitor", score=0.71)

    assert result is None
    assert no_network == [], "the no-op must not open a socket"
    # It records the notification it is declining to send -- that INFO line is
    # the only observable effect, and it says "no-op" so a log reader is not
    # left believing mail went out.
    messages = [r.getMessage() for r in caplog.records]
    assert any("no-op" in m and "stu-1" in m for m in messages), messages


def test_send_notification_email_is_a_no_op_without_key_either(monkeypatch, no_network):
    """No key is not a different code path -- there is only the one."""
    monkeypatch.delenv("SENDGRID_API_KEY", raising=False)

    assert _send_notification_email(student_name="stu-2", action="clear", score=0.12) is None
    assert no_network == []


def test_startup_warns_when_key_is_set(monkeypatch, caplog):
    """The line an operator who exported the key needs to see at boot."""
    monkeypatch.setenv("SENDGRID_API_KEY", "SG.not-a-real-key.definitely-not-used")

    with caplog.at_level(logging.WARNING, logger="original.routers._shared"):
        log_email_sender_status()

    warnings = [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]
    assert len(warnings) == 1, warnings
    assert "SENDGRID_API_KEY is set" in warnings[0]
    assert "no-op" in warnings[0]


@pytest.mark.parametrize("value", ["", "   "])
def test_startup_is_quiet_when_key_is_unset_or_blank(monkeypatch, caplog, value):
    """Nothing to correct, so nothing is said -- including for a blank value,
    which Render produces for an env var declared but left empty."""
    monkeypatch.setenv("SENDGRID_API_KEY", value)

    with caplog.at_level(logging.INFO, logger="original.routers._shared"):
        log_email_sender_status()

    assert caplog.records == []


def test_startup_is_quiet_when_key_is_absent(monkeypatch, caplog):
    monkeypatch.delenv("SENDGRID_API_KEY", raising=False)

    with caplog.at_level(logging.INFO, logger="original.routers._shared"):
        log_email_sender_status()

    assert caplog.records == []
