"""Tests for the Sentry capture processor in the structlog pipeline."""

import io
import json
import logging

import pytest
import structlog

from auditry import configure_logging, get_logger, logging_config


class _StubScope:
    def __init__(self, tags):
        self._tags = tags

    def set_tag(self, key, value):
        self._tags[key] = value

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class SentryStub:
    def __init__(self):
        self.exceptions = []
        self.messages = []
        self.tags = {}

    def push_scope(self):
        return _StubScope(self.tags)

    def capture_exception(self, error=None):
        self.exceptions.append(error)

    def capture_message(self, message, level=None):
        self.messages.append((message, level))


@pytest.fixture
def sentry_stub(monkeypatch):
    stub = SentryStub()
    # ignore_logger is imported from the real sentry_sdk inside configure_logging;
    # keep it a no-op so the stub does not need to model that submodule.
    monkeypatch.setattr(
        "sentry_sdk.integrations.logging.ignore_logger", lambda name: None
    )
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


def test_log_line_stays_single_line_json(sentry_stub):
    # configure_logging's basicConfig(force=True) handler binds to the stderr in
    # effect during fixture setup, which escapes capsys/capfd. Assert on a single
    # buffer handler we own instead: it is the only handler, so the rendered JSON
    # must be exactly one parseable line.
    buffer = io.StringIO()
    handler = logging.StreamHandler(buffer)
    handler.setFormatter(logging.Formatter("%(message)s"))
    logging.getLogger().handlers = [handler]
    get_logger("test").error("Unhandled exception", exc_info=ValueError("boom"))
    lines = buffer.getvalue().strip().splitlines()
    assert len(lines) == 1
    parsed = json.loads(lines[0])
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


def test_exc_info_true_without_active_exception_falls_back_to_message(sentry_stub):
    # exc_info=True outside an except block has no ambient exception; capturing it
    # would send an empty, untriageable event, so fall back to the message.
    get_logger("test").error("orphaned error", exc_info=True)
    assert sentry_stub.exceptions == []
    assert sentry_stub.messages == [("orphaned error", "error")]


def test_captured_event_carries_context_tags(sentry_stub):
    structlog.contextvars.bind_contextvars(correlation_id="abc-123")
    try:
        get_logger("test").error(
            "Request failed", exc_info=ValueError("boom"), service="svc"
        )
    finally:
        structlog.contextvars.clear_contextvars()
    assert sentry_stub.tags.get("correlation_id") == "abc-123"
    assert sentry_stub.tags.get("service") == "svc"


def test_warns_when_sentry_capture_enabled_without_sdk(monkeypatch):
    monkeypatch.setattr(logging_config, "sentry_sdk", None)
    with pytest.warns(RuntimeWarning, match="sentry-sdk is not installed"):
        configure_logging(level="INFO", sentry_capture=True)


def test_real_sentry_sdk_sends_one_exception_envelope(monkeypatch):
    sentry_sdk = pytest.importorskip("sentry_sdk")
    from sentry_sdk.integrations.logging import LoggingIntegration
    from sentry_sdk.transport import Transport

    envelopes = []

    class CapturingTransport(Transport):
        def capture_envelope(self, envelope):
            envelopes.append(envelope)

    monkeypatch.setattr(logging_config, "sentry_sdk", sentry_sdk)
    sentry_sdk.init(
        dsn="https://public@example.invalid/1",
        transport=CapturingTransport,
        default_integrations=False,
        integrations=[LoggingIntegration(event_level=None)],
    )
    configure_logging(level="INFO", sentry_capture=True)
    try:
        raise RuntimeError("boom")
    except RuntimeError:
        get_logger("test").error("Request failed", exc_info=True)
    sentry_sdk.flush()

    events = [
        item.payload.json
        for envelope in envelopes
        for item in envelope.items
        if item.type == "event"
    ]
    assert len(events) == 1
    assert events[0]["exception"]["values"]


def test_capture_survives_a_transient_failure(monkeypatch):
    # A single capture failure must not disable capture for the rest of the
    # process; the next record still gets reported.
    class FlakySentry(SentryStub):
        def __init__(self):
            super().__init__()
            self.calls = 0

        def capture_exception(self, error=None):
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("transport boom")
            super().capture_exception(error)

    stub = FlakySentry()
    monkeypatch.setattr(
        "sentry_sdk.integrations.logging.ignore_logger", lambda name: None
    )
    monkeypatch.setattr(logging_config, "sentry_sdk", stub)
    configure_logging(level="INFO", sentry_capture=True)
    err = ValueError("boom")
    get_logger("test").error("first", exc_info=err)  # induced failure, swallowed
    get_logger("test").error("second", exc_info=err)  # must still capture
    assert stub.calls == 2
    assert stub.exceptions == [err]


def test_warns_when_logging_integration_double_reports(monkeypatch):
    sentry_sdk = pytest.importorskip("sentry_sdk")
    from sentry_sdk.integrations.logging import LoggingIntegration
    from sentry_sdk.transport import Transport

    class NullTransport(Transport):
        def capture_envelope(self, envelope):
            pass

    monkeypatch.setattr(logging_config, "sentry_sdk", sentry_sdk)
    sentry_sdk.init(
        dsn="https://public@example.invalid/1",
        transport=NullTransport,
        default_integrations=False,
        integrations=[LoggingIntegration()],  # default event_level=ERROR
    )
    with pytest.warns(RuntimeWarning, match="reported twice"):
        configure_logging(level="INFO", sentry_capture=True)


def test_no_double_report_warning_when_event_level_none(monkeypatch, recwarn):
    sentry_sdk = pytest.importorskip("sentry_sdk")
    from sentry_sdk.integrations.logging import LoggingIntegration
    from sentry_sdk.transport import Transport

    class NullTransport(Transport):
        def capture_envelope(self, envelope):
            pass

    monkeypatch.setattr(logging_config, "sentry_sdk", sentry_sdk)
    sentry_sdk.init(
        dsn="https://public@example.invalid/1",
        transport=NullTransport,
        default_integrations=False,
        integrations=[LoggingIntegration(event_level=None)],
    )
    configure_logging(level="INFO", sentry_capture=True)
    assert [w for w in recwarn if issubclass(w.category, RuntimeWarning)] == []
