"""Shared test fixtures.

`configure_logging` mutates process-global state (`structlog.configure` and
`logging.basicConfig(force=True)`). Several test modules call it at import time,
so without a restore the last configuration — including the Sentry processor —
leaks into unrelated tests. Snapshot and restore around every test.
"""

import logging

import pytest
import structlog

from auditry import logging_config


@pytest.fixture(autouse=True)
def _restore_logging_state():
    saved_structlog = structlog.get_config()
    saved_handlers = logging.getLogger().handlers[:]
    logging_config._sentry_capture_warned = False
    yield
    structlog.configure(**saved_structlog)
    logging.getLogger().handlers[:] = saved_handlers
    logging_config._sentry_capture_warned = False


@pytest.fixture(autouse=True)
def _restore_sentry_client():
    # A test that calls sentry_sdk.init installs a process-wide client; without a
    # restore, later tests push envelopes into that dead transport (order-
    # dependent, silently swallowed). Snapshot the client and put it back.
    try:
        import sentry_sdk
    except ImportError:  # pragma: no cover - sentry-sdk is an optional dep
        yield
        return
    saved = sentry_sdk.get_client()
    yield
    current = sentry_sdk.get_client()
    if current is not saved:
        current.close()
        sentry_sdk.get_global_scope().set_client(saved)
