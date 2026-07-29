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
    logging_config._sentry_capture_disabled = False
    yield
    structlog.configure(**saved_structlog)
    logging.getLogger().handlers[:] = saved_handlers
    logging_config._sentry_capture_disabled = False
