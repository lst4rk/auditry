"""
Structured logging configuration using structlog.

This module provides JSON-formatted logging that integrates with
correlation IDs and is optimized for log aggregators like Datadog.
"""

import logging
import structlog

try:
    import sentry_sdk
except ImportError:  # pragma: no cover - optional dependency
    sentry_sdk = None

_SENTRY_LEVELS = {"error": "error", "exception": "error", "critical": "fatal"}


def _capture_to_sentry(logger, method_name, event_dict):
    """
    Report error-level logs to Sentry before exc_info is flattened to a string.

    JSONRenderer hands stdlib logging a rendered string, so Sentry's
    LoggingIntegration never sees exc_info and falls back to message-based
    events grouped by the JSON blob. Capturing here preserves the exception
    for stacktrace grouping. Sentry's dedupe integration tracks the most
    recently captured exception, so back-to-back captures of the same error
    (e.g. middleware log then error handler log) collapse into one event;
    interleaved errors under concurrency may still occasionally double-report.
    No-op when sentry_sdk is absent or not initialized.
    """
    level = _SENTRY_LEVELS.get(method_name)
    if sentry_sdk is None or level is None:
        return event_dict
    try:
        exc_info = event_dict.get("exc_info")
        if exc_info:
            sentry_sdk.capture_exception(None if exc_info is True else exc_info)
        else:
            sentry_sdk.capture_message(str(event_dict.get("event", "")), level=level)
    except Exception:  # pragma: no cover - reporting must never break logging
        pass
    return event_dict


def configure_logging(level: str = "INFO", sentry_capture: bool = False) -> None:
    """
    Configure application-wide structured logging using structlog.

    Sets up JSON-formatted logging with timestamps, log levels, and
    correlation IDs. Should be called once at application startup.

    Args:
        level: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        sentry_capture: Report error-level logs to Sentry with exc_info
            intact. Consumers enabling this should also disable event-level
            capture in sentry_sdk's LoggingIntegration (event_level=None)
            to avoid duplicate message-based events.
    """
    # Configure structlog processors
    processors = [
        # Add log level to event dict
        structlog.stdlib.add_log_level,
        # Add timestamp in ISO format
        structlog.processors.TimeStamper(fmt="iso"),
        # Add correlation_id from context if available
        structlog.contextvars.merge_contextvars,
    ]
    if sentry_capture and sentry_sdk is not None:
        # Report to Sentry while exc_info is still an exception
        processors.append(_capture_to_sentry)
    processors += [
        # Format exceptions
        structlog.processors.format_exc_info,
        # Render as JSON
        structlog.processors.JSONRenderer(),
    ]
    structlog.configure(
        processors=processors,
        # Use standard library logging
        wrapper_class=structlog.stdlib.BoundLogger,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # Configure standard library logging
    logging.basicConfig(
        format="%(message)s",
        level=getattr(logging, level.upper()),
        force=True,
    )


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    """
    Get a structlog logger instance.

    This logger automatically includes correlation IDs and outputs
    structured JSON logs.

    Args:
        name: Logger name (typically __name__ of the module)

    Returns:
        Configured structlog logger
    """
    return structlog.get_logger(name)