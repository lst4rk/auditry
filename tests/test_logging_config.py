"""Tests for the Sentry capture processor in the structlog pipeline."""

import json
import logging

import pytest

from auditry import configure_logging, get_logger
from auditry import logging_config


class SentryStub:
    def __init__(self):
        self.exceptions = []
        self.messages = []

    def capture_exception(self, error=None):
        self.exceptions.append(error)

    def capture_message(self, message, level=None):
        self.messages.append((message, level))


@pytest.fixture
def sentry_stub(monkeypatch):
    stub = SentryStub()
    monkeypatch.setattr(logging_config, "sentry_sdk", stub)
    configure_logging(level="INFO", sentry_capture=True)
    return stub


def test_error_log_with_exception_instance_is_captured(sentry_stub):
    error = ValueError("boom")
    get_logger("test").error("Unhandled exception", exc_info=error)
    assert sentry_stub.exceptions == [error]
    assert sentry_stub.messages == []


def test_exception_log_inside_except_block_is_captured(sentry_stub):
    try:
        raise RuntimeError("boom")
    except RuntimeError:
        get_logger("test").error("Request failed", exc_info=True)
    assert sentry_stub.exceptions == [None]
    assert sentry_stub.messages == []


def test_error_log_without_exc_info_is_captured_as_message(sentry_stub):
    get_logger("test").error("DB connection failed", attempts=3)
    assert sentry_stub.exceptions == []
    assert sentry_stub.messages == [("DB connection failed", "error")]


def test_info_and_warning_logs_are_not_captured(sentry_stub):
    get_logger("test").info("Request completed")
    get_logger("test").warning("Request validation failed")
    assert sentry_stub.exceptions == []
    assert sentry_stub.messages == []


def test_log_line_stays_single_line_json(sentry_stub, capsys):
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter("%(message)s"))
    root = logging.getLogger()
    root.addHandler(handler)
    try:
        get_logger("test").error("Unhandled exception", exc_info=ValueError("boom"))
    finally:
        root.removeHandler(handler)
    line = capsys.readouterr().err.strip()
    parsed = json.loads(line)
    assert parsed["event"] == "Unhandled exception"
    assert "ValueError: boom" in parsed["exception"]


def test_missing_sentry_sdk_is_a_noop(monkeypatch):
    monkeypatch.setattr(logging_config, "sentry_sdk", None)
    configure_logging(level="INFO", sentry_capture=True)
    get_logger("test").error("Unhandled exception", exc_info=ValueError("boom"))


def test_sentry_capture_disabled_by_default(monkeypatch):
    stub = SentryStub()
    monkeypatch.setattr(logging_config, "sentry_sdk", stub)
    configure_logging(level="INFO")
    get_logger("test").error("Unhandled exception", exc_info=ValueError("boom"))
    assert stub.exceptions == []
    assert stub.messages == []
